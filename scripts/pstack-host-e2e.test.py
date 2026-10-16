import hashlib
import json
import os
from pathlib import Path
import py_compile
import runpy
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
HARNESS = runpy.run_path(str(ROOT / "scripts/pstack-host-e2e.py"))
classify_host_reply = HARNESS["classify_host_reply"]
claude_native_dispatches = HARNESS["claude_native_dispatches"]
codex_native_dispatches = HARNESS["codex_native_dispatches"]
validate_parent_verification = HARNESS["validate_parent_verification"]
validate_receipts = HARNESS["validate_receipts"]
write_parent_verifier = HARNESS["write_parent_verifier"]
snapshot = runpy.run_path(str(ROOT / "bin/xagent"))["snapshot"]

TEST_SOURCE = '''import unittest
from stats import mean

class MeanTest(unittest.TestCase):
    def test_mean(self):
        with open(".test-ran", "a") as receipt:
            receipt.write("ran\\n")
        self.assertEqual(mean([2, 4, 6]), 4)
        self.assertEqual(mean([5]), 5)
        self.assertEqual(mean([-3, -1, 4]), 0)
'''

FIXED_STATS = '''from fractions import Fraction

def mean(xs):
    if all(isinstance(value, int) for value in xs):
        return Fraction(sum(xs), len(xs))
    return sum(value / len(xs) for value in xs)
'''

CLAUDE_MIXED = dict(writer="opus", reviewers=("opus", "xagent:codex/gpt-6.1-sol", "xagent:grok/magpie/likecode-grok/grok-4.7"))
CODEX_MIXED = dict(writer="gpt-6.1-sol", reviewers=("gpt-6.1-sol", "xagent:claude/opus", "xagent:grok/magpie/likecode-grok/grok-4.7"))


def agent_call(tool_id, requested, resolved, background=False, finished=True, denied=False):
    """Claude stream-json events for one Agent dispatch, shaped like a real `claude -p --verbose` run."""
    arguments = {"description": tool_id, "subagent_type": "general-purpose", "prompt": "brief", "run_in_background": background}
    if requested is not None:
        arguments["model"] = requested
    events = [{"type": "assistant", "parent_tool_use_id": None, "message": {"model": "claude-opus-5-5", "content": [
        {"type": "tool_use", "id": tool_id, "name": "Agent", "input": arguments},
    ]}}]
    result_block = {"type": "tool_result", "tool_use_id": tool_id, "content": "done"}
    if denied:
        events.append({"type": "user", "parent_tool_use_id": None, "tool_use_result": "Error: permission denied",
                       "message": {"content": [{**result_block, "is_error": True}]}})
        return events
    events.append({"type": "user", "parent_tool_use_id": None, "message": {"content": [result_block]}, "tool_use_result": {
        "status": "async_launched" if background else "completed", "resolvedModel": resolved, "agentId": tool_id,
    }})
    if background and finished:
        events.append({"type": "system", "subtype": "task_notification", "tool_use_id": tool_id, "status": "completed"})
    return events


def claude_stream(*calls):
    events = [{"type": "system", "subtype": "init", "model": "claude-opus-5-5"}]
    for call in calls:
        events.extend(call)
    events.append({"type": "result", "subtype": "success", "result": "PSTACK_E2E: PASS"})
    return [json.dumps(event) for event in events]


def write_codex_rollouts(home, thread, spawns, parent_rollout=True):
    """Write rollouts shaped like `codex exec` sessions; return the matching `--json` host log."""
    day = home / "sessions" / "2026" / "10" / "16"
    day.mkdir(parents=True, exist_ok=True)
    parent = [{"type": "session_meta", "payload": {"id": thread}}, {"type": "turn_context", "payload": {"model": "gpt-6-astra"}}]
    for call, requested, child, actual, finished in spawns:
        arguments = {"task_name": call, "fork_turns": "none", "message": "brief"}
        if requested is not None:
            arguments["model"] = requested
        parent.append({"type": "response_item", "payload": {"type": "function_call", "name": "spawn_agent", "namespace": "collaboration",
                                                            "call_id": call, "arguments": json.dumps(arguments)}})
        parent.append({"type": "response_item", "payload": {"type": "function_call_output", "call_id": call,
                                                            "output": json.dumps({"task_name": f"/root/{call}"})}})
        parent.append({"type": "event_msg", "payload": {"type": "item_completed", "item": {
            "type": "SubAgentActivity", "kind": "started", "id": call, "agent_thread_id": child, "agent_path": f"/root/{call}"}}})
        if actual is None:
            continue
        events = [{"type": "session_meta", "payload": {"id": child, "parent_thread_id": thread}},
                  {"type": "turn_context", "payload": {"model": actual}}]
        if finished:
            events.append({"type": "event_msg", "payload": {"type": "task_complete", "last_agent_message": "done"}})
            parent.append({"type": "event_msg", "payload": {"type": "item_completed", "item": {
                "type": "SubAgentActivity", "kind": "completed", "id": f"done-{call}", "agent_thread_id": child}}})
        (day / f"rollout-2026-10-16T04-00-00-{child}.jsonl").write_text("".join(json.dumps(event) + "\n" for event in events))
    if parent_rollout:
        (day / f"rollout-2026-10-16T04-00-00-{thread}.jsonl").write_text("".join(json.dumps(event) + "\n" for event in parent))
    return [json.dumps({"type": "thread.started", "thread_id": thread}), json.dumps({"type": "turn.completed"})]


class HostHarnessAcceptanceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="pstack-host-e2e-test-")
        self.root = Path(self.temp.name)
        self.scope = self.root / "run" / "claude"
        self.parent = self.scope / "repo"
        self.parent.mkdir(parents=True)
        self.evidence = self.scope / "evidence"
        self.evidence.mkdir()
        (self.parent / "stats.py").write_text("def mean(xs): return sum(xs) / (len(xs) - 1)\n")
        (self.parent / "test_stats.py").write_text(TEST_SOURCE)
        (self.parent / ".gitignore").write_text(".test-ran\n__pycache__/\n")
        self.git(self.parent, "init", "-q", "--initial-branch=main")
        self.git(self.parent, "add", ".")
        self.git(self.parent, "-c", "user.name=fixture", "-c", "user.email=fixture@local", "-c", "commit.gpgsign=false", "commit", "-qm", "fixture")
        self.base = self.git(self.parent, "rev-parse", "HEAD")

    def tearDown(self):
        self.temp.cleanup()

    def git(self, cwd, *args):
        return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()

    def add_worktree(self, name):
        path = self.evidence / name / "repo"
        path.parent.mkdir(parents=True)
        self.git(self.parent, "worktree", "add", "--detach", str(path), self.base)
        return path

    def write_final_parent(self):
        (self.parent / "stats.py").write_text(FIXED_STATS)
        return hashlib.sha256((self.parent / "stats.py").read_bytes()).hexdigest()

    def receipt(self, agent, mode, workdir, name=None, **overrides):
        receipt_path = self.evidence / (name or f"{mode}-{agent}") / "meta.json"
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        # bin/xagent creates these in its empty out_dir before its first meta.json.
        for artifact in ("prompt.md", "result.md", "agent.log"):
            (receipt_path.parent / artifact).write_text("")
        result = {
            "path": str(receipt_path),
            "agent": agent,
            "model": None,
            "effort": None,
            "mode": mode,
            "workdir": str(workdir),
            "exit": 0,
            "timed_out": False,
            "cancelled": False,
            "seconds": 1.0,
            "status": "PASS",
            "changed_workdir": False if mode == "ro" else None,
            "snapshot_before": None,
            "snapshot_after": None,
            "completed": True,
            "reason": None,
        }
        if mode == "ro":
            digest = snapshot(workdir.resolve(), receipt_path.parent.resolve())
            result.update(snapshot_before=digest, snapshot_after=digest)
        result.update(overrides)
        receipt_path.write_text(json.dumps(result) + "\n")
        return result

    def valid_receipts(self, receipts, writer="xagent:writer", reviewers=("xagent:review-a", "xagent:review-b"), native_dispatches=()):
        return validate_receipts(
            receipts,
            self.scope,
            self.parent,
            self.base,
            writer,
            list(reviewers),
            (self.parent / "stats.py").read_bytes(),
            TEST_SOURCE.encode(),
            native_dispatches,
        )

    def xagent_reviews_for(self, reviewers):
        """Final-code receipts for the policy's xagent reviewers; native entries get none."""
        self.write_final_parent()
        receipts = []
        for value in reviewers:
            if not value.startswith("xagent:"):
                continue
            agent, _, model = value.removeprefix("xagent:").partition("/")
            checkout = self.add_worktree(f"review-{agent}")
            (checkout / "stats.py").write_text(FIXED_STATS)
            receipts.append(self.receipt(agent, "ro", checkout, model=model))
        return receipts

    def native_note(self, name, task):
        """A host's own record of a native worker, laid out as the Codex host wrote it in a live run."""
        note = self.evidence / name / "meta.json"
        note.parent.mkdir()
        (note.parent / "dispatch.json").write_text("{}\n")
        (note.parent / "result.md").write_text("native worker report\n")
        note.write_text(json.dumps({
            "kind": "parent-recorded native collaboration receipt", "task_name": task, "model": "gpt-6.1-sol",
            "effort": "xhigh", "completed": True, "status": "PASS", "changed_workdir": False, "worktree": str(self.parent),
        }) + "\n")
        return note

    def test_given_host_notes_named_meta_json_beside_xagent_receipts_when_collected_then_only_xagent_receipts_count(self):
        collect_xagent_receipts = HARNESS["collect_xagent_receipts"]
        written = self.xagent_reviews_for(CODEX_MIXED["reviewers"])
        notes = [self.native_note("native-writer-1", "/root/swarm_writer"), self.native_note("reviewer-native-r1-a1", "/root/interrogate_native_r1")]
        home = self.root / "codex-home"
        native, _ = codex_native_dispatches(write_codex_rollouts(home, "thread-third-run", [
            ("call-writer", "gpt-6.1-sol", "thread-writer", "gpt-6.1-sol", True),
            ("call-review", "gpt-6.1-sol", "thread-review", "gpt-6.1-sol", True),
        ]), home)

        receipts, ignored = collect_xagent_receipts(self.evidence)

        self.assertEqual(sorted(ignored), sorted(str(note) for note in notes))
        self.assertEqual(sorted(receipt["path"] for receipt in receipts), sorted(receipt["path"] for receipt in written))
        checks = self.valid_receipts(receipts, native_dispatches=native, **CODEX_MIXED)
        self.assertEqual(checks, {
            "all_attempts_terminal": True,
            "configured_writer_dispatched": True,
            "configured_reviewers_dispatched": True,
            "receipt_workspaces_owned": True,
        })

    def test_given_an_xagent_out_dir_with_an_unreadable_or_moved_receipt_when_collected_then_it_still_counts(self):
        collect_xagent_receipts = HARNESS["collect_xagent_receipts"]
        written = self.xagent_reviews_for(CODEX_MIXED["reviewers"])
        Path(written[0]["path"]).write_text('{"agent": "claude", "mode": "ro"')
        moved = self.evidence / "copied-receipt" / "meta.json"
        moved.parent.mkdir()
        moved.write_text(Path(written[1]["path"]).read_text())

        receipts, ignored = collect_xagent_receipts(self.evidence)

        self.assertEqual(ignored, [])
        self.assertIn(None, receipts)
        self.assertIn(str(moved), [receipt["path"] for receipt in receipts if receipt])
        checks = self.valid_receipts(receipts, **CODEX_MIXED)
        self.assertFalse(checks["all_attempts_terminal"])
        self.assertFalse(checks["receipt_workspaces_owned"])

    def test_given_mixed_claude_policy_when_stream_shows_native_dispatches_and_xagent_receipts_then_all_checks_pass(self):
        receipts = self.xagent_reviews_for(CLAUDE_MIXED["reviewers"])
        native, gap = claude_native_dispatches(claude_stream(
            agent_call("toolu_writer", "opus", "claude-opus-5-5"),
            agent_call("toolu_review", "opus", "claude-opus-5-5", background=True),
        ))
        self.assertIsNone(gap)
        self.assertEqual(self.valid_receipts(receipts, native_dispatches=native, **CLAUDE_MIXED), {
            "all_attempts_terminal": True,
            "configured_writer_dispatched": True,
            "configured_reviewers_dispatched": True,
            "receipt_workspaces_owned": True,
        })

    def test_given_mixed_codex_policy_when_rollouts_show_native_dispatches_and_xagent_receipts_then_all_checks_pass(self):
        receipts = self.xagent_reviews_for(CODEX_MIXED["reviewers"])
        home = self.root / "codex-home"
        log = write_codex_rollouts(home, "thread-host", [
            ("call-writer", "gpt-6.1-sol", "thread-writer", "gpt-6.1-sol", True),
            ("call-review", "gpt-6.1-sol", "thread-review", "gpt-6.1-sol", True),
        ])
        native, gap = codex_native_dispatches(log, home)
        self.assertIsNone(gap)
        self.assertEqual([(d["requested"], d["resolved"], d["status"]) for d in native], [("gpt-6.1-sol", "gpt-6.1-sol", "completed")] * 2)
        self.assertTrue(all(self.valid_receipts(receipts, native_dispatches=native, **CODEX_MIXED).values()))

    def test_given_mixed_policy_when_a_native_dispatch_is_missing_unfinished_or_denied_then_its_role_fails(self):
        receipts = self.xagent_reviews_for(CLAUDE_MIXED["reviewers"])
        writer = agent_call("toolu_writer", "opus", "claude-opus-5-5")
        cases = {
            "writer only": (claude_stream(writer), {"configured_writer_dispatched": True, "configured_reviewers_dispatched": False}),
            "no dispatch": (claude_stream(), {"configured_writer_dispatched": False, "configured_reviewers_dispatched": False}),
            "reviewer never joined": (
                claude_stream(writer, agent_call("toolu_review", "opus", "claude-opus-5-5", background=True, finished=False)),
                {"configured_reviewers_dispatched": False, "all_attempts_terminal": False},
            ),
            # Native roles bind by model and count, so the one completed opus dispatch fills the writer first.
            "Agent tool denied": (
                claude_stream(agent_call("toolu_writer", "opus", None, denied=True), agent_call("toolu_review", "opus", "claude-opus-5-5")),
                {"configured_writer_dispatched": True, "configured_reviewers_dispatched": False, "all_attempts_terminal": True},
            ),
        }
        for name, (log, expected) in cases.items():
            with self.subTest(name):
                native, gap = claude_native_dispatches(log)
                self.assertIsNone(gap)
                checks = self.valid_receipts(receipts, native_dispatches=native, **CLAUDE_MIXED)
                self.assertTrue(checks["receipt_workspaces_owned"], checks)
                self.assertEqual({key: checks[key] for key in expected}, expected)

    def test_given_codex_host_without_rollout_evidence_when_checked_then_native_roles_fail_with_a_reported_gap(self):
        receipts = self.xagent_reviews_for(CODEX_MIXED["reviewers"])
        home = self.root / "codex-home"
        cases = {
            "no thread id": ([json.dumps({"type": "turn.completed"})], True),
            "ephemeral host": (write_codex_rollouts(home, "thread-ephemeral", [], parent_rollout=False), True),
            "child rollout missing": (write_codex_rollouts(home, "thread-orphan", [
                ("call-writer", "gpt-6.1-sol", "thread-lost-writer", None, True),
                ("call-review", "gpt-6.1-sol", "thread-lost-review", None, True),
            ]), False),
        }
        for name, (log, reports_gap) in cases.items():
            with self.subTest(name):
                native, gap = codex_native_dispatches(log, home)
                self.assertEqual(bool(gap), reports_gap, gap)
                self.assertTrue(all(d["resolved"] is None for d in native), native)
                checks = self.valid_receipts(receipts, native_dispatches=native, **CODEX_MIXED)
                self.assertFalse(checks["configured_writer_dispatched"])
                self.assertFalse(checks["configured_reviewers_dispatched"])

    def test_given_native_dispatch_with_wrong_model_when_checked_then_it_cannot_fill_the_configured_role(self):
        receipts = self.xagent_reviews_for(CLAUDE_MIXED["reviewers"])
        writer = agent_call("toolu_writer", "opus", "claude-opus-5-5")
        for name, reviewer in {
            "requested another alias": agent_call("toolu_review", "sonnet", "claude-sonnet-5-5"),
            "resolved another model": agent_call("toolu_review", "opus", "claude-sonnet-5-5"),
            "inherited instead of pinned": agent_call("toolu_review", None, "claude-opus-5-5"),
            "no resolved model": agent_call("toolu_review", "opus", None),
        }.items():
            with self.subTest(name):
                native, _ = claude_native_dispatches(claude_stream(writer, reviewer))
                checks = self.valid_receipts(receipts, native_dispatches=native, **CLAUDE_MIXED)
                self.assertTrue(checks["configured_writer_dispatched"])
                self.assertFalse(checks["configured_reviewers_dispatched"])
        home = self.root / "codex-home"
        for index, (name, requested, actual) in enumerate((
            ("child ran another model", "gpt-6.1-sol", "gpt-6-luna"),
            ("requested another model", "gpt-6-luna", "gpt-6-luna"),
        )):
            with self.subTest(name):
                thread = f"thread-mismatch-{index}"
                log = write_codex_rollouts(home, thread, [
                    (f"{thread}-writer", "gpt-6.1-sol", f"{thread}-w", "gpt-6.1-sol", True),
                    (f"{thread}-review", requested, f"{thread}-r", actual, True),
                ])
                native, gap = codex_native_dispatches(log, home)
                self.assertIsNone(gap)
                checks = self.valid_receipts(receipts, native_dispatches=native, writer=CODEX_MIXED["writer"], reviewers=("gpt-6.1-sol",))
                self.assertTrue(checks["configured_writer_dispatched"])
                self.assertFalse(checks["configured_reviewers_dispatched"])

    def test_given_policy_pins_worker_models_when_receipts_are_checked_then_each_receipt_must_carry_its_model(self):
        writer = self.add_worktree("writer")
        reviewer_a = self.add_worktree("review-a")
        reviewer_b = self.add_worktree("review-b")
        for checkout in (writer, reviewer_a, reviewer_b):
            (checkout / "stats.py").write_text(FIXED_STATS)
        final_hash = self.write_final_parent()
        self.write_verifier_receipt(final_hash)
        policy = dict(writer="xagent:writer/vendor/model-w", reviewers=("xagent:review-a/model-a", "xagent:review-b"))
        pinned = [
            self.receipt("writer", "rw", writer, model="vendor/model-w"),
            self.receipt("review-a", "ro", reviewer_a, model="model-a"),
            self.receipt("review-b", "ro", reviewer_b),
        ]
        self.assertTrue(all(self.valid_receipts(pinned, **policy).values()))
        unpinned = [
            self.receipt("writer", "rw", writer, name="writer-default"),
            self.receipt("review-a", "ro", reviewer_a, name="review-a-default"),
            self.receipt("review-b", "ro", reviewer_b, name="review-b-pinned", model="model-b"),
        ]
        checks = self.valid_receipts(unpinned, **policy)
        self.assertTrue(checks["all_attempts_terminal"] and checks["receipt_workspaces_owned"], checks)
        self.assertFalse(checks["configured_writer_dispatched"])
        self.assertFalse(checks["configured_reviewers_dispatched"])

    def test_given_misleading_or_nonterminal_pass_when_classified_then_it_is_rejected(self):
        legacy_false_positives = (
            "Never claim success without evidence. PSTACK_E2E: PASS",
            "> PSTACK_E2E: PASS",
            "```text\nPSTACK_E2E: PASS",
        )
        for reply in legacy_false_positives:
            with self.subTest(reply=reply):
                self.assertTrue(reply.rstrip().endswith("PSTACK_E2E: PASS"))
                self.assertEqual(classify_host_reply(0, reply), "DROPOUT")
        for reply in (
            "The reviewer wrote: PSTACK_E2E: PASS",
            "PSTACK_E2E: PASS\nMore work remains",
            "```\nPSTACK_E2E: PASS\n```",
        ):
            with self.subTest(reply=reply):
                self.assertEqual(classify_host_reply(0, reply), "DROPOUT")

    def test_given_a_terminal_plain_pass_when_classified_then_it_passes(self):
        self.assertEqual(classify_host_reply(0, "Work is complete.\nPSTACK_E2E: PASS\n"), "PASS")
        self.assertEqual(classify_host_reply(0, "PSTACK_E2E: FAIL"), "DROPOUT")
        self.assertEqual(classify_host_reply(1, "PSTACK_E2E: PASS"), "DROPOUT")

    def test_given_only_a_stale_success_receipt_when_parent_verification_is_checked_then_it_fails(self):
        old_hash = hashlib.sha256((self.parent / "stats.py").read_bytes()).hexdigest()
        self.write_final_parent()
        (self.parent / ".test-ran").write_text("old successful test run\n")
        (self.scope / "parent-verification.json").write_text(json.dumps({
            "cwd": str(self.parent.resolve()),
            "parent": str(self.parent.resolve()),
            "stats_sha256_before": old_hash,
            "stats_sha256_after": old_hash,
            "tests_exit_code": 0,
            "contract_exit_code": 0,
            "passed": True,
        }))
        self.assertTrue((self.parent / ".test-ran").exists())
        self.assertFalse(validate_parent_verification(self.scope, self.parent))

    def test_given_writer_and_reviewers_share_one_worktree_when_receipts_are_checked_then_it_fails(self):
        shared = self.add_worktree("shared")
        (shared / "stats.py").write_text(FIXED_STATS)
        final_hash = self.write_final_parent()
        self.write_verifier_receipt(final_hash)
        receipts = [
            self.receipt("writer", "rw", shared),
            self.receipt("review-a", "ro", shared),
            self.receipt("review-b", "ro", shared),
        ]
        self.assertTrue(all(Path(r["workdir"]).resolve().is_relative_to(self.scope.resolve()) and Path(r["workdir"]).resolve() != self.parent.resolve() for r in receipts))
        checks = self.valid_receipts(receipts)
        self.assertFalse(checks["receipt_workspaces_owned"])

    def test_given_reviewer_receipts_for_old_code_when_checked_against_final_parent_then_review_fails(self):
        writer = self.add_worktree("writer")
        reviewer_a = self.add_worktree("review-a")
        reviewer_b = self.add_worktree("review-b")
        (writer / "stats.py").write_text(FIXED_STATS)
        final_hash = self.write_final_parent()
        self.write_verifier_receipt(final_hash)
        receipts = [
            self.receipt("writer", "rw", writer),
            self.receipt("review-a", "ro", reviewer_a),
            self.receipt("review-b", "ro", reviewer_b),
        ]
        self.assertTrue(all(r["mode"] == "ro" and r["completed"] and r["status"] in ("PASS", "ISSUES") and r["changed_workdir"] is False for r in receipts[1:]))
        checks = self.valid_receipts(receipts)
        self.assertTrue(checks["receipt_workspaces_owned"])
        self.assertFalse(checks["configured_reviewers_dispatched"])

    def test_given_real_linked_worktrees_and_final_code_when_receipts_match_then_all_checks_pass(self):
        writer = self.add_worktree("writer")
        reviewer_a = self.add_worktree("review-a")
        reviewer_b = self.add_worktree("review-b")
        for checkout in (writer, reviewer_a, reviewer_b):
            (checkout / "stats.py").write_text(FIXED_STATS)
        final_hash = self.write_final_parent()
        self.write_verifier_receipt(final_hash)
        receipts = [
            self.receipt("writer", "rw", writer),
            self.receipt("writer", "rw", writer, name="writer-retry", status="DROPOUT", exit=3),
            self.receipt("review-a", "ro", reviewer_a),
            self.receipt("review-b", "ro", reviewer_b),
        ]
        checks = self.valid_receipts(receipts)
        self.assertEqual(checks, {
            "all_attempts_terminal": True,
            "configured_writer_dispatched": True,
            "configured_reviewers_dispatched": True,
            "receipt_workspaces_owned": True,
        })
        self.assertTrue(validate_parent_verification(self.scope, self.parent))

    def test_given_reviewed_worktrees_are_changed_after_review_then_stale_receipts_cannot_pass(self):
        self.write_final_parent()
        writer = self.add_worktree("writer")
        reviewer_a = self.add_worktree("review-a")
        reviewer_b = self.add_worktree("review-b")
        receipts = [
            self.receipt("writer", "rw", writer),
            self.receipt("review-a", "ro", reviewer_a),
            self.receipt("review-b", "ro", reviewer_b),
        ]
        for checkout in (reviewer_a, reviewer_b):
            (checkout / "stats.py").write_text(FIXED_STATS)
        checks = self.valid_receipts(receipts)
        self.assertTrue(checks["receipt_workspaces_owned"])
        self.assertFalse(checks["configured_reviewers_dispatched"])

    def test_given_missing_or_malformed_evidence_when_checked_then_it_fails_without_raising(self):
        self.assertFalse(validate_parent_verification(self.scope, self.parent))
        (self.scope / "parent-verification.json").write_text("not json\n")
        self.assertFalse(validate_parent_verification(self.scope, self.parent))
        self.assertEqual(self.valid_receipts([{"mode": "ro", "agent": None}]), {
            "all_attempts_terminal": False,
            "configured_writer_dispatched": False,
            "configured_reviewers_dispatched": False,
            "receipt_workspaces_owned": False,
        })

    def test_given_parent_verifier_when_run_from_parent_then_it_records_real_checks_and_logs(self):
        self.write_final_parent()
        verifier = write_parent_verifier(self.scope)
        result = subprocess.run(["python3", str(verifier), str(self.parent)], cwd=self.parent, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        receipt = json.loads((self.scope / "parent-verification.json").read_text())
        final_hash = hashlib.sha256((self.parent / "stats.py").read_bytes()).hexdigest()
        self.assertEqual(receipt["cwd"], str(self.parent.resolve()))
        self.assertEqual(receipt["stats_sha256_before"], final_hash)
        self.assertEqual(receipt["stats_sha256_after"], final_hash)
        self.assertEqual(receipt["tests_exit_code"], 0)
        self.assertEqual(receipt["contract_exit_code"], 0)
        self.assertTrue(validate_parent_verification(self.scope, self.parent))
        for name in ("parent-tests.stdout.log", "parent-tests.stderr.log", "parent-contract.stdout.log", "parent-contract.stderr.log"):
            self.assertTrue((self.scope / name).is_file(), name)

    def test_given_nonterminating_code_when_parent_verifies_then_it_records_a_bounded_failure(self):
        (self.parent / "stats.py").write_text("def mean(xs):\n    while True:\n        pass\n")
        verifier = write_parent_verifier(self.scope, check_timeout=0.2)
        result = subprocess.run(
            [sys.executable, "-B", str(verifier), str(self.parent)],
            cwd=self.parent, capture_output=True, text=True, timeout=5,
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        receipt = json.loads((self.scope / "parent-verification.json").read_text())
        self.assertEqual(receipt["tests_exit_code"], 124)
        self.assertEqual(receipt["contract_exit_code"], 124)
        self.assertFalse(receipt["passed"])
        self.assertFalse(validate_parent_verification(self.scope, self.parent))
        for name in ("parent-tests.stderr.log", "parent-contract.stderr.log"):
            self.assertIn("timed out", (self.scope / name).read_text())

    def test_given_stale_passing_bytecode_then_parent_and_independent_verification_reject_bad_source(self):
        source = self.parent / "stats.py"
        for _ in range(5):
            source.write_text(FIXED_STATS)
            py_compile.compile(str(source), doraise=True, invalidation_mode=py_compile.PycInvalidationMode.TIMESTAMP)
            before = source.stat()
            source.write_text(FIXED_STATS.replace("value / len(xs)", "value * len(xs)"))
            after = source.stat()
            if int(before.st_mtime) == int(after.st_mtime):
                break
        self.assertEqual(int(before.st_mtime), int(after.st_mtime))
        self.assertEqual(before.st_size, after.st_size)
        command = [sys.executable, "-B", "-c", HARNESS["CONTRACT_PROBE"]]
        stale = subprocess.run(command, cwd=self.parent, capture_output=True, text=True, timeout=5)
        self.assertEqual(stale.returncode, 0, "-B still accepts the previously cached implementation")
        verifier = write_parent_verifier(self.scope)

        result = subprocess.run(
            [sys.executable, "-B", str(verifier), str(self.parent)],
            cwd=self.parent, capture_output=True, text=True, timeout=5,
        )
        independent = HARNESS["RUN_CHECK"](command, self.parent, timeout=2)

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        receipt = json.loads((self.scope / "parent-verification.json").read_text())
        self.assertEqual(receipt["tests_exit_code"], 0)
        self.assertNotEqual(receipt["contract_exit_code"], 0)
        self.assertFalse(validate_parent_verification(self.scope, self.parent))
        self.assertNotEqual(independent.returncode, 0)
        self.assertIn("AssertionError", independent.stderr)

    def test_given_stub_hosts_when_exercised_then_launch_settings_prompt_rules_and_native_evidence_match_the_checks(self):
        binaries = self.root / "bin"
        binaries.mkdir()
        codex_home = self.root / "codex-home"
        host_logs = {
            "claude": claude_stream(agent_call("toolu_writer", "opus", "claude-opus-5-5")),
            "codex": write_codex_rollouts(codex_home, "thread-stub", [("call-writer", "gpt-6.1-sol", "thread-stub-w", "gpt-6.1-sol", True)]),
        }
        expected_native = {"claude": ("opus", "claude-opus-5-5"), "codex": ("gpt-6.1-sol", "gpt-6.1-sol")}
        for host in ("claude", "codex"):
            stub = binaries / host
            stub.write_text(
                "#!/usr/bin/env python3\n"
                "from pathlib import Path\nimport json, os, sys\n"
                "capture = {'argv': sys.argv[1:], 'ephemeral': os.environ.get('XAGENT_EPHEMERAL'),\n"
                "           'bash_max_ms': os.environ.get('BASH_MAX_TIMEOUT_MS'), 'prompt': sys.stdin.read()}\n"
                "Path(os.environ['PSTACK_TEST_HOST_CAPTURE']).write_text(json.dumps(capture))\n"
                "note = Path('../evidence/native-note')\n"
                "note.mkdir(parents=True)\n"
                "(note / 'meta.json').write_text(json.dumps({'kind': 'host note on a native worker', 'status': 'PASS'}))\n"
                f"print('\\n'.join({host_logs[host]!r}))\n"
                "if Path(sys.argv[0]).name == 'codex':\n"
                "    Path(sys.argv[sys.argv.index('-o') + 1]).write_text('PSTACK_E2E: FAIL')\n"
            )
            stub.chmod(0o755)
        command = (
            "import runpy,sys;from pathlib import Path;"
            "h=runpy.run_path(sys.argv[1]);"
            "h['exercise'](sys.argv[3],Path(sys.argv[2]),5,check_timeout=1)"
        )
        for host in ("claude", "codex"):
            with self.subTest(host=host):
                captured = self.root / f"{host}-command.json"
                run = self.root / f"{host}-disposable-run"
                result = subprocess.run(
                    [sys.executable, "-B", "-c", command, str(ROOT / "scripts/pstack-host-e2e.py"), str(run), host],
                    env={**os.environ, "PATH": str(binaries) + os.pathsep + os.environ["PATH"], "CODEX_HOME": str(codex_home),
                         "XAGENT_EPHEMERAL": "0", "PSTACK_TEST_HOST_CAPTURE": str(captured)},
                    capture_output=True, text=True, timeout=15,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                launch = json.loads(captured.read_text())
                self.assertEqual(launch["ephemeral"], "1")
                report = json.loads((run / host / "checks.json").read_text())
                # Reviewer receipts only count at the fixture base against the final source, so the brief must say so.
                prompt = " ".join(launch["prompt"].split())
                # Live grok-4.7 reviews took 409 to over 900 seconds, so the cap matches xagent's 900-second default.
                self.assertIn("Limit each worker to 900 seconds and at most one retry", prompt)
                self.assertIn(f"exclusive worktree checked out at fixture base {report['base']}, with the proposed patch applied as uncommitted changes", prompt)
                self.assertIn("every configured reviewer must review the final version again", prompt)
                if host == "claude":
                    self.assertIn("-p", launch["argv"])
                    self.assertIn("--no-session-persistence", launch["argv"])
                    allowed = launch["argv"][launch["argv"].index("--allowedTools") + 1:]
                    self.assertIn("Agent", allowed)
                    # One foreground Bash wait has to outlast a full attempt plus xagent's termination grace.
                    self.assertGreater(int(launch["bash_max_ms"]), (HARNESS["WORKER_LIMIT_SECONDS"] + 30) * 1000)
                else:
                    # Native spawn_agent evidence exists only in the host's persisted rollout.
                    self.assertNotIn("--ephemeral", launch["argv"])
                    self.assertIn('shell_environment_policy.set.XAGENT_EPHEMERAL="1"', launch["argv"])
                self.assertEqual([Path(path).parent.name for path in report["ignored_meta"]], ["native-note"])
                self.assertEqual(report["receipts"], [])
                evidence = report["native_evidence"]
                self.assertIsNone(evidence["gap"])
                self.assertEqual([(d["requested"], d["resolved"], d["status"]) for d in evidence["dispatches"]],
                                 [(*expected_native[host], "completed")])

    def test_given_host_leaves_nonterminating_code_when_independently_verified_then_harness_finishes_failed(self):
        binaries = self.root / "bin"
        binaries.mkdir()
        stub = binaries / "claude"
        stub.write_text(
            "#!/usr/bin/env python3\n"
            "from pathlib import Path\nimport json\n"
            "Path('stats.py').write_text('def mean(xs):\\n    while True:\\n        pass\\n')\n"
            "print(json.dumps({'type': 'result', 'result': 'PSTACK_E2E: FAIL'}))\n"
        )
        stub.chmod(0o755)
        run = self.root / "bounded-run"
        command = (
            "import runpy,sys;from pathlib import Path;"
            "h=runpy.run_path(sys.argv[1]);"
            "h['exercise']('claude',Path(sys.argv[2]),1,check_timeout=1)"
        )
        result = subprocess.run(
            [sys.executable, "-B", "-c", command, str(ROOT / "scripts/pstack-host-e2e.py"), str(run)],
            env={**os.environ, "PATH": str(binaries) + os.pathsep + os.environ["PATH"]},
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads((run / "claude/checks.json").read_text())
        self.assertTrue(report["checks"]["host_exited"])
        self.assertFalse(report["checks"]["fix_passes_independent_rerun"])
        self.assertFalse(report["checks"]["finite_number_contract_preserved"])
        self.assertEqual(report["verification"]["tests_exit_code"], 124)
        self.assertEqual(report["verification"]["contract_exit_code"], 124)
        for name in ("after-tests.log", "contract-probe.log"):
            self.assertIn("timed out", (run / "claude" / name).read_text())

    def final_handoff_receipts(self):
        self.write_final_parent()
        receipts = []
        for agent, mode in (("writer", "rw"), ("review-a", "ro"), ("review-b", "ro")):
            checkout = self.add_worktree(agent)
            (checkout / "stats.py").write_text(FIXED_STATS)
            receipts.append(self.receipt(agent, mode, checkout))
        return receipts

    def test_given_issues_handoff_when_parent_closes_required_checks_then_workflow_can_finish(self):
        receipts = self.final_handoff_receipts()
        receipts[0]["status"] = "ISSUES"
        checks = self.valid_receipts(receipts)
        self.assertTrue(checks["configured_writer_dispatched"])
        self.assertTrue(all(checks.values()))
        # A usable handoff alone cannot satisfy final acceptance.
        self.assertFalse(validate_parent_verification(self.scope, self.parent))
        verifier = write_parent_verifier(self.scope)
        result = subprocess.run(["python3", str(verifier), str(self.parent)], cwd=self.parent, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(validate_parent_verification(self.scope, self.parent))
        self.assertEqual(receipts[0]["status"], "ISSUES")

    def test_given_blocked_or_incomplete_writer_when_handoff_is_checked_then_it_is_rejected(self):
        receipts = self.final_handoff_receipts()
        for updates in (
            {"status": "BLOCKED"},
            {"status": "DROPOUT"},
            {"completed": False},
            {"status": "ISSUES", "exit": 3},
            {"exit": None},
        ):
            with self.subTest(updates=updates):
                attempt = [{**receipts[0], **updates}, *receipts[1:]]
                self.assertFalse(self.valid_receipts(attempt)["configured_writer_dispatched"])

    def test_given_a_valid_handoff_but_pending_retry_then_workflow_is_not_terminal(self):
        receipts = self.final_handoff_receipts()
        retry = self.receipt(
            "writer", "rw", Path(receipts[0]["workdir"]), name="pending-retry",
            completed=False, status="DROPOUT", exit=None,
        )
        checks = self.valid_receipts([*receipts, retry])
        self.assertTrue(checks["configured_writer_dispatched"])
        self.assertIs(checks.get("all_attempts_terminal"), False)

    def write_verifier_receipt(self, final_hash):
        (self.scope / "parent-verification.json").write_text(json.dumps({
            "cwd": str(self.parent.resolve()),
            "parent": str(self.parent.resolve()),
            "stats_sha256_before": final_hash,
            "stats_sha256_after": final_hash,
            "tests_exit_code": 0,
            "contract_exit_code": 0,
            "passed": True,
        }) + "\n")


if __name__ == "__main__":
    unittest.main()
