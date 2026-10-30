"""Read a host's native subagent dispatches and its own shell commands from Claude stream-json output or Codex rollouts."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote, urlparse

# An absolute path as it appears in a shell command.
ABSOLUTE_PATH = re.compile(r"/[^\s'\"`<>()\[\]{},;|\\]+")
# Claude Code's file-edit tools: a writer repairs stats.py with them, and an adversary may add repro files.
CLAUDE_EDIT_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")
ROLLOUT_NAME = re.compile(r"rollout-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-(.+)\.jsonl")
# Enough of a command's output to show what a rerun printed, without copying whole file listings into checks.json.
OUTPUT_LIMIT = 2000
# Claude reports a Bash command that ran and exited nonzero as an error result that starts with its exit code.
CLAUDE_EXIT = re.compile(r"Exit code -?\d+\b")


@dataclass
class ShellCommand:
    """One shell command a subagent or the host called, with the paths it named and the start of its output.

    ran is whether the host's record shows the command ran: a Claude result with no error or one that reports the
    command's exit code, or a Codex exit code. A call a permission rule or hook stopped, one Codex declined, and one
    with no result did not run.
    """
    command: str
    paths: list[str]
    output: str | None = None
    ran: bool = False


@dataclass
class NativeDispatch:
    """One subagent dispatch as a host log records it, which the harness's role checks read."""
    id: str | None
    requested: str | None  # the model the host asked for; None inherits the parent's
    effort: str | None  # the reasoning effort the host passed
    resolved: str | None = None  # the model that actually ran
    status: str = "pending"  # completed, failed or pending
    usable: bool = False  # completed and ran the requested model
    paths_touched: list[str] = field(default_factory=list)  # paths the subagent's own tool calls used
    paths_edited: list[str] = field(default_factory=list)  # paths it changed with its host's file-edit tool
    commands: list[ShellCommand] = field(default_factory=list)  # its own shell commands, in order
    thread: str | None = None  # the Codex child thread
    rollout: str | None = None  # the Codex child rollout
    started: str | None = None  # when the host dispatched it, as its log's ISO timestamp


def json_events(lines):
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            yield event


def _blocks(event):
    content = event["message"].get("content") if isinstance(event.get("message"), dict) else None
    return [block for block in content if isinstance(block, dict)] if isinstance(content, list) else []


def claude_native_dispatches(lines):
    """Return the host's Agent dispatches from `claude -p --output-format stream-json --verbose` output."""
    events = list(json_events(lines))
    if not any(event.get("type") == "system" and event.get("subtype") == "init" for event in events):
        return [], "claude stream-json log has no init event"
    dispatches, touched, edited, edits, shells = {}, {}, {}, {}, {}
    for event in events:
        blocks = _blocks(event)
        if event.get("type") == "assistant" and event.get("parent_tool_use_id") is None:
            for block in blocks:
                if block.get("type") == "tool_use" and block.get("name") in ("Agent", "Task"):
                    arguments = block.get("input") if isinstance(block.get("input"), dict) else {}
                    dispatches[block.get("id")] = NativeDispatch(block.get("id"), arguments.get("model"), arguments.get("effort"), started=event.get("timestamp"))
                    touched[block.get("id")], edited[block.get("id")] = set(), set()
        elif event.get("type") == "assistant" and event.get("parent_tool_use_id") in dispatches:
            # The subagent's own tool calls stream under its Agent call, for background agents too.
            parent = event["parent_tool_use_id"]
            for block in blocks:
                arguments = block.get("input") if block.get("type") == "tool_use" and isinstance(block.get("input"), dict) else {}
                paths = {value for value in (arguments.get(key) for key in ("file_path", "notebook_path", "path")) if isinstance(value, str)}
                touched[parent].update(paths)
                if block.get("name") in CLAUDE_EDIT_TOOLS:
                    edits[block.get("id")] = parent, paths
                if isinstance(arguments.get("command"), str):
                    command = ShellCommand(arguments["command"], ABSOLUTE_PATH.findall(arguments["command"]))
                    touched[parent].update(command.paths)
                    dispatches[parent].commands.append(command)
                    shells[block.get("id")] = command
        elif event.get("type") == "user":
            # An edit counts once its tool_result reports success, as Codex records only completed FileChanges.
            for block in blocks:
                if block.get("type") == "tool_result" and block.get("tool_use_id") in edits:
                    parent, paths = edits.pop(block["tool_use_id"])
                    if not block.get("is_error"):
                        edited[parent].update(paths)
                if block.get("type") == "tool_result" and block.get("tool_use_id") in shells:
                    _claude_result(shells.pop(block["tool_use_id"]), block)
            results = [block for block in blocks if block.get("type") == "tool_result" and block.get("tool_use_id") in dispatches]
            # tool_use_result describes the event's single tool result; an ambiguous event stays pending.
            if len(results) != 1:
                continue
            dispatch, result = dispatches[results[0]["tool_use_id"]], event.get("tool_use_result")
            if not isinstance(result, dict):
                dispatch.status = "failed"
                continue
            dispatch.resolved = result.get("resolvedModel")
            if result.get("status") == "completed":
                dispatch.status = "completed"
            elif result.get("status") != "async_launched":
                dispatch.status = "failed"
        elif event.get("type") == "system" and event.get("subtype") == "task_notification":
            # Background agents finish here; Bash tasks also notify, so only Agent tool_use ids count.
            dispatch = dispatches.get(event.get("tool_use_id"))
            if dispatch is not None:
                dispatch.status = "completed" if event.get("status") == "completed" else "failed"
    for key, dispatch in dispatches.items():
        dispatch.paths_touched, dispatch.paths_edited = sorted(touched[key]), sorted(edited[key])
        requested, resolved = dispatch.requested, dispatch.resolved
        # Claude resolves an alias such as opus to claude-opus-<version>; an omitted model inherits the parent's.
        dispatch.usable = dispatch.status == "completed" and isinstance(resolved, str) and bool(resolved) and (
            requested is None or resolved == requested or resolved.startswith(f"claude-{requested}-"))
    return list(dispatches.values()), None


