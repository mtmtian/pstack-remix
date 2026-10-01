import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
verify_spec = importlib.util.spec_from_file_location(
    "xagent_e2e_verify", Path(__file__).with_name("xagent-e2e-verify.py")
)
verify = importlib.util.module_from_spec(verify_spec)
verify_spec.loader.exec_module(verify)


BUGGY_STATS = "def mean(xs):\n    return sum(xs) / (len(xs) - 1)\n"
FIXED_STATS = "def mean(xs):\n    return sum(xs) / len(xs)\n"


class VerifyFixtureTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="xagent-e2e-verify-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def make_repo(self, name):
        repo = self.root / name
        repo.mkdir()
        (repo / "stats.py").write_text(BUGGY_STATS)
        verify.write_fixture_test(repo / "test_stats.py")
        (repo / ".gitignore").write_text(".test-ran\n__pycache__/\n")
        self.git(repo, "init", "-q")
        self.git(repo, "add", ".")
        self.git(
            repo,
            "-c", "user.name=e2e",
            "-c", "user.email=e2e@local",
            "-c", "commit.gpgsign=false",
            "commit", "-qm", "fixture",
        )
        return repo

    def git(self, repo, *args):
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def run_unittest(self, repo):
        return subprocess.run(
            [sys.executable, "-m", "unittest", "-q"],
            cwd=repo,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

    def test_unstaged_staged_and_committed_test_rewrites_are_rejected(self):
        for mode in ("unstaged", "staged", "committed"):
            with self.subTest(mode=mode):
                repo = self.make_repo(mode)
                test_path = repo / "test_stats.py"
                test_path.write_text(test_path.read_text() + "# rewritten\n")
                if mode in ("staged", "committed"):
                    self.git(repo, "add", "test_stats.py")
                    old_gate = subprocess.run(
                        ["git", "-C", str(repo), "diff", "--quiet", "--", "test_stats.py"],
                        check=False,
                    )
                    self.assertEqual(old_gate.returncode, 0, "the former worktree-only gate misses this rewrite")
                if mode == "committed":
                    self.git(
                        repo,
                        "-c", "user.name=e2e",
                        "-c", "user.email=e2e@local",
                        "-c", "commit.gpgsign=false",
                        "commit", "-qm", "rewritten test",
                    )
                self.assertTrue(verify.check_test_integrity(repo), mode)

    def test_real_unittest_success_writes_hash_bound_worker_receipt(self):
        repo = self.make_repo("passing")
        (repo / "stats.py").write_text(FIXED_STATS)

        result = self.run_unittest(repo)

        self.assertEqual(result.returncode, 0, result.stdout)
        receipt = json.loads((repo / ".test-ran").read_text())
        expected_hash = hashlib.sha256((repo / "stats.py").read_bytes()).hexdigest()
        self.assertIs(receipt["passed"], True)
        self.assertEqual(receipt["stats_sha256"], expected_hash)
        self.assertEqual(verify.check_test_integrity(repo), [])
        self.assertEqual(verify.check_worker_receipt(repo), [])

    def test_import_only_does_not_create_worker_receipt(self):
        repo = self.make_repo("import-only")
        sys.modules.pop("stats", None)
        sys.path.insert(0, str(repo))
        try:
            spec = importlib.util.spec_from_file_location("worker_test_stats", repo / "test_stats.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        finally:
            sys.path.remove(str(repo))
            sys.modules.pop("stats", None)

        self.assertFalse((repo / ".test-ran").exists())
        self.assertTrue(verify.check_worker_receipt(repo))

    def test_failed_real_unittest_does_not_create_worker_receipt(self):
        repo = self.make_repo("failing")

        result = self.run_unittest(repo)

        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertFalse((repo / ".test-ran").exists())
        self.assertTrue(verify.check_worker_receipt(repo))

    def test_stats_change_during_assertion_does_not_create_receipt(self):
        repo = self.make_repo("changing-stats")
        (repo / "stats.py").write_text(
            "from pathlib import Path\n"
            "def mean(xs):\n"
            "    path = Path(__file__)\n"
            "    path.write_text(path.read_text() + '# changed during test\\n')\n"
            "    return 4\n"
        )

        result = self.run_unittest(repo)

        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertFalse((repo / ".test-ran").exists())
        self.assertTrue(verify.check_worker_receipt(repo))

    def test_empty_legacy_marker_and_receipt_for_old_stats_are_rejected(self):
        repo = self.make_repo("stale-receipt")
        (repo / ".test-ran").write_text("")
        self.assertTrue(verify.check_worker_receipt(repo), "the old empty touch-file marker is invalid")

        old_stats_hash = hashlib.sha256((repo / "stats.py").read_bytes()).hexdigest()
        stale_receipt = {
            "passed": True,
            "stats_sha256": old_stats_hash,
        }
        (repo / ".test-ran").write_text(json.dumps(stale_receipt))
        (repo / "stats.py").write_text(FIXED_STATS)
        errors = verify.check_worker_receipt(repo)
        self.assertIn("worker test receipt is for a different stats.py hash", errors)

    def test_shell_fixture_phase_keeps_host_recheck_command_in_prompt(self):
        script = Path(__file__).with_name("xagent-e2e.sh").resolve()
        harness = script.read_text()
        boundary = "# Readers without an enforced read-only sandbox must not share the parent checkout either."
        prefix = harness.split(boundary, 1)[0]
        stub_bin = self.root / "stub-bin"
        stub_bin.mkdir()
        claude_stub = stub_bin / "claude"
        claude_stub.write_text("#!/bin/sh\nexit 1\n")
        claude_stub.chmod(0o755)
        run_dir = self.root / "shell-run"
        env = os.environ.copy()
        env["PATH"] = str(stub_bin) + os.pathsep + env["PATH"]

        result = subprocess.run(
            ["bash", "-c", prefix, str(script), str(run_dir)],
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")
        prompt = (run_dir / "host.md").read_text()
        self.assertIn('python3 "' + str(script.parents[1] / "scripts/e2e-process.py") + '" --timeout 30', prompt)
        self.assertIn('-- python3 -m unittest -q', prompt)
        self.assertTrue((run_dir / "repo/test_stats.py").is_file())
        self.assertFalse((run_dir / "wt-host-pi").exists(), "fixture phase must stop before worktree/vendor execution")


if __name__ == "__main__":
    unittest.main()
