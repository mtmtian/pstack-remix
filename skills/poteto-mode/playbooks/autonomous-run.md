### Autonomous run

**Define done as a checkable predicate, then drive the authorized task to that result.** Follow the plugin's shared runtime contract for goals, event waits, and recurring work.

1. State the full objective, scope, constraints, and executable finish condition before the first iteration. Keep all required deliverables; time spent working is not a completion predicate.
2. For an explicit `/goal` or request to create a durable goal, inspect current goal state and create it once through the selected host adapter if none is active. Reuse the matching active goal. A different active goal must not be silently replaced. A normal task runs in the current session without inventing a persistent goal. If native goal activation is unavailable, say goal continuation is not armed and complete feasible work in the active session.
3. Each iteration makes the smallest change justified by evidence, runs the relevant check, and records what changed in the **show-me-your-work** trail. Commit only within authorization. Revert only your own ineffective changes, preserving unrelated work. Use **sequence-verifiable-units** so each unit ends in a check.
4. For CI, process, or child-agent dependencies, await actual host events or poll the returned IDs. Keep progress updates and use bounded waits. A shell sentinel alone does not re-enter an ended turn. For a separately requested fixed cadence, use an available scheduling capability and verify registration; a goal never substitutes for that schedule.
5. Address failures within scope and return to the predicate. A newly discovered issue outside scope is reported with evidence, not silently turned into another PR or external operation. Observe actual permission boundaries for sending, pushing, merging, publishing, and destructive actions.
6. Preserve checkpoints and evidence across compaction. On explicit pause, use Pause safely and handle the goal only as the selected host adapter permits. On repeated external blockers, follow the host's actual blocked-state or clearing behavior; do not mark complete to stop.
7. Complete only when the original predicate and every required deliverable are proven on the current artifact. If a goal is active, surface the completion evidence and follow the host adapter's completion behavior; retain usage accounting when provided. Report unverified gates honestly.

**Reply:** finish condition, iterations and evidence, accepted and discarded changes, remaining blockers, and actual goal state.