def claude_parent_commands(lines):
    """Return the Bash calls the host itself made, in call order, from `claude -p --output-format stream-json --verbose` output.

    A subagent's tool calls stream under its Agent call's id, so only calls with no parent_tool_use_id are the host's.
    """
    commands, pending = [], {}
    for event in json_events(lines):
        for block in _blocks(event):
            arguments = block.get("input") if isinstance(block.get("input"), dict) else {}
            if (event.get("type") == "assistant" and event.get("parent_tool_use_id") is None and block.get("type") == "tool_use"
                    and block.get("name") == "Bash" and isinstance(arguments.get("command"), str)):
                pending[block.get("id")] = ShellCommand(arguments["command"], ABSOLUTE_PATH.findall(arguments["command"]))
                commands.append(pending[block.get("id")])
            elif event.get("type") == "user" and block.get("type") == "tool_result" and block.get("tool_use_id") in pending:
                _claude_result(pending.pop(block["tool_use_id"]), block)
    return commands


def _claude_result(command, block):
    """Record a Bash call's tool_result on its command. It ran unless Claude reports an error that gives no exit code."""
    command.output = _text(block.get("content"))
    command.ran = not block.get("is_error") or CLAUDE_EXIT.match(command.output or "") is not None


def codex_parent_commands(lines, codex_home):
    """Return the shell commands the host itself called, from its own session rollout, each with its working directory.

    The rollout holds only the host's own items, as the `codex exec --json` stream does, and adds the cwd that a
    command run with a workdir names nowhere else.
    """
    try:
        thread, rollouts, gap = _codex_rollouts(lines, codex_home)
        if gap:
            return []
        return [_codex_command(payload["item"]) for _, payload, _ in _payloads(rollouts[thread])
                if payload.get("type") == "item_completed" and isinstance(payload.get("item"), dict)
                and payload["item"].get("type") == "CommandExecution" and payload.get("thread_id") in (None, thread)]
    except OSError:
        return []


def _codex_command(item):
    """A Codex CommandExecution item as a ShellCommand: its script, the paths it names, and its cwd. It ran when Codex
    recorded its exit code; one Codex declined has none."""
    command = item.get("command")
    # Codex runs each command as [shell, -lc, script].
    script = str(command[-1]) if isinstance(command, list) and command else str(command or "")
    paths = ABSOLUTE_PATH.findall(" ".join(map(str, command)) if isinstance(command, list) else script)
    if isinstance(item.get("cwd"), str):
        paths.append(unquote(urlparse(item["cwd"]).path))
    return ShellCommand(script, paths, _text(item.get("aggregated_output", item.get("stdout"))), type(item.get("exit_code")) is int)


def _text(content):
    if isinstance(content, list):
        content = "\n".join(part.get("text", "") for part in content if isinstance(part, dict))
    return content[:OUTPUT_LIMIT] if isinstance(content, str) else None


