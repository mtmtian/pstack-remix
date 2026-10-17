// Turn a resolved pstack policy and one live T3 catalog into dispatch arguments.
// This module neither launches tasks nor reads or changes configuration.
const EFFORT_IDS = new Set(["effort", "reasoningEffort", "thinking"]);

function unique(rows, predicate, label) {
  const matches = Array.isArray(rows) ? rows.filter(predicate) : [];
  if (matches.length !== 1) {
    throw new Error(`${label}: ${matches.length ? "ambiguous in" : "not in"} T3 catalog`);
  }
  return matches[0];
}

function compareVersion(a, b) {
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    const left = a[i] ?? 0n;
    const right = b[i] ?? 0n;
    if (left !== right) return left > right ? 1 : -1;
  }
  return 0;
}

function latestModel(models, selector, label) {
  const family = selector.slice(0, -"@latest".length);
  let pattern;
  if (/^gpt-(sol|astra|luna)$/.test(family)) {
    pattern = new RegExp(`^gpt-(\\d{1,3}(?:\\.\\d{1,3})?)-${family.slice(4)}$`);
  } else if (/^claude-(opus|fable|sonnet|haiku)$/.test(family)) {
    pattern = new RegExp(`^${family}-(\\d{1,3}(?:-\\d{1,3})?)$`);
  } else {
    throw new Error(`${label}: unsupported @latest family; use a canonical family or an exact model ID`);
  }
  const matches = (Array.isArray(models) ? models : []).flatMap(model => {
    const match = typeof model?.id === "string" && pattern.exec(model.id);
    return match ? [{ model, version: match[1].split(/[.-]/).map(BigInt) }] : [];
  });
  if (!matches.length) throw new Error(`${label}: no canonical release for this family in T3 catalog`);
  matches.sort((a, b) => compareVersion(b.version, a.version));
  const latest = matches[0];
  if (matches.length > 1 && compareVersion(latest.version, matches[1].version) === 0) {
    throw new Error(`${label}: ambiguous latest release in T3 catalog`);
  }
  return latest.model;
}

function modelFor(catalog, providerId, modelId, allowLatest) {
  const label = `${providerId}/${modelId}`;
  const provider = unique(catalog.providers, p => p?.providerInstanceId === providerId, label);
  const constraints = (provider.constraints ?? []).join("; ");
  if (provider.canRunChildTask !== true) {
    throw new Error(`${label}: cannot run child tasks${constraints ? `: ${constraints}` : ""}`);
  }
  if (providerId !== catalog.inheritedProviderInstanceId && provider.canRunCrossProviderChildTask !== true) {
    throw new Error(`${label}: cross-provider child tasks are unavailable${constraints ? `: ${constraints}` : ""}`);
  }
  return allowLatest && modelId.endsWith("@latest")
    ? latestModel(provider.models, modelId, label)
    : unique(provider.models, m => m?.id === modelId, label);
}

function effortFor(model, requested, label) {
  const result = { requested, sent: null, option: null };
  if (requested === null) return { effort: result, warnings: [] };
  const controls = (model.options ?? []).filter(o => o?.type === "select" && EFFORT_IDS.has(o.id));
  if (controls.length > 1) throw new Error(`${label}: ambiguous effort controls in T3 catalog`);
  if (!controls.length) {
    return { effort: result, warnings: [`${label}: no effort control; requested ${requested} is not sent, so the runtime default or inherited setting applies`] };
  }
  const control = controls[0];
  const choices = (control.options ?? []).map(o => o.id);
  if (!choices.includes(requested)) {
    throw new Error(`${label}: effort ${requested} is not offered by ${control.id}; choose ${choices.join(", ") || "a supported value"}`);
  }
  return { effort: { requested, sent: requested, option: control.id }, warnings: [] };
}

