# Shared pstack adaptation

Upstream pstack 0.15.5 at `12d587dfb20741cafc376c42c696c5f6e2a64487`, synced 2026-09-25 from 0.15.3 (`b42effe0`). MIT attribution is preserved.

## Maintained source

The repository `mtmtian/pstack-remix` is maintained as one checkout per machine for both hosts. `.codex-plugin/plugin.json` preserves the installed Codex name; `.claude-plugin/plugin.json` exposes the Claude name `pstack`. The repository includes native marketplace manifests for both hosts, named `pstack-local`. Existing Codex `personal` registrations may keep pointing at the same checkout. Both consume the same 48 skills, 23 playbooks, 2 agent files, and runtime helpers. Host caches are generated installation artifacts, never edit targets.

Shared preferences live at `~/.config/pstack/config.json`. `bin/config.mjs` supplies read-only resolution, idempotent initialization/legacy import, host-scoped updates, null-to-remove overrides, validation, locking, and atomic writes. A concrete model ID cannot be stored in the common policy. An `xagent:<agent>` entry can, because `bin/xagent` dispatches it to the named local agent CLI the same way from either host. The `xagent` skill, its allowlist, and the pi guard are local additions with no upstream counterpart; `scripts/xagent-e2e.sh` is their behavioral test. Actual model/effort availability is still checked by each running host. No global host model or permission setting is changed by setup.

`references/runtime.md` holds the shared contract. The Codex and Claude adapters hold only native tool and goal differences. Every skill reads the shared contract; parent agents relay the same resolved policy to workers. Canonical project skills remain in `.agents/skills`, with individual non-overwriting `.claude/skills` links for discovery. Existing projects are not rewritten by installation.

Benny remains dormant. Its copied runtime entry discovers this shared contract instead of maintaining a duplicated adapter. Installing the package does not arm messages, remote writes, webhooks, goals, or scheduled runs.

## Upstream behavior retained

The 0.15.3 base retains code-ready review rounds, exact SHA/method evidence, child ledgers, merge-prep CI checks, Shipping lane reuse rules, and append-only logging. Adaptations preserve real completion evidence, risk-sized lanes, current runtime model names, explicit external-write authorization, and observed scheduling capabilities.

The 0.15.5 sync (upstream #419, #422) takes the instruction trims (principles, tdd, figure-it-out, interrogate reviewer references, reflect reviewer references, delegate-review lines in feature/bug-fix/refactoring), multi-run `start` rows and append-only audit in show-me-your-work, and the Autopilot owner babysit/`--force-with-lease` rebase rules in babysit, opening-a-pr, and autopilot-full (kept under explicit push authorization). It skips the `pstack-models.mdc` role-line wording, the fall-back-to-default-slug rule, retired-role cleanup in setup, and the fixed "Ten lanes on `<model>`" check in multi-phase-plan/check-plan, because this fork resolves models through `config.json` with inherited defaults, forbids silent substitution, and sizes live lanes by risk.

## Verification

Run these offline checks for configuration, guard, receipt, process and host-acceptance behavior:

```sh
node --test scripts/config.test.mjs scripts/xagent-pi-guard.test.mjs
bash scripts/xagent-classify.test.sh
python3 -B scripts/xagent.test.py
python3 -B scripts/xagent-e2e-verify.test.py
python3 -B scripts/e2e-process.test.py
python3 -B scripts/pstack-host-e2e.test.py
```

The CLI tests use real Git checkouts and subprocesses with vendor stand-ins, including staged/committed read-only violations, misleading verdicts, timeout and cancellation. Vendor acceptance pins the fixture's test contents and checks the worker's successful test receipt against its final source before independently rerunning it. Importing the test, rewriting it, or reusing a receipt from older code cannot satisfy that gate.

Run `scripts/xagent-e2e.sh` after changing `bin/xagent*` or upgrading an agent CLI; it calls every vendor. Run `python3 scripts/pstack-host-e2e.py <new-run-dir>` for actual Claude and Codex hosts executing swarm then interrogate through their current shared policy on synthetic fixtures. It records source hashes, policy, worker receipts and independent tests, and checks that the parent verified the final source and that each configured reviewer saw it in a separate worktree. It expects external xagent entries for swarm and the review panel and never changes preferences. Both live harnesses use `timeout` with a kill-after limit for the outer host process; host workflows default to 1200 seconds, configurable with `--host-timeout`. Verification commands use `scripts/e2e-process.py` with a 30-second default deadline, process-group termination and bounded output collection; the host harness exposes `--check-timeout`. A verification timeout remains a failed check with logs and exit code 124.

Validate both manifests, all SKILL.md frontmatter and local links. Use a fresh Codex app-server skills/list and Claude `plugin details` to verify inventory; a manifest validator alone is not a discovery or behavioral test.

The source `orch`/`watch-pr` helpers and their bundled Node code are unchanged by this shared-host adaptation. Rebuild with `python3 scripts/build-runtime.py` only when those sources change, using their development dependencies. Node runtime helpers never download dependencies.

See the task's shared-installation report for actual dated commands/results and any remaining gaps. No overnight, real PR queue, remote runner, or Slack workflow is implied by local package validation.
