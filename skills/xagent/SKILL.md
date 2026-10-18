---
name: xagent
description: Dispatch a task to another local coding agent (claude, codex, grok, gemini, pi) headlessly and collect a PASS/ISSUES/BLOCKED verdict. Use when a pstack policy entry is `xagent:<agent>`, or when the user asks to run a swarm, arena, review panel or second opinion across different agents or model families, from any host.
---

Read [the shared runtime contract](../../references/runtime.md) before this workflow.

# xagent

One CLI turns any local agent into a pstack worker, whichever agent is the host. It requires Python 3.9+ and a POSIX host; the pi guard also needs the installed pi runtime. No package download is needed.

```sh
<plugin-root>/bin/xagent <claude|codex|grok|gemini|pi>[/<model>] <ro|rw> <workdir> <prompt-file> <out-dir> [timeout-sec] [--effort low|medium|high|xhigh|max]
```

`~/.local/bin/xagent` links to the checkout's `bin/xagent` on this machine. Each attempt needs a new empty out-dir, separate from workdir. Each run writes `prompt.md`, `result.md`, `agent.log` and an atomically replaced `meta.json`; pi also writes `guard.log`. The receipt includes `status`, `exit`, `seconds`, `completed`, `timed_out`, `cancelled`, `reason` and `changed_workdir`, plus the requested `model` and `effort` (null when the CLI's own setting applied) and `resolved_models`, the models the CLI reports the run used (claude and grok from their JSON `modelUsage`, codex from the `model:` line of its log; null when the CLI reports none). A receipt with `completed=false` is an interrupted/in-progress attempt, never completion evidence. Timeout and cancellation stop the worker's process group, with one second for termination before a forced stop, and preserve partial output.

Claude workers keep their normal session persistence by default. For disposable checks, set `XAGENT_EPHEMERAL=1` to pass `--no-session-persistence`; those Claude sessions cannot be resumed. Both `scripts/xagent-e2e.sh` and `scripts/pstack-host-e2e.py` enable it for their hosts and workers automatically. Run evidence and receipts are still written to the output directory.

## Agents

| agent | ro | rw | model / effort flag |
|---|---|---|---|
| claude | plan mode | acceptEdits; commands from `bin/xagent-allowed-commands` | `--model` / `--effort` |
| codex | read-only sandbox | workspace-write sandbox; any command | `-m` / `-c model_reasoning_effort` |
| grok | auto mode in the workspace sandbox (see below) | auto mode in the workspace sandbox | `-m` / `--reasoning-effort` |
| gemini | plan mode | accept-edits; commands from `permissions.allow` in `~/.gemini/antigravity-cli/settings.json` | `--model` / `--effort` |
| pi | read/grep/find/ls | + edit/write inside workdir, bash from `bin/xagent-allowed-commands`, both through `bin/xagent-pi-guard.ts` | `--model` / `--thinking` |

A model after the agent's first `/`, such as `claude/claude-opus-5-5` or `pi/openai/gpt-6.1`, goes to that CLI's model flag, and `--effort` to its effort flag. Leave either out and the worker keeps the default from its own CLI configuration. The model is that vendor's own ID or alias, not the host's. Each CLI validates both itself: an unknown model or an effort the model does not support ends the run as `DROPOUT`, never as a quiet fallback to another model. A CLI that still runs another model, such as Claude replacing one the organization's model policy disallows with its default, is caught by its own report: when a model was pinned and none of `resolved_models` matches it, allowing for an alias such as `opus` resolving to `claude-opus-<version>` and for a helper model alongside, the run is `DROPOUT` with reason `model_mismatch`. Quote an agent argument containing `[` or `]`, such as `'claude/opus[1m]'`, in the shell. claude needs `claude auth login` once. The agy allowlist mirrors `bin/xagent-allowed-commands`; `scripts/xagent-e2e.sh` fails on drift. agy ends a headless run with no reply when gemini tries any other command, so xagent tells gemini its limits in the brief; a gemini `DROPOUT` usually means it tried anyway.

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

A role or panel entry `xagent:<agent>` or `xagent:<agent>/<model>` runs that worker through xagent instead of the host's subagent tool, with the brief the workflow would give a native worker. Pass everything after `xagent:` as the agent argument, and the worker's effort, meaning the effective `reasoning_effort` after poteto-mode's per-job adjustment, as `--effort`; with no effective value, omit it. Reviewers, judges and explorers run `ro`; writers run `rw`. Shared entries apply to every host; `hosts.<host>` entries override them, which is how each host gets the other family as its reviewer. Shared `required_panel_members` adds its agents to every panel on both hosts, and the runtime never lets a panel substitute or silently drop an `xagent:<agent>` entry. `xagent:claude` and `xagent:claude/opus` are different workers, so a required `xagent:claude` still joins a panel that already has `xagent:claude/opus`.

## Checks

- `scripts/xagent-classify.test.sh`, `python3 scripts/xagent.test.py` and `node --test scripts/xagent-pi-guard.test.mjs`: offline, including deterministic read-only violations and unresponsive/cancelled processes.
- `scripts/xagent-e2e.sh [run-dir]`: every agent in both modes, each CLI accepting `--effort` and any model pinned in `XAGENT_E2E_MODELS`, allowlist denials, the agy mirror, nested refusal, timeout, and Codex as host. Calls every vendor by default. A run with `XAGENT_E2E_AGENTS` covers only the listed vendors in both modes, while its fixed cases still call codex, gemini and pi; record it as partial evidence that names the vendors left out.
