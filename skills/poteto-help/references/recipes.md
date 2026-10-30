# Prompts worth copying

Replace the goal, paths, and checks with the real ones. These examples use `poteto-mode` as shorthand. Invoke it as `$pstack-codex:poteto-mode` in Codex or `/pstack:poteto-mode` in Claude Code. Use the same host prefix for direct skills.

## Understand

- `poteto-mode read <thread>. Restate the underlying issue plainly before doing anything. Don't change code yet.`
- `in-your-own-words <long or messy ask>`
- `sharpen <the prompt you're about to send>`
- `poteto-mode investigate why <symptom>. Give me what we know, which evidence you used, and your best hypotheses. Don't change code yet.`
- `Use how to trace <subsystem>, then why to find the evidence behind the recent change.`
- `Recall my work on <topic> from last week, then read this issue.`
- `Teach me why you implemented it this way, what you traded off, and where the code proves it.`
- `poteto-mode take over this branch. Read the decision log, identify what is done, and continue without repeating finished work.`

## Build

- Bug: `poteto-mode <symptom>. Reproduce first, then fix and verify.`
- Bug in an app: `poteto-mode reproduce this with verify-<app>. If it reproduces on the intended base, fix it and show me the user-visible result.`
- Bug with a cheap test: `Reproduce <bug> first. If a cheap test path exists, use tdd, then fix and rerun it.`
- Feature: `Add <behavior>. Keep <current output> byte-identical and verify both cases.`
- Refactor: `Move <code> into one module with zero behavior change. Record current output first and prove it is unchanged.`
- Performance: `<operation> takes <time> on <fixture>. Trace the measured cause, fix it, and show before and after.`

## Design and plan

- `poteto-mode prototype a few options for <feature>. Give me screenshots or timings to compare.`
- `We need <feature>. Architect it first and answer open questions with prototypes. Stop for my design review before implementation.`
- `Write a user tutorial for <new package> first, then teach me why it fits the caller's needs.`
- `Ask arena for an independent attempt at this approach.`
- `Turn the settled design into a plan of small, verifiable PRs. Give every step its own check.`
- `Plan the migration from <library> to <target>. Preserve current behavior, including known bugs, and give each step a verification check.`

## Review and ship

- `Interrogate the whole branch against its intent. Do not change anything; report only defects or regressions a run proves.` Read the Dropped list too.
- `create-formal-verification-skill prove <property> holds in <module>, even when <steps> interleave or retry.` After merges or refactors in that code: `maintain-formal-verification-skill`.
- `Swarm: check each package under <dir> with its own check script, then give me one report.`
- `Open a focused PR with the verification evidence in its description.`
- `Babysit this PR until it is merge-ready; do not merge it.`
- `Land the stack.`

## Away and back

- `I am stepping away. Finish <goal> in a fresh worktree from <base>. Done means <checks>. Keep a decision log, push the branch, and open the PR; stop before any merge or other external write that I have not authorized.`
- `Show me the work trail and what still needs attention.`
- `ketchup` catches you up on this chat since your last message and lists every call that waits on you.
- `Run these independent queue items and report each result before proceeding to another phase.`
- `Reflect on this task and propose only skill edits that change a future decision.`
- `Explain your last reply in plain language.`
