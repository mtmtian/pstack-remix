---
name: setup-benny
description: Configure the dormant Benny run pack, validate its Codex capabilities, and generate reviewable configuration and goal prompt drafts.
---

# Set up Benny

Before using this skill, read [`../../references/runtime.md`](../../references/runtime.md). The runtime contract replaces the upstream host assumptions and defines goal, event, tool, browser, authorization, and evidence boundaries.

Benny is an on-demand configuration pack. It contains two operational flows: triage a Slack issue report, then reproduce and optionally fix a confirmed bug. Setup may copy local files and generate secret-free drafts. It must not create, arm, enable, or inspect a live automation, send a message, write a tracker, open a pull request, create a bot, or write any remote resource.

A host goal is one optional way to keep a finite durable objective. Benny can also run as a manual single run supplied with one report, or from an actually registered event trigger. A goal is not a timer or an incoming-event subscription. A recurring or event-driven run needs a real scheduler or event interface exposed by the current host. Do not invent one, create a background process, or claim that a goal is listening. If the user later explicitly authorizes activation, inspect the actual tool schema first and call only the exposed capability for the exact target and scope.

## 1. Copy the pack and verify the project runtime

Ask which repository will use Benny. The source pack is the directory containing `FOR_AGENTS.md`. The destination is `<target-repository>/.agents/automations/benny/`.

Merge the entire source pack into the destination:

1. Create the destination when it is absent.
2. Copy every source file to the same relative path.
3. Preserve destination-only files. Never delete unrelated files.
4. Keep user-owned configuration, feature maps, routing maps, drafts, and secrets outside the copied pack.
5. When a source-managed destination file differs, inspect the diff and merge without discarding local edits. If ownership is ambiguous, stop and ask before replacing it.
6. Verify that `FOR_AGENTS.md`, this setup file, both operational files, every reference, and every template are present.
7. Read the copied `.agents/automations/benny/skills/setup-benny/SKILL.md` directly from the target repository before continuing.

Do not edit `.cursor/settings.json`, a Cursor manifest, or another plugin manifest. From a fresh agent rooted in the target repository, verify that the pstack plugin for the current host is installed or otherwise available and that these shared skills resolve there. A local target may use project or user scope; a remote runner must independently verify its own available scope:

- `how`
- `why`
- `tdd`
- `unslop`
- `principle-separate-before-serializing-shared-state`
- `principle-minimize-reader-load`
- `principle-guard-the-context-window`
- `principle-sequence-verifiable-units`
- `principle-fix-root-causes`
- `principle-prove-it-works`

Do not count a skill loaded only from the current session. Use the host's actual skill/plugin discovery. If the plugin or any required skill does not resolve in the relevant target environment, stop and report the missing capability. The files under `.agents/automations/benny/` are read directly by the run prompts; they are not slash skills and must not be added to a manifest.

The copied pack and all referenced secret-free configuration must be committed before a run reads them. Setup does not commit files.

## 2. Create user-owned configuration

Open these examples without editing them in place:

- `../../templates/configuration.example.yaml`
- `../reproduce-and-fix-issues/references/feature-map.example.md`
- `../triage-issue-reports/references/routing.example.md` when routing is needed

Create user-owned copies outside `.agents/automations/benny/`, for example:

- `.agents/benny/configuration.yaml`
- `.agents/benny/feature-map.md`
- `.agents/benny/routing.md`

Write these local files only when the user explicitly asks for that local write. Otherwise generate the completed, secret-free contents as a reviewable response or draft. Never put a key, token, password, cookie, or private credential in the pack, a prompt, or committed configuration.

Keep `runtime.invocation` as `manual-single-run` unless the user selected a registered event trigger or native goal. Set `runtime.event_interface` or `runtime.scheduler_interface` only to a name discovered from the current host tool schema. Empty means unavailable. Keep `runtime.enabled: false` during setup.

Fill and confirm:

- Source Slack channel ID and optional operations channel ID
- Repository URL and default branch
- Triage identity or Slack user ID
- Tracker type, team, project, labels, intake status, and the actual exposed adapter
- Optional routing map path
- Control skill or adapter and completed user-facing feature-map path
- Status strings, artifact directory, and retention policy
- Budgets for polling, verdict wait, follow-up, repro, rejection, fix, and operations status
- Available host model IDs or `inherit-parent`; never guess an upstream model slug
- Explicit per-run authorization for Slack thread replies, operations status posts, tracker writes, draft pull requests, and any event binding

The required source channel, triage identity, repository, tracker adapter, control adapter, and feature map must be explicit. If any is missing or ambiguous, fail closed.

## 3. Discover current capabilities

Use only integrations and tools that the current host actually exposes. Check their live schemas before putting a name in the configuration or prompt:

- Slack read, thread reply, attachment metadata/download, and optional operations edit
- The configured issue-tracker read/search/write/compensation operations
- Repository and history reads, tests, and the host's draft-pull-request action
- The configured control adapter and its seven capabilities in `references/control-adapter.md`
- The user's isolated `ego-browser` surface for browser UI work

Do not turn a placeholder action name into a tool call. Do not use an undocumented endpoint or a private connector. External writes require user authorization for the exact target and scope; if that authorization or capability is absent, prepare a dry-run result and stop.

For Slack, the coordinator alone may post. Delegated workers receive no Slack credentials and no write actions. If a worker cannot be structurally prevented from posting, do the analysis in the coordinator.

## 4. Prepare the routing and control inputs

