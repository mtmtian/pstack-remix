import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, mkdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { initConfig } from "../bin/config.mjs";

const root = path.resolve(import.meta.dirname, "..");
const cli = path.join(root, "bin/config.mjs");

function tempDir() {
  return mkdtempSync(path.join(os.tmpdir(), "pstack-config-test-"));
}

function validConfig() {
  return {
    version: 1,
    roles: {},
    panels: {},
    hosts: {
      codex: { roles: {}, panels: {} },
      claude: { roles: {}, panels: {} },
    },
  };
}

function writeJson(file, value) {
  mkdirSync(path.dirname(file), { recursive: true });
  writeFileSync(file, `${JSON.stringify(value, null, 2)}\n`);
}

function runCli(args) {
  return spawnSync(process.execPath, [cli, ...args], { encoding: "utf8" });
}

test("Given no shared file, When either host runs show, Then defaults inherit the parent and use two panel attempts", (t) => {
  const dir = tempDir();
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  const configPath = path.join(dir, "config.json");

  for (const host of ["codex", "claude"]) {
    const result = runCli(["show", "--host", host, "--config", configPath]);
    assert.equal(result.status, 0, result.stderr);
    const shown = JSON.parse(result.stdout);
    assert.equal(shown.exists, false);
    assert.equal(shown.host, host);
    assert.deepEqual(shown.effective.roles, {});
    assert.deepEqual(shown.effective.panels, {});
    assert.equal(shown.effective.reasoning_effort, null);
    assert.equal(shown.effective.defaultModel, "inherit-parent");
    assert.deepEqual(shown.effective.defaultPanel, ["inherit-parent", "inherit-parent"]);
  }
});

test("Given one common policy, When both hosts run show, Then both see the same shared choices", (t) => {
  const dir = tempDir();
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  const configPath = path.join(dir, "config.json");
  const config = validConfig();
  config.roles.feature = "auto";
  config.panels.review = ["inherit-parent", "auto"];
  config.reasoning_effort = "high";
  writeJson(configPath, config);

  for (const host of ["codex", "claude"]) {
    const result = runCli(["show", "--host", host, "--config", configPath]);
    assert.equal(result.status, 0, result.stderr);
    const effective = JSON.parse(result.stdout).effective;
    assert.equal(effective.roles.feature, "auto");
    assert.deepEqual(effective.panels.review, ["inherit-parent", "auto"]);
    assert.equal(effective.reasoning_effort, "high");
  }
});

test("Given a host-specific model, When Codex is updated, Then Claude and common policy never receive that model", (t) => {
  const dir = tempDir();
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  const configPath = path.join(dir, "config.json");
  const inputPath = path.join(dir, "patch.json");
  writeJson(configPath, validConfig());
  writeJson(inputPath, { roles: { feature: "codex-model-x" }, panels: { review: ["codex-panel-model"] } });

  const update = runCli(["update", "--host", "codex", "--input", inputPath, "--config", configPath]);
  assert.equal(update.status, 0, update.stderr);
  const config = JSON.parse(readFileSync(configPath, "utf8"));
  assert.equal(config.hosts.codex.roles.feature, "codex-model-x");
  assert.deepEqual(config.hosts.codex.panels.review, ["codex-panel-model"]);
  assert.deepEqual(config.roles, {});
  assert.deepEqual(config.panels, {});
  assert.deepEqual(config.hosts.claude.roles, {});
  const claude = JSON.parse(runCli(["show", "--host", "claude", "--config", configPath]).stdout);
  assert.equal(claude.effective.roles.feature, undefined);
  assert.equal(JSON.stringify(claude).includes("codex-model-x"), false);
});

test("Given unknown root and host keys, When one host field is updated, Then all unrelated keys survive", (t) => {
  const dir = tempDir();
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  const configPath = path.join(dir, "config.json");
  const inputPath = path.join(dir, "patch.json");
  const config = validConfig();
  config.extension = { preserved: true };
  config.hosts.codex.userNote = "keep me";
  config.hosts.claude.custom = [1, 2];
  writeJson(configPath, config);
  writeJson(inputPath, { roles: { feature: "auto" } });

  const update = runCli(["update", "--host", "codex", "--input", inputPath, "--config", configPath]);
  assert.equal(update.status, 0, update.stderr);
  const saved = JSON.parse(readFileSync(configPath, "utf8"));
  assert.deepEqual(saved.extension, { preserved: true });
  assert.equal(saved.hosts.codex.userNote, "keep me");
  assert.deepEqual(saved.hosts.claude.custom, [1, 2]);
  assert.equal(saved.hosts.codex.roles.feature, "auto");
});

