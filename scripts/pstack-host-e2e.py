#!/usr/bin/env python3
"""Exercise real swarm -> interrogate policy routing from Claude and Codex on a synthetic repo.

Actual Claude and Codex hosts run swarm, then interrogate, through their current
shared policy on synthetic fixtures. The run records source hashes, policy,
worker receipts and independent tests. It never changes preferences. A run
passes only on the evidence below; the host's own report never counts.

Parent, writer and adversaries. The parent verified the final source, the
configured writer repaired it in a worktree of its own, and each configured
interrogate adversary attacked the final version in a separate worktree.

xagent entries are checked through their receipts. A meta.json counts as an
xagent attempt when either marker bin/xagent creates first (prompt.md,
agent.log) sits beside it, so a broken attempt still fails. Attempts are keyed
by mode, agent and model; any other meta.json under the evidence directory is
listed as ignored.

Native entries are checked through the host's own log, parsed by
scripts/e2e-native-evidence.py: Claude's stream-json Agent calls and their
resolved model, or Codex's persisted session rollouts. The Codex host therefore
runs without --ephemeral.

- Checkout. A native dispatch's checkout comes from its subagent's own tool
  calls: the Claude events whose parent_tool_use_id is its Agent call, or the
  Codex child rollout, whose task payload is encrypted. Those calls must use
  exactly one checkout under the run other than the parent, and it must be a
  linked worktree at the fixture base.
- Writer. The dispatch writes when it edited that checkout's stats.py with its
  host's file-edit tool and the edit succeeded (Claude Write/Edit with a
  successful tool result, a completed Codex FileChange), leaving test_stats.py
  unchanged. Shell edits are not writer evidence, so a writer that edits only
  through the shell cannot fill the writer slot.

Adversaries. An adversary proves each finding with a run, so it may add repro
files to its worktree, and an xagent adversary runs rw: ro is plan mode for
claude and gemini, which runs no commands, so an ro receipt fills no slot. An
attempt attacked the final version when its checkout holds the final stats.py
and the fixture's test_stats.py, neither written after the attempt started. An
xagent attempt starts at the mtime of its prompt.md, which xagent writes before
it starts the agent and never again; a native one at its dispatch's timestamp in
the host's log (Claude's Agent call, the Codex parent rollout's spawn_agent). A
worktree brought to the final version after its attack therefore holds no
attack on it, as when a re-interrogation in a reused worktree drops out. Forging
a time would take touching the files or rewriting the host's log, which is
outside the threat model of an acceptance test for cooperating agents.

Parent reruns. The parent records each finding it reran in findings.json: the
adversary's policy entry, its worktree, the exact command the parent ran, and
whether it kept the finding. Each entry needs a shell command the parent ran
itself, read from the host's log (Claude's top-level Bash calls, the Codex
--json stream's command_execution items), that contains the entry's command and
names that worktree, and an attempt by that adversary must have used the
worktree. An empty list passes, since no findings is a valid result; whether the
list is complete is the host's claim, bounded by the final independent checks.

Effort. When the effective policy sets reasoning_effort, a worker fills a role
only if its xagent receipt, Claude Agent call or Codex spawn_agent records an
effort level. The level itself may differ, since poteto-mode adjusts it per
task.

Ownership. Each checkout belongs to one owner, a worker (kind, agent and model)
in one mode, so an xagent retry or a native writer's follow-up fix may reuse its
worktree. Each configured writer or adversary slot needs an attempt in a
checkout no other slot used, so two attacks in one worktree count once. The
adversary slots choose first, because an xagent attempt that attacked the final
version also meets the writer slot's test. A missing log or a dispatch that used
no path is reported as a gap and fails the check.

Time limits. Each worker attempt gets xagent's default limit with one retry,
not doubled. The outer host process runs under timeout with a kill-after limit;
the default --host-timeout lets the writer, interrogation and post-fix
re-interrogation rounds each retry, and --help prints its arithmetic. Verification commands run through
scripts/e2e-process.py with a default deadline (--check-timeout),
process-group termination and bounded output collection. A verification
timeout remains a failed check with logs and exit code 124.
"""
from __future__ import annotations

