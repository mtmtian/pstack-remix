# xagent maintenance

Read when changing [xagent](../SKILL.md) or running disposable Claude checks.

## XAGENT_EPHEMERAL

Claude workers keep their normal session persistence by default. For disposable checks, set `XAGENT_EPHEMERAL=1` to pass `--no-session-persistence`; those Claude sessions cannot be resumed. Both `scripts/xagent-e2e.sh` and `scripts/pstack-host-e2e.py` enable it for their hosts and workers automatically. Run evidence and receipts are still written to the output directory.

## Checks

- `scripts/xagent-classify.test.sh`, `python3 scripts/xagent.test.py` and `node --test scripts/xagent-pi-guard.test.mjs`: offline, including deterministic read-only violations and unresponsive/cancelled processes.
- `scripts/xagent-e2e.sh [run-dir]`: each agent it runs in both modes, each CLI accepting `--effort` and any model pinned in `XAGENT_E2E_MODELS`, allowlist denials, the agy mirror, nested refusal, timeout, and Codex as host. By default it runs claude (when logged in), codex, gemini and pi; grok runs only when listed in `XAGENT_E2E_AGENTS` or, while claude is logged out, when `XAGENT_E2E_REVIEWER=grok` makes it the codex host's reviewer (with claude logged in the reviewer is claude). A run whose `XAGENT_E2E_AGENTS` leaves out one of the default vendors still calls codex, gemini and pi in its fixed cases; record it as partial evidence that names the vendors left out.
