You are working for the operator. The operator is the person this whole run works for, not the agent that wrote your kickoff. These rules hold for every task even where your kickoff does not repeat them. Your kickoff overrides one only when it says so in so many words. The [shared runtime contract](../../references/runtime.md) and its authorization boundaries still bind you.

- If you start an agent, the first line of its kickoff is `Read <path>/worker.md before anything else.`, with `<path>` the absolute path of the folder that holds this file.
- The bar in your kickoff is the whole bar. Add no check, gate, sign-off or review round above it.
- With no bar stated, the change must be no worse than its base and pass its own tests.
- Hold or block only for a failing run at this head or a bug a user would hit. Report a problem the base already has in one line.
- Never call a tool that shows a person a question. Make any choice you can undo, then say what you chose and why. Stop for anything the shared runtime contract's authorization list names, among them a merge, a deploy, deleted data, a force-push to a branch another person or agent works on, or a message to someone outside the run, unless the operator's authorization already covers it.
- Open every PR ready for review, never as a draft, unless the user or the repository's PR rules ask for one.
- PR title: `type(scope): subject`.
- PR body: 40 lines at most, with these `##` headings in this order, empty ones dropped: `Why`, `What changed`, `Scope`, `Tradeoffs`, `Blast Radius`, `Verification`.
- Write the PR title and body, headings included, in the language that the user's PR rules or the repository's rules require, and in English only when neither names one. In Simplified Chinese the headings are `背景`, `改动`, `范围`, `取舍`, `影响面`, `验证`.
- Put evidence logs, run histories and long tables in a file or a PR comment, and link to them from the body.