import argparse
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, fields
from datetime import datetime
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
NATIVE = runpy.run_path(str(ROOT / "scripts/e2e-native-evidence.py"))
NativeDispatch = NATIVE["NativeDispatch"]
ShellCommand = NATIVE["ShellCommand"]
claude_native_dispatches = NATIVE["claude_native_dispatches"]
codex_native_dispatches = NATIVE["codex_native_dispatches"]
checkouts_touched = NATIVE["checkouts_touched"]
# The fields the role checks read; another runpy load of the module makes an equal dispatch of a different class.
NATIVE_FIELDS = tuple(field.name for field in fields(NativeDispatch))
# One findings.json entry: a finding the parent reran, with the command it ran and its verdict.
FINDING_FIELDS = {"adversary": str, "worktree": str, "command": str, "kept": bool}
# Each worker attempt gets xagent's own default limit and at most one retry; the retry is not doubled.
WORKER_LIMIT_SECONDS = XAGENT["DEFAULT_TIMEOUT"]
# Per attempt, on top of its limit and xagent's termination grace: process start-up and xagent's before/after snapshots.
ATTEMPT_OVERHEAD_SECONDS = 30
# The longest one attempt can take, so one foreground wait in the host must outlast it.
ATTEMPT_SECONDS = WORKER_LIMIT_SECONDS + XAGENT["TERMINATION_GRACE"] + ATTEMPT_OVERHEAD_SECONDS
# Worst case: the writer, interrogation and post-fix re-interrogation rounds run in sequence, each an attempt plus one retry.
WORST_CASE_ATTEMPTS = 3 * 2
# The host's own start-up, patch integration and reasoning between rounds.
HOST_WORK_SECONDS = 600
DEFAULT_CHECK_TIMEOUT = 30


def default_host_timeout(check_timeout):
    """Every worst-case attempt run to its limit, plus the host's own work and its two final verification checks."""
    return math.ceil(WORST_CASE_ATTEMPTS * ATTEMPT_SECONDS + HOST_WORK_SECONDS + 2 * check_timeout)


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


def _linked_worktree_at_base(workdir, run_scope, parent, base, parent_common):
    """Whether workdir is a linked worktree of the parent, under the run, checked out at the fixture base."""
    try:
        workdir, scope, parent = Path(workdir).resolve(), Path(run_scope).resolve(), Path(parent).resolve()
        if workdir == parent or not workdir.is_relative_to(scope):
            return False
        top = _git_output(workdir, "rev-parse", "--show-toplevel")
        head = _git_output(workdir, "rev-parse", "HEAD")
        common = _git_path(workdir, "--git-common-dir")
        git_dir = _git_path(workdir, "--git-dir")
        if not top or Path(top).resolve() != workdir or head != base:
            return False
        if not parent_common or common != parent_common or not git_dir or git_dir == common:
            return False
        if not git_dir.is_relative_to(parent_common / "worktrees") or not (workdir / ".git").is_file():
            return False
        worktree_list = _git_output(parent, "worktree", "list", "--porcelain")
        listed = [Path(line.removeprefix("worktree ")).resolve() for line in (worktree_list or "").splitlines() if line.startswith("worktree ")]
        return workdir in listed
    except (OSError, RuntimeError, TypeError, ValueError):
        return False


def _valid_linked_worktree(receipt, run_scope, parent, base, parent_common):
    """Return the receipt's linked worktree at the fixture base, or None when it or the receipt's worker is invalid."""
    if not isinstance(receipt, dict) or not isinstance(receipt.get("workdir"), str) or not receipt["workdir"]:
        return None
    mode, agent, model = receipt.get("mode"), receipt.get("agent"), receipt.get("model")
    if mode not in ("rw", "ro") or not isinstance(agent, str) or not agent or not isinstance(model, (str, type(None))):
        return None
    workdir = Path(receipt["workdir"]).resolve()
    return workdir if _linked_worktree_at_base(workdir, run_scope, parent, base, parent_common) else None


