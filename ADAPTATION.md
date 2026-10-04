# Shared pstack adaptation

Upstream pstack 0.15.9 at `e43c7ee26e0038c6c1fa8380dd34ce86ff94cb2a`, synced 2026-10-04 from 0.15.5 (`12d587df`), itself synced 2026-09-25 from 0.15.3 (`b42effe0`). MIT attribution is preserved.

## Maintained source

The repository `mtmtian/pstack-remix` is maintained as one checkout per machine for both hosts. `.codex-plugin/plugin.json` preserves the installed Codex name; `.claude-plugin/plugin.json` exposes the Claude name `pstack`. The repository includes native marketplace manifests for both hosts, named `pstack-local`. Existing Codex `personal` registrations may keep pointing at the same checkout. Both consume the same 51 skills, 23 playbooks, 2 agent files, and runtime helpers. Host caches are generated installation artifacts, never edit targets.

Shared preferences live at `~/.config/pstack/config.json`. `bin/config.mjs` supplies read-only resolution, idempotent initialization/legacy import, host-scoped updates, null-to-remove overrides, validation, locking, and atomic writes. A concrete model ID cannot be stored in the common policy. An `xagent:<agent>` entry can, because `bin/xagent` dispatches it to the named local agent CLI the same way from either host. The `xagent` skill, its allowlist, and the pi guard are local additions with no upstream counterpart; `scripts/xagent-e2e.sh` is their behavioral test. Replays in `create-verification-skill` and `maintain-verification-skill` are also local additions, adapted from tester.army `e2e`'s verified replay cache: a replay is a test script written only after a passing check, it runs before any manual drive, and a stale replay is reported instead of letting an agent redo it. Keep them when syncing those skills. Actual model/effort availability is still checked by each running host. No global host model or permission setting is changed by setup.

`references/runtime.md` holds the shared contract. The Codex and Claude adapters hold only native tool and goal differences. Every skill reads the shared contract; parent agents relay the same resolved policy to workers. Canonical project skills remain in `.agents/skills`, with individual non-overwriting `.claude/skills` links for discovery. Existing projects are not rewritten by installation.

Benny remains dormant. Its copied runtime entry discovers this shared contract instead of maintaining a duplicated adapter. Installing the package does not arm messages, remote writes, webhooks, goals, or scheduled runs.

## Upstream behavior retained

The 0.15.3 base retains code-ready review rounds, exact SHA/method evidence, child ledgers, merge-prep CI checks, Shipping lane reuse rules, and append-only logging. Adaptations preserve real completion evidence, risk-sized lanes, current runtime model names, explicit external-write authorization, and observed scheduling capabilities.

The 0.15.5 sync (upstream #419, #422) takes the instruction trims (principles, tdd, figure-it-out, interrogate reviewer references, reflect reviewer references, delegate-review lines in feature/bug-fix/refactoring), multi-run `start` rows and append-only audit in show-me-your-work, and the Autopilot owner babysit/`--force-with-lease` rebase rules in babysit, opening-a-pr, and autopilot-full (kept under explicit push authorization). It skips the `pstack-models.mdc` role-line wording, the fall-back-to-default-slug rule, retired-role cleanup in setup, and the fixed "Ten lanes on `<model>`" check in multi-phase-plan/check-plan, because this fork resolves models through `config.json` with inherited defaults, forbids silent substitution, and sizes live lanes by risk.

The 0.15.9 sync (upstream 0.15.6 and #494, #495, #496) adds the `correct`, `benchmark-checklist`, and `principle-explain-the-number` skills with the local frontmatter and runtime-contract line, the agent-resistant design red flags in architect, the fresh-workers-by-default rule in poteto-mode's Subagents section, the benchmark routing in poteto-mode, hillclimb, and perf-issue, the performance mantras that replace perf-issue's strategy families, the merge-tree and CI-path checks plus fresh-owner handoff in autopilot-full step 5, the push-after-every-unit rule and hourly audit cadence in both autopilot playbooks, the shorter PR body format and the built-in PR tool rule in opening-a-pr, the schema-first cast guidance in typescript-best-practices, the respawn wording in swarm, and the removal of the fetched-source lines in technical-writing. It keeps this fork's wording where upstream's is Cursor-specific: the optional native host goal and observable scheduler instead of `/goal` and `/loop 1h`, `<resolved trunk ref>` instead of `origin/main`, `inherit-parent` instead of a concrete perf-issue model, the authorization-gated PR readiness rule instead of "ready, never draft", the local `check-plan.mjs` markers, and the local `poteto-agent.md` frontmatter.

## Verification

Run the offline runtime checks for configuration, guard, receipt, process and host-acceptance behavior:

```sh
bash scripts/check.sh runtime
```

For all CI checks, including strict TypeScript checks, Bun tests and reproducible bundle verification, follow [Run the CI checks locally](./docs/ci.md). The same entrypoint runs in GitHub Actions without vendor credentials.

The CLI tests use real Git checkouts and subprocesses with vendor stand-ins, including staged/committed read-only violations, misleading verdicts, timeout and cancellation. Vendor acceptance pins the fixture's test contents and checks the worker's successful test receipt against its final source before independently rerunning it. The shared verification runner gives each command a fresh Python bytecode-cache prefix and disables cache writes; `-B` alone can still load stale bytecode after an equal-size edit in the same second. A worker receipt is not sufficient without that independent run. Importing the test, rewriting it, or reusing a receipt from older code cannot satisfy the full acceptance gate.

Run `scripts/xagent-e2e.sh` after changing `bin/xagent*` or upgrading an agent CLI; it calls every vendor. Run `python3 scripts/pstack-host-e2e.py <new-run-dir>` for actual Claude and Codex hosts executing swarm then interrogate through their current shared policy on synthetic fixtures. It records source hashes, policy, worker receipts and independent tests, and checks that the parent verified the final source and that each configured reviewer saw it in a separate worktree. It expects external xagent entries for swarm and the review panel and never changes preferences. Both live harnesses use `timeout` with a kill-after limit for the outer host process; host workflows default to 1200 seconds, configurable with `--host-timeout`. Verification commands use `scripts/e2e-process.py` with a 30-second default deadline, process-group termination and bounded output collection; the host harness exposes `--check-timeout`. A verification timeout remains a failed check with logs and exit code 124.

Validate both manifests, all SKILL.md frontmatter and local links. Use a fresh Codex app-server skills/list and Claude `plugin details` to verify inventory; a manifest validator alone is not a discovery or behavioral test.

Rebuild the `orch` and `watch-pr` bundles with `python3 scripts/build-runtime.py` when their sources, dependencies or builder change. Use the Bun version in `.bun-version` and locked development dependencies. `python3 scripts/build-runtime.py --check` compares a temporary build with the working tree without writing artifacts. Node runtime helpers never download dependencies.

See the task's shared-installation report for actual dated commands/results and any remaining gaps. No overnight, real PR queue, remote runner, or Slack workflow is implied by local package validation.
