from datetime import datetime, timezone
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
TEST_SOURCE = FIXTURES["TEST_SOURCE"]
CLAUDE_MIXED, CODEX_MIXED = FIXTURES["CLAUDE_MIXED"], FIXTURES["CODEX_MIXED"]
claude_native_dispatches = HARNESS["claude_native_dispatches"]
codex_native_dispatches = HARNESS["codex_native_dispatches"]
claude_parent_commands, codex_parent_commands = HARNESS["claude_parent_commands"], HARNESS["codex_parent_commands"]
seconds = HARNESS["_timestamp"]


def iso(seconds=None):
    """A host log's ISO timestamp for seconds since the epoch, now by default."""
    moment = datetime.fromtimestamp(seconds, timezone.utc) if seconds is not None else datetime.now(timezone.utc)
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def agent_call(tool_id, requested, resolved, background=False, finished=True, denied=False, prompt="brief", tools=(), effort=None, started=None):
    """Claude stream-json events for one Agent dispatch, shaped like a real `claude -p --verbose` run, dispatched now unless started says when."""
    arguments = {"description": tool_id, "subagent_type": "general-purpose", "prompt": prompt, "run_in_background": background}
    if requested is not None:
        arguments["model"] = requested
    if effort is not None:
        arguments["effort"] = effort
    events = [{"type": "assistant", "parent_tool_use_id": None, "timestamp": started or iso(), "message": {"model": "claude-opus-5-5", "content": [
        {"type": "tool_use", "id": tool_id, "name": "Agent", "input": arguments},
    ]}}]
    # The subagent's own tool calls and results stream under the Agent call's id, for background agents too.
    for index, (name, arguments, *outcome) in enumerate(tools):
        succeeded, output = (outcome[0] if outcome else True), (outcome[1] if len(outcome) > 1 else "ok")
        events.append({"type": "assistant", "parent_tool_use_id": tool_id, "message": {"content": [
            {"type": "tool_use", "id": f"{tool_id}-{index}", "name": name, "input": arguments}]}})
        events.append({"type": "user", "parent_tool_use_id": tool_id, "message": {"content": [
            {"type": "tool_result", "tool_use_id": f"{tool_id}-{index}", "is_error": not succeeded, "content": output}]}})
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


def attacks_in(checkout):
    """An adversary's own tool calls: run the tests, add a repro beside them, and run it."""
    return [*works_in(checkout), ("Bash", {"command": f"cd {checkout} && python3 -m unittest -q"}),
            ("Write", {"file_path": f"{checkout}/test_repro.py"}), ("Bash", {"command": f"cd {checkout} && python3 -m unittest test_repro"}, False, "FAILED")]


def host_bash(tool_id, command, output="ok"):
    """Stream-json events for a Bash call the host itself ran."""
    return [{"type": "assistant", "parent_tool_use_id": None, "message": {"content": [
                {"type": "tool_use", "id": tool_id, "name": "Bash", "input": {"command": command}}]}},
            {"type": "user", "parent_tool_use_id": None, "message": {"content": [
                {"type": "tool_result", "tool_use_id": tool_id, "is_error": False, "content": output}]}}]


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


def write_codex_rollouts(home, thread, spawns, parent_rollout=True, effort=None, forked=False, started=None, parent_commands=()):
    """Write rollouts shaped like `codex exec` sessions; return the matching `--json` host log.

    Each spawn is (call, requested model, child thread, model the child ran, finished, *actions), where an action
    is a shell command the child ran, ("run", command, output), or edits(path). A forked child's rollout starts
    with a copy of the parent's history under the parent's turn id, as Codex writes it. Every rollout line carries
    started, now by default, as its timestamp. parent_commands are the host's own commands, each a script or a
    (script, working directory) pair, which its rollout records as CommandExecution items.
    """
    stamp = started or iso()
    day = home / "sessions" / "2026" / "10" / "16"
    day.mkdir(parents=True, exist_ok=True)
    parent_turn = f"{thread}-turn"
    parent_context = {"type": "turn_context", "payload": {"model": "gpt-6-astra", "turn_id": parent_turn}}
    parent = [{"type": "session_meta", "payload": {"id": thread}}, parent_context]
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
        events = [{"type": "session_meta", "payload": {"id": child, "parent_thread_id": thread, **({"forked_from_id": thread} if forked else {})}}]
        if forked:
            events += [{"type": "session_meta", "payload": {"id": thread}}, parent_context,
                       {"type": "event_msg", "payload": {"type": "item_completed", "thread_id": thread, "turn_id": parent_turn, "item": {
                           "type": "CommandExecution", "command": ["/bin/zsh", "-lc", "echo parent"], "aggregated_output": "parent", "status": "completed"}}},
                       {"type": "event_msg", "payload": {"type": "task_complete", "turn_id": parent_turn, "last_agent_message": "parent done"}}]
        events.append({"type": "turn_context", "payload": {"model": actual, "turn_id": f"{child}-turn"}})
        for index, action in enumerate(actions):
            if isinstance(action, tuple) and action[0] == "edit":
                events.append({"type": "event_msg", "payload": {"type": "item_completed", "item": {
                    "type": "FileChange", "changes": {action[1]: {"type": "update", "unified_diff": "+fix"}}, "status": "completed"}}})
                continue
            command, output = (action[1], action[2]) if isinstance(action, tuple) else (action, "")
            events.append({"type": "response_item", "payload": {"type": "custom_tool_call", "name": "exec", "call_id": f"{child}-{index}",
                                                                 "input": f"text(await tools.exec_command({{cmd:{json.dumps(command)}}}))"}})
            events.append({"type": "event_msg", "payload": {"type": "item_completed", "item": {
                "type": "CommandExecution", "command": ["/bin/zsh", "-lc", command], "aggregated_output": output, "status": "completed"}}})
        if finished:
            events.append({"type": "event_msg", "payload": {"type": "task_complete", "last_agent_message": "done"}})
            parent.append({"type": "event_msg", "payload": {"type": "item_completed", "item": {
                "type": "SubAgentActivity", "kind": "completed", "id": f"done-{call}", "agent_thread_id": child}}})
        (day / f"rollout-2026-10-16T04-00-00-{child}.jsonl").write_text("".join(json.dumps({"timestamp": stamp, **event}) + "\n" for event in events))
    for script, cwd in ((ran, None) if isinstance(ran, str) else ran for ran in parent_commands):
        parent.append({"type": "event_msg", "payload": {"type": "item_completed", "item": {
            "type": "CommandExecution", "command": ["/bin/zsh", "-lc", script], "aggregated_output": "FAILED", "status": "completed",
            **({"cwd": Path(cwd).as_uri()} if cwd else {})}}})
    if parent_rollout:
        (day / f"rollout-2026-10-16T04-00-00-{thread}.jsonl").write_text("".join(json.dumps({"timestamp": stamp, **event}) + "\n" for event in parent))
    return [json.dumps({"type": "thread.started", "thread_id": thread}), json.dumps({"type": "turn.completed"})]