def collect_xagent_receipts(evidence):
    """Return the meta.json receipts bin/xagent wrote under evidence, and the paths of other meta.json files.

    xagent requires an empty out_dir and creates its RECEIPT_MARKERS there before its first meta.json, so a
    meta.json beside either marker is an xagent attempt even when it is unreadable or a marker is missing, and
    fails as such. A host's own notes on its native workers, or a receipt copied elsewhere, are ignored.
    """
    receipts, ignored = [], []
    for file in sorted(Path(evidence).rglob("meta.json")):
        if not any((file.parent / name).is_file() for name in XAGENT["RECEIPT_MARKERS"]):
            ignored.append(str(file))
            continue
        try:
            receipt = json.loads(file.read_text())
        except (OSError, UnicodeError, ValueError):
            receipt = None
        receipts.append({**receipt, "path": str(file)} if isinstance(receipt, dict) else None)
    return receipts, ignored


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


def route(value):
    """Return (kind, (agent, model)) for a policy entry, or None when it names no worker."""
    if not isinstance(value, str) or not value:
        return None
    if value.startswith("xagent:"):
        try:
            return "xagent", XAGENT["agent_spec"](value.removeprefix("xagent:"))
        except argparse.ArgumentTypeError:
            return None
    # A native dispatch names no agent; inherit-parent and auto omit its model field.
    return "native", (None, None if value in ("inherit-parent", "auto") else value)


def expected_roles(effective):
    """Return the configured swarm writer and interrogate adversaries, falling back to the helper's own defaults."""
    return (effective["roles"].get("swarm workers", effective["defaultModel"]),
            effective["panels"].get("interrogate reviewers", effective["defaultPanel"]))


def load_findings(path):
    """Return the parent's findings ledger, or None when it is missing or an entry lacks a field of the right type."""
    try:
        findings = json.loads(Path(path).read_text())
    except (OSError, UnicodeError, ValueError):
        return None
    valid = isinstance(findings, list) and all(
        isinstance(entry, dict) and all(isinstance(entry.get(key), kind) for key, kind in FINDING_FIELDS.items())
        and entry["command"].strip() for entry in findings)
    return findings if valid else None


@dataclass(frozen=True)
class Attempt:
    """One worker attempt from an xagent receipt or a native host dispatch, as the role and ownership checks see it."""
    kind: str  # xagent or native
    mode: str | None  # rw or ro: an xagent receipt's mode, or whether a native subagent edited its checkout
    worker: tuple[str | None, str | None]  # (agent, model); a native dispatch names no agent
    effort: str | None
    terminal: bool
    checkouts: frozenset[Path]  # the checkouts it worked in
    roles: frozenset[str]  # the slots it can fill, writer or adversary; empty when the attempt is unusable

    @property
    def owner(self):
        # One worker in one mode, so retries and follow-up fixes may reuse a worktree that nobody else may use.
        return self.kind, self.mode, self.worker


def _holds(path, expected):
    try:
        return path.read_bytes() == expected
    except OSError:
        return False


def _held_since(checkout, started, final_stats, test_file):
    """Whether checkout holds the final stats.py and the fixture's test_stats.py, neither written after started."""
    try:
        return started is not None and all(_holds(path, expected) and path.stat().st_mtime <= started
                                           for path, expected in ((checkout / "stats.py", final_stats), (checkout / "test_stats.py", test_file)))
    except OSError:
        return False


def _mtime(path):
    try:
        return Path(path).stat().st_mtime
    except (OSError, TypeError, ValueError):
        return None


def _timestamp(value):
    """Seconds since the epoch for a host log's ISO timestamp, or None."""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (AttributeError, TypeError, ValueError):
        return None


def _xagent_attempt(receipt, workdir, final_stats, test_file):
    if not isinstance(receipt, dict):
        return Attempt("xagent", None, (None, None), None, False, frozenset(), frozenset())
    mode = receipt.get("mode") if receipt.get("mode") in ("rw", "ro") else None
    terminal = receipt.get("completed") is True and receipt.get("status") in ("PASS", "ISSUES", "BLOCKED", "DROPOUT")
    # ISSUES may carry a usable patch or findings; final parent checks remain mandatory. Writers and adversaries both run rw.
    usable = (workdir is not None and terminal and mode == "rw" and receipt.get("status") in ("PASS", "ISSUES")
              and type(receipt.get("exit")) is int and receipt.get("exit") == 0)
    roles = frozenset()
    if usable:
        # xagent writes prompt.md before it starts the agent and never again, so its mtime is when the attempt started.
        started = _mtime(Path(receipt["path"]).parent / "prompt.md") if isinstance(receipt.get("path"), str) else None
        roles = frozenset({"writer", "adversary"} if _held_since(workdir, started, final_stats, test_file) else {"writer"})
    return Attempt("xagent", mode, (receipt.get("agent"), receipt.get("model")), receipt.get("effort"), terminal,
                   frozenset({workdir} if workdir else ()), roles)


