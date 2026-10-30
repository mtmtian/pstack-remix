---
name: interrogate
description: "Use for \"interrogate\", \"adversarial review\", \"multi-model review\", \"challenge this\", \"stress test this code\", \"find blind spots\", or \"tear this apart\". Adversaries try to break a change or design, and only findings proven by a run survive."
---

Read [the shared runtime contract](../../references/runtime.md) before this workflow.

# Interrogate

Adversaries try to break a change or a design. A finding survives only when a run proves it. Report the findings. Do not apply fixes.

## Frame

The scope is what the user names. Otherwise it is the branch diff from its merge base with the base branch, through the working tree. State the intent with the **in-your-own-words** skill, from the user's message, the commits, and the PR description. Ask the user when the intent is unclear.

## Fan out

Run Phase A steps 3 and 4 and Phase B of the **arena** skill, with four changes. Read the `interrogate reviewers` list from the effective policy from `node <plugin-root>/bin/config.mjs show --host <codex|claude|t3>` in place of `arena runners`, one adversary per entry. Copy the scope's uncommitted changes into each worktree. Spawn each adversary as a worker that can edit files and run commands in its own worktree; an `xagent:<agent>` adversary runs `rw`, and its dropouts follow the retry and unresolved-outcome rule, as the [xagent skill](../xagent/SKILL.md#with-pstack) describes. An `xagent:claude`, `xagent:gemini`, or `xagent:pi` adversary runs only the commands in `<plugin-root>/bin/xagent-allowed-commands`, so tell it to prove each finding with a test that one of those commands runs. In place of the arena task and rationale, give each adversary the scope, the intent, and this brief:

> Break this change. Prove each finding with a run against the real code, such as a failing test, a repro script, or command output that shows the wrong behavior. For a design or plan, run a prototype or probe the current tree. Keep repros in your own worktree. Report each finding with a title, the exact command, the output it printed, and the output the intent requires. Leave out anything you did not run. That covers style, naming, structure, and risks that need a future change to matter. No findings is a valid result.

## Verify

Verify each finding per arena Phase F by rerunning its command yourself in that adversary's worktree. Keep a finding when the output shows the failure and the failure breaks the intent. Drop the rest. Merge findings that share a root cause.

Skip arena Phases C, D, and E. Adversaries find different failures, so the verdict keeps every verified finding, not one adversary's list.

## Output

- **Intent**: the restatement.
- **Findings**: for each verified finding, the command, its output, how it breaks the intent, and the adversaries that found it. Say "no verified findings" when none survive.
- **Dropped**: for each adversary, the count of dropped findings and why.

Name each adversary's model, and say which ones shared the inherited model: those are independent runs, not distinct model families. Say which adversaries ran no command.
