// Turn a resolved pstack policy and one live T3 catalog into dispatch arguments.
// This module neither launches tasks nor reads or changes configuration.
const EFFORT_IDS = new Set(["effort", "reasoningEffort", "thinking"]);
const EFFORT_ORDER = ["low", "medium", "high", "xhigh", "max"];
// A provider can route to any vendor, so the family comes only from the model ID's last segment.
const FAMILY = /^(claude|gpt|gemini|grok)-/;
// Its worker must differ in family from the work it checks, which the parent provider's default cannot ensure.
const CROSS_FAMILY_ROLE = "verification workers";
// The drivers whose current models orchestrator_capabilities always lists in full, per its description.
const FULLY_LISTED_DRIVERS = new Set(["codex", "claudeAgent", "muse", "grok"]);

function familyOf(modelId) {
  if (typeof modelId !== "string") return null;
  const name = modelId.slice(modelId.lastIndexOf("/") + 1).replace(/@latest$/, "").toLowerCase();
  return FAMILY.exec(name)?.[1] ?? null;
}

// The model part of a policy entry or a --checked value: a T3 target or bare model ID loses only its provider,
// and an xagent agent without a model has none.
function modelOf(entry, catalog) {
  if (entry === "inherit-parent" || entry === "auto") return catalog.inheritedModel;
  const slash = entry.indexOf("/");
  if (entry.startsWith("xagent:")) return slash < 0 ? null : entry.slice(slash + 1);
  return entry.slice(slash + 1);
}

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
  // Since T3 0.1.2 a provider lists a short list, and omittedModels counts the rest, which only a
  // search lists.
  const omitted = provider.omittedModels ?? 0;
  if (allowLatest && modelId.endsWith("@latest")) {
    if (omitted > 0 && provider.driverKind !== undefined && !FULLY_LISTED_DRIVERS.has(provider.driverKind)) {
      throw new Error(`${label}: T3 lists only part of ${providerId}'s models (${omitted} omitted), so @latest cannot see every release; use an exact model ID`);
    }
    return latestModel(provider.models, modelId, label);
  }
  if (omitted > 0 && !(provider.models ?? []).some(m => m?.id === modelId)) {
    throw new Error(`${label}: not among the models T3 listed, and ${omitted} more are omitted; call orchestrator_capabilities with search for this model and pass that result as another --catalog`);
  }
  return unique(provider.models, m => m?.id === modelId, label);
}

// The values of a select option: T3 0.1.0 lists {type: "select", options: [{id}]}, and 0.1.2 lists
// {values}, where a boolean option has [false, true]. null for any option that is not a select.
function selectChoices(option) {
  if (option?.type === "select") return (option.options ?? []).map(o => o.id);
  if (option?.type === undefined && Array.isArray(option?.values) && option.values.every(v => typeof v === "string")) {
    return option.values;
  }
  return null;
}

// The model's one effort control as {id, choices}, or null when it has none.
function effortControl(model, label) {
  const controls = (model.options ?? []).filter(o => EFFORT_IDS.has(o?.id) && selectChoices(o) !== null);
  if (controls.length > 1) throw new Error(`${label}: ambiguous effort controls in T3 catalog`);
  return controls.length ? { id: controls[0].id, choices: selectChoices(controls[0]) } : null;
}

function effortFor(model, requested, label) {
  const result = { requested, sent: null, option: null };
  if (requested === null) return { effort: result, warnings: [] };
  const control = effortControl(model, label);
  if (!control) {
    return { effort: result, warnings: [`${label}: no effort control; requested ${requested} is not sent, so the runtime default or inherited setting applies`] };
  }
  if (!control.choices.includes(requested)) {
    throw new Error(`${label}: effort ${requested} is not offered by ${control.id}; choose ${control.choices.join(", ") || "a supported value"}`);
  }
  return { effort: { requested, sent: requested, option: control.id }, warnings: [] };
}

