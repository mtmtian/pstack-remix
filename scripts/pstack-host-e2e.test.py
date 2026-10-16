import hashlib
import json
import os
from pathlib import Path
import py_compile
import re
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
XAGENT = runpy.run_path(str(ROOT / "bin/xagent"))
agent_spec = XAGENT["agent_spec"]
snapshot = XAGENT["snapshot"]

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

STALE_STATS = "def mean(xs):\n    return sum(xs) / len(xs)\n"

ALL_CHECKS_PASS = {
    "all_attempts_terminal": True,
    "configured_writer_dispatched": True,
    "configured_reviewers_dispatched": True,
    "receipt_workspaces_owned": True,
}
CLAUDE_MIXED = dict(writer="opus", reviewers=("opus", "xagent:codex/gpt-6.1-sol", "xagent:grok/magpie/likecode-grok/grok-4.7"))
CODEX_MIXED = dict(writer="gpt-6.1-sol", reviewers=("gpt-6.1-sol", "xagent:claude/opus", "xagent:grok/magpie/likecode-grok/grok-4.7"))


def agent_call(tool_id, requested, resolved, background=False, finished=True, denied=False, prompt="brief", tools=(), effort=None):
    """Claude stream-json events for one Agent dispatch, shaped like a real `claude -p --verbose` run."""
    arguments = {"description": tool_id, "subagent_type": "general-purpose", "prompt": prompt, "run_in_background": background}
    if requested is not None:
        arguments["model"] = requested
    if effort is not None:
        arguments["effort"] = effort
    events = [{"type": "assistant", "parent_tool_use_id": None, "message": {"model": "claude-opus-5-5", "content": [
        {"type": "tool_use", "id": tool_id, "name": "Agent", "input": arguments},
    ]}}]
    # The subagent's own tool calls stream under the Agent call's id, for foreground and background agents alike.
    events += [{"type": "assistant", "parent_tool_use_id": tool_id, "message": {"content": [
        {"type": "tool_use", "id": f"{tool_id}-{index}", "name": name, "input": arguments}]}} for index, (name, arguments) in enumerate(tools)]
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


def works_in(checkout):
    """A subagent's own read-only tool calls inside checkout."""
    return [("Bash", {"command": f"cd {checkout} && git diff"}), ("Read", {"file_path": f"{checkout}/stats.py"})]


def writes_in(checkout):
    """A subagent's tool calls that also edit a file in checkout."""
    return [*works_in(checkout), ("Edit", {"file_path": f"{checkout}/stats.py"})]


def edits(path):
    """A Codex child's apply_patch on path, recorded as a FileChange item."""
    return ("edit", str(path))


def claude_stream(*calls):
    events = [{"type": "system", "subtype": "init", "model": "claude-opus-5-5"}]
    for call in calls:
        events.extend(call)
    events.append({"type": "result", "subtype": "success", "result": "PSTACK_E2E: PASS"})
    return [json.dumps(event) for event in events]