def _native_attempt(dispatch, run_scope, parent, base, parent_common, final_stats, test_file):
    """A native dispatch writes when its subagent repaired stats.py in the one checkout it used, and attacks when that
    checkout held the final version from the dispatch on; either way the checkout must be a linked worktree at the
    fixture base."""
    if not all(hasattr(dispatch, name) for name in NATIVE_FIELDS):
        return Attempt("native", None, (None, None), None, False, frozenset(), frozenset())
    try:
        checkouts = frozenset(checkouts_touched(dispatch.paths_touched, run_scope, parent))
        edited = checkouts_touched(dispatch.paths_edited, run_scope, parent)
    except (OSError, RuntimeError, TypeError, ValueError):
        checkouts, edited = frozenset(), set()
    # Its own edits decide the mode whether or not it finished, as an xagent receipt records its mode up front.
    mode = "rw" if edited else "ro"
    roles = frozenset()
    if dispatch.usable and len(checkouts) == 1:
        (checkout,) = checkouts
        # A writer's edits must include the repair itself, with the fixture's tests left alone.
        repaired = (checkout / "stats.py") in {Path(path).resolve() for path in dispatch.paths_edited if Path(path).is_absolute()}
        if _linked_worktree_at_base(checkout, run_scope, parent, base, parent_common):
            if repaired and _holds(checkout / "test_stats.py", test_file):
                roles = frozenset({"writer"})
            elif _held_since(checkout, _timestamp(dispatch.started), final_stats, test_file):
                roles = frozenset({"adversary"})
    return Attempt("native", mode, (None, dispatch.requested), dispatch.effort, dispatch.status in ("completed", "failed"), checkouts, roles)


def _rerun_by_parent(entry, attempts, parent_commands, run_scope, parent):
    """Whether the parent itself ran entry's command in the worktree of an attempt by entry's adversary."""
    worktree = Path(entry["worktree"]).resolve()
    adversary = route(entry["adversary"])
    return (any((attempt.kind, attempt.worker) == adversary and worktree in attempt.checkouts for attempt in attempts)
            and any(entry["command"] in command.command and worktree in checkouts_touched(command.paths, run_scope, parent)
                    for command in parent_commands))


