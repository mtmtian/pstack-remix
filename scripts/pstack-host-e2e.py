#!/usr/bin/env python3
"""Exercise real swarm -> interrogate policy routing from Claude and Codex on a synthetic repo."""
from __future__ import annotations

import argparse
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import runpy
import subprocess
import sys
from urllib.parse import unquote, urlparse

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
# Each worker attempt gets xagent's own default limit and at most one retry; the retry is not doubled.
WORKER_LIMIT_SECONDS = XAGENT["DEFAULT_TIMEOUT"]
# Per attempt, on top of its limit and xagent's termination grace: process start-up and xagent's before/after snapshots.
ATTEMPT_OVERHEAD_SECONDS = 30
# The longest one attempt can take, so one foreground wait in the host must outlast it.
ATTEMPT_SECONDS = WORKER_LIMIT_SECONDS + XAGENT["TERMINATION_GRACE"] + ATTEMPT_OVERHEAD_SECONDS
# Worst case: the writer, review and post-fix re-review rounds run in sequence, each an attempt plus one retry.
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
    """Return the receipt's worktree and its owner (mode, agent, model), or None when either is invalid."""
    if not isinstance(receipt, dict) or not isinstance(receipt.get("workdir"), str) or not receipt["workdir"]:
        return None
    mode, agent, model = receipt.get("mode"), receipt.get("agent"), receipt.get("model")
    if mode not in ("rw", "ro") or not isinstance(agent, str) or not agent or not isinstance(model, (str, type(None))):
        return None
    workdir = Path(receipt["workdir"]).resolve()
    if not _linked_worktree_at_base(workdir, run_scope, parent, base, parent_common):
        return None
    return workdir, (mode, agent, model)


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


# An absolute path as it appears in a prompt or shell command.
ABSOLUTE_PATH = re.compile(r"/[^\s'\"`<>()\[\]{},;|\\]+")


def _json_events(lines):
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            yield event


# Claude Code's file-edit tools; a writer changes its checkout with them, a reviewer never does.
CLAUDE_EDIT_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")


def claude_native_dispatches(lines):
    """Return the host's Agent dispatches from `claude -p --output-format stream-json --verbose` output."""
    events = list(_json_events(lines))
    if not any(event.get("type") == "system" and event.get("subtype") == "init" for event in events):
        return [], "claude stream-json log has no init event"
    dispatches = {}
    for event in events:
        content = event["message"].get("content") if isinstance(event.get("message"), dict) else None
        blocks = [block for block in content if isinstance(block, dict)] if isinstance(content, list) else []
        if event.get("type") == "assistant" and event.get("parent_tool_use_id") is None:
            for block in blocks:
                if block.get("type") == "tool_use" and block.get("name") in ("Agent", "Task"):
                    arguments = block.get("input") if isinstance(block.get("input"), dict) else {}
                    dispatches[block.get("id")] = {"id": block.get("id"), "requested": arguments.get("model"), "effort": arguments.get("effort"),
                                                   "resolved": None, "status": "pending", "paths_touched": set(), "paths_edited": set()}
        elif event.get("type") == "assistant" and event.get("parent_tool_use_id") in dispatches:
            # The subagent's own tool calls stream under its Agent call, for background agents too.
            dispatch = dispatches[event["parent_tool_use_id"]]
            for block in blocks:
                arguments = block.get("input") if block.get("type") == "tool_use" and isinstance(block.get("input"), dict) else {}
                paths = {value for key in ("file_path", "notebook_path", "path") if isinstance(value := arguments.get(key), str)}
                dispatch["paths_touched"].update(paths)
                if block.get("name") in CLAUDE_EDIT_TOOLS:
                    dispatch["paths_edited"].update(paths)
                if isinstance(arguments.get("command"), str):
                    dispatch["paths_touched"].update(ABSOLUTE_PATH.findall(arguments["command"]))
        elif event.get("type") == "user":
            results = [block for block in blocks if block.get("type") == "tool_result" and block.get("tool_use_id") in dispatches]
            # tool_use_result describes the event's single tool result; an ambiguous event stays pending.
            if len(results) != 1:
                continue
            dispatch, result = dispatches[results[0]["tool_use_id"]], event.get("tool_use_result")
            if not isinstance(result, dict):
                dispatch["status"] = "failed"
                continue
            dispatch["resolved"] = result.get("resolvedModel")
            if result.get("status") == "completed":
                dispatch["status"] = "completed"
            elif result.get("status") != "async_launched":
                dispatch["status"] = "failed"
        elif event.get("type") == "system" and event.get("subtype") == "task_notification":
            # Background agents finish here; Bash tasks also notify, so only Agent tool_use ids count.
            dispatch = dispatches.get(event.get("tool_use_id"))
            if dispatch is not None:
                dispatch["status"] = "completed" if event.get("status") == "completed" else "failed"
    for dispatch in dispatches.values():
        dispatch["paths_touched"], dispatch["paths_edited"] = sorted(dispatch["paths_touched"]), sorted(dispatch["paths_edited"])
        requested, resolved = dispatch["requested"], dispatch["resolved"]
        # Claude resolves an alias such as opus to claude-opus-<version>; an omitted model inherits the parent's.
        dispatch["usable"] = dispatch["status"] == "completed" and isinstance(resolved, str) and bool(resolved) and (
            requested is None or resolved == requested or resolved.startswith(f"claude-{requested}-"))
    return list(dispatches.values()), None