def write_codex_rollouts(home, thread, spawns, parent_rollout=True, effort=None):
    """Write rollouts shaped like `codex exec` sessions; return the matching `--json` host log.

    Each spawn is (call, requested model, child thread, model the child ran, finished, *actions), where an action
    is a shell command the child ran or edits(path).
    """
    day = home / "sessions" / "2026" / "10" / "16"
    day.mkdir(parents=True, exist_ok=True)
    parent = [{"type": "session_meta", "payload": {"id": thread}}, {"type": "turn_context", "payload": {"model": "gpt-6-astra"}}]
    for call, requested, child, actual, finished, *actions in spawns:
        arguments = {"task_name": call, "fork_turns": "none", "message": "brief"}
        if requested is not None:
            arguments["model"] = requested
        if effort is not None:
            arguments["reasoning_effort"] = effort
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
        for index, action in enumerate(actions):
            if isinstance(action, tuple):
                events.append({"type": "event_msg", "payload": {"type": "item_completed", "item": {
                    "type": "FileChange", "changes": {action[1]: {"type": "update", "unified_diff": "+fix"}}, "status": "completed"}}})
                continue
            events.append({"type": "response_item", "payload": {"type": "custom_tool_call", "name": "exec", "call_id": f"{child}-{index}",
                                                                 "input": f"text(await tools.exec_command({{cmd:{json.dumps(action)}}}))"}})
            events.append({"type": "event_msg", "payload": {"type": "item_completed", "item": {
                "type": "CommandExecution", "command": ["/bin/zsh", "-lc", action], "status": "completed"}}})
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

    def valid_receipts(self, receipts, writer="xagent:codex", reviewers=("xagent:claude", "xagent:grok"), native_dispatches=(), effort=None):
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
            effort,
        )

    def final_checkout(self, name, stats=FIXED_STATS):
        """A reviewer worktree at the fixture base with stats.py changed but uncommitted."""
        checkout = self.add_worktree(name)
        (checkout / "stats.py").write_text(stats)
        return checkout

    def committed_checkout(self, name):
        """A writer worktree whose patch is committed, so it has left the fixture base."""
        checkout = self.final_checkout(name)
        self.git(checkout, "-c", "user.name=fixture", "-c", "user.email=fixture@local", "-c", "commit.gpgsign=false", "commit", "-qam", "writer commit")
        return checkout

    def codex_writes(self, checkout):
        return (f"cd {checkout} && git diff", edits(checkout / "stats.py"))

    def xagent_reviews_for(self, reviewers):
        """Final-code receipts for the policy's xagent reviewers; native entries get none."""
        self.write_final_parent()
        receipts = []
        for value in reviewers:
            if not value.startswith("xagent:"):
                continue
            agent, model = agent_spec(value.removeprefix("xagent:"))
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
            ("call-writer", "gpt-6.1-sol", "thread-writer", "gpt-6.1-sol", True, *self.codex_writes(self.committed_checkout("writer-1"))),
            ("call-review", "gpt-6.1-sol", "thread-review", "gpt-6.1-sol", True, f"cat {self.final_checkout('reviewer-native-r1')}/stats.py"),
        ]), home)

        receipts, ignored = collect_xagent_receipts(self.evidence)

        self.assertEqual(sorted(ignored), sorted(str(note) for note in notes))
        self.assertEqual(sorted(receipt["path"] for receipt in receipts), sorted(receipt["path"] for receipt in written))
        checks = self.valid_receipts(receipts, native_dispatches=native, **CODEX_MIXED)
        self.assertEqual(checks, ALL_CHECKS_PASS)

    def test_given_an_unreadable_receipt_in_an_xagent_out_dir_and_a_copy_elsewhere_when_collected_then_only_the_copy_is_ignored(self):
        collect_xagent_receipts = HARNESS["collect_xagent_receipts"]
        written = self.xagent_reviews_for(CODEX_MIXED["reviewers"])
        Path(written[0]["path"]).write_text('{"agent": "claude", "mode": "ro"')
        copied = self.evidence / "copied-receipt" / "meta.json"
        copied.parent.mkdir()
        copied.write_text(Path(written[1]["path"]).read_text())

        receipts, ignored = collect_xagent_receipts(self.evidence)

        self.assertEqual(ignored, [str(copied)])
        self.assertIn(None, receipts)
        self.assertEqual(len(receipts), len(written))
        checks = self.valid_receipts(receipts, **CODEX_MIXED)
        self.assertFalse(checks["all_attempts_terminal"])
        self.assertFalse(checks["receipt_workspaces_owned"])

    def test_given_mixed_claude_policy_when_stream_shows_native_dispatches_and_xagent_receipts_then_all_checks_pass(self):
        receipts = self.xagent_reviews_for(CLAUDE_MIXED["reviewers"])
        native, gap = claude_native_dispatches(claude_stream(
            self.native_writer(self.committed_checkout("writer-native")),
            agent_call("toolu_review", "opus", "claude-opus-5-5", background=True, tools=works_in(self.final_checkout("review-native"))),
        ))
        self.assertIsNone(gap)
        self.assertEqual(self.valid_receipts(receipts, native_dispatches=native, **CLAUDE_MIXED), ALL_CHECKS_PASS)

    def test_given_mixed_codex_policy_when_rollouts_show_native_dispatches_and_xagent_receipts_then_all_checks_pass(self):
        receipts = self.xagent_reviews_for(CODEX_MIXED["reviewers"])
        home = self.root / "codex-home"
        log = write_codex_rollouts(home, "thread-host", [
            ("call-writer", "gpt-6.1-sol", "thread-writer", "gpt-6.1-sol", True, *self.codex_writes(self.committed_checkout("writer-native"))),
            ("call-review", "gpt-6.1-sol", "thread-review", "gpt-6.1-sol", True, f"git -C {self.final_checkout('review-native')} diff"),
        ])
        native, gap = codex_native_dispatches(log, home)
        self.assertIsNone(gap)
        self.assertEqual([(d["requested"], d["resolved"], d["status"]) for d in native], [("gpt-6.1-sol", "gpt-6.1-sol", "completed")] * 2)
        self.assertTrue(all(self.valid_receipts(receipts, native_dispatches=native, **CODEX_MIXED).values()))

    def test_given_an_all_native_policy_when_every_agent_call_completes_then_no_xagent_receipt_is_required(self):
        self.write_final_parent()
        native, gap = claude_native_dispatches(claude_stream(self.native_writer(self.committed_checkout("writer-native")), *(
            agent_call(f"toolu_review_{index}", "opus", "claude-opus-5-5", tools=works_in(self.final_checkout(f"review-{index}"))) for index in range(2))))
        self.assertIsNone(gap)
        self.assertEqual(self.valid_receipts([], native_dispatches=native, writer="opus", reviewers=("opus", "opus")), ALL_CHECKS_PASS)

    def test_given_one_agent_with_two_models_sharing_a_reviewer_worktree_when_checked_then_ownership_fails(self):
        shared = self.add_worktree("shared-claude")
        (shared / "stats.py").write_text(FIXED_STATS)
        self.write_final_parent()
        receipts = [
            self.receipt("claude", "ro", shared, name="claude-default"),
            self.receipt("claude", "ro", shared, name="claude-opus", model="opus"),
        ]
        native, _ = claude_native_dispatches(claude_stream(self.native_writer(self.committed_checkout("writer-native"))))
        checks = self.valid_receipts(receipts, native_dispatches=native, writer="opus", reviewers=("xagent:claude", "xagent:claude/opus"))
        self.assertTrue(checks["configured_reviewers_dispatched"], checks)
        self.assertFalse(checks["receipt_workspaces_owned"])

    def test_given_entries_xagent_would_reject_when_checked_then_they_fill_no_role(self):
        writer = self.add_worktree("writer")
        reviewer = self.add_worktree("review-grok")
        for checkout in (writer, reviewer):
            (checkout / "stats.py").write_text(FIXED_STATS)
        self.write_final_parent()
        review = self.receipt("grok", "ro", reviewer)
        for index, (entry, agent, model) in enumerate((("xagent:nobody", "nobody", None), ("xagent:claude/-bad", "claude", "-bad"))):
            with self.subTest(entry):
                receipts = [self.receipt(agent, "rw", writer, name=f"rw-{index}", model=model), review]
                self.assertFalse(self.valid_receipts(receipts, writer=entry, reviewers=("xagent:grok",))["configured_writer_dispatched"])

    def test_given_codex_reports_a_claude_style_model_id_when_checked_then_only_claude_resolves_aliases(self):
        self.write_final_parent()
        home = self.root / "codex-home"
        writer_checkout = self.committed_checkout("writer-native")
        codex, gap = codex_native_dispatches(write_codex_rollouts(home, "thread-alias", [
            ("call-writer", "opus", "thread-alias-w", "claude-opus-5-5", True, *self.codex_writes(writer_checkout))]), home)
        self.assertIsNone(gap)
        claude, _ = claude_native_dispatches(claude_stream(self.native_writer(writer_checkout)))
        self.assertFalse(self.valid_receipts([], native_dispatches=codex, writer="opus", reviewers=())["configured_writer_dispatched"])
        self.assertTrue(self.valid_receipts([], native_dispatches=claude, writer="opus", reviewers=())["configured_writer_dispatched"])

    def test_given_a_policy_without_swarm_or_interrogate_entries_when_roles_resolve_then_the_helper_defaults_apply(self):
        shown = json.loads(subprocess.check_output(
            ["node", str(ROOT / "bin/config.mjs"), "show", "--host", "claude", "--config", str(self.root / "absent.json")], text=True))
        effective = shown["effective"]
        self.assertEqual(HARNESS["expected_roles"](effective), (effective["defaultModel"], effective["defaultPanel"]))

    def test_given_claude_native_reviews_when_their_subagents_work_in_checkouts_then_only_one_final_checkout_at_the_base_counts(self):
        self.write_final_parent()
        final = self.final_checkout("review-final")
        stale = self.final_checkout("review-stale", stats=STALE_STATS)
        committed = self.committed_checkout("review-committed")
        brief = self.scope / "briefs" / "review.md"
        brief.parent.mkdir()
        brief.write_text(f"Your exclusive read-only worktree: {stale}\n")
        writer = self.native_writer(self.committed_checkout("writer-native"))
        for name, tools, counted in (
            ("final checkout", works_in(final), True),
            ("brief outside any checkout, then the final checkout", [("Read", {"file_path": str(brief)}), *works_in(final)], True),
            ("parent checkout and the final checkout", [("Bash", {"command": f"git -C {self.parent} status"}), *works_in(final)], True),
            ("checkout reviewed before the last change", works_in(stale), False),
            ("checkout moved off the fixture base", works_in(committed), False),
            ("final and stale checkouts", [*works_in(final), *works_in(stale)], False),
            ("final checkout it edited", writes_in(final), False),
            ("relative and missing paths only", [("Bash", {"command": "cat stats.py"}), ("Read", {"file_path": f"{final}/notes/missing.md"})], False),
        ):
            with self.subTest(name):
                native, _ = claude_native_dispatches(claude_stream(writer, agent_call("toolu_review", "opus", "claude-opus-5-5", tools=tools)))
                checks = self.valid_receipts([], native_dispatches=native, writer="opus", reviewers=("opus",))
                self.assertTrue(checks["configured_writer_dispatched"])
                self.assertEqual(checks["configured_reviewers_dispatched"], counted)

    def test_given_codex_native_reviews_when_their_own_commands_name_checkouts_then_only_a_final_version_counts(self):
        # Codex encrypts the task payload in both rollouts, so the child's own commands show where it reviewed.
        self.write_final_parent()
        final = self.final_checkout("review-final")
        stale = self.final_checkout("review-stale", stats=STALE_STATS)
        writer_checkout = self.committed_checkout("writer-native")
        home = self.root / "codex-home"
        for index, (name, commands, counted) in enumerate((
            ("final checkout", [f"git -C {final} diff"], True),
            ("checkout reviewed before the last change", [f"sed -n 1,40p {stale}/stats.py"], False),
            ("no command", [], False),
        )):
            with self.subTest(name):
                thread = f"thread-bind-{index}"
                # The review comes first, so the writer must not take the only attempt that can review.
                native, gap = codex_native_dispatches(write_codex_rollouts(home, thread, [
                    (f"{thread}-review", "gpt-6.1-sol", f"{thread}-r", "gpt-6.1-sol", True, *commands),
                    (f"{thread}-writer", "gpt-6.1-sol", f"{thread}-w", "gpt-6.1-sol", True, *self.codex_writes(writer_checkout)),
                ]), home)
                self.assertIsNone(gap)
                checks = self.valid_receipts([], native_dispatches=native, writer="gpt-6.1-sol", reviewers=("gpt-6.1-sol",))
                self.assertTrue(checks["configured_writer_dispatched"])
                self.assertEqual(checks["configured_reviewers_dispatched"], counted)

    def test_given_default_limits_when_the_host_deadline_is_chosen_then_six_full_attempts_and_the_parent_checks_fit(self):
        result = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/pstack-host-e2e.py"), "--help"], capture_output=True, text=True, timeout=30)
        default = int(re.search(r"default: (\d+)", " ".join(result.stdout.split())).group(1))
        # Writer, review and re-review rounds may each retry once; every attempt can run to its limit plus xagent's grace.
        attempts = 3 * 2 * (XAGENT["DEFAULT_TIMEOUT"] + XAGENT["TERMINATION_GRACE"])
        self.assertGreater(default, attempts + 2 * 30)

    def test_given_an_xagent_out_dir_missing_one_marker_when_collected_then_its_broken_receipt_still_fails(self):
        out = self.evidence / "interrupted-attempt"
        out.mkdir()
        (out / "prompt.md").write_text("brief\n")
        (out / "meta.json").write_text('{"agent": "grok", "mode": "ro", "completed": fal')
        receipts, ignored = HARNESS["collect_xagent_receipts"](self.evidence)
        self.assertEqual((receipts, ignored), ([None], []))
        self.assertFalse(self.valid_receipts(receipts, writer="opus", reviewers=("opus",))["all_attempts_terminal"])

    # Scenarios A-E from the second review round: a native review is bound by its subagent's own tool calls.
    def native_writer(self, checkout, prompt=None):
        return agent_call("toolu_writer", "opus", "claude-opus-5-5", prompt=prompt or f"Fix stats.py in {checkout}.", tools=writes_in(checkout))

    def test_given_a_native_writer_and_an_unrelated_agent_call_when_nothing_was_reviewed_then_the_review_slot_stays_empty(self):
        self.write_final_parent()
        writer_checkout = self.final_checkout("writer-native")
        native, _ = claude_native_dispatches(claude_stream(
            self.native_writer(writer_checkout),
            agent_call("toolu_summary", "opus", "claude-opus-5-5", prompt="Summarize the plan."),
        ))
        checks = self.valid_receipts([], native_dispatches=native, writer="opus", reviewers=("opus",))
        self.assertTrue(checks["configured_writer_dispatched"])
        self.assertFalse(checks["configured_reviewers_dispatched"])

    def test_given_two_native_reviews_working_in_one_checkout_when_checked_then_ownership_fails(self):
        self.write_final_parent()
        writer_checkout = self.final_checkout("writer-native")
        shared = self.final_checkout("review-shared")
        native, _ = claude_native_dispatches(claude_stream(self.native_writer(writer_checkout), *(
            agent_call(f"toolu_review_{index}", "opus", "claude-opus-5-5", prompt=f"Review {shared}.", tools=works_in(shared)) for index in range(2))))
        checks = self.valid_receipts([], native_dispatches=native, writer="opus", reviewers=("opus", "opus"))
        self.assertFalse(checks["receipt_workspaces_owned"])

    def test_given_a_native_review_working_in_the_xagent_writers_checkout_when_checked_then_ownership_fails(self):
        writer_checkout = self.final_checkout("writer-codex")
        self.write_final_parent()
        writer = self.receipt("codex", "rw", writer_checkout)
        native, _ = claude_native_dispatches(claude_stream(
            agent_call("toolu_review", "opus", "claude-opus-5-5", prompt=f"Review {writer_checkout}.", tools=works_in(writer_checkout))))
        checks = self.valid_receipts([writer], native_dispatches=native, writer="xagent:codex", reviewers=("opus",))
        self.assertFalse(checks["receipt_workspaces_owned"])

    def test_given_a_review_prompt_that_mentions_the_writers_committed_checkout_when_the_review_worked_elsewhere_then_it_counts(self):
        self.write_final_parent()
        writer_checkout = self.final_checkout("writer-committed")
        self.git(writer_checkout, "-c", "user.name=fixture", "-c", "user.email=fixture@local", "-c", "commit.gpgsign=false", "commit", "-qam", "writer commit")
        review_checkout = self.final_checkout("review-native")
        native, _ = claude_native_dispatches(claude_stream(
            self.native_writer(writer_checkout, prompt=f"Fix stats.py in {writer_checkout} and commit it."),
            agent_call("toolu_review", "opus", "claude-opus-5-5", tools=works_in(review_checkout),
                       prompt=f"The writer committed in {writer_checkout}. Review the uncommitted patch in {review_checkout}."),
        ))
        self.assertEqual(self.valid_receipts([], native_dispatches=native, writer="opus", reviewers=("opus",)), ALL_CHECKS_PASS)

    def test_given_a_review_that_writes_notes_naming_an_old_checkout_when_checked_then_its_own_checkout_decides(self):
        self.write_final_parent()
        # A committed writer checkout cannot pass as a review, so only the review's own evidence decides.
        writer_checkout = self.final_checkout("writer-committed")
        self.git(writer_checkout, "-c", "user.name=fixture", "-c", "user.email=fixture@local", "-c", "commit.gpgsign=false", "commit", "-qam", "writer commit")
        stale = self.final_checkout("review-stale", stats=STALE_STATS)
        review_checkout = self.final_checkout("review-native")
        notes = self.scope / "evidence" / "review-notes.md"
        notes.write_text(f"An earlier draft was reviewed in {stale}.\n")
        native, _ = claude_native_dispatches(claude_stream(
            self.native_writer(writer_checkout),
            agent_call("toolu_review", "opus", "claude-opus-5-5", prompt=f"Review {review_checkout} and keep notes in {notes}.",
                       tools=[*works_in(review_checkout), ("Write", {"file_path": str(notes)})]),
        ))
        self.assertEqual(self.valid_receipts([], native_dispatches=native, writer="opus", reviewers=("opus",)), ALL_CHECKS_PASS)

    def test_given_a_host_that_dispatched_only_reviews_when_checked_then_no_review_fills_the_writer_slot(self):
        # Codex review of 78ecce9, P1: a writer slot needs a dispatch that edited its own checkout.
        self.write_final_parent()
        reviews = [self.final_checkout(f"review-{index}") for index in range(2)]
        claude, _ = claude_native_dispatches(claude_stream(*(
            agent_call(f"toolu_review_{index}", "opus", "claude-opus-5-5", tools=works_in(checkout)) for index, checkout in enumerate(reviews))))
        home = self.root / "codex-home"
        codex, _ = codex_native_dispatches(write_codex_rollouts(home, "thread-reviews-only", [
            (f"call-review-{index}", "gpt-6.1-sol", f"thread-review-{index}", "gpt-6.1-sol", True, f"git -C {checkout} diff")
            for index, checkout in enumerate(reviews)]), home)
        for host, native, model in (("claude", claude, "opus"), ("codex", codex, "gpt-6.1-sol")):
            with self.subTest(host):
                checks = self.valid_receipts([], native_dispatches=native, writer=model, reviewers=(model,))
                self.assertFalse(checks["configured_writer_dispatched"])
                self.assertTrue(checks["configured_reviewers_dispatched"])

    def test_given_a_policy_effort_when_a_worker_records_none_then_it_fills_no_role(self):
        # Codex review of 78ecce9, P1: any level counts, since poteto-mode adjusts it per task, but it must be passed.
        self.write_final_parent()
        writer_checkout = self.committed_checkout("writer-native")
        review_checkout = self.final_checkout("review-native")
        home = self.root / "codex-home"
        for index, (effort, policy, counted) in enumerate(((None, "xhigh", False), ("high", "xhigh", True), (None, None, True), ("turbo", "xhigh", False))):
            with self.subTest(effort=effort, policy=policy):
                writer = self.final_checkout(f"writer-codex-{index}")
                review = self.final_checkout(f"review-grok-{index}")
                receipts = [self.receipt("codex", "rw", writer, name=f"rw-codex-{index}", effort=effort),
                            self.receipt("grok", "ro", review, name=f"ro-grok-{index}", effort=effort)]
                checks = self.valid_receipts(receipts, reviewers=("xagent:grok",), effort=policy)
                self.assertEqual((checks["configured_writer_dispatched"], checks["configured_reviewers_dispatched"]), (counted, counted))
                claude, _ = claude_native_dispatches(claude_stream(
                    agent_call("toolu_writer", "opus", "claude-opus-5-5", tools=writes_in(writer_checkout), effort=effort),
                    agent_call("toolu_review", "opus", "claude-opus-5-5", tools=works_in(review_checkout), effort=effort)))
                codex, _ = codex_native_dispatches(write_codex_rollouts(home, f"thread-effort-{index}", [
                    (f"effort-{index}-writer", "gpt-6.1-sol", f"effort-{index}-w", "gpt-6.1-sol", True, *self.codex_writes(writer_checkout)),
                    (f"effort-{index}-review", "gpt-6.1-sol", f"effort-{index}-r", "gpt-6.1-sol", True, f"git -C {review_checkout} diff"),
                ], effort=effort), home)
                for native, model in ((claude, "opus"), (codex, "gpt-6.1-sol")):
                    checks = self.valid_receipts([], native_dispatches=native, writer=model, reviewers=(model,), effort=policy)
                    self.assertEqual((checks["configured_writer_dispatched"], checks["configured_reviewers_dispatched"]), (counted, counted))

    def test_given_mixed_policy_when_a_native_dispatch_is_missing_unfinished_or_denied_then_its_role_fails(self):
        receipts = self.xagent_reviews_for(CLAUDE_MIXED["reviewers"])
        writer = self.native_writer(self.committed_checkout("writer-native"))
        review_checkout = self.final_checkout("review-native")
        cases = {
            "writer only": (claude_stream(writer), {"configured_writer_dispatched": True, "configured_reviewers_dispatched": False}),
            "no dispatch": (claude_stream(), {"configured_writer_dispatched": False, "configured_reviewers_dispatched": False}),
            "reviewer never joined": (
                claude_stream(writer, agent_call("toolu_review", "opus", "claude-opus-5-5", background=True, finished=False, tools=works_in(review_checkout))),
                {"configured_reviewers_dispatched": False, "all_attempts_terminal": False},
            ),
            # A completed review cannot stand in for the denied writer.
            "Agent tool denied": (
                claude_stream(agent_call("toolu_writer", "opus", None, denied=True), agent_call("toolu_review", "opus", "claude-opus-5-5", tools=works_in(review_checkout))),
                {"configured_writer_dispatched": False, "configured_reviewers_dispatched": True, "all_attempts_terminal": True},
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
        writer_checkout, review_checkout = self.committed_checkout("writer-native"), self.final_checkout("review-native")
        writer = self.native_writer(writer_checkout)
        # Each review worked in a final checkout, so only its model keeps it from the review slot.
        for name, reviewer in {
            "requested another alias": agent_call("toolu_review", "sonnet", "claude-sonnet-5-5", tools=works_in(review_checkout)),
            "resolved another model": agent_call("toolu_review", "opus", "claude-sonnet-5-5", tools=works_in(review_checkout)),
            "inherited instead of pinned": agent_call("toolu_review", None, "claude-opus-5-5", tools=works_in(review_checkout)),
            "no resolved model": agent_call("toolu_review", "opus", None, tools=works_in(review_checkout)),
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
                    (f"{thread}-writer", "gpt-6.1-sol", f"{thread}-w", "gpt-6.1-sol", True, *self.codex_writes(writer_checkout)),
                    (f"{thread}-review", requested, f"{thread}-r", actual, True, f"git -C {review_checkout} diff"),
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
        policy = dict(writer="xagent:codex/vendor/model-w", reviewers=("xagent:claude/model-a", "xagent:grok"))
        pinned = [
            self.receipt("codex", "rw", writer, model="vendor/model-w"),
            self.receipt("claude", "ro", reviewer_a, model="model-a"),
            self.receipt("grok", "ro", reviewer_b),
        ]
        self.assertTrue(all(self.valid_receipts(pinned, **policy).values()))
        unpinned = [
            self.receipt("codex", "rw", writer, name="writer-default"),
            self.receipt("claude", "ro", reviewer_a, name="review-a-default"),
            self.receipt("grok", "ro", reviewer_b, name="review-b-pinned", model="model-b"),
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
            self.receipt("codex", "rw", shared),
            self.receipt("claude", "ro", shared),
            self.receipt("grok", "ro", shared),
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
            self.receipt("codex", "rw", writer),
            self.receipt("claude", "ro", reviewer_a),
            self.receipt("grok", "ro", reviewer_b),
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
            self.receipt("codex", "rw", writer),
            self.receipt("codex", "rw", writer, name="writer-retry", status="DROPOUT", exit=3),
            self.receipt("claude", "ro", reviewer_a),
            self.receipt("grok", "ro", reviewer_b),
        ]
        checks = self.valid_receipts(receipts)
        self.assertEqual(checks, ALL_CHECKS_PASS)
        self.assertTrue(validate_parent_verification(self.scope, self.parent))

    def test_given_reviewed_worktrees_are_changed_after_review_then_stale_receipts_cannot_pass(self):
        self.write_final_parent()
        writer = self.add_worktree("writer")
        reviewer_a = self.add_worktree("review-a")
        reviewer_b = self.add_worktree("review-b")
        receipts = [
            self.receipt("codex", "rw", writer),
            self.receipt("claude", "ro", reviewer_a),
            self.receipt("grok", "ro", reviewer_b),
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
                # A foreground wait covers one attempt, so the retry has to start in a call of its own.
                self.assertIn("then run an allowed retry in a new call", prompt)
                self.assertIn(f"exclusive worktree checked out at fixture base {report['base']}, with the proposed patch applied as uncommitted changes", prompt)
                self.assertIn("every configured reviewer must review the final version again", prompt)
                self.assertIn("A native writer changes files only with its host's file-edit tool", prompt)
                self.assertIn("pass an effort to every worker, native or xagent", prompt)
                if host == "claude":
                    self.assertIn("-p", launch["argv"])
                    self.assertIn("--no-session-persistence", launch["argv"])
                    allowed = launch["argv"][launch["argv"].index("--allowedTools") + 1:]
                    self.assertIn("Agent", allowed)
                    # One foreground Bash wait has to outlast a full attempt plus xagent's termination grace.
                    self.assertGreaterEqual(int(launch["bash_max_ms"]), (XAGENT["DEFAULT_TIMEOUT"] + XAGENT["TERMINATION_GRACE"]) * 1000)
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
        for agent, mode in (("codex", "rw"), ("claude", "ro"), ("grok", "ro")):
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
            "codex", "rw", Path(receipts[0]["workdir"]), name="pending-retry",
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
