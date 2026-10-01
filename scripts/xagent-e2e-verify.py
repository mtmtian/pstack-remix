#!/usr/bin/env python3
"""Fixed fixture and evidence checks for scripts/xagent-e2e.sh."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path


TEST_SOURCE = '''import hashlib
import json
import unittest
from pathlib import Path

from stats import mean


class MeanTest(unittest.TestCase):
    def test_mean(self):
        stats_hash_before = hashlib.sha256(Path(__file__).with_name("stats.py").read_bytes()).hexdigest()
        self.assertEqual(mean([2, 4, 6]), 4)
        stats_hash_after = hashlib.sha256(Path(__file__).with_name("stats.py").read_bytes()).hexdigest()
        self.assertEqual(stats_hash_after, stats_hash_before)
        receipt = {"passed": True, "stats_sha256": stats_hash_before}
        Path(__file__).with_name(".test-ran").write_text(json.dumps(receipt) + "\\n")
'''
TEST_SHA256 = hashlib.sha256(TEST_SOURCE.encode()).hexdigest()


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def write_fixture_test(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(TEST_SOURCE)


def check_test_integrity(repo: Path) -> list[str]:
    errors = []
    path = repo / "test_stats.py"
    if not path.is_file() or path.is_symlink():
        errors.append("test_stats.py is missing or is not a regular file")
    else:
        actual = digest(path.read_bytes())
        if actual != TEST_SHA256:
            errors.append(f"working test_stats.py sha256 {actual}, expected {TEST_SHA256}")

    for revision, spec in (("index", ":test_stats.py"), ("HEAD", "HEAD:test_stats.py")):
        result = subprocess.run(
            ["git", "-C", str(repo), "show", spec],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if result.returncode:
            errors.append(f"{revision} test_stats.py is unavailable")
        else:
            actual = digest(result.stdout)
            if actual != TEST_SHA256:
                errors.append(f"{revision} test_stats.py sha256 {actual}, expected {TEST_SHA256}")
    return errors


def check_worker_receipt(repo: Path) -> list[str]:
    receipt_path = repo / ".test-ran"
    try:
        receipt = json.loads(receipt_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return [f"worker test receipt is missing or invalid: {exc}"]

    stats_path = repo / "stats.py"
    if not stats_path.is_file() or stats_path.is_symlink():
        return ["stats.py is missing or is not a regular file"]
    current_stats_hash = digest(stats_path.read_bytes())
    errors = []
    if not isinstance(receipt, dict):
        return ["worker test receipt is not an object"]
    if receipt.get("passed") is not True:
        errors.append("worker test receipt does not record a passing test")
    if receipt.get("stats_sha256") != current_stats_hash:
        errors.append("worker test receipt is for a different stats.py hash")
    return errors


def report_check(name: str, errors: list[str]) -> int:
    if errors:
        for error in errors:
            print(f"FAIL {name}: {error}", file=sys.stderr)
        return 1
    print(f"PASS {name}")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] not in {"write-test", "check-test", "check-receipt"}:
        print("usage: xagent-e2e-verify.py {write-test|check-test|check-receipt} REPO", file=sys.stderr)
        return 2
    repo = Path(argv[2])
    if argv[1] == "write-test":
        write_fixture_test(repo / "test_stats.py")
        return 0
    if argv[1] == "check-test":
        return report_check("fixture test integrity", check_test_integrity(repo))
    return report_check("worker test receipt", check_worker_receipt(repo))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
