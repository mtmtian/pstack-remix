#!/usr/bin/env node
// Static guards for upstream syncs. Shipped content must not bring back the
// Cursor-only instructions ADAPTATION.md replaced and must keep the local
// decisions it records, every skill outside STANDALONE keeps its shared runtime
// contract, local links resolve, the manifests keep their fork names, and every
// copy of the upstream pin matches UPSTREAM.json.
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
    hint: "use the project's verification harness and the browser the user's or host's instructions name",
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
    pattern: /\bdisable-model-invocation\b|\ballow_implicit_invocation:\s*false\b/,
    allow: ["skills/poteto-help/SKILL.md", "skills/poteto-help/agents/openai.yaml"],
    hint: "skills stay model-invocable on Claude Code and Codex; poteto-help is the one recorded exception",
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

// Guidance skills that use nothing in the shared runtime contract, so they skip
// it as upstream's do. A listed skill that links the contract again is reported,
// so the list cannot outlive the files it describes.
export const STANDALONE = new Set([
  "bro",
  "in-your-own-words",
  "principle-attack-the-premise",
  "principle-boundary-discipline",
  "principle-encode-lessons-in-structure",
  "principle-exhaust-the-design-space",
  "principle-experience-first",
  "principle-explain-the-number",
  "principle-fix-root-causes",
  "principle-foundational-thinking",
  "principle-laziness-protocol",
  "principle-make-operations-idempotent",
  "principle-migrate-callers-then-delete-legacy-apis",
  "principle-minimize-reader-load",
  "principle-model-the-domain",
  "principle-never-block-on-the-human",
  "principle-outcome-oriented-execution",
  "principle-prove-it-works",
  "principle-redesign-from-first-principles",
  "principle-subtract-before-you-add",
  "principle-test-behavior-not-implementation",
  "principle-type-system-discipline",
  "sharpen",
  "tdd",
  "teach",
  "typescript-best-practices",
]);

