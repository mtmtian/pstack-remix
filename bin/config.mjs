#!/usr/bin/env node

import { closeSync, existsSync, fsyncSync, mkdirSync, openSync, readFileSync, renameSync, unlinkSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { fileURLToPath } from "node:url";
import { resolveT3Targets } from "./t3-targets.mjs";

const HOSTS = ["codex", "claude"];
// T3 Code orchestrates over a Codex or Claude host; its section is optional so existing files stay valid.
const T3 = "t3";
const UPDATE_HOSTS = [...HOSTS, T3];
const SHOW_HOSTS = [...UPDATE_HOSTS, "antigravity"];
const COMMON_MODEL_VALUES = new Set(["inherit-parent", "auto"]);
// External agents run through the xagent CLI identically from every host, so they may be shared policy.
// An optional /<model> after the agent is that CLI's own model ID; bin/xagent mirrors the model pattern.
const XAGENT_VALUE = /^xagent:[a-z][a-z0-9-]*(?:\/[A-Za-z0-9][A-Za-z0-9_.:@+[\]/-]*)?$/;
// <providerInstanceId>/<modelId> from T3's orchestrator_capabilities; model IDs may contain slashes.
const T3_TARGET = /^[A-Za-z][A-Za-z0-9_-]*\/[^\s/]\S*$/;
const REASONING_EFFORTS = new Set(["low", "medium", "high", "xhigh", "max"]);
const DEFAULT_PANEL = ["inherit-parent", "inherit-parent"];
// External agents that must join every panel, so a per-panel or per-host list cannot leave them out.
const REQUIRED_MEMBERS = "required_panel_members";
// External agents whose unresolved outcome is reported as a gap instead of blocking their panel.
const AUXILIARY_MEMBERS = "auxiliary_panel_members";
const MEMBER_LISTS = [REQUIRED_MEMBERS, AUXILIARY_MEMBERS];
// The highest effort each external agent's CLI accepts; the parent passes it the lower of the job's effort and this cap.
const EFFORT_CAPS = "xagent_effort_caps";
const XAGENT_NAME = /^[a-z][a-z0-9-]*$/;
// Fields that only common policy may set, because xagent runs the same way from every host.
const SHARED_FIELDS = [...MEMBER_LISTS, EFFORT_CAPS];

export function getDefaultConfigPath(homeDir = homedir()) {
  return path.join(homeDir, ".config", "pstack", "config.json");
}

function getDefaultLegacyPaths(homeDir = homedir()) {
  return {
    codex: path.join(homeDir, ".codex", "pstack", "models.json"),
    claude: path.join(homeDir, ".claude", "pstack", "models.json"),
  };
}

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function requireObject(value, label) {
  if (!isObject(value)) throw new Error(`${label} must be a JSON object`);
}

function parseJson(text, label) {
  try {
    return JSON.parse(text);
  } catch (error) {
    throw new Error(`${label} is not valid JSON: ${error.message}`);
  }
}

function isCommonModelValue(value) {
  return COMMON_MODEL_VALUES.has(value) || XAGENT_VALUE.test(value);
}

// Throws when a nonempty string is not allowed in this scope; Codex and Claude host values stay free-form,
// except that any xagent: value reaches bin/xagent and must parse as one.
function checkModelValue(value, scope, field) {
  if (value.startsWith("xagent:") && !XAGENT_VALUE.test(value)) {
    throw new Error(`${field} must be xagent:<agent> or xagent:<agent>/<model>`);
  }
  if (scope === "common" && !isCommonModelValue(value)) {
    throw new Error(`${field} must be inherit-parent, auto or xagent:<agent>[/<model>] in common policy`);
  }
  if (scope === T3 && !isCommonModelValue(value) && !T3_TARGET.test(value)) {
    throw new Error(`${field} must be inherit-parent, auto, xagent:<agent>[/<model>] or <providerInstanceId>/<modelId> for T3`);
  }
}

function scopeOf(host) {
  if (host === undefined) return "common";
  return host === T3 ? T3 : "host";
}

function checkRoleValue(value, scope, field) {
  if (scope === T3 && isObject(value)) {
    const candidates = value.candidates;
    if (Object.keys(value).length !== 1 || !Array.isArray(candidates) || !candidates.length) {
      throw new Error(`${field} must contain only a nonempty candidates array`);
    }
    const providers = new Set();
    for (const entry of candidates) {
      if (typeof entry !== "string" || !T3_TARGET.test(entry) || entry.startsWith("xagent:")) {
        throw new Error(`${field}.candidates entries must be T3 <providerInstanceId>/<modelId> targets`);
      }
      const provider = entry.split("/", 1)[0];
      if (providers.has(provider)) throw new Error(`${field}.candidates must have one target per provider`);
      providers.add(provider);
    }
    return;
  }
  if (typeof value !== "string" || !value.trim()) throw new Error(`${field} must be a nonempty string${scope === T3 ? " or candidates object" : ""}`);
  checkModelValue(value, scope, field);
}

function validateRoles(roles, scope, label) {
  requireObject(roles, `${label}.roles`);
  for (const [name, value] of Object.entries(roles)) {
    if (!name.trim()) throw new Error(`${label}.roles keys must not be empty`);
    checkRoleValue(value, scope, `${label}.roles.${name}`);
  }
}

function validatePanels(panels, scope, label) {
  requireObject(panels, `${label}.panels`);
  for (const [name, values] of Object.entries(panels)) {
    if (!name.trim()) throw new Error(`${label}.panels keys must not be empty`);
    if (!Array.isArray(values) || values.length === 0) throw new Error(`${label}.panels.${name} must be a nonempty array`);
    for (const value of values) {
      if (typeof value !== "string" || !value.trim()) throw new Error(`${label}.panels.${name} entries must be nonempty strings`);
      checkModelValue(value, scope, `${label}.panels.${name} entries`);
    }
  }
}

function validateEffort(policy, label) {
  if (Object.hasOwn(policy, "reasoning_effort") && !REASONING_EFFORTS.has(policy.reasoning_effort)) {
    throw new Error(`${label}.reasoning_effort must be one of ${[...REASONING_EFFORTS].join(", ")}`);
  }
}

// null means unset, in a stored config as in a patch.
function validateSharedFields(policy, scope, label) {
  for (const key of SHARED_FIELDS) {
    if (!Object.hasOwn(policy, key)) continue;
    const field = `${label}.${key}`;
    if (scope !== "common") throw new Error(`${field} is shared policy and cannot be set per host`);
    const value = policy[key];
    if (value === null) continue;
    if (key === EFFORT_CAPS) validateEffortCaps(value, field);
    else validateMemberList(value, field);
  }
}

function validateMemberList(members, field) {
  if (!Array.isArray(members) || members.length === 0) throw new Error(`${field} must be a nonempty array or null`);
  for (const member of members) {
    if (typeof member !== "string" || !XAGENT_VALUE.test(member)) throw new Error(`${field} entries must be xagent:<agent>[/<model>]`);
  }
  if (new Set(members).size !== members.length) throw new Error(`${field} entries must be unique`);
}

function validateEffortCaps(caps, field) {
  if (!isObject(caps) || Object.keys(caps).length === 0) throw new Error(`${field} must be a nonempty object or null`);
  for (const [agent, effort] of Object.entries(caps)) {
    if (!XAGENT_NAME.test(agent)) throw new Error(`${field} keys must be xagent agent names`);
    if (!REASONING_EFFORTS.has(effort)) throw new Error(`${field}.${agent} must be one of ${[...REASONING_EFFORTS].join(", ")}`);
  }
}

function validatePolicy(policy, scope, label) {
  requireObject(policy, label);
  if (!Object.hasOwn(policy, "roles") || !Object.hasOwn(policy, "panels")) {
    throw new Error(`${label} must contain roles and panels objects`);
  }
  validateRoles(policy.roles, scope, label);
  validatePanels(policy.panels, scope, label);
  validateEffort(policy, label);
  validateSharedFields(policy, scope, label);
}

function validateConfig(config) {
  requireObject(config, "config");
  if (config.version !== 1) throw new Error("config.version must be 1");
  validatePolicy(config, "common", "config");
  requireObject(config.hosts, "config.hosts");
  for (const host of HOSTS) validatePolicy(config.hosts[host], "host", `config.hosts.${host}`);
  if (Object.hasOwn(config.hosts, T3)) validatePolicy(config.hosts[T3], T3, `config.hosts.${T3}`);
  return config;
}

function validatePatch(patch, scope, label) {
  requireObject(patch, label);
  const allowed = new Set(["roles", "panels", "reasoning_effort", ...SHARED_FIELDS]);
  for (const key of Object.keys(patch)) {
    if (!allowed.has(key)) throw new Error(`${label}.${key} is not a supported update field`);
  }
  if (Object.hasOwn(patch, "roles")) {
    requireObject(patch.roles, `${label}.roles`);
    for (const [name, value] of Object.entries(patch.roles)) {
      if (!name.trim()) throw new Error(`${label}.roles keys must not be empty`);
      if (value === null) continue;
      checkRoleValue(value, scope, `${label}.roles.${name}`);
    }
  }
  if (Object.hasOwn(patch, "panels")) {
    requireObject(patch.panels, `${label}.panels`);
    for (const [name, values] of Object.entries(patch.panels)) {
      if (!name.trim()) throw new Error(`${label}.panels keys must not be empty`);
      if (values === null) continue;
      if (!Array.isArray(values) || values.length === 0) throw new Error(`${label}.panels.${name} must be a nonempty array or null`);
      for (const value of values) {
        if (typeof value !== "string" || !value.trim()) throw new Error(`${label}.panels.${name} entries must be nonempty strings`);
        checkModelValue(value, scope, `${label}.panels.${name} entries`);
      }
    }
  }
  validateSharedFields(patch, scope, label);
  if (Object.hasOwn(patch, "reasoning_effort") && patch.reasoning_effort !== null && !REASONING_EFFORTS.has(patch.reasoning_effort)) {
    throw new Error(`${label}.reasoning_effort must be one of ${[...REASONING_EFFORTS].join(", ")} or null`);
  }
}

function defaultConfig() {
  return {
    version: 1,
    roles: {},
    panels: {},
    hosts: {
      codex: { roles: {}, panels: {} },
      claude: { roles: {}, panels: {} },
    },
  };
}

function readConfig(configPath) {
  if (!existsSync(configPath)) return null;
  return validateConfig(parseJson(readFileSync(configPath, "utf8"), `Config ${configPath}`));
}

function withLock(configPath, callback) {
  mkdirSync(path.dirname(configPath), { recursive: true, mode: 0o700 });
  const lockPath = `${configPath}.lock`;
  let lockFd;
  try {
    lockFd = openSync(lockPath, "wx", 0o600);
  } catch (error) {
    if (error.code === "EEXIST") throw new Error(`Config is locked by another writer (${lockPath}); retry after it finishes`);
    throw error;
  }
  try {
    writeFileSync(lockFd, `${process.pid}\n`);
    return callback();
  } finally {
    closeSync(lockFd);
    try {
      unlinkSync(lockPath);
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
    }
  }
}

function atomicWrite(configPath, config) {
  const tempPath = `${configPath}.${process.pid}.${randomUUID()}.tmp`;
  let fd;
  try {
    fd = openSync(tempPath, "wx", 0o600);
    writeFileSync(fd, `${JSON.stringify(config, null, 2)}\n`);
    fsyncSync(fd);
    closeSync(fd);
    fd = undefined;
    renameSync(tempPath, configPath);
  } catch (error) {
    if (fd !== undefined) closeSync(fd);
    try {
      unlinkSync(tempPath);
    } catch (cleanupError) {
      if (cleanupError.code !== "ENOENT") throw cleanupError;
    }
    throw error;
  }
}

function cloneJson(value) {
  return JSON.parse(JSON.stringify(value));
}

function importLegacyHost(legacyPath, host) {
  if (!legacyPath || !existsSync(legacyPath)) return { roles: {}, panels: {} };
  const legacy = parseJson(readFileSync(legacyPath, "utf8"), `Legacy ${host} config ${legacyPath}`);
  requireObject(legacy, `Legacy ${host} config`);
  const migrated = { roles: {}, panels: {}, ...legacy };
  validatePolicy(migrated, "host", `Legacy ${host} config`);
  return migrated;
}

export function initConfig({ configPath = getDefaultConfigPath(), legacyPaths = getDefaultLegacyPaths() } = {}) {
  configPath = path.resolve(configPath);
  return withLock(configPath, () => {
    const current = readConfig(configPath);
    if (current) return { path: configPath, created: false };

    const config = defaultConfig();
    for (const host of HOSTS) config.hosts[host] = importLegacyHost(legacyPaths?.[host], host);
    validateConfig(config);
    atomicWrite(configPath, config);
    return { path: configPath, created: true };
  });
}

function applyPatch(policy, patch) {
  for (const section of ["roles", "panels"]) {
    if (!Object.hasOwn(patch, section)) continue;
    for (const [key, value] of Object.entries(patch[section])) {
      if (value === null) delete policy[section][key];
      else Object.defineProperty(policy[section], key, {
        value: cloneJson(value),
        enumerable: true,
        configurable: true,
        writable: true,
      });
    }
  }
  for (const key of ["reasoning_effort", ...SHARED_FIELDS]) {
    if (!Object.hasOwn(patch, key)) continue;
    if (patch[key] === null) delete policy[key];
    else policy[key] = cloneJson(patch[key]);
  }
}

export function updateConfig({ configPath = getDefaultConfigPath(), host, patch } = {}) {
  configPath = path.resolve(configPath);
  if (host !== undefined && !UPDATE_HOSTS.includes(host)) throw new Error(`host must be one of ${UPDATE_HOSTS.join(" or ")}`);
  validatePatch(patch, scopeOf(host), "input");

  return withLock(configPath, () => {
    const config = readConfig(configPath) ?? defaultConfig();
    if (host === T3) config.hosts[T3] ??= { roles: {}, panels: {} };
    applyPatch(host ? config.hosts[host] : config, patch);
    validateConfig(config);
    atomicWrite(configPath, config);
    return { path: configPath, updated: true, host: host ?? null };
  });
}

export function showConfig({ configPath = getDefaultConfigPath(), host } = {}) {
  configPath = path.resolve(configPath);
  if (!SHOW_HOSTS.includes(host)) throw new Error(`host must be one of ${SHOW_HOSTS.join(" or ")}`);
  const config = readConfig(configPath) ?? defaultConfig();
  // Antigravity gets a read-only view of shared policy. T3 layers only its own section over common policy,
  // never the Codex or Claude overrides of the host it runs on.
  const hostPolicy = host === "antigravity" ? { roles: {}, panels: {} } : config.hosts[host] ?? { roles: {}, panels: {} };
  const required = config[REQUIRED_MEMBERS] ?? [];
  const withRequired = (panel) => [...panel, ...required.filter((member) => !panel.includes(member))];
  const panels = { ...config.panels, ...hostPolicy.panels };
  return {
    path: configPath,
    exists: existsSync(configPath),
    host,
    effective: {
      roles: { ...config.roles, ...hostPolicy.roles },
      panels: Object.fromEntries(Object.entries(panels).map(([name, panel]) => [name, withRequired(panel)])),
      [REQUIRED_MEMBERS]: [...required],
      [AUXILIARY_MEMBERS]: [...(config[AUXILIARY_MEMBERS] ?? [])],
      [EFFORT_CAPS]: { ...config[EFFORT_CAPS] },
      reasoning_effort: hostPolicy.reasoning_effort ?? config.reasoning_effort ?? null,
      defaultModel: "inherit-parent",
      defaultPanel: withRequired(DEFAULT_PANEL),
    },
  };
}

function parseOptions(args, allowed) {
  const values = {};
  for (let i = 0; i < args.length; i += 1) {
    const flag = args[i];
    if (!flag.startsWith("--")) throw new Error(`Unexpected argument: ${flag}`);
    const key = flag.slice(2);
    if (!allowed.has(key)) throw new Error(`Unknown option: ${flag}`);
    if (Object.hasOwn(values, key)) throw new Error(`Option ${flag} may only be provided once`);
    const value = args[i + 1];
    if (value === undefined || value.startsWith("--")) throw new Error(`Option ${flag} requires a value`);
    values[key] = value;
    i += 1;
  }
  return values;
}

function requireShowHost(host) {
  if (!SHOW_HOSTS.includes(host)) throw new Error(`--host must be ${SHOW_HOSTS.join(" or ")}`);
  return host;
}

function printJson(value) {
  process.stdout.write(`${JSON.stringify(value, null, 2)}\n`);
}

function runCli(args) {
  const [command, ...rest] = args;
  if (command === "resolve") {
    const options = parseOptions(rest, new Set(["host", "config", "catalog", "role", "panel", "effort", "provider", "checked"]));
    if (options.host !== T3) throw new Error("resolve requires --host t3");
    if (!options.catalog) throw new Error("resolve requires --catalog JSON-file from orchestrator_capabilities");
    if (options.effort !== undefined && !REASONING_EFFORTS.has(options.effort)) {
      throw new Error(`effort must be one of ${[...REASONING_EFFORTS].join(", ")}`);
    }
    const shown = showConfig({ host: T3, configPath: options.config ?? getDefaultConfigPath() });
    const catalog = parseJson(readFileSync(path.resolve(options.catalog), "utf8"), `Catalog ${options.catalog}`);
    const plan = resolveT3Targets(shown.effective, catalog, options);
    printJson({ path: shown.path, host: T3, ...plan });
    return;
  }
  if (command === "show") {
    const options = parseOptions(rest, new Set(["host", "config"]));
    printJson(showConfig({ host: requireShowHost(options.host), configPath: options.config ?? getDefaultConfigPath() }));
    return;
  }
  if (command === "init") {
    const options = parseOptions(rest, new Set(["config"]));
    const homeDir = homedir();
    printJson(initConfig({ configPath: options.config ?? getDefaultConfigPath(homeDir), legacyPaths: getDefaultLegacyPaths(homeDir) }));
    return;
  }
  if (command === "update") {
    const options = parseOptions(rest, new Set(["host", "input", "config"]));
    if (!options.input) throw new Error("update requires explicit --input JSON-file");
    const patch = parseJson(readFileSync(path.resolve(options.input), "utf8"), `Input ${options.input}`);
    printJson(updateConfig({ host: options.host, patch, configPath: options.config ?? getDefaultConfigPath() }));
    return;
  }
  throw new Error("Usage: config.mjs show --host codex|claude|t3|antigravity [--config path] | resolve --host t3 --catalog JSON-file (--role name | --panel name) [--effort level] [--provider candidate-provider | --checked entry-or-model] [--config path] | init [--config path] | update [--host codex|claude|t3] --input JSON-file [--config path]");
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    runCli(process.argv.slice(2));
  } catch (error) {
    process.stderr.write(`${error.message}\n`);
    process.exitCode = 1;
  }
}
