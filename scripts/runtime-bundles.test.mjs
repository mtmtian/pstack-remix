import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { copyFileSync, mkdtempSync, rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

const root = path.resolve(import.meta.dirname, "..");

test("The shipped orchestrator persists work units using Node without Bun or installed dependencies", (t) => {
  const directory = mkdtempSync(path.join(os.tmpdir(), "pstack-node-runtime-"));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  const cli = path.join(directory, "orch.mjs");
  copyFileSync(path.join(root, "bin/orch.mjs"), cli);
  const store = path.join(directory, "store");
  for (const args of [["init"], ["unit", "add", "ci-smoke", "--track", "ci"]]) {
    const result = spawnSync(process.execPath, [cli, "--store", store, ...args], {
      cwd: directory, env: { ...process.env, PATH: "" }, encoding: "utf8", timeout: 10000,
    });
    assert.equal(result.status, 0, result.stderr);
  }
  const listed = spawnSync(process.execPath, [cli, "--store", store, "--json", "unit", "list"], {
    cwd: directory, env: { ...process.env, PATH: "" }, encoding: "utf8", timeout: 10000,
  });
  assert.equal(listed.status, 0, listed.stderr);
  assert.deepEqual(JSON.parse(listed.stdout), [{
    id: "ci-smoke", track: "ci", state: "pending", branch: "", pr: "", sha: "", brief: "",
  }]);
});

test("The shipped PR watcher shows help and rejects invalid arguments without GitHub access", (t) => {
  const directory = mkdtempSync(path.join(os.tmpdir(), "pstack-node-watcher-"));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  const cli = path.join(directory, "watch-pr.mjs");
  copyFileSync(path.join(root, "bin/watch-pr.mjs"), cli);
  const options = { cwd: directory, env: { ...process.env, PATH: "" }, encoding: "utf8", timeout: 10000 };
  const help = spawnSync(process.execPath, [cli, "--help"], options);
  assert.equal(help.status, 0, help.stderr);
  assert.match(help.stdout, /Usage: watch-pr/);
  const invalid = spawnSync(process.execPath, [cli, "--interval", "0"], options);
  assert.equal(invalid.status, 64, invalid.stderr);
  assert.match(invalid.stderr, /must be greater than zero/);
});