test("Given host overrides over a common policy, When nulls remove overrides, Then common values become effective again", (t) => {
  const dir = tempDir();
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  const configPath = path.join(dir, "config.json");
  const inputPath = path.join(dir, "patch.json");
  const config = validConfig();
  config.roles.feature = "auto";
  config.panels.review = ["auto"];
  config.reasoning_effort = "medium";
  config.hosts.codex.roles.feature = "codex-model-x";
  config.hosts.codex.panels.review = ["codex-model-y"];
  config.hosts.codex.reasoning_effort = "high";
  writeJson(configPath, config);
  writeJson(inputPath, { roles: { feature: null }, panels: { review: null }, reasoning_effort: null });

  const update = runCli(["update", "--host", "codex", "--input", inputPath, "--config", configPath]);
  assert.equal(update.status, 0, update.stderr);
  const shown = JSON.parse(runCli(["show", "--host", "codex", "--config", configPath]).stdout);
  assert.equal(shown.effective.roles.feature, "auto");
  assert.deepEqual(shown.effective.panels.review, ["auto"]);
  assert.equal(shown.effective.reasoning_effort, "medium");
  assert.equal(JSON.parse(readFileSync(configPath, "utf8")).hosts.codex.reasoning_effort, undefined);
});

test("Given no shared file, When init runs twice, Then it creates one stable default file and remains idempotent", (t) => {
  const dir = tempDir();
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  const configPath = path.join(dir, "nested", "config.json");

  const first = runCli(["init", "--config", configPath]);
  assert.equal(first.status, 0, first.stderr);
  const bytes = readFileSync(configPath);
  assert.equal(statSync(configPath).mode & 0o077, 0);
  const second = runCli(["init", "--config", configPath]);
  assert.equal(second.status, 0, second.stderr);
  assert.deepEqual(readFileSync(configPath), bytes);
  assert.equal(JSON.parse(first.stdout).created, true);
  assert.equal(JSON.parse(second.stdout).created, false);
});

test("Given legacy files at explicit paths, When init migrates, Then each vendor's choices and unknown keys stay in that host", (t) => {
  const dir = tempDir();
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  const configPath = path.join(dir, "shared", "config.json");
  const codexLegacyPath = path.join(dir, "old-codex.json");
  const claudeLegacyPath = path.join(dir, "old-claude.json");
  writeJson(codexLegacyPath, { roles: { feature: "codex-model" }, panels: { review: ["codex-panel"] }, reasoning_effort: "high", privateChoice: 7 });
  writeJson(claudeLegacyPath, { roles: { feature: "claude-model" }, panels: { review: ["claude-panel"] }, reasoning_effort: "low", extra: { keep: true } });

  const result = initConfig({ configPath, legacyPaths: { codex: codexLegacyPath, claude: claudeLegacyPath } });
  assert.equal(result.created, true);
  const config = JSON.parse(readFileSync(configPath, "utf8"));
  assert.equal(config.hosts.codex.roles.feature, "codex-model");
  assert.deepEqual(config.hosts.codex.panels.review, ["codex-panel"]);
  assert.equal(config.hosts.codex.reasoning_effort, "high");
  assert.equal(config.hosts.codex.privateChoice, 7);
  assert.equal(config.hosts.claude.roles.feature, "claude-model");
  assert.deepEqual(config.hosts.claude.panels.review, ["claude-panel"]);
  assert.equal(config.hosts.claude.reasoning_effort, "low");
  assert.deepEqual(config.hosts.claude.extra, { keep: true });
  assert.deepEqual(JSON.parse(readFileSync(codexLegacyPath, "utf8")).roles, { feature: "codex-model" });
  assert.deepEqual(JSON.parse(readFileSync(claudeLegacyPath, "utf8")).roles, { feature: "claude-model" });
});

test("Given malformed shared config or malformed input, When update runs, Then every original file remains byte-for-byte unchanged", (t) => {
  const dir = tempDir();
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  const configPath = path.join(dir, "config.json");
  const inputPath = path.join(dir, "patch.json");
  const malformedConfig = "{\n  \"version\": 7,\n  \"untouched\": true\n}\n";
  writeFileSync(configPath, malformedConfig);
  writeJson(inputPath, { roles: { feature: "auto" } });

  const badConfigResult = runCli(["update", "--host", "codex", "--input", inputPath, "--config", configPath]);
  assert.notEqual(badConfigResult.status, 0);
  assert.equal(readFileSync(configPath, "utf8"), malformedConfig);

  writeJson(configPath, validConfig());
  const validConfigBytes = readFileSync(configPath, "utf8");
  writeFileSync(inputPath, "{ invalid json\n");
  const badInputResult = runCli(["update", "--host", "codex", "--input", inputPath, "--config", configPath]);
  assert.notEqual(badInputResult.status, 0);
  assert.equal(readFileSync(configPath, "utf8"), validConfigBytes);
});

