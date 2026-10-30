import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

const here = import.meta.dirname;
const entry = path.join(here, "../statechart.ts");
const counter = path.join(here, "corpus/Counter");

const scratch = () => fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "statechart-fork-")));

const script = (file: string, body: string) => {
  fs.writeFileSync(file, `#!/bin/sh\n${body}\n`);
  fs.chmodSync(file, 0o755);
};

// A mise that has nothing installed and logs every call, so a test sees whether the command asked it to install.
const fakeMise = (installStatus: number) => {
  const dir = scratch();
  const log = path.join(dir, "mise.log");
  script(
    path.join(dir, "mise"),
    `echo "$*" >> '${log}'\ncase "$1" in install) exit ${installStatus} ;; *) exit 1 ;; esac`,
  );
  return { dir, log };
};

const runOn = (cwd: string, env: NodeJS.ProcessEnv) => {
  const { TLA2TOOLS: _jar, JAVA: _java, STATECHART_INSTALL: _install, ...rest } = process.env;
  return spawnSync(
    process.execPath,
    [entry, path.join(counter, "Counter.tla"), "--out", path.join(scratch(), "out")],
    { cwd, encoding: "utf8", env: { ...rest, ...env } },
  );
};

test("without STATECHART_INSTALL, a missing TLC stops the command with the install command and installs nothing", () => {
  const mise = fakeMise(0);
  const r = runOn(scratch(), { PATH: `${mise.dir}${path.delimiter}${process.env.PATH}` });
  assert.equal(r.status, 2, r.stderr);
  assert.match(r.stderr, /downloads nothing unless STATECHART_INSTALL=1 is set; then it runs: mise install java@/);
  assert.doesNotMatch(fs.readFileSync(mise.log, "utf8"), /^install\b/m);
});

test("STATECHART_INSTALL=1 lets the command install TLC and Java with mise", () => {
  const mise = fakeMise(1);
  const r = runOn(scratch(), {
    PATH: `${mise.dir}${path.delimiter}${process.env.PATH}`,
    STATECHART_INSTALL: "1",
  });
  assert.equal(r.status, 2, r.stderr);
  assert.match(r.stderr, /mise install failed/);
  assert.match(fs.readFileSync(mise.log, "utf8"), /^install java@\S+ http:tla2tools/m);
});

test("relative JAVA and TLA2TOOLS resolve from where the command started, not from TLC's scratch folder", () => {
  const cwd = scratch();
  const log = path.join(cwd, "java.log");
  fs.mkdirSync(path.join(cwd, "bin"));
  script(path.join(cwd, "bin/java"), `printf '%s\\n' "$@" >> '${log}'\nexit 1`);
  const r = runOn(cwd, { JAVA: "bin/java", TLA2TOOLS: "tla2tools.jar" });
  assert.equal(r.status, 2, r.stderr);
  assert.match(r.stderr, /SANY could not read/);
  const args = fs.readFileSync(log, "utf8").split("\n");
  assert.equal(args[args.indexOf("-cp") + 1], path.join(cwd, "tla2tools.jar"));
});
