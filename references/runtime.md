# Shared pstack runtime

All bundled skills use this contract. Resolve sibling skills from this plugin's `skills/` directory, not an unrelated same-named installed skill. User, project, and host instructions take precedence over this package.

## Select the host once, then load its adapter

Use the actual session identity and exposed tools, not the plugin's directory name. Both hosts install the same source directory.

- Codex: read [codex-runtime.md](./codex-runtime.md). The existing plugin name remains `pstack-codex`.
- Claude Code: read [claude-runtime.md](./claude-runtime.md). The plugin name is `pstack`.
- Another host: use only observed capabilities. Do not assume either API works there.

Examples using `$skill-name` in shared prose mean the bundled skill, not literal syntax to pass to every host. Codex entry: `$pstack-codex:poteto-mode`. Claude Code entry: `/pstack:poteto-mode`. Read sibling files directly when the host does not expose them as callable skills. Treat poteto-mode as a conversation instruction until the user opts out; it does not register a global mode or create a goal.

## One configuration, inherited by workers

At the start of a pstack task, run:

```sh
node <plugin-root>/bin/config.mjs show --host codex
# In Claude Code use --host claude instead.
```

Resolve `<plugin-root>` from this skill's installed path. The canonical configuration is `~/.config/pstack/config.json`, outside either host's plugin cache. If the file is absent, the helper returns inherited defaults without writing anything. Only setup or an explicit configuration request writes preferences. Do not ask every worker to run setup.

Shared `roles`, `panels`, and `reasoning_effort` define policy for both hosts. Shared model choices are `inherit-parent`, `auto`, or an `xagent:<agent>` entry (below); concrete model IDs belong only in `hosts.codex` or `hosts.claude`. Host entries override the corresponding shared entries. Missing roles inherit the main conversation; a missing panel uses the helper's `defaultPanel`, two independent inherited-model attempts plus any required panel members. Model availability is validated against the running host, not against upstream names or this JSON schema. A requested unavailable model is an unresolved choice, not permission to silently substitute. Never splice reasoning effort into a model ID.

A value `xagent:<agent>` (for example `xagent:grok`) names an external agent CLI, not a host model, so it is valid in shared policy and resolves the same on every host. Never pass it as a subagent `model`. Run that worker with `<plugin-root>/bin/xagent <agent> <ro|rw> <workdir> <brief-file> <out-dir>` as specified in the bundled [xagent skill](../skills/xagent/SKILL.md): `ro` for reviewers, judges, and explorers; `rw` for writers. The parent gives every external worker, including readers, an exclusively owned worktree at the intended revision and every attempt a new output directory. Give it the same standalone brief a native worker would get. Its evidence is process completion, `meta.json` completed/status and `result.md`, held to the same standard as a native worker's result; a `PASS` still needs the parent's own check. Reject read-only violations and unavailable snapshots without resetting a shared checkout.

Shared `required_panel_members` lists `xagent:<agent>` entries that `show` appends to every effective panel and to `defaultPanel` on both hosts, so no per-panel or host list can leave them out. Run every entry of the effective panel; a pool such as `arena cross-judge pool` still selects one. An `xagent:<agent>` entry is never replaced by an inherited model or another agent and never dropped to finish with N-1. Unless the user set a time limit, give an external worker at least xagent's 900-second default. On `DROPOUT`, inspect partial changes and rerun once into a new output directory; without a user-set limit, double the timeout when the first attempt timed out. A second `DROPOUT`, `BLOCKED`, a missing CLI, or an agent xagent rejects is an unresolved required outcome: report it by agent name, keep it out of coverage and consensus claims, and do not call the panel or task complete unless the user waives it.

Each worker brief carries the selected host, plugin root, configuration path, resolved role/panel policy, scope, and verification predicate. A read-only child without command execution uses this supplied snapshot. If none was supplied, it may read the single shared JSON file and apply the host-over-common precedence; an absent file means inherited defaults. It must not invent a Bash tool or run setup. Use the same policy snapshot throughout one task unless the user changes it. A worker inherits this policy; it does not edit shared preferences. Same-family reviewers are independent attempts, not cross-family evidence.

