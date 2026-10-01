#!/usr/bin/env python3
"""Exercise real swarm -> interrogate policy routing from Claude and Codex on a synthetic repo."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
import os
from pathlib import Path
import runpy
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
RUN_CHECK = runpy.run_path(str(ROOT / "scripts/e2e-process.py"))["run_check"]
CONTRACT_PROBE = '''from fractions import Fraction
from stats import mean

assert mean([1e308, 1e308]) == 1e308
assert mean([10**309, 10**309 + 1]) == Fraction(2 * 10**309 + 1, 2)
print("finite-number contract: PASS")
'''
TEST = '''import unittest
from stats import mean

class MeanTest(unittest.TestCase):
    def test_mean(self):
        with open(".test-ran", "a") as receipt:
            receipt.write("ran\\n")
        self.assertEqual(mean([2, 4, 6]), 4)
        self.assertEqual(mean([5]), 5)
        self.assertEqual(mean([-3, -1, 4]), 0)
'''
XAGENT = runpy.run_path(str(ROOT / "bin/xagent"))
CLASSIFY = XAGENT["classify"]
SNAPSHOT = XAGENT["snapshot"]

PARENT_VERIFIER_TEMPLATE = r'''#!/usr/bin/env python3
import hashlib
import json
from pathlib import Path
import runpy
import sys

CONTRACT_PROBE = __CONTRACT_PROBE__
RUN_CHECK = runpy.run_path(__PROCESS_HELPER__)["run_check"]
CHECK_TIMEOUT = __CHECK_TIMEOUT__

def sha256(path):
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None

def run_and_log(command, cwd, stdout_path, stderr_path):
    result = RUN_CHECK(command, cwd, CHECK_TIMEOUT)
    stdout_path.write_text(result.stdout)
    stderr_path.write_text(result.stderr)
    return result.returncode

def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: verify-parent.py <parent-repo>")
    parent = Path(sys.argv[1]).resolve()
    actual_cwd = Path.cwd().resolve()
    directory = Path(__file__).resolve().parent
    stats = parent / "stats.py"
    before = sha256(stats)
    tests_exit = run_and_log(
        ["python3", "-B", "-m", "unittest", "-q"], parent,
        directory / "parent-tests.stdout.log", directory / "parent-tests.stderr.log",
    )
    contract_exit = run_and_log(
        ["python3", "-B", "-c", CONTRACT_PROBE], parent,
        directory / "parent-contract.stdout.log", directory / "parent-contract.stderr.log",
    )
    after = sha256(stats)
    passed = (
        actual_cwd == parent and before is not None and before == after
        and tests_exit == 0 and contract_exit == 0
    )
    receipt = {
        "cwd": str(actual_cwd),
        "parent": str(parent),
        "stats_sha256_before": before,
        "stats_sha256_after": after,
        "tests_exit_code": tests_exit,
        "contract_exit_code": contract_exit,
        "check_timeout_seconds": CHECK_TIMEOUT,
        "passed": passed,
        "logs": {
            "tests_stdout": "parent-tests.stdout.log",
            "tests_stderr": "parent-tests.stderr.log",
            "contract_stdout": "parent-contract.stdout.log",
            "contract_stderr": "parent-contract.stderr.log",
        },
    }
    (directory / "parent-verification.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, sort_keys=True))
    return 0 if passed else 1

if __name__ == "__main__":
    raise SystemExit(main())
'''


def classify_host_reply(code, reply):
    """Apply xagent's terminal-verdict rules to a host's complete reply."""
    return CLASSIFY(code, False, reply.replace("PSTACK_E2E:", "STATUS:"))


def write_parent_verifier(directory, check_timeout=30):
    directory = Path(directory).resolve()
    verifier = directory / "verify-parent.py"
    source = PARENT_VERIFIER_TEMPLATE.replace("__CONTRACT_PROBE__", repr(CONTRACT_PROBE))
    source = source.replace("__PROCESS_HELPER__", repr(str(ROOT / "scripts/e2e-process.py")))
    source = source.replace("__CHECK_TIMEOUT__", repr(check_timeout))
    verifier.write_text(source)
    verifier.chmod(0o755)
    return verifier


def _git_output(workdir, *args):
    try:
        result = subprocess.run(
            ["git", "-C", str(workdir), *args],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()
    except (OSError, subprocess.CalledProcessError, ValueError):
        return None


def _git_path(workdir, option):
    value = _git_output(workdir, "rev-parse", option)
    if not value:
        return None
    path = Path(value)
    try:
        return (path if path.is_absolute() else Path(workdir) / path).resolve()
    except (OSError, RuntimeError, ValueError):
        return None


def _valid_linked_worktree(receipt, run_scope, parent, base, parent_common):
    try:
        if not isinstance(receipt, dict):
            return None
        raw_workdir = receipt.get("workdir")
        if not isinstance(raw_workdir, str) or not raw_workdir:
            return None
        workdir = Path(raw_workdir).resolve()
        scope = Path(run_scope).resolve()
        parent = Path(parent).resolve()
        if workdir == parent or not workdir.is_relative_to(scope):
            return None
        top = _git_output(workdir, "rev-parse", "--show-toplevel")
        head = _git_output(workdir, "rev-parse", "HEAD")
        common = _git_path(workdir, "--git-common-dir")
        git_dir = _git_path(workdir, "--git-dir")
        if not top or Path(top).resolve() != workdir or head != base:
            return None
        if not parent_common or common != parent_common or not git_dir or git_dir == common:
            return None
        if not git_dir.is_relative_to(parent_common / "worktrees"):
            return None
        git_marker = workdir / ".git"
        if not git_marker.is_file():
            return None
        worktree_list = _git_output(parent, "worktree", "list", "--porcelain")
        if worktree_list is None:
            return None
        listed_paths = []
        for line in worktree_list.splitlines():
            if line.startswith("worktree "):
                listed_paths.append(Path(line.removeprefix("worktree ")).resolve())
        if workdir not in listed_paths:
            return None
        mode, agent = receipt.get("mode"), receipt.get("agent")
        if mode not in ("rw", "ro") or not isinstance(agent, str) or not agent:
            return None
        return workdir, (mode, agent)
    except (OSError, RuntimeError, TypeError, ValueError):
        return None


def validate_parent_verification(directory, parent):
    try:
        directory = Path(directory).resolve()
        parent = Path(parent).resolve()
        receipt = json.loads((directory / "parent-verification.json").read_text())
        if not isinstance(receipt, dict):
            return False
        if receipt.get("cwd") != str(parent) or receipt.get("parent") != str(parent):
            return False
        stats_hash = hashlib.sha256((parent / "stats.py").read_bytes()).hexdigest()
        before = receipt.get("stats_sha256_before")
        after = receipt.get("stats_sha256_after")
        if not isinstance(before, str) or before != after or before != stats_hash:
            return False
        if receipt.get("tests_exit_code") != 0 or type(receipt.get("tests_exit_code")) is not int:
            return False
        if receipt.get("contract_exit_code") != 0 or type(receipt.get("contract_exit_code")) is not int:
            return False
        return receipt.get("passed") is True
    except (OSError, RuntimeError, TypeError, ValueError, KeyError):
        return False


def validate_receipts(receipts, run_scope, parent, base, expected_writer, expected_reviewers, final_stats, test_file):
    """Validate dispatches, workspace ownership, and reviewer version evidence."""
    try:
        receipts = list(receipts)
        all_terminal = bool(receipts) and all(
            isinstance(receipt, dict) and receipt.get("completed") is True
            and receipt.get("status") in ("PASS", "ISSUES", "BLOCKED", "DROPOUT")
            for receipt in receipts
        )
        run_scope, parent = Path(run_scope).resolve(), Path(parent).resolve()
        parent_common = _git_path(parent, "--git-common-dir")
        parent_top = _git_output(parent, "rev-parse", "--show-toplevel")
        if not parent_top or Path(parent_top).resolve() != parent:
            parent_common = None
        valid_workdirs = {}
        owners = {}
        workspaces_valid = bool(receipts) and parent_common is not None
        for index, receipt in enumerate(receipts):
            validated = _valid_linked_worktree(receipt, run_scope, parent, base, parent_common)
            if validated is None:
                workspaces_valid = False
                continue
            workdir, owner = validated
            prior_owner = owners.get(workdir)
            if prior_owner is not None and prior_owner != owner:
                workspaces_valid = False
            owners[workdir] = owner
            valid_workdirs[index] = workdir

        def matches(receipt, agent, mode, allowed_statuses):
            if not isinstance(receipt, dict):
                return False
            if receipt.get("agent") != agent or receipt.get("mode") != mode:
                return False
            if receipt.get("completed") is not True or receipt.get("status") not in allowed_statuses:
                return False
            if type(receipt.get("exit")) is not int or receipt.get("exit") != 0:
                return False
            return True

        writer_agent = expected_writer.removeprefix("xagent:") if isinstance(expected_writer, str) and expected_writer.startswith("xagent:") else None
        # ISSUES may carry a usable patch; final parent checks and reviews remain mandatory.
        writer_ok = bool(writer_agent) and any(
            index in valid_workdirs and matches(receipt, writer_agent, "rw", ("PASS", "ISSUES"))
            for index, receipt in enumerate(receipts)
        )

        reviewer_agents = []
        if isinstance(expected_reviewers, list):
            reviewer_agents = [
                value.removeprefix("xagent:") if isinstance(value, str) and value.startswith("xagent:") else None
                for value in expected_reviewers
            ]
        reviewer_ok = bool(reviewer_agents) and all(reviewer_agents)
        available = set(range(len(receipts)))
        for agent in reviewer_agents:
            matching_index = None
            for index in sorted(available):
                receipt = receipts[index]
                workdir = valid_workdirs.get(index)
                if workdir is None or not matches(receipt, agent, "ro", ("PASS", "ISSUES")):
                    continue
                if receipt.get("changed_workdir") is not False:
                    continue
                try:
                    before, after = receipt.get("snapshot_before"), receipt.get("snapshot_after")
                    if not isinstance(before, str) or before != after:
                        continue
                    if SNAPSHOT(workdir, Path(receipt["path"]).parent.resolve()) != after:
                        continue
                    if (workdir / "stats.py").read_bytes() != final_stats:
                        continue
                    if (workdir / "test_stats.py").read_bytes() != test_file:
                        continue
                except (OSError, ValueError, KeyError, subprocess.CalledProcessError):
                    continue
                matching_index = index
                break
            if matching_index is None:
                reviewer_ok = False
            else:
                available.remove(matching_index)

        return {
            "all_attempts_terminal": all_terminal,
            "configured_writer_dispatched": writer_ok,
            "configured_reviewers_dispatched": reviewer_ok,
            "receipt_workspaces_owned": workspaces_valid,
        }
    except (OSError, RuntimeError, TypeError, ValueError):
        return {
            "all_attempts_terminal": False,
            "configured_writer_dispatched": False,
            "configured_reviewers_dispatched": False,
            "receipt_workspaces_owned": False,
        }


def git(work, *args):
    return subprocess.run(["git", "-C", str(work), *args], check=True, text=True, capture_output=True).stdout.strip()


def exercise(host, run, host_timeout, check_timeout=30):
    directory = run / host
    work = directory / "repo"
    work.mkdir(parents=True)
    evidence = directory / "evidence"
    evidence.mkdir()
    verifier = write_parent_verifier(directory, check_timeout)
    (work / "stats.py").write_text("def mean(xs):\n    return sum(xs) / (len(xs) - 1)\n")
    (work / "test_stats.py").write_text(TEST)
    (work / ".gitignore").write_text(".test-ran\n__pycache__/\n")
    git(work, "init", "-q", "--initial-branch=main")
    git(work, "add", ".")
    git(work, "-c", "user.name=e2e", "-c", "user.email=e2e@local", "-c", "commit.gpgsign=false", "commit", "-qm", "fixture")
    base = git(work, "rev-parse", "HEAD")
    failing = RUN_CHECK([sys.executable, "-m", "unittest", "-q"], work, check_timeout)
    (directory / "before-tests.log").write_text(failing.stdout + failing.stderr)
    if failing.returncode != 1:
        raise AssertionError(f"expected a failing test fixture, got exit {failing.returncode}")
    (work / ".test-ran").unlink()
    policy = json.loads(subprocess.check_output(["node", str(ROOT / "bin/config.mjs"), "show", "--host", host], text=True))
    (directory / "policy.json").write_text(json.dumps(policy, indent=2) + "\n")
    (directory / "contract-probe.py").write_text(CONTRACT_PROBE)
    prompt = f'''Run a real pstack workflow acceptance test from the local candidate checkout {ROOT}.
Read and follow {ROOT}/references/runtime.md and {ROOT}/references/{host}-runtime.md, then execute
{ROOT}/skills/swarm/SKILL.md and {ROOT}/skills/interrogate/SKILL.md.
The candidate checkout's bundled runtime and skills are authoritative for this test, not another installed copy.
Resolve the real current pstack policy for your host ({host}) yourself. Do not run setup or change preferences.

Task: fix stats.py so mean returns the arithmetic mean for nonempty lists of finite numbers.
Empty lists and other types are outside this fixture's contract. Keep test_stats.py byte-for-byte unchanged.
The contract includes finite integers beyond the float range; an exact rational result is permitted when
the mathematical mean cannot be represented as a finite float. The independent acceptance probe is
{directory}/contract-probe.py; run it from the parent checkout with python3 -B -c and its file contents.
Use swarm with one worker for this one-file repair. Select its agent from the effective policy, not by guessing.
The writer can run python3 -m unittest -q from the shared allowlist. Do not require it to use -B or -c;
the parent owns the contract probe and final verification commands below.
Give the writer an exclusive worktree from fixture base {base}; keep all worktrees and outputs under {directory}.
The parent checkout is {work}. Integrate the worker's patch locally, then run python3 -m unittest yourself.
Use interrogate on the resulting change with all configured reviewers, selected from the effective policy.
Reviewers get separate worktrees containing the proposed patch. Preserve parent and worker evidence.
Fix any real in-scope findings and rerun the affected check; do not count a dropout, cancelled run, or missing evidence as a pass.
Both host controllers run one-shot/headless. Do not send the final reply until every external command and reviewer
has completed and you have inspected its terminal output and receipt. When running xagent commands in parallel,
start them with & in one foreground Bash call, capture every PID, and wait for every PID; give the call a timeout
longer than the 240-second attempt limit plus termination grace and enough time for the allowed retry. Do not
promise later notifications, rely on Monitor or shell sentinels, or use TaskOutput (it is not an available tool).
Follow the host adapter's supported tools and wait behavior.

After all integrations, fixes, and configured reviews are complete, personally run the final parent verification
from the parent checkout by executing exactly: python3 {verifier} {work}
The helper runs python3 -B -m unittest -q and the contract probe, writes separate stdout/stderr logs plus
{directory}/parent-verification.json, and exits nonzero if the real cwd, stable stats.py hash, or either check fails.
Each verification command has a {check_timeout:g}-second deadline and terminates its process group on timeout.
Do not edit stats.py after running it. The harness checks that this receipt describes the final parent version,
then independently reruns the tests and contract probe.

Every xagent attempt must write to a new subdirectory under {evidence}. Limit each worker to 240 seconds and at most one retry.
Use only this synthetic fixture and local candidate skill files. The human has authorized this real multi-vendor E2E,
including sending this synthetic code and the standalone briefs to the locally configured agents.
No extra confirmation is needed for those calls. Do not push, publish, change global settings, contact people, or edit the candidate plugin.
Workers must remain leaves. Do not replace configured external agents with native workers.
Report the resolved routes, actual worker receipt paths, findings, your own test output, and any gaps.
End with PSTACK_E2E: PASS only if the repair, all configured reviews and your independent tests are complete,
with no unresolved reproduced violation of the stated contract; otherwise PSTACK_E2E: FAIL.
'''
    (directory / "prompt.md").write_text(prompt)
    if host == "codex":
        args = ["codex", "exec", "--skip-git-repo-check", "--ephemeral", "--json", "-C", str(work), "-o", str(directory / "result.md"), "-"]
    else:
        args = ["claude", "-p", "--output-format", "stream-json", "--verbose", "--permission-mode", "acceptEdits", "--plugin-dir", str(ROOT), "--allowedTools", "Bash", "Read", "Write", "Edit", "Glob", "Grep"]
    env = dict(os.environ)
    env.pop("XAGENT_DEPTH", None)
    with (directory / "host.log").open("w") as log:
        finished = subprocess.run(["timeout", "-k", "5", str(host_timeout), *args], cwd=work, env=env, input=prompt, text=True, stdout=log, stderr=subprocess.STDOUT)
    if host == "claude":
        for line in (directory / "host.log").read_text().splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict) and event.get("type") == "result" and isinstance(event.get("result"), str):
                (directory / "result.md").write_text(event["result"])
    try:
        reply = (directory / "result.md").read_text()
    except (OSError, UnicodeError):
        reply = ""
    receipts = []
    for file in sorted(evidence.rglob("meta.json")):
        try:
            receipt = json.loads(file.read_text())
            receipts.append({**receipt, "path": str(file)} if isinstance(receipt, dict) else None)
        except (OSError, UnicodeError, ValueError):
            receipts.append(None)
    expected_writer = policy["effective"]["roles"].get("swarm workers", "inherit-parent")
    expected_reviewers = policy["effective"]["panels"].get("interrogate reviewers", [])
    try:
        test_file_preserved = (work / "test_stats.py").read_text() == TEST
    except (OSError, UnicodeError):
        test_file_preserved = False
    final_stats = (work / "stats.py").read_bytes() if (work / "stats.py").is_file() else b""
    receipt_checks = validate_receipts(
        receipts,
        directory,
        work,
        base,
        expected_writer,
        expected_reviewers,
        final_stats,
        TEST.encode(),
    )
    parent_verification_valid = validate_parent_verification(directory, work)
    checks = {
        "host_exited": finished.returncode == 0,
        "host_completed_workflow": classify_host_reply(finished.returncode, reply) == "PASS",
        "test_file_preserved": test_file_preserved,
        "parent_verification_valid": parent_verification_valid,
        **receipt_checks,
    }
    verification = RUN_CHECK([sys.executable, "-B", "-m", "unittest", "-q"], work, check_timeout)
    (directory / "after-tests.log").write_text(verification.stdout + verification.stderr)
    checks["fix_passes_independent_rerun"] = verification.returncode == 0
    contract = RUN_CHECK([sys.executable, "-B", "-c", CONTRACT_PROBE], work, check_timeout)
    (directory / "contract-probe.log").write_text(contract.stdout + contract.stderr)
    checks["finite_number_contract_preserved"] = contract.returncode == 0
    report = {"host": host, "exit": finished.returncode, "base": base, "policy": policy["effective"], "checks": checks, "receipts": receipts,
              "verification": {"tests_exit_code": verification.returncode, "contract_exit_code": contract.returncode, "timeout_seconds": check_timeout}}
    (directory / "checks.json").write_text(json.dumps(report, indent=2) + "\n")
    for name, passed in checks.items():
        print(f"{'ok' if passed else 'FAIL'} {host}: {name}", flush=True)
    return all(checks.values())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--host", choices=("claude", "codex"), action="append")
    parser.add_argument("--host-timeout", type=int, default=1200, help="outer host deadline in seconds (default: 1200)")
    parser.add_argument("--check-timeout", type=float, default=30, help="deadline for each verification command (default: 30)")
    options = parser.parse_args()
    if options.host_timeout <= 0:
        parser.error("host-timeout must be positive")
    if not math.isfinite(options.check_timeout) or options.check_timeout <= 0:
        parser.error("check-timeout must be positive and finite")
    run = options.run_dir.resolve()
    run.mkdir(parents=True, exist_ok=True)
    if any(run.iterdir()):
        parser.error("use a new empty run directory")
    sources = ["bin/xagent", "bin/xagent-pi-guard.ts", "references/runtime.md", "references/claude-runtime.md", "references/codex-runtime.md", "skills/xagent/SKILL.md", "skills/swarm/SKILL.md", "skills/interrogate/SKILL.md", "scripts/pstack-host-e2e.py", "scripts/pstack-host-e2e.test.py", "scripts/e2e-process.py"]
    (run / "source-hashes.json").write_text(json.dumps({name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in sources}, indent=2) + "\n")
    hosts = options.host or ["claude", "codex"]
    with ThreadPoolExecutor(max_workers=len(hosts)) as pool:
        results = list(pool.map(lambda host: exercise(host, run, options.host_timeout, options.check_timeout), hosts))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
