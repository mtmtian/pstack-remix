# Shared pstack runtime

Bundled workflow skills use this contract; short guidance skills, such as the principles, do not need it. Resolve sibling skills from this plugin's `skills/` directory, not an unrelated same-named installed skill. User, project, and host instructions take precedence over this package.

## Select the host once, then load its adapter

Use the actual session identity and exposed tools, not the plugin's directory name. Host packages use the same source tree.

- Codex: read [codex-runtime.md](./codex-runtime.md). The existing plugin name remains `pstack-codex`.
- Claude Code: read [claude-runtime.md](./claude-runtime.md). The plugin name is `pstack`.
- Antigravity: read [antigravity-runtime.md](./antigravity-runtime.md). Its configuration adapter exposes shared policy read-only; do not assume Codex or Claude APIs work there.
- Another host: use only observed capabilities. Do not assume either API works there.
- T3 Code is an overlay, not a separate host. When the session exposes T3's `orchestrator_capabilities` and `delegate_task` tools, load the Codex or Claude Code adapter above, then read [t3-runtime.md](./t3-runtime.md).

Examples using `$skill-name` in shared prose mean the bundled skill, not literal syntax to pass to every host. Codex entry: `$pstack-codex:poteto-mode`. Claude Code entry: `/pstack:poteto-mode`. Read sibling files directly when the host does not expose them as callable skills. Treat poteto-mode as a conversation instruction until the user opts out; it does not register a global mode or create a goal.

## One configuration, inherited by workers

At the start of a pstack task, run:

```sh
node <plugin-root>/bin/config.mjs show --host codex
# In Claude Code use --host claude instead.
# In Antigravity use --host antigravity for the read-only shared-policy view.
# In a T3 Code session (see t3-runtime.md) use --host t3, whichever host runs it.
```

Resolve `<plugin-root>` from this skill's installed path. The canonical configuration is `~/.config/pstack/config.json`, outside host plugin caches. If the file is absent, the helper returns inherited defaults without writing anything. Only setup or an explicit configuration request writes preferences; the [setup skill](../skills/setup-pstack/SKILL.md) owns initialization, optional legacy import, and updates. Do not ask every worker to run setup. Configuration is not a credentials store. Do not write keys or tokens there.

Shared `roles`, `panels`, `reasoning_effort`, `required_panel_members`, `auxiliary_panel_members`, and `xagent_effort_caps` define policy. Codex and Claude Code apply `hosts.codex` or `hosts.claude` over it; the Antigravity adapter and the T3 overlay say which view they read. Shared entries are `inherit-parent`, `auto`, or `xagent:<agent>[/<model>]`; concrete model IDs come only from a host's own section. Candidate objects and `@latest` family selectors are T3-only: they resolve to concrete targets before dispatch and are never native Agent model values. Missing roles inherit the main conversation; a missing panel uses the helper's `defaultPanel`, two independent inherited-model attempts plus any required panel members. Model availability is validated against the running host, not against upstream names or this JSON schema. A requested unavailable model is an unresolved choice, not permission to silently substitute. Never splice reasoning effort into a model ID. A native agent type whose definition sets its own effort keeps it, and keeps its own model when the role is `inherit-parent`; every other worker gets the effective `reasoning_effort`, `xagent:` workers through `--effort`. The host adapter names the fields.

An `xagent:<agent>` entry (for example `xagent:grok`, or `xagent:claude/claude-opus-5-5` with that CLI's own model) names an external agent CLI, not a host model, so it is valid in shared policy and never a subagent `model`. Before dispatching one, including every panel that `required_panel_members` joins, read the [xagent skill](../skills/xagent/SKILL.md#with-pstack): it defines the command, effort cap, isolation, evidence, panel membership, retries, and unresolved outcomes.

Each worker brief carries the selected host, plugin root, configuration path, resolved role/panel policy, scope, and verification predicate. A read-only child without command execution uses this supplied snapshot. If none was supplied, it may read the single shared JSON file and apply the host-over-common precedence; an absent file means inherited defaults. It must not invent a Bash tool or run setup. Use the same policy snapshot throughout one task unless the user changes it. A worker inherits this policy; it does not edit shared preferences. Same-family reviewers are independent attempts, not cross-family evidence.

## Authorization and execution

Installing or invoking pstack grants no authority beyond the playbooks' own steps. Continue authorized local work. As upstream does, a playbook commits, pushes the task's own branches, and opens or updates the task's PRs, including replies to and resolution of review threads on them, without asking first; a user who keeps a task local overrides that. Never push the trunk directly. Merges, `--auto`, force-pushes to a branch another person or agent works on, deploys, publishing, remote messages outside the task's PRs, resource creation, and destructive cleanup require authorization for that action and scope. An overnight request does not widen it. Preserve unrelated work and all named approval gates. A read-only assessment stays read-only; a plan is not authorization to execute it.

Use supported delegation tools only where independent work helps. Choose the actual host role and fields from its schema. Writers get owned files or separate worktrees; never claim a cloud VM or isolation that was not created. At the nesting or concurrency limit, do feasible work directly and disclose any unmet independent-review gate. Read final artifacts and terminal results yourself. Empty mailboxes, idle states, timeouts, or query errors do not prove completion. Do not cancel an active child merely to clear a badge. Resolve ownership before replacement to avoid two writers.

The parent judges completion against the stated task contract and its own checks, including reproduced reviewer counterexamples. A completed review is evidence, not acceptance of the change. An unresolved violation inside that contract prevents PASS or a claim that the task is complete; finish the authorized repair, or report ISSUES/BLOCKED with the remaining work. Only the user can waive a required outcome. Explain why rejected findings are incorrect or outside the contract; keep optional style preferences separate from blockers.

Goals, process/event waits, and recurring schedules are separate capabilities. Follow the selected host adapter for a finite goal explicitly requested by the user. Poll only real returned handles. A shell sentinel does not revive an ended turn. Recurrence requires the host's actual scheduler and a verified registration result; never create implicit OS jobs or promise restart survival without evidence. Keep waits bounded so active-work updates remain possible.

## Tools and evidence

Prefer the project's existing verification harness. Browser work uses the browser the user's or host's instructions name; CLI/TUI verification uses documented commands and isolated PTYs. Missing control surfaces or credentials are concrete prerequisites, not permission to invent evidence.

Upstream `deslop`, `control-ui`, and `control-cli` dependencies are replaced by direct diff review and actually available tools. `gh` is the default forge; use Origin/Graphite only when present, compatible, and authorized. Do not install optional connectors implicitly.

Use the current task and authorized project artifacts first. Read earlier sessions only as the [prior sessions guide](./session-history.md) describes; do not mine unrelated sessions or write persistent memory without an explicit request. Creating, placing, or substantially editing a skill follows the [project skills guide](./project-skills.md).

The Node helpers `bin/orch.mjs`, `bin/watch-pr.mjs`, `bin/config.mjs`, and `bin/transcripts.mjs` need no runtime dependency downloads. Resolve them from the plugin root, never the target project's current directory. Keep verification evidence after cleanup. Discovery, structural validation, script tests, and actual agent behavior are separate gates.
