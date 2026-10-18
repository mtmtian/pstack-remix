---
name: setup-pstack
description: Configure shared pstack role and reasoning preferences once for Codex and Claude Code, with optional host-specific model overrides and a separate T3 Code section.
---

Read [the shared runtime contract](../../references/runtime.md) and its selected host adapter first.

# Configure pstack once

Configure only pstack. Do not change global host models, permissions, credentials, or unrelated skills.

In a T3 Code session (the [T3 overlay](../../references/t3-runtime.md) applies), configure the `t3` section. Its entries may be T3 targets `<providerInstanceId>/<modelId>`, checked against `orchestrator_capabilities`: the provider can run child tasks and lists the model. Write them with `update --host t3`, read back with `show --host t3`, and leave `hosts.codex` and `hosts.claude` untouched. Set `reasoning_effort` there too, since a target without it runs at the provider's default effort. Outside T3, change the T3 section only on an explicit request.

For T3, preview proposed choices against the current catalog before writing the live file. Use a temporary config with the same effective policy plus the proposed patch, then run `node <plugin-root>/bin/config.mjs resolve --host t3 --role '<role>' --catalog <catalog.json> --config <temporary-config.json>` for each changed role, or `--panel '<panel>'` for a panel. Resolve the live file again after update. The output preserves exact targets and independent repeated seats, maps effort using each explicit model's actual option, and identifies inherited defaults. Unavailable targets and unsupported explicit effort fail; a model without effort control emits a warning and no effort option. Inherited targets omit all options to preserve the parent's complete settings and warn when requested effort is unsent; choose an explicit model target for independent effort. An xagent entry stays on its CLI path, even if T3 now lists that model, and required external members are not dropped. This is a selection preview, not proof that a worker ran.

For version-following choices, T3 accepts explicit family selectors such as `codex/gpt-sol@latest` and `claudeAgent/claude-opus@latest`. A role can instead contain `{"candidates":["codex/gpt-sol@latest","claudeAgent/claude-opus@latest"]}` with one target per provider. Preview every candidate with `--provider <id>`; default selection prefers the parent provider, then the first configured candidate. These are choices, never fallback attempts. Panels still contain string entries. Use `hardest architect runners` only when the user wants a distinct panel for the hardest designs. The [routing guide](../../docs/t3-model-routing.md) specifies numeric version selection and phase boundaries. Upgrade installed helpers before saving candidate objects; old helpers reject that shape even when reading a native host view.

In Antigravity, run `node <plugin-root>/bin/config.mjs show --host antigravity` and explain the common-policy view. This integration does not enable Antigravity-specific preference writes. Do not run the setup steps below implicitly; shared changes still require an explicit configuration request through a supported update path.

1. Identify the current host from its actual tools and read the effective configuration with `node <plugin-root>/bin/config.mjs show --host <codex|claude>`. Missing configuration means all roles inherit and panels use two independent attempts; setup is optional.
2. For a setup request, run `node <plugin-root>/bin/config.mjs init`. It creates `~/.config/pstack/config.json` only when absent and imports any legacy `~/.codex/pstack/models.json` or `~/.claude/pstack/models.json` into that host's overrides. Existing shared configuration is authoritative. Legacy files remain untouched and are no longer runtime sources.
3. Honor preferences already given. Shared roles and panel entries can use only `inherit-parent`, `auto`, or `xagent:<agent>` (an external agent CLI dispatched through xagent, for example `xagent:grok`), optionally with that CLI's own model as `xagent:<agent>/<model>`, for example `xagent:claude/claude-opus-5-5`; check the model with that CLI, such as `grok models` or `pi --list-models`, before saving it. Any other concrete model goes into the current host's override after checking actual availability and role constraints. Keep reasoning separate. Do not infer IDs from upstream brand names or silently substitute for an unavailable explicit choice. Preserve the other host's choices.
4. Write a small JSON patch containing only the requested `roles`, `panels`, `reasoning_effort`, `reasoning_effort_cap`, `required_panel_members`, `auxiliary_panel_members`, and/or `xagent_effort_caps`. Apply shared preferences with `node <plugin-root>/bin/config.mjs update --input <patch.json>`; add `--host codex`, `--host claude`, or `--host t3` for host-specific overrides. The helper merges per-role changes atomically. A null role/panel or null effort removes that override and restores inheritance from the next layer. Delete the scratch patch after readback, not the evidence. Concurrent edits fail visibly rather than overwriting each other.
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

