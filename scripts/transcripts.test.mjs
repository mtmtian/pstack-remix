import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { chmodSync, mkdirSync, mkdtempSync, rmSync, utimesSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

const root = path.resolve(import.meta.dirname, "..");
const cli = path.join(root, "bin/transcripts.mjs");
const DAY = 24 * 60 * 60 * 1000;
const now = Date.now();
// Message content the helper must never print.
const SECRET = "SECRET-CONTENT-MARKER";

function tempHome(t) {
  const home = mkdtempSync(path.join(os.tmpdir(), "pstack-transcripts-test-"));
  t.after(() => rmSync(home, { recursive: true, force: true }));
  return home;
}

function writeJsonl(file, records, ageDays) {
  mkdirSync(path.dirname(file), { recursive: true });
  writeFileSync(file, records.map((record) => `${JSON.stringify(record)}\n`).join(""));
  const mtime = new Date(now - ageDays * DAY);
  utimesSync(file, mtime, mtime);
  return file;
}

// A Claude session as Claude Code writes it: a cwd-less header, then messages that record the cwd.
function claudeSession(home, dirName, session, cwd, ageDays) {
  return writeJsonl(path.join(home, ".claude/projects", dirName, `${session}.jsonl`), [
    { type: "permission-mode", sessionId: session },
    { type: "user", cwd, sessionId: session, message: { role: "user", content: SECRET } },
  ], ageDays);
}

function codexRollout(home, day, id, cwd, ageDays, source = "cli") {
  return writeJsonl(path.join(home, ".codex/sessions", ...day.split("-"), `rollout-${day}T00-00-00-${id}.jsonl`), [
    { timestamp: new Date(now).toISOString(), type: "session_meta", payload: { id, session_id: id, cwd, source, base_instructions: { text: SECRET } } },
    { type: "response_item", payload: { type: "message", role: "user", content: [{ type: "input_text", text: SECRET }] } },
  ], ageDays);
}

function run(home, args, env = {}) {
  const clean = { ...process.env, HOME: home };
  delete clean.CLAUDE_CONFIG_DIR;
  delete clean.CODEX_HOME;
  return spawnSync(process.execPath, [cli, ...args], { encoding: "utf8", env: { ...clean, ...env } });
}

function list(home, args, env) {
  const result = run(home, [...args, "--json"], env);
  assert.equal(result.status, 0, result.stderr);
  return JSON.parse(result.stdout);
}

function paths(listing) {
  return listing.transcripts.map((item) => item.path);
}

test("Given cwds with spaces, dots, underscores, non-ASCII and over 200 characters, When Claude sessions are listed, Then each is found under Claude Code's directory name", (t) => {
  const home = tempHome(t);
  const cases = [
    ["/work/Application Support/my_app.v2", "-work-Application-Support-my-app-v2"],
    ["/work/项目/🚀", "-work------"],
    [
      `/work/${Array(15).fill("nested-segment").join("/")}`,
      `${"-work-nested-segment".padEnd(200, "-nested-segment")}-hw57gs`,
    ],
  ];
  for (const [index, [cwd, dirName]] of cases.entries()) {
    const file = claudeSession(home, dirName, `session-${index}`, cwd, 1);
    // Upstream's '/' and '.' rule would look here; nothing may be found there.
    claudeSession(home, cwd.replace(/[/.]/g, "-"), `decoy-${index}`, cwd, 1);
    assert.deepEqual(paths(list(home, ["--host", "claude", "--cwd", cwd])), [file], cwd);
  }
});

test("Given one Claude directory shared by colliding paths and a moved session, When one cwd is listed, Then only sessions that recorded that cwd and their subagents are returned", (t) => {
  const home = tempHome(t);
  const dir = path.join(home, ".claude/projects/-work-a-b");
  const own = claudeSession(home, "-work-a-b", "own", "/work/a.b", 2);
  claudeSession(home, "-work-a-b", "collision", "/work/a-b", 1);
  const moved = writeJsonl(path.join(dir, "moved.jsonl"), [
    { type: "user", cwd: "/scratch/start", message: { content: "first" } },
    { type: "user", cwd: "/work/a.b", message: { content: "after the move" } },
  ], 3);
  const subagent = writeJsonl(path.join(dir, "own/subagents/agent-a1.jsonl"), [{ type: "user", cwd: "/work/a.b/.claude/worktrees/w" }], 2.5);
  writeFileSync(path.join(dir, "own/subagents/agent-a1.meta.json"), "{}");
  writeJsonl(path.join(dir, "own/tool-results/out.jsonl"), [{ cwd: "/work/a.b" }], 1);
  writeJsonl(path.join(dir, "memory/notes.jsonl"), [{ cwd: "/work/a.b" }], 1);

  const listing = list(home, ["--host", "claude", "--cwd", "/work/a.b"]);
  assert.deepEqual(paths(listing), [own, subagent, moved]);
  assert.deepEqual(listing.transcripts.map(({ kind, session, parent, cwd }) => ({ kind, session, parent, cwd })), [
    { kind: "session", session: "own", parent: null, cwd: "/work/a.b" },
    { kind: "subagent", session: "agent-a1", parent: "own", cwd: "/work/a.b" },
    { kind: "session", session: "moved", parent: null, cwd: "/work/a.b" },
  ]);
  assert.ok(!JSON.stringify(listing).includes(SECRET));
});

test("Given Claude sessions of several ages, When listed by default and with explicit bounds, Then only files whose own mtime is in the window appear, newest first", (t) => {
  const home = tempHome(t);
  const cwd = "/work/repo";
  const recent = claudeSession(home, "-work-repo", "recent", cwd, 1);
  const older = claudeSession(home, "-work-repo", "older", cwd, 6);
  const stale = claudeSession(home, "-work-repo", "stale", cwd, 10);
  const oldChild = writeJsonl(path.join(home, ".claude/projects/-work-repo/recent/subagents/agent-old.jsonl"), [{ cwd }], 9);
  const staleChild = writeJsonl(path.join(home, ".claude/projects/-work-repo/stale/subagents/agent-new.jsonl"), [{ cwd }], 2);

  assert.deepEqual(paths(list(home, ["--host", "claude", "--cwd", cwd])), [recent, staleChild, older]);
  const since = new Date(now - 11 * DAY).toISOString();
  const until = new Date(now - 5 * DAY).toISOString();
  assert.deepEqual(paths(list(home, ["--host", "claude", "--cwd", cwd, "--since", since, "--until", until])), [older, oldChild, stale]);

  const text = run(home, ["--host", "claude", "--cwd", cwd]);
  assert.equal(text.status, 0, text.stderr);
  assert.deepEqual(text.stdout.trim().split("\n").map((line) => line.split("\t")[3]), [recent, staleChild, older]);
  assert.match(text.stderr, /^3 claude transcript\(s\) for \/work\/repo from /);
});

test("Given Codex rollouts from several projects and days, When one cwd is listed, Then matching sessions and subagents in the window are returned by mtime", (t) => {
  const home = tempHome(t);
  const cwd = "/work/repo";
  const today = codexRollout(home, "2026-10-17", "today", cwd, 0.5);
  const resumed = codexRollout(home, "2026-09-01", "resumed", cwd, 1);
  const child = codexRollout(home, "2026-10-16", "child", cwd, 2, { subagent: { thread_spawn: { parent_thread_id: "today", depth: 1 } } });
  codexRollout(home, "2026-10-17", "other-project", "/work/repo-other", 0.5);
  codexRollout(home, "2026-10-01", "too-old", cwd, 20);
  writeJsonl(path.join(home, ".codex/sessions/2026/10/17/rollout-no-meta.jsonl"), [{ type: "response_item", payload: { cwd } }], 0.5);
  writeJsonl(path.join(home, ".codex/sessions/archive/rollout-elsewhere.jsonl"), [{ type: "session_meta", payload: { id: "x", cwd } }], 0.5);

  const listing = list(home, ["--host", "codex", "--cwd", cwd]);
  assert.deepEqual(paths(listing), [today, resumed, child]);
  assert.deepEqual(listing.transcripts.map(({ kind, session, parent }) => ({ kind, session, parent })), [
    { kind: "session", session: "today", parent: null },
    { kind: "session", session: "resumed", parent: null },
    { kind: "subagent", session: "child", parent: "today" },
  ]);
  assert.ok(!JSON.stringify(listing).includes(SECRET));
});

test("Given unreadable files outside the scope, When either host lists, Then they are never opened", { skip: process.getuid?.() === 0 && "root ignores file modes" }, (t) => {
  const home = tempHome(t);
  const cwd = "/work/repo";
  const own = claudeSession(home, "-work-repo", "own", cwd, 1);
  const lockedProject = claudeSession(home, "-work-repo-sibling", "theirs", "/work/repo-sibling", 1);
  const codexOwn = codexRollout(home, "2026-10-17", "own", cwd, 1);
  const lockedOld = codexRollout(home, "2026-09-01", "old", "/work/elsewhere", 30);
  for (const file of [lockedProject, lockedOld]) chmodSync(file, 0);

  assert.deepEqual(paths(list(home, ["--host", "claude", "--cwd", cwd])), [own]);
  assert.deepEqual(paths(list(home, ["--host", "codex", "--cwd", cwd])), [codexOwn]);
});

test("Given relocated host homes and several checkouts, When listed, Then CLAUDE_CONFIG_DIR and CODEX_HOME are read and every --cwd is matched", (t) => {
  const home = tempHome(t);
  const claudeDir = path.join(home, "claude-config");
  const codexDir = path.join(home, "codex-home");
  const main = writeJsonl(path.join(claudeDir, "projects/-work-repo/main.jsonl"), [{ cwd: "/work/repo" }], 1);
  const worktree = writeJsonl(path.join(claudeDir, "projects/-work-repo--claude-worktrees-w/wt.jsonl"), [{ cwd: "/work/repo/.claude/worktrees/w" }], 2);
  claudeSession(home, "-work-repo", "default-home", "/work/repo", 1);
  const rollout = writeJsonl(path.join(codexDir, "sessions/2026/10/17/rollout.jsonl"), [{ type: "session_meta", payload: { id: "r", cwd: "/work/repo" } }], 1);
  const env = { CLAUDE_CONFIG_DIR: claudeDir, CODEX_HOME: codexDir };

  const claude = list(home, ["--host", "claude", "--cwd", "/work/repo", "--cwd", "/work/repo/.claude/worktrees/w"], env);
  assert.deepEqual(paths(claude), [main, worktree]);
  assert.deepEqual(claude.cwds, ["/work/repo", "/work/repo/.claude/worktrees/w"]);
  assert.deepEqual(paths(list(home, ["--host", "codex", "--cwd", "/work/repo"], env)), [rollout]);
});

test("Given bounds in years 0 to 99 or on a day the local calendar skipped, When the CLI parses them, Then it keeps the dates as written", (t) => {
  const home = tempHome(t);
  const ancient = list(home, ["--host", "claude", "--since", "0000-01-01T00:00:00Z", "--until", "0000-01-02T00:00:00Z"], { TZ: "UTC" });
  assert.equal(ancient.since, "0000-01-01T00:00:00.000Z");
  const bare = list(home, ["--host", "claude", "--since", "0050-01-01", "--until", "0050-01-01"], { TZ: "UTC" });
  assert.deepEqual([bare.since, bare.until], ["0050-01-01T00:00:00.000Z", "0050-01-01T23:59:59.999Z"]);
  // Samoa skipped 2011-12-30 locally, but that UTC date still exists.
  const skipped = list(home, ["--host", "claude", "--since", "2011-12-30T12:00:00Z", "--until", "2011-12-31T00:00:00Z"], { TZ: "Pacific/Apia" });
  assert.equal(skipped.since, "2011-12-30T12:00:00.000Z");
});

test("Given invalid arguments, When the CLI runs, Then it exits 1 with the reason", (t) => {
  const home = tempHome(t);
  const cases = [
    [[], /--host is required/],
    [["--host", "cursor"], /host must be one of claude or codex/],
    [["--host", "claude", "--since", "last week"], /--since must be YYYY-MM-DD or an ISO 8601 date-time/],
    [["--host", "claude", "--until", "2026-02-30"], /--until 2026-02-30 is not a calendar date/],
    [["--host", "claude", "--until", "2026-02-30T23:00:00Z"], /--until 2026-02-30T23:00:00Z is not a calendar date/],
    [["--host", "claude", "--since", "2026-04-31T00:00"], /--since 2026-04-31T00:00 is not a calendar date/],
    [["--host", "claude", "--since", "2026-10-10", "--until", "2026-10-01"], /since must not be later than until/],
    [["--host", "claude", "--host", "codex"], /may only be provided once/],
    [["--host", "codex", "--cwd"], /--cwd requires a value/],
  ];
  for (const [args, message] of cases) {
    const result = run(home, args);
    assert.equal(result.status, 1, args.join(" "));
    assert.match(result.stderr, message);
    assert.equal(result.stdout, "");
  }
});
