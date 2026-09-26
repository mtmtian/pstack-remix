# benny run intent

Before using this file, read [`references/runtime.md`](./references/runtime.md). It defines the host's goal, event, tool, authorization, and evidence boundaries.

## what i want to automate

i want two dormant host run profiles that work together in one Slack issue channel. A report can start a manual single run, an actually registered event trigger, or an optional native goal that the user explicitly establishes.

The profiles are configuration sources, not live automations. A host goal is an optional finite durable objective, not a timer or an event subscription. If the host exposes an authorized Slack event or scheduler interface, setup may prepare a separate event binding for review. If it does not, the user may start one manual run per report. Do not invent a scheduler or claim that a run is armed.

### automation 1: triage issue reports

- trigger: when someone posts a new top-level report in my configured source slack channel, i want this automation to start on that report and keep its original thread coordinates.
- behavior: i want it to read the thread and attachments, classify the report as a bug or performance issue, feature request, question or feedback, or reroute, and trace the likely owning layer before routing.
- tracker: i want it to search my configured tracker for duplicates, update a confident duplicate, and create a ticket only for a clear net-new bug.
- tools: i want slack thread read and reply access, my configured tracker integration, and my optional routing map.
- outcome: i want exactly one reply in the source thread with a short verdict and `[benny:bug]`, `[benny:performance]`, or `[benny:other]`. a bug or performance marker may include the tracker url.
- boundary: i never want this automation to post a root message in the source channel.

### automation 2: reproduce and fix confirmed bugs

- trigger: i want this automation to start from the same new top-level report, or another supported trigger chosen during setup, then wait for the trusted triage marker in the original thread.
- gates: i want it to stop when someone clearly owns the fix. if an existing pull request or merged commit may fix the report, i want verification instead of a competing change.
- behavior: i want it to use my configured control adapter and feature map, reproduce the exact symptom twice through the real ui, and capture screenshots, video, and a read-only state cross-check.
- fix: i want it to verify existing pull requests without authoring over them. after a confirmed repro, it may attempt one bounded root-cause fix, use tdd when the test is cheap, smoke the blast radius, and open a draft pull request only when before-and-after proof passes.
- tools: i want slack thread read and reply access, repository and history access, draft pull request creation, my configured tracker, and my control adapter.
- outcome: i want evidence and a verified result in the source or optional operations threads, plus an optional draft pull request. updates should be concise.
- boundary: i never want this automation to post a root message in the source channel.

### shared rules

- i want the source channel and root thread coordinates to stay immutable for the whole run.
- i treat utility and debug bots as evidence, not delegation or fix ownership.
- i allow subagents to help, but they cannot post to slack or receive slack credentials.
- i want this entire pack committed at `.agents/automations/benny/` in the target repository. Its `SKILL.md` files are direct run instructions, not registered plugin skills.
- i want setup to verify that the pstack plugin for the current host and the shared skills such as `how`, `why`, `tdd`, `unslop`, and the required principle skills are available to a fresh target agent. Do not edit `.cursor/settings.json`.
- i want each goal prompt to read its committed operational file directly. I do not want plugin cache paths, copied excerpts, or slash-skill discovery.
- i keep user-owned configuration, feature maps, routing maps, drafts, and secrets outside `.agents/automations/benny/` so pack refreshes cannot overwrite them.
- i want both automations to fail closed when channel coordinates, tracker access, the control adapter, or the feature map are missing or uncertain.
- i want draft pull requests only. do not merge or deploy.
- I authorize no external write, message, issue, pull request, publication, or event binding by default. Each such action needs an explicit target and scope in the user-owned configuration and a matching user authorization for the current run.

### my configuration

- source slack channel: `<channel>`
- optional operations channel: `<channel or none>`
- repository and default branch: `<repo>`, `<branch>`
- tracker: `<type, team, project, labels, intake status>`
- routing map: `<path or none>`
- triage identity: `<slack identity>`
- control skill: `<configured skill or adapter>`
- feature map: `<committed same-repo path outside the copied pack, or behavior to paraphrase>`
- models: `<triage, reproduce, code, media review>`
- status emoji strings: `<seen, reproducing, reproduced, blocked, fixing, failed, pull request opened>`
- budgets: `<polling, verdict wait, follow-up, repro, rejection, fix>`
- optional bot token capability: `<none, file download, or editable operations status>`
- per-run external-write authorization: `<Slack thread reply, operations status, tracker, draft pull request, event binding>`

start from [`configuration.example.yaml`](./templates/configuration.example.yaml) and [`feature-map.example.md`](./skills/reproduce-and-fix-issues/references/feature-map.example.md). Copy and fill them outside this pack, for example under `.agents/benny/`. Keep secret values in a secret manager or environment.

## for the agent

The human enters setup by asking the agent to read this file. Do not look for or invoke a discovered Benny slash skill; read the committed operational files directly.

1. ask which repository will run the automations.
2. treat the directory containing this `FOR_AGENTS.md` as the source pack.
3. merge the entire source pack into `<target-repository>/.agents/automations/benny/`.
4. preserve every destination-only file. never delete unrelated files or overwrite user-owned configuration, feature maps, or routing maps.
5. when an existing destination file at a source-managed path differs, review the diff and merge without discarding local edits. if ownership is ambiguous, stop and ask before replacing it.
6. verify that the copied `FOR_AGENTS.md` and `skills/setup-benny/SKILL.md` exist in the target repository.
7. read and follow `.agents/automations/benny/skills/setup-benny/SKILL.md` directly from the target repository.

Verify from a fresh agent rooted in the target repository that the installed pstack plugin and the shared skills used by Benny resolve. For a local target, project-scoped or user-scoped pstack is sufficient; record which scope was found. A remote runner must independently resolve the same skills in its own environment. Do not count skills loaded only from the current session. Do not edit `.cursor/settings.json`, add this pack to another plugin manifest, or expect these operational files to appear in the slash-skill list.

If pstack or any shared dependency does not resolve in the relevant target environment, stop and explain what failed. Tell me that `.agents/automations/benny/` and any referenced secret-free configuration must be committed before a run can safely read them. Do not create, arm, enable, or update a live automation during setup.

Generate reviewable, secret-free configuration and two goal prompt drafts. The drafts may be written under the user-owned `.agents/benny/drafts/` directory only when the user explicitly requests that local write; otherwise present them for review. Do not activate a goal, a scheduler, or an event API as part of setup.

Paraphrase this intent and the finished configuration into each draft. The triage prompt must read and follow `.agents/automations/benny/skills/triage-issue-reports/SKILL.md`. The repro prompt must read and follow `.agents/automations/benny/skills/reproduce-and-fix-issues/SKILL.md`. Use these repo-relative paths only after the target repository confirms they are committed and the user explicitly starts a run.

For an existing external automation or event binding, do not inspect or update it through an undocumented backend. Validate the configuration, then give the user the concise field checklist so they can edit that integration directly. Do not create duplicates. If the host exposes no supported event or scheduler interface, report that gap and leave the drafts dormant.
