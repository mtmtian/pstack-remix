# T3 task difficulty and model versions

pstack classifies each delegated step before resolving its model. The main conversation does not change models when it invokes pstack.

Use the ordinary code role for an ordinary feature, bug fix, refactor or performance change. Use `hardest tasks` for difficult planning or implementation that still contains hard design, concurrency or algorithmic reasoning. A settled difficult plan does not make every implementation step difficult. The architect workflow can opt into `hardest architect runners`; other panels retain their configured membership.

## Configuration and real calls

This T3 patch permits two families per code role. It does not start two workers:

```json
{
  "roles": {
    "feature": {"candidates": ["codex/gpt-sol@latest", "claudeAgent/claude-opus@latest"]},
    "hardest tasks": {"candidates": ["codex/gpt-astra@latest", "claudeAgent/claude-fable@latest"]}
  },
  "panels": {
    "hardest architect runners": ["claudeAgent/claude-fable@latest", "codex/gpt-astra@latest"]
  },
  "reasoning_effort": "high"
}
```

Save the raw current `orchestrator_capabilities` structured result to `catalog.json`, then resolve:

```sh
node bin/config.mjs resolve --host t3 --role 'hardest tasks' --catalog catalog.json
node bin/config.mjs resolve --host t3 --role 'feature' --catalog catalog.json
node bin/config.mjs resolve --host t3 --role 'feature' --provider claudeAgent --catalog catalog.json
node bin/config.mjs resolve --host t3 --panel 'hardest architect runners' --catalog catalog.json
```

For a Codex parent, the first call selects Astra and the second Sol. For a Claude parent, they select Fable and Opus. If the parent provider is not a candidate, the first configured candidate is the explicit default. The third call selects the configured Claude candidate regardless of the parent; the brief must explain why that model perspective is useful. An unlisted provider is an error. If a selected provider or model cannot run, the command fails rather than trying the other candidate.

Each result includes one role worker or all ordered panel seats. `selection.strategy` records how a candidate was chosen. `workers[].entry` is the configured policy, while `workers[].target` is the exact dispatch argument, including the model's supported effort option. Preserve that output with the task receipt. Required xagent panel members remain present.

## Version upgrades

`@latest` is an explicit opt-in to follow canonical releases of one family within one provider. With Opus 5.5 and 5.6 in that provider's catalog, `claude-opus@latest` resolves to 5.6. Numeric ordering also makes 5.10 newer than 5.9. GPT version ordering handles 6.1, 6.2 and 7 in the same way.

Recognized IDs contain a major and optional minor version, each one to three digits. Previews, dated snapshots, context suffixes, routed aliases and other families are excluded. Exact IDs such as `claude-opus-5-5` remain pinned. A missing family, ambiguous newest release or unsupported requested effort is an error. It never downgrades to an older release or another provider. Availability in the catalog does not prove authentication or behavior of a new release.

Resolve against a fresh catalog once per task and preserve that task's concrete IDs for all rounds. A future task sees a newer release when T3 lists it. Updating T3/provider catalogs remains the host's responsibility. The resolver makes no network call and maintains no second model registry. A changed naming scheme requires an explicit resolver change or exact target.

## Direct Claude Code

Direct Claude Code uses the same task classification guidance but reads `hosts.claude`, not `hosts.t3`. Missing role choices inherit the main CC conversation; `agents/poteto-agent.md` uses `model: inherit`. A main conversation on Opus therefore sends inherited native roles to Opus; one on Fable sends them to Fable. Effort can vary only when the native Agent schema supports it. Cross-provider GPT work needs the configured xagent bridge rather than a GPT ID passed as a native Claude model.

Changing T3 policy does not populate native roles. Upgrade both local plugin packages before storing candidate objects, and start a fresh session to discover the new runtime. Older cached helpers cannot validate the new candidate object shape; do not edit their generated caches in place.

## Verification

`node --test scripts/config.test.mjs scripts/t3-targets.test.mjs` covers candidate selection, separate hard/ordinary roles, numeric upgrades, exact pins, invalid choices, non-fallback failures, native view isolation and preserved panel seats. Synthetic 5.6/5.10/6.2 catalogs test future-version handling; they do not claim those releases are currently available. Use the [live verification procedure](./t3-verification.md) for actual provider execution.
