---
name: poteto-help
description: Helps users understand pstack setup, poteto-mode, and which skill or playbook fits a task. Invoke it with a question.
disable-model-invocation: true
---

# Poteto help

Use this skill when the user asks how pstack works, where to start, or which skill fits. Answer from the linked files, give a prompt they can send, and link the source file. A help question asks for guidance; do not start the underlying work. A request that asks you to do the work, such as "use pstack to fix this bug," is a task: read [`poteto-mode`](../poteto-mode/SKILL.md) and continue under its workflow.

First identify the actual host. Codex entry points use `$pstack-codex:<skill>`; Claude Code entry points use `/pstack:<skill>`. In Antigravity, use the skill entry exposed by its native plugin UI or CLI and read [antigravity-runtime.md](../../references/antigravity-runtime.md); do not borrow another host's command syntax. Read the [shared runtime](../../references/runtime.md) and its selected adapter if the answer depends on host behavior.

The skill and guide files own the details. Read the destination before quoting or recommending it. Give the user the relevant installed file link and a short prompt adapted to the current host.

## Find out what they need

Infer the need from the question and conversation. A named situation, such as "which skill reviews a PR?", goes directly to the matching section. If the need is unclear, ask one short multiple-choice question:

- Get set up
- Start a task with `poteto-mode`
- Pick a skill for a situation
- Fix a run that went wrong
- Make pstack my own

Check only state that changes the answer:

- When model or cost setup matters, read the active host's effective policy with `node <plugin-root>/bin/config.mjs show --host codex`, `--host claude`, or the read-only common-policy view `--host antigravity`. The shared file is `~/.config/pstack/config.json`. If it is absent, missing roles inherit the main conversation and setup remains optional. This command is read-only; do not initialize or change preferences from a help request.
- If the project has no `verify-*` skill or application harness, mention [`create-verification-skill`](../create-verification-skill/SKILL.md) when the question is about proving behavior.

When setup is relevant and the user has not chosen a policy, offer to point them to the current host's `setup-pstack` entry now or answer first and leave setup for later. Do not run setup or write preferences as part of help.

## Get set up

Use [the setup guide](../../docs/guide/01-setup.md) for installation and updates. Once installed, the setup entry is `$pstack-codex:setup-pstack` in Codex and `/pstack:setup-pstack` in Claude Code. It reads and updates pstack's shared or host-specific preferences only when the user asks.

To start a real task, invoke `$pstack-codex:poteto-mode` in Codex or `/pstack:poteto-mode` in Claude Code. A useful prompt states the goal, a check that can pass or fail, the proof to show, and any real constraints. The playbook supplies the steps, so a hand-written skill sequence can drop or reorder them. See [`references/prompting.md`](references/prompting.md) and [guide page 2](../../docs/guide/02-poteto-mode.md).

pstack uses extra tokens for delegated work and review panels. To reduce that cost, shorten a panel list in setup, use `inherit-parent` or `auto` where appropriate, or reserve `poteto-mode` for work that needs its rigor. Do not promise a price or model capability from upstream names; model availability is checked by the actual host.

Codex and Claude Code share the skills and configuration, but use different native delegation, discovery, goal, and scheduling interfaces. `poteto-mode` is a conversation instruction; it does not install a global mode, create a goal, or schedule future work. See the [runtime contract](../../references/runtime.md) for the boundaries.

## Start a task with `poteto-mode`

`poteto-mode` matches the request to a playbook, copies its steps into the todo list, and uses other skills as those steps need them. A skipped step remains visible with its reason. State what should change and how to tell it is done; do not list skills unless you want to override a specific playbook choice.

When the current conversation already holds the task, short follow-ups such as "continue" or "keep going until the check passes" are enough. Say "new task" when the subject changes, or state that the question is read-only. The mode does not create a separate persistent host mode. For a long finite task, request the host's native goal explicitly and give it a checkable finish condition. Scheduling is separate and needs its own explicit request.

## Pick a skill

The default for non-trivial work is `poteto-mode`, which routes to other skills when a playbook calls for them. Recommend a direct skill when the user wants more or less scrutiny than the playbook provides. Read that skill before recommending it and give one example prompt.

