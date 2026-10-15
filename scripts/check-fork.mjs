#!/usr/bin/env node
// Static guards for upstream syncs. Shipped content must not bring back the
// Cursor-only instructions ADAPTATION.md replaced, every skill keeps its shared
// runtime contract, local links resolve, and the manifests keep their fork names.
import { existsSync, readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const SHIPPED = ["skills", "references", "agents"];
const SKIPPED_DIRS = new Set([".git", "node_modules"]);
const ADAPTERS = ["references/claude-runtime.md", "references/codex-runtime.md"];
// Template placeholders such as `[PR #123](url)` in a prompt the agent fills in.
const PLACEHOLDER_TARGETS = new Set(["url"]);

// `allow` names files that cite a pattern on purpose, such as an adapter listing
// the fields it forbids. An allowed file that no longer matches is reported, so
// the list cannot outlive the sentence it excuses.
export const DENYLIST = [
  {
    id: "cursor-model-sheet",
    pattern: /pstack-models\.mdc/,
    hint: "models resolve from ~/.config/pstack/config.json through bin/config.mjs",
  },
  {
    id: "fixed-loop",
    pattern: /\/loop \d+\s*[smhd]\b/,
    hint: "use an authorized host scheduler and report its observed cadence",
  },
  {
    id: "control-drivers",
    pattern: /\bcontrol-(?:ui|cli)\b/,
    allow: ["references/runtime.md"],
    hint: "use the project's verification harness and the browser named in references/runtime.md",
  },
  {
    id: "cursor-cloud-agents",
    pattern: /\bcloud[- ]agents?\b|\bcloud_base_branch\b|\bcloud-sleeper\b/i,
    allow: ["references/codex-runtime.md"],
    hint: "delegates are isolated host workers; say what the host actually runs",
  },
  {
    id: "cursor-paths",
    pattern: /~\/\.cursor\b|(?<![\w.])\.cursor(?:\/|-plugin\b)|Application Support\/Cursor\b/,
    hint: "use the Claude install record, the Codex plugin cache, or .agents/skills",
  },
  {
    id: "cursor-transcripts",
    pattern: /\bagent-transcripts\b/,
    hint: "use the host's thread history or a supplied session link, as session-pickup does",
  },
  {
    id: "cursor-task-tool",
    pattern: /`Task`|\bTask (?:tool|subagents?|calls?)\b|\b(?:generalPurpose|AskQuestion|subagent_type|run_in_background)\b|`(?:readonly|environment)`|\breadonly:\s*(?:true|false)\b|\benvironment:\s*"?(?:cloud|local)\b/,
    allow: ADAPTERS,
    hint: "shared skills name no delegation fields; each host adapter maps delegation to its own tools",
  },
  {
    id: "model-invocation",
    pattern: /\bdisable-model-invocation\b/,
    allow: ["skills/poteto-help/SKILL.md"],
    hint: "skills stay model-invocable; poteto-help is the one recorded exception",
  },
  {
    id: "effort-model-slug",
    pattern: /\b(?:claude|gpt|gemini|grok|composer)-[0-9a-z.-]*-(?:max|fast|xhigh|high|medium|low|thinking)\b/i,
    hint: "models come from config.json, effort from each host's effort control, and fast mode stays off unless asked",
  },
  {
    id: "cursor-ui",
    pattern: /\/visualize\b|\bCustom Modes?\b/,
    hint: "Cursor-only UI; use the host's own output and entry points",
  },
];

function walk(dir) {
  if (!existsSync(dir)) return [];
  return readdirSync(dir, { withFileTypes: true })
    .sort((a, b) => a.name.localeCompare(b.name))
    .flatMap((entry) => {
      if (SKIPPED_DIRS.has(entry.name)) return [];
      const file = path.join(dir, entry.name);
      return entry.isDirectory() ? walk(file) : [file];
    });
}

function relative(root, file) {
  return path.relative(root, file).split(path.sep).join("/");
}

function lineAt(text, index) {
  return text.slice(0, index).split("\n").length;
}

export function scanDenylist(root) {
  const problems = [];
  const allowedHits = new Set();
  for (const file of SHIPPED.flatMap((top) => walk(path.join(root, top)))) {
    const text = readFileSync(file, "utf8");
    if (text.includes("\0")) continue;
    const rel = relative(root, file);
    for (const rule of DENYLIST) {
      const allowed = rule.allow?.includes(rel);
      for (const match of text.matchAll(new RegExp(rule.pattern.source, `${rule.pattern.flags}g`))) {
        if (allowed) {
          allowedHits.add(`${rule.id} ${rel}`);
          continue;
        }
        problems.push(`${rel}:${lineAt(text, match.index)}: ${rule.id}: ${JSON.stringify(match[0])}; ${rule.hint}`);
      }
    }
  }
  for (const rule of DENYLIST) {
    for (const rel of rule.allow ?? []) {
      if (!allowedHits.has(`${rule.id} ${rel}`)) {
        problems.push(`${rel}: ${rule.id}: allowed here but no longer matches; remove it from the allow list`);
      }
    }
  }
  return problems;
}

// Fenced blocks and code spans hold examples and literal syntax, not links.
// Blanking them in place keeps line numbers for what remains.
function proseOnly(text) {
  let fence = null;
  return text.split("\n").map((line) => {
    const marker = /^ {0,3}(`{3,}|~{3,})(.*)$/.exec(line);
    if (fence) {
      if (marker && marker[1][0] === fence[0] && marker[1].length >= fence.length && !marker[2].trim()) fence = null;
      return "";
    }
    if (marker) {
      fence = marker[1];
      return "";
    }
    return line.replace(/(`+)(?!`).*?[^`]\1(?!`)/g, (span) => " ".repeat(span.length));
  }).join("\n");
}

function linkTargets(text) {
  const prose = proseOnly(text);
  const unwrap = (raw) => (raw.startsWith("<") ? raw.slice(1, -1) : raw);
  return [
    ...[...prose.matchAll(/\]\(\s*(<[^>\n]*>|[^)\s]*)/g)].map((m) => ({ target: unwrap(m[1]), index: m.index })),
    ...[...prose.matchAll(/^ {0,3}\[(?!\^)[^\]\n]+\]:\s*(<[^>\n]*>|\S+)/gm)].map((m) => ({ target: unwrap(m[1]), index: m.index })),
  ];
}

// Resolves a link to an absolute path, or null for anchors and URLs.
function localPath(file, target) {
  if (!target || PLACEHOLDER_TARGETS.has(target) || target.startsWith("#") || target.startsWith("//")) return null;
  if (/^[a-z][a-z0-9+.-]*:/i.test(target)) return null;
  const encoded = target.split(/[?#]/, 1)[0];
  if (!encoded) return null;
  if (encoded.startsWith("/")) return { error: "absolute path" };
  try {
    return { resolved: path.resolve(path.dirname(file), decodeURIComponent(encoded)) };
  } catch {
    return { error: "invalid URI encoding" };
  }
}

// Dot directories hold tooling state, such as nested .claude/worktrees checkouts.
function repositoryMarkdown(root) {
  return readdirSync(root, { withFileTypes: true })
    .filter((entry) => !entry.name.startsWith(".") && !SKIPPED_DIRS.has(entry.name))
    .sort((a, b) => a.name.localeCompare(b.name))
    .flatMap((entry) => (entry.isDirectory() ? walk(path.join(root, entry.name)) : [path.join(root, entry.name)]))
    .filter((file) => file.endsWith(".md"));
}

export function validateLinks(root) {
  const problems = [];
  for (const file of repositoryMarkdown(root)) {
    const text = readFileSync(file, "utf8");
    const rel = relative(root, file);
    for (const { target, index } of linkTargets(text)) {
      const local = localPath(file, target);
      if (!local) continue;
      const where = `${rel}:${lineAt(text, index)}: link ${target}`;
      if (local.error) problems.push(`${where}: ${local.error}`);
      else if (/^\.\.(?:\/|$)/.test(relative(root, local.resolved))) problems.push(`${where}: escapes the repository`);
      else if (!existsSync(local.resolved)) problems.push(`${where}: missing`);
    }
  }
  return problems;
}

function scalar(raw) {
  const value = raw.trim();
  if (/^[|>][+-]?$/.test(value)) return "";
  if (value.length >= 2 && value.startsWith('"') && value.endsWith('"')) {
    try {
      return JSON.parse(value);
    } catch {
      return value.slice(1, -1);
    }
  }
  if (value.length >= 2 && value.startsWith("'") && value.endsWith("'")) return value.slice(1, -1).replaceAll("''", "'");
  return value;
}

// Top-level scalar keys only, which is all skill and agent frontmatter uses.
function frontmatter(text) {
  const block = /^---\r?\n([\s\S]*?)\r?\n---\r?\n/.exec(text);
  if (!block) return null;
  const fields = {};
  let key = null;
  for (const line of block[1].split(/\r?\n/)) {
    const entry = /^([\w-]+):(?:\s+(.*))?$/.exec(line);
    if (entry) {
      key = entry[1];
      fields[key] = scalar(entry[2] ?? "");
    } else if (key && /^\s+\S/.test(line)) {
      fields[key] = `${fields[key]} ${line.trim()}`.trim();
    }
  }
  return fields;
}

function frontmatterProblems(rel, text, name) {
  const fields = frontmatter(text);
  if (!fields) return [`${rel}:1: no YAML frontmatter`];
  const problems = [];
  if (fields.name !== name) problems.push(`${rel}:1: frontmatter name ${JSON.stringify(fields.name ?? null)} must be ${JSON.stringify(name)}`);
  if (!fields.description) problems.push(`${rel}:1: frontmatter description is missing or empty`);
  return problems;
}

export function validateSkills(root) {
  const problems = [];
  const contract = path.join(root, "references/runtime.md");
  const skills = path.join(root, "skills");
  for (const entry of readdirSync(skills, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
    if (!entry.isDirectory()) continue;
    const file = path.join(skills, entry.name, "SKILL.md");
    const rel = relative(root, file);
    if (!existsSync(file)) {
      problems.push(`${rel}: missing`);
      continue;
    }
    const text = readFileSync(file, "utf8");
    problems.push(...frontmatterProblems(rel, text, entry.name));
    if (!linkTargets(text).some(({ target }) => localPath(file, target)?.resolved === contract)) {
      problems.push(`${rel}: no link to the shared runtime contract references/runtime.md`);
    }
  }
  for (const file of walk(path.join(root, "agents")).filter((name) => name.endsWith(".md"))) {
    problems.push(...frontmatterProblems(relative(root, file), readFileSync(file, "utf8"), path.basename(file, ".md")));
  }
  return problems;
}

const MANIFEST_NAMES = {
  "plugin.json": "pstack",
  ".claude-plugin/plugin.json": "pstack",
  ".codex-plugin/plugin.json": "pstack-codex",
};

export function validateManifests(root) {
  const problems = [];
  for (const [rel, name] of Object.entries(MANIFEST_NAMES)) {
    let text;
    let manifest;
    try {
      text = readFileSync(path.join(root, rel), "utf8");
      manifest = JSON.parse(text);
    } catch (error) {
      problems.push(`${rel}: ${error.message}`);
      continue;
    }
    if (manifest.name !== name) problems.push(`${rel}: name ${JSON.stringify(manifest.name ?? null)} must be ${JSON.stringify(name)}`);
    // An Agent Plugins $schema makes Codex load the checkout as an Agent Plugin,
    // which truncates each injected skill to 8,000 bytes (ADAPTATION.md, 0.15.21).
    if (rel === "plugin.json" && /agent-plugins\.org/i.test(text)) {
      problems.push(`${rel}: references agent-plugins.org; the root manifest stays the Antigravity manifest without the Agent Plugins $schema`);
    }
  }
  return problems;
}

export function checkFork(root) {
  return [...validateManifests(root), ...validateSkills(root), ...validateLinks(root), ...scanDenylist(root)];
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  const root = path.resolve(process.argv[2] ?? path.join(import.meta.dirname, ".."));
  const problems = checkFork(root);
  if (problems.length) {
    console.error(`Fork guards failed:\n${problems.join("\n")}`);
    process.exit(1);
  }
  console.log(`Fork guards passed: ${DENYLIST.length} denylist rules, skill frontmatter and contract links, local Markdown links, manifests.`);
}
