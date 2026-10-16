---
name: reflect
description: Spawn three parallel review subagents over the active transcript, surface learnings, and route each to a concrete edit on an existing skill. Use when the user says reflect.
---

Read [the shared runtime contract](../../references/runtime.md) before this workflow.

# Reflect

Mine the current conversation for durable learnings, then route them into skill edits.

Invoke when the user says "reflect" or "$reflect". Skip when the conversation is trivial, off-topic, or already covered by an existing skill the parent followed correctly. One-offs are not learnings.

## 1. Locate the active transcript

Use the current conversation or an authorized host thread-history tool. If local rollouts are needed, constrain candidates by real session metadata (workspace cwd, thread ID, and requested date range) before reading content. Do not scan unrelated projects. If the active transcript is unavailable, use a clearly labeled digest and report the limits of trace verification.

## 2. Spawn three reviewers in parallel

Spawn three bounded read-only review perspectives using actual host roles and available models. Grant no external writes; available read-only MCP lookups may supplement in-scope transcript evidence. Set each worker's reasoning effort for the job, per the Subagents section of the **poteto-mode** skill.

| Lens | `model` | Prompt template |
|---|---|---|
| Judgment | your configured `reflect judgment` model (default `inherit-parent`) | `references/judgment-reviewer.md` |
| Tooling | your configured `reflect tooling` model (default `inherit-parent`) | `references/tooling-reviewer.md` |
| Divergent | your configured `reflect judgment` model (default `inherit-parent`) | `references/divergent-reviewer.md` |

Pass each template verbatim, substituting the transcript path or digest where marked. Reviewers return findings in their terminal result.

## 3. Synthesize

Use a supported synthesis agent when it can run alongside useful parent work, otherwise synthesize directly. It may perform available read-only lookups to verify citations. Use `references/synthesizer.md` verbatim, with each reviewer's full output inlined where marked. It returns an Accepted / Rejected / Backlog list.

## 4. Structural enforcement check

Move any Accepted item that a lint rule, script, metadata flag, or runtime check would enforce more reliably to Backlog. See the **encode-lessons-in-structure** principle skill.

## 5. Apply

Present the synthesizer's full Accepted / Rejected / Backlog output and wait for explicit approval before applying any Accepted edit. The user picks the subset and may redirect routings. Skill changes affect every future agent in the org. Do not auto-apply.

Report backlog items locally. File them in an external tracker only when the user explicitly authorizes that destination and content.

Follow each approved row's Routing exactly:

- Trivial existing-skill edit (a one-line bullet, a tightened sentence, a stale fact corrected): the parent does it directly.
- Substantive existing-skill edit (a new section, a new pattern table, more than ~10 lines): hand to the available skill authoring helper described in the runtime contract and run its draft / test / iterate loop.
- `tune description: <skill path>` (the skill exists but didn't trigger when it should have): hand to `skill-creator` and run its description-optimization loop.
- `new skill via skill-creator: <kebab-name>`: hand creation to `skill-creator`. Do not invent the shape ad hoc.

If your environment ships a SKILL.md validator, run it on every touched skill before declaring done.

## 6. Summarize for the user

Short list, no preamble:

- Edits applied: `<skill path>`. What changed, one line each.
- New skills created: `<skill path>`. One line each (rare).
- Backlog filed to the devex tracker: `<issue title>` (`<tags>`). One line each.
- Dropped: one line per rejected finding + reason from the synthesizer.
