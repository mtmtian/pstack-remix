### Multi-phase or multi-PR plan

**You own the plan, not the code. The plan is a checklist an owner runs box by box and the operator audits from the evidence.** The plan is the deliverable. Do not implement.

1. When the change is one or two files with an obvious approach, skip the plan. Say so and stop.
2. Settle open questions by prototype before you write. Run `playbooks/prototype.md` for each. Keep the branch, the SHA, and the screenshots for Appendix A. Ask the operator only about a product or preference call that no run can settle. Give options (the **never-block-on-the-human** principle skill).
3. Explore in subagents with a supported agent role instructed to read `agents/poteto-agent.md` from this plugin and an explicit model per the Subagents section (the **guard-the-context-window** principle skill). Each returns file pointers, conventions, test commands, and entry points. No inlined dumps.
4. Copy the skeleton below into the plan file and fill every placeholder. Unless the operator names a path, write the file under the selected state directory's `docs/`. Keep every heading and every sub-block in the order shown. One section per PR. One PR is one change with its own evidence (the **sequence-verifiable-units** principle skill). Name the execution playbook in **How to read this**. Pick between `playbooks/autopilot-full.md` and `playbooks/autopilot-stack.md` per the rule at the end of `playbooks/autopilot-stack.md`. A standing program takes `playbooks/orchestrate.md`.
5. Write under `$technical-writing` in full, then `$unslop`. The body is one Diátaxis mode, how-to. Appendices hold explanation and reference. Each heading states the task or the finding. No long dashes. No mid-sentence colons.
6. Run `node <plugin-root>/skills/poteto-mode/scripts/check-plan.mjs <plan.md>` launcher and fix every line it prints (the **encode-lessons-in-structure** principle skill).
7. Hand back. Post the plan path and the script's output, then stop. Execution starts on the operator's explicit go, under the execution playbook the plan names.

**Verification.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked (the **prove-it-works** principle skill). That sentence is the verification rule. Every verification block opens with it. Size independent live lanes to the changed surface and risk. Include a regression lane against trunk when a comparable trunk scenario exists, and record the missing baseline when it does not. Each lane is one box with a concrete scenario, the evidence it saves, and its pass predicate. Never invent a control surface, screenshot, baseline, ratio, or metric. If a required surface or probe is unavailable, mark the lane blocked and explain the prerequisite in Appendix C. The perf gate is dual-sided when comparable. Trunk and head must both produce the named metric; when the feature is absent on trunk, isolate the diff-added work and use an absolute budget for that work plus the end-to-end state the user waits for. Do not claim a ratio between unlike scenarios. A PR that changes an interaction is review-gated. The operator reviews it with the available evidence before merge. A PR that changes no interaction writes `**Review gate.** None. <PR id> is not review-gated.` and no boxes under it.

**Control skill.** Pick it by surface. Browser and web UIs use the installed `ego-browser` skill. Electron uses a supported isolated control tool. CLIs and TUIs use the project harness and isolated PTY sessions. Native mobile uses whatever simulator-driving skill the repo has. A PR that touches two surfaces gets lanes on both. A surface with no control skill is a risk in Appendix C, and its live block still names how each lane drives it.

````markdown
# <Program> plan

<Under ten lines. What changes, for whom, the rule the program enforces, and the PR ids in order.>

## How to read this

One box is one unit of work. Every box names the evidence that checks it. A nested box is a sub-step of the box above it. Check a box only when its evidence exists, a file, a log line, a screenshot, a test run, or a SHA. The body is a how-to. The appendices explain and record.

The program runs `<plugin-root>/skills/poteto-mode/playbooks/<execution playbook>.md`. <Who merges, and which PR ids are the operator's items that stop at merge-ready.>

Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

## Program checklist

### Arm the program

- [ ] State the protocol and this plan to the operator, then stop. Start execution only on the operator's explicit go.
- [ ] Read these from trunk at program start. Re-read them at every tick.
  - [ ] `git show <resolved trunk ref>:<execution playbook path>`
  - [ ] `git show <resolved trunk ref>:<selected review skill path>`
  - [ ] `git show <resolved trunk ref>:<control skill path>`
  - [ ] `git show <resolved trunk ref>:<opening-a-pr path>`
  - [ ] `git show <resolved trunk ref>:<each other leaf skill path used>`
- [ ] If explicitly requested, create or reuse one native host goal with the plan path, PR order, verification rule, merge owner, and done condition. Otherwise execute in the current session. Do not create a goal file as a substitute for the host goal.
- [ ] Poll actual collaboration, process, CI, and forge handles at the host-supported cadence. A goal is finite state, not a timer. Use an installed scheduler only when its registration result is observable; otherwise keep recurrence unarmed and report that fact.
- [ ] At each observed event, re-read the execution playbook and armed goal, audit side effects and every owner's `children.tsv`, and investigate suspected stalls before reassignment. Post a short status message only for previously unreported tracked changes, such as a code-ready head, round, verdict, merge, blocker, or required operator decision. Log each audit and its reported changes (or none) in the decision trail. Keep active-work progress updates required by the host; unchanged heartbeat polls stay quiet.
- [ ] On the operator's hold or stand-down, send every owner a zero-writes order at once.

### Spawn owners

- [ ] Spawn one owner per PR with the full lifecycle the execution playbook names.
- [ ] Follow this dependency graph. Start dependent work only after its parent merges, or base it on the parent branch when the execution playbook stacks.
  - [ ] <PR id> and <PR id> are independent and first. Both branch from `main`.
  - [ ] <PR id> after <PR id>.
