# Set up pstack once

Both hosts install the same source tree. The shared configuration lives outside their caches at `~/.config/pstack/config.json`. Default roles inherit the current conversation, so no model setup is required per host or worker.

## Clone on a new machine

Prerequisites: Git, Node.js 22 or newer, and the host CLI you want to use. The repository is private: authenticate GitHub CLI with an account that can read `mtmtian/pstack-codex`. Bun is needed only when rebuilding or testing the TypeScript helpers; the checked-in Node bundles run without installing dependencies.

```sh
mkdir -p "$HOME/plugins"
gh repo clone mtmtian/pstack-codex "$HOME/plugins/pstack-codex"
cd "$HOME/plugins/pstack-codex"
node --test scripts/config.test.mjs
```

The checkout may live elsewhere. Run the following commands from its root. Register only the hosts installed on that machine.

## Install

Codex:

```sh
codex plugin marketplace add "$PWD"
codex plugin add pstack-codex@pstack-local
```

Claude Code:

```sh
claude plugin marketplace add "$PWD"
claude plugin install pstack@pstack-local --scope user
```

For development without installation:

```sh
claude --plugin-dir "$PWD"
```

Do not register a second source copy for Claude. A host's installed cache is generated, not another maintained source tree.

If Codex already uses `pstack-codex@personal` and its marketplace points to this checkout, keep that registration and use `codex plugin add pstack-codex@personal` when refreshing. Do not install the same plugin under both marketplaces. If your CLI does not expose these marketplace commands, update the host before installation.

## Optional preferences

Use `$pstack-codex:setup-pstack` in Codex or `/pstack:setup-pstack` in Claude. Both read [the same setup skill](../../skills/setup-pstack/SKILL.md). Initialization imports legacy host preferences if present and leaves the original files untouched. Existing shared configuration takes precedence.

Read the effective choices without changing them:

```sh
node bin/config.mjs show --host codex
node bin/config.mjs show --host claude
```

A missing role inherits its parent. Shared panel lists set the number of independent attempts. Concrete model IDs are stored only under that host's overrides and must be available in its running session. Removing an override restores the next layer's value. Rerunning setup preserves choices unless you ask to change them. Configuration changes apply to the next pstack task; already-running workers keep their parent's policy snapshot.

The repository syncs code and prompts, not `~/.config/pstack/config.json`, credentials, conversation logs, plugin caches, or wiki data. Each new machine starts with inherited model defaults; configure its available models through setup if needed. Keep llm-wiki-compiler in its own repository: the modules have separate release and runtime state, and neither requires the other to install.

## Run a task

- Codex: `$pstack-codex:poteto-mode fix this CLI bug; reproduce and verify it.`
- Claude Code: `/pstack:poteto-mode fix this CLI bug; reproduce and verify it.`

Both use the same 23 playbooks. Generated verify skills keep one canonical directory with a non-overwriting Claude discovery link as described in [the runtime](../../references/runtime.md). The host adapter handles delegation, goal state, and scheduling; it does not grant new permissions.

## Sync another machine

From a clean checkout, pull published changes and refresh the hosts you use:

```sh
git pull --ff-only
node --test scripts/config.test.mjs
codex plugin add pstack-codex@pstack-local
claude plugin marketplace update pstack-local
claude plugin update pstack@pstack-local
```

Use `pstack-codex@personal` instead for an existing personal-marketplace installation. Resolve local edits before pulling; do not reset them away. Use a fresh Codex task and a fresh Claude session for the final discovery check. Verify that `poteto-mode` and `setup-pstack` appear and that each host resolves the shared preferences. Pulling source alone does not refresh an already-running session.

## Maintain and publish

Edit this checkout, preserve the host adapters, and bump both plugin manifest versions together when publishing runtime or skill changes. Run `node --test scripts/config.test.mjs scripts/xagent-pi-guard.test.mjs` and `scripts/xagent-classify.test.sh` (plus `scripts/xagent-e2e.sh` when `bin/xagent*` changes), validate the manifests, and check any changed helper scripts before committing and pushing. When TypeScript helper sources change, install their pinned dependencies with `bun install --frozen-lockfile` in `skills/poteto-mode/scripts`, run `bun test orch watch-pr` and `bun run typecheck` there, then rebuild from the repository root with `python3 scripts/build-runtime.py`.

Run `node scripts/check-upstream.mjs` for a read-only upstream comparison. Review changes before applying them; it never overwrites adapters or model preferences. Retain the MIT license and update `UPSTREAM.json` when accepting a new upstream version.

Next: [Route work through poteto-mode](./02-poteto-mode.md).
