#!/usr/bin/env node

import { closeSync, existsSync, fsyncSync, mkdirSync, openSync, readFileSync, renameSync, unlinkSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { fileURLToPath } from "node:url";

const HOSTS = ["codex", "claude"];
const COMMON_MODEL_VALUES = new Set(["inherit-parent", "auto"]);
// External agents run through the xagent CLI identically from every host, so they may be shared policy.
const XAGENT_VALUE = /^xagent:[a-z][a-z0-9-]*$/;
const REASONING_EFFORTS = new Set(["low", "medium", "high", "xhigh", "max"]);
const DEFAULT_PANEL = ["inherit-parent", "inherit-parent"];
// External agents that must join every panel, so a per-panel or per-host list cannot leave them out.
const REQUIRED_MEMBERS = "required_panel_members";

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

function validateRoles(roles, scope, label) {
  requireObject(roles, `${label}.roles`);
  for (const [name, value] of Object.entries(roles)) {
    if (!name.trim()) throw new Error(`${label}.roles keys must not be empty`);
    if (typeof value !== "string" || !value.trim()) throw new Error(`${label}.roles.${name} must be a nonempty string`);
    if (scope === "common" && !isCommonModelValue(value)) {
      throw new Error(`${label}.roles.${name} must be inherit-parent, auto or xagent:<agent> in common policy`);
    }
  }
}

function validatePanels(panels, scope, label) {
  requireObject(panels, `${label}.panels`);
  for (const [name, values] of Object.entries(panels)) {
    if (!name.trim()) throw new Error(`${label}.panels keys must not be empty`);
    if (!Array.isArray(values) || values.length === 0) throw new Error(`${label}.panels.${name} must be a nonempty array`);
    for (const value of values) {
      if (typeof value !== "string" || !value.trim()) throw new Error(`${label}.panels.${name} entries must be nonempty strings`);
      if (scope === "common" && !isCommonModelValue(value)) {
        throw new Error(`${label}.panels.${name} entries must be inherit-parent, auto or xagent:<agent> in common policy`);
      }
    }
  }
}

function validateEffort(policy, label) {
  if (Object.hasOwn(policy, "reasoning_effort") && !REASONING_EFFORTS.has(policy.reasoning_effort)) {
    throw new Error(`${label}.reasoning_effort must be one of ${[...REASONING_EFFORTS].join(", ")}`);
  }
}

// null means unset, in a stored config as in a patch.
function validateRequiredMembers(policy, scope, label) {
  if (!Object.hasOwn(policy, REQUIRED_MEMBERS)) return;
  const field = `${label}.${REQUIRED_MEMBERS}`;
  if (scope !== "common") throw new Error(`${field} is shared policy and cannot be set per host`);
  const members = policy[REQUIRED_MEMBERS];
  if (members === null) return;
  if (!Array.isArray(members) || members.length === 0) throw new Error(`${field} must be a nonempty array or null`);
  for (const member of members) {
    if (typeof member !== "string" || !XAGENT_VALUE.test(member)) throw new Error(`${field} entries must be xagent:<agent>`);
  }
  if (new Set(members).size !== members.length) throw new Error(`${field} entries must be unique`);
}

function validatePolicy(policy, scope, label) {
  requireObject(policy, label);
  if (!Object.hasOwn(policy, "roles") || !Object.hasOwn(policy, "panels")) {
    throw new Error(`${label} must contain roles and panels objects`);
  }
  validateRoles(policy.roles, scope, label);
  validatePanels(policy.panels, scope, label);
  validateEffort(policy, label);
  validateRequiredMembers(policy, scope, label);
}

function validateConfig(config) {
  requireObject(config, "config");
  if (config.version !== 1) throw new Error("config.version must be 1");
  validatePolicy(config, "common", "config");
  requireObject(config.hosts, "config.hosts");
  for (const host of HOSTS) validatePolicy(config.hosts[host], "host", `config.hosts.${host}`);
  return config;
}

function validatePatch(patch, scope, label) {
  requireObject(patch, label);
  const allowed = new Set(["roles", "panels", "reasoning_effort", REQUIRED_MEMBERS]);
  for (const key of Object.keys(patch)) {
    if (!allowed.has(key)) throw new Error(`${label}.${key} is not a supported update field`);
  }
  if (Object.hasOwn(patch, "roles")) {
    requireObject(patch.roles, `${label}.roles`);
    for (const [name, value] of Object.entries(patch.roles)) {
      if (!name.trim()) throw new Error(`${label}.roles keys must not be empty`);
      if (value === null) continue;
      if (typeof value !== "string" || !value.trim()) throw new Error(`${label}.roles.${name} must be a nonempty string or null`);
      if (scope === "common" && !isCommonModelValue(value)) {
        throw new Error(`${label}.roles.${name} must be inherit-parent, auto or xagent:<agent> in common policy`);
      }
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
        if (scope === "common" && !isCommonModelValue(value)) {
          throw new Error(`${label}.panels.${name} entries must be inherit-parent, auto or xagent:<agent> in common policy`);
        }
      }
    }
  }
  validateRequiredMembers(patch, scope, label);
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
  for (const key of ["reasoning_effort", REQUIRED_MEMBERS]) {
    if (!Object.hasOwn(patch, key)) continue;
    if (patch[key] === null) delete policy[key];
    else policy[key] = cloneJson(patch[key]);
  }
}

export function updateConfig({ configPath = getDefaultConfigPath(), host, patch } = {}) {
  configPath = path.resolve(configPath);
  if (host !== undefined && !HOSTS.includes(host)) throw new Error(`host must be one of ${HOSTS.join(" or ")}`);
  const scope = host ? "host" : "common";
  validatePatch(patch, scope, "input");

  return withLock(configPath, () => {
    const config = readConfig(configPath) ?? defaultConfig();
    applyPatch(host ? config.hosts[host] : config, patch);
    validateConfig(config);
    atomicWrite(configPath, config);
    return { path: configPath, updated: true, host: host ?? null };
  });
}

export function showConfig({ configPath = getDefaultConfigPath(), host } = {}) {
  configPath = path.resolve(configPath);
  if (!HOSTS.includes(host)) throw new Error(`host must be one of ${HOSTS.join(" or ")}`);
  const config = readConfig(configPath) ?? defaultConfig();
  const hostPolicy = config.hosts[host];
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

function requireHost(host) {
  if (!HOSTS.includes(host)) throw new Error(`--host must be ${HOSTS.join(" or ")}`);
  return host;
}

function printJson(value) {
  process.stdout.write(`${JSON.stringify(value, null, 2)}\n`);
}

function runCli(args) {
  const [command, ...rest] = args;
  if (command === "show") {
    const options = parseOptions(rest, new Set(["host", "config"]));
    printJson(showConfig({ host: requireHost(options.host), configPath: options.config ?? getDefaultConfigPath() }));
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
  throw new Error("Usage: config.mjs show --host codex|claude [--config path] | init [--config path] | update [--host codex|claude] --input JSON-file [--config path]");
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    runCli(process.argv.slice(2));
  } catch (error) {
    process.stderr.write(`${error.message}\n`);
    process.exitCode = 1;
  }
}