def codex_native_dispatches(lines, codex_home):
    """Return the host's spawn_agent dispatches from the session rollouts named by `codex exec --json` output.

    The --json stream omits collaboration calls, so the parent rollout supplies each requested model
    and the child rollout's turn_context the model that actually ran.
    """
    try:
        return _codex_native_dispatches(lines, codex_home)
    except OSError as error:
        return [], f"cannot read Codex rollouts: {error}"


ROLLOUT_NAME = re.compile(r"rollout-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-(.+)\.jsonl")


def _codex_native_dispatches(lines, codex_home):
    thread = next((event["thread_id"] for event in _json_events(lines)
                   if event.get("type") == "thread.started" and isinstance(event.get("thread_id"), str)), None)
    if not thread:
        return [], "codex --json log has no thread.started thread_id"
    sessions = Path(codex_home) / "sessions"
    rollouts = {}
    for path in sorted(sessions.rglob("rollout-*.jsonl")):
        match = ROLLOUT_NAME.fullmatch(path.name)
        if match:
            rollouts.setdefault(match.group(1), path)

    def payloads(path):
        for event in _json_events(path.read_text(errors="replace").splitlines()):
            if isinstance(event.get("payload"), dict):
                yield event.get("type"), event["payload"]

    if thread not in rollouts:
        return [], f"no Codex rollout for thread {thread} under {sessions}"
    requested, efforts, returned, started, finished = {}, {}, set(), {}, set()
    for _, payload in payloads(rollouts[thread]):
        if payload.get("type") == "function_call" and payload.get("name") == "spawn_agent":
            try:
                arguments = json.loads(payload.get("arguments") or "{}")
            except (TypeError, ValueError):
                arguments = {}
            arguments = arguments if isinstance(arguments, dict) else {}
            requested[payload.get("call_id")], efforts[payload.get("call_id")] = arguments.get("model"), arguments.get("reasoning_effort")
        elif payload.get("type") == "function_call_output":
            returned.add(payload.get("call_id"))
        elif payload.get("type") == "item_completed" and isinstance(payload.get("item"), dict):
            item = payload["item"]
            if item.get("type") == "SubAgentActivity" and item.get("kind") == "started":
                started[item.get("id")] = item.get("agent_thread_id")
            elif item.get("type") == "SubAgentActivity" and item.get("kind") == "completed":
                finished.add(item.get("agent_thread_id"))
    dispatches = []
    for call, model in requested.items():
        child = started.get(call)
        child_rollout = rollouts.get(child) if isinstance(child, str) else None
        linked, models, complete, aborted, touched, edited = False, [], False, False, set(), set()
        for kind, payload in payloads(child_rollout) if child_rollout else ():
            item = payload.get("item") if payload.get("type") == "item_completed" and isinstance(payload.get("item"), dict) else {}
            if kind == "session_meta":
                linked = payload.get("parent_thread_id") == thread
            elif kind == "turn_context":
                models.append(payload.get("model"))
            elif item.get("type") == "CommandExecution":
                # The task payload is encrypted, so the child's own commands show which checkout it worked in.
                command = item.get("command")
                touched.update(ABSOLUTE_PATH.findall(" ".join(command) if isinstance(command, list) else str(command or "")))
                if isinstance(item.get("cwd"), str):
                    touched.add(unquote(urlparse(item["cwd"]).path))
            elif item.get("type") == "FileChange" and item.get("status") == "completed" and isinstance(item.get("changes"), dict):
                touched.update(item["changes"])
                edited.update(item["changes"])
            elif kind == "event_msg":
                complete = complete or payload.get("type") == "task_complete"
                aborted = aborted or payload.get("type") == "turn_aborted"
        if linked and complete and not aborted:
            status = "completed"
        elif (linked and aborted) or (child is not None and child in finished) or (child is None and call in returned):
            status = "failed"
        else:
            status = "pending"
        resolved = models[0] if linked and models and len(set(models)) == 1 else None
        dispatches.append({
            "id": call, "thread": child, "rollout": str(child_rollout) if linked else None, "requested": model, "effort": efforts.get(call),
            "resolved": resolved, "status": status, "paths_touched": sorted(touched) if linked else [], "paths_edited": sorted(edited) if linked else [],
            # Codex reports the model it ran; an omitted model inherits the parent's.
            "usable": status == "completed" and isinstance(resolved, str) and bool(resolved) and model in (None, resolved),
        })
    return dispatches, None


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
    """Return the configured swarm writer and interrogate reviewers, falling back to the helper's own defaults."""
    return (effective["roles"].get("swarm workers", effective["defaultModel"]),
            effective["panels"].get("interrogate reviewers", effective["defaultPanel"]))