def validate_receipts(receipts, run_scope, parent, base, expected_writer, expected_adversaries, final_stats, test_file,
                      native_dispatches=(), effort_required=False, findings=(), parent_commands=()):
    """Check that every attempt finished, each configured slot took a usable attempt in a checkout of its own, each
    checkout has one owner, and the parent itself reran every finding in its ledger.

    When the policy sets a reasoning effort, an attempt fills a slot only if it records one; poteto-mode adjusts the level per task.
    findings is the parent's ledger from load_findings, None when it was missing or malformed.
    """
    try:
        run_scope, parent = Path(run_scope).resolve(), Path(parent).resolve()
        parent_common = _git_path(parent, "--git-common-dir")
        parent_top = _git_output(parent, "rev-parse", "--show-toplevel")
        if not parent_top or Path(parent_top).resolve() != parent:
            parent_common = None
        attempts = [_xagent_attempt(receipt, _valid_linked_worktree(receipt, run_scope, parent, base, parent_common), final_stats, test_file)
                    for receipt in receipts]
        attempts += [_native_attempt(dispatch, run_scope, parent, base, parent_common, final_stats, test_file) for dispatch in native_dispatches]
        # Every xagent receipt needs its own linked worktree, and each checkout belongs to one owner across all attempts.
        workspaces_valid, claims = parent_common is not None, {}
        for attempt in attempts:
            if attempt.kind == "xagent" and not attempt.checkouts:
                workspaces_valid = False
            for checkout in attempt.checkouts:
                workspaces_valid = claims.setdefault(checkout, attempt.owner) == attempt.owner and workspaces_valid
        pool, taken = list(attempts), set()

        def take(value, role):
            # A slot cannot use a checkout another slot used, so every configured worker had a worktree of its own.
            wanted = route(value)
            for index, attempt in enumerate(pool):
                if (wanted == (attempt.kind, attempt.worker) and role in attempt.roles and not attempt.checkouts & taken
                        and (not effort_required or attempt.effort in XAGENT["EFFORTS"])):
                    taken.update(pool.pop(index).checkouts)
                    return True
            return False

        # An xagent attempt that attacked the final version also meets the writer test, so adversaries choose first.
        adversaries = expected_adversaries if isinstance(expected_adversaries, list) else []
        adversaries_ok = bool(adversaries)
        for value in adversaries:
            adversaries_ok = take(value, "adversary") and adversaries_ok
        writer_ok = take(expected_writer, "writer")
        return {
            "all_attempts_terminal": bool(attempts) and all(attempt.terminal for attempt in attempts),
            "configured_writer_dispatched": writer_ok,
            "configured_adversaries_dispatched": adversaries_ok,
            "receipt_workspaces_owned": workspaces_valid,
            "findings_rerun_by_parent": findings is not None and all(
                _rerun_by_parent(entry, attempts, parent_commands, run_scope, parent) for entry in findings),
        }
    except (OSError, RuntimeError, TypeError, ValueError):
        return {
            "all_attempts_terminal": False,
            "configured_writer_dispatched": False,
            "configured_adversaries_dispatched": False,
            "receipt_workspaces_owned": False,
            "findings_rerun_by_parent": False,
        }


def git(work, *args):
    return subprocess.run(["git", "-C", str(work), *args], check=True, text=True, capture_output=True).stdout.strip()


def _save_claude_reply(directory, host_log):
    for event in NATIVE["json_events"](host_log):
        if event.get("type") == "result" and isinstance(event.get("result"), str):
            (directory / "result.md").write_text(event["result"])


@dataclass(frozen=True)
class HostAdapter:
    command: Callable[[Path, Path], list[str]]  # (parent checkout, run directory) -> argv; the prompt goes through stdin
    env: dict[str, str]
    save_reply: Callable[[Path, list[str]], None]  # leaves the host's final reply in the run directory's result.md
    dispatches: Callable[[list[str]], tuple[list[NativeDispatch], str | None]]  # host log lines -> (native dispatches, gap)
    parent_commands: Callable[[list[str]], list[ShellCommand]]  # host log lines -> the shell commands the host itself ran


