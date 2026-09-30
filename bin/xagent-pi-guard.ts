import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { appendFileSync, existsSync, readFileSync, realpathSync } from "node:fs";
import path from "node:path";

// pi has no permission system, so xagent loads this guard. bash runs only whole-word prefixes from
// XAGENT_ALLOWED_FILE, one plain command at a time; edit and write stay inside the working directory
// and out of .git. Every block is appended to XAGENT_GUARD_LOG.

const SHELL_SYNTAX = /[;&|`$<>(){}\\\n]/;

export function isAllowed(command: string, allowed: string[]): boolean {
  if (SHELL_SYNTAX.test(command)) return false;
  const words = command.trim().split(/\s+/);
  // git log/diff --output=<file> writes anywhere.
  if (words.some((word) => word.startsWith("--output"))) return false;
  return allowed.some((prefix) => {
    const need = prefix.split(/\s+/);
    return need.length <= words.length && need.every((word, i) => words[i] === word);
  });
}

// Resolves symlinks through the deepest existing ancestor, so a new file is judged by where it would land.
function landing(target: string): string {
  let dir = target;
  const rest: string[] = [];
  while (!existsSync(dir)) {
    rest.unshift(path.basename(dir));
    dir = path.dirname(dir);
  }
  return path.join(realpathSync(dir), ...rest);
}

export function isWritable(target: string, root: string): boolean {
  if (!target || target.startsWith("~")) return false;
  const real = landing(path.resolve(root, target));
  const base = realpathSync(root);
  const inside = real === base || real.startsWith(base + path.sep);
  return inside && !real.slice(base.length).split(path.sep).includes(".git");
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