@dataclass(frozen=True)
class Attempt:
    """One worker attempt from an xagent receipt or a native host dispatch, as the role and ownership checks see it."""
    kind: str  # xagent or native
    worker: tuple[str | None, str | None]  # (agent, model); a native dispatch names no agent
    owner: tuple[str | None, ...]  # (mode, agent, model) for xagent, so its retries share a worktree; the dispatch id for native
    terminal: bool
    checkouts: frozenset[Path]  # the checkouts it worked in, each of which may belong to one owner only
    role: str | None  # rw: a usable writer result; ro: a review of the final version; None: fills no role


def _final_version(checkout, final_stats, test_file):
    try:
        return (checkout / "stats.py").read_bytes() == final_stats and (checkout / "test_stats.py").read_bytes() == test_file
    except OSError:
        return False


def _reviewed_final_version(receipt, workdir, final_stats, test_file):
    try:
        before, after = receipt.get("snapshot_before"), receipt.get("snapshot_after")
        return (receipt.get("changed_workdir") is False and isinstance(before, str) and before == after
                and SNAPSHOT(workdir, Path(receipt["path"]).parent.resolve()) == after
                and _final_version(workdir, final_stats, test_file))
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError):
        return False


def _checkouts_touched(paths, run_scope, parent):
    """Return the git checkouts under the run, other than the parent, that hold an existing path a subagent's tool calls used."""
    checkouts = set()
    for raw in paths:
        if not Path(raw).is_absolute():
            continue
        path = Path(raw).resolve()
        if not path.exists() or not path.is_relative_to(run_scope):
            continue
        top = _git_output(path if path.is_dir() else path.parent, "rev-parse", "--show-toplevel")
        if top and Path(top).resolve() != parent and Path(top).resolve().is_relative_to(run_scope):
            checkouts.add(Path(top).resolve())
    return checkouts


def _xagent_attempt(receipt, validated, final_stats, test_file, effort_required):
    if not isinstance(receipt, dict):
        return Attempt("xagent", (None, None), (None,), False, frozenset(), None)
    workdir, owner = validated or (None, (None,))
    terminal = receipt.get("completed") is True and receipt.get("status") in ("PASS", "ISSUES", "BLOCKED", "DROPOUT")
    # ISSUES may carry a usable patch or review; final parent checks and reviews remain mandatory.
    usable = (workdir is not None and terminal and receipt.get("status") in ("PASS", "ISSUES")
              and type(receipt.get("exit")) is int and receipt.get("exit") == 0
              and (not effort_required or receipt.get("effort") in XAGENT["EFFORTS"]))
    if usable and receipt.get("mode") == "ro":
        usable = _reviewed_final_version(receipt, workdir, final_stats, test_file)
    return Attempt("xagent", (receipt.get("agent"), receipt.get("model")), owner, terminal,
                   frozenset({workdir} if workdir else ()), receipt.get("mode") if usable else None)