def codex_native_dispatches(lines, codex_home):
    """Return the host's spawn_agent dispatches from the session rollouts named by `codex exec --json` output.

    The --json stream omits collaboration calls, so the parent rollout supplies each requested model
    and the child rollout's turn_context the model that actually ran.
    """
    try:
        return _codex_native_dispatches(lines, codex_home)
    except OSError as error:
        return [], f"cannot read Codex rollouts: {error}"


def _codex_rollouts(lines, codex_home):
    """Return the host's thread id from `codex exec --json` output, every session rollout by thread, and a gap when
    the host's own rollout is missing."""
    thread = next((event["thread_id"] for event in json_events(lines)
                   if event.get("type") == "thread.started" and isinstance(event.get("thread_id"), str)), None)
    if not thread:
        return None, {}, "codex --json log has no thread.started thread_id"
    sessions = Path(codex_home) / "sessions"
    rollouts = {}
    for path in sorted(sessions.rglob("rollout-*.jsonl")):
        match = ROLLOUT_NAME.fullmatch(path.name)
        if match:
            rollouts.setdefault(match.group(1), path)
    if thread not in rollouts:
        return thread, rollouts, f"no Codex rollout for thread {thread} under {sessions}"
    return thread, rollouts, None


def _payloads(path):
    for event in json_events(path.read_text(errors="replace").splitlines()):
        if isinstance(event.get("payload"), dict):
            yield event.get("type"), event["payload"], event.get("timestamp")


def _codex_native_dispatches(lines, codex_home):
    thread, rollouts, gap = _codex_rollouts(lines, codex_home)
    if gap:
        return [], gap
    requested, efforts, spawned, returned, started, finished, parent_turns = {}, {}, {}, set(), {}, set(), set()
    for _, payload, timestamp in _payloads(rollouts[thread]):
        if isinstance(payload.get("turn_id"), str):
            parent_turns.add(payload["turn_id"])
        if payload.get("type") == "function_call" and payload.get("name") == "spawn_agent":
            try:
                arguments = json.loads(payload.get("arguments") or "{}")
            except (TypeError, ValueError):
                arguments = {}
            arguments = arguments if isinstance(arguments, dict) else {}
            requested[payload.get("call_id")], efforts[payload.get("call_id")] = arguments.get("model"), arguments.get("reasoning_effort")
            spawned[payload.get("call_id")] = timestamp
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
        linked, models, complete, aborted, touched, edited, commands = False, [], False, False, set(), set(), []
        for kind, payload, _ in _payloads(child_rollout) if child_rollout else ():
            # A forked child's rollout begins with a copy of the parent's history, which keeps the parent's turn ids.
            if payload.get("turn_id") in parent_turns or payload.get("thread_id") not in (None, child):
                continue
            item = payload.get("item") if payload.get("type") == "item_completed" and isinstance(payload.get("item"), dict) else {}
            if kind == "session_meta":
                linked = linked or (payload.get("id") == child and payload.get("parent_thread_id") == thread)
            elif kind == "turn_context":
                models.append(payload.get("model"))
            elif item.get("type") == "CommandExecution":
                # The task payload is encrypted, so the child's own commands show which checkout it worked in.
                command = _codex_command(item)
                touched.update(command.paths)
                commands.append(command)
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
        dispatches.append(NativeDispatch(
            call, model, efforts.get(call), resolved, status,
            # Codex reports the model it ran; an omitted model inherits the parent's.
            usable=status == "completed" and isinstance(resolved, str) and bool(resolved) and model in (None, resolved),
            paths_touched=sorted(touched) if linked else [], paths_edited=sorted(edited) if linked else [], commands=commands if linked else [],
            thread=child, rollout=str(child_rollout) if linked else None, started=spawned.get(call),
        ))
    return dispatches, None


def _toplevel(directory):
    try:
        result = subprocess.run(["git", "-C", str(directory), "rev-parse", "--show-toplevel"], check=True, capture_output=True, text=True)
        return Path(result.stdout.strip()).resolve()
    except (OSError, subprocess.CalledProcessError, ValueError):
        return None


def checkouts_touched(paths, run_scope, parent):
    """Return the git checkouts under the run, other than the parent, that hold an existing path a subagent's tool calls used."""
    checkouts = set()
    for raw in paths:
        if not Path(raw).is_absolute():
            continue
        path = Path(raw).resolve()
        if not path.exists() or not path.is_relative_to(run_scope):
            continue
        top = _toplevel(path if path.is_dir() else path.parent)
        if top and top != parent and top.is_relative_to(run_scope):
            checkouts.add(top)
    return checkouts
