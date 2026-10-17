import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync, existsSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

const cli = path.resolve(import.meta.dirname, "../bin/config.mjs");

function fixture(t) {
  const dir = mkdtempSync(path.join(os.tmpdir(), "pstack-t3-targets-"));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  const configPath = path.join(dir, "config.json");
  const catalogPath = path.join(dir, "catalog.json");
  const config = {
    version: 1, roles: {}, panels: {}, required_panel_members: ["xagent:gemini"],
    hosts: {
      codex: { roles: { feature: "native-model-must-not-leak" }, panels: {} },
      claude: { roles: {}, panels: {} },
      t3: { roles: { feature: "code/ordinary", "hardest tasks": "judge/strong" }, panels: {}, reasoning_effort: "high" },
    },
  };
  const select = (id, values) => ({ id, type: "select", options: values.map(id => ({ id })) });
  const catalog = {
    inheritedProviderInstanceId: "code", inheritedModel: "parent",
    providers: [
      { providerInstanceId: "code", canRunChildTask: true, canRunCrossProviderChildTask: false,
        models: ["ordinary", "parent"].map(id => ({ id, options: [select("reasoningEffort", ["low", "high"])] })) },
      { providerInstanceId: "judge", canRunChildTask: true, canRunCrossProviderChildTask: true,
        models: [{ id: "strong", options: [select("effort", ["medium", "high", "xhigh"])] }] },
      { providerInstanceId: "custom", canRunChildTask: true, canRunCrossProviderChildTask: true,
        models: [{ id: "route/vendor/model", options: [select("thinking", ["low", "high"])] }] },
    ],
  };
  function run(args = [], { absent = false } = {}) {
    if (!absent) writeFileSync(configPath, JSON.stringify(config));
    writeFileSync(catalogPath, JSON.stringify(catalog));
    const before = existsSync(configPath) ? readFileSync(configPath, "utf8") : null;
    const result = spawnSync(process.execPath, [cli, "resolve", "--host", "t3", "--config", configPath, "--catalog", catalogPath, ...args], { encoding: "utf8" });
    assert.equal(existsSync(configPath) ? readFileSync(configPath, "utf8") : null, before);
    return result;
  }
  function resolved(args, options) {
    const result = run(args, options);
    assert.equal(result.status, 0, result.stderr);
    return JSON.parse(result.stdout);
  }
  return { config, catalog, run, resolved };
}

test("Given role tiers, When previewed, Then exact targets and each model's effort control are emitted without writes", t => {
  const f = fixture(t);
  assert.deepEqual(f.resolved(["--role", "feature"]).workers[0].target,
    { providerInstanceId: "code", model: "ordinary", options: { reasoningEffort: "high" } });
  assert.deepEqual(f.resolved(["--role", "hardest tasks", "--effort", "xhigh"]).workers[0].target,
    { providerInstanceId: "judge", model: "strong", options: { effort: "xhigh" } });
});

test("Given a missing or inherited role, When previewed, Then this catalog's parent is used without pinning its identity", t => {
  const f = fixture(t);
  for (const entry of [undefined, "auto", "inherit-parent"]) {
    if (entry) f.config.hosts.t3.roles.feature = entry;
    else delete f.config.hosts.t3.roles.feature;
    const plan = f.resolved(["--role", "feature"]);
    assert.deepEqual(plan.workers[0].resolved, { providerInstanceId: "code", model: "parent" });
    assert.equal(plan.workers[0].target, null);
    assert.equal(plan.workers[0].effort.sent, null);
    assert.match(plan.workers[0].warnings.join(" "), /preserve.*parent.*options/);
    assert.equal(plan.selection.defaulted, entry === undefined);
  }
  f.catalog.inheritedProviderInstanceId = "judge";
  f.catalog.inheritedModel = "strong";
  assert.equal(f.resolved(["--role", "feature"]).workers[0].target, null);
  assert.equal(f.resolved(["--role", "constructor"]).selection.defaulted, true);
});

