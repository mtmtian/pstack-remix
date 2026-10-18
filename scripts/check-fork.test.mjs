import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { cpSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { checkFork, REQUIRED, scanDenylist, validateLinks, validateManifests, validateRequired, validateSkills } from "./check-fork.mjs";

const root = path.resolve(import.meta.dirname, "..");
const cli = path.join(root, "scripts/check-fork.mjs");

function copyRepo(t) {
  const dir = mkdtempSync(path.join(os.tmpdir(), "pstack-fork-guard-"));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  cpSync(root, dir, { recursive: true, filter: (source) => ![".git", "node_modules"].includes(path.basename(source)) });
  return dir;
}

function edit(dir, rel, change) {
  const file = path.join(dir, rel);
  const before = readFileSync(file, "utf8");
  const after = change(before);
  assert.notEqual(after, before, `planting into ${rel} changed nothing`);
  writeFileSync(file, after);
}

test("Given the maintained tree, When the fork guards run, Then they report nothing", () => {
  assert.deepEqual(checkFork(root), []);
});

test("Given upstream wording for each Cursor-only primitive, When it lands in a shipped playbook, Then its rule names the line", (t) => {
  const dir = copyRepo(t);
  const rel = "skills/poteto-mode/playbooks/shipping.md";
  const planted = [
    ["cursor-model-sheet", "Use the `interrogate reviewers` line in pstack-models.mdc."],
    ["fixed-loop", "Re-arm the audit with `/loop 1h`."],
    ["control-drivers", "Drive the UI through control-ui."],
    ["cursor-cloud-agents", "Hand each unit to a Cursor cloud agent."],
    ["cursor-paths", "Resolve poteto-mode from ~/.cursor/plugins/."],
    ["cursor-transcripts", "Read the workspace's agent-transcripts directory."],
    ["cursor-task-tool", "Spawn it with subagent_type: generalPurpose."],
    ["cursor-task-tool", "Pass readonly: false to the writer."],
    ["model-invocation", "Set disable-model-invocation on the skill."],
    ["effort-model-slug", "Default to claude-opus-5-5-xhigh for the judge."],
    ["effort-model-slug", "Run the panel on grok-4.7-xhigh-fast."],
    ["cursor-ui", "Render the chart with /visualize."],
  ];
  let first;
  edit(dir, rel, (text) => {
    const base = text.endsWith("\n") ? text : `${text}\n`;
    first = base.split("\n").length;
    return `${base}${planted.map(([, line]) => line).join("\n")}\n`;
  });

  const problems = scanDenylist(dir);

  for (const [index, [rule]] of planted.entries()) {
    const prefix = `${rel}:${first + index}: ${rule}: `;
    assert.ok(problems.some((problem) => problem.startsWith(prefix)), `missing ${prefix}\n${problems.join("\n")}`);
  }
  assert.ok(problems.every((problem) => problem.startsWith(`${rel}:`)), problems.join("\n"));
});

test("Given an adapter that lists forbidden fields, When its sentence moves into a skill, Then only the skill copy fails", (t) => {
  const dir = copyRepo(t);
  const sentence = readFileSync(path.join(dir, "references/codex-runtime.md"), "utf8")
    .split("\n").find((line) => line.includes("cloud_base_branch"));
  assert.ok(sentence);
  edit(dir, "skills/tdd/SKILL.md", (text) => `${text}\n${sentence}\n`);

  const problems = scanDenylist(dir);

  assert.ok(problems.length > 0);
  assert.ok(problems.every((problem) => problem.startsWith("skills/tdd/SKILL.md:")), problems.join("\n"));
  assert.ok(problems.some((problem) => problem.includes(": cursor-task-tool: ")));
  assert.ok(problems.some((problem) => problem.includes(": cursor-cloud-agents: ")));
});

test("Given an allowed file no longer names its pattern, When scanned, Then the stale allowance is reported", (t) => {
  const dir = copyRepo(t);
  edit(dir, "references/runtime.md", (text) => text.replace("`deslop`, `control-ui`, and `control-cli` dependencies are", "`deslop` dependency is"));

  assert.deepEqual(scanDenylist(dir), [
    "references/runtime.md: control-drivers: allowed here but no longer matches; remove it from the allow list",
  ]);
});

test("Given skills that drift from the fork's contract, When validated, Then each drift is reported", (t) => {
  const dir = copyRepo(t);
  edit(dir, "skills/poteto-mode/SKILL.md", (text) => text.replace("name: poteto-mode", "name: Poteto Mode"));
  edit(dir, "skills/sharpen/SKILL.md", (text) => text.replace(/^description: .*$/m, 'description: ""'));
  edit(dir, "skills/ketchup/SKILL.md", (text) => text.split("\n").filter((line) => !line.includes("references/runtime.md")).join("\n"));
  edit(dir, "agents/comment-sicko.md", (text) => text.replace("name: comment-sicko", "name: Comment Sicko"));
  mkdirSync(path.join(dir, "skills/new-upstream-skill/references"), { recursive: true });
  writeFileSync(path.join(dir, "skills/new-upstream-skill/references/notes.md"), "Notes.\n");

  assert.deepEqual(validateSkills(dir), [
    "skills/ketchup/SKILL.md: no link to the shared runtime contract references/runtime.md",
    "skills/new-upstream-skill/SKILL.md: missing",
    'skills/poteto-mode/SKILL.md:1: frontmatter name "Poteto Mode" must be "poteto-mode"',
    "skills/sharpen/SKILL.md:1: frontmatter description is missing or empty",
    'agents/comment-sicko.md:1: frontmatter name "Comment Sicko" must be "comment-sicko"',
  ]);
});

test("Given broken local links outside code, When validated, Then missing and escaping targets are reported", (t) => {
  const dir = copyRepo(t);
  const rel = "skills/how/SKILL.md";
  let first;
  edit(dir, rel, (text) => {
    const base = text.endsWith("\n") ? text : `${text}\n`;
    first = base.split("\n").length;
    return `${base}${[
      "See [the guide](../../docs/guide/99-missing.md).",
      "See [outside](../../../outside.md).",
      "See [the parent](../../..).",
      "```md",
      "[example](does-not-exist.md)",
      "```",
      "Literal `[example](does-not-exist.md)` stays code. [Web](https://example.com) and [anchor](#how) are not files.",
      "See [the contract](../../references/runtime.md#authorization).",
    ].join("\n")}\n`;
  });

  assert.deepEqual(validateLinks(dir), [
    `${rel}:${first}: link ../../docs/guide/99-missing.md: missing`,
    `${rel}:${first + 1}: link ../../../outside.md: escapes the repository`,
    `${rel}:${first + 2}: link ../../..: escapes the repository`,
  ]);
});

test("Given upstream's Agent Plugins root manifest, When the guards run, Then the manifest is rejected and the CLI fails", (t) => {
  const dir = copyRepo(t);
  edit(dir, "plugin.json", (text) => text.replace("{\n", '{\n  "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",\n'));
  edit(dir, ".codex-plugin/plugin.json", (text) => text.replace('"name": "pstack-codex"', '"name": "pstack"'));

  assert.deepEqual(validateManifests(dir), [
    "plugin.json: references agent-plugins.org; the root manifest stays the Antigravity manifest without the Agent Plugins $schema",
    '.codex-plugin/plugin.json: name "pstack" must be "pstack-codex"',
  ]);
  const failed = spawnSync(process.execPath, [cli, dir], { encoding: "utf8" });
  assert.equal(failed.status, 1, failed.stdout);
  assert.match(failed.stderr, /^plugin\.json: references agent-plugins\.org/m);
});

test("Given a clean copy, When the CLI runs on it, Then it exits 0", (t) => {
  const dir = copyRepo(t);
  const passed = spawnSync(process.execPath, [cli, dir], { encoding: "utf8" });
  assert.equal(passed.status, 0, passed.stderr);
  assert.match(passed.stdout, /^Fork guards passed/);
});

// What a sync loses for each required decision: [rule, file, local text, what replaces it].
// Replacements quote upstream's wording at the pin where upstream has its own; null text deletes the file.
const DROPPED = [
  ["replay-after-pass", "skills/create-verification-skill/SKILL.md", "Write a replay only after a drive's end-state check passed", ""],
  ["replay-stale-line", "skills/create-verification-skill/SKILL.md", "`stale: <reason> at <step>`", "a failure"],
  ["replay-runs-first", "skills/maintain-verification-skill/SKILL.md", "Run a feature's replay first when it has one", ""],
  ["replay-stale-is-finding", "skills/maintain-verification-skill/SKILL.md", "Never let a passing drive quietly stand in for a stale replay", ""],
  ["xagent-skill", "skills/xagent/SKILL.md", null],
  ["xagent-allowlist", "bin/xagent-allowed-commands", null],
  ["pr-authorization", "skills/poteto-mode/playbooks/opening-a-pr.md", "Use when PR delivery is requested or otherwise explicitly authorized.", "Invoked at the end of every other playbook."],
  ["babysit-write-authorization", "skills/poteto-mode/playbooks/babysit.md", "only to the extent explicitly authorized", ""],
  ["babysit-merge-authorization", "skills/poteto-mode/playbooks/babysit.md", "Babysitting never authorizes merging. ", ""],
  ["auto-merge-on-request", "skills/poteto-mode/playbooks/shipping.md", "only when the user asked for merge-when-ready, and only on a PR", "only on a PR"],
  ["autopilot-push-authorization", "skills/poteto-mode/playbooks/autopilot-full.md", "Within the program's push authorization, force-push", "Force-push"],
  ["autopilot-merge-authorization", "skills/poteto-mode/playbooks/autopilot-full.md", "Only the operator's explicit authorization to merge this queue, together with your clean verdict, permits the merge.", "Green CI alone never authorizes a merge."],
  ["fast-mode-on-request", "skills/poteto-mode/SKILL.md", "Fast mode and priority service tiers cost more, so use them only when the user asked.", "Use fast mode only when the job is urgent, meaning CI or trunk is red or a person is blocked on the result right now."],
  ["verification-workers-role", "skills/poteto-mode/SKILL.md", "Verification workers, including a swarm's verify lanes and the **show-me-your-work** handback review, read `verification workers`.", ""],
  ["swarm-verify-role", "skills/swarm/SKILL.md", "Workers that verify another agent's work, as in a swarm-verify, read `verification workers` instead.", ""],
  ["handback-review-role", "skills/show-me-your-work/SKILL.md", "on the `verification workers` role from the effective policy, on a different available model family", "on a different model family"],
  ["t3-no-service-tier", "references/t3-runtime.md", "The preview adds no speed or service-tier option; do not add one unless the user asked.", ""],
  ["t3-catalog-preview", "references/t3-runtime.md", "config.mjs resolve --host t3", "removed-by-sync"],
  ["t3-worktree-isolation", "references/t3-runtime.md", 'isolation: "worktree"', "removed-by-sync"],
  ["t3-completed-status", "references/t3-runtime.md", "status: completed", "removed-by-sync"],
  ["t3-result-available", "references/t3-runtime.md", "workState: result_available", "removed-by-sync"],
  ["watch-pr-once", "skills/poteto-mode/scripts/watch-pr/cli.ts", '"--once"', ""],
  ["watch-pr-once-test", "skills/poteto-mode/scripts/watch-pr/once.test.ts", null],
];

test("Given a sync that drops one recorded local decision, When guarded, Then only that decision's rule fails and cites the guide", (t) => {
  assert.deepEqual(DROPPED.map(([rule]) => rule).sort(), REQUIRED.map((rule) => rule.id).sort(), "each required rule needs one planted loss here");
  const dir = copyRepo(t);
  for (const [rule, rel, text, replacement] of DROPPED) {
    const file = path.join(dir, rel);
    const original = readFileSync(file, "utf8");
    if (text === null) rmSync(file);
    else edit(dir, rel, (body) => body.split(text).join(replacement));

    const problems = validateRequired(dir);

    assert.equal(problems.length, 1, `${rule}:\n${problems.join("\n")}`);
    assert.ok(problems[0].startsWith(`${rel}: ${rule}: ${text === null ? "missing" : "no match for "}`), problems[0]);
    assert.match(problems[0], /\(ADAPTATION\.md#[\w-]+\)$/);
    writeFileSync(file, original);
  }
});

test("Given the guide renames a section that rules cite, When guarded, Then each citing rule is reported", (t) => {
  const dir = copyRepo(t);
  edit(dir, "ADAPTATION.md", (text) => text.replace("## T3 Code overlay", "## T3 overlay"));

  assert.deepEqual(validateRequired(dir), [
    "t3-catalog-preview",
    "t3-worktree-isolation",
    "t3-completed-status",
    "t3-result-available",
    "watch-pr-once",
    "watch-pr-once-test",
  ].map((rule) => `ADAPTATION.md: ${rule}: no section #t3-code-overlay records this decision`));
});
