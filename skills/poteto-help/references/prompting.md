# Word the prompt

State the goal and the check for done. The playbook supplies the steps, so a few plain sentences are usually clearer than a spec.

## Put in

- The goal: what is wrong or what should change.
- The done check: something that can pass or fail. "Make it better" and a duration are not checks.
- The proof to show: a command result, a user-visible flow, a stored value, or a before-and-after measurement.
- What you already know: a symptom, reproduction step, log line, or relevant file.
- Real constraints: "reproduce first", "don't change code yet", "zero behavior change", or "show me the diff before opening a PR" can change the work.

## Leave out

- The implementation recipe. State the outcome and leave room to find a better approach.
- A manual sequence of skills. The playbook owns the order; name a skill only to override a specific choice.
- Your theory of the cause before the agent has restated the problem. A guess can narrow the search too early.

## Load the context first

- For a noisy report, ask the agent to restate the issue plainly before acting. Correct a misunderstanding before code exists.
- In a fresh chat, use `recall` to recover relevant work before handing over a new issue.
- Before changing unfamiliar code, use `how` to trace behavior and `why` to understand the design or evidence.
- Ask `teach` to explain a choice and its trade-offs; an explanation with evidence is easier to assess than a summary.

Use the active host's entry point for each skill: `$pstack-codex:<skill>` in Codex or `/pstack:<skill>` in Claude Code.

## Design before the plan

- Ask for more than one design when the choice is expensive to reverse; use prototypes to answer open questions with evidence.
- Let a runnable prototype settle questions before adversarially reviewing an abstract plan.
- For a shared package or API, write the caller-facing example or tutorial first, then work back to the implementation.
- Write a multi-step plan after its design is settled. End each step with a check.

## Follow up briefly

- "Do it", "continue", and "keep going until the check passes" are enough when the conversation already holds the task.
- Say "new task" when the subject changes. Otherwise `poteto-mode` may treat the message as a follow-up.

## Before stepping away

- State a finite goal and its pass/fail checks. Request the active host's native goal only when that is what you want; pstack does not create one for you.
- Ask for a fresh worktree at a named base when parallel writers need isolation.
- State review or approval gates that matter, especially before external writes.
- Give an exit condition, such as "if the check is still blocked after two attempts, stop and report why." Scheduling is separate and must be requested separately.

## Steer in one line

- Restate the goal: "I asked for a reproduction, not a fix yet."
- Name the principle: "Apply prove it works; show the actual output, not just the build log."
- A principle name works when the skill already defines the decision it changes.