class NativeEvidenceTest(FIXTURES["HarnessFixture"]):
    def codex_writes(self, checkout):
        return (f"cd {checkout} && git diff", edits(checkout / "stats.py"))

    def codex_attacks(self, checkout):
        return (f"git -C {checkout} diff", f"cd {checkout} && python3 -m unittest -q", edits(checkout / "test_repro.py"),
                ("run", f"cd {checkout} && python3 -m unittest test_repro", "FAILED"))

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
        written = self.xagent_attacks_for(CODEX_MIXED["adversaries"])
        notes = [self.native_note("native-writer-1", "/root/swarm_writer"), self.native_note("adversary-native-r1-a1", "/root/interrogate_native_r1")]
        home = self.root / "codex-home"
        native, _ = codex_native_dispatches(write_codex_rollouts(home, "thread-third-run", [
            ("call-writer", "gpt-6.1-sol", "thread-writer", "gpt-6.1-sol", True, *self.codex_writes(self.final_checkout("writer-1"))),
            ("call-attack", "gpt-6.1-sol", "thread-attack", "gpt-6.1-sol", True, *self.codex_attacks(self.attack_checkout("adversary-native-r1"))),
        ]), home)

        receipts, ignored = collect_xagent_receipts(self.evidence)

        self.assertEqual(sorted(ignored), sorted(str(note) for note in notes))
        self.assertEqual(sorted(receipt["path"] for receipt in receipts), sorted(receipt["path"] for receipt in written))
        checks = self.valid_receipts(receipts, native_dispatches=native, **CODEX_MIXED)
        self.assertEqual(checks, ALL_CHECKS_PASS)

    def test_given_a_forked_codex_child_when_checked_then_its_copy_of_the_parent_history_is_ignored(self):
        home = self.root / "codex-home-forked"
        native, gap = codex_native_dispatches(write_codex_rollouts(home, "thread-forked", [
            ("call-done", None, "thread-done", "gpt-6-luna", True, ("run", "echo child", "child")),
            ("call-open", None, "thread-open", "gpt-6-luna", False, ("run", "echo still", "still")),
        ], forked=True), home)

        self.assertIsNone(gap)
        done, still_open = native
        self.assertEqual((done.status, done.resolved, done.usable), ("completed", "gpt-6-luna", True))
        self.assertEqual([command.command for command in done.commands], ["echo child"])
        self.assertEqual((still_open.status, still_open.resolved), ("pending", "gpt-6-luna"))
        self.assertEqual([command.command for command in still_open.commands], ["echo still"])

    def test_given_mixed_claude_policy_when_stream_shows_native_dispatches_and_xagent_receipts_then_all_checks_pass(self):
        receipts = self.xagent_attacks_for(CLAUDE_MIXED["adversaries"])
        native, gap = claude_native_dispatches(claude_stream(
            self.native_writer(self.final_checkout("writer-native")),
            agent_call("toolu_attack", "opus", "claude-opus-5-5", background=True, tools=attacks_in(self.attack_checkout("attack-native"))),
        ))
        self.assertIsNone(gap)
        self.assertEqual(self.valid_receipts(receipts, native_dispatches=native, **CLAUDE_MIXED), ALL_CHECKS_PASS)

    def test_given_mixed_codex_policy_when_rollouts_show_native_dispatches_and_xagent_receipts_then_all_checks_pass(self):
        receipts = self.xagent_attacks_for(CODEX_MIXED["adversaries"])
        home = self.root / "codex-home"
        log = write_codex_rollouts(home, "thread-host", [
            ("call-writer", "gpt-6.1-sol", "thread-writer", "gpt-6.1-sol", True, *self.codex_writes(self.final_checkout("writer-native"))),
            ("call-attack", "gpt-6.1-sol", "thread-attack", "gpt-6.1-sol", True, *self.codex_attacks(self.attack_checkout("attack-native"))),
        ])
        native, gap = codex_native_dispatches(log, home)
        self.assertIsNone(gap)
        self.assertEqual([(d.requested, d.resolved, d.status) for d in native], [("gpt-6.1-sol", "gpt-6.1-sol", "completed")] * 2)
        self.assertEqual(self.valid_receipts(receipts, native_dispatches=native, **CODEX_MIXED), ALL_CHECKS_PASS)

    def test_given_an_all_native_policy_when_every_agent_call_completes_then_no_xagent_receipt_is_required(self):
        self.write_final_parent()
        native, gap = claude_native_dispatches(claude_stream(self.native_writer(self.final_checkout("writer-native")), *(
            agent_call(f"toolu_attack_{index}", "opus", "claude-opus-5-5", tools=attacks_in(self.attack_checkout(f"attack-{index}"))) for index in range(2))))
        self.assertIsNone(gap)
        self.assertEqual(self.valid_receipts([], native_dispatches=native, writer="opus", adversaries=("opus", "opus")), ALL_CHECKS_PASS)

    def test_given_one_agent_with_two_models_sharing_an_adversary_worktree_when_checked_then_ownership_fails(self):
        shared = self.attack_checkout("shared-claude")
        self.write_final_parent()
        receipts = [
            self.receipt("claude", "rw", shared, name="claude-default"),
            self.receipt("claude", "rw", shared, name="claude-opus", model="opus"),
        ]
        native, _ = claude_native_dispatches(claude_stream(self.native_writer(self.final_checkout("writer-native"))))
        checks = self.valid_receipts(receipts, native_dispatches=native, writer="opus", adversaries=("xagent:claude", "xagent:claude/opus"))
        # Different models are different workers, and the second adversary slot cannot reuse the first one's checkout either.
        self.assertFalse(checks["receipt_workspaces_owned"])
        self.assertFalse(checks["configured_adversaries_dispatched"])

    def test_given_codex_reports_a_claude_style_model_id_when_checked_then_only_claude_resolves_aliases(self):
        self.write_final_parent()
        home = self.root / "codex-home"
        writer_checkout = self.final_checkout("writer-native")
        codex, gap = codex_native_dispatches(write_codex_rollouts(home, "thread-alias", [
            ("call-writer", "opus", "thread-alias-w", "claude-opus-5-5", True, *self.codex_writes(writer_checkout))]), home)
        self.assertIsNone(gap)
        claude, _ = claude_native_dispatches(claude_stream(self.native_writer(writer_checkout)))
        self.assertFalse(self.valid_receipts([], native_dispatches=codex, writer="opus", adversaries=())["configured_writer_dispatched"])
        self.assertTrue(self.valid_receipts([], native_dispatches=claude, writer="opus", adversaries=())["configured_writer_dispatched"])

    def test_given_claude_native_attacks_when_their_subagents_work_in_checkouts_then_only_one_final_checkout_at_the_base_counts(self):
        self.write_final_parent()
        final = self.attack_checkout("attack-final")
        stale = self.final_checkout("attack-stale", stats=STALE_STATS)
        committed = self.committed_checkout("attack-committed")
        brief = self.scope / "briefs" / "attack.md"
        brief.parent.mkdir()
        brief.write_text(f"Your exclusive worktree: {stale}\n")
        writer = self.native_writer(self.final_checkout("writer-native"))
        for name, tools, counted in (
            ("final checkout", attacks_in(final), True),
            ("brief outside any checkout, then the final checkout", [("Read", {"file_path": str(brief)}), *attacks_in(final)], True),
            ("parent checkout and the final checkout", [("Bash", {"command": f"git -C {self.parent} status"}), *attacks_in(final)], True),
            # An attack that found nothing to run still attacked the final version.
            ("final checkout, reads only", works_in(final), True),
            ("checkout attacked before the last change", attacks_in(stale), False),
            ("checkout moved off the fixture base", attacks_in(committed), False),
            ("final and stale checkouts", [*attacks_in(final), *works_in(stale)], False),
            ("final checkout whose stats.py it edited", writes_in(final), False),
            ("relative and missing paths only", [("Bash", {"command": "cat stats.py"}), ("Read", {"file_path": f"{final}/notes/missing.md"})], False),
        ):
            with self.subTest(name):
                native, _ = claude_native_dispatches(claude_stream(writer, agent_call("toolu_attack", "opus", "claude-opus-5-5", tools=tools)))
                checks = self.valid_receipts([], native_dispatches=native, writer="opus", adversaries=("opus",))
                self.assertTrue(checks["configured_writer_dispatched"])
                self.assertEqual(checks["configured_adversaries_dispatched"], counted)

    def test_given_codex_native_attacks_when_their_own_commands_name_checkouts_then_only_a_final_version_counts(self):
        # Codex encrypts the task payload in both rollouts, so the child's own commands show where it attacked.
        self.write_final_parent()
        final = self.attack_checkout("attack-final")
        stale = self.final_checkout("attack-stale", stats=STALE_STATS)
        writer_checkout = self.final_checkout("writer-native")
        home = self.root / "codex-home"
        for index, (name, commands, counted) in enumerate((
            ("final checkout", self.codex_attacks(final), True),
            ("checkout attacked before the last change", self.codex_attacks(stale), False),
            ("no command", [], False),
        )):
            with self.subTest(name):
                thread = f"thread-bind-{index}"
                # The attack comes first, and the writer still finds its own attempt.
                native, gap = codex_native_dispatches(write_codex_rollouts(home, thread, [
                    (f"{thread}-attack", "gpt-6.1-sol", f"{thread}-a", "gpt-6.1-sol", True, *commands),
                    (f"{thread}-writer", "gpt-6.1-sol", f"{thread}-w", "gpt-6.1-sol", True, *self.codex_writes(writer_checkout)),
                ]), home)
                self.assertIsNone(gap)
                checks = self.valid_receipts([], native_dispatches=native, writer="gpt-6.1-sol", adversaries=("gpt-6.1-sol",))
                self.assertTrue(checks["configured_writer_dispatched"])
                self.assertEqual(checks["configured_adversaries_dispatched"], counted)

    # Scenarios A-E from the second review round: a native worker is bound by its subagent's own tool calls.
    def test_given_a_native_writer_and_an_unrelated_agent_call_when_nothing_was_attacked_then_the_adversary_slot_stays_empty(self):
        self.write_final_parent()
        writer_checkout = self.final_checkout("writer-native")
        native, _ = claude_native_dispatches(claude_stream(
            self.native_writer(writer_checkout),
            agent_call("toolu_summary", "opus", "claude-opus-5-5", prompt="Summarize the plan."),
        ))
        checks = self.valid_receipts([], native_dispatches=native, writer="opus", adversaries=("opus",))
        self.assertTrue(checks["configured_writer_dispatched"])
        self.assertFalse(checks["configured_adversaries_dispatched"])

    def test_given_two_native_attacks_working_in_one_checkout_when_checked_then_only_one_attack_counts(self):
        self.write_final_parent()
        writer_checkout = self.final_checkout("writer-native")
        shared = self.attack_checkout("attack-shared")
        native, _ = claude_native_dispatches(claude_stream(self.native_writer(writer_checkout), *(
            agent_call(f"toolu_attack_{index}", "opus", "claude-opus-5-5", prompt=f"Attack {shared}.", tools=attacks_in(shared)) for index in range(2))))
        checks = self.valid_receipts([], native_dispatches=native, writer="opus", adversaries=("opus", "opus"))
        self.assertTrue(checks["receipt_workspaces_owned"])
        self.assertFalse(checks["configured_adversaries_dispatched"])

    def test_given_a_native_attack_working_in_the_xagent_writers_checkout_when_checked_then_ownership_fails(self):
        writer_checkout = self.final_checkout("writer-codex")
        self.write_final_parent()
        writer = self.writer_receipt("codex", writer_checkout)
        native, _ = claude_native_dispatches(claude_stream(
            agent_call("toolu_attack", "opus", "claude-opus-5-5", prompt=f"Attack {writer_checkout}.", tools=attacks_in(writer_checkout))))
        checks = self.valid_receipts([writer], native_dispatches=native, writer="xagent:codex", adversaries=("opus",))
        self.assertFalse(checks["receipt_workspaces_owned"])

    def test_given_an_attack_prompt_that_mentions_a_committed_checkout_when_the_attack_worked_elsewhere_then_it_counts(self):
        self.write_final_parent()
        writer_checkout, committed = self.final_checkout("writer-native"), self.committed_checkout("writer-committed")
        attack_checkout = self.attack_checkout("attack-native")
        native, _ = claude_native_dispatches(claude_stream(
            self.native_writer(writer_checkout),
            agent_call("toolu_attack", "opus", "claude-opus-5-5", tools=attacks_in(attack_checkout),
                       prompt=f"An earlier writer committed in {committed}. Attack the uncommitted patch in {attack_checkout}."),
        ))
        self.assertEqual(self.valid_receipts([], native_dispatches=native, writer="opus", adversaries=("opus",)), ALL_CHECKS_PASS)

    def test_given_an_attack_that_writes_notes_naming_an_old_checkout_when_checked_then_its_own_checkout_decides(self):
        self.write_final_parent()
        writer_checkout = self.final_checkout("writer-native")
        stale = self.final_checkout("attack-stale", stats=STALE_STATS)
        attack_checkout = self.attack_checkout("attack-native")
        notes = self.scope / "evidence" / "attack-notes.md"
        notes.write_text(f"An earlier draft was attacked in {stale}.\n")
        native, _ = claude_native_dispatches(claude_stream(
            self.native_writer(writer_checkout),
            agent_call("toolu_attack", "opus", "claude-opus-5-5", prompt=f"Attack {attack_checkout} and keep notes in {notes}.",
                       tools=[*attacks_in(attack_checkout), ("Write", {"file_path": str(notes)})]),
        ))
        self.assertEqual(self.valid_receipts([], native_dispatches=native, writer="opus", adversaries=("opus",)), ALL_CHECKS_PASS)

    def test_given_a_host_that_dispatched_only_attacks_when_checked_then_no_attack_fills_the_writer_slot(self):
        # Codex review of 78ecce9, P1: a writer slot needs a dispatch that edited its own checkout.
        self.write_final_parent()
        attacks = [self.attack_checkout(f"attack-{index}") for index in range(2)]
        claude, _ = claude_native_dispatches(claude_stream(*(
            agent_call(f"toolu_attack_{index}", "opus", "claude-opus-5-5", tools=attacks_in(checkout)) for index, checkout in enumerate(attacks))))
        home = self.root / "codex-home"
        codex, _ = codex_native_dispatches(write_codex_rollouts(home, "thread-attacks-only", [
            (f"call-attack-{index}", "gpt-6.1-sol", f"thread-attack-{index}", "gpt-6.1-sol", True, *self.codex_attacks(checkout))
            for index, checkout in enumerate(attacks)]), home)
        for host, native, model in (("claude", claude, "opus"), ("codex", codex, "gpt-6.1-sol")):
            with self.subTest(host):
                checks = self.valid_receipts([], native_dispatches=native, writer=model, adversaries=(model,))
                self.assertFalse(checks["configured_writer_dispatched"])
                self.assertTrue(checks["configured_adversaries_dispatched"])

    def test_given_a_policy_effort_when_a_worker_records_none_then_it_fills_no_role(self):
        # Codex review of 78ecce9, P1: any level counts, since poteto-mode adjusts it per task, but it must be passed.
        self.write_final_parent()
        writer_checkout = self.final_checkout("writer-native")
        attack_checkout = self.attack_checkout("attack-native")
        home = self.root / "codex-home"
        for index, (effort, policy, counted) in enumerate(((None, "xhigh", False), ("high", "xhigh", True), (None, None, True), ("turbo", "xhigh", False))):
            with self.subTest(effort=effort, policy=policy):
                writer = self.final_checkout(f"writer-codex-{index}")
                attack = self.attack_checkout(f"attack-grok-{index}")
                receipts = [self.writer_receipt("codex", writer, name=f"rw-codex-{index}", effort=effort),
                            self.receipt("grok", "rw", attack, name=f"rw-grok-{index}", effort=effort)]
                checks = self.valid_receipts(receipts, adversaries=("xagent:grok",), effort=policy)
                self.assertEqual((checks["configured_writer_dispatched"], checks["configured_adversaries_dispatched"]), (counted, counted))
                claude, _ = claude_native_dispatches(claude_stream(
                    agent_call("toolu_writer", "opus", "claude-opus-5-5", tools=writes_in(writer_checkout), effort=effort),
                    agent_call("toolu_attack", "opus", "claude-opus-5-5", tools=attacks_in(attack_checkout), effort=effort)))
                codex, _ = codex_native_dispatches(write_codex_rollouts(home, f"thread-effort-{index}", [
                    (f"effort-{index}-writer", "gpt-6.1-sol", f"effort-{index}-w", "gpt-6.1-sol", True, *self.codex_writes(writer_checkout)),
                    (f"effort-{index}-attack", "gpt-6.1-sol", f"effort-{index}-a", "gpt-6.1-sol", True, *self.codex_attacks(attack_checkout)),
                ], effort=effort), home)
                for native, model in ((claude, "opus"), (codex, "gpt-6.1-sol")):
                    checks = self.valid_receipts([], native_dispatches=native, writer=model, adversaries=(model,), effort=policy)
                    self.assertEqual((checks["configured_writer_dispatched"], checks["configured_adversaries_dispatched"]), (counted, counted))

    def test_given_a_native_writer_sent_back_to_its_own_worktree_when_checked_then_the_follow_up_keeps_its_owner(self):
        # Third review round, scenario G: like an xagent retry, a writer's follow-up fix may reuse its worktree.
        self.write_final_parent()
        writer_checkout, attack_checkout = self.final_checkout("writer-native"), self.attack_checkout("attack-native")
        native, _ = claude_native_dispatches(claude_stream(
            self.native_writer(writer_checkout),
            agent_call("toolu_attack", "opus", "claude-opus-5-5", tools=attacks_in(attack_checkout)),
            agent_call("toolu_fix", "opus", "claude-opus-5-5", prompt=f"Address the finding in {writer_checkout}.", tools=writes_in(writer_checkout)),
        ))
        self.assertEqual(self.valid_receipts([], native_dispatches=native, writer="opus", adversaries=("opus",)), ALL_CHECKS_PASS)

    def test_given_an_attack_by_the_writers_model_in_the_writers_worktree_when_checked_then_the_workflow_fails(self):
        # One worker is one owner, so it may share the worktree, but the adversary slot then has no checkout of its own.
        self.write_final_parent()
        writer_checkout = self.final_checkout("writer-native")
        (writer_checkout / "test_repro.py").write_text(FIXTURES["REPRO_TEST"])
        for name, tools in (("reads only", works_in(writer_checkout)), ("adds a repro", attacks_in(writer_checkout))):
            with self.subTest(name):
                native, _ = claude_native_dispatches(claude_stream(
                    self.native_writer(writer_checkout), agent_call("toolu_attack", "opus", "claude-opus-5-5", tools=tools)))
                checks = self.valid_receipts([], native_dispatches=native, writer="opus", adversaries=("opus",))
                self.assertEqual((checks["receipt_workspaces_owned"], checks["configured_writer_dispatched"], checks["configured_adversaries_dispatched"]),
                                 (True, True, False))

    def test_given_a_native_attack_retried_in_its_worktree_when_only_the_retry_adds_a_repro_then_both_keep_one_owner(self):
        # thermos round 1: whether an attempt edited a file does not split one worker into two owners.
        self.write_final_parent()
        writer, checkout = self.native_writer(self.final_checkout("writer-native")), self.attack_checkout("attack-native")
        native, _ = claude_native_dispatches(claude_stream(
            writer, agent_call("toolu_attack", "opus", None, denied=True, tools=works_in(checkout)),
            agent_call("toolu_retry", "opus", "claude-opus-5-5", tools=attacks_in(checkout))))
        self.assertEqual(self.valid_receipts([], native_dispatches=native, writer="opus", adversaries=("opus",)), ALL_CHECKS_PASS)

    def test_given_a_shell_written_writer_and_an_edit_somewhere_else_when_checked_then_the_workflow_fails(self):
        # A shell edit fills no writer slot (third review round, scenario F). Its worktree, written during the attempt, holds no attack either.
        self.write_final_parent()
        shell_written = self.final_checkout("writer-shell")
        elsewhere = self.scope / "scratch"
        elsewhere.mkdir()
        self.git(elsewhere, "init", "-q")
        (elsewhere / "stats.py").write_text(FIXED_STATS)
        started = iso()
        shell_writer = agent_call("toolu_writer", "opus", "claude-opus-5-5", tools=[("Bash", {"command": f"cat > {shell_written}/stats.py <<'EOF'"})], started=started)
        self.write_after(shell_written / "stats.py", FIXED_STATS, seconds(started))
        native, _ = claude_native_dispatches(claude_stream(
            shell_writer, agent_call("toolu_other", "opus", "claude-opus-5-5", tools=[("Edit", {"file_path": f"{elsewhere}/stats.py"})])))
        self.assertFalse(self.valid_receipts([], native_dispatches=native, writer="opus", adversaries=("opus",))["configured_writer_dispatched"])
        # The same with the other edit in a proper worktree at the base: it may write, but nothing attacked.
        native, _ = claude_native_dispatches(claude_stream(shell_writer, self.native_writer(self.final_checkout("writer-elsewhere"))))
        checks = self.valid_receipts([], native_dispatches=native, writer="opus", adversaries=("opus",))
        self.assertEqual((checks["configured_writer_dispatched"], checks["configured_adversaries_dispatched"]), (True, False))

    def test_given_native_writer_evidence_when_checked_then_only_a_successful_edit_in_a_worktree_at_the_base_writes(self):
        self.write_final_parent()
        final, committed = self.final_checkout("writer-final"), self.committed_checkout("writer-committed")
        notes, tests_changed = self.final_checkout("writer-notes"), self.final_checkout("writer-tests")
        (notes / "notes.md").write_text("plan\n")
        (tests_changed / "test_stats.py").write_text("import unittest\n")
        for name, tools, writes in (
            ("successful edit at the base", writes_in(final), True),
            ("edit the tool rejected", [*works_in(final), ("Edit", {"file_path": f"{final}/stats.py"}, False)], False),
            ("edit in a worktree that left the base", writes_in(committed), False),
            # Codex review of 5934d62, P1: the edit must be the repair itself, with the tests left alone.
            ("edit of an unrelated file only", [*works_in(notes), ("Write", {"file_path": f"{notes}/notes.md"})], False),
            ("edit beside a changed test file", writes_in(tests_changed), False),
        ):
            with self.subTest(name):
                native, _ = claude_native_dispatches(claude_stream(agent_call("toolu_writer", "opus", "claude-opus-5-5", tools=tools)))
                self.assertEqual(self.valid_receipts([], native_dispatches=native, writer="opus", adversaries=())["configured_writer_dispatched"], writes)

    def test_given_dispatches_from_a_second_load_of_the_evidence_module_when_checked_then_the_result_is_the_same(self):
        # Fourth review round: the role checks read a dispatch's fields, not the identity of a class runpy loaded.
        self.write_final_parent()
        stream = claude_stream(self.native_writer(self.final_checkout("writer-native")),
                               agent_call("toolu_attack", "opus", "claude-opus-5-5", tools=attacks_in(self.attack_checkout("attack-native"))))
        second_load, _ = runpy.run_path(str(ROOT / "scripts/e2e-native-evidence.py"))["claude_native_dispatches"](stream)
        self.assertEqual(self.valid_receipts([], native_dispatches=second_load, writer="opus", adversaries=("opus",)), ALL_CHECKS_PASS)

    def native_attack(self, host, checkout, started):
        """A native writer and one native attack on checkout dispatched at started, as the host's log shows them, with
        the model both ran."""
        writer_checkout = self.final_checkout(f"writer-{host}-{checkout.parent.name}")
        if host == "claude":
            return claude_native_dispatches(claude_stream(
                self.native_writer(writer_checkout), agent_call("toolu_attack", "opus", "claude-opus-5-5", tools=attacks_in(checkout), started=started)))[0], "opus"
        home, thread = self.root / "codex-home", f"thread-{checkout.parent.name}"
        return codex_native_dispatches(write_codex_rollouts(home, thread, [
            (f"{thread}-writer", "gpt-6.1-sol", f"{thread}-w", "gpt-6.1-sol", True, *self.codex_writes(writer_checkout)),
            (f"{thread}-attack", "gpt-6.1-sol", f"{thread}-a", "gpt-6.1-sol", True, *self.codex_attacks(checkout)),
        ], started=started), home)[0], "gpt-6.1-sol"

    def test_given_a_native_attack_whose_checkout_was_written_after_its_dispatch_when_checked_then_it_is_not_an_attack(self):
        # The files an attack ran against must predate its dispatch.
        self.write_final_parent()
        for index, (name, written, early, counted) in enumerate((
            ("checkout left alone", None, False, True),
            ("stats.py rewritten with the same bytes", ("stats.py", FIXED_STATS), False, False),
            ("stats.py changed back", ("stats.py", STALE_STATS), False, False),
            ("test_stats.py rewritten with the same bytes", ("test_stats.py", TEST_SOURCE), False, False),
            # A reused worktree: the attack was dispatched before the final version arrived, and its re-attack dropped out.
            ("dispatched before the final version arrived", None, True, False),
        )):
            for host in ("claude", "codex"):
                with self.subTest(name, host=host):
                    checkout = self.attack_checkout(f"attack-{host}-{index}")
                    started = iso((checkout / "stats.py").stat().st_mtime - 30) if early else iso()
                    native, model = self.native_attack(host, checkout, started)
                    if written:
                        self.write_after(checkout / written[0], written[1], seconds(started))
                    checks = self.valid_receipts([], native_dispatches=native, writer=model, adversaries=(model,))
                    self.assertTrue(checks["configured_writer_dispatched"])
                    self.assertEqual(checks["configured_adversaries_dispatched"], counted)

    def test_given_a_claude_findings_ledger_when_checked_then_only_the_hosts_own_bash_rerun_counts(self):
        self.write_final_parent()
        attack = self.attack_checkout("attack-native")
        rerun = f"cd {attack} && python3 -m unittest test_repro"
        finding = {"adversary": "opus", "worktree": str(attack), "command": rerun, "kept": True}
        writer = self.native_writer(self.final_checkout("writer-native"))
        # The adversary ran the same command itself, under its Agent call.
        adversary = agent_call("toolu_attack", "opus", "claude-opus-5-5", tools=attacks_in(attack))
        ledger = f"cat > {self.scope}/findings.json <<'EOF'\n{json.dumps([finding])}\nEOF"
        # A live Claude parent reran every finding in one script through a shell variable, so no call is the ledger's command.
        batched = f'W={attack.parent}\necho "### 1"; cd $W/{attack.name} && python3 -m unittest test_repro; echo "exit $?"'
        for name, ran, counted in (
            ("the host reran it", [host_bash("toolu_rerun", rerun, "FAILED (failures=1)"), host_bash("toolu_ledger", ledger)], True),
            ("only the adversary ran it, and the host wrote the ledger", [host_bash("toolu_ledger", ledger)], False),
            ("the host reran it inside a batch through a shell variable",
             [host_bash("toolu_batch", batched, "FAILED (failures=1)"), host_bash("toolu_ledger", ledger)], False),
        ):
            with self.subTest(name):
                lines = claude_stream(writer, adversary, *ran)
                parent_commands = claude_parent_commands(lines)
                self.assertEqual([command.command for command in parent_commands], [event[0]["message"]["content"][0]["input"]["command"] for event in ran])
                self.assertEqual(parent_commands[0].output, ran[0][1]["message"]["content"][0]["content"])
                native, _ = claude_native_dispatches(lines)
                checks = self.valid_receipts([], native_dispatches=native, writer="opus", adversaries=("opus",), findings=[finding],
                                             parent_commands=parent_commands)
                self.assertEqual(checks, {**ALL_CHECKS_PASS, "findings_rerun_by_parent": counted})

    def test_given_a_codex_findings_ledger_when_checked_then_only_the_hosts_own_rollout_commands_count(self):
        self.write_final_parent()
        attack = self.attack_checkout("attack-native")
        writer_checkout = self.final_checkout("writer-native")
        home = self.root / "codex-home"
        named = f"cd {attack} && python3 -m unittest test_repro"
        for index, (name, parent_commands, command, counted) in enumerate((
            ("the host reran it naming the worktree", [named], named, True),
            ("the host reran it with the worktree as its working directory", [("python3 -m unittest test_repro", attack)], "python3 -m unittest test_repro", True),
            # The child ran the same command in its own rollout.
            ("only the adversary ran it", [], named, False),
        )):
            with self.subTest(name):
                log = write_codex_rollouts(home, f"thread-findings-{index}", [
                    (f"findings-{index}-writer", "gpt-6.1-sol", f"findings-{index}-w", "gpt-6.1-sol", True, *self.codex_writes(writer_checkout)),
                    (f"findings-{index}-attack", "gpt-6.1-sol", f"findings-{index}-a", "gpt-6.1-sol", True, *self.codex_attacks(attack)),
                ], parent_commands=parent_commands)
                native, _ = codex_native_dispatches(log, home)
                ran = codex_parent_commands(log, home)
                self.assertEqual([command.command for command in ran], [ran if isinstance(ran, str) else ran[0] for ran in parent_commands])
                finding = {"adversary": "gpt-6.1-sol", "worktree": str(attack), "command": command, "kept": False}
                checks = self.valid_receipts([], native_dispatches=native, writer="gpt-6.1-sol", adversaries=("gpt-6.1-sol",), findings=[finding],
                                             parent_commands=ran)
                self.assertEqual(checks, {**ALL_CHECKS_PASS, "findings_rerun_by_parent": counted})

    def test_given_mixed_policy_when_a_native_dispatch_is_missing_unfinished_or_denied_then_its_role_fails(self):
        receipts = self.xagent_attacks_for(CLAUDE_MIXED["adversaries"])
        writer = self.native_writer(self.final_checkout("writer-native"))
        attack_checkout = self.attack_checkout("attack-native")
        cases = {
            "writer only": (claude_stream(writer), {"configured_writer_dispatched": True, "configured_adversaries_dispatched": False}),
            "no dispatch": (claude_stream(), {"configured_writer_dispatched": False, "configured_adversaries_dispatched": False}),
            "adversary never joined": (
                claude_stream(writer, agent_call("toolu_attack", "opus", "claude-opus-5-5", background=True, finished=False, tools=attacks_in(attack_checkout))),
                {"configured_adversaries_dispatched": False, "all_attempts_terminal": False},
            ),
            # A completed attack cannot stand in for the denied writer.
            "Agent tool denied": (
                claude_stream(agent_call("toolu_writer", "opus", None, denied=True), agent_call("toolu_attack", "opus", "claude-opus-5-5", tools=attacks_in(attack_checkout))),
                {"configured_writer_dispatched": False, "configured_adversaries_dispatched": True, "all_attempts_terminal": True},
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
        receipts = self.xagent_attacks_for(CODEX_MIXED["adversaries"])
        home = self.root / "codex-home"
        cases = {
            "no thread id": ([json.dumps({"type": "turn.completed"})], True),
            "ephemeral host": (write_codex_rollouts(home, "thread-ephemeral", [], parent_rollout=False), True),
            "child rollout missing": (write_codex_rollouts(home, "thread-orphan", [
                ("call-writer", "gpt-6.1-sol", "thread-lost-writer", None, True),
                ("call-attack", "gpt-6.1-sol", "thread-lost-attack", None, True),
            ]), False),
        }
        for name, (log, reports_gap) in cases.items():
            with self.subTest(name):
                native, gap = codex_native_dispatches(log, home)
                self.assertEqual(bool(gap), reports_gap, gap)
                self.assertTrue(all(d.resolved is None for d in native), native)
                checks = self.valid_receipts(receipts, native_dispatches=native, **CODEX_MIXED)
                self.assertFalse(checks["configured_writer_dispatched"])
                self.assertFalse(checks["configured_adversaries_dispatched"])

    def test_given_native_dispatch_with_wrong_model_when_checked_then_it_cannot_fill_the_configured_role(self):
        receipts = self.xagent_attacks_for(CLAUDE_MIXED["adversaries"])
        writer_checkout, attack_checkout = self.final_checkout("writer-native"), self.attack_checkout("attack-native")
        writer = self.native_writer(writer_checkout)
        # Each attack worked in a final checkout, so only its model keeps it from the adversary slot.
        for name, adversary in {
            "requested another alias": agent_call("toolu_attack", "sonnet", "claude-sonnet-5-5", tools=attacks_in(attack_checkout)),
            "resolved another model": agent_call("toolu_attack", "opus", "claude-sonnet-5-5", tools=attacks_in(attack_checkout)),
            "inherited instead of pinned": agent_call("toolu_attack", None, "claude-opus-5-5", tools=attacks_in(attack_checkout)),
            "no resolved model": agent_call("toolu_attack", "opus", None, tools=attacks_in(attack_checkout)),
        }.items():
            with self.subTest(name):
                native, _ = claude_native_dispatches(claude_stream(writer, adversary))
                checks = self.valid_receipts(receipts, native_dispatches=native, **CLAUDE_MIXED)
                self.assertTrue(checks["configured_writer_dispatched"])
                self.assertFalse(checks["configured_adversaries_dispatched"])
        home = self.root / "codex-home"
        for index, (name, requested, actual) in enumerate((
            ("child ran another model", "gpt-6.1-sol", "gpt-6-luna"),
            ("requested another model", "gpt-6-luna", "gpt-6-luna"),
        )):
            with self.subTest(name):
                thread = f"thread-mismatch-{index}"
                log = write_codex_rollouts(home, thread, [
                    (f"{thread}-writer", "gpt-6.1-sol", f"{thread}-w", "gpt-6.1-sol", True, *self.codex_writes(writer_checkout)),
                    (f"{thread}-attack", requested, f"{thread}-a", actual, True, *self.codex_attacks(attack_checkout)),
                ])
                native, gap = codex_native_dispatches(log, home)
                self.assertIsNone(gap)
                checks = self.valid_receipts(receipts, native_dispatches=native, writer=CODEX_MIXED["writer"], adversaries=("gpt-6.1-sol",))
                self.assertTrue(checks["configured_writer_dispatched"])
                self.assertFalse(checks["configured_adversaries_dispatched"])

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
                # Attacks only count at the fixture base against the final source, so the brief must say so.
                prompt = " ".join(launch["prompt"].split())
                # Live grok-4.7 reviews took 409 to over 900 seconds, so the cap matches xagent's 900-second default.
                self.assertIn("Limit each worker to 900 seconds and at most one retry", prompt)
                # A foreground wait covers one attempt, so the retry has to start in a call of its own.
                self.assertIn("then run an allowed retry in a new call", prompt)
                self.assertIn(f"exclusive worktree checked out at fixture base {report['base']}, with the proposed patch applied as uncommitted changes", prompt)
                self.assertIn("every configured adversary must attack the final version again in a new worktree prepared the same way", prompt)
                self.assertIn("A native writer changes stats.py only with its host's file-edit tool", prompt)
                self.assertIn(f"exclusive worktree at fixture base {report['base']} and have it leave its change uncommitted", prompt)
                self.assertIn("Adversaries leave stats.py and test_stats.py unchanged and keep their repro files beside them in their own worktree", prompt)
                # The parent's reruns are the evidence, so the brief asks for a ledger that names each worktree.
                # A live Claude parent batched its reruns in one script with shell variables, which no ledger entry can quote.
                self.assertIn("in a shell call of its own that runs only that command: cd <that adversary's worktree as an absolute path> "
                              "&& <the finding's command>, with no shell variables", prompt)
                self.assertIn(f"Record every rerun in {run / host / 'findings.json'}", prompt)
                self.assertIn('"command" (that shell call\'s command string, copied verbatim)', prompt)
                self.assertIn("Write [] when no adversary reported a finding", prompt)
                self.assertIn("pass an effort to every worker, native or xagent; dispatch each native worker as an agent type "
                              "whose definition sets no effort of its own", prompt)
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
                # The stub wrote no ledger, so no rerun evidence exists.
                self.assertIsNone(report["findings"])
                self.assertEqual(report["parent_commands"], [])
                self.assertFalse(report["checks"]["findings_rerun_by_parent"])


if __name__ == "__main__":
    unittest.main()