HOSTS = {
    # --allowedTools is variadic, so the prompt cannot follow it on the command line.
    "claude": HostAdapter(
        command=lambda work, directory: ["claude", "-p", "--no-session-persistence", "--output-format", "stream-json", "--verbose", "--permission-mode", "acceptEdits", "--plugin-dir", str(ROOT), "--allowedTools", "Agent", "Bash", "Read", "Write", "Edit", "Glob", "Grep"],
        # Claude Code caps a Bash call at 10 minutes by default. One foreground wait must outlast a whole attempt;
        # the prompt runs a retry in a new call, so it need not cover two.
        env={"BASH_MAX_TIMEOUT_MS": str(ATTEMPT_SECONDS * 1000)},
        save_reply=_save_claude_reply,
        dispatches=claude_native_dispatches,
        parent_commands=NATIVE["claude_parent_commands"],
    ),
    # Not --ephemeral: spawn_agent evidence for native workers exists only in the persisted session rollout.
    "codex": HostAdapter(
        command=lambda work, directory: ["codex", "exec", "--skip-git-repo-check", "--json", "-C", str(work), "-c", 'shell_environment_policy.set.XAGENT_EPHEMERAL="1"', "-o", str(directory / "result.md"), "-"],
        env={},
        save_reply=lambda directory, host_log: None,
        dispatches=lambda host_log: codex_native_dispatches(host_log, os.environ.get("CODEX_HOME") or Path.home() / ".codex"),
        parent_commands=NATIVE["codex_parent_commands"],
    ),
}


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
Give the writer an exclusive worktree at fixture base {base} and have it leave its change uncommitted there;
keep all worktrees and outputs under {directory}.
The parent checkout is {work}. Integrate the worker's patch locally, then run python3 -m unittest yourself.
Use interrogate on the resulting change with every configured adversary, selected from the effective policy.
Give each adversary its own exclusive worktree checked out at fixture base {base}, with the proposed patch applied
as uncommitted changes; do not commit the patch or check out a writer commit. Preserve parent and worker evidence.
Adversaries leave stats.py and test_stats.py unchanged and keep their repro files beside them in their own worktree.
Rerun each finding's command yourself, naming that adversary's worktree path in the command, before you keep or drop it,
and record every rerun in {directory}/findings.json: a JSON list with one object per finding, holding "adversary" (its
policy entry), "worktree" (the absolute path of its worktree), "command" (the exact command you ran) and "kept" (true
or false). Write [] when no adversary reported a finding.
Fix any verified in-scope findings and rerun the affected check; do not count a dropout, cancelled run, or missing evidence as a pass.
If stats.py changes after any interrogation, every configured adversary must attack the final version again in a new
worktree prepared the same way; an attack on an earlier version does not count.
Both host controllers run one-shot/headless. Do not send the final reply until every external command and adversary
has completed and you have inspected its terminal output and receipt. When running xagent commands in parallel,
start them with & in one foreground Bash call, capture every PID, and wait for every PID; give the call a timeout
longer than the {WORKER_LIMIT_SECONDS}-second attempt limit plus termination grace. Inspect each receipt, then run an allowed
retry in a new call. Do not promise later notifications, rely on Monitor or shell sentinels, or use TaskOutput (it is not an available tool).
Follow the host adapter's supported tools and wait behavior.

After all integrations, fixes, and configured attacks are complete, personally run the final parent verification
from the parent checkout by executing exactly: python3 {verifier} {work}
The helper runs python3 -B -m unittest -q and the contract probe, writes separate stdout/stderr logs plus
{directory}/parent-verification.json, and exits nonzero if the real cwd, stable stats.py hash, or either check fails.
Each verification command has a {check_timeout:g}-second deadline and terminates its process group on timeout.
Do not edit stats.py after running it. The harness checks that this receipt describes the final parent version,
then independently reruns the tests and contract probe.

