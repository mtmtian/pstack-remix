import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { copyFileSync, existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, realpathSync, readlinkSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

const helper = path.resolve(import.meta.dirname, "../references/link-into");
const EXCLUDED = ["/.agents/skills/verify-notes", "/.claude/skills/verify-notes", "/.verify/"];

function run(cmd, args, cwd) {
  const result = spawnSync(cmd, args, { cwd, encoding: "utf8", env: { ...process.env, GIT_CONFIG_GLOBAL: "/dev/null", GIT_CONFIG_NOSYSTEM: "1" } });
  return { status: result.status, out: result.stdout, err: result.stderr };
}

function git(cwd, ...args) {
  const result = run("git", args, cwd);
  assert.equal(result.status, 0, `git ${args.join(" ")}: ${result.err}`);
  return result.out;
}

// A repository with one commit and a worktree, and a personal skill outside both, as the guide lays them out.
function setup(t) {
  const base = realpathSync(mkdtempSync(path.join(os.tmpdir(), "pstack-link-into-")));
  t.after(() => rmSync(base, { recursive: true, force: true }));
  const repo = path.join(base, "repo");
  mkdirSync(repo);
  git(repo, "init", "-q", "-b", "main");
  writeFileSync(path.join(repo, "README.md"), "app\n");
  git(repo, "add", "README.md");
  git(repo, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "init");
  const worktree = path.join(base, "wt");
  git(repo, "worktree", "add", "-q", "-b", "feature", worktree);
  const skill = path.join(base, "local-skills", "verify-notes");
  mkdirSync(path.join(skill, "bin"), { recursive: true });
  writeFileSync(path.join(skill, "SKILL.md"), "---\nname: verify-notes\ndescription: test\n---\n");
  copyFileSync(helper, path.join(skill, "bin", "link-into"));
  const exclude = path.join(repo, ".git", "info", "exclude");
  return { base, repo, worktree, skill, exclude, link: (checkout) => run(path.join(skill, "bin", "link-into"), [checkout], skill) };
}

test("Given a personal skill, When it is linked into a checkout and its worktree, Then neither shows it and only info/exclude ignores it", (t) => {
  const { repo, worktree, skill, exclude, link } = setup(t);
  for (const checkout of [worktree, repo]) {
    const linked = link(checkout);
    assert.equal(linked.status, 0, linked.err);
    assert.equal(readlinkSync(path.join(checkout, ".agents/skills/verify-notes")), skill);
    assert.equal(readlinkSync(path.join(checkout, ".claude/skills/verify-notes")), "../../.agents/skills/verify-notes");
    mkdirSync(path.join(checkout, ".verify/notes/run-1"), { recursive: true });
    writeFileSync(path.join(checkout, ".verify/notes/run-1/proof.txt"), "ok\n");
    assert.equal(git(checkout, "status", "--porcelain", "--untracked-files=all"), "");
    const ignored = git(checkout, "check-ignore", "-v", ".agents/skills/verify-notes", ".claude/skills/verify-notes", ".verify/x").trim().split("\n");
    assert.equal(ignored.length, 3);
    for (const line of ignored) assert.match(line, /(^|\/)\.git\/info\/exclude:\d+:/, line);
    assert.equal(existsSync(path.join(checkout, ".gitignore")), false);
  }
  const again = link(repo);
  assert.equal(again.status, 0, again.err);
  const lines = readFileSync(exclude, "utf8").split("\n");
  for (const line of EXCLUDED) assert.equal(lines.filter((l) => l === line).length, 1, line);
});

test("Given something else at a destination, When linking, Then it stops before linking or excluding anything", (t) => {
  const { repo, exclude, link } = setup(t);
  const before = readFileSync(exclude, "utf8");
  mkdirSync(path.join(repo, ".claude/skills/verify-notes"), { recursive: true });
  const refused = link(repo);
  assert.equal(refused.status, 1);
  assert.match(refused.err, /refusing: .*\.claude\/skills\/verify-notes already exists/);
  assert.equal(existsSync(path.join(repo, ".agents/skills/verify-notes")), false);
  assert.equal(readFileSync(exclude, "utf8"), before);
});

test("Given a parent directory that is a link out of the checkout, When linking, Then it stops before writing anywhere", (t) => {
  const { base, repo, exclude, link } = setup(t);
  const before = readFileSync(exclude, "utf8");
  const shared = path.join(base, "shared-skills");
  mkdirSync(shared);
  mkdirSync(path.join(repo, ".claude"));
  symlinkSync(shared, path.join(repo, ".claude/skills"));
  const refused = link(repo);
  assert.equal(refused.status, 1);
  assert.match(refused.err, /refusing: .*\.claude\/skills is a link or not a directory/);
  assert.deepEqual(readdirSync(shared), []);
  assert.equal(existsSync(path.join(repo, ".agents")), false);
  assert.equal(readFileSync(exclude, "utf8"), before);
});

test("Given a skill directory inside the checkout, When linking, Then it refuses", (t) => {
  const { repo, skill } = setup(t);
  const inside = path.join(repo, "tools", "verify-notes");
  mkdirSync(path.join(inside, "bin"), { recursive: true });
  copyFileSync(path.join(skill, "SKILL.md"), path.join(inside, "SKILL.md"));
  copyFileSync(helper, path.join(inside, "bin", "link-into"));
  const refused = run(path.join(inside, "bin", "link-into"), [repo], inside);
  assert.equal(refused.status, 1);
  assert.match(refused.err, /inside the checkout/);
});
