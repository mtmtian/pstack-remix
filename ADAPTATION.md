# Shared pstack adaptation

Upstream pstack 0.15.32 at `e73df471cd4bd918367e99f3dd9c51bd53ddf5f0` (#800–#807 after the release), synced 2026-10-24. MIT attribution is preserved.

This guide records what this fork does differently from upstream and why. Each section states the current decision; the [sync log](#sync-log) says when each sync landed, and its pull request holds the details of that sync.

## Maintained source

The repository `mtmtian/pstack-remix` is maintained as one checkout per machine for every host. `.codex-plugin/plugin.json` preserves the installed Codex name; `.claude-plugin/plugin.json` exposes the Claude name `pstack`; the root `plugin.json` is the Antigravity manifest. The repository includes native marketplace manifests for Codex and Claude Code, named `pstack-local`. Existing Codex `personal` registrations may keep pointing at the same checkout. All hosts consume the same 58 skills, 23 playbooks, 2 agent files, and runtime helpers. Host caches are generated installation artifacts, never edit targets. Installing the package arms no messages, remote writes, webhooks, goals, or scheduled runs.

Shared preferences live at `~/.config/pstack/config.json`. `bin/config.mjs` supplies read-only resolution, idempotent initialization/legacy import, host-scoped updates, null-to-remove overrides, validation, locking, and atomic writes. A concrete model ID cannot be stored in the common policy. An `xagent:<agent>` entry can, because `bin/xagent` dispatches it to the named local agent CLI the same way from either host; so can `xagent:<agent>/<model>`, whose model goes only to that CLI's own model flag. `bin/xagent --effort` maps the worker's effort to each CLI's own effort flag, and the receipt records the requested model and effort. Actual model/effort availability is still checked by each running host. No global host model or permission setting is changed by setup.

### Runtime contract

`references/runtime.md` holds the shared contract, about 8.5KB: host selection, configuration, delegation, authorization, completion, goals, and evidence. The Codex and Claude adapters hold only native tool, effort, goal, and history differences. Every workflow skill reads the contract; parent agents relay the same resolved policy to workers. Each detail with one set of readers lives with them instead:

- The xagent command, effort cap, evidence, panel membership, retries, and unresolved outcomes are in the xagent skill's With pstack section. The contract sends every xagent dispatch there, including every panel that `required_panel_members` joins, and swarm, arena, interrogate, the T3 overlay, and the Claude adapter cite it for the retry and blocking rules.
- T3 resolution is in the T3 overlay; Antigravity's view and effort limits are in its adapter.
- Skill placement, discovery links, and authoring are in `references/project-skills.md`, linked from the skills and the playbook that create or edit skills. Canonical project skills stay in `.agents/skills`, with individual non-overwriting `.claude/skills` links for discovery. Existing projects are not rewritten by installation.
- Transcript listing is in `references/session-history.md`, linked from `recall`, `correct`, and `automate-me`.

The 26 short guidance skills listed in `STANDALONE` in `scripts/check-fork.mjs` (the principles, `bro`, `in-your-own-words`, `sharpen`, `tdd`, `teach`, and `typescript-best-practices`) do not link the contract, as upstream's never did. They use nothing in it: no delegation, model choice, remote write, schedule, or history, and the link made every call read 17–19KB of contract and host adapter first. 19 of them differ from upstream only by the removed `disable-model-invocation` line. A skill that starts to need the contract leaves the list and links it again.

The contract and the shipped skills do not name the user's browser. The user's global instructions on each host already name `ego-browser`, and the Codex adapter keeps user-specific rules out of the plugin, so shipped text says to use the browser the user's or host's instructions name.

### Model invocation

Skills stay model-invocable on both hosts, and poteto-help is the one exception: its Claude frontmatter keeps `disable-model-invocation: true`, and its Codex `agents/openai.yaml` sets `allow_implicit_invocation: false`, so either host runs it only when named. Until 0.15.32-shared.3, 46 skills carried that Codex setting from the initial port, while poteto-help and the 13 skills added later did not, so Codex hid most skills from the model and offered poteto-help, the reverse of Claude Code. Removing those files puts their descriptions into a Codex session's context by default, about 10.7KB, as Claude Code already does. The `model-invocation` denylist rule matches both forms, and its allow list holds poteto-help's two files.

### Local additions

The `xagent` skill, its allowlist, and the pi guard have no upstream counterpart; `scripts/xagent-e2e.sh` is their behavioral test.

Replays in `create-verification-skill` and `maintain-verification-skill` are adapted from tester.army `e2e`'s verified replay cache: a replay is a test script written only after a passing check, it runs before any manual drive, and a stale replay is reported instead of letting an agent redo it. Keep them when syncing those skills.

`bin/transcripts.mjs` lists prior sessions for `recall`, `correct`, and `automate-me` instead of describing transcript paths in prose, and it enforces the shared runtime's cwd and time restriction before any content is read. Claude sessions come only from the project directory Claude Code derives from each requested cwd, and a session counts only if it recorded that cwd, because distinct paths can share a directory name and a session moved from another directory keeps its earlier cwd. Codex rollouts are opened only when modified inside the window, and only for their first `session_meta` record. The Claude directory rule was read from Claude Code 2.1.302 and checked against every existing project directory on the maintainer's machine; upstream's harness note (cursor/plugins#637) names only `/` and `.`, which misses paths with spaces, underscores or non-ASCII characters and those longer than 200 characters. `scripts/transcripts.test.mjs` covers both hosts with a temporary home.

### Refresh installations

After maintained-source changes, refresh the existing installations with `agy plugin install <source>`, `codex plugin add pstack-codex@personal` for this machine's existing Codex ID, and `claude plugin update pstack@pstack-local`. Do not flatten pstack skills into shared standalone names or restore retired paseo aliases.

## Upstream sync

`node scripts/check-upstream.mjs` reports whether upstream moved past the pin and which files changed; it reads through `gh api` only. Merge each changed file by its history in this fork, never by copying the upstream directory:

- A file this fork adapted: take upstream's intent and keep every adaptation this guide records; where upstream's wording is Cursor-specific, keep the fork's.
- A new upstream file: adapt it as earlier syncs did, with local frontmatter, the runtime-contract line, and the fork's host primitives. A new guidance skill that uses nothing in the contract goes in `STANDALONE` instead of taking the line.
- A file this fork never changed: apply the change, then check it against the decisions below. The 0.15.25 sync rewrote upstream's new fast-mode sentence in two otherwise untouched forensics playbooks.
- A file this fork deleted, such as `.cursor-plugin/plugin.json`, `make-bot-ui`, or the Benny pack: keep it deleted unless the change removes the reason recorded under [Not taken from upstream](#not-taken-from-upstream).

The [fork guards](./docs/ci.md#fork-guards) reject the denylisted Cursor primitives and require each local decision listed in `REQUIRED` in `scripts/check-fork.mjs`, by file and anchor sentence. A decision this guide records without such a rule is guarded only by reading, so read every change against the guide. When a sync changes a guarded decision on purpose, update its section here and its rule in the same commit. When `comparisonMayBeTruncated` is true, the file list is incomplete; sync through an intermediate upstream commit. Finish a sync by moving `UPSTREAM.json` and the first line of this guide to the new commit, adding a line to the sync log, recording each new or changed decision in its section, running the [verification](#verification) checks, and [refreshing the installations](#refresh-installations).

### Not taken from upstream

- **Cursor's model sheet and its rules.** The `pstack-models.mdc` role lines and slugs, the fall-back-to-default-slug rule, retired-role cleanup in setup, the fixed roster and panel fan-out, the fixed "Ten lanes on `<model>`" check in multi-phase-plan and check-plan, and a concrete perf-issue model. This fork resolves models through `config.json` with inherited defaults, forbids silent substitution, and sizes live lanes by risk.
- **Urgency-based fast mode.** Fast mode and priority service tiers cost more and stay off unless the user asks, which also holds on T3.
- **The Agent Plugins root manifest (#576).** Its `$schema` makes Codex load the package as an Agent Plugin, which truncates each injected skill to 8,000 bytes, and poteto-mode's `SKILL.md` is longer. The local root `plugin.json` stays the Antigravity manifest and carries no version, so upstream's version bumps stay out of it.
- **The generated Claude Code harness (#637, #705).** Its tree, `docs/harness/claude-code.md`, and the `~/.claude/rules/pstack-models.md` model rule translate Cursor names at run time, while this fork rewrites the shared skills in host-neutral wording, resolves models through `config.json`, and lists transcripts with `bin/transcripts.mjs`. Upstream's repository-root harness and docs checks (#637, #704) sit outside the tracked path; the fork guards check local links instead.
- **Cursor-only README and guide lines.** The Claude Code and Cursor install lines, the Custom Mode link, the built-in `/autopilot` note, the Cursor `/` menu note, the Cursor-only Benny note, and #806's auto-update note, since Claude Code reads the `pstack-local` directory marketplace in place.
- **#805's transcript timing in `worktree-audit.sh`.** The local script reads no transcripts, so it runs no `stat` or `date` on them.
- **statechart's `OutputFolder` model (#791).** The local output-folder check and copy fixes below cover the same ground.
- **`make-bot-ui` and the Benny automation pack.** Both drive Cursor platform features: make-bot-ui creates a Cursor webhook routine with `update_state`, takes its sender key through a Cursor secret request, and posts to `api2.cursor.sh`; Benny is two Cursor automations for Slack issue reports. The fork's earlier ports kept them as dormant prose with no platform behind them on Codex, Claude Code, or Antigravity, and every sync still had to re-adapt them, so 0.15.32-shared.5 removed both. Host features cover the same jobs where the user's plan offers them (checked 2026-10-25): Claude Code scheduled tasks, a research preview, take an API trigger with a per-task bearer token that a local page's server can POST to; Claude Tag, on Team and Enterprise, takes a Slack bug report to a draft PR; and the Claude Code GitHub Action can triage and fix on issue events. See the [scheduled tasks](https://code.claude.com/docs/en/routines.md), [Claude Tag](https://claude.com/docs/claude-tag/overview.md), and [GitHub Actions](https://code.claude.com/docs/en/github-actions.md) docs.

### Sync log

| Upstream | Synced | From | Pull request |
|---|---|---|---|
| 0.15.32 (`e73df471`, #791–#807) | 2026-10-24 | 0.15.30 (`4ec7ffa1`) | #25 |
| 0.15.30 (#776, #779 follow-ups) | 2026-10-22 | 0.15.25 (`99743e9c`) | #21, #22, #23 |
| 0.15.25 (#633, #634) | 2026-10-16 | 0.15.21 (`997ffc7f`) | #10 |
| 0.15.21 | 2026-10-13 | 0.15.15 (`df581122`) | #8 |
| 0.15.15 | 2026-10-13 | 0.15.9 (`e43c7ee2`) | #8 |
| 0.15.9 (0.15.6, #494–#496) | 2026-10-04 | 0.15.5 (`12d587df`) | #7 |
| 0.15.5 (#419, #422) | 2026-09-25 | 0.15.3 (`b42effe0`), the first adaptation | first published 2026-09-26 in `ea765cd` |

## Local decisions

The 0.15.3 base retains code-ready review rounds, exact SHA/method evidence, child ledgers, merge-prep CI checks, Shipping lane reuse rules, and append-only logging. Adaptations preserve real completion evidence, risk-sized lanes, current runtime model names, explicit authorization for merges and other external writes beyond a task's own branch and PR, and observed scheduling capabilities.

### Authorization

Pushes and PRs follow upstream, at the user's request on 2026-10-25 (0.15.32-shared.2). Opening a PR is invoked at the end of every other playbook and opens the PR ready unless the user or the repository's PR rules ask for a draft. A playbook commits, pushes the task's own branches, and updates the task's PRs, including review replies and resolved threads in Babysit and bugbot triage, without asking first; a user who keeps a task local overrides that. The shared runtime contract still requires authorization for merges, `--auto`, force-pushes to a branch another person or agent works on, deploys, publishing, remote messages outside the task's PRs, resource creation, and destructive cleanup, and forbids pushing the trunk directly. poteto-mode keeps upstream's always-pause line, with merges added. Babysit never merges, Shipping uses `--auto` only on request, and Autopilot-full merges only under the operator's explicit authorization. Replace a stuck agent only after its ownership is resolved. User or host instructions that require approval for remote writes still apply on top of pstack.

### Host-neutral wording

Where upstream names a Cursor primitive, the fork names the host capability, and the denylist keeps the Cursor form out:

- An optional native host goal and an observed, authorized host scheduler instead of `/goal`, `/loop 1h`, or `/loop until`.
- `<resolved trunk ref>` and the installed playbook instead of `origin/main`.
- Host collaboration tools instead of `Task` fields, and isolated host workers instead of Cursor cloud agents.
- The project's verification harness and actually available tools instead of `control-ui`, `control-cli`, and `deslop`.
- The selected state directory instead of the root agent's system-prompt store.
- `.agents/skills` and `~/.agents/skills` paths instead of `.cursor/skills`, and `poteto-agent.md` resolving poteto-mode from the Claude install record or the Codex plugin cache instead of `~/.cursor/plugins/`.
- Host-rendered charts and output instead of `/visualize`, and the host's entry points instead of Custom Modes.
- The local `check-plan.mjs` markers (its tests' fixtures use them) and the local `poteto-agent.md` frontmatter.

### Models and effort

Models come from `config.json`, where every role inherits the parent by default, instead of upstream's Cursor slug defaults. Poteto-mode's Subagents section keeps upstream's "Code delegates tier by difficulty" routing: each code playbook's delegate reads its role, the hardest changes read `hardest tasks`, prose and judgment read `judgment and prose`, and verification workers read `verification workers`. `how`, `why`, and `reflect` name their role keys, such as `how explorer` and `reflect judgment`, so a configured role is the one they read.

Effort moves per job within the role's model ("match effort to the job"): workers start from the resolved role and `reasoning_effort`, rise one step for the hardest work, and drop one step for judgment or two or more for routine work. The value goes only through each host's separate effort control (Codex `reasoning_effort`, the Claude Agent `effort` field, T3 `target.options`, `bin/xagent --effort`), and never changes a role's model, T3 target, or `xagent:<agent>` entry, so panels stay diverse. Native agent definitions own their effort: on Codex and Claude Code a worker's effort goes to a native agent type only when its definition sets none, so `reasoning_effort` mainly reaches `xagent:` workers, whose CLIs otherwise run at the user's interactive default.

### Cross-vendor panels

`verification workers` is a local role with no upstream line. Upstream runs orchestrate's verifier and show-me-your-work's handback review on a different model family than the work. On Codex or Claude Code another family needs an `xagent:` entry, so verification takes its own role instead of sharing `swarm workers` with fan-out workers, and each host can point it at the other vendor while swarms keep their own worker. A swarm's verify lanes, as in autopilot's swarm-verify, and the handback review read it too.

Shared `auxiliary_panel_members` names external members whose unresolved outcome is a reported gap rather than a blocker, so a supporting vendor's outage does not stop a review its primary members finished; upstream reaches the same availability by falling back within a family, which xagent entries never do. Shared `xagent_effort_caps` keeps effort within what each external CLI's model accepts: an unsupported level is a `DROPOUT`, never a quiet downgrade, so a shared `xhigh` would otherwise drop every seat of a CLI whose model stops at `high`, as agy's `gemini-3.8-flash` does. setup-pstack proposes a cross-vendor layout for multi-party steps when another vendor's CLI is signed in, because this fork's `inherit-parent` defaults stay one family where upstream's defaults pair two.

### orch frontier and Shipping

`orch frontier set` takes upstream's base-chain discovery through `gh` or `--forge origin` in place of the optional Graphite path, and keeps this fork's authoritative `--prs` list, which reads each PR's state and head SHA with `gh pr view` and so works from a detached worker worktree; `--prs` with `--forge origin` fails because Origin's list output carries no head SHA. It prefers a branch's open PR over its closed or merged history (#804), and recovery hints offer `--prs` only where it works, on GitHub.

Local fixes for defects in upstream's discovery, found in independent review: `gh` queries pin `--repo` to the GitHub origin and drop PRs whose head repository is another fork, so a same-named fork branch never gets the local SHA; every list passes `--limit 1000` and fails when the result may be truncated, since `gh pr list` returns 30 rows by default; trunk comes from `origin/HEAD`, else from whichever of `main` and `master` exists, remote refs first, and fails when both or neither exist instead of assuming `main`; and `ssh://git@github.com/` origins are accepted alongside HTTPS and scp-style ones, here and in `worktree-audit.sh`. Origin's list output has no head repository, so `--forge origin` cannot drop same-named fork PRs; prefer `gh` or `--prs` where forks exist. Its GitHub remote parsing is `skills/poteto-mode/scripts/github-remote.ts`, moved out of upstream's `watch-pr/github.ts` so `orch` and `watch-pr` share one parser.

Shipping reads and fixes the bottom PR's base before every merge, the first after a restart included, because a PR still targeting its merged parent merges into that branch. The multi-phase-plan skeleton makes its rebase items depend on the execution playbook, because Autopilot-stack owners never rebase. `worktree-audit.sh` keeps a no-fetch, read-only contract: `-b` names a local ref, the fallback is `origin/HEAD`, `origin/main`, then `origin/master`, and its PR query stays GitHub-only, because Origin's list output has no head repository and the audit must not match a same-named fork branch.

### orch store lock

The orch store lock carries a local fix for three races that upstream still has at `e5136d82`: a writer killed between the exclusive open and its pid write left an empty lock that only `--force` could pass, two writers that saw the same dead holder could both take the lock, and a release could unlink the lock a `--force` writer had just put in its place. `acquireLock` writes the pid to a private file and hard-links it into place, falling back to the exclusive open where hard links are unsupported. Every read-then-unlink of the lock, in a takeover or a release, runs behind a `.orch.lock.takeover` claim, and a takeover re-reads the holder before it unlinks. A writer that meets a live claim is refused with `is being released or replaced; retry`; a release that meets one retries every 10 ms, so `close` waits while a live claimant, even a stopped one, holds it. Each acquire also removes the private pid files and staged claims that a writer killed mid-claim leaves behind, judged by the pid in their names, which the kill-at-every-step test checks.

The fix and its multi-process race tests are adapted from michael-denyer/pstack-claude #219 (`eef8f7c6`) and #238 (`de804764`), MIT, Copyright (c) 2026 Michael Denyer, whose notice is in `LICENSE`. That fork's TLA+ model and its retry when a lock vanishes before its holder is read are not taken. The lock lives in `skills/poteto-mode/scripts/orch/lock.ts`, with `UserError` and `errorCode` in `orch/errors.ts`, because this fork replaced upstream's lock wholesale and `store.ts` was already past 1,000 lines; its race tests live in `orch/lock.test.ts`, sharing `orch/store.test-helper.ts` with `orch.test.ts`. The frontier code stays in `store.ts` even though it is large, so upstream's edits there still merge file by file.

### statechart

statechart takes upstream's scripts, the Pele and resvg renderer, its `Inputs` snapshot of each spec's `EXTENDS` and `INSTANCE` modules and each mapping's relative imports (which replaced an equivalent local fix and keeps that fix's regression test), and its process rules: rules name what the user sees and the code that changes it, each action condition cites its `file:line`, a replay drives only user or client entry points, and the hand-off says whether the agreed spec already lists each bug. The hand-off gives the rendered image instead of the PNG, to match the local render step. `create-formal-verification-skill` tells generated verify skills to read each TLA+ result with `$statechart`.

The scripts download nothing on their own: `findTlc` and `loadRenderer` install with mise or npm only when `STATECHART_INSTALL=1` is set, and otherwise exit 2 with the install command. The skill tells the agent to ask the user before setting it, and still renders each `.mmd` locally when the renderer is missing. Upstream's install tests run with `STATECHART_INSTALL=1`, and two local tests check that without it neither mise nor npm installs anything. `scripts/check.sh` runs the statechart script tests; those that need TLC skip without it.

Local fixes for defects found in review, each with a regression test that runs without TLC, all eight kept by the fork guards:

- The output folder check reads inside `tlc/` and its `fixed/` and `against/` folders: only each TLC run's config, output, and graph, named after the module and the rule, the rules module, and the regions proofs count as the command's own, so a user's file or folder there makes the run refuse the folder instead of replacing it.
- `parseValue` decodes the TLA+ string escapes `\n`, `\t`, `\r`, and `\f`, so a string with a newline no longer reads as the letter `n` and collapses onto another state.
- Where the output folder cannot take a rename, upstream claims an empty folder and copies into it exclusively, but a failed copy deleted the whole claimed folder with any file another run or the user put there. A failed copy removes only what it made, and only while the path still names that same file or folder, and removes the claimed folder only while it is empty. The test uses a preload that, like upstream's model of a FUSE mount, fails renames of a folder that has files.
- A `PROPERTY` that the second model's config skips gets the same unchecked warning as an `INVARIANT`, and only an `INVARIANT` counts as checking an `INVARIANT`, because a state predicate under `PROPERTY` holds only in the initial states.
- With `--against`, the input snapshot also covers that folder's list of specs and configs and every config in that same list, and `listedBreaks()` reads them from the snapshot, because the stories quote which configs list each bug.
- The mapping scaffold in `spec-text.mjs` splits definitions at the module's least definition indentation, so a module whose definitions are indented still gets its actions, and a `LET` definition stays inside its action.
- TLC runs inside the input snapshot, so `findTlc` resolves a relative `JAVA` or `TLA2TOOLS` to an absolute path, and keeps the bare `java` fallback.
- A map edited and restored before the final content check would publish labels that TLC's results never matched, so the charts, in `statechart.mjs` and each `tlc-to-chart.mjs` run through `--snapshot`, load the map and the files it imports from the snapshot with a `module.registerHooks` load hook, which finds each copy by the module's real path because Node loads a module from that path, so an input named through a symlink, such as `/tmp` on macOS, is covered too. Node still resolves each module from its own path, so a package that the map imports by name, and `package.json`, apply as before; importing the copies directly would break both.

Upstream's own fix for a second-model config that skips a rule came with #776, and a local test without TLC checks that such a rule's states stay wrong under `--fixed`.

### Other skills

- poteto-help uses the Codex and Claude entry points, reads the shared `~/.config/pstack/config.json` policy, links to this checkout, and does not claim Cursor Custom Modes, `/loop`, Cursor model paths, or Cursor delegation tools.
- `sharpen` keeps upstream's prompt: it hands back the rewritten prompt and does not do the task.
- `ketchup` lists every waiting call with its link, pick, evidence, and risk and never cuts items to meet a word count; ketchup catch-ups close autopilot ticks and replies.
- `ketchup-video` is model-invocable, with its video embedded when the host can show it and otherwise linked as a local file.
- `reflect` never edits a skill inside an installed plugin and copies it to `.agents/skills/<skill>/` or `~/.agents/skills/<skill>/` with the discovery link.
- `create-formal-verification-skill` writes the generated verify skill in `.agents/skills/` with the discovery link, `maintain-formal-verification-skill` looks in both `.agents/skills/` and `.claude/skills/`, and setup-pstack mentions the create skill once, in the same mention-only form as its verification step.
- watch-pr takes the fork-head fix in stack discovery (#801), so the local merge-gates fixture has `isCrossRepository`, and the deadline cap on polling sleeps (#802), so the local `--once` test expects a native run past its deadline to sleep zero seconds.

## Antigravity integration

Antigravity imports this same checkout through its native root `plugin.json` with `agy plugin install <source>`. Read its installed version with `agy plugin list`; updating the Claude/Codex manifests does not update the Antigravity installation. Native installation processes the existing 58 skills and agent templates without adding hooks or MCP servers. Host copies are generated by each normal installer, never edited directly.

The Antigravity runtime adapter reads the same `~/.config/pstack/config.json` through `show --host antigravity`, using common policy only. Codex and Claude-specific model overrides are excluded. Antigravity config writes are not enabled by this integration; missing config remains read-only. Actual host tool/model capabilities and authorization still govern execution. Read `references/antigravity-runtime.md` before running workflows there.

## T3 Code overlay

T3 Code runs Codex or Claude Code underneath, so it is an overlay on the selected host adapter, not a fourth host. `references/t3-runtime.md` applies only when the session exposes T3's `orchestrator_capabilities` and `delegate_task` tools; an inherited `T3CODE_CLI_PATH` alone does not activate it. It replaces model resolution, delegation, scheduling, and PR watching with `delegate_task`, `task_status`, `schedule_task`, and `watch_pull_request`. Skills, playbooks, authorization, evidence rules, and `bin/xagent` stay shared, so agents T3 does not list, such as Gemini, and every `required_panel_members` entry still run through xagent. T3's own instructions prefer native subagents for same-provider work and send explicitly T3-owned child tasks through `delegate_task`; the overlay states that every pstack worker is such a task, which keeps it consistent with the shared runtime's rule that host instructions take precedence.

**Policy view.** `show --host t3` returns common policy plus an optional `hosts.t3` section and never reads `hosts.codex` or `hosts.claude`. That section also accepts T3 targets `<providerInstanceId>/<modelId>`, validated by `bin/config.mjs`; files without it remain valid, and older helpers ignore it. A T3 change therefore never alters native Codex or Claude sessions, and their overrides never reach T3; `scripts/config.test.mjs` covers that isolation. `hosts.t3`, not a native agent definition, owns a T3 child's effort.

**Resolution.** `config.mjs resolve --host t3` previews one role or panel read-only. `bin/t3-targets.mjs` maps exact targets and effort against the current thread's capability catalog, preserves xagent entries and repeated/required panel members, and rejects unavailable explicit targets without model substitution. Missing effort controls remain visible warnings with no claim of delivery. The catalog does not assume particular vendors are absent. T3 0.1.2 lists each model option as `{id, values, default}` instead of 0.1.0's `{type: "select", options}`; the resolver reads both forms and never treats a boolean option as an effort control. `orchestrator_capabilities` returns a short list with a per-provider `omittedModels` count and a `search` input, so a preview names a target that the list omits and asks for a search, `resolve` takes a repeated `--catalog` that adds a search result from the same thread to the default listing, and `@latest` fails on a provider whose list is partial, since it cannot see every release; Codex, Claude, Muse, and Grok list every current model. Version following requires the current server-filtered catalog; older T3 builds affected by hidden-model catalog omissions must be upgraded or use an explicitly approved exact target.

**Inherited roles.** An inherited T3 role keeps the parent's complete model selection. On T3 0.1.0 the resolver omits `target` and reports requested effort as unsent, because that T3 replaced supplied options and did not expose the parent's complete selection in its catalog. From T3 0.1.1, `inheritedOptions` is present and options sent for the parent's own provider and model override only the values they name, so an inherited role with a requested effort that its parent model offers sends that effort alone and keeps every other parent option; a 0.1.0 catalog keeps the earlier behavior. Explicit targets retain their supported effort mapping.

**Candidates and family selectors.** A candidate role chooses one provider, preferring the current parent or the first configured candidate; an explicit `--provider` can select another configured candidate. Failures never walk the list. `@latest` family selection uses canonical numeric releases in the task's live catalog, freezes concrete IDs for that task, and preserves exact pins. It adds no second registry and does not change xagent defaults. Each new delegate is classified by its own phase and difficulty; ordinary implementation returns to its ordinary role after a hard design. The optional `hardest architect runners` panel supports Fable/Astra designs without rewriting other panels. Native roles and their inheritance remain separate. Both installed helpers must be upgraded before storing the candidate-object shape, and existing sessions must reload the new runtime. [Routing examples](./docs/t3-model-routing.md) cover the contract and compatibility boundary.

**Cross-vendor.** `verification workers` requires `--checked` on T3: the parent-provider default would choose the parent's own family, so the helper picks the candidate whose model family differs from the checked work's, read from model IDs, because one T3 provider can route Claude, GPT, Gemini, and Grok models. The preview marks auxiliary panel seats, so the panel rule needs no second lookup. setup-pstack proposes a T3 cross-vendor layout with T3 seats for vendors the catalog lists and xagent only for the rest.

**Dispatch and evidence.** T3 children use application-owned `isolation: "worktree"`; briefs and acceptance evidence distinguish the parent commit from uncommitted or separately prepared input. A child's non-null `pendingApproval` is not completion and grants no approval authority, and `task_status`'s stored `options` must hold what the target sent. Shipping treats a queued `WAITING`/`merge-queue` as a wait and stops only at `COMPLETE` or a blocker, and the no-polling watch-pr rule covers Babysit and Shipping. `bin/watch-pr.mjs` has a local `--once` flag for T3 babysit rounds: it classifies once, never sleeps or retries, and ends a wait as `TIMEOUT`; `watch-pr/once.test.ts` covers it, and for it the upstream watch-pr tests only gain the `once: false` default.

**Sources and checks.** chhoumann/t3-pstack, a T3 port of the pstack-claude lineage, informed the tool mapping, and its declared adaptation checks and creedants/pstack-t3's catalog-backed role resolution informed these boundaries; their code, model defaults, automatic fallback, separate configuration, and standing coordinators are not imported. `scripts/t3-targets.test.mjs` and the fork guards' required T3 anchors protect these boundaries, covering both catalog forms, and [T3 live verification](./docs/t3-verification.md) separates selection, task metadata, provider observations, and artifact acceptance. A live T3 run under it is still owed.

## watch-pr merge gates

`watch-pr` fails closed on the merge gates GitHub enforces, a local port of michael-denyer/pstack-claude (MIT) [#95](https://github.com/michael-denyer/pstack-claude/pull/95), [#223](https://github.com/michael-denyer/pstack-claude/pull/223) and [#245](https://github.com/michael-denyer/pstack-claude/pull/245), with [#124](https://github.com/michael-denyer/pstack-claude/pull/124)'s `satisfies never` check on the merge-gate hint. `LICENSE` carries that project's copyright line. Upstream reported `READY` for PRs GitHub would not merge: it gated only closed, draft and `CHANGES_REQUESTED` PRs, accepted `BLOCKED` beside a passing rollup, and passed unknown mergeability. `READY` now requires `mergeable: MERGEABLE` and a settled merge state. `mergeStateStatus: BEHIND` stops at the `behind-base` merge gate without waiting for checks, since updating restarts them. `reviewDecision: REVIEW_REQUIRED` stops at `review-required`, and `BLOCKED` beside a passing rollup at `merge-blocked`; both wait for pending checks first, as `draft-pr` does. All three exit 6 in single, `--stack` and `--queued-stack` mode. Unknown mergeability is a `mergeability-unknown` wait, so `--once` ends it as `TIMEOUT`. PR facts come from one GraphQL query that reads the base branch's current commit, `baseRef.target.oid`, instead of `gh pr view`, whose `baseRefOid` is the commit the PR recorded. Each open snapshot reads the facts again after its checks and retries as `snapshot-changed` when one moved, except mergeability GitHub computed between the reads. An open PR without a head or base commit fails closed, and `READY`'s proof names both. Babysit treats `review-required` as the owner-approval wait, `behind-base` as a rebase to report and `merge-blocked` as a rule to name. Shipping does step 4's move for `behind-base` and stops at the other two. `watch-pr/merge-gates.test.ts` covers each gate and failed on the previous source; upstream's watch-pr tests change only where they pinned one facts read per snapshot, the `gh pr view` response, or the waiting decision's `pending` field. Keep these edits when a sync touches watch-pr.

Two pstack-claude changes are not taken. Its shared `WatchDeadline` (#124) changes exit codes at the deadline edge and is independent of these gates. Its `ci-none` verdict ([#153](https://github.com/michael-denyer/pstack-claude/pull/153)) is not ported, so a PR in a repository with no checks configured stays fail-closed: `gh pr checks` exits 1 with "no checks reported", the head has no rollup, and the watcher ends at `BLOCKER status-query` (exit 7, `checks-unavailable`) at once under `--once` or after `--max-query-errors` reads. It is never `READY`, and a person confirms such a PR.

## Verification

Run the offline runtime checks for configuration, guard, receipt, process and host-acceptance behavior:

```sh
bash scripts/check.sh runtime
```

For all CI checks, including strict TypeScript checks, Bun tests and reproducible bundle verification, follow [Run the CI checks locally](./docs/ci.md). The same entrypoint runs in GitHub Actions without vendor credentials.

The CLI tests use real Git checkouts and subprocesses with vendor stand-ins, including staged/committed read-only violations, misleading verdicts, timeout and cancellation. Vendor acceptance pins the fixture's test contents and checks the worker's successful test receipt against its final source before independently rerunning it. The shared verification runner gives each command a fresh Python bytecode-cache prefix and disables cache writes; `-B` alone can still load stale bytecode after an equal-size edit in the same second. A worker receipt is not sufficient without that independent run. Importing the test, rewriting it, or reusing a receipt from older code cannot satisfy the full acceptance gate.

Run `scripts/xagent-e2e.sh` after changing `bin/xagent*` or upgrading an agent CLI; it calls every vendor. Run `python3 scripts/pstack-host-e2e.py <new-run-dir>` after changing cross-agent routing: actual Claude and Codex hosts run swarm, then interrogate, through their current shared policy on synthetic fixtures. The host harness accepts a run only on evidence the host cannot write, such as xagent receipts, the host's own logs, snapshots the snapshot tool printed, and its own independent tests, because the host's success report is the thing under test. Its acceptance rules live in the script's module docstring, beside the code and tests that enforce them, so change them there. Neither harness changes preferences. Both bound the outer host process with `timeout` and a kill-after limit, and a verification timeout is a failed check with exit code 124.

The runtime checks start with `scripts/check-fork.mjs`, which validates the manifests, all SKILL.md and agent frontmatter, each workflow skill's link to the shared runtime contract and its absence from the `STANDALONE` skills, local links, a denylist of the Cursor-only wording this guide replaces, and the files and anchor sentences of the local decisions it requires; see [Fork guards](./docs/ci.md#fork-guards). Use a fresh Codex app-server skills/list and Claude `plugin details` to verify inventory; a static validator alone is not a discovery or behavioral test.

Rebuild the `orch` and `watch-pr` bundles with `python3 scripts/build-runtime.py` when their sources, dependencies or builder change. Use the Bun version in `.bun-version` and locked development dependencies. `python3 scripts/build-runtime.py --check` compares a temporary build with the working tree without writing artifacts. Node runtime helpers never download dependencies.

See the task's shared-installation report for actual dated commands/results and any remaining gaps. No overnight, real PR queue, remote runner, or Slack workflow is implied by local package validation.