function workerFor(entry, catalog, requestedEffort, effortCaps) {
  if (entry.startsWith("xagent:")) {
    const spec = entry.slice("xagent:".length);
    const slash = spec.indexOf("/");
    const agent = slash < 0 ? spec : spec.slice(0, slash);
    const cap = effortCaps[agent];
    const lowered = requestedEffort !== null && cap !== undefined && EFFORT_ORDER.indexOf(requestedEffort) > EFFORT_ORDER.indexOf(cap);
    const model = modelOf(entry, catalog);
    return {
      entry, transport: "xagent", agent, model, family: familyOf(model),
      effort: lowered ? cap : requestedEffort,
      warnings: lowered ? [`${entry}: requested effort ${requestedEffort} is above its xagent_effort_caps entry, so ${cap} is sent`] : [],
    };
  }
  const inherited = entry === "inherit-parent" || entry === "auto";
  const slash = entry.indexOf("/");
  const providerId = inherited ? catalog.inheritedProviderInstanceId : entry.slice(0, slash);
  const modelId = inherited ? catalog.inheritedModel : entry.slice(slash + 1);
  const model = modelFor(catalog, providerId, modelId, !inherited);
  const label = `${providerId}/${model.id}`;
  if (inherited) {
    const parent = {
      entry, transport: "t3", target: null,
      resolved: { providerInstanceId: providerId, model: model.id }, family: familyOf(model.id),
    };
    const unsent = { requested: requestedEffort, sent: null, option: null };
    if (requestedEffort === null) return { ...parent, effort: unsent, warnings: [] };
    // T3 0.1.0 replaced the parent's whole option set with target.options. From 0.1.1 the catalog
    // lists inheritedOptions, and options sent for the parent's own provider and model override
    // only the values they name, so effort alone can change.
    if (!Array.isArray(catalog.inheritedOptions)) {
      return { ...parent, effort: unsent, warnings: [`${label}: requested effort ${requestedEffort} is not sent to preserve all parent model options; choose an explicit model target to set effort independently`] };
    }
    const control = effortControl(model, label);
    if (!control?.choices.includes(requestedEffort)) {
      return { ...parent, effort: unsent, warnings: [`${label}: the parent model does not offer effort ${requestedEffort}, so the parent's own setting applies`] };
    }
    return {
      ...parent,
      target: { providerInstanceId: providerId, model: model.id, options: { [control.id]: requestedEffort } },
      effort: { requested: requestedEffort, sent: requestedEffort, option: control.id },
      warnings: [],
    };
  }
  const { effort, warnings } = effortFor(model, requestedEffort, label);
  const target = { providerInstanceId: providerId, model: model.id };
  if (effort.sent !== null) target.options = { [effort.option]: effort.sent };
  return {
    entry, transport: "t3", target,
    resolved: { providerInstanceId: providerId, model: model.id }, family: familyOf(model.id), effort, warnings,
  };
}

/**
 * One catalog from this thread's orchestrator_capabilities results: the default listing first, then
 * any search results, whose models join their provider's list. Every result must come from the
 * same thread, so a search cannot change the parent.
 * @param {object[]} catalogs Raw structured results, default listing first.
 * @returns {object} The default listing with the searched models added.
 */
export function mergeT3Catalogs([listing, ...searches]) {
  const same = ["parentThreadId", "inheritedProviderInstanceId", "inheritedModel"];
  for (const search of searches) {
    const differs = same.find(key => search?.[key] !== listing?.[key]);
    if (differs !== undefined) throw new Error(`each --catalog must come from the same thread; ${differs} differs`);
  }
  if (!searches.length || !Array.isArray(listing?.providers)) return listing;
  return {
    ...listing,
    providers: listing.providers.map(provider => {
      const models = [...(provider?.models ?? [])];
      for (const search of searches) {
        const found = (search.providers ?? []).find(p => p?.providerInstanceId === provider?.providerInstanceId);
        for (const model of found?.models ?? []) if (!models.some(m => m?.id === model?.id)) models.push(model);
      }
      return { ...provider, models };
    }),
  };
}