- [ ] Hold the file boundaries. <PR id or class> touches only `<glob>`.
- [ ] Hold the review gate. <PR ids> change an interaction. They wait for the operator's review in chat with screenshots and a video before merge.

### PR mechanics, for every PR

- [ ] Resolve the forge once. Default to `gh`; if `command -v origin` succeeds and Origin can resolve the repository, use `origin pr` for every PR operation. Record any fallback to `gh`. Never require `gt`.
- [ ] Open a PR only when authorized, with readiness matching the user's instructions, project rules, and current evidence. Use the resolved forge. A stack child targets its parent branch.
- [ ] Run the repo's lint and typecheck once before the PR-facing push. Push with hooks on.
- [ ] Review the diff directly under the runtime contract before each commit and use `$no-comments` before review.
- [ ] Triage every Bugbot and security-reviewer comment per `../references/bugbot-triage.md`.
- [ ] Rebase onto current trunk before the code-ready report and babysit. Keep that merge base in fix rounds. Rebase again only at merge prep, on a `git merge-tree` conflict with trunk, or on a CI failure that comes from a change on trunk.

### Verdict and merge, for every PR

- [ ] At the code-ready head SHA and each later patch-changing push, run the independent review lanes named in the PR's **Verify, live** and **Verify, perf** blocks, plus independent audit lanes with distinct focuses that read the diff and receipts. Size lanes to the risk and state the reason. Audit merge-ready receipts before the final verdict.
- [ ] Clean only when every required lane is `PASS`. Send all proven defects to the owner, including defects reported as notes, with a red regression test or reproducible evidence. Carry those defects into the next review brief. A new head gets a fresh round except for lane results valid under the Shipping patch-id rule.
- [ ] <The merge or append rule from the execution playbook, with the patch-id rule from `playbooks/shipping.md`.>

### Boot recipe, for every live lane

Each live lane runs in an isolated worktree or process at the PR head, using only the project's verification harness or an available application-control tool. Record the isolation mechanism. If no supported control surface exists, name that gap and leave the lane blocked.

- [ ] Create or select an isolated worktree and check out `<head SHA>` without overwriting unrelated work.
- [ ] <Start the backend and the surface. Wait for ready.>
- [ ] <Deliver input only through the control skill's commands. Name the read-only diagnostics.>
- [ ] Save evidence to a project-approved path and return the paths with the report. Use screenshots or video only when the selected control surface produces them.

## <Task as a verb phrase> (<PR id>)

**Depends on.** <PR id, or None.>

**Files.**

- [ ] Edit `<path>`.
- [ ] Create `<path>`.
- [ ] Delete `<path>`.

**Build.**

- [ ] <One change. Name the symbol and the file.>

**You see.**

- [ ] <One observable result, with the exact log line or screen state.>

**Verify, unit.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] <Test file and the case it gains.> Run `<command>`.

**Verify, live.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked. Use `<N>` independent lanes sized to the changed surface and risk, and explain that choice.

- [ ] Lane 1. <Regression lane against trunk, or a recorded reason that no comparable trunk scenario exists.> Run the same load-bearing scenario at trunk and head when possible. Save `<evidence path>` when the control surface supports it. Pass when <predicate>; otherwise record the blocked prerequisite.
- [ ] Lane 2. <Scenario or omit this lane when the risk assessment does not require it.> Save `<evidence path>` when available. Pass when <predicate>, or record the concrete blocker.
- [ ] Lane N. <Repeat only for independently justified scenarios.> Save `<evidence path>` when available. Pass when <predicate>, or record the concrete blocker.

**Verify, perf.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Metric. <What is measured at both trunk and head. If trunk lacks the feature, also name the diff-added work and the end-to-end state the user waits for.>
- [ ] Probe. <The command or procedure, run at trunk and at the head, interleaved. Both sides must produce the metric.>
- [ ] Baseline. Record the trunk <value> first.
- [ ] Rule. <Head against trunk, with the number that fails. If the scenarios differ, add absolute budgets for the diff-added work and the user-visible end state instead of an invalid ratio.>

**Review gate.** The operator reviews before merge.

- [ ] Copy lane <n> screenshots into `<media path>/<pr-id>-review-<slug>.png`.
- [ ] Record a 30 to 60 second video of the change in the selected isolated lane when the control surface supports video. Save it as `<media path>/<pr-id>-review.mp4`; otherwise record why video is unavailable.
- [ ] Post the screenshots and the video in chat. Stop at merge-ready. Wait for the operator's click.

**Merge.**

- [ ] Root's clean verdict at the exact head SHA.
- [ ] Bugbot triage done.
- [ ] Rebased onto current trunk after the verdict, patch-id unchanged.
- [ ] <The owner squash-merges its own PR, or the root appends it to the base-branch stack and the operator lands it bottom-up.>

## Close the program

- [ ] Every box above is checked with its evidence.
- [ ] Reply to the operator with the report the execution playbook names.

## Appendix A. Prototype evidence

<Each open question a prototype answered, with the branch, the SHA, and the artifact links. Each question that stays unproven.>

## Appendix B. Alternatives rejected

<Each approach weighed and why it lost.>

## Appendix C. Risks

<Each risk with the PR it lands in and what the owner watches.>

## Appendix D. Links and reading list

<Docs to read before editing. Which PRs get `<plugin-root>/skills/how/SKILL.md` and `<plugin-root>/skills/interrogate/SKILL.md`. The trail per `<plugin-root>/skills/show-me-your-work/SKILL.md`.>
````

**Reply:** the plan path, the PR ids with their dependencies and the review-gated set, what the prototypes proved and what stays unproven, and the check script's output.