// The local decisions an upstream sync must keep: each names a file and, where
// wording carries the decision, an anchor in it. `section` is the ADAPTATION.md
// heading that records the decision; a rule whose heading is gone is reported,
// so the table cannot point at a decision the guide no longer records.
export const REQUIRED = [
  {
    id: "replay-after-pass",
    file: "skills/create-verification-skill/SKILL.md",
    pattern: /Write a replay only after a drive's end-state check passed/,
    hint: "a replay is written only from a passing drive",
    section: "maintained-source",
  },
  {
    id: "replay-stale-line",
    file: "skills/create-verification-skill/SKILL.md",
    pattern: /prints `stale: <reason> at <step>`/,
    hint: "a stale replay reports itself instead of being redone",
    section: "maintained-source",
  },
  {
    id: "replay-runs-first",
    file: "skills/maintain-verification-skill/SKILL.md",
    pattern: /Run a feature's replay first when it has one/,
    hint: "a replay runs before any manual drive",
    section: "maintained-source",
  },
  {
    id: "replay-stale-is-finding",
    file: "skills/maintain-verification-skill/SKILL.md",
    pattern: /Never let a passing drive quietly stand in for a stale replay/,
    hint: "a stale replay is a finding, never covered by a passing drive",
    section: "maintained-source",
  },
  {
    id: "statechart-no-tlc-download",
    file: "skills/statechart/scripts/run.ts",
    pattern: /if \(process\.env\.STATECHART_INSTALL !== "1"\)\s*throw new Error\(/,
    hint: "statechart installs TLC and Java with mise only when STATECHART_INSTALL=1 is set",
    section: "local-decisions",
  },
  {
    id: "statechart-absolute-tools",
    file: "skills/statechart/scripts/run.ts",
    pattern: /process\.env\.JAVA\?\.includes\("\/"\) \? path\.resolve\(process\.env\.JAVA\) : process\.env\.JAVA;\n\s*if \(TLA2TOOLS\) return \{ jar: path\.resolve\(TLA2TOOLS\)/,
    hint: "JAVA and TLA2TOOLS resolve to absolute paths, since Java runs in TLC's scratch folder",
    section: "local-decisions",
  },
  {
    id: "statechart-fork-test",
    file: "skills/statechart/scripts/test/fork.test.ts",
    hint: "the no-download gate and the absolute tool paths keep their own test",
    section: "local-decisions",
  },
  {
    id: "statechart-ask-before-install",
    file: "skills/statechart/SKILL.md",
    pattern: /The command downloads nothing on its own\. With `STATECHART_INSTALL=1`[^.]*so ask the user before you set it\./,
    hint: "the skill asks the user before setting STATECHART_INSTALL=1",
    section: "local-decisions",
  },
  {
    id: "statechart-ask-before-renderer",
    file: "skills/statechart/references/render.md",
    pattern: /Installing Pele downloads it, so ask the user first/,
    hint: "the render guide asks the user before installing Pele from npm",
    section: "local-decisions",
  },
  {
    id: "interrogate-policy-panel",
    file: "skills/interrogate/SKILL.md",
    pattern: /Read the `interrogate reviewers` list from the effective policy from `node <plugin-root>\/bin\/config\.mjs show --host <codex\|claude\|t3>` in place of `arena runners`/,
    hint: "interrogate reads its adversaries from the effective policy, not from upstream's model sheet",
    section: "interrogate",
  },
  {
    id: "interrogate-adversaries-rw",
    file: "skills/interrogate/SKILL.md",
    pattern: /Spawn each adversary as a worker that can edit files and run commands in its own worktree; an `xagent:<agent>` adversary runs `rw`[^\n]*adversary runs only the commands in `<plugin-root>\/bin\/xagent-allowed-commands`/,
    hint: "each adversary edits and runs commands in its own worktree; an xagent one runs rw, within its agent's allowlist",
    section: "interrogate",
  },
  {
    id: "interrogate-parent-rerun",
    file: "skills/interrogate/SKILL.md",
    pattern: /Verify each finding per arena Phase F by rerunning its command yourself in that adversary's worktree\./,
    hint: "the parent reruns each finding's command itself, in that adversary's worktree",
    section: "interrogate",
  },
  {
    id: "xagent-skill",
    file: "skills/xagent/SKILL.md",
    hint: "the xagent skill is a local addition with no upstream counterpart",
    section: "maintained-source",
  },
  {
    id: "xagent-allowlist",
    file: "bin/xagent-allowed-commands",
    hint: "xagent writers and the pi guard read their command allowlist here",
    section: "maintained-source",
  },
  {
    id: "runtime-remote-boundary",
    file: "references/runtime.md",
    pattern: /Never push the trunk directly\. Merges, `--auto`, force-pushes to a branch another person or agent works on/,
    hint: "playbooks push their own branches and open PRs, but merges, --auto, and force-pushes to shared branches still need authorization",
    section: "local-decisions",
  },
  {
    id: "babysit-merge-authorization",
    file: "skills/poteto-mode/playbooks/babysit.md",
    pattern: /Babysitting never authorizes merging\. Only an explicit request to merge, land, ship, or merge when ready does\./,
    hint: "only an explicit request authorizes a merge",
    section: "local-decisions",
  },
  {
    id: "auto-merge-on-request",
    file: "skills/poteto-mode/playbooks/shipping.md",
    pattern: /Arm `--auto` [^.]*only when the user asked for merge-when-ready/,
    hint: "`--auto` is armed only when the user asked for merge-when-ready",
    section: "local-decisions",
  },
  {
    id: "orchestrate-merge-authorization",
    file: "skills/poteto-mode/playbooks/orchestrate.md",
    pattern: /carries the PR from build to merge, merging only under the run's merge authorization\./,
    hint: "Orchestrate's PR owners merge only under the run's merge authorization",
    section: "local-decisions",
  },
  {
    id: "autopilot-merge-authorization",
    file: "skills/poteto-mode/playbooks/autopilot-full.md",
    pattern: /Only the operator's explicit authorization to merge this queue, together with your clean verdict, permits the merge\./,
    hint: "owners merge only under the operator's explicit merge authorization",
    section: "local-decisions",
  },
  {
    id: "fast-mode-on-request",
    file: "skills/poteto-mode/SKILL.md",
    pattern: /Fast mode and priority service tiers cost more, so use them only when the user asked\./,
    hint: "fast mode stays off unless the user asks; urgency does not turn it on",
    section: "local-decisions",
  },
  {
    id: "verification-workers-role",
    file: "skills/poteto-mode/SKILL.md",
    pattern: /Verification workers, including a swarm's verify lanes and the \*\*show-me-your-work\*\* handback review, read `verification workers`\./,
    hint: "verifiers read their own role so each host can point it at another vendor",
    section: "local-decisions",
  },
  {
    id: "swarm-verify-role",
    file: "skills/swarm/SKILL.md",
    pattern: /Workers that verify another agent's work, as in a swarm-verify, read `verification workers` instead\./,
    hint: "a swarm's verify lanes read verification workers, not swarm workers",
    section: "local-decisions",
  },
  {
    id: "handback-review-role",
    file: "skills/show-me-your-work/SKILL.md",
    pattern: /spawn a subagent on the `verification workers` role from the effective policy/,
    hint: "the handback review runs on the verification workers role",
    section: "local-decisions",
  },
  {
    id: "t3-no-service-tier",
    file: "references/t3-runtime.md",
    pattern: /The preview adds no speed or service-tier option; do not add one unless the user asked\./,
    hint: "T3 dispatch adds no speed or service tier unless the user asks",
    section: "local-decisions",
  },
  {
    id: "t3-catalog-preview",
    file: "references/t3-runtime.md",
    pattern: /config\.mjs resolve --host t3/,
    hint: "T3 targets come from the catalog-backed preview",
    section: "t3-code-overlay",
  },
  {
    id: "t3-worktree-isolation",
    file: "references/t3-runtime.md",
    pattern: /isolation: "worktree"/,
    hint: "T3 children run in application-owned worktrees",
    section: "t3-code-overlay",
  },
  {
    id: "t3-completed-status",
    file: "references/t3-runtime.md",
    pattern: /status: completed/,
    hint: "a T3 task counts only at terminal status completed",
    section: "t3-code-overlay",
  },
  {
    id: "t3-result-available",
    file: "references/t3-runtime.md",
    pattern: /workState: result_available/,
    hint: "a T3 result counts only once it is available",
    section: "t3-code-overlay",
  },
  {
    id: "t3-owned-child-task",
    file: "references/t3-runtime.md",
    pattern: /every pstack worker is an explicitly T3-owned child task/,
    hint: "pstack workers are explicitly T3-owned child tasks, which T3 itself sends through delegate_task",
    section: "t3-code-overlay",
  },
  {
    id: "t3-cross-family-verification",
    file: "bin/t3-targets.mjs",
    pattern: /const CROSS_FAMILY_ROLE = "verification workers";/,
    hint: "T3 verification workers require --checked and pick a candidate of another model family",
    section: "t3-code-overlay",
  },
  {
    id: "watch-pr-once",
    file: "skills/poteto-mode/scripts/watch-pr/cli.ts",
    pattern: /"--once"/,
    hint: "T3 babysit and shipping rounds classify once with --once instead of polling",
    section: "t3-code-overlay",
  },
  {
    id: "watch-pr-once-test",
    file: "skills/poteto-mode/scripts/watch-pr/once.test.ts",
    hint: "--once keeps its own test",
    section: "t3-code-overlay",
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
    const links = linkTargets(text).some(({ target }) => localPath(file, target)?.resolved === contract);
    if (STANDALONE.has(entry.name)) {
      if (links) problems.push(`${rel}: links the shared runtime contract, but STANDALONE in scripts/check-fork.mjs lists it; remove one`);
    } else if (!links) {
      problems.push(`${rel}: no link to the shared runtime contract references/runtime.md`);
    }
  }
  for (const name of STANDALONE) {
    if (!existsSync(path.join(skills, name))) problems.push(`scripts/check-fork.mjs: STANDALONE lists ${name}, which is not a skill`);
  }
  for (const file of walk(path.join(root, "agents")).filter((name) => name.endsWith(".md"))) {
    problems.push(...frontmatterProblems(relative(root, file), readFileSync(file, "utf8"), path.basename(file, ".md")));
  }
  return problems;
}

// The host manifests version the fork as <upstream version>-shared.<n>; the root
// plugin.json is the Antigravity manifest and carries no version.
const MANIFESTS = {
  "plugin.json": { name: "pstack" },
  ".claude-plugin/plugin.json": { name: "pstack", versioned: true },
  ".codex-plugin/plugin.json": { name: "pstack-codex", versioned: true },
};

// pin is readPin's result, or null when UPSTREAM.json is malformed, which checkFork reports.
export function validateManifests(root, pin) {
  const problems = [];
  for (const [rel, { name, versioned }] of Object.entries(MANIFESTS)) {
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
    const prefix = `${pin?.version}-shared.`;
    if (versioned && pin && !(typeof manifest.version === "string" && manifest.version.startsWith(prefix))) {
      problems.push(`${rel}: upstream-pin: version ${JSON.stringify(manifest.version ?? null)} must start with ${JSON.stringify(prefix)}, after UPSTREAM.json`);
    }
    // An Agent Plugins $schema makes Codex load the checkout as an Agent Plugin,
    // which truncates each injected skill to 8,000 bytes (ADAPTATION.md, Not taken from upstream).
    if (rel === "plugin.json" && /agent-plugins\.org/i.test(text)) {
      problems.push(`${rel}: references agent-plugins.org; the root manifest stays the Antigravity manifest without the Agent Plugins $schema`);
    }
  }
  return problems;
}

// UPSTREAM.json holds the pin. A sync moves it there, and the guards name every
// copy left behind: the sentences in PIN_COPIES and the host manifests' versions.
const PIN_FIELDS = {
  repository: /^https:\/\/github\.com\/[\w.-]+\/[\w.-]+$/,
  path: /^[\w/-]+$/,
  commit: /^[a-f0-9]{40}$/,
  version: /^\d+\.\d+\.\d+$/,
};

export function readPin(root) {
  const pin = JSON.parse(readFileSync(path.join(root, "UPSTREAM.json"), "utf8"));
  const malformed = Object.entries(PIN_FIELDS).filter(([field, pattern]) => typeof pin[field] !== "string" || !pattern.test(pin[field]));
  if (malformed.length) throw new Error(`upstream-pin: malformed ${malformed.map(([field]) => field).join(", ")}`);
  return pin;
}

const PIN_COPIES = {
  "ADAPTATION.md": ({ version, commit }) => `Upstream pstack ${version} at \`${commit}\``,
  "README.md": ({ version, short, tree }) => `upstream pstack ${version} at [\`${short}\`](${tree})`,
  "README.zh-CN.md": ({ version, short, tree }) => `上游 pstack ${version}，跟踪提交 [\`${short}\`](${tree})`,
};

// pin is readPin's result, or null when UPSTREAM.json is malformed, which checkFork reports.
export function validatePin(root, pin) {
  if (!pin) return [];
  const fields = { ...pin, short: pin.commit.slice(0, 8), tree: `${pin.repository}/tree/${pin.commit}/${pin.path}` };
  const problems = [];
  for (const [rel, cite] of Object.entries(PIN_COPIES)) {
    const expected = cite(fields);
    let text;
    try {
      text = readFileSync(path.join(root, rel), "utf8");
    } catch (error) {
      problems.push(`${rel}: ${error.message}`);
      continue;
    }
    if (!text.includes(expected)) problems.push(`${rel}: upstream-pin: no ${JSON.stringify(expected)}; cite the version and commit in UPSTREAM.json`);
  }
  return problems;
}

// GitHub's heading anchors: lowercase, punctuation other than `-` and `_` dropped, spaces to `-`.
function headingSlugs(text) {
  return new Set([...text.matchAll(/^#{1,6}[ \t]+(.+?)[ \t]*$/gm)].map((m) => m[1].toLowerCase().replace(/[^\w\- ]/g, "").replaceAll(" ", "-")));
}

export function validateRequired(root) {
  const guide = path.join(root, "ADAPTATION.md");
  const sections = existsSync(guide) ? headingSlugs(readFileSync(guide, "utf8")) : new Set();
  const problems = [];
  for (const rule of REQUIRED) {
    if (!sections.has(rule.section)) problems.push(`ADAPTATION.md: ${rule.id}: no section #${rule.section} records this decision`);
    const file = path.join(root, rule.file);
    const why = `${rule.hint} (ADAPTATION.md#${rule.section})`;
    if (!existsSync(file)) problems.push(`${rule.file}: ${rule.id}: missing; ${why}`);
    else if (rule.pattern && !rule.pattern.test(readFileSync(file, "utf8"))) problems.push(`${rule.file}: ${rule.id}: no match for ${rule.pattern}; ${why}`);
  }
  return problems;
}

export function checkFork(root) {
  let pin = null;
  const problems = [];
  try {
    pin = readPin(root);
  } catch (error) {
    problems.push(`UPSTREAM.json: ${error.message}`);
  }
  return [...problems, ...validateManifests(root, pin), ...validatePin(root, pin), ...validateSkills(root), ...validateLinks(root), ...scanDenylist(root), ...validateRequired(root)];
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  const root = path.resolve(process.argv[2] ?? path.join(import.meta.dirname, ".."));
  const problems = checkFork(root);
  if (problems.length) {
    console.error(`Fork guards failed:\n${problems.join("\n")}`);
    process.exit(1);
  }
  console.log(`Fork guards passed: ${DENYLIST.length} denylist rules, ${REQUIRED.length} required local decisions, skill frontmatter and contract links, local Markdown links, manifests, upstream pin.`);
}
