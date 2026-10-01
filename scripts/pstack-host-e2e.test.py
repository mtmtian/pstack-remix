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
        result = {
            "path": str(receipt_path),
            "agent": agent,
            "mode": mode,
            "workdir": str(workdir),
            "exit": 0,
            "timed_out": False,
            "cancelled": False,
            "status": "PASS",
            "changed_workdir": False if mode == "ro" else None,
            "completed": True,
        }
        if mode == "ro":
            digest = snapshot(workdir.resolve(), receipt_path.parent.resolve())
            result.update(snapshot_before=digest, snapshot_after=digest)
        result.update(overrides)
        receipt_path.write_text(json.dumps(result) + "\n")
        return result

    def valid_receipts(self, receipts):
        return validate_receipts(
            receipts,
            self.scope,
            self.parent,
            self.base,
            "xagent:writer",
            ["xagent:review-a", "xagent:review-b"],
            (self.parent / "stats.py").read_bytes(),
            TEST_SOURCE.encode(),
        )

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

    def test_given_disposable_hosts_then_they_and_their_workers_disable_session_persistence(self):
        binaries = self.root / "bin"
        binaries.mkdir()
        for host in ("claude", "codex"):
            stub = binaries / host
            stub.write_text(
                "#!/usr/bin/env python3\n"
                "from pathlib import Path\nimport json, os, sys\n"
                "capture = {'argv': sys.argv[1:], 'ephemeral': os.environ.get('XAGENT_EPHEMERAL')}\n"
                "Path(os.environ['PSTACK_TEST_HOST_CAPTURE']).write_text(json.dumps(capture))\n"
                "reply = 'PSTACK_E2E: FAIL'\n"
                "if Path(sys.argv[0]).name == 'codex':\n"
                "    Path(sys.argv[sys.argv.index('-o') + 1]).write_text(reply)\n"
                "else:\n"
                "    print(json.dumps({'type': 'result', 'result': reply}))\n"
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
                    env={**os.environ, "PATH": str(binaries) + os.pathsep + os.environ["PATH"],
                         "XAGENT_EPHEMERAL": "0", "PSTACK_TEST_HOST_CAPTURE": str(captured)},
                    capture_output=True, text=True, timeout=15,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                launch = json.loads(captured.read_text())
                self.assertEqual(launch["ephemeral"], "1")
                if host == "claude":
                    self.assertIn("-p", launch["argv"])
                    self.assertIn("--no-session-persistence", launch["argv"])
                else:
                    self.assertIn("--ephemeral", launch["argv"])
                    self.assertIn('shell_environment_policy.set.XAGENT_EPHEMERAL="1"', launch["argv"])

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
