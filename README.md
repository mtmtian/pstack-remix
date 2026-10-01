# pstack for Codex and Claude Code

English | [简体中文](./README.zh-CN.md)

One source tree, one configuration, two native host entry points. This independent local adaptation tracks Lauren Tan's MIT-licensed upstream pstack 0.15.5 at [`12d587df`](https://github.com/cursor/plugins/tree/12d587dfb20741cafc376c42c696c5f6e2a64487/pstack). It is not maintained by Lauren Tan, Cursor, OpenAI, or Anthropic.

The 48 skills, 23 playbooks, engineering principles, agent prompts, and Node helpers are shared. Only the plugin manifests and two short runtime adapters differ. Codex retains its installed `pstack-codex` name; Claude Code uses `pstack` from the same directory.

## Install and use

Clone the repository once per machine, then register that same checkout with each host. See [setup and updates](./docs/guide/01-setup.md) for prerequisites and existing installations.

```sh
git clone https://github.com/mtmtian/pstack-remix.git "$HOME/plugins/pstack-codex"
cd "$HOME/plugins/pstack-codex"
codex plugin marketplace add "$PWD"
codex plugin add pstack-codex@pstack-local
claude plugin marketplace add "$PWD"
claude plugin install pstack@pstack-local --scope user
```

Marketplace registration is needed only once per host. Host caches are generated installation copies; edit only the checkout. Machines already using `pstack-codex@personal` can retain that registration if it points to the same checkout; do not install a duplicate under a second marketplace.

- Codex entry: `$pstack-codex:poteto-mode`.
- Claude Code entry: `/pstack:poteto-mode`.
- Optional setup: `$pstack-codex:setup-pstack` or `/pstack:setup-pstack`.

Preferences are shared in `~/.config/pstack/config.json`. Roles inherit the main conversation unless configured; workers receive the resolved policy and do not need setup. Concrete model choices are host-scoped so one vendor's model ID never leaks into another host. Shared reasoning and panel-size preferences apply to both when the actual runtime supports them. See [the runtime contract](./references/runtime.md).

Examples below use `$skill` as a short reference to the bundled skill; in Claude Code invoke `/pstack:skill` or read its file through the host's skill interface.

## usage

use [`$poteto-mode`](./skills/poteto-mode/SKILL.md) at the start of a task. it reads your request, picks from a set of playbooks, and runs the other skills as the steps need them.

### just use [`$poteto-mode`](./skills/poteto-mode/SKILL.md)

This skill is the main shortcut for rigorous engineering work. It comes with twenty-three playbooks.

```
$poteto-mode this pr has a subtle bug where the scroll drifts every 750ms even when idle. repro
first, then fix and verify.
```

```
$poteto-mode i'm stepping away. prepare and verify the stack in an isolated worktree. stop at
the first unresolved check and leave an auditable decision log. I will authorize remote landing separately.
```

<details>
<summary>the twenty-three playbooks</summary>

