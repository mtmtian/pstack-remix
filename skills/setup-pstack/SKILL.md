---
name: setup-pstack
description: Configure shared pstack role and reasoning preferences once for Codex and Claude Code, with optional host-specific model overrides and a separate T3 Code section.
---

Read [the shared runtime contract](../../references/runtime.md) and its selected host adapter first.

# Configure pstack once

Configure only pstack. Do not change global host models, permissions, credentials, or unrelated skills.

In a T3 Code session (the [T3 overlay](../../references/t3-runtime.md) applies), configure the `t3` section. Its entries may be T3 targets `<providerInstanceId>/<modelId>`, checked against `orchestrator_capabilities`: the provider can run child tasks and lists the model. Write them with `update --host t3`, read back with `show --host t3`, and leave `hosts.codex` and `hosts.claude` untouched. Set `reasoning_effort` there too, since a target without it runs at the provider's default effort. Outside T3, change the T3 section only on an explicit request.

For T3, preview proposed choices against the current catalog before writing the live file. Use a temporary config with the same effective policy plus the proposed patch, then run `node <plugin-root>/bin/config.mjs resolve --host t3 --role '<role>' --catalog <catalog.json> --config <temporary-config.json>` for each changed role, or `--panel '<panel>'` for a panel. Resolve the live file again after update. The output preserves exact targets and independent repeated seats, maps effort using each model's actual option, and identifies inherited defaults. Unavailable targets and unsupported explicit effort fail; a model without effort control emits a warning and no effort option. An xagent entry stays on its CLI path, even if T3 now lists that model, and required external members are not dropped. This is a selection preview, not proof that a worker ran.

For version-following choices, T3 accepts explicit family selectors such as `codex/gpt-sol@latest` and `claudeAgent/claude-opus@latest`. A role can instead contain `{"candidates":["codex/gpt-sol@latest","claudeAgent/claude-opus@latest"]}` with one target per provider. Preview every candidate with `--provider <id>`; default selection prefers the parent provider, then the first configured candidate. These are choices, never fallback attempts. Panels still contain string entries. Use `hardest architect runners` only when the user wants a distinct panel for the hardest designs. The [routing guide](../../docs/t3-model-routing.md) specifies numeric version selection and phase boundaries. Upgrade installed helpers before saving candidate objects; old helpers reject that shape even when reading a native host view.

In Antigravity, run `node <plugin-root>/bin/config.mjs show --host antigravity` and explain the common-policy view. This integration does not enable Antigravity-specific preference writes. Do not run the setup steps below implicitly; shared changes still require an explicit configuration request through a supported update path.

1. Identify the current host from its actual tools and read the effective configuration with `node <plugin-root>/bin/config.mjs show --host <codex|claude>`. Missing configuration means all roles inherit and panels use two independent attempts; setup is optional.
2. For a setup request, run `node <plugin-root>/bin/config.mjs init`. It creates `~/.config/pstack/config.json` only when absent and imports any legacy `~/.codex/pstack/models.json` or `~/.claude/pstack/models.json` into that host's overrides. Existing shared configuration is authoritative. Legacy files remain untouched and are no longer runtime sources.
3. Honor preferences already given. Shared roles and panel entries can use only `inherit-parent`, `auto`, or `xagent:<agent>` (an external agent CLI dispatched through xagent, for example `xagent:grok`), optionally with that CLI's own model as `xagent:<agent>/<model>`, for example `xagent:claude/claude-opus-5-5`; check the model with that CLI, such as `grok models` or `pi --list-models`, before saving it. Any other concrete model goes into the current host's override after checking actual availability and role constraints. Keep reasoning separate. Do not infer IDs from upstream brand names or silently substitute for an unavailable explicit choice. Preserve the other host's choices.
4. Write a small JSON patch containing only the requested `roles`, `panels`, `reasoning_effort`, and/or `required_panel_members`. Apply shared preferences with `node <plugin-root>/bin/config.mjs update --input <patch.json>`; add `--host codex`, `--host claude`, or `--host t3` for host-specific overrides. The helper merges per-role changes atomically. A null role/panel or null effort removes that override and restores inheritance from the next layer. Delete the scratch patch after readback, not the evidence. Concurrent edits fail visibly rather than overwriting each other.
5. Read back both hosts with `show --host codex` and `show --host claude`, plus `show --host t3` when a T3 section exists. Report the shared path and effective choices. Validation of JSON/model names is not proof of model execution. Workers inherit the resolved policy from the parent; do not configure each worker separately.
6. Inspect the current project's existing verify skill or harness. If neither exists, mention `create-verification-skill` once; generate and exercise one only when requested.

Example shared patch, usable on both hosts:

```json
{
  "roles": {"feature": "inherit-parent", "how explorer": "inherit-parent"},
  "panels": {"interrogate reviewers": ["inherit-parent", "inherit-parent"]},
  "reasoning_effort": "high"
}
```

Role names follow the bundled workflow: the code playbook roles `feature`, `refactoring`, `bug-fix`, `perf-issue`, and `hillclimb`; `hardest tasks` for the hardest changes; `judgment and prose`; `how explorer`, `how explainer`, `why investigators`, `why synthesizer`, `reflect judgment`, and `reflect tooling`; and `swarm workers`, which verification workers also read. Panels include `arena runners`, `arena cross-judge pool`, `architect runners`, optional `hardest architect runners`, and `interrogate reviewers`. Use the role a workflow actually requests; do not populate unused choices.

Shared `required_panel_members`, for example `["xagent:grok", "xagent:gemini"]`, adds those external agents to every panel and the default panel on both hosts. It is rejected in a host override; `null` removes it.