test("Given inherited model options are absent from the catalog, When effort is requested, Then no partial options replace the parent selection", t => {
  const f = fixture(t);
  f.config.hosts.t3.roles.feature = "inherit-parent";
  // Catalog control values describe provider defaults, not the parent's actual selection.
  // T3 replaces the entire options object when target.options is present.
  f.catalog.providers[0].models[1].options.push(
    { id: "fastMode", type: "boolean", currentValue: false },
    { id: "serviceTier", type: "select", currentValue: "default", options: [{ id: "default" }, { id: "priority" }] },
  );
  const worker = f.resolved(["--role", "feature", "--effort", "low"]).workers[0];
  assert.equal(worker.target, null);
  assert.deepEqual(worker.effort, { requested: "low", sent: null, option: null });
  assert.match(worker.warnings.join(" "), /low.*not sent.*preserve.*parent.*options/);
});

test("Given no config or effort, When a role is previewed, Then it inherits without creating a config or adding options", t => {
  const f = fixture(t);
  const worker = f.resolved(["--role", "feature"], { absent: true }).workers[0];
  assert.equal(worker.target, null);
  assert.equal(worker.effort.requested, null);
  assert.equal(worker.effort.sent, null);
});

test("Given a custom model path, When previewed, Then all model segments and the catalog's option key survive", t => {
  const f = fixture(t);
  f.config.hosts.t3.roles.feature = "custom/route/vendor/model";
  const worker = f.resolved(["--role", "feature", "--effort", "low"]).workers[0];
  assert.deepEqual(worker.target, { providerInstanceId: "custom", model: "route/vendor/model", options: { thinking: "low" } });
  assert.equal(worker.effort.sent, "low");
});

test("Given mixed and repeated panel seats, When previewed, Then order, independent attempts and required external members survive", t => {
  const f = fixture(t);
  f.config.hosts.t3.panels.review = ["code/ordinary", "code/ordinary", "xagent:claude/opus[1m]"];
  const workers = f.resolved(["--panel", "review"]).workers;
  assert.deepEqual(workers.map(w => w.entry), ["code/ordinary", "code/ordinary", "xagent:claude/opus[1m]", "xagent:gemini"]);
  assert.deepEqual(workers[2], { entry: "xagent:claude/opus[1m]", transport: "xagent", agent: "claude", model: "opus[1m]", effort: "high" });
  assert.equal(workers[3].model, null);
  const defaultPlan = f.resolved(["--panel", "unconfigured"]);
  assert.equal(defaultPlan.selection.defaulted, true);
  assert.deepEqual(defaultPlan.workers.map(w => w.entry), ["inherit-parent", "inherit-parent", "xagent:gemini"]);
});

test("Given an unavailable explicit target, When any panel member cannot run, Then the whole preview fails without a replacement", t => {
  const f = fixture(t);
  f.config.hosts.t3.panels.review = ["code/ordinary", "judge/strong"];
  f.catalog.providers[1].canRunChildTask = false;
  f.catalog.providers[1].constraints = ["Provider disabled by user"];
  const result = f.run(["--panel", "review"]);
  assert.notEqual(result.status, 0);
  assert.equal(result.stdout, "");
  assert.match(result.stderr, /judge\/strong.*Provider disabled by user/);
});

test("Given a missing model or forbidden cross-provider dispatch, When previewed, Then it fails with the target named", t => {
  const f = fixture(t);
  f.config.hosts.t3.roles.feature = "judge/missing";
  assert.match(f.run(["--role", "feature"]).stderr, /judge\/missing.*not.*catalog/);
  f.config.hosts.t3.roles.feature = "judge/strong";
  f.catalog.providers[1].canRunCrossProviderChildTask = false;
  const failed = f.run(["--role", "feature"]);
  assert.notEqual(failed.status, 0);
  assert.match(failed.stderr, /cross-provider/);
});

test("Given invalid effort, When previewed, Then it is rejected instead of switching model or effort", t => {
  const f = fixture(t);
  for (const value of ["xhigh", "nonsense"]) {
    const result = f.run(["--role", "feature", "--effort", value]);
    assert.notEqual(result.status, 0);
    assert.equal(result.stdout, "");
    assert.match(result.stderr, /effort/);
  }
});

test("Given a model without effort control, When effort is requested, Then the preview declares it unsent", t => {
  const f = fixture(t);
  f.catalog.providers[0].models[0].options = [];
  const worker = f.resolved(["--role", "feature"]).workers[0];
  assert.deepEqual(worker.target, { providerInstanceId: "code", model: "ordinary" });
  assert.equal(worker.effort.requested, "high");
  assert.equal(worker.effort.sent, null);
  assert.match(worker.warnings.join(" "), /effort.*default/);
});

