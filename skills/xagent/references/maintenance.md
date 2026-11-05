# xagent maintenance

Read when changing [xagent](../SKILL.md) or running disposable Claude checks.

## XAGENT_EPHEMERAL

Claude workers keep their normal session persistence by default. For disposable checks, set `XAGENT_EPHEMERAL=1` to pass `--no-session-persistence`; those Claude sessions cannot be resumed. Both `scripts/xagent-e2e.sh` and `scripts/pstack-host-e2e.py` enable it for their hosts and workers automatically. Run evidence and receipts are still written to the output directory.

## Checks

- `scripts/xagent-classify.test.sh`, `python3 scripts/xagent.test.py` and `node --test scripts/xagent-pi-guard.test.mjs`: offline, including deterministic read-only violations and unresponsive/cancelled processes.
- `scripts/xagent-e2e.sh [run-dir]`: every agent in both modes, each CLI accepting `--effort` and any model pinned in `XAGENT_E2E_MODELS`, allowlist denials, the agy mirror, nested refusal, timeout, and Codex as host. Calls every vendor by default. A run with `XAGENT_E2E_AGENTS` covers only the listed vendors in both modes, while its fixed cases still call codex, gemini and pi; record it as partial evidence that names the vendors left out.