| playbook | for |
|---|---|
| [investigation](./skills/poteto-mode/playbooks/investigation.md) | a read-only question. how does x work, why was y built this way, are we sure. |
| [bug fix](./skills/poteto-mode/playbooks/bug-fix.md) | reproduce a defect, root-cause it, and fix with runtime evidence. |
| [perf](./skills/poteto-mode/playbooks/perf-issue.md) | trace a measured slowness and improve it against a baseline. |
| [hillclimb](./skills/poteto-mode/playbooks/hillclimb.md) | sustained, scientific improvement of one metric against a target, looping hypotheses with before/after measurement and one commit per accepted win. |
| [runtime forensics](./skills/poteto-mode/playbooks/runtime-forensics.md) | diagnose a live symptom (leak, idle-cpu spin, glitch) from instrumentation. |
| [trace forensics](./skills/poteto-mode/playbooks/trace-forensics.md) | diagnose a captured profiling artifact (cpuprofile, trace, spindump, heap snapshot). |
| [feature](./skills/poteto-mode/playbooks/feature.md) | new or changed behavior, built from a named data shape. |
| [refactoring](./skills/poteto-mode/playbooks/refactoring.md) | a behavior-preserving change to structure or shape. |
| [prototype](./skills/poteto-mode/playbooks/prototype.md) | a throwaway sketch to make a design or behavioral decision cheaply, or to settle an empirical fork by observing it. |
| [visual parity](./skills/poteto-mode/playbooks/visual-parity.md) | pixel-exact ui equivalence between two implementations. |
| [authoring a skill](./skills/poteto-mode/playbooks/authoring-a-skill.md) | writing or editing a SKILL.md. |
| [eval](./skills/poteto-mode/playbooks/eval.md) | test how a skill or prompt change affects agent behavior, blinded. |
| [babysit](./skills/poteto-mode/playbooks/babysit.md) | drive a pr or a stack to merge-ready: conflicts, review threads, ci. |
| [shipping](./skills/poteto-mode/playbooks/shipping.md) | independently verify a green stack, then prepare or land the contiguous verified run bottom-up when an authorized forge tool is available. |
| [autonomous run](./skills/poteto-mode/playbooks/autonomous-run.md) | drive a long task to completion without stopping. |
| [orchestrate](./skills/poteto-mode/playbooks/orchestrate.md) | a standing project handed to one coordinator chat: multi-day, many stacked prs, fleets of subagents. |
| [autopilot-full](./skills/poteto-mode/playbooks/autopilot-full.md) | run independent PRs through verification and, only with authorized remote access, merge them with one owner per PR and root verification of every code-ready or patch-changing round. |
| [autopilot-stack](./skills/poteto-mode/playbooks/autopilot-stack.md) | build and verify one linear base-branch stack for the operator to review and land. |
| [session pickup](./skills/poteto-mode/playbooks/session-pickup.md) | resume or take over a prior agent's in-flight work. |
| [pause safely](./skills/poteto-mode/playbooks/pause-safely.md) | suspend in-flight work cleanly so it can be resumed later. |
| [multi-phase plan](./skills/poteto-mode/playbooks/multi-phase-plan.md) | work that spans phases or stacked PRs. |
| [worktree cleanup](./skills/poteto-mode/playbooks/worktree-cleanup.md) | reclaim disk by pruning merged or abandoned worktrees and stale ios simulators, safety-gated. |
| [opening a pr](./skills/poteto-mode/playbooks/opening-a-pr.md) | prepare a ready PR from small ordered commits with a conventional commits title and a briefing-style body when a PR is requested and authorized. |

</details>



when invoked it:

1. matches your task to a [playbook](./skills/poteto-mode/playbooks/) and opens a todo list whose first items are its steps, copied in verbatim.
2. routes to the other skills as the steps fire.
3. writes unslopped replies framed for the consumer and the maintainer.

the full rules and playbooks live in [`skills/poteto-mode/SKILL.md`](./skills/poteto-mode/SKILL.md).

[`$poteto-mode`](./skills/poteto-mode/SKILL.md) is also a sticky conversation instruction: once entered it stays on across turns, applying itself when a playbook matches or the task needs rigor and staying out of the way otherwise. Opt out any time by saying so.

For a long finite task, explicitly start the host's native goal with `/goal`. A goal drives work toward a finish condition; its continuation and completion behavior comes from the selected host adapter. It is not a timer and requires an explicit request. Recurring or scheduled work uses an available automation or scheduling interface separately. pstack does not install a timer or claim that a goal will wake itself on a schedule.

## skills

[`$poteto-mode`](./skills/poteto-mode/SKILL.md) runs most of these for you when a step needs them (`how`, `why`, `architect`, `arena`, `swarm`, `interrogate`, `unslop`, `no-comments`, `technical-writing`, `tdd`, and the principles). the table below is for when you want one directly:

```
$how do we cancel runs? do we have an n+1 when we look up every run to cancel?
```

```
$interrogate review this pr.
```

<details>
<summary>all skills</summary>

