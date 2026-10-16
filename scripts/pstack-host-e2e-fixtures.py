"""Shared fixtures for the host harness tests: a synthetic parent checkout, linked worktrees and xagent receipts."""
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = runpy.run_path(str(ROOT / "scripts/pstack-host-e2e.py"))
XAGENT = runpy.run_path(str(ROOT / "bin/xagent"))

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


class HarnessFixture(unittest.TestCase):
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
        for artifact in XAGENT["OUT_FILES"]:
            (receipt_path.parent / artifact).write_text("")
        result = {
            "path": str(receipt_path), "agent": agent, "model": None, "effort": None, "mode": mode, "workdir": str(workdir),
            "exit": 0, "timed_out": False, "cancelled": False, "seconds": 1.0, "status": "PASS",
            "changed_workdir": False if mode == "ro" else None, "snapshot_before": None, "snapshot_after": None,
            "completed": True, "reason": None,
        }
        if mode == "ro":
            digest = XAGENT["snapshot"](workdir.resolve(), receipt_path.parent.resolve())
            result.update(snapshot_before=digest, snapshot_after=digest)
        result.update(overrides)
        receipt_path.write_text(json.dumps(result) + "\n")
        return result

    def valid_receipts(self, receipts, writer="xagent:codex", reviewers=("xagent:claude", "xagent:grok"), native_dispatches=(), effort=None):
        return HARNESS["validate_receipts"](
            receipts, self.scope, self.parent, self.base, writer, list(reviewers),
            (self.parent / "stats.py").read_bytes(), TEST_SOURCE.encode(), native_dispatches, effort,
        )

    def final_checkout(self, name, stats=FIXED_STATS):
        """A worktree at the fixture base with stats.py changed but uncommitted."""
        checkout = self.add_worktree(name)
        (checkout / "stats.py").write_text(stats)
        return checkout

    def committed_checkout(self, name):
        """A worktree whose patch is committed, so it has left the fixture base."""
        checkout = self.final_checkout(name)
        self.git(checkout, "-c", "user.name=fixture", "-c", "user.email=fixture@local", "-c", "commit.gpgsign=false", "commit", "-qam", "writer commit")
        return checkout

    def xagent_reviews_for(self, reviewers):
        """Final-code receipts for the policy's xagent reviewers; native entries get none."""
        self.write_final_parent()
        receipts = []
        for value in reviewers:
            if not value.startswith("xagent:"):
                continue
            agent, model = XAGENT["agent_spec"](value.removeprefix("xagent:"))
            checkout = self.add_worktree(f"review-{agent}")
            (checkout / "stats.py").write_text(FIXED_STATS)
            receipts.append(self.receipt(agent, "ro", checkout, model=model))
        return receipts

    def write_verifier_receipt(self, final_hash):
        (self.scope / "parent-verification.json").write_text(json.dumps({
            "cwd": str(self.parent.resolve()), "parent": str(self.parent.resolve()),
            "stats_sha256_before": final_hash, "stats_sha256_after": final_hash,
            "tests_exit_code": 0, "contract_exit_code": 0, "passed": True,
        }) + "\n")