The [setup skill](../skills/setup-pstack/SKILL.md) owns initialization, optional legacy import, and updates. Configuration is not a credentials store. Do not write keys or tokens there.

## Authorization and execution

Installing or invoking pstack grants no additional authority. Continue authorized local work. Remote messages, PR writes, pushes, merges, publishing, resource creation, and destructive cleanup require authorization for that action and scope. An overnight request does not widen it. Preserve unrelated work and all named approval gates. A read-only assessment stays read-only; a plan is not authorization to execute it.

Use supported delegation tools only where independent work helps. Choose the actual host role and fields from its schema. Writers get owned files or separate worktrees; never claim a cloud VM or isolation that was not created. At the nesting or concurrency limit, do feasible work directly and disclose any unmet independent-review gate. Read final artifacts and terminal results yourself. Empty mailboxes, idle states, timeouts, or query errors do not prove completion. Do not cancel an active child merely to clear a badge. Resolve ownership before replacement to avoid two writers.

The parent judges completion against the stated task contract and its own checks, including reproduced reviewer counterexamples. A completed review is evidence, not acceptance of the change. An unresolved violation inside that contract prevents PASS or a claim that the task is complete; finish the authorized repair, or report ISSUES/BLOCKED with the remaining work. Only the user can waive a required outcome. Explain why rejected findings are incorrect or outside the contract; keep optional style preferences separate from blockers.

Goals, process/event waits, and recurring schedules are separate capabilities. Follow the selected host adapter for a finite goal explicitly requested by the user. Poll only real returned handles. A shell sentinel does not revive an ended turn. Recurrence requires the host's actual scheduler and a verified registration result; never create implicit OS jobs or promise restart survival without evidence. Keep waits bounded so active-work updates remain possible.

## Shared project skills

Keep new project skills in `.agents/skills/<name>/` and personal skills in `~/.agents/skills/<name>/`. First inspect existing `.agents/skills/` and `.claude/skills/`; an existing skill remains authoritative. Resolve symlinks and do not create two copies of one feature map.

When creating a new shared skill on this local filesystem, expose the canonical directory to Claude Code with a relative directory symlink from `.claude/skills/<name>` to `../../.agents/skills/<name>` (the same relative layout works for personal skills). Create the parent directory if needed; do not overwrite a file, directory, or different symlink already at the destination. Check the resolved target and actual host discovery. If linking is unavailable, keep one canonical copy and report the discovery limitation; direct reading still works. Do not link the entire shared skills directory over existing Claude skills.

For authoring, use an available skill-creator when present. Otherwise edit SKILL.md directly with `name` and `description`, validate YAML and local references, then exercise the behavior it teaches. Do not require a Codex-only authoring skill in Claude Code. Generated verification skills and their feature maps stay project-local.

## Tools and evidence

Prefer the project's existing verification harness. In this user's environment, browser rendering, clicks, login, screenshots, and dynamic extraction use `ego-browser` and its isolated task space. Do not start the default browser. CLI/TUI verification uses documented commands and isolated PTYs. Missing control surfaces or credentials are concrete prerequisites, not permission to invent evidence.

Upstream `deslop`, `control-ui`, and `control-cli` dependencies are replaced by direct diff review and actually available tools. `gh` is the default forge; use Origin/Graphite only when present, compatible, and authorized. Do not install optional connectors or activate the dormant Benny pack implicitly.

Use the current task and authorized project artifacts first. For history, follow the host adapter; restrict local transcript candidates by repository/cwd, session, and time before reading content. Do not mine unrelated sessions or write persistent memory without an explicit request.

The Node helpers `bin/orch.mjs`, `bin/watch-pr.mjs`, and `bin/config.mjs` need no runtime dependency downloads. Resolve them from the plugin root, never the target project's current directory. Source helper development uses Bun; only rebuild the existing bundles when their TypeScript sources change. Keep verification evidence after cleanup. Discovery, structural validation, script tests, and actual agent behavior are separate gates.
