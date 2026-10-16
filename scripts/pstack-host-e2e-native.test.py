import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = runpy.run_path(str(ROOT / "scripts/pstack-host-e2e-fixtures.py"))
HARNESS, XAGENT = FIXTURES["HARNESS"], FIXTURES["XAGENT"]
FIXED_STATS, STALE_STATS, ALL_CHECKS_PASS = FIXTURES["FIXED_STATS"], FIXTURES["STALE_STATS"], FIXTURES["ALL_CHECKS_PASS"]
CLAUDE_MIXED, CODEX_MIXED = FIXTURES["CLAUDE_MIXED"], FIXTURES["CODEX_MIXED"]
# The parsers the harness itself loaded, so their dispatches are the harness's own NativeDispatch.
claude_native_dispatches = HARNESS["claude_native_dispatches"]
codex_native_dispatches = HARNESS["codex_native_dispatches"]


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


class NativeEvidenceTest(FIXTURES["HarnessFixture"]):
    def codex_writes(self, checkout):
        return (f"cd {checkout} && git diff", edits(checkout / "stats.py"))

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

    def native_writer(self, checkout, prompt=None):
        return agent_call("toolu_writer", "opus", "claude-opus-5-5", prompt=prompt or f"Fix stats.py in {checkout}.", tools=writes_in(checkout))

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
        self.assertEqual([(d.requested, d.resolved, d.status) for d in native], [("gpt-6.1-sol", "gpt-6.1-sol", "completed")] * 2)
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

    # Scenarios A-E from the second review round: a native review is bound by its subagent's own tool calls.
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
                self.assertTrue(all(d.resolved is None for d in native), native)
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


if __name__ == "__main__":
    unittest.main()
