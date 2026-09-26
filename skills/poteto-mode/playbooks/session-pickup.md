### Session pickup

**You own the resume point. Read the prior trail, don't redo it.**

1. Locate the prior trail. Use the current conversation or an authorized host thread-history tool. If local rollouts are needed, constrain candidates by real session metadata (workspace cwd, thread ID, and requested date range) before reading content. Do not scan unrelated projects. If the active transcript is unavailable, use a clearly labeled digest and report the limits of trace verification. A supplied session link or pushed branch can also anchor the pickup. Read the metadata overview and last messages first, then scan back for the decision points. Parse a long transcript in a subagent and keep the reduced timeline in the main thread (the **principle-guard-the-context-window** skill).
2. Reconstruct operational state. The branch and worktree, what already landed (`git log`, `git diff` against the base), the open todos, the decisions made. The prior trail is evidence of intent and prior observations; current code and external state determine what is still true. Resist the bias to re-derive it.
3. Diff done vs pending. Compare what shipped against what was planned, name the resume point, do not re-run the prior repro or redo completed work. Recheck drift-prone or material claims against current state without repeating already-proven work unnecessarily.
4. Route the remaining work to the matching playbook and pick the verdict: continue the execution, ship a finished recommendation, ratify or override a prior conclusion, or postmortem a failed run. The pickup playbook ends here. The routed playbook owns the rest.
5. Verify the inherited claims against the original goal on the real artifact (the **principle-prove-it-works** skill). A passing prior self-report is not the proof.

**Reply:** where the prior agent stopped, what you inherited vs redid (ideally nothing redone), the resume point, and the outcome.