test("Given another writer holds the lock, When update runs, Then it fails clearly without changing config", (t) => {
  const dir = tempDir();
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  const configPath = path.join(dir, "config.json");
  const inputPath = path.join(dir, "patch.json");
  writeJson(configPath, validConfig());
  writeJson(inputPath, { roles: { feature: "auto" } });
  const original = readFileSync(configPath, "utf8");
  writeFileSync(`${configPath}.lock`, "locked");

  const result = runCli(["update", "--host", "codex", "--input", inputPath, "--config", configPath]);
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /locked|lock/i);
  assert.equal(readFileSync(configPath, "utf8"), original);
});

test("Given a concrete model in common policy, When update runs, Then it rejects the vendor-specific value without writing", (t) => {
  const dir = tempDir();
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  const configPath = path.join(dir, "config.json");
  const inputPath = path.join(dir, "patch.json");
  writeJson(configPath, validConfig());
  writeJson(inputPath, { roles: { feature: "codex-model-x" } });
  const original = readFileSync(configPath, "utf8");

  const result = runCli(["update", "--input", inputPath, "--config", configPath]);
  assert.notEqual(result.status, 0);
  assert.equal(readFileSync(configPath, "utf8"), original);
});

test("Given xagent entries in a shared patch, When both hosts run show, Then both resolve the same external agent policy", (t) => {
  const dir = tempDir();
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  const configPath = path.join(dir, "config.json");
  const inputPath = path.join(dir, "patch.json");
  writeJson(configPath, validConfig());
  writeJson(inputPath, {
    roles: { "swarm workers": "xagent:pi" },
    panels: { "arena runners": ["xagent:codex", "xagent:grok", "inherit-parent"] },
  });

  const update = runCli(["update", "--input", inputPath, "--config", configPath]);
  assert.equal(update.status, 0, update.stderr);
  for (const host of ["codex", "claude"]) {
    const effective = JSON.parse(runCli(["show", "--host", host, "--config", configPath]).stdout).effective;
    assert.equal(effective.roles["swarm workers"], "xagent:pi");
    assert.deepEqual(effective.panels["arena runners"], ["xagent:codex", "xagent:grok", "inherit-parent"]);
  }
});

test("Given a malformed xagent entry in common policy, When update runs, Then it is rejected without writing", (t) => {
  const dir = tempDir();
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  const configPath = path.join(dir, "config.json");
  const inputPath = path.join(dir, "patch.json");
  writeJson(configPath, validConfig());
  const original = readFileSync(configPath, "utf8");

  for (const value of ["xagent:", "xagent:Grok Model", "xagent:grok;rm"]) {
    writeJson(inputPath, { panels: { "arena runners": [value] } });
    const result = runCli(["update", "--input", inputPath, "--config", configPath]);
    assert.notEqual(result.status, 0, value);
    assert.equal(readFileSync(configPath, "utf8"), original);
  }
});

test("Given a valid config, When update omits --input, Then the CLI rejects the request without writing", (t) => {
  const dir = tempDir();
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  const configPath = path.join(dir, "config.json");
  writeJson(configPath, validConfig());
  const original = readFileSync(configPath, "utf8");

  const result = runCli(["update", "--host", "codex", "--config", configPath]);
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /--input/);
  assert.equal(readFileSync(configPath, "utf8"), original);
});

test("Given an empty panel list or unsupported effort, When update runs, Then validation rejects both shapes", (t) => {
  const dir = tempDir();
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  const configPath = path.join(dir, "config.json");
  const inputPath = path.join(dir, "patch.json");
  writeJson(configPath, validConfig());
  const original = readFileSync(configPath, "utf8");

  for (const patch of [{ panels: { review: [] } }, { reasoning_effort: "ultra" }]) {
    writeJson(inputPath, patch);
    const result = runCli(["update", "--host", "codex", "--input", inputPath, "--config", configPath]);
    assert.notEqual(result.status, 0);
    assert.equal(readFileSync(configPath, "utf8"), original);
  }
});
