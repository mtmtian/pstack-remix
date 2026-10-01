---
name: xagent
description: Dispatch a task to another local coding agent (claude, codex, grok, gemini, pi) headlessly and collect a PASS/ISSUES/BLOCKED verdict. Use when a pstack policy entry is `xagent:<agent>`, or when the user asks to run a swarm, arena, review panel or second opinion across different agents or model families, from any host.
---

Read [the shared runtime contract](../../references/runtime.md) before this workflow.

# xagent

One CLI turns any local agent into a pstack worker, whichever agent is the host. It requires Python 3.9+ and a POSIX host; the pi guard also needs the installed pi runtime. No package download is needed.

```sh
<plugin-root>/bin/xagent <claude|codex|grok|gemini|pi> <ro|rw> <workdir> <prompt-file> <out-dir> [timeout-sec]
```

`~/.local/bin/xagent` links to the checkout's `bin/xagent` on this machine. Each attempt needs a new empty out-dir, separate from workdir. Each run writes `prompt.md`, `result.md`, `agent.log` and an atomically replaced `meta.json`; pi also writes `guard.log`. The receipt includes `status`, `exit`, `seconds`, `completed`, `timed_out`, `cancelled`, `reason` and `changed_workdir`. A receipt with `completed=false` is an interrupted/in-progress attempt, never completion evidence. Timeout and cancellation stop the worker's process group, with one second for termination before a forced stop, and preserve partial output.

Claude workers keep their normal session persistence by default. For disposable checks, set `XAGENT_EPHEMERAL=1` to pass `--no-session-persistence`; those Claude sessions cannot be resumed. Both `scripts/xagent-e2e.sh` and `scripts/pstack-host-e2e.py` enable it for their hosts and workers automatically. Run evidence and receipts are still written to the output directory.

## Agents

| agent | ro | rw |
|---|---|---|
| claude | plan mode | acceptEdits; commands from `bin/xagent-allowed-commands` |
| codex | read-only sandbox | workspace-write sandbox; any command |
| grok | auto mode in the workspace sandbox (see below) | auto mode in the workspace sandbox |
| gemini | plan mode | accept-edits; commands from `permissions.allow` in `~/.gemini/antigravity-cli/settings.json` |
| pi | read/grep/find/ls | + edit/write inside workdir, bash from `bin/xagent-allowed-commands`, both through `bin/xagent-pi-guard.ts` |

claude needs `claude auth login` once. The agy allowlist mirrors `bin/xagent-allowed-commands`; `scripts/xagent-e2e.sh` fails on drift. agy ends a headless run with no reply when gemini tries any other command, so xagent tells gemini its limits in the brief; a gemini `DROPOUT` usually means it tried anyway.

Grok's built-in read-only sandbox refuses to start while `/var/run/docker.sock` is a symlink, so its readers can still write the workdir. A prompt or a tool allowlist is not an OS sandbox. Give every external reviewer an exclusively owned checkout at the intended revision, just as for writers; never dispatch a potentially writable reader into the user's shared checkout. If reviewing uncommitted work, copy the intended patch and needed untracked files into that isolated checkout first and record what was reviewed. The parent creates and verifies this isolation; xagent does not create worktrees.

For `ro`, xagent checks HEAD, index entries, tracked file contents and non-ignored untracked contents. Its own nested out-dir is excluded. The receipt's `snapshot_before` and `snapshot_after` digests bind the result to the checkout actually reviewed; keep that checkout unchanged when reusing its evidence. A changed checkout sets `changed_workdir=true` and prevents a PASS (`ISSUES`, reason `read_only_violation`, unless execution already dropped out). An unavailable snapshot, including a non-Git directory or populated submodule, yields `changed_workdir=null` and `BLOCKED`; it is never reported unchanged. Preserve evidence in that worker's checkout, reject the result, and inspect it. Do not restore or reset a shared checkout. These checks are for accidental changes, not protection against hostile code or concurrent filesystem replacement.

The pi write guard accepts plain relative or absolute paths, including paths through existing internal symlinks. Use plain paths instead of `@`, `~`, URI or Unicode-space aliases that pi would normalize. Bash checks accept a limited non-expanding command syntax with ordinary quoted arguments, and reject output redirection and `--output` options. Tests/build scripts still execute project code, so this is an accident guard, not a sandbox.

## Rules for the parent

1. Write one standalone brief file per task. xagent appends the verdict contract and a do-not-delegate line.
2. Give every attempt its own empty out-dir and every worker its own git worktree at the intended SHA. Keep the initial SHA and scope in its brief.
3. Launch runs in the background with the host's own mechanism and wait for real completion. Several xagent calls may run in parallel.
4. Check actual process completion and `meta.json` `completed`/`status`, never the exit code alone. Only an unquoted final verdict outside a code block is accepted. `DROPOUT` means no usable verdict: inspect partial changes and process termination before rerunning once into a new output directory, then record a gap. Do not automatically retry a cancelled task. Usage errors return 2 without starting a worker.
5. `PASS` is the worker's claim. Missing required checks count as incomplete work; optional unverified checks must be named. Read the diff and rerun the checks yourself before accepting it.
6. Workers cannot dispatch again: xagent refuses when `XAGENT_DEPTH` is set.
7. Dispatching sends the brief and the workdir's code to that agent's vendor. Confirm non-public code may leave the machine.

## With pstack

A role or panel entry `xagent:<agent>` runs that worker through xagent instead of the host's subagent tool, with the brief the workflow would give a native worker. Reviewers, judges and explorers run `ro`; writers run `rw`. Shared entries apply to every host; `hosts.<host>` entries override them, which is how each host gets the other family as its reviewer.

## Checks

- `scripts/xagent-classify.test.sh`, `python3 scripts/xagent.test.py` and `node --test scripts/xagent-pi-guard.test.mjs`: offline, including deterministic read-only violations and unresponsive/cancelled processes.
- `scripts/xagent-e2e.sh [run-dir]`: every agent in both modes, allowlist denials, the agy mirror, nested refusal, timeout, and Codex as host. Calls every vendor.
