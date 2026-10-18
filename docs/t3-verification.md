# Verify T3 dispatch in a real thread

Run this after changing the T3 resolver or runtime contract. The offline tests cannot prove provider authentication, actual worker behavior or application-owned isolation. Use synthetic input only; do not modify production data, global permissions, or the configured review panel for a test. A writer plus one independent reviewer is a focused routing check, not completion of the configured full panel.

## Evidence to retain

Create a fresh evidence directory outside the reviewed files. Save the candidate source revision or patch and source hashes, the actual `show --host t3` policy, raw `orchestrator_capabilities` output, every `resolve` result, standalone brief, `delegate_task` response, terminal `task_status`, and `t3_thread_read` run/worktree metadata. Retain verification stdout, stderr and exit codes. Keep requested, T3-recorded and provider-observed model/effort in separate fields. A missing observation is unknown.

## Writer and reviewer

1. Use the synthetic `stats.py`, `TEST` and `CONTRACT_PROBE` already defined in `scripts/pstack-host-e2e.py`. Its contract covers nonempty finite numbers, including integers beyond the float range; empty inputs are outside scope. Record failing baseline tests. Preserve the fixed test and contract files by hash.
2. Save the live T3 catalog, resolve the intended writer role, and retain its exact `target`. An external xagent entry remains external; choose a configured T3 code role for this T3 check. Dispatch with `isolation: "worktree"`, a unique `clientRequestId`, the expected parent commit and a standalone brief. The child prepares the synthetic input under its own application-owned checkout before the repair and leaves the plugin source unchanged. The brief prohibits nested workers, global configuration and remote writes.
3. Read the returned child's actual `worktreePath` and verify its base. Record the prepared fixture's input hash and git baseline. Accept only a completed task with an available summary that you have read, and verify the fixture artifact yourself. A task ID or an idle turn is not a result. Retry the identical dispatch ID only to recover its response; a new repair/review round uses a new ID.
4. Resolve the reviewer with `--checked` set to the writer's resolved target; it should report `selection.strategy: cross-family`, and a family warning makes the result a same-family review. Dispatch a fresh application-owned worktree from the same intended source commit. Supply the writer's final candidate as a named content snapshot; verify its hash after preparation. The reviewer inspects that final candidate, runs the fixed tests and contract probe, and records read-only before/after snapshots. It must not edit the plugin, candidate or tests. T3's review role is only a label, so check the artifacts and tool evidence rather than trusting the label.
5. Read both terminal results and provider metadata. Assert two distinct worktree paths, correct base commits, exact final candidate reviewed, unchanged tests, no read-only violation, successful parent-run final tests and contract probe, and equality of requested vs T3-recorded targets. Check provider-observed model and effort when available; report an unobservable field rather than treating request metadata as its proof.
6. Exercise a negative case: an unavailable target must fail at preview before any dispatch; a stale candidate or modified test must fail the artifact check. Preserve that failed check beside the passing result. Do not alter a fixed test or acceptance predicate to make the run pass.

The existing host harness's `RUN_CHECK` and `write_parent_verifier` provide bounded verification and fresh bytecode-cache handling for this fixture. Reuse them when scripting the procedure. A parent independently runs the contract after the reviewer; it does not accept the worker's test receipt alone.

## Completion boundary

If the source changes after the check, rerun affected checks; if the fixture's final source changes after review, obtain a new review. Record the exact tested revision. Native Claude/Codex behavior is still covered by the [dual-host harness](../ADAPTATION.md#verification); a T3 result does not replace that evidence when those routes change. Do not publish, merge, or delete task evidence as part of this procedure.
