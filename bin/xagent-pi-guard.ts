import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { appendFileSync, lstatSync, readFileSync, readlinkSync, realpathSync } from "node:fs";
import path from "node:path";

// pi has no permission system, so xagent loads this guard. bash runs only whole-word prefixes from
// XAGENT_ALLOWED_FILE, one plain command at a time; edit and write stay inside the working directory
// and out of .git. Every block is appended to XAGENT_GUARD_LOG.

const SHELL_SYNTAX = new Set(";&|`$<>(){}\\");
const UNICODE_SPACES = /[\u00a0\u2000-\u200a\u202f\u205f\u3000]/;

// Parse only the small, non-expanding shell subset accepted by this guard. Quotes group argv
// characters and are removed; unquoted operators/globs, active substitutions, escapes, and open
// quotes fail closed.
function parseSimpleArgv(command: string): string[] | undefined {
  const argv: string[] = [];
  let word = "";
  let started = false;
  let quote: "'" | '"' | undefined;

  for (const char of command) {
    if (char === "\n" || char === "\r") return undefined;
    if (quote === "'") {
      if (char === "'") quote = undefined;
      else word += char;
      started = true;
      continue;
    }
    if (quote === '"') {
      if (char === '"') quote = undefined;
      else if (char === "$" || char === "`" || char === "\\") return undefined;
      else word += char;
      started = true;
      continue;
    }
    if (char === "'" || char === '"') {
      quote = char;
      started = true;
      continue;
    }
    if (/\s/.test(char)) {
      if (started) argv.push(word);
      word = "";
      started = false;
      continue;
    }
    if (SHELL_SYNTAX.has(char) || "*?[]".includes(char)) return undefined;
    // Bash treats # at the beginning of a word as a comment and expands a leading unquoted ~.
    if ((char === "#" && !started) || (char === "~" && !started)) return undefined;
    word += char;
    started = true;
  }
  if (quote) return undefined;
  if (started) argv.push(word);
  return argv;
}

export function isAllowed(command: string, allowed: string[]): boolean {
  const words = parseSimpleArgv(command);
  if (!words?.length) return false;
  // git log/diff --output=<file> writes anywhere.
  if (words.some((word) => word.startsWith("--output"))) return false;
  return allowed.some((prefix) => {
    const need = prefix.split(/\s+/);
    return need.length <= words.length && need.every((word, i) => words[i] === word);
  });
}

// Resolve the deepest existing ancestor while lstat preserves dangling symlink entries. Any
// unresolved or inaccessible component fails closed in isWritable below.
function landing(target: string, symlinkDepth = 0): string {
  if (symlinkDepth > 40) throw new Error("Too many symlinks");
  let dir = path.resolve(target);
  const rest: string[] = [];
  while (true) {
    let stat;
    try {
      stat = lstatSync(dir);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
      const parent = path.dirname(dir);
      if (parent === dir) throw error;
      rest.unshift(path.basename(dir));
      dir = parent;
      continue;
    }
    if (stat.isSymbolicLink()) {
      const linkTarget = readlinkSync(dir);
      const resolvedLink = path.resolve(path.dirname(dir), linkTarget);
      return landing(path.join(resolvedLink, ...rest), symlinkDepth + 1);
    }
    return path.join(realpathSync(dir), ...rest);
  }
}

function hasGitMetadataComponent(relative: string): boolean {
  return relative.split(path.sep).some((component) => component.toLowerCase() === ".git");
}

export function isWritable(target: string, root: string): boolean {
  if (!target || target.startsWith("@") || target.startsWith("~") || UNICODE_SPACES.test(target)) return false;
  if (process.platform === "win32" && /^\/(?:mnt\/|cygdrive\/)?[a-z](?:\/|$)/i.test(target)) return false;
  const isWindowsAbsolute = process.platform === "win32" && /^[a-z]:[\\/]/i.test(target);
  if (/^[a-z][a-z\d+.-]*:/i.test(target) && !isWindowsAbsolute) return false;

  try {
    const base = realpathSync(root);
    const resolvedTarget = path.resolve(base, target);
    const inputRelative = path.relative(base, resolvedTarget);
    if (hasGitMetadataComponent(inputRelative)) return false;
    const real = landing(resolvedTarget);
    const relative = path.relative(base, real);
    const inside = relative === "" || (relative !== ".." && !relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative));
    return inside && !hasGitMetadataComponent(relative);
  } catch {
    return false;
  }
}

export function readAllowed(file: string): string[] {
  return readFileSync(file, "utf8")
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith("#"));
}

export default function (pi: ExtensionAPI) {
  const allowed = readAllowed(process.env.XAGENT_ALLOWED_FILE ?? "");
  const root = process.cwd();
  const block = (what: string, reason: string) => {
    if (process.env.XAGENT_GUARD_LOG) appendFileSync(process.env.XAGENT_GUARD_LOG, `blocked: ${what}\n`);
    return { block: true, reason };
  };

  pi.on("tool_call", async (event) => {
    if (event.toolName === "bash") {
      const command = String(event.input.command ?? "");
      if (isAllowed(command, allowed)) return undefined;
      return block(command, `Only these commands may run, one at a time, from the current directory: ${allowed.join(", ")}`);
    }
    if (event.toolName === "edit" || event.toolName === "write") {
      const target = String(event.input.path ?? "");
      if (isWritable(target, root)) return undefined;
      return block(`${event.toolName} ${target}`, `Only files inside ${root}, outside .git, may be changed`);
    }
    return undefined;
  });
}