test("Given an incomplete or ambiguous catalog, When previewed, Then it cannot guess a parent or target", t => {
  for (const mutate of [
    c => { delete c.inheritedProviderInstanceId; },
    c => { delete c.inheritedModel; },
    c => { c.providers = null; },
    c => { c.providers.push(c.providers[0]); },
    c => { c.providers[0].models.push(c.providers[0].models[0]); },
  ]) {
    const f = fixture(t);
    mutate(f.catalog);
    const result = f.run(["--role", "feature"]);
    assert.notEqual(result.status, 0);
    assert.equal(result.stdout, "");
    assert.match(result.stderr, /catalog|ambiguous/);
  }
});

test("Given an ambiguous selection, When the CLI is called, Then exactly one role or panel is required", t => {
  const f = fixture(t);
  for (const args of [[], ["--role", "feature", "--panel", "review"], ["--role", " "]]) {
    const result = f.run(args);
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /role.*panel/);
  }
});

function familyFixture(t) {
  const f = fixture(t);
  const model = id => ({ id, options: [{ id: "effort", type: "select", options: ["low", "high", "xhigh"].map(id => ({ id })) }] });
  f.catalog.providers[0].models.push(...["gpt-6-sol", "gpt-6.1-sol", "gpt-6-astra"].map(model));
  f.catalog.providers[1].models.push(...["claude-opus-5-5", "claude-fable-5-1"].map(model));
  f.config.hosts.t3.roles.feature = { candidates: ["code/gpt-sol@latest", "judge/claude-opus@latest"] };
  f.config.hosts.t3.roles["hardest tasks"] = { candidates: ["code/gpt-astra@latest", "judge/claude-fable@latest"] };
  return { ...f, model };
}

test("Given candidate roles, When each parent delegates design then ordinary implementation, Then exactly one model per current task is selected", t => {
  const f = familyFixture(t);
  for (const [provider, hard, ordinary] of [["code", "gpt-6-astra", "gpt-6.1-sol"], ["judge", "claude-fable-5-1", "claude-opus-5-5"]]) {
    f.catalog.inheritedProviderInstanceId = provider;
    for (const [role, expected] of [["hardest tasks", hard], ["feature", ordinary]]) {
      const plan = f.resolved(["--role", role]);
      assert.equal(plan.workers.length, 1);
      assert.equal(plan.workers[0].target.model, expected);
      assert.equal(plan.selection.strategy, "parent-provider");
    }
  }
});

test("Given a role with candidates, When explicitly choosing a configured provider, Then only that choice runs and an outsider is rejected", t => {
  const f = familyFixture(t);
  const plan = f.resolved(["--role", "feature", "--provider", "judge"]);
  assert.equal(plan.workers[0].target.model, "claude-opus-5-5");
  assert.equal(plan.selection.strategy, "explicit-provider");
  for (const args of [["--role", "feature", "--provider", "custom"], ["--panel", "review", "--provider", "judge"]]) {
    const failed = f.run(args);
    assert.notEqual(failed.status, 0);
    assert.equal(failed.stdout, "");
    assert.match(failed.stderr, /provider/);
  }
});

test("Given a parent outside the configured candidate providers, When selecting, Then the declared first candidate is used", t => {
  const f = familyFixture(t);
  f.catalog.inheritedProviderInstanceId = "custom";
  f.catalog.providers[0].canRunCrossProviderChildTask = true;
  const plan = f.resolved(["--role", "feature"]);
  assert.equal(plan.workers[0].target.model, "gpt-6.1-sol");
  assert.equal(plan.selection.strategy, "first-candidate");
});

test("Given a chosen unavailable candidate, When another candidate works, Then it still fails without a fallback", t => {
  const f = familyFixture(t);
  f.catalog.providers[0].canRunChildTask = false;
  const failed = f.run(["--role", "feature"]);
  assert.notEqual(failed.status, 0);
  assert.equal(failed.stdout, "");
  assert.match(failed.stderr, /code.*cannot run child/);
  assert.equal(f.resolved(["--role", "feature", "--provider", "judge"]).workers[0].target.model, "claude-opus-5-5");
});