def _native_attempt(dispatch, run_scope, parent, base, parent_common, final_stats, test_file, effort_required):
    """A native dispatch whose subagent worked in exactly one checkout writes if it edited that checkout, and
    otherwise reviews if the checkout is the final version at the base."""
    if not isinstance(dispatch, dict):
        return Attempt("native", (None, None), ("native", None), False, frozenset(), None)
    worker, owner = (None, dispatch.get("requested")), ("native", dispatch.get("id"))
    terminal = dispatch.get("status") in ("completed", "failed")
    if dispatch.get("usable") is not True:
        return Attempt("native", worker, owner, terminal, frozenset(), None)
    try:
        checkouts = frozenset(_checkouts_touched(dispatch.get("paths_touched") or [], run_scope, parent))
        edited = _checkouts_touched(dispatch.get("paths_edited") or [], run_scope, parent)
    except (OSError, RuntimeError, TypeError, ValueError):
        checkouts, edited = frozenset(), set()
    role = None
    if len(checkouts) == 1 and (not effort_required or dispatch.get("effort") in XAGENT["EFFORTS"]):
        (checkout,) = checkouts
        if checkout in edited:
            role = "rw"
        elif _linked_worktree_at_base(checkout, run_scope, parent, base, parent_common) and _final_version(checkout, final_stats, test_file):
            role = "ro"
    return Attempt("native", worker, owner, terminal, checkouts, role)