| The user wants to | Skill |
|---|---|
| Do a non-trivial task with a rigorous workflow | [`poteto-mode`](../poteto-mode/SKILL.md) |
| Understand what code does or where code should live | [`how`](../how/SKILL.md) |
| Trace why code is shaped this way or why a number changed | [`why`](../why/SKILL.md) |
| Understand a change in plain language | [`teach`](../teach/SKILL.md) |
| Recover context from recent work | [`recall`](../recall/SKILL.md) |
| Catch up on this chat since your last message, with enough context to decide each action item | [`ketchup`](../ketchup/SKILL.md) |
| Check what a small diff might break elsewhere | [`blast-radius`](../blast-radius/SKILL.md) |
| Settle types and module boundaries before implementation | [`architect`](../architect/SKILL.md) |
| Compare several attempts at one brief | [`arena`](../arena/SKILL.md) |
| Split work across independent slices or races | [`swarm`](../swarm/SKILL.md) |
| Ask independent reviewers to find defects in a diff | [`interrogate`](../interrogate/SKILL.md) |
| Fix a bug test-first when a cheap test path exists | [`tdd`](../tdd/SKILL.md) |
| Apply TypeScript-specific rules | [`typescript-best-practices`](../typescript-best-practices/SKILL.md) |
| Remove comments before an independent review | [`no-comments`](../no-comments/SKILL.md) |
| Remove generic AI wording from prose | [`unslop`](../unslop/SKILL.md) |
| Write a README, guide, proposal, or PR description | [`technical-writing`](../technical-writing/SKILL.md) |
| Hear an explanation in simpler words | [`bro`](../bro/SKILL.md) |
| Give an app a scripted way to prove user-visible behavior | [`create-verification-skill`](../create-verification-skill/SKILL.md) |
| Update a verification skill and its feature map | [`maintain-verification-skill`](../maintain-verification-skill/SKILL.md) |
| Vet a performance measurement | [`benchmark-checklist`](../benchmark-checklist/SKILL.md) |
| Design a rigorous run when no playbook fits | [`figure-it-out`](../figure-it-out/SKILL.md) |
| Keep a decision record for later review | [`show-me-your-work`](../show-me-your-work/SKILL.md) |
| Configure pstack role and reasoning preferences | [`setup-pstack`](../setup-pstack/SKILL.md) |
| Draft a personal mode from authorized work history | [`automate-me`](../automate-me/SKILL.md) |
| Turn a finished task's lessons into approved skill edits | [`reflect`](../reflect/SKILL.md) |
| Prevent repeated engineering mistakes | [`correct`](../correct/SKILL.md) |
| Build an optional webhook UI workflow | [`make-bot-ui`](../make-bot-ui/SKILL.md) |
| Dispatch a local external-agent CLI | [`xagent`](../xagent/SKILL.md) |
| Find the right pstack entry point | `poteto-help` |

If a neighboring skill is not listed, read its frontmatter and route by its description. The `principle-*` skills are one-rule guidance used by `poteto-mode`; [guide page 8](../../docs/guide/08-principles.md) lists them.

Close calls:

- `how` explains current behavior; `why` traces the reasons; `teach` turns one or both into a plain explanation.
- `arena` gives each worker the same brief and compares attempts; `swarm` assigns slices or a race and aggregates evidence.
- `architect` settles a design and normally continues into implementation; add a review checkpoint if the user wants to approve the design first.
- `interrogate` reviews the diff; `blast-radius` investigates possible breakage outside it and proves a key safety fact.
- `recall` rebuilds context across recent chats; `ketchup` covers only this chat since the user's last message; resuming one specific task or branch uses the Session pickup playbook.
- `figure-it-out` designs one rigorous run; the Orchestrate playbook handles a program spanning multiple phases or PRs.

## Playbooks and principles

Playbooks are steps inside `poteto-mode`, not separate skills. Phrases such as "babysit this PR", "land the stack", "take over this branch", "pause safely", or "run the eval playbook" select playbooks. Babysit stops at merge-ready; merging or publishing still needs the user's explicit request. [Guide page 6](../../docs/guide/06-verify-and-ship.md) explains the PR flow.

`principle-*` skills state one engineering rule that `poteto-mode` can apply and cite. Users usually steer with the principle name, for example, "apply prove it works and show the actual output." Direct invocation remains available.

pstack has no standalone `orchestrate` skill; Orchestrate is a playbook. Goals and recurring schedules come from the active host and remain separate from pstack. Installing or invoking pstack does not authorize external writes or create a schedule.

## Fix a run that went wrong

| Symptom | What to try |
|---|---|
| The workflow did not apply to a new chat | Invoke `poteto-mode` in that chat; it does not create a global mode. |
| A question continued the prior task | Say "new task" or state that the question is read-only. |
| A model preference had no effect | Read back the active host's effective config and start a new pstack task; existing workers retain their policy snapshot. |
| Runs cost more than expected | Reduce panel length or use inherited models where appropriate; see the cost guidance above. |
| A skill did not load automatically | Skills load when invoked or called by a playbook; pstack does not load every skill into every task. |
| Parallel writers collide | Give each writer a separate supported worktree and verify its base revision. |
| A long task stops at a duration | Give the host's native goal a finite, verifiable finish condition. A schedule is a separate feature. |
| A green build is reported as proof of behavior | Ask for the user-visible flow, stored value, or other behavior check. |

For a run that drifts, [`references/prompting.md`](references/prompting.md) has short steering prompts. [Guide page 10](../../docs/guide/10-recipes-and-pitfalls.md) has more examples.

## Make pstack your own

- [`automate-me`](../automate-me/SKILL.md) drafts a personal entry from authorized work history.
- [`reflect`](../reflect/SKILL.md) proposes skill edits after a task; the user reviews them.
- Ask `poteto-mode` to write a skill for a workflow; the Eval playbook can test the change.
- Fix a misbehaving shared skill in its own change, not inside unrelated feature work.

See [guide page 9](../../docs/guide/09-make-it-yours.md).

## Reply

Lead with the answer. Give at most one example prompt, adapted from [`references/recipes.md`](references/recipes.md), then link the relevant installed file. Keep the answer short unless the user asks for the full map.