If routing is requested, copy `../triage-issue-reports/references/routing.example.md` to the user-owned `.agents/benny/routing.md` and replace every placeholder. Keep owner pings off by default. A route needs evidence from the report or cause trace; a keyword alone is insufficient. A reroute tells the reporter where to go; the run never cross-posts.

Read `../reproduce-and-fix-issues/references/control-adapter.md` and the completed feature map. Confirm that the named adapter can:

- Bring up the target app and safe test environment
- Navigate every mapped feature through the real UI
- Exercise the mapped states through declared actions
- Inspect state without forcing the result
- Capture screenshots
- Start and stop a recording
- Clean up processes, sessions, profiles, and temporary data

If any capability is missing, leave the repro draft blocked. It must never claim a reproduction it did not perform.

## 5. Generate reviewable goal drafts

Read [`../../templates/triage-automation-prompt.md`](../../templates/triage-automation-prompt.md) and [`../../templates/reproduce-automation-prompt.md`](../../templates/reproduce-automation-prompt.md). Generate two secret-free drafts that paraphrase `FOR_AGENTS.md` and the finished configuration:

- `.agents/benny/drafts/benny-triage.goal.md`
- `.agents/benny/drafts/benny-reproduce.goal.md`

Write them only when the user explicitly requests those local files; otherwise show the same drafts for review. Each draft must point to the committed operational file under `.agents/automations/benny/` and the pack-local `references/runtime.md` snapshot by a stable relative path. Never embed plugin cache paths or copy the operational file contents into a live prompt. Keep the snapshot synchronized with the canonical plugin-root contract when refreshing the pack.

The drafts remain dormant. Do not activate a goal, a scheduler, a Slack event registration, or any other activation interface during setup. If the user later explicitly says to arm a finite goal, use the selected host adapter to establish the full objective once after checking that the target repository and referenced files are committed. If the user asks for event-driven or recurring behavior, inspect the exposed scheduler/event tools first; call one only when it exists, is authenticated, and the user authorized that exact binding. Otherwise report the missing interface and leave the drafts unchanged.

### Triage goal draft

The goal must:

- Read and follow `.agents/automations/benny/skills/triage-issue-reports/SKILL.md` for every run.
- Start from one supplied top-level report event, an explicitly started manual single run with the same immutable coordinates, or a native goal that the user explicitly established for this report.
- Read the full thread and relevant attachments, classify bug, performance, feature request, question/feedback, or reroute, trace the likely owning layer, and deduplicate against the configured tracker.
- Create or update a tracker item only when the config and current run explicitly authorize that exact tracker target and the adapter supports compensation.
- End with at most one concise reply in the original source thread and exactly one configured `[benny:bug]`, `[benny:performance]`, or `[benny:other]` marker. A bug or performance marker may include a tracker URL.
- Never post a source-channel root message, cross-post, DM, or progress update.
- Keep delegated workers read-only and forbid every Slack write.

### Reproduce goal draft

The goal must:

- Read and follow `.agents/automations/benny/skills/reproduce-and-fix-issues/SKILL.md` for every run.
- Start from the same supplied report event, an explicitly started manual single run, or a native goal that the user explicitly established, then wait for a trusted triage marker in the immutable original thread.
- Use the configured repository and branch, tracker, control adapter, and feature map. Require the adapter's real UI, screenshots, recording, read-only state cross-check, and cleanup.
- Stop when a person owns the fix. If a pull request or merged commit may already fix the report, verify it on baseline and patched builds without authoring over it.
- Attempt at most one bounded root-cause fix after a confirmed repro and all rejection/fix gates pass. Use TDD when the test is cheap, smoke the blast radius, and open a draft pull request only with explicit authorization and before-and-after proof.
- Keep source updates concise and thread-only. Never post a source-channel root message. Children return findings only and cannot use Slack writes.

## 6. Existing external bindings

Do not inspect, update, or create existing external automations through an undocumented backend. Give the user a concise field checklist for the integration they control:

- Name and description
- Trigger source and immutable thread coordinates
- Direct instruction to read the committed operational file
- Slack read and thread-reply capabilities
- Repository and branch, tracker, control adapter, feature map, and draft-pull-request capability
- Marker wait, evidence, existing-fix verification, bounded-fix, and thread-only rules

Do not create replacements or duplicates. If the host exposes no supported scheduler or event interface, state that event-driven self-running behavior is unavailable and leave the goal drafts dormant.

## 7. Verify before any activation

Use a test channel or harmless test report only after the user explicitly authorizes the test's exact target and writes. Confirm that the pack and every referenced secret-free file are committed. Confirm that both goal drafts point at their exact committed operational files.

For the triage flow, verify:

1. The immutable root `thread_ts` is stored.
2. At most one verdict is posted as a reply and contains one configured marker.
3. Missing coordinates, a deleted parent, or an unavailable capability produces no post and no tracker write.

For the repro flow, verify:

4. Only the configured triage identity can supply the accepted marker.
5. The same source coordinates remain immutable.
6. A delegated worker cannot use any Slack write action.
7. No source-channel root message appears.
8. The control adapter proves the exact symptom twice, preserves captures, and cleans up without deleting user work.
9. Existing fixes are verified without competing edits, and a draft pull request is attempted only after the explicit authorization and proof gates.

Do not activate normal traffic until the relevant checks pass. A missing host interface, unavailable integration, uncommitted file, or missing authorization is a blocker, not permission to guess.
