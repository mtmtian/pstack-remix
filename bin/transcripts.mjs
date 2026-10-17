#!/usr/bin/env node

// Lists one checkout's own session transcripts, newest first, for recall, correct and automate-me.
// A session matches by the working directory its host recorded; the helper reads that metadata and
// never prints message content.
import { closeSync, openSync, readdirSync, readSync, realpathSync, statSync } from "node:fs";
import { homedir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HOSTS = ["claude", "codex"];
const DEFAULT_DAYS = 7;
const DAY_MS = 24 * 60 * 60 * 1000;
// Claude Code (checked against 2.1.302 and this machine's project directories) replaces every UTF-16
// code unit outside [a-zA-Z0-9] with "-", so spaces, dots, underscores and CJK become one dash and an
// emoji two; past 200 characters it keeps the first 200 and appends a base-36 string hash.
const CLAUDE_SLUG_LIMIT = 200;
const READ_CHUNK = 64 * 1024;
const NEWLINE = 0x0a;

function claudeProjectSlug(cwd) {
  const slug = cwd.replace(/[^a-zA-Z0-9]/g, "-");
  if (slug.length <= CLAUDE_SLUG_LIMIT) return slug;
  let hash = 0;
  for (let i = 0; i < cwd.length; i += 1) hash = ((hash << 5) - hash + cwd.charCodeAt(i)) | 0;
  return `${slug.slice(0, CLAUDE_SLUG_LIMIT)}-${Math.abs(hash).toString(36)}`;
}

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function statOrNull(file) {
  return statSync(file, { throwIfNoEntry: false }) ?? null;
}

function entries(dir) {
  return statOrNull(dir)?.isDirectory() ? readdirSync(dir, { withFileTypes: true }) : [];
}

// Splits only at newline bytes, which never occur inside a UTF-8 sequence, so each line decodes whole.
// Stopping early closes the file through the generator's finally block.
function* lines(file) {
  const fd = openSync(file, "r");
  try {
    const buffer = Buffer.alloc(READ_CHUNK);
    let pending = [];
    for (let bytes; (bytes = readSync(fd, buffer, 0, buffer.length, null)) > 0;) {
      const chunk = buffer.subarray(0, bytes);
      let start = 0;
      for (let end; (end = chunk.indexOf(NEWLINE, start)) !== -1; start = end + 1) {
        pending.push(chunk.subarray(start, end));
        yield Buffer.concat(pending).toString("utf8");
        pending = [];
      }
      pending.push(Buffer.from(chunk.subarray(start)));
    }
    const rest = Buffer.concat(pending);
    if (rest.length) yield rest.toString("utf8");
  } finally {
    closeSync(fd);
  }
}

function parseRecord(line) {
  try {
    const value = JSON.parse(line);
    return isObject(value) ? value : null;
  } catch {
    return null;
  }
}

function transcript(file, stat, fields) {
  return { ...fields, path: file, mtime: new Date(stat.mtimeMs).toISOString(), size: stat.size };
}

// A session can start elsewhere and be moved into this directory, and distinct paths such as a-b and
// a.b share one directory name, so the first recorded cwd is not enough: any top-level cwd must match.
function claudeSessionCwd(file, cwds) {
  for (const line of lines(file)) {
    const cwd = parseRecord(line)?.cwd;
    if (cwds.has(cwd)) return cwd;
  }
  return null;
}

function listClaude({ cwds, inWindow, env, homeDir }) {
  const root = path.join(env.CLAUDE_CONFIG_DIR || path.join(homeDir, ".claude"), "projects");
  const found = [];
  for (const dir of new Set([...cwds].map((cwd) => path.join(root, claudeProjectSlug(cwd))))) {
    for (const entry of entries(dir)) {
      if (!entry.isFile() || !entry.name.endsWith(".jsonl")) continue;
      const session = entry.name.slice(0, -".jsonl".length);
      const file = path.join(dir, entry.name);
      const subagentDir = path.join(dir, session, "subagents");
      const candidates = [
        { file, fields: { kind: "session", session, parent: null } },
        ...entries(subagentDir)
          .filter((sub) => sub.isFile() && sub.name.endsWith(".jsonl"))
          .map((sub) => ({ file: path.join(subagentDir, sub.name), fields: { kind: "subagent", session: sub.name.slice(0, -".jsonl".length), parent: session } })),
      ]
        .map((candidate) => ({ ...candidate, stat: statSync(candidate.file) }))
        .filter((candidate) => inWindow(candidate.stat.mtimeMs));
      if (!candidates.length) continue;
      const cwd = claudeSessionCwd(file, cwds);
      if (cwd === null) continue;
      for (const candidate of candidates) found.push(transcript(candidate.file, candidate.stat, { ...candidate.fields, cwd }));
    }
  }
  return found;
}

function* codexRollouts(root) {
  const numbered = (dir, digits) => entries(dir).filter((entry) => entry.isDirectory() && new RegExp(`^\\d{${digits}}$`).test(entry.name));
  for (const year of numbered(root, 4)) {
    for (const month of numbered(path.join(root, year.name), 2)) {
      for (const day of numbered(path.join(root, year.name, month.name), 2)) {
        const dir = path.join(root, year.name, month.name, day.name);
        for (const entry of entries(dir)) {
          if (entry.isFile() && entry.name.endsWith(".jsonl")) yield path.join(dir, entry.name);
        }
      }
    }
  }
}

function firstRecord(file) {
  for (const line of lines(file)) return parseRecord(line);
  return null;
}

// Codex keeps no per-project directory, so a rollout's cwd is in its first record (session_meta).
// The mtime check comes first: only rollouts inside the window are opened, and only that first line.
function listCodex({ cwds, inWindow, env, homeDir }) {
  const root = path.join(env.CODEX_HOME || path.join(homeDir, ".codex"), "sessions");
  const found = [];
  for (const file of codexRollouts(root)) {
    const stat = statSync(file);
    if (!inWindow(stat.mtimeMs)) continue;
    const record = firstRecord(file);
    const meta = record?.type === "session_meta" && isObject(record.payload) ? record.payload : null;
    if (!meta || !cwds.has(meta.cwd)) continue;
    const subagent = isObject(meta.source) && isObject(meta.source.subagent) ? meta.source.subagent : null;
    const parent = subagent?.thread_spawn?.parent_thread_id;
    found.push(transcript(file, stat, {
      kind: subagent ? "subagent" : "session",
      session: typeof meta.id === "string" ? meta.id : null,
      parent: typeof parent === "string" ? parent : null,
      cwd: meta.cwd,
    }));
  }
  return found;
}

// Hosts record the process cwd, which resolves symlinks (macOS /tmp is /private/tmp), so both
// spellings match. A directory that no longer exists, such as a removed worktree, still matches as given.
function matchableCwds(cwds) {
  const forms = new Set();
  for (const cwd of cwds) {
    const resolved = path.resolve(cwd);
    forms.add(resolved);
    try {
      forms.add(realpathSync.native(resolved));
    } catch (error) {
      if (error.code !== "ENOENT" && error.code !== "ENOTDIR") throw error;
    }
  }
  return forms;
}

export function listTranscripts({ host, cwds, since, until, env = process.env, homeDir = homedir() }) {
  if (!HOSTS.includes(host)) throw new Error(`host must be one of ${HOSTS.join(" or ")}`);
  if (!cwds.length) throw new Error("at least one cwd is required");
  if (since > until) throw new Error("since must not be later than until");
  const options = { cwds: matchableCwds(cwds), inWindow: (mtime) => mtime >= since && mtime <= until, env, homeDir };
  const found = host === "claude" ? listClaude(options) : listCodex(options);
  found.sort((a, b) => b.mtime.localeCompare(a.mtime) || a.path.localeCompare(b.path));
  return {
    host,
    cwds: cwds.map((cwd) => path.resolve(cwd)),
    since: new Date(since).toISOString(),
    until: new Date(until).toISOString(),
    transcripts: found,
  };
}

// A bare date is a local calendar day: --since starts at its midnight and --until includes the whole day.
function parseTime(value, flag, { endOfDay }) {
  const day = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (day) {
    const [year, month, date] = day.slice(1).map(Number);
    const start = new Date(year, month - 1, date);
    if (start.getFullYear() !== year || start.getMonth() !== month - 1 || start.getDate() !== date) {
      throw new Error(`${flag} ${value} is not a calendar date`);
    }
    return endOfDay ? new Date(year, month - 1, date + 1).getTime() - 1 : start.getTime();
  }
  const time = /^\d{4}-\d{2}-\d{2}T/.test(value) ? Date.parse(value) : Number.NaN;
  if (Number.isNaN(time)) throw new Error(`${flag} must be YYYY-MM-DD or an ISO 8601 date-time`);
  return time;
}

const USAGE = "Usage: transcripts.mjs --host claude|codex [--cwd dir]... [--since YYYY-MM-DD|date-time] [--until YYYY-MM-DD|date-time] [--json]";

function parseArgs(args) {
  const options = { cwd: [], json: false };
  for (let i = 0; i < args.length; i += 1) {
    const flag = args[i];
    if (flag === "--json") {
      options.json = true;
      continue;
    }
    const key = flag.startsWith("--") ? flag.slice(2) : null;
    if (!["host", "cwd", "since", "until"].includes(key)) throw new Error(`Unknown argument: ${flag}\n${USAGE}`);
    const value = args[i + 1];
    if (value === undefined || value.startsWith("--")) throw new Error(`Option ${flag} requires a value`);
    if (key === "cwd") options.cwd.push(value);
    else if (Object.hasOwn(options, key)) throw new Error(`Option ${flag} may only be provided once`);
    else options[key] = value;
    i += 1;
  }
  if (!options.host) throw new Error(`--host is required\n${USAGE}`);
  return options;
}

function runCli(args) {
  const options = parseArgs(args);
  const now = Date.now();
  const result = listTranscripts({
    host: options.host,
    cwds: options.cwd.length ? options.cwd : [process.cwd()],
    since: options.since === undefined ? now - DEFAULT_DAYS * DAY_MS : parseTime(options.since, "--since", { endOfDay: false }),
    until: options.until === undefined ? now : parseTime(options.until, "--until", { endOfDay: true }),
  });
  if (options.json) {
    process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
    return;
  }
  for (const item of result.transcripts) process.stdout.write(`${item.mtime}\t${item.kind}\t${item.size}\t${item.path}\n`);
  process.stderr.write(`${result.transcripts.length} ${result.host} transcript(s) for ${result.cwds.join(", ")} from ${result.since} to ${result.until}\n`);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    runCli(process.argv.slice(2));
  } catch (error) {
    process.stderr.write(`${error.message}\n`);
    process.exitCode = 1;
  }
}