Role names follow the bundled workflow: the code playbook roles `feature`, `refactoring`, `bug-fix`, `perf-issue`, and `hillclimb`; `hardest tasks` for the hardest changes; `judgment and prose`; `how explorer`, `how explainer`, `why investigators`, `why synthesizer`, `reflect judgment`, and `reflect tooling`; `swarm workers` for swarm fan-out; and `verification workers` for verifier agents, a swarm's verify lanes, and the show-me-your-work handback review. Set `verification workers` per host to a model family other than that host's writers, for example `xagent:claude` under `hosts.codex`; on T3, list candidates from different model families, one per provider. Panels include `arena runners`, `arena cross-judge pool`, `architect runners`, optional `hardest architect runners`, and `interrogate reviewers`. Use the role a workflow actually requests; do not populate unused choices.

Shared `required_panel_members`, for example `["xagent:grok", "xagent:gemini"]`, adds those external agents to every panel and the default panel on both hosts. It is rejected in a host override; `null` removes it.

Shared `auxiliary_panel_members`, for example `["xagent:gemini"]`, marks external panel members whose failure after the retry is a reported gap instead of a blocker. It adds no member to any panel, so list the agent in the panels it should join. It is rejected in a host override; `null` removes it.

Shared `xagent_effort_caps`, for example `{"gemini": "high"}`, sets the highest effort each external agent receives, for a CLI whose model accepts fewer levels than `reasoning_effort` or a raised job asks for. Read the levels from that CLI's model list, such as `agy models`, before saving. It changes only the effort, never the model. It is rejected in a host override; `null` removes it.

Shared `reasoning_effort_cap`, for example `"xhigh"`, is the highest effort any worker receives on any host, so poteto-mode's one-step raise for the hardest work stops there instead of reaching `max`. Propose it when the user wants to bound cost. It changes only the effort, never the model. It is rejected in a host override; `null` removes it.

Multi-party steps are the panels above, `reflect judgment` with `reflect tooling`, and `verification workers`. Upstream gives each of them two model families by default; this fork's `inherit-parent` defaults stay one family until configured. When another vendor's CLI is installed and signed in, propose a cross-vendor layout for them: the host's own model plus the other vendor through `xagent:<agent>` in each panel, and only the other vendor in `arena cross-judge pool`, since arena picks a single judge from it. Mark a supporting vendor auxiliary rather than required when it should not hold up a review. Confirm the proposal with the user before writing it.

For the T3 section, build the same layout from T3 seats. Give each vendor whose models the live catalog lists on a provider that can run child tasks a seat or candidate: `<providerInstanceId>/<family>@latest` for the Claude and GPT families the helper follows, and an exact catalog ID for any other, such as a Gemini or Grok model. Use `xagent:<agent>` only for a vendor the catalog lacks, and pin its model as `xagent:<agent>/<model>` when its family must count as cross-family evidence. A T3 parent can run on either provider, so give `verification workers` candidates of different families and list each family once in `arena cross-judge pool`; resolving with `--checked` picks the other family at run time. Candidates still allow one target per provider, so when one provider routes both families, a candidate role holds only one of them: set the exact target of the family other than your usual parent's, and `--checked` warns when it matches. Confirm this proposal too before writing it.

On Codex and Claude Code, `reasoning_effort` reaches `xagent:` workers and native agent types whose definition sets no effort; a definition that sets its own effort keeps it. Without a value, an external CLI runs at its own default, which may be the user's interactive setting.