def validate_receipts(receipts, run_scope, parent, base, expected_writer, expected_reviewers, final_stats, test_file, native_dispatches=(), effort=None):
    """Check that every attempt finished, each configured role consumed a usable attempt, and each checkout has one owner.

    When the policy sets a reasoning effort, an attempt fills a role only if it records one; poteto-mode adjusts the level per task.
    """
    try:
        run_scope, parent = Path(run_scope).resolve(), Path(parent).resolve()
        parent_common = _git_path(parent, "--git-common-dir")
        parent_top = _git_output(parent, "rev-parse", "--show-toplevel")
        if not parent_top or Path(parent_top).resolve() != parent:
            parent_common = None
        attempts = [_xagent_attempt(receipt, _valid_linked_worktree(receipt, run_scope, parent, base, parent_common), final_stats, test_file, effort is not None)
                    for receipt in receipts]
        attempts += [_native_attempt(dispatch, run_scope, parent, base, parent_common, final_stats, test_file, effort is not None)
                     for dispatch in native_dispatches]
        # Every xagent receipt needs its own linked worktree, and each checkout belongs to one owner across all attempts.
        workspaces_valid, claims = parent_common is not None, {}
        for attempt in attempts:
            if attempt.kind == "xagent" and not attempt.checkouts:
                workspaces_valid = False
            for checkout in attempt.checkouts:
                workspaces_valid = claims.setdefault(checkout, attempt.owner) == attempt.owner and workspaces_valid
        pool = list(attempts)

        def take(value, mode):
            wanted = route(value)
            for index, attempt in enumerate(pool):
                if wanted == (attempt.kind, attempt.worker) and attempt.role == mode:
                    del pool[index]
                    return True
            return False

        writer_ok = take(expected_writer, "rw")
        reviewers = expected_reviewers if isinstance(expected_reviewers, list) else []
        reviewer_ok = bool(reviewers)
        for value in reviewers:
            reviewer_ok = take(value, "ro") and reviewer_ok
        return {
            "all_attempts_terminal": bool(attempts) and all(attempt.terminal for attempt in attempts),
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


def _save_claude_reply(directory, host_log):
    for event in _json_events(host_log):
        if event.get("type") == "result" and isinstance(event.get("result"), str):
            (directory / "result.md").write_text(event["result"])


@dataclass(frozen=True)
class HostAdapter:
    command: Callable[[Path, Path], list[str]]  # (parent checkout, run directory) -> argv; the prompt goes through stdin
    env: dict[str, str]
    save_reply: Callable[[Path, list[str]], None]  # leaves the host's final reply in the run directory's result.md
    dispatches: Callable[[list[str]], tuple[list[dict], str | None]]  # host log lines -> (native dispatches, gap)


HOSTS = {
    # --allowedTools is variadic, so the prompt cannot follow it on the command line.
    "claude": HostAdapter(
        command=lambda work, directory: ["claude", "-p", "--no-session-persistence", "--output-format", "stream-json", "--verbose", "--permission-mode", "acceptEdits", "--plugin-dir", str(ROOT), "--allowedTools", "Agent", "Bash", "Read", "Write", "Edit", "Glob", "Grep"],
        # Claude Code caps a Bash call at 10 minutes by default. One foreground wait must outlast a whole attempt;
        # the prompt runs a retry in a new call, so it need not cover two.
        env={"BASH_MAX_TIMEOUT_MS": str(ATTEMPT_SECONDS * 1000)},
        save_reply=_save_claude_reply,
        dispatches=claude_native_dispatches,
    ),
    # Not --ephemeral: spawn_agent evidence for native workers exists only in the persisted session rollout.
    "codex": HostAdapter(
        command=lambda work, directory: ["codex", "exec", "--skip-git-repo-check", "--json", "-C", str(work), "-c", 'shell_environment_policy.set.XAGENT_EPHEMERAL="1"', "-o", str(directory / "result.md"), "-"],
        env={},
        save_reply=lambda directory, host_log: None,
        dispatches=lambda host_log: codex_native_dispatches(host_log, os.environ.get("CODEX_HOME") or Path.home() / ".codex"),
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
Give the writer an exclusive worktree from fixture base {base}; keep all worktrees and outputs under {directory}.
The parent checkout is {work}. Integrate the worker's patch locally, then run python3 -m unittest yourself.
Use interrogate on the resulting change with all configured reviewers, selected from the effective policy.
Give each reviewer its own exclusive worktree checked out at fixture base {base}, with the proposed patch applied
as uncommitted changes; do not commit the patch or check out a writer commit. Preserve parent and worker evidence.
Fix any real in-scope findings and rerun the affected check; do not count a dropout, cancelled run, or missing evidence as a pass.
If stats.py changes after any review, every configured reviewer must review the final version again in a new worktree
prepared the same way; a review of an earlier version does not count.
Both host controllers run one-shot/headless. Do not send the final reply until every external command and reviewer
has completed and you have inspected its terminal output and receipt. When running xagent commands in parallel,
start them with & in one foreground Bash call, capture every PID, and wait for every PID; give the call a timeout
longer than the {WORKER_LIMIT_SECONDS}-second attempt limit plus termination grace. Inspect each receipt, then run an allowed
retry in a new call. Do not promise later notifications, rely on Monitor or shell sentinels, or use TaskOutput (it is not an available tool).
Follow the host adapter's supported tools and wait behavior.

After all integrations, fixes, and configured reviews are complete, personally run the final parent verification
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
pass that exact model, omitting the model only for inherit-parent or auto. A native writer changes files only with its
host's file-edit tool (Write or Edit in Claude Code, apply_patch in Codex); a native reviewer changes no files.
When the effective policy sets reasoning_effort, pass an effort to every worker, native or xagent.
Report the resolved routes, actual worker receipt paths, findings, your own test output, and any gaps.
End with PSTACK_E2E: PASS only if the repair, all configured reviews and your independent tests are complete,
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
    expected_writer, expected_reviewers = expected_roles(policy["effective"])
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
        native,
        policy["effective"].get("reasoning_effort"),
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
              "ignored_meta": ignored_meta, "native_evidence": {"gap": native_gap, "dispatches": native},
              "verification": {"tests_exit_code": verification.returncode, "contract_exit_code": contract.returncode, "timeout_seconds": check_timeout}}
    (directory / "checks.json").write_text(json.dumps(report, indent=2) + "\n")
    for name, passed in checks.items():
        print(f"{'ok' if passed else 'FAIL'} {host}: {name}", flush=True)
    if native_gap:
        print(f"GAP {host}: native dispatch evidence unavailable: {native_gap}", flush=True)
    for dispatch in native:
        if not dispatch.get("paths_touched"):
            print(f"GAP {host}: native dispatch {dispatch.get('id')} used no path, so it cannot fill a role", flush=True)
    for path in ignored_meta:
        print(f"IGNORED {host}: {path} was not written by xagent", flush=True)
    return all(checks.values())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
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
    sources = ["bin/xagent", "bin/xagent-pi-guard.ts", "references/runtime.md", "references/claude-runtime.md", "references/codex-runtime.md", "skills/xagent/SKILL.md", "skills/swarm/SKILL.md", "skills/interrogate/SKILL.md", "scripts/pstack-host-e2e.py", "scripts/pstack-host-e2e.test.py", "scripts/e2e-process.py"]
    (run / "source-hashes.json").write_text(json.dumps({name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in sources}, indent=2) + "\n")
    hosts = options.host or list(HOSTS)
    with ThreadPoolExecutor(max_workers=len(hosts)) as pool:
        host_timeout = options.host_timeout or default_host_timeout(options.check_timeout)
        results = list(pool.map(lambda host: exercise(host, run, host_timeout, options.check_timeout), hosts))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
