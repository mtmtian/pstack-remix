# xagent maintenance and agent notes

Details from [the xagent skill](../SKILL.md) that only maintaining xagent or dispatching pi or grok needs.

## pi write guard

The pi write guard accepts plain relative or absolute paths, including paths through existing internal symlinks. Use plain paths instead of `@`, `~`, URI or Unicode-space aliases that pi would normalize. Bash checks accept a limited non-expanding command syntax with ordinary quoted arguments, and reject output redirection and `--output` options. Tests/build scripts still execute project code, so this is an accident guard, not a sandbox.

## grok read-only sandbox

Grok's built-in read-only sandbox refuses to start while `/var/run/docker.sock` is a symlink, so its readers can still write the workdir.

## One-time setup and the agy allowlist

claude needs `claude auth login` once. The agy allowlist mirrors `bin/xagent-allowed-commands`; `scripts/xagent-e2e.sh` fails on drift.

## XAGENT_EPHEMERAL

Claude workers keep their normal session persistence by default. For disposable checks, set `XAGENT_EPHEMERAL=1` to pass `--no-session-persistence`; those Claude sessions cannot be resumed. Both `scripts/xagent-e2e.sh` and `scripts/pstack-host-e2e.py` enable it for their hosts and workers automatically. Run evidence and receipts are still written to the output directory.

## Checks

- `scripts/xagent-classify.test.sh`, `python3 scripts/xagent.test.py` and `node --test scripts/xagent-pi-guard.test.mjs`: offline, including deterministic read-only violations and unresponsive/cancelled processes.
- `scripts/xagent-e2e.sh [run-dir]`: every agent in both modes, each CLI accepting `--effort` and any model pinned in `XAGENT_E2E_MODELS`, allowlist denials, the agy mirror, nested refusal, timeout, and Codex as host. Calls every vendor by default. A run with `XAGENT_E2E_AGENTS` covers only the listed vendors in both modes, while its fixed cases still call codex, gemini and pi; record it as partial evidence that names the vendors left out.