function workerFor(entry, catalog, requestedEffort) {
  if (entry.startsWith("xagent:")) {
    const spec = entry.slice("xagent:".length);
    const slash = spec.indexOf("/");
    return {
      entry, transport: "xagent",
      agent: slash < 0 ? spec : spec.slice(0, slash),
      model: slash < 0 ? null : spec.slice(slash + 1),
      effort: requestedEffort,
    };
  }
  const inherited = entry === "inherit-parent" || entry === "auto";
  const slash = entry.indexOf("/");
  const providerId = inherited ? catalog.inheritedProviderInstanceId : entry.slice(0, slash);
  const modelId = inherited ? catalog.inheritedModel : entry.slice(slash + 1);
  const model = modelFor(catalog, providerId, modelId, !inherited);
  if (inherited) {
    // T3 replaces target.options; catalog control defaults are not parent selections.
    return {
      entry, transport: "t3", target: null,
      resolved: { providerInstanceId: providerId, model: model.id },
      effort: { requested: requestedEffort, sent: null, option: null },
      warnings: requestedEffort === null ? [] : [
        `${providerId}/${model.id}: requested effort ${requestedEffort} is not sent to preserve all parent model options; choose an explicit model target to set effort independently`,
      ],
    };
  }
  const { effort, warnings } = effortFor(model, requestedEffort, `${providerId}/${model.id}`);
  const target = { providerInstanceId: providerId, model: model.id };
  if (effort.sent !== null) target.options = { [effort.option]: effort.sent };
  return {
    entry, transport: "t3", target,
    resolved: { providerInstanceId: providerId, model: model.id }, effort, warnings,
  };
}

/**
 * @param {object} policy Effective output of config.mjs show --host t3.
 * @param {object} catalog Raw orchestrator_capabilities structured result for this task.
 * @param {{role?: string, panel?: string, effort?: string, provider?: string}} selection One role or panel, with optional per-job effort and candidate provider.
 * @returns {{selection: object, workers: object[]}} Ordered arguments, never an execution receipt.
 */
export function resolveT3Targets(policy, catalog, { role, panel, effort, provider }) {
  if ((role === undefined) === (panel === undefined) || !(role ?? panel).trim()) {
    throw new Error("resolve requires exactly one nonempty --role or --panel");
  }
  if (!catalog || !Array.isArray(catalog.providers)
      || typeof catalog.inheritedProviderInstanceId !== "string" || !catalog.inheritedProviderInstanceId.trim()
      || typeof catalog.inheritedModel !== "string" || !catalog.inheritedModel.trim()) {
    throw new Error("T3 catalog requires providers, inheritedProviderInstanceId and inheritedModel from the current thread");
  }
  const kind = role === undefined ? "panel" : "role";
  const name = role ?? panel;
  const choices = kind === "role" ? policy.roles : policy.panels;
  const defaulted = !Object.hasOwn(choices, name);
  const value = defaulted ? (kind === "role" ? policy.defaultModel : policy.defaultPanel) : choices[name];
  const selection = { kind, name, defaulted };
  let entries;
  if (kind === "role" && typeof value === "object") {
    const candidates = value.candidates;
    const providerMatch = candidates.find(entry => entry.slice(0, entry.indexOf("/")) === (provider ?? catalog.inheritedProviderInstanceId));
    if (provider !== undefined && !providerMatch) throw new Error(`role ${name}: provider ${provider} is not a configured candidate`);
    const entry = providerMatch ?? candidates[0];
    selection.strategy = provider !== undefined ? "explicit-provider" : providerMatch ? "parent-provider" : "first-candidate";
    selection.entry = entry;
    entries = [entry];
  } else {
    if (provider !== undefined) throw new Error("--provider requires a role with configured candidates");
    entries = kind === "role" ? [value] : value;
  }
  const requestedEffort = effort ?? policy.reasoning_effort ?? null;
  return {
    selection,
    workers: entries.map(entry => workerFor(entry, catalog, requestedEffort)),
  };
}
