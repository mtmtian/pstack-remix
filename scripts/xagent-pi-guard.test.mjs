import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, rmSync, symlinkSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { isAllowed, isWritable, readAllowed } from "../bin/xagent-pi-guard.ts";

const allowed = readAllowed(path.resolve(import.meta.dirname, "../bin/xagent-allowed-commands"));

test("Given the shared allowlist, When pi runs a listed check with arguments, Then the guard lets it through", () => {
  for (const command of ["pnpm test", "pnpm test --filter api", "python3 -m unittest -q", "git diff --stat"]) {
    assert.equal(isAllowed(command, allowed), true, command);
  }
});

test("Given the shared allowlist, When pi chains, substitutes, redirects or runs an unlisted command, Then the guard blocks it", () => {
  for (const command of [
    "pnpm test:scripts",
    "pnpm",
    "pnpm test && rm -rf /",
    "pnpm test; rm x",
    "git status | cat",
    "echo $(whoami)",
    "cd sub && pnpm test",
    "git init repo",
    "git log --output=/tmp/x",
    "rm -rf node_modules",
    "",
  ]) {
    assert.equal(isAllowed(command, allowed), false, command);
  }
});

test("Given a worktree with an outward symlink, When pi edits or writes, Then only paths landing inside it and outside .git pass", (t) => {
  const base = mkdtempSync(path.join(os.tmpdir(), "xagent-guard-"));
  t.after(() => rmSync(base, { recursive: true, force: true }));
  const root = path.join(base, "wt");
  const outside = path.join(base, "outside");
  mkdirSync(root);
  mkdirSync(outside);
  symlinkSync(outside, path.join(root, "link-out"));

  for (const target of ["stats.py", "new/dir/file.py", path.join(root, "stats.py")]) {
    assert.equal(isWritable(target, root), true, target);
  }
  for (const target of ["../outside/x", path.join(outside, "x"), "link-out/x", "~/.zshrc", ".git/config", ".git", ""]) {
    assert.equal(isWritable(target, root), false, target);
  }
});
