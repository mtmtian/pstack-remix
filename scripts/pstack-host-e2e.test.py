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
classify_host_reply = HARNESS["classify_host_reply"]
validate_parent_verification = HARNESS["validate_parent_verification"]
write_parent_verifier = HARNESS["write_parent_verifier"]


class HostHarnessAcceptanceTest(FIXTURES["HarnessFixture"]):
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

    def test_given_a_policy_without_swarm_or_interrogate_entries_when_roles_resolve_then_the_helper_defaults_apply(self):
        shown = json.loads(subprocess.check_output(
            ["node", str(ROOT / "bin/config.mjs"), "show", "--host", "claude", "--config", str(self.root / "absent.json")], text=True))
        effective = shown["effective"]
        self.assertEqual(HARNESS["expected_roles"](effective), (effective["defaultModel"], effective["defaultPanel"]))

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

    def test_given_one_reviewer_entry_twice_when_both_receipts_share_a_worktree_then_only_one_review_counts(self):
        # Third review round, scenario H, and Codex's review of fc4805e: each review slot needs a worktree of its own.
        writer = self.final_checkout("writer")
        self.write_final_parent()
        written = self.receipt("codex", "rw", writer)
        for agent in ("grok", "claude"):
            with self.subTest(agent):
                shared = self.final_checkout(f"review-{agent}")
                first, second = (self.receipt(agent, "ro", shared, name=f"ro-{agent}-{index}") for index in (1, 2))
                checks = self.valid_receipts([written, first, second], reviewers=(f"xagent:{agent}",) * 2)
                self.assertEqual((checks["receipt_workspaces_owned"], checks["configured_reviewers_dispatched"]), (True, False))
                # A retry of the same reviewer for one slot may reuse its worktree.
                dropout = self.receipt(agent, "ro", shared, name=f"ro-{agent}-dropout", status="DROPOUT", exit=3)
                self.assertEqual(self.valid_receipts([written, dropout, first], reviewers=(f"xagent:{agent}",)), ALL_CHECKS_PASS)

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


if __name__ == "__main__":
    unittest.main()
