# T3 Code overlay

Read [the shared runtime](./runtime.md) and the Codex or Claude Code adapter first. T3 Code runs one of those hosts underneath, so files, shell, skill entry points, goals, and project instructions still follow that host adapter. This overlay replaces only four things: model resolution, delegation, scheduling, and PR watching.

## When it applies

Apply it only when the current session exposes T3's orchestration tools `orchestrator_capabilities` and `delegate_task`, under any MCP prefix such as `mcp__t3-code__delegate_task`. An environment variable such as `T3CODE_CLI_PATH` is not enough, because processes started from a T3 thread inherit it without the tools. Without both tools, ignore this file and use the host adapter alone. A T3 child that exposes the tools follows this overlay for nested work inside its brief and limits.

## Resolve policy

Run `node <plugin-root>/bin/config.mjs show --host t3`. The T3 view is common policy plus the optional `hosts.t3` section. It never reads `hosts.codex` or `hosts.claude`, whichever host runs the thread, because those hold host-native IDs. Update it with `update --host t3`, through [setup](../skills/setup-pstack/SKILL.md).

A T3 entry is `inherit-parent`, `auto`, `xagent:<agent>`, or a T3 target `<providerInstanceId>/<modelId>`. Split a target at the first `/`; model IDs may contain more slashes.

Call `orchestrator_capabilities` once before the first dispatch of a task and check every target it will use: the provider instance is listed, `canRunChildTask` is true, `canRunCrossProviderChildTask` is true when the provider differs from `inheritedProviderInstanceId`, and the model is in that provider's `models`. A failed check is an unresolved choice under the shared rules. Report the entry with the provider's `constraints` text. Do not substitute another model, provider, or `xagent:<agent>` unless the user says so.

| Entry | `delegate_task` target |
| --- | --- |
| `inherit-parent`, `auto` | Omit `target`. T3 inherits the thread's provider, model, and options. T3 has no automatic router, so `auto` inherits too |
| `<providerInstanceId>/<modelId>` | `{"providerInstanceId": "<id>", "model": "<model>"}` |
| `xagent:<agent>` | Not a T3 target. Run it with `bin/xagent` as the shared runtime specifies |

Map the effective `reasoning_effort` to the target model's own option: the listed select option with id `effort` or `reasoningEffort`, only when the value is one of its choices. Pass it as `target.options`, for example `{"effort": "high"}` for `claudeAgent` or `{"reasoningEffort": "high"}` for `codex` and `grok`; an inherited entry passes only `options`. Otherwise omit it and disclose that the model ran at its default. A target with no effort option otherwise runs at the provider default, which can be low, so set `reasoning_effort` in `hosts.t3` for review panels. Do not set other options, such as service tier or fast mode, unless the user asked.

## Delegate

In a T3 session every pstack worker goes through `delegate_task`, including `inherit-parent` roles, so each child is owned by and visible in the thread. Do not also use the host's native subagent tool for the same role.

| pstack action | On T3 |
| --- | --- |
| Start a worker | `delegate_task` with `mode: "async"`, the target above, a `title`, a `role` (`review` for reviewers and judges, `research` for explorers, `design` for architect and arena runners, `implementation` for writers, `test` for verification), and a `clientRequestId` such as `<skill>-<run>-r<round>-<member>`, stable across retries of that round. Keep the returned `taskId` |
| Parallel workers | One `delegate_task` call per entry in the same response |
| Wait | End the turn. The child's completion wakes the thread. Call `task_status` only when this turn needs the result. Accept only `status: completed` with `workState: result_available` and a `summary` you have read. `working`, `waiting_for_children`, or `waitTimedOut` is not completion. A `failed` status also reports `result_available`; treat it as that entry's `DROPOUT` under the shared rules, since `canRunChildTask` does not prove the provider is authenticated |
| Fix round or follow-up | A new `delegate_task` with the original brief, every later directive, prior findings, responses, and unresolved objections, and a new `clientRequestId`. Never `t3_thread_send` to a `childThreadId` |
| Stop a worker | `task_cancel`, then `task_status` to confirm |
| `poteto-agent`, `comment-sicko` | Open the task with the absolute path of `agents/poteto-agent.md` or `agents/comment-sicko.md` and tell the child to read it first, as on Codex |

Every brief is standalone, because the child gets no parent history. It carries the shared runtime's fields: host, plugin root, configuration path, the resolved T3 policy snapshot, scope, and verification predicate.

A T3 child works in the parent's workspace unless told otherwise. For a read-only child, say so in the brief, ask it to run code only in ways that write nothing (for example `python3 -B`), and record `git status --porcelain --ignored` and `HEAD` before launch. Any change after it returns, including a stray `__pycache__`, is a read-only violation, whatever the child reports. Give each writer its own worktree at the intended base SHA, created by the parent with `git worktree add`, and pass the absolute path. Two writers never share a checkout.

## Mixed panels

`xagent:<agent>` entries, including `required_panel_members`, still run through `bin/xagent` from the host shell. They are the only path to agents T3 does not list, such as Gemini. Start T3 targets first so they run while the xagent commands block the shell call, then collect both. A family listed both as a T3 target and as `xagent:<agent>` runs twice, as two independent attempts. Count and label them that way. The final reply names the provider and model, or xagent agent, that ran each step, with its `taskId` or output directory.

## Schedules and PRs

- Recurrence the user asked for uses `schedule_task` bound to this thread instead of the host's `/loop` or Cron tools. Report the returned cadence and `nextRunAt`, and delete it with `delete_scheduled_task` when the loop ends.
- To wait on a PR between babysit rounds, call `watch_pull_request` after handling existing comments, then end the turn. `bin/watch-pr.mjs` still decides readiness. Call `unwatch_pull_request` before handing the PR back. Only the parent thread can watch. Register PRs this work creates or updates with `link_pull_request`.
- `t3_thread_launch` and `create_threads` create top-level threads. Use them only when the user asks for separate threads, never for pstack workers.