Every xagent attempt must write to a new subdirectory under {evidence}. Limit each worker to {WORKER_LIMIT_SECONDS} seconds and at most one retry.
Use only this synthetic fixture and local candidate skill files. The human has authorized this real multi-vendor E2E,
including sending this synthetic code and the standalone briefs to the locally configured agents.
No extra confirmation is needed for those calls. Do not push, publish, change global settings, contact people, or edit the candidate plugin.
Workers must remain leaves. Do not replace configured external agents with native workers.
A policy entry without the xagent: prefix is a native worker: dispatch it with your host's own subagent tool and
pass that exact model, omitting the model only for inherit-parent or auto. A native writer changes stats.py only with
its host's file-edit tool (Write or Edit in Claude Code, apply_patch in Codex).
When the effective policy sets reasoning_effort, pass an effort to every worker, native or xagent; dispatch each native
worker as an agent type whose definition sets no effort of its own, so that effort applies.
Report the resolved routes, actual worker receipt paths, findings, your own test output, and any gaps.
End with PSTACK_E2E: PASS only if the repair, every configured adversary's attack on the final version, your reruns
of their findings and your independent tests are complete,
with no unresolved reproduced violation of the stated contract; otherwise PSTACK_E2E: FAIL.
'''
    (directory / "prompt.md").write_text(prompt)
    adapter = HOSTS[host]
    env = {**os.environ, "XAGENT_EPHEMERAL": "1", **adapter.env}
    env.pop("XAGENT_DEPTH", None)
    with (directory / "host.log").open("w") as log:
        finished = subprocess.run(["timeout", "-k", "5", str(host_timeout), *adapter.command(work, directory)], cwd=work, env=env, input=prompt, text=True, stdout=log, stderr=subprocess.STDOUT)
    host_log = (directory / "host.log").read_text(errors="replace").splitlines()
    adapter.save_reply(directory, host_log)
    try:
        reply = (directory / "result.md").read_text()
    except (OSError, UnicodeError):
        reply = ""
    receipts, ignored_meta = collect_xagent_receipts(evidence)
    native, native_gap = adapter.dispatches(host_log)
    parent_commands = adapter.parent_commands(host_log)
    findings = load_findings(directory / "findings.json")
    expected_writer, expected_adversaries = expected_roles(policy["effective"])
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
        expected_adversaries,
        final_stats,
        TEST.encode(),
        native,
        policy["effective"].get("reasoning_effort") is not None,
        findings,
        parent_commands,
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
              "ignored_meta": ignored_meta, "native_evidence": {"gap": native_gap, "dispatches": [asdict(dispatch) for dispatch in native]},
              # The parent's ledger, beside the commands it ran in checkouts under the run, so a reader can match each rerun.
              "findings": findings, "parent_commands": [asdict(command) for command in parent_commands if checkouts_touched(command.paths, directory, work)],
              "verification": {"tests_exit_code": verification.returncode, "contract_exit_code": contract.returncode, "timeout_seconds": check_timeout}}
    (directory / "checks.json").write_text(json.dumps(report, indent=2) + "\n")
    for name, passed in checks.items():
        print(f"{'ok' if passed else 'FAIL'} {host}: {name}", flush=True)
    if native_gap:
        print(f"GAP {host}: native dispatch evidence unavailable: {native_gap}", flush=True)
    for dispatch in native:
        if not dispatch.paths_touched:
            print(f"GAP {host}: native dispatch {dispatch.id} used no path, so it cannot fill a role", flush=True)
    for path in ignored_meta:
        print(f"IGNORED {host}: {path} was not written by xagent", flush=True)
    return all(checks.values())


def main():
    parser = argparse.ArgumentParser(description=__doc__.partition("\n")[0], epilog="Acceptance rules: the module docstring of scripts/pstack-host-e2e.py.")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--host", choices=tuple(HOSTS), action="append")
    parser.add_argument("--host-timeout", type=int, help=(
        f"outer host deadline in seconds (default: {default_host_timeout(DEFAULT_CHECK_TIMEOUT)} with the default check timeout, "
        f"from {WORST_CASE_ATTEMPTS} attempts x ({WORKER_LIMIT_SECONDS} s limit + {XAGENT['TERMINATION_GRACE']} s grace + "
        f"{ATTEMPT_OVERHEAD_SECONDS} s overhead) + {HOST_WORK_SECONDS} s host work + 2 x check timeout)"))
    parser.add_argument("--check-timeout", type=float, default=DEFAULT_CHECK_TIMEOUT, help=f"deadline for each verification command (default: {DEFAULT_CHECK_TIMEOUT})")
    options = parser.parse_args()
    if options.host_timeout is not None and options.host_timeout <= 0:
        parser.error("host-timeout must be positive")
    if not math.isfinite(options.check_timeout) or options.check_timeout <= 0:
        parser.error("check-timeout must be positive and finite")
    run = options.run_dir.resolve()
    run.mkdir(parents=True, exist_ok=True)
    if any(run.iterdir()):
        parser.error("use a new empty run directory")
    sources = ["bin/xagent", "bin/xagent-pi-guard.ts", "references/runtime.md", "references/claude-runtime.md", "references/codex-runtime.md", "skills/xagent/SKILL.md", "skills/swarm/SKILL.md", "skills/interrogate/SKILL.md", "scripts/pstack-host-e2e.py", "scripts/pstack-host-e2e.test.py", "scripts/pstack-host-e2e-native.test.py",
               "scripts/pstack-host-e2e-fixtures.py", "scripts/e2e-native-evidence.py", "scripts/e2e-process.py"]
    (run / "source-hashes.json").write_text(json.dumps({name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in sources}, indent=2) + "\n")
    hosts = options.host or list(HOSTS)
    with ThreadPoolExecutor(max_workers=len(hosts)) as pool:
        host_timeout = options.host_timeout or default_host_timeout(options.check_timeout)
        results = list(pool.map(lambda host: exercise(host, run, host_timeout, options.check_timeout), hosts))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