test("Given future canonical releases, When using latest, Then numeric version order advances only the selected family", t => {
  const f = familyFixture(t);
  f.config.hosts.t3.roles.feature = "judge/claude-opus@latest";
  for (const id of ["claude-opus-5-6", "claude-opus-5-9", "claude-opus-5-10", "claude-opus-6"]) {
    f.catalog.providers[1].models.push(f.model(id));
    assert.equal(f.resolved(["--role", "feature"]).workers[0].target.model, id);
  }
  f.config.hosts.t3.roles.feature = "code/gpt-sol@latest";
  for (const id of ["gpt-6.2-sol", "gpt-6.10-sol", "gpt-7-sol"]) {
    f.catalog.providers[0].models.push(f.model(id));
    assert.equal(f.resolved(["--role", "feature"]).workers[0].target.model, id);
  }
});

test("Given preview, dated, routed and other-family models, When selecting latest, Then only canonical releases match and pinned models stay pinned", t => {
  const f = familyFixture(t);
  f.catalog.providers[1].models.push(...["claude-opus-9-preview", "claude-opus-5-5-20261017", "claude-opus-20261017", "claude-opus-5-20261017", "route/claude-opus-9", "claude-opus-9[1m]", "claude-fable-9", "claude-opus-4-5"].map(f.model));
  f.config.hosts.t3.roles.feature = "judge/claude-opus@latest";
  assert.equal(f.resolved(["--role", "feature"]).workers[0].target.model, "claude-opus-5-5");
  f.config.hosts.t3.roles.feature = "judge/claude-opus-4-5";
  assert.equal(f.resolved(["--role", "feature"]).workers[0].target.model, "claude-opus-4-5");
});

test("Given a missing or ambiguous family, When selecting latest, Then no older, cross-family or guessed target is emitted", t => {
  const f = familyFixture(t);
  for (const entry of ["code/gpt-luna@latest", "judge/unknown@latest"]) {
    f.config.hosts.t3.roles.feature = entry;
    const failed = f.run(["--role", "feature"]);
    assert.notEqual(failed.status, 0);
    assert.equal(failed.stdout, "");
    assert.match(failed.stderr, /family|latest/);
  }
  f.config.hosts.t3.roles.feature = "judge/claude-opus@latest";
  f.catalog.providers[1].models.push(f.model("claude-opus-5-5"));
  assert.match(f.run(["--role", "feature"]).stderr, /ambiguous/);
});

test("Given newest release rejects effort, When an older release accepts it, Then resolution fails without downgrading", t => {
  const f = familyFixture(t);
  f.catalog.providers[1].models.push({ id: "claude-opus-5-6", options: [{ id: "effort", type: "select", options: [{ id: "low" }] }] });
  const failed = f.run(["--role", "feature", "--provider", "judge"]);
  assert.notEqual(failed.status, 0);
  assert.equal(failed.stdout, "");
  assert.match(failed.stderr, /claude-opus-5-6.*effort high/);
});

test("Given candidate objects in native or common policy, When loaded, Then host-specific routing cannot leak", t => {
  for (const host of [null, "codex", "claude"]) {
    const f = familyFixture(t);
    (host ? f.config.hosts[host] : f.config).roles.feature = f.config.hosts.t3.roles.feature;
    assert.notEqual(f.run(["--role", "feature"]).status, 0);
  }
});

test("Given malformed candidates, When loaded, Then ambiguity, inheritance, external CLI entries and unknown fields are rejected", t => {
  const f = familyFixture(t);
  for (const value of [{ candidates: [] }, { candidates: ["code/a", "code/b"] }, { candidates: ["inherit-parent"] }, { candidates: ["xagent:claude"] }, { candidates: ["code/a"], typo: true }]) {
    f.config.hosts.t3.roles.feature = value;
    assert.notEqual(f.run(["--role", "feature"]).status, 0, JSON.stringify(value));
  }
});

test("Given a latest-family panel, When resolved, Then ordered independent seats and required external members remain", t => {
  const f = familyFixture(t);
  f.config.hosts.t3.panels["hardest architect runners"] = ["judge/claude-fable@latest", "code/gpt-astra@latest"];
  const workers = f.resolved(["--panel", "hardest architect runners"]).workers;
  assert.deepEqual(workers.map(w => w.target?.model ?? w.agent), ["claude-fable-5-1", "gpt-6-astra", "gemini"]);
});
