---
name: xagent
description: Dispatch a task to another local coding agent (claude, codex, grok, gemini, pi) headlessly and collect a PASS/ISSUES/BLOCKED verdict. Use when a pstack policy entry is `xagent:<agent>`, or when the user asks to run a swarm, arena, review panel or second opinion across different agents or model families, from any host.
---

Read [the shared runtime contract](../../references/runtime.md) before this workflow.

# xagent

One CLI turns any local agent into a pstack worker, whichever agent is the host.

```sh
<plugin-root>/bin/xagent <claude|codex|grok|gemini|pi> <ro|rw> <workdir> <prompt-file> <out-dir> [timeout-sec]
```

`~/.local/bin/xagent` links to the checkout's `bin/xagent` on this machine. Each run writes `prompt.md`, `result.md`, `agent.log` and `meta.json` (`status`, `exit`, `seconds`) to its out-dir; pi also writes `guard.log`.

## Agents

| agent | ro | rw |
|---|---|---|
| claude | plan mode | acceptEdits; commands from `bin/xagent-allowed-commands` |
| codex | read-only sandbox | workspace-write sandbox; any command |
| grok | auto mode in the workspace sandbox (see below) | auto mode in the workspace sandbox |
| gemini | plan mode | accept-edits; commands from `permissions.allow` in `~/.gemini/antigravity-cli/settings.json` |
| pi | read/grep/find/ls | + edit/write inside workdir, bash from `bin/xagent-allowed-commands`, both through `bin/xagent-pi-guard.ts` |

claude needs `claude auth login` once. The agy allowlist mirrors `bin/xagent-allowed-commands`; `scripts/xagent-e2e.sh` fails on drift. agy ends a headless run with no reply when gemini tries any other command, so xagent tells gemini its limits in the brief; a gemini `DROPOUT` usually means it tried anyway.

Only codex and claude enforce `ro`. grok's built-in read-only sandbox refuses to start while `/var/run/docker.sock` is a symlink, so its readers can still write the workdir. For every `ro` run in a git checkout, `meta.json` records `changed_workdir`; when it is `true`, treat the verdict with suspicion and restore the checkout.

## Rules for the parent

1. Write one standalone brief file per task. xagent appends the verdict contract and a do-not-delegate line.
2. Give every worker its own out-dir. Give every `rw` worker its own git worktree at the intended SHA.
3. Launch runs in the background with the host's own mechanism and wait for real completion. Several xagent calls may run in parallel.
4. Trust `meta.json` `status`, never the exit code alone. `DROPOUT` means no usable verdict: rerun once, then record a gap.
5. `PASS` is the worker's claim and may name checks it could not run. Read the diff and rerun the checks yourself before accepting it.
6. Workers cannot dispatch again: xagent refuses when `XAGENT_DEPTH` is set.
7. Dispatching sends the brief and the workdir's code to that agent's vendor. Confirm non-public code may leave the machine.

## With pstack

A role or panel entry `xagent:<agent>` runs that worker through xagent instead of the host's subagent tool, with the brief the workflow would give a native worker. Reviewers, judges and explorers run `ro`; writers run `rw`. Shared entries apply to every host; `hosts.<host>` entries override them, which is how each host gets the other family as its reviewer.

## Checks

- `scripts/xagent-classify.test.sh` and `node --test scripts/xagent-pi-guard.test.mjs`: offline.
- `scripts/xagent-e2e.sh [run-dir]`: every agent in both modes, allowlist denials, the agy mirror, nested refusal, timeout, and Codex as host. Calls every vendor.
