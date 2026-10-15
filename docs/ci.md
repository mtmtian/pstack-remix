# Run the CI checks locally

Use POSIX, Git, Node 22.18 or newer, Python 3.9 or newer, and GNU `timeout` with `-k` support. Build checks also require the Bun version in [`.bun-version`](../.bun-version).

On macOS, make the coreutils commands available in the current shell before running runtime checks:

```sh
brew install coreutils
export PATH="$(brew --prefix coreutils)/libexec/gnubin:$PATH"
```

Install the locked development dependencies once, then run the same checks as GitHub Actions:

```sh
(cd skills/poteto-mode/scripts && bun install --frozen-lockfile)
bash scripts/check.sh
```

For a narrower check, run either group:

```sh
bash scripts/check.sh runtime
bash scripts/check.sh build
```

`runtime` needs no Bun, vendor CLI, login, or shared pstack configuration. It starts with the [fork guards](#fork-guards), then exercises config resolution, the pi guard, verdict parsing, xagent receipts, cancellation, timeouts, and host verification with vendor stand-ins. It also copies the shipped Node bundles into a temporary directory without dependencies and checks orchestrator persistence and watcher argument handling.

`build` runs strict type checking and the Bun tests for both `orch` and `watch-pr`. It tests the real builder, then rebuilds into a temporary directory and compares the result with the working-tree artifacts. It fails if source hashes, bundles, or the bundled license differ or are missing, or a bundle loses execute permission. Build inputs exclude `node_modules`, logs, `.DS_Store`, and TypeScript build caches. It never repairs artifacts during a check. Checks stop at the first failure and print the failing command.

## Fork guards

`node scripts/check-fork.mjs` checks the shipped tree statically, so an upstream sync cannot silently undo a decision recorded in [the adaptation guide](../ADAPTATION.md). The `runtime` suite runs it first. It prints each problem with its file and line, and fails if any remain.

| Guard | Fails when |
| --- | --- |
| Denylist | `skills/`, `references/`, or `agents/` names a Cursor-only primitive this fork replaced: `pstack-models.mdc`, a fixed `/loop 1h` interval, `control-ui` or `control-cli`, Cursor cloud agents, `~/.cursor` or `.cursor/` paths, `agent-transcripts`, the `Task` tool and its fields (`subagent_type`, `readonly`, `run_in_background`, `environment`), `disable-model-invocation`, an effort- or fast-suffixed model slug, `/visualize`, or Custom Modes |
| Skills | a skill directory lacks `SKILL.md`, a frontmatter `name` differs from its directory or agent file name, a `description` is empty, or a `SKILL.md` has no link to `references/runtime.md` |
| Links | a Markdown link outside code points at a missing file or leaves the repository |
| Manifests | a manifest is not valid JSON or loses its name (`pstack`, or `pstack-codex` for Codex), or the root `plugin.json` references `agent-plugins.org`, whose `$schema` makes Codex truncate each skill to 8,000 bytes |

When the denylist fires after a sync, rewrite the sentence the way the adaptation guide records for that sync instead of swapping tokens. A file that names a pattern on purpose, such as an adapter listing the fields it forbids, goes in that rule's `allow` list in `scripts/check-fork.mjs`; `skills/poteto-help/SKILL.md` is the one allowed `disable-model-invocation`. An allowed file that stops matching fails as stale, so an allowance cannot outlive the sentence it excuses. `scripts/check-fork.test.mjs` plants each violation in a copy of the tree and checks that it is reported.

## Update the distributed bundles

After changing helper sources, their build dependencies, or the builder, regenerate the artifacts with the pinned Bun version:

```sh
python3 scripts/build-runtime.py
bash scripts/check.sh
```

Include the changed `bin/orch.mjs`, `bin/watch-pr.mjs`, `bin/source-hashes.json`, and any changed `bin/COMMANDER-LICENSE.txt` in the patch. The checker compares against the working tree, so it works before committing. An incorrect Bun version fails with the expected version instead of producing an unexplained bundle diff.

To check only artifact freshness:

```sh
python3 scripts/build-runtime.py --check
```

## GitHub checks

The [workflow](../.github/workflows/ci.yml) runs on every pull request, pushes to `main`, and manual dispatch. It has no path filters, so a required check cannot remain pending because only documentation changed.

| Check | Environment | Purpose |
| --- | --- | --- |
| Runtime | Ubuntu 24.04, Node 22.18.0, Python 3.9 | Exercise the documented runtime floor |
| Runtime | macOS 15, Node 24, Python 3.14 | Exercise the maintained host platform and current runtimes |
| Build and types | Ubuntu 24.04, Node 24, Python 3.14, pinned Bun | Check TypeScript, source behavior, reproducibility, and artifact freshness |

Each job has a ten-minute limit. A newer run on the same PR or ref cancels the older run. Jobs use read-only repository permissions, discard checkout credentials, and pin actions to full commit SHAs, following [GitHub's secure-use guidance](https://docs.github.com/en/actions/reference/security/secure-use). They run on GitHub-hosted runners and need no custom secrets.

The macOS runtime job installs coreutils. Ubuntu already supplies GNU `timeout`.

After the first successful GitHub run, select all three check names in branch protection if they must block merges. Adding the workflow does not configure branch protection.

## Checks that still require a host

PR CI does not call real model vendors or run a live host workflow. For changes to xagent or cross-agent routing, run the separately authorized [vendor and dual-host checks](../ADAPTATION.md#verification). Keep their receipts separate from offline test results.

Plugin discovery and Skill behavior still require the package review described in [the adaptation guide](../ADAPTATION.md#verification); the fork guards check only text, frontmatter, links, and manifests. This workflow does not establish host discovery, model behavior, deployment, or restart persistence.