/**
 * @param {object} policy Effective output of config.mjs show --host t3.
 * @param {object} catalog Raw orchestrator_capabilities structured result for this task.
 * @param {{role?: string, panel?: string, effort?: string, provider?: string, checked?: string}} selection One role or panel,
 *   with optional per-job effort, candidate provider, or the entry or model that produced the work being checked.
 * @returns {{selection: object, workers: object[]}} Ordered arguments, never an execution receipt.
 */
export function resolveT3Targets(policy, catalog, { role, panel, effort, provider, checked }) {
  if ((role === undefined) === (panel === undefined) || !(role ?? panel).trim()) {
    throw new Error("resolve requires exactly one nonempty --role or --panel");
  }
  if (!catalog || !Array.isArray(catalog.providers)
      || typeof catalog.inheritedProviderInstanceId !== "string" || !catalog.inheritedProviderInstanceId.trim()
      || typeof catalog.inheritedModel !== "string" || !catalog.inheritedModel.trim()) {
    throw new Error("T3 catalog requires providers, inheritedProviderInstanceId and inheritedModel from the current thread");
  }
  if (provider !== undefined && checked !== undefined) throw new Error("use --provider or --checked, not both");
  if (checked !== undefined && !checked.trim()) throw new Error("--checked requires a nonempty entry or model");
  if (role === CROSS_FAMILY_ROLE && provider === undefined && checked === undefined) {
    throw new Error(`role ${role} requires --checked <entry or model that produced the checked work>, or --provider with a stated reason`);
  }
  const kind = role === undefined ? "panel" : "role";
  const name = role ?? panel;
  const choices = kind === "role" ? policy.roles : policy.panels;
  const defaulted = !Object.hasOwn(choices, name);
  const value = defaulted ? (kind === "role" ? policy.defaultModel : policy.defaultPanel) : choices[name];
  const selection = { kind, name, defaulted };
  const checkedFamily = checked === undefined ? null : familyOf(modelOf(checked, catalog));
  // Unknown on either side never counts as a different family.
  const crossFamily = family => checkedFamily !== null && family !== null && family !== checkedFamily;
  if (checked !== undefined) selection.checked = { entry: checked, family: checkedFamily };
  let entries;
  if (kind === "role" && typeof value === "object") {
    const candidates = value.candidates;
    const providerOf = entry => entry.slice(0, entry.indexOf("/"));
    let entry;
    if (provider !== undefined) {
      entry = candidates.find(candidate => providerOf(candidate) === provider);
      if (!entry) throw new Error(`role ${name}: provider ${provider} is not a configured candidate`);
      selection.strategy = "explicit-provider";
    } else {
      const parent = candidates.find(candidate => providerOf(candidate) === catalog.inheritedProviderInstanceId);
      const ordered = parent ? [parent, ...candidates.filter(candidate => candidate !== parent)] : candidates;
      entry = ordered.find(candidate => crossFamily(familyOf(modelOf(candidate, catalog))));
      selection.strategy = entry ? "cross-family" : parent ? "parent-provider" : "first-candidate";
      entry ??= ordered[0];
    }
    selection.entry = entry;
    entries = [entry];
  } else {
    if (provider !== undefined) throw new Error("--provider requires a role with configured candidates");
    entries = kind === "role" ? [value] : value;
  }
  const requestedEffort = effort ?? policy.reasoning_effort ?? null;
  const auxiliary = new Set(policy.auxiliary_panel_members ?? []);
  return {
    selection,
    workers: entries.map(entry => {
      const worker = workerFor(entry, catalog, requestedEffort, policy.xagent_effort_caps ?? {});
      // The auxiliary listing only relaxes panel seats; a role never becomes optional.
      worker.auxiliary = kind === "panel" && auxiliary.has(entry);
      if (checked !== undefined && !crossFamily(worker.family)) {
        worker.warnings.push(worker.family !== null && worker.family === checkedFamily
          ? `${entry}: same ${worker.family} family as the checked work; label it same-family review`
          : `${entry}: the family of ${worker.family === null ? "this worker" : "the checked work"} is unknown, so it is not cross-family evidence`);
      }
      return worker;
    }),
  };
}
