---
name: swarm
description: "Fan out N parallel workers, drain them, and return one report. Use for $swarm, 'swarm this', or parallel coverage, races, gauntlets, and exploration."
---

Read [the shared runtime contract](../../references/runtime.md) before this workflow.

# Swarm

Fan out N independent workers within the actual host concurrency limit. They may cover separate slices, race the same brief, or mix both. The parent waits, aggregates, and returns one report.

## Start

Open a todolist with one entry per phase before launching anything.

1. Frame
2. Fan out
3. Aggregate
4. Report

## Phase A: Frame

1. State the done predicate and the artifact or report the swarm must return.
2. Choose the shape. Partition into slices, race N workers on identical briefs, or mix both. For a race or mixed shape, declare `first pass`, `rank all`, or `best-of` before spawning.
3. Set N from the user or derive it from the shape. N is total workers, not the cloud concurrency limit.
4. Pick the worker model from `swarm workers` in the effective policy from `node <plugin-root>/bin/config.mjs show --host <codex|claude>` when present. Otherwise use `inherit-parent`. For a model race, name each arm's model up front.
5. Give each worker its own writable output when it writes. When workers verify or measure commits, name the exact SHAs in each brief. Measurement briefs also name the sample count, what constitutes a sample, and execution order. Require the worker to record those SHAs and the method in its result.

## Phase B: Fan out

Spawn independent workers through the actual collaboration tool. Choose task-appropriate supported roles; apply only available model overrides. Use a bounded rolling window when N exceeds host capacity. Isolate writers with owned files or separate worktrees; local workers share this machine.

When a worker needs a non-default branch, prepare and verify a worktree at that branch and pass its exact path in the brief. Do not assume a tool parameter switches its checkout.

Every brief stands alone. Include the goal, scope, exact slice or race arm, how to verify, and what to report. Reports use `PASS`, `ISSUES`, or `BLOCKED` with evidence. A worker that can prove a defect reports `ISSUES` and lists every issue it can prove, not only the first.

If a worker drops out, proceed with N-1 and note it.

## Phase C: Aggregate

Read the terminal results. Drop a result that does not record the SHAs and method its brief names, and rerun that worker once. After a second miss, record a gap. A gap does not count as a pass. For coverage, every required slice needs a result. For a race, apply the selection rule declared up front. Use first pass, rank all, or best-of. Do not paste raw worker dumps.

Keep a compact result table, one-line evidenced issues, and explicit gaps or dropouts.

## Phase D: Report

Return one consolidated in-chat report with the table, issue one-liners, gaps or dropouts, and the race rule when used.