| skill | use it when |
|---|---|
| [`$poteto-mode`](./skills/poteto-mode/SKILL.md) | default entry point for any non-trivial task. |
| [`$how`](./skills/how/SKILL.md) | you want a walkthrough of how a subsystem works. |
| [`$why`](./skills/why/SKILL.md) | you want to know why something was built this way. discovers available MCPs at run time and queries each evidence category in parallel (source control, issue tracker, long-form docs, real-time chat, infra observability, error tracking, analytics warehouse). |
| [`$recall`](./skills/recall/SKILL.md) | you're starting or resuming work and want your recent context on a topic rebuilt from your own chat history and the shared record, handed back as a tight current-state brief. |
| [`$blast-radius`](./skills/blast-radius/SKILL.md) | you have a small-looking change and want to know what else it could break, with the one fact it's safe because of proven by running code, not asserted. |
| [`$architect`](./skills/architect/SKILL.md) | you're about to write code that crosses a function boundary and want the caller's usage, types, and module shape settled first. |
| [`$arena`](./skills/arena/SKILL.md) | you want N parallel attempts at the same thing, then to grab the best parts of each. |
| [`$swarm`](./skills/swarm/SKILL.md) | you want N parallel workers across different slices or races, then one aggregated report. |
| [`$interrogate`](./skills/interrogate/SKILL.md) | you have a diff and want several different models to try to break it, including a strict code-quality lens. |
| [`$automate-me`](./skills/automate-me/SKILL.md) | you want your own `-mode` skill, drafted from how you've actually worked. |
| [`$make-bot-ui`](./skills/make-bot-ui/SKILL.md) | you want the optional webhook UI workflow; bot credentials, sender keys, and network exposure remain host-dependent and are not enabled by default. |
| [`$setup-pstack`](./skills/setup-pstack/SKILL.md) | you want to pick which models pstack uses per role. detects your models and writes a config rule. |
| [`$reflect`](./skills/reflect/SKILL.md) | a long task landed and you want the recipe captured as a skill edit. |
| [`$teach`](./skills/teach/SKILL.md) | you want to actually understand a change or subsystem, not just have it summarized. runs how + why and weaves one plain explanation, built up diagram by diagram. |
| [`$tdd`](./skills/tdd/SKILL.md) | you're fixing a bug and there's a cheap local test path. write the failing test first, then the fix. |
| [`$no-comments`](./skills/no-comments/SKILL.md) | strip comments before review; spawns Comment Sicko, fixes accepted findings, offers encodings for claimed constraints. |
| [`typescript-best-practices`](./skills/typescript-best-practices/SKILL.md) | you're reading or editing TypeScript. It grounds the type-system-discipline principle in syntax and loads through the host workflow. |
| [`$figure-it-out`](./skills/figure-it-out/SKILL.md) | no bundled playbook fits. designs a rigorous, auditable playbook for the task. |
| [`$show-me-your-work`](./skills/show-me-your-work/SKILL.md) | you want a reviewable decision trail. logs decisions to a tsv you can commit. |
| [`$create-verification-skill`](./skills/create-verification-skill/SKILL.md) | your project has no scripted way to prove app behavior. generates a project-local verify skill with a feature map, for any language or platform. |
| [`$maintain-verification-skill`](./skills/maintain-verification-skill/SKILL.md) | your verify skill's feature map has drifted from the app. source wave + one live pass, at most one PR of proven corrections. |
| [`$unslop`](./skills/unslop/SKILL.md) | you're cleaning up writing. removes AI tells. |
| [`$bro`](./skills/bro/SKILL.md) | you want the last message restated in plain human language, no jargon. |
| [`$technical-writing`](./skills/technical-writing/SKILL.md) | layered doc standard (Diátaxis + Google developer style + STE + Global English) for docs, RFCs, readmes, PR descriptions, commit messages. |

</details>



### examples

Most users type [`$poteto-mode`](./skills/poteto-mode/SKILL.md) at the start of a task and let it route to a playbook. The other skills fire as the steps need them, and any skill can be invoked directly.


<details>
<summary>all the examples</summary>

