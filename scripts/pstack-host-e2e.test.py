import hashlib
import json
import os
from pathlib import Path
import py_compile
import re
import runpy
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = runpy.run_path(str(ROOT / "scripts/pstack-host-e2e-fixtures.py"))
HARNESS, XAGENT = FIXTURES["HARNESS"], FIXTURES["XAGENT"]
FIXED_STATS, ALL_CHECKS_PASS, CODEX_MIXED = FIXTURES["FIXED_STATS"], FIXTURES["ALL_CHECKS_PASS"], FIXTURES["CODEX_MIXED"]
STALE_STATS, TEST_SOURCE = FIXTURES["STALE_STATS"], FIXTURES["TEST_SOURCE"]
ShellCommand, load_findings = HARNESS["ShellCommand"], HARNESS["load_findings"]
classify_host_reply = HARNESS["classify_host_reply"]
validate_parent_verification = HARNESS["validate_parent_verification"]
write_parent_verifier = HARNESS["write_parent_verifier"]


class HostHarnessAcceptanceTest(FIXTURES["HarnessFixture"]):
    def test_given_an_unreadable_receipt_in_an_xagent_out_dir_and_a_copy_elsewhere_when_collected_then_only_the_copy_is_ignored(self):
        collect_xagent_receipts = HARNESS["collect_xagent_receipts"]
        written = self.xagent_attacks_for(CODEX_MIXED["adversaries"])
        Path(written[0]["path"]).write_text('{"agent": "claude", "mode": "rw"')
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

    def test_given_entries_xagent_would_reject_when_checked_then_they_fill_no_role(self):
        writer = self.final_checkout("writer")
        self.write_final_parent()
        attack = self.receipt("grok", "rw", self.attack_checkout("attack-grok"))
        for index, (entry, agent, model) in enumerate((("xagent:nobody", "nobody", None), ("xagent:claude/-bad", "claude", "-bad"))):
            with self.subTest(entry):
                receipts = [self.receipt(agent, "rw", writer, name=f"rw-{index}", model=model), attack]
                self.assertFalse(self.valid_receipts(receipts, writer=entry, adversaries=("xagent:grok",))["configured_writer_dispatched"])

    def test_given_a_policy_without_swarm_or_interrogate_entries_when_roles_resolve_then_the_helper_defaults_apply(self):
        shown = json.loads(subprocess.check_output(
            ["node", str(ROOT / "bin/config.mjs"), "show", "--host", "claude", "--config", str(self.root / "absent.json")], text=True))
        effective = shown["effective"]
        self.assertEqual(HARNESS["expected_roles"](effective), (effective["defaultModel"], effective["defaultPanel"]))

    def test_given_default_limits_when_the_host_deadline_is_chosen_then_six_full_attempts_and_the_parent_checks_fit(self):
        result = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/pstack-host-e2e.py"), "--help"], capture_output=True, text=True, timeout=30)
        default = int(re.search(r"default: (\d+)", " ".join(result.stdout.split())).group(1))
        # Writer, attack and re-attack rounds may each retry once; every attempt can run to its limit plus xagent's grace.
        attempts = 3 * 2 * (XAGENT["DEFAULT_TIMEOUT"] + XAGENT["TERMINATION_GRACE"])
        self.assertGreater(default, attempts + 2 * 30)

    def test_given_an_xagent_out_dir_missing_one_marker_when_collected_then_its_broken_receipt_still_fails(self):
        out = self.evidence / "interrupted-attempt"
        out.mkdir()
        (out / "prompt.md").write_text("brief\n")
        (out / "meta.json").write_text('{"agent": "grok", "mode": "rw", "completed": fal')
        receipts, ignored = HARNESS["collect_xagent_receipts"](self.evidence)
        self.assertEqual((receipts, ignored), ([None], []))
        self.assertFalse(self.valid_receipts(receipts, writer="opus", adversaries=("opus",))["all_attempts_terminal"])

    def test_given_policy_pins_worker_models_when_receipts_are_checked_then_each_receipt_must_carry_its_model(self):
        writer = self.final_checkout("writer")
        attack_a = self.attack_checkout("attack-a")
        attack_b = self.attack_checkout("attack-b")
        final_hash = self.write_final_parent()
        self.write_verifier_receipt(final_hash)
        policy = dict(writer="xagent:codex/vendor/model-w", adversaries=("xagent:claude/model-a", "xagent:grok"))
        pinned = [
            self.writer_receipt("codex", writer, model="vendor/model-w"),
            self.receipt("claude", "rw", attack_a, model="model-a"),
            self.receipt("grok", "rw", attack_b),
        ]
        self.assertTrue(all(self.valid_receipts(pinned, **policy).values()))
        unpinned = [
            self.writer_receipt("codex", writer, name="writer-default"),
            self.receipt("claude", "rw", attack_a, name="attack-a-default"),
            self.receipt("grok", "rw", attack_b, name="attack-b-pinned", model="model-b"),
        ]
        checks = self.valid_receipts(unpinned, **policy)
        self.assertTrue(checks["all_attempts_terminal"] and checks["receipt_workspaces_owned"], checks)
        self.assertFalse(checks["configured_writer_dispatched"])
        self.assertFalse(checks["configured_adversaries_dispatched"])

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

    def test_given_one_adversary_entry_twice_when_both_receipts_share_a_worktree_then_only_one_attack_counts(self):
        # Third review round, scenario H, and Codex's review of fc4805e: each adversary slot needs a worktree of its own.
        writer = self.final_checkout("writer")
        self.write_final_parent()
        written = self.writer_receipt("codex", writer)
        for agent in ("grok", "claude"):
            with self.subTest(agent):
                shared = self.attack_checkout(f"attack-{agent}")
                first, second = (self.receipt(agent, "rw", shared, name=f"rw-{agent}-{index}") for index in (1, 2))
                checks = self.valid_receipts([written, first, second], adversaries=(f"xagent:{agent}",) * 2)
                self.assertEqual((checks["receipt_workspaces_owned"], checks["configured_adversaries_dispatched"]), (True, False))
                # A retry of the same adversary for one slot may reuse its worktree.
                dropout = self.receipt(agent, "rw", shared, name=f"rw-{agent}-dropout", status="DROPOUT", exit=3)
                self.assertEqual(self.valid_receipts([written, dropout, first], adversaries=(f"xagent:{agent}",)), ALL_CHECKS_PASS)

    def test_given_writer_and_adversaries_share_one_worktree_when_receipts_are_checked_then_it_fails(self):
        shared = self.attack_checkout("shared")
        final_hash = self.write_final_parent()
        self.write_verifier_receipt(final_hash)
        receipts = [
            self.writer_receipt("codex", shared),
            self.receipt("claude", "rw", shared),
            self.receipt("grok", "rw", shared),
        ]
        self.assertTrue(all(Path(r["workdir"]).resolve().is_relative_to(self.scope.resolve()) and Path(r["workdir"]).resolve() != self.parent.resolve() for r in receipts))
        checks = self.valid_receipts(receipts)
        self.assertFalse(checks["receipt_workspaces_owned"])

    def test_given_adversary_receipts_for_old_code_when_checked_against_final_parent_then_the_attacks_fail(self):
        writer = self.final_checkout("writer")
        final_hash = self.write_final_parent()
        self.write_verifier_receipt(final_hash)
        receipts = [
            self.writer_receipt("codex", writer),
            self.receipt("claude", "rw", self.add_worktree("attack-a")),
            self.receipt("grok", "rw", self.final_checkout("attack-b", stats=STALE_STATS)),
        ]
        self.assertTrue(all(r["completed"] and r["status"] in ("PASS", "ISSUES") and r["exit"] == 0 for r in receipts[1:]))
        checks = self.valid_receipts(receipts)
        self.assertTrue(checks["receipt_workspaces_owned"])
        self.assertTrue(checks["configured_writer_dispatched"])
        self.assertFalse(checks["configured_adversaries_dispatched"])

    def test_given_an_adversary_left_stats_or_its_tests_changed_when_checked_then_its_attack_fills_no_slot(self):
        writer = self.final_checkout("writer")
        self.write_final_parent()
        written = self.writer_receipt("codex", writer)
        for name, content in (("stats.py", STALE_STATS), ("test_stats.py", TEST_SOURCE + "# weakened\n")):
            with self.subTest(name):
                checkout = self.attack_checkout(f"attack-{name}")
                attack = self.receipt("claude", "rw", checkout, name=f"attack-{name}-out")
                self.assertEqual(self.valid_receipts([written, attack], adversaries=("xagent:claude",)), ALL_CHECKS_PASS)
                (checkout / name).write_text(content)
                self.assertFalse(self.valid_receipts([written, attack], adversaries=("xagent:claude",))["configured_adversaries_dispatched"])

    def test_given_an_xagent_adversary_ran_read_only_when_checked_then_it_fills_no_slot(self):
        # ro is plan mode for claude and gemini, which runs no commands, so it cannot prove a finding with a run.
        writer = self.final_checkout("writer")
        self.write_final_parent()
        receipts = [self.writer_receipt("codex", writer), self.receipt("claude", "ro", self.final_checkout("attack-claude"))]
        self.assertTrue(receipts[1]["completed"] and receipts[1]["status"] == "PASS" and receipts[1]["changed_workdir"] is False)
        checks = self.valid_receipts(receipts, adversaries=("xagent:claude",))
        self.assertTrue(checks["receipt_workspaces_owned"] and checks["configured_writer_dispatched"], checks)
        self.assertFalse(checks["configured_adversaries_dispatched"])

    def test_given_real_linked_worktrees_and_final_code_when_receipts_match_then_all_checks_pass(self):
        writer = self.final_checkout("writer")
        attack_a = self.attack_checkout("attack-a")
        attack_b = self.attack_checkout("attack-b")
        final_hash = self.write_final_parent()
        self.write_verifier_receipt(final_hash)
        receipts = [
            self.writer_receipt("codex", writer),
            self.receipt("codex", "rw", writer, name="writer-retry", status="DROPOUT", exit=3),
            self.receipt("claude", "rw", attack_a),
            self.receipt("grok", "rw", attack_b),
        ]
        # Each adversary kept its repro beside the fixture's files.
        self.assertTrue(all((checkout / "test_repro.py").is_file() for checkout in (attack_a, attack_b)))
        checks = self.valid_receipts(receipts)
        self.assertEqual(checks, ALL_CHECKS_PASS)
        self.assertTrue(validate_parent_verification(self.scope, self.parent))

    def test_given_attacked_worktrees_are_rewritten_after_the_attack_started_then_stale_receipts_cannot_pass(self):
        writer = self.final_checkout("writer")
        self.write_final_parent()
        attack_a = self.attack_checkout("attack-a")
        attack_b = self.attack_checkout("attack-b")
        receipts = [
            self.writer_receipt("codex", writer),
            self.receipt("claude", "rw", attack_a),
            self.receipt("grok", "rw", attack_b),
        ]
        self.assertEqual(self.valid_receipts(receipts), ALL_CHECKS_PASS)
        # The same bytes written again after the attack started still mean it attacked something else.
        self.write_after(attack_a / "stats.py", FIXED_STATS, self.started(receipts[1]))
        self.write_after(attack_b / "test_stats.py", TEST_SOURCE, self.started(receipts[2]))
        checks = self.valid_receipts(receipts)
        self.assertTrue(checks["receipt_workspaces_owned"])
        self.assertFalse(checks["configured_adversaries_dispatched"])

    def test_given_a_reused_worktree_whose_final_attack_dropped_out_then_the_earlier_attack_does_not_count(self):
        # After a fix, the parent reuses an adversary's worktree for the re-attack, and that re-attack drops out.
        writer = self.final_checkout("writer")
        self.write_final_parent()
        reused = self.attack_checkout("attack-claude")
        earlier = self.receipt("claude", "rw", reused, name="attack-claude-first")
        # The first attack ran before the final version reached the worktree, so the parent's copy is no repair.
        started = (reused / "stats.py").stat().st_mtime - 30
        self.ran(earlier, started, started + 10)
        dropout = self.receipt("claude", "rw", reused, name="attack-claude-final", status="DROPOUT", exit=3)
        written = self.writer_receipt("codex", writer)
        checks = self.valid_receipts([written, earlier, dropout], adversaries=("xagent:claude",))
        self.assertTrue(checks["all_attempts_terminal"] and checks["receipt_workspaces_owned"], checks)
        self.assertFalse(checks["configured_adversaries_dispatched"])
        # A re-attack that finishes fills the slot.
        retried = self.receipt("claude", "rw", reused, name="attack-claude-retry")
        self.assertEqual(self.valid_receipts([written, earlier, dropout, retried], adversaries=("xagent:claude",)), ALL_CHECKS_PASS)

    def test_given_an_xagent_writer_that_dropped_out_after_its_repair_when_the_retry_only_verifies_then_the_writer_slot_fills(self):
        # thermos round 2: xagent retries in the same worktree, and a retry that finds the repair made only runs the tests.
        checkout = self.add_worktree("writer")
        dropped = self.writer_receipt("codex", checkout, name="writer-1", status="DROPOUT", exit=3, reason="timeout")
        retry = self.receipt("codex", "rw", checkout, name="writer-2")
        later = self.started(dropped) + 600
        self.ran(retry, later, later + 2)
        attacks = self.xagent_attacks_for(("xagent:claude", "xagent:grok"))
        self.assertEqual(self.valid_receipts([dropped, retry, *attacks]), ALL_CHECKS_PASS)
        # A write between the two runs, as when the parent copies a fix in, is not that worker's repair.
        between = self.started(dropped) + 300
        os.utime(checkout / "stats.py", (between, between))
        self.assertFalse(self.valid_receipts([dropped, retry, *attacks])["configured_writer_dispatched"])

    def test_given_an_xagent_writer_run_another_model_answered_when_the_retry_only_verifies_then_the_writer_slot_stays_empty(self):
        # thermos round 3: xagent drops a pinned run as model_mismatch when the CLI answered with another model.
        checkout = self.add_worktree("writer")
        mismatched = self.writer_receipt("codex", checkout, name="writer-1", model="gpt-6.1-sol", status="DROPOUT",
                                         reason="model_mismatch", resolved_models=["gpt-6-luna"])
        retry = self.receipt("codex", "rw", checkout, name="writer-2", model="gpt-6.1-sol", resolved_models=["gpt-6.1-sol"])
        later = self.started(mismatched) + 600
        self.ran(retry, later, later + 2)
        attacks = self.xagent_attacks_for(("xagent:claude", "xagent:grok"))
        checks = self.valid_receipts([mismatched, retry, *attacks], writer="xagent:codex/gpt-6.1-sol")
        self.assertEqual(checks, {**ALL_CHECKS_PASS, "configured_writer_dispatched": False})
        # The same repair in a run of the pinned model, dropped for a timeout, is that worker's, so the retry fills the slot.
        timed_out = {**mismatched, "reason": "timeout", "timed_out": True, "resolved_models": ["gpt-6.1-sol"]}
        self.assertEqual(self.valid_receipts([timed_out, retry, *attacks], writer="xagent:codex/gpt-6.1-sol"), ALL_CHECKS_PASS)

    def test_given_one_xagent_agent_as_writer_and_adversary_when_it_only_attacked_then_the_writer_slot_stays_empty(self):
        # thermos round 1: an attack on an earlier patch, then the re-attack the brief requires after a fix, and no writer.
        self.write_final_parent()
        earlier = self.receipt("codex", "rw", self.final_checkout("attack-codex-1", stats=STALE_STATS), name="attack-codex-1-out")
        again = self.receipt("codex", "rw", self.attack_checkout("attack-codex-2"), name="attack-codex-2-out")
        checks = self.valid_receipts([earlier, again], writer="xagent:codex", adversaries=("xagent:codex",))
        self.assertEqual((checks["configured_adversaries_dispatched"], checks["configured_writer_dispatched"]), (True, False))
        # The same agent writing in a worktree of its own fills the writer slot beside its attack.
        written = self.writer_receipt("codex", self.add_worktree("writer"))
        self.assertEqual(self.valid_receipts([earlier, again, written], writer="xagent:codex", adversaries=("xagent:codex",)), ALL_CHECKS_PASS)

    def test_given_missing_or_malformed_evidence_when_checked_then_it_fails_without_raising(self):
        self.assertFalse(validate_parent_verification(self.scope, self.parent))
        (self.scope / "parent-verification.json").write_text("not json\n")
        self.assertFalse(validate_parent_verification(self.scope, self.parent))
        self.assertEqual(self.valid_receipts([{"mode": "rw", "agent": None}], findings=None), {
            "all_attempts_terminal": False,
            "configured_writer_dispatched": False,
            "configured_adversaries_dispatched": False,
            "receipt_workspaces_owned": False,
            "findings_rerun_by_parent": False,
        })

    def test_given_a_findings_ledger_when_loaded_then_only_a_list_of_complete_entries_is_accepted(self):
        ledger = self.scope / "findings.json"
        self.assertIsNone(load_findings(ledger))
        entry = {"adversary": "xagent:claude", "worktree": str(self.parent), "command": "python3 -m unittest", "kept": True}
        for content in ("not json", json.dumps(entry), json.dumps([{**entry, "kept": "yes"}]), json.dumps([{**entry, "command": "  "}]),
                        json.dumps([{key: value for key, value in entry.items() if key != "worktree"}])):
            with self.subTest(content):
                ledger.write_text(content)
                self.assertIsNone(load_findings(ledger))
        for findings in ([], [entry, {**entry, "kept": False}]):
            ledger.write_text(json.dumps(findings))
            self.assertEqual(load_findings(ledger), findings)

    def test_given_a_findings_ledger_when_checked_then_each_entry_needs_a_parent_rerun_in_that_adversarys_worktree(self):
        writer = self.final_checkout("writer")
        self.write_final_parent()
        attack_a = self.attack_checkout("attack-a")
        attack_b = self.attack_checkout("attack-b")
        receipts = [self.writer_receipt("codex", writer), self.receipt("claude", "rw", attack_a), self.receipt("grok", "rw", attack_b)]
        rerun = f"cd {attack_a} && python3 -m unittest test_repro"
        finding = {"adversary": "xagent:claude", "worktree": str(attack_a), "command": rerun, "kept": True}
        reruns = [ShellCommand(rerun, [str(attack_a)], ran=True)]
        self.assertEqual(self.valid_receipts(receipts, findings=[finding], parent_commands=reruns), ALL_CHECKS_PASS)
        self.assertTrue(self.valid_receipts(receipts, findings=[], parent_commands=())["findings_rerun_by_parent"])
        # Whitespace aside, the ledger holds the command as it ran, here in the worktree as its working directory.
        in_worktree = [ShellCommand("python3  -m unittest test_repro\n", [str(attack_a)], ran=True)]
        self.assertTrue(self.valid_receipts(receipts, findings=[{**finding, "command": "python3 -m unittest test_repro"}],
                                            parent_commands=in_worktree)["findings_rerun_by_parent"])
        ledger = json.dumps([finding])
        for case, findings, commands in (
            ("no ledger", None, reruns),
            ("the parent never ran it", [finding], ()),
            # thermos round 4: the host stopped the call before it ran, as a permission rule does.
            ("the parent's rerun was refused", [finding], [ShellCommand(rerun, [str(attack_a)])]),
            ("the parent ran another command", [{**finding, "command": f"cd {attack_a} && python3 -m unittest test_other"}], reruns),
            ("the rerun ran in another worktree", [{**finding, "command": "python3 -m unittest test_repro"}],
             [ShellCommand("python3 -m unittest test_repro", [str(attack_b)], ran=True)]),
            ("the worktree is another adversary's", [{**finding, "adversary": "xagent:grok"}], reruns),
            # thermos round 1: commands that only mention the rerun, or run more than it.
            ("only the heredoc that wrote the ledger", [finding],
             [ShellCommand(f"cat > {self.scope}/findings.json <<'EOF'\n{ledger}\nEOF", [str(attack_a)], ran=True)]),
            ("only an echo of it", [finding], [ShellCommand(f"echo '{rerun}'", [str(attack_a)], ran=True)]),
            ("a setup command that contains it", [{**finding, "command": "python3 -m unittest"}],
             [ShellCommand(f"cd {attack_a} && git status && python3 -m unittest", [str(attack_a)], ran=True)]),
        ):
            with self.subTest(case):
                self.assertFalse(self.valid_receipts(receipts, findings=findings, parent_commands=commands)["findings_rerun_by_parent"])

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

    def exercise_claude_stub(self, edit, check_timeout):
        """Run exercise for a stub Claude host that runs edit, Python source, in the parent checkout and fails its
        reply; return the run's claude directory."""
        binaries = self.root / "bin"
        binaries.mkdir()
        stub = binaries / "claude"
        stub.write_text(
            "#!/usr/bin/env python3\n"
            "from pathlib import Path\nimport json\n"
            f"{edit}\n"
            "print(json.dumps({'type': 'result', 'result': 'PSTACK_E2E: FAIL'}))\n"
        )
        stub.chmod(0o755)
        run = self.root / "bounded-run"
        command = (
            "import runpy,sys;from pathlib import Path;"
            "h=runpy.run_path(sys.argv[1]);"
            f"h['exercise']('claude',Path(sys.argv[2]),5,check_timeout={check_timeout})"
        )
        result = subprocess.run(
            [sys.executable, "-B", "-c", command, str(ROOT / "scripts/pstack-host-e2e.py"), str(run)],
            env={**os.environ, "PATH": str(binaries) + os.pathsep + os.environ["PATH"]},
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return run / "claude"

    def test_given_host_leaves_nonterminating_code_when_independently_verified_then_harness_finishes_failed(self):
        directory = self.exercise_claude_stub("Path('stats.py').write_text('def mean(xs):\\n    while True:\\n        pass\\n')", 1)
        run = directory.parent
        report = json.loads((directory / "checks.json").read_text())
        self.assertTrue(report["checks"]["host_exited"])
        self.assertFalse(report["checks"]["fix_passes_independent_rerun"])
        self.assertFalse(report["checks"]["finite_number_contract_preserved"])
        self.assertIsNone(report["findings"])
        self.assertFalse(report["checks"]["findings_rerun_by_parent"])
        self.assertEqual(report["verification"]["tests_exit_code"], 124)
        self.assertEqual(report["verification"]["contract_exit_code"], 124)
        for name in ("after-tests.log", "contract-probe.log"):
            self.assertIn("timed out", (run / "claude" / name).read_text())

    def test_given_a_check_timeout_shorter_than_a_python_start_when_exercised_then_the_fixture_check_still_runs(self):
        # thermos round 2 of #33: the fixture check before the host took --check-timeout, so a short one failed the run
        # before the host started, and the 1 s test above failed under load.
        directory = self.exercise_claude_stub("pass", 0.05)
        self.assertIn("FAILED (failures=1)", (directory / "before-tests.log").read_text())
        self.assertTrue(json.loads((directory / "checks.json").read_text())["checks"]["host_exited"])

    def final_handoff_receipts(self):
        self.write_final_parent()
        receipts = []
        receipts.append(self.writer_receipt("codex", self.add_worktree("codex")))
        for agent in ("claude", "grok"):
            receipts.append(self.receipt(agent, "rw", self.attack_checkout(agent)))
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


if __name__ == "__main__":
    unittest.main()