```
bug fix:           $poteto-mode this pr has a subtle bug where the scroll drifts every 750ms even
                   when idle. repro first, then fix and verify.
perf:              $poteto-mode a big list takes a second or two to load even though we virtualize.
                   run a cpu trace and tell me why.
feature:           $poteto-mode build a small feature behind a feature flag. verify it really works.
prototype:         $poteto-mode build two prototypes of the markdown renderer so we can compare.
                   spawn an agent for each.
multi-phase:       $poteto-mode open source these skills as a plugin. nothing internal leaks, work
                   in a temp dir, show me the dependency graph first.
long finite run:   $poteto-mode i'm stepping away. prepare and verify the stack in an isolated
                   worktree. stop at the first unresolved check and leave an auditable log.
babysit:           $poteto-mode check on pr 123. anything outstanding?
visual parity:     $poteto-mode the row spacing is too tall when this flag is on. the second image
                   is correct. repro and fix until it matches.
figure it out:     $poteto-mode i'm stepping away. migrate every caller from the synchronous store
                   to the new async one, keeping behavior identical. i want to trust it was done
                   right when i'm back.
how:               $how do we cancel runs? do we have an n+1 when we look up every run to cancel?
why:               $why is this feature flag not on yet?
architect:         design this instrumentation to be high signal with no false positives. $architect
                   this first.
arena:             $arena take my prompt to the arena verbatim. i want to compare their proposals
                   with yours.
swarm:             $swarm check every package under packages/ against its check.sh. one worker per
                   package. one report.
interrogate:       $interrogate review this pr.
tdd:               $tdd implement
unslop:            can we unslop and tighten the new changes?
reflect:           $reflect that took too long. capture what we learned so the next run doesn't
                   repeat it.
show-me-your-work: $show-me-your-work keep a decision trail i can review when i'm back.
automate-me:       $automate-me
```

</details>

## Shared agent prompts

The shared [poteto-agent](./agents/poteto-agent.md) and [comment-sicko](./agents/comment-sicko.md) files are native Claude Code agent definitions. Codex passes their bodies to supported collaboration roles instead of inventing custom agent types. Both read the same runtime and skills. Comment Sicko has read-only tools in Claude and requires a matching read-only role/scope in Codex.

## principles

twenty-three short skills, one principle each. `poteto-mode` indexes them inline and reads that index at task start. the standalone files are there so other skills can reference a principle by name, and so the index can point at the full rule for each.

<details>
<summary>all twenty-three principles</summary>

| principle | group | rule |
|---|---|---|
| [laziness-protocol](./skills/principle-laziness-protocol/SKILL.md) | core | Bias toward deletion and the smallest change that solves the problem. |
| [foundational-thinking](./skills/principle-foundational-thinking/SKILL.md) | core | Apply before writing logic: choosing core types and data structures, sequencing scaffold-vs-feature work, asking what concurrent actors share. Get the data structures right so downstream code becomes obvious. |
| [redesign-from-first-principles](./skills/principle-redesign-from-first-principles/SKILL.md) | core | Redesign as if the requirement had been a foundational assumption from day one, instead of bolting it on. |
| [attack-the-premise](./skills/principle-attack-the-premise/SKILL.md) | core | Apply when two or more fixes that share one premise have failed the same gate. Take a census of which actors hold the imbalance before the next fix, then question the premise instead of writing another fix that assumes it. |
| [subtract-before-you-add](./skills/principle-subtract-before-you-add/SKILL.md) | core | Remove dead weight, redundant validators, and stub references first, then build on the simpler base. |
| [minimize-reader-load](./skills/principle-minimize-reader-load/SKILL.md) | core | Count layers between question and answer, and hidden state in the reader's head; collapse one-caller wrappers and shrink mutable scope. |
| [outcome-oriented-execution](./skills/principle-outcome-oriented-execution/SKILL.md) | core | Apply during planned rewrites and migrations with explicit phase boundaries. Converge on the target architecture; don't preserve smooth intermediate states with throwaway compatibility code. |
| [experience-first](./skills/principle-experience-first/SKILL.md) | core | Choose user delight over implementation convenience; ship fewer polished features over more rough ones. |
| [exhaust-the-design-space](./skills/principle-exhaust-the-design-space/SKILL.md) | core | Build 2-3 competing prototypes and compare side by side before committing. |
| [build-the-lever](./skills/principle-build-the-lever/SKILL.md) | core | Apply to any non-trivial work, not just bulk work: edits, migrations, analyses, checks. Build the tool that does it or proves it (codemod, script, generator, or a skill your subagents follow) instead of working by hand. The tool is the artifact a reviewer can rerun. |
| [model-the-domain](./skills/principle-model-the-domain/SKILL.md) | architecture | Encode the domain in a structure instead of scattered conditionals. |
| [boundary-discipline](./skills/principle-boundary-discipline/SKILL.md) | architecture | Concentrate guards at system boundaries (CLI, config, network, external APIs); trust internal types and keep business logic in pure functions. |
| [type-system-discipline](./skills/principle-type-system-discipline/SKILL.md) | architecture | Make illegal states unrepresentable, brand semantic primitives, parse external data at boundaries, refuse to lie to the compiler, exhaust variants, derive from authoritative schemas. |
| [make-operations-idempotent](./skills/principle-make-operations-idempotent/SKILL.md) | architecture | Converge to the same end state regardless of partial prior runs. |
| [migrate-callers-then-delete-legacy-apis](./skills/principle-migrate-callers-then-delete-legacy-apis/SKILL.md) | architecture | Migrate callers and delete the old API in the same wave instead of preserving compatibility layers. |
| [separate-before-serializing-shared-state](./skills/principle-separate-before-serializing-shared-state/SKILL.md) | architecture | Eliminate the sharing first; serialize structurally only when one shared writer is a real invariant. |
| [prove-it-works](./skills/principle-prove-it-works/SKILL.md) | verification | Apply after completing a task, before declaring done. Verify against the real artifact (run the feature, read the actual value, inspect the diff), not a proxy, self-report, or 'it compiles.'. |
| [fix-root-causes](./skills/principle-fix-root-causes/SKILL.md) | verification | Trace each symptom to its root cause and fix it there; reproduce first, ask why until you reach it, resist nil-check guards that silence crashes. |
| [sequence-verifiable-units](./skills/principle-sequence-verifiable-units/SKILL.md) | verification | Apply to multi-step work (sweeps, migrations, runs of similar edits) and to how you stack commits and PRs. Break work into small units that each end in a verifiable state, check each before the next, and order delivery so the sequence proves itself to a reviewer. |
| [test-behavior-not-implementation](./skills/principle-test-behavior-not-implementation/SKILL.md) | verification | Apply when you write, change, or keep a test. Call the code the way its users do and assert the result they observe against a literal expected value. If the test would still pass when every imported function returns undefined, rewrite the assertion or delete the test. |
| [guard-the-context-window](./skills/principle-guard-the-context-window/SKILL.md) | delegation | Route bulk to subagents; keep summaries in the main thread, not raw payloads. |
| [never-block-on-the-human](./skills/principle-never-block-on-the-human/SKILL.md) | delegation | Proceed, present the result, let the human course-correct after the fact; reserve confirmation for irreversible actions. |
| [encode-lessons-in-structure](./skills/principle-encode-lessons-in-structure/SKILL.md) | meta | Encode the rule as a lint, metadata flag, runtime check, or script instead of more text. |

</details>

## Host adapters

[Shared runtime](./references/runtime.md) owns configuration, scope, evidence, and shared skill discovery. [Codex](./references/codex-runtime.md) and [Claude Code](./references/claude-runtime.md) define their native delegation, goal, and scheduling interfaces. Do not turn one host's tool names into instructions for the other.

Upstream Cursor control helpers are replaced by available project harnesses and host tools. External writes retain the user's authorization boundaries. Installing this package does not create a goal, timer, bot, or webhook.

## make it yours

`poteto-mode` encodes one opinionated engineering style. Your project may want different defaults.

type [`$automate-me`](./skills/automate-me/SKILL.md). it mines your recent transcripts, drafts a `<your-name>-mode` skill from how you've actually worked, and routes through pstack underneath. you keep pstack as the base and end up with your own routing skill alongside `poteto-mode`.

Models are configurable through [setup-pstack](./skills/setup-pstack/SKILL.md), which reads and updates the single shared JSON file. Host-specific overrides preserve existing choices. Defaults need no setup.

## Keeping up with upstream

Run [the CI checks locally](./docs/ci.md) with `bash scripts/check.sh` after installing the locked build dependencies. GitHub Actions checks the minimum runtime versions, macOS behavior, TypeScript, and distributed bundle freshness on every PR.

Run `node <plugin-root>/scripts/check-upstream.mjs`. The read-only report compares the pinned `UPSTREAM.json` commit with the latest pstack change. Review the diff once in this shared tree, preserve both host adapters, run `node --test scripts/config.test.mjs`, validate/discover both plugins, then refresh both installations per the [setup guide](./docs/guide/01-setup.md). Do not overwrite this adaptation with the upstream Cursor directory.

## automations

pstack also ships a dormant [Benny automation pack](./automations/benny/). Benny is a complete on-demand configuration package for issue triage and UI evidence. It has not been enabled with remote Slack access or a recurring schedule. Its files are not registered as slash skills. Configure it only through the documented local automation interface after checking the available host connectors and authorization.

## license

MIT
