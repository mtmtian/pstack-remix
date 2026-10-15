import { afterEach, describe, expect, it } from "bun:test";
import {
  chmod,
  mkdir,
  mkdtemp,
  readFile,
  readdir,
  rm,
  writeFile,
} from "node:fs/promises";
import { realpathSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  NotFoundError,
  UserError,
  openStore,
  parseVerdict,
  type Forge,
  type OpenStoreOptions,
  type Store,
} from "./store.ts";

const SCRIPT = join(import.meta.dir, "orch.ts");
const directories: string[] = [];
const handles: Store[] = [];

interface RunResult {
  readonly code: number;
  readonly stdout: string;
  readonly stderr: string;
}

async function makeDirectory(): Promise<string> {
  const directory = await mkdtemp(join(tmpdir(), "orch-test-"));
  directories.push(directory);
  return directory;
}

function useStore(
  directory: string,
  options?: OpenStoreOptions
): Store {
  const store = openStore(directory, options);
  handles.push(store);
  return store;
}

async function initializedStore(): Promise<{
  readonly directory: string;
  readonly store: Store;
}> {
  const directory = await makeDirectory();
  const store = useStore(directory);
  await store.init();
  return { directory, store };
}

function git({
  args,
  repo,
}: {
  args: readonly string[];
  repo: string;
}): string {
  const result = Bun.spawnSync(["git", "-C", repo, ...args]);
  if (result.exitCode !== 0) {
    throw new Error(
      `git ${args.join(" ")} failed: ${result.stderr.toString()}`
    );
  }
  return result.stdout.toString().trim();
}

async function makeGitStack(directory: string): Promise<{
  readonly repo: string;
  readonly mergedSha: string;
  readonly closedSha: string;
  readonly openSha: string;
  readonly draftSha: string;
}> {
  const repo = join(directory, "repo");
  await mkdir(repo);
  git({ repo, args: ["init", "--initial-branch=main"] });
  git({ repo, args: ["config", "user.name", "Orch Test"] });
  git({ repo, args: ["config", "user.email", "orch@example.com"] });
  git({
    repo,
    args: ["remote", "add", "origin", "https://github.com/acme/fixture.git"],
  });
  await writeFile(join(repo, "main.txt"), "main\n");
  git({ repo, args: ["add", "."] });
  git({ repo, args: ["commit", "-m", "main"] });

  const branches = [
    "stack/merged",
    "stack/closed",
    "stack/open",
    "stack/draft",
  ];
  for (const [index, branch] of branches.entries()) {
    git({ repo, args: ["checkout", "-b", branch] });
    await writeFile(join(repo, `stack-${index}.txt`), `${branch}\n`);
    git({ repo, args: ["add", "."] });
    git({ repo, args: ["commit", "-m", branch] });
  }
  git({ repo, args: ["checkout", "stack/open"] });

  return {
    repo,
    mergedSha: git({ repo, args: ["rev-parse", "stack/merged"] }),
    closedSha: git({ repo, args: ["rev-parse", "stack/closed"] }),
    openSha: git({ repo, args: ["rev-parse", "stack/open"] }),
    draftSha: git({ repo, args: ["rev-parse", "stack/draft"] }),
  };
}

type FixtureState = "open" | "draft" | "merged" | "closed";

interface FixturePr {
  readonly number: number;
  readonly state: FixtureState;
  readonly head: string;
  readonly base: string;
  readonly repository?: string;
}

const FORGE_FIXTURES: Readonly<
  Record<
    Forge,
    {
      readonly fields: string;
      readonly row: (pr: FixturePr) => Record<string, unknown>;
    }
  >
> = {
  gh: {
    fields: "number,state,headRefName,baseRefName,headRepository",
    row: ({ number, state, head, base, repository }) => ({
      number,
      state: state === "draft" ? "OPEN" : state.toUpperCase(),
      headRefName: head,
      baseRefName: base,
      headRepository: {
        id: "R_fixture",
        name: "fixture",
        nameWithOwner: repository ?? "acme/fixture",
      },
    }),
  },
  origin: {
    fields: "number,status,headRef,baseRef",
    row: ({ number, state, head, base }) => ({
      number,
      status: state,
      headRef: head,
      baseRef: base,
    }),
  },
};

function forgeRows(forge: Forge, prs: readonly FixturePr[]): string {
  return JSON.stringify(prs.map((pr) => FORGE_FIXTURES[forge].row(pr)));
}

async function withFakeForge<T>({
  directory,
  forge,
  operation,
  currentRows,
}: {
  directory: string;
  forge: Forge;
  operation: () => Promise<T>;
  currentRows?: string;
}): Promise<T> {
  const bin = join(directory, "bin");
  const outputPath = join(directory, "forge-output.txt");
  await mkdir(bin, { recursive: true });
  await writeFile(
    outputPath,
    `${
      currentRows ??
      forgeRows(forge, [
        {
          number: 11,
          state: "open",
          head: "stack/open",
          base: "stack/closed",
        },
      ])
    }\n`
  );
  const { fields } = FORGE_FIXTURES[forge];
  const repoFlag = forge === "gh" ? "--repo acme/fixture " : "";
  const list = (filter: string, branch: string): string =>
    `pr list ${repoFlag}${filter} ${branch} --state all --limit 1000 --json ${fields}`;
  const fake = join(bin, forge);
  await writeFile(
    fake,
    `#!/usr/bin/env bash
set -euo pipefail
if [ "$(pwd -P)" != "${realpathSync(join(directory, "repo"))}" ]; then
  printf '${forge} ran outside the fixture repo: %s\\n' "$(pwd -P)" >&2
  exit 2
fi
case "$*" in
  "${list("--head", "stack/open")}")
    cat "${outputPath}"
    ;;
  "${list("--head", "stack/closed")}")
    printf '%s\\n' '${forgeRows(forge, [{ number: 13, state: "closed", head: "stack/closed", base: "stack/merged" }])}'
    ;;
  "${list("--head", "stack/merged")}")
    printf '%s\\n' '${forgeRows(forge, [{ number: 10, state: "merged", head: "stack/merged", base: "main" }])}'
    ;;
  "${list("--base", "stack/open")}")
    printf '%s\\n' '${forgeRows(forge, [
      { number: 14, state: "draft", head: "stack/draft", base: "stack/open" },
      {
        number: 15,
        state: "closed",
        head: "stack/abandoned",
        base: "stack/open",
      },
    ])}'
    ;;
  "${list("--base", "stack/draft")}")
    printf '[]\\n'
    ;;
  *)
    printf 'unexpected ${forge} arguments: %s\\n' "$*" >&2
    exit 2
    ;;
esac
`
  );
  await chmod(fake, 0o755);

  const originalPath = process.env.PATH;
  process.env.PATH = `${bin}:${originalPath ?? ""}`;
  try {
    return await operation();
  } finally {
    if (originalPath === undefined) {
      delete process.env.PATH;
    } else {
      process.env.PATH = originalPath;
    }
  }
}

async function withFakeGh<T>({
  directory,
  operation,
}: {
  directory: string;
  operation: () => Promise<T>;
}): Promise<T> {
  const bin = join(directory, "gh-bin");
  await mkdir(bin);
  const gh = join(bin, "gh");
  await writeFile(
    gh,
    `#!/usr/bin/env bash
set -euo pipefail
if [ "$1" != "pr" ] || [ "$2" != "view" ]; then
  printf 'unexpected gh arguments: %s\n' "$*" >&2
  exit 2
fi
case "$3" in
  10) printf '{"number":10,"state":"MERGED","headRefName":"stack/merged","headRefOid":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}\n' ;;
  13) printf '{"number":13,"state":"CLOSED","headRefName":"stack/closed","headRefOid":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}\n' ;;
  11) printf '{"number":11,"state":"OPEN","headRefName":"stack/open","headRefOid":"cccccccccccccccccccccccccccccccccccccccc"}\n' ;;
  *) printf 'unknown PR %s\n' "$3" >&2; exit 1 ;;
esac
`
  );
  await chmod(gh, 0o755);
  const originalPath = process.env.PATH;
  process.env.PATH = `${bin}:${originalPath ?? ""}`;
  try {
    return await operation();
  } finally {
    if (originalPath === undefined) delete process.env.PATH;
    else process.env.PATH = originalPath;
  }
}

function runCli(
  args: readonly string[],
  env: Readonly<Record<string, string | undefined>> = process.env
): RunResult {
  const result = Bun.spawnSync([process.execPath, SCRIPT, ...args], { env });
  return {
    code: result.exitCode,
    stdout: result.stdout.toString(),
    stderr: result.stderr.toString(),
  };
}

async function plantStaleLock(directory: string): Promise<number> {
  const exited = Bun.spawn(["true"]);
  await exited.exited;
  await writeFile(join(directory, ".orch.lock"), `${exited.pid}\n`);
  return exited.pid;
}

// Runs one store writer in its own process, so a lock race is staged between
// real pids. Each hook is code spliced into the writer: `onStaleLock` runs in
// that callback, `before` before its write, `afterHeld` after a write that got
// the lock, `atLockUnlink` before its first unlink of the lock, `afterClose`
// once the store is closed, and `patch` after the unlink hook is installed.
// `killAfterLockCall` sends SIGKILL after that many filesystem calls on a path
// that starts with the lock's.
function spawnWriter({
  directory,
  flags,
  name,
  force = false,
  onStaleLock = "",
  before = "",
  afterHeld = "",
  atLockUnlink = "",
  afterClose = "",
  patch = "",
  killAfterLockCall = 0,
}: {
  directory: string;
  flags: string;
  name: string;
  force?: boolean;
  onStaleLock?: string;
  before?: string;
  afterHeld?: string;
  atLockUnlink?: string;
  afterClose?: string;
  patch?: string;
  killAfterLockCall?: number;
}) {
  const killer =
    killAfterLockCall === 0
      ? ""
      : `let lockCalls = 0;
for (const [call, run] of Object.entries(promises)) {
  if (typeof run !== "function") continue;
  promises[call] = async (...args) => {
    try {
      return await run(...args);
    } finally {
      if (args.slice(0, 2).some((path) => String(path).startsWith(lock))) {
        lockCalls += 1;
        if (lockCalls === ${killAfterLockCall}) process.kill(process.pid, "SIGKILL");
      }
    }
  };
}`;
  const script = `
const { existsSync, readFileSync, writeFileSync } = require("node:fs");
const promises = require("node:fs/promises");
const flag = (suffix) => ${JSON.stringify(`${flags}/${name}.`)} + suffix;
const peer = (outcome) => existsSync(${JSON.stringify(`${flags}/`)} + outcome);
const lock = ${JSON.stringify(join(directory, ".orch.lock"))};
const holder = () => {
  try {
    return readFileSync(lock, "utf8").trim();
  } catch {
    return "missing";
  }
};
const spin = (ready) => {
  const deadline = Date.now() + 5000;
  while (!ready()) {
    if (Date.now() > deadline) throw new Error("barrier timeout");
  }
};
const { unlink } = promises;
let reached = false;
promises.unlink = async (path) => {
  if (!reached && path === lock) {
    reached = true;
    ${atLockUnlink}
  }
  return unlink(path);
};
${patch}
${killer}
const { openStore } = await import(${JSON.stringify(join(import.meta.dir, "store.ts"))});
const store = openStore(${JSON.stringify(directory)}, {
  force: ${force},
  onStaleLock: () => {
    ${onStaleLock}
  },
});
${before}
try {
  await store.units.add({ id: "${name}-unit", track: "race" });
  writeFileSync(flag("held"), "");
  ${afterHeld}
} catch (error) {
  writeFileSync(flag("refused"), error.message);
}
await store.close();
${afterClose}
`;
  return Bun.spawn([process.execPath, "-e", script], { stderr: "pipe" });
}

async function readFlags(
  flags: string
): Promise<Readonly<Record<string, string>>> {
  const entries = await Promise.all(
    (await readdir(flags)).map(async (name) => [
      name,
      await readFile(join(flags, name), "utf8"),
    ])
  );
  return Object.fromEntries(entries);
}

async function lockFiles(directory: string): Promise<readonly string[]> {
  return (await readdir(directory))
    .filter((name) => name.startsWith(".orch.lock"))
    .sort();
}

afterEach(async () => {
  for (const store of handles.splice(0).reverse()) {
    await store.close();
  }
  for (const directory of directories.splice(0)) {
    await rm(directory, { recursive: true, force: true });
  }
});

describe("Store", () => {
  it("initializes an idempotent plain-file store and releases its lock", async () => {
    const directory = await makeDirectory();
    const store = useStore(directory);

    expect(await store.init()).toEqual({ store: directory });
    const firstUnits = await readFile(join(directory, "units.tsv"), "utf8");
    const firstLedger = await readFile(
      join(directory, "ledger.tsv"),
      "utf8"
    );

    expect(await store.init()).toEqual({ store: directory });
    expect(await readFile(join(directory, "units.tsv"), "utf8")).toBe(
      firstUnits
    );
    expect(await readFile(join(directory, "ledger.tsv"), "utf8")).toBe(
      firstLedger
    );
    expect((await readdir(directory)).sort()).toEqual([
      ".orch.lock",
      "frontier.json",
      "gates.md",
      "inbox",
      "ledger.tsv",
      "preferences.md",
      "units.tsv",
    ]);

    await store.close();
    expect(await readdir(directory)).not.toContain(".orch.lock");
  });

  it("composes unit add, set, get, list, and counts", async () => {
    const { store } = await initializedStore();

    expect(
      await store.units.add({
        id: "u1",
        track: "build",
        brief: "briefs/u1.md",
      })
    ).toMatchObject({ id: "u1", state: "pending" });
    expect(
      await store.units.add({ id: "=SUM(A1)", track: "+build" })
    ).toMatchObject({ id: "'=SUM(A1)", track: "'+build" });

    const updated = await store.units.set({
      id: "u1",
      state: "done",
      branch: "poteto/u1",
      pr: 184530,
      sha: "abc123",
    });
    expect(updated).toEqual({
      id: "u1",
      track: "build",
      state: "done",
      branch: "poteto/u1",
      pr: "184530",
      sha: "abc123",
      brief: "briefs/u1.md",
    });
    expect(await store.units.get("u1")).toEqual(updated);
    expect(
      await store.units.list({ state: "done", track: "build" })
    ).toEqual([updated]);
    expect(await store.units.counts()).toEqual({ done: 1, pending: 1 });
    await expect(
      store.units.add({ id: "u1", track: "build" })
    ).rejects.toThrow("unit u1 already exists");
    await expect(
      store.units.set({ id: "missing", state: "done" })
    ).rejects.toBeInstanceOf(NotFoundError);
  });

  it("records, replaces, checks, and summarizes typed ledger verdicts", async () => {
    const { store } = await initializedStore();

    try {
      await store.ledger.check({ pr: 184530, sha: "abc123" });
      throw new Error("expected ledger check to fail");
    } catch (error) {
      expect(error).toBeInstanceOf(NotFoundError);
      if (error instanceof NotFoundError) {
        expect(error.output).toEqual({
          compact: "NOT-VERIFIED",
          json: {
            pr: "184530",
            sha: "abc123",
            verdict: "NOT-VERIFIED",
          },
        });
      }
    }
    expect(() => parseVerdict("looks-good")).toThrow("verdict must be");

    const recorded = await store.ledger.record({
      pr: 184530,
      sha: "abc123",
      verdict: "unit-test-verified",
      evidence: "reports/verify.md",
      verifier: "opus",
    });
    expect(await store.ledger.check({ pr: 184530, sha: "abc123" })).toEqual(
      recorded
    );
    expect(await store.ledger.summary()).toEqual({
      "unit-test-verified": 1,
    });

    await store.ledger.record({
      pr: 184530,
      sha: "abc123",
      verdict: "live-ui-verified",
      evidence: "reports/live.md",
    });
    expect(await store.ledger.summary()).toEqual({
      "live-ui-verified": 1,
    });
  });

  it("pushes, peeks, and atomically drains inbox pointers", async () => {
    const { directory, store } = await initializedStore();

    const first = await store.inbox.push({
      agent: "worker-1",
      unit: "u1",
      status: "done",
      report: "reports/u1.md",
    });
    expect(first.pointer).toMatchObject({ unit: "u1", status: "done" });
    expect(first.filename).toEndWith(".tsv");
    await store.inbox.push({
      agent: "worker-2",
      unit: "u2",
      status: "failed",
    });

    expect(await store.inbox.count()).toBe(2);
    expect(await store.inbox.peek()).toHaveLength(2);
    expect(await store.inbox.count()).toBe(2);
    expect(await store.inbox.drain()).toHaveLength(2);
    expect(await store.inbox.count()).toBe(0);
    expect(await readdir(join(directory, "inbox"))).toEqual([]);
    expect(
      (await readdir(directory)).filter((name) =>
        name.startsWith(".inbox-drain-")
      )
    ).toEqual([]);
  });

  it("replaces a stale lock whose holder pid is dead", async () => {
    const { directory } = await initializedStore();
    const exited = Bun.spawn(["true"]);
    await exited.exited;
    await writeFile(join(directory, ".orch.lock"), `${exited.pid}\n`);

    const stale: string[] = [];
    const recovered = useStore(directory, {
      onStaleLock: (holder) => stale.push(holder),
    });
    expect(
      await recovered.units.add({ id: "u1", track: "build" })
    ).toMatchObject({ id: "u1" });
    expect(stale).toEqual([String(exited.pid)]);
    await recovered.close();
    expect(await readdir(directory)).not.toContain(".orch.lock");
  });

  it("blocks a writer and steals the pid lock only with force", async () => {
    const { directory, store } = await initializedStore();
    await store.close();
    await writeFile(join(directory, ".orch.lock"), `${process.pid}\n`);

    const blocked = useStore(directory);
    await expect(
      blocked.units.add({ id: "u1", track: "build" })
    ).rejects.toThrow(`store lock held by pid ${process.pid}`);

    const stolen: string[] = [];
    const forced = useStore(directory, {
      force: true,
      onLockStolen: (holder) => stolen.push(holder),
    });
    expect(
      await forced.units.add({ id: "u1", track: "build" })
    ).toMatchObject({ id: "u1" });
    expect(stolen).toEqual([String(process.pid)]);
    await forced.close();
    expect(await readdir(directory)).not.toContain(".orch.lock");
  });

  it.each([
    ["no lock", false],
    ["a stale lock", true],
  ])(
    "lets the next writer in after a writer that found %s is killed at any step of taking or releasing it",
    async (_found, stale) => {
      const { directory, store } = await initializedStore();
      await store.close();
      const flags = await makeDirectory();

      for (let kills = 0; ; kills += 1) {
        if (stale) {
          await plantStaleLock(directory);
        }
        const writer = spawnWriter({
          directory,
          flags,
          name: `w${kills}`,
          killAfterLockCall: kills + 1,
        });
        await writer.exited;
        if (writer.signalCode !== "SIGKILL") {
          expect(await new Response(writer.stderr).text()).toBe("");
          expect(writer.exitCode).toBe(0);
          expect(kills).toBeGreaterThan(2);
          break;
        }
        const id = `after-kill-${kills}`;
        const next = useStore(directory);
        expect(await next.units.add({ id, track: "build" })).toMatchObject({
          id,
        });
        await next.close();
      }
    },
    60_000
  );

  it("lets only one of two writers that saw the same dead holder replace its lock", async () => {
    const { directory, store } = await initializedStore();
    await store.close();
    await plantStaleLock(directory);
    const flags = await makeDirectory();

    const a = spawnWriter({
      directory,
      flags,
      name: "A",
      onStaleLock: `writeFileSync(flag("saw-stale"), "");
    spin(() => peer("B.saw-stale"));`,
      afterHeld: `spin(() => peer("B.held") || peer("B.refused"));`,
    });
    const b = spawnWriter({
      directory,
      flags,
      name: "B",
      onStaleLock: `writeFileSync(flag("saw-stale"), "");
    spin(() => peer("A.held"));`,
    });
    expect(await Promise.all([a.exited, b.exited])).toEqual([0, 0]);
    expect(await new Response(a.stderr).text()).toBe("");
    expect(await new Response(b.stderr).text()).toBe("");

    expect(await readFlags(flags)).toEqual({
      "A.saw-stale": "",
      "B.saw-stale": "",
      "A.held": "",
      "B.refused": `store lock held by pid ${a.pid}`,
    });
    expect(await readFile(join(directory, "units.tsv"), "utf8")).toBe(
      "id\ttrack\tstate\tbranch\tpr\tsha\tbrief\nA-unit\trace\tpending\t\t\t\t\n"
    );
    expect(await lockFiles(directory)).toEqual([]);
  });

  it("refuses a writer that saw the same dead holder while another is between its re-read and its unlink", async () => {
    const { directory, store } = await initializedStore();
    await store.close();
    const stale = await plantStaleLock(directory);
    const flags = await makeDirectory();

    const a = spawnWriter({
      directory,
      flags,
      name: "A",
      atLockUnlink: `writeFileSync(flag("replacing"), "");
    spin(() => peer("B.held") || peer("B.refused"));`,
    });
    const b = spawnWriter({
      directory,
      flags,
      name: "B",
      before: `spin(() => peer("A.replacing"));`,
    });
    expect(await Promise.all([a.exited, b.exited])).toEqual([0, 0]);
    expect(await new Response(a.stderr).text()).toBe("");
    expect(await new Response(b.stderr).text()).toBe("");

    expect(await readFlags(flags)).toEqual({
      "A.replacing": "",
      "A.held": "",
      "B.refused": `store lock held by pid ${stale} is being released or replaced; retry`,
    });
    expect(await readFile(join(directory, "units.tsv"), "utf8")).toBe(
      "id\ttrack\tstate\tbranch\tpr\tsha\tbrief\nA-unit\trace\tpending\t\t\t\t\n"
    );
    expect(await lockFiles(directory)).toEqual([]);
  });

  it("keeps a forced writer's lock when the holder it replaced was releasing", async () => {
    const { directory, store } = await initializedStore();
    await store.close();
    const flags = await makeDirectory();

    const a = spawnWriter({
      directory,
      flags,
      name: "A",
      atLockUnlink: `writeFileSync(flag("releasing"), "");
    spin(() => peer("F.held") || peer("F.refused"));`,
      afterClose: `writeFileSync(flag("released"), "");`,
    });
    const f = spawnWriter({
      directory,
      flags,
      name: "F",
      force: true,
      before: `spin(() => peer("A.releasing"));`,
      afterHeld: `spin(() => peer("A.released"));
  writeFileSync(flag("lock-after-A-released"), holder());`,
    });
    expect(await Promise.all([a.exited, f.exited])).toEqual([0, 0]);
    expect(await new Response(a.stderr).text()).toBe("");
    expect(await new Response(f.stderr).text()).toBe("");

    expect(await readFlags(flags)).toEqual({
      "A.held": "",
      "A.releasing": "",
      "A.released": "",
      "F.refused": `store lock held by pid ${a.pid} is being released or replaced; retry`,
    });
    expect(await readFile(join(directory, "units.tsv"), "utf8")).toBe(
      "id\ttrack\tstate\tbranch\tpr\tsha\tbrief\nA-unit\trace\tpending\t\t\t\t\n"
    );
    expect(await lockFiles(directory)).toEqual([]);
  });

  it("closes a store whose directory was removed while it held the lock", async () => {
    const { directory, store } = await initializedStore();
    await store.units.add({ id: "u1", track: "build" });
    await rm(directory, { recursive: true, force: true });

    await store.close();
  });

  it("takes the lock with an exclusive open where hard links are unsupported", async () => {
    const { directory, store } = await initializedStore();
    await store.close();
    const flags = await makeDirectory();
    const patch = `promises.link = async () => {
  writeFileSync(flag("linked"), "");
  throw Object.assign(new Error("no hard links"), { code: "ENOTSUP" });
};`;

    await writeFile(join(directory, ".orch.lock"), `${process.pid}\n`);
    const blocked = spawnWriter({ directory, flags, name: "B", patch });
    expect(await blocked.exited).toBe(0);
    expect(await readFlags(flags)).toEqual({
      "B.linked": "",
      "B.refused": `store lock held by pid ${process.pid}`,
    });

    await rm(join(directory, ".orch.lock"));
    const writer = spawnWriter({ directory, flags, name: "A", patch });
    expect(await writer.exited).toBe(0);
    expect(await new Response(writer.stderr).text()).toBe("");
    expect(await readFlags(flags)).toMatchObject({
      "A.linked": "",
      "A.held": "",
    });
    expect(await lockFiles(directory)).toEqual([]);
  });

  it("parks gates, stores standing orders, and renders status", async () => {
    const { directory, store } = await initializedStore();
    await store.units.add({ id: "u1", track: "build" });
    expect(
      await store.gates.park({
        id: "release",
        question: "Ship now?",
        options: "ship,wait",
        defaultAnswer: "wait",
      })
    ).toMatchObject({ kind: "open", id: "release" });
    expect(
      await store.standing.add({ line: "Never force push." })
    ).toEqual({ number: 1, line: "Never force push." });

    const first = await store.status.render();
    expect(first.changed).toBe("first render");
    expect(first.summary.openGateIds).toEqual(["release"]);
    expect(await readFile(join(directory, "status.md"), "utf8")).toContain(
      "| release | open | Ship now? |"
    );
    expect((await store.status.render()).changed).toBe("no derived changes");

    expect(
      await store.gates.resolve({ id: "release", answer: "ship" })
    ).toMatchObject({ kind: "resolved", answer: "ship" });
    expect((await store.status.render()).changed).toBe("open gates 1->0");
    expect(await store.gates.list()).toEqual([]);
    expect(await store.standing.show()).toEqual([
      { number: 1, line: "Never force push." },
    ]);
  });

  for (const forge of ["gh", "origin"] as const) {
    it(`resolves the ordered frontier from the ${forge} base chain`, async () => {
      const { directory, store } = await initializedStore();
      const stack = await makeGitStack(directory);
      const forgeParams = forge === "gh" ? {} : { forge };

      await withFakeForge({
        directory,
        forge,
        operation: async () => {
          expect(
            await store.frontier.set({ repo: stack.repo, ...forgeParams })
          ).toEqual({
            generation: 1,
            prs: [
              {
                pr: 10,
                branches: "stack/merged",
                sha: stack.mergedSha,
                state: "MERGED",
              },
              {
                pr: 13,
                branches: "stack/closed",
                sha: stack.closedSha,
                state: "CLOSED",
              },
              {
                pr: 11,
                branches: "stack/open",
                sha: stack.openSha,
                state: "OPEN",
              },
              {
                pr: 14,
                branches: "stack/draft",
                sha: stack.draftSha,
                state: "OPEN",
              },
            ],
            lowestUnmerged: 11,
          });
          await expect(
            store.frontier.set({
              repo: stack.repo,
              ...forgeParams,
              prs: [10, 10],
            })
          ).rejects.toThrow("--prs must not contain duplicates");
        },
      });
    });

    it(`rejects unparseable ${forge} output loudly`, async () => {
      const { directory, store } = await initializedStore();
      const stack = await makeGitStack(directory);

      await withFakeForge({
        directory,
        forge,
        currentRows: "this line is not forge output",
        operation: async () => {
          await expect(
            store.frontier.set({ repo: stack.repo, forge })
          ).rejects.toThrow(
            `${forge} pr list --head stack/open output is not valid JSON`
          );
        },
      });
    });
  }

  it("resolves an explicit PR order through gh from a detached checkout", async () => {
    const { directory, store } = await initializedStore();
    const stack = await makeGitStack(directory);
    git({ repo: stack.repo, args: ["checkout", "--detach"] });

    await withFakeGh({
      directory,
      operation: async () => {
        const frontier = await store.frontier.set({
          repo: stack.repo,
          prs: [11, 10, 13],
        });
        expect(frontier.prs).toEqual([
          {
            pr: 11,
            branches: "stack/open",
            sha: "cccccccccccccccccccccccccccccccccccccccc",
            state: "OPEN",
          },
          {
            pr: 10,
            branches: "stack/merged",
            sha: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            state: "MERGED",
          },
          {
            pr: 13,
            branches: "stack/closed",
            sha: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            state: "CLOSED",
          },
        ]);
        expect(frontier.lowestUnmerged).toBe(11);
      },
    });
  });

  it("rejects an explicit PR order with a non-GitHub forge", async () => {
    const { directory, store } = await initializedStore();
    const stack = await makeGitStack(directory);

    await expect(
      store.frontier.set({ repo: stack.repo, forge: "origin", prs: [11] })
    ).rejects.toThrow("--prs reads GitHub with gh pr view; omit --forge");
  });

  it("ignores another fork's pull request for a same-named branch", async () => {
    const { directory, store } = await initializedStore();
    const stack = await makeGitStack(directory);

    await withFakeForge({
      directory,
      forge: "gh",
      currentRows: forgeRows("gh", [
        {
          number: 99,
          state: "open",
          head: "stack/open",
          base: "main",
          repository: "someone/fixture",
        },
        {
          number: 11,
          state: "open",
          head: "stack/open",
          base: "stack/closed",
        },
      ]),
      operation: async () => {
        expect(
          (await store.frontier.set({ repo: stack.repo })).prs.map(
            (row) => row.pr
          )
        ).toEqual([10, 13, 11, 14]);
      },
    });
  });

  it("treats a branch whose only pull request comes from another fork as having none", async () => {
    const { directory, store } = await initializedStore();
    const stack = await makeGitStack(directory);

    await withFakeForge({
      directory,
      forge: "gh",
      currentRows: forgeRows("gh", [
        {
          number: 99,
          state: "open",
          head: "stack/open",
          base: "main",
          repository: "someone/fixture",
        },
      ]),
      operation: async () => {
        await expect(store.frontier.set({ repo: stack.repo })).rejects.toThrow(
          "branch stack/open has no pull request"
        );
      },
    });
  });

  it("rejects a pull request list that may be truncated", async () => {
    const { directory, store } = await initializedStore();
    const stack = await makeGitStack(directory);

    await withFakeForge({
      directory,
      forge: "gh",
      currentRows: forgeRows(
        "gh",
        Array.from({ length: 1000 }, (_, index) => ({
          number: 1000 + index,
          state: "closed" as const,
          head: "stack/open",
          base: "stack/closed",
        }))
      ),
      operation: async () => {
        await expect(store.frontier.set({ repo: stack.repo })).rejects.toThrow(
          "gh pr list --head stack/open returned 1000 pull requests and may be truncated; set the frontier with --prs"
        );
      },
    });
  });

  it("refuses to guess trunk when origin/main and origin/master both exist", async () => {
    const { directory, store } = await initializedStore();
    const stack = await makeGitStack(directory);
    git({ repo: stack.repo, args: ["update-ref", "refs/remotes/origin/main", "main"] });
    git({ repo: stack.repo, args: ["update-ref", "refs/remotes/origin/master", "main"] });

    await withFakeGh({
      directory,
      operation: async () => {
        await expect(store.frontier.set({ repo: stack.repo })).rejects.toThrow(
          "cannot tell whether main or master is trunk without origin/HEAD"
        );
      },
    });
  });

  it("resolves the base chain for an ssh:// GitHub origin", async () => {
    const { directory, store } = await initializedStore();
    const stack = await makeGitStack(directory);
    git({
      repo: stack.repo,
      args: ["remote", "set-url", "origin", "ssh://git@github.com/acme/fixture.git"],
    });

    await withFakeForge({
      directory,
      forge: "gh",
      operation: async () => {
        expect(
          (await store.frontier.set({ repo: stack.repo })).prs.map(
            (row) => row.pr
          )
        ).toEqual([10, 13, 11, 14]);
      },
    });
  });

  it("resolves a master trunk without origin/HEAD and without asking the forge", async () => {
    const { directory, store } = await initializedStore();
    const repo = join(directory, "repo");
    await mkdir(repo);
    git({ repo, args: ["init", "--initial-branch=master"] });
    git({ repo, args: ["config", "user.name", "Orch Test"] });
    git({ repo, args: ["config", "user.email", "orch@example.com"] });
    await writeFile(join(repo, "master.txt"), "master\n");
    git({ repo, args: ["add", "."] });
    git({ repo, args: ["commit", "-m", "master"] });
    git({ repo, args: ["update-ref", "refs/remotes/origin/master", "HEAD"] });

    await withFakeGh({
      directory,
      operation: async () => {
        expect(await store.frontier.set({ repo })).toEqual({
          generation: 1,
          prs: [],
          lowestUnmerged: null,
        });
      },
    });
  });

  it("names the missing pull request when a chain branch has none", async () => {
    const { directory, store } = await initializedStore();
    const stack = await makeGitStack(directory);

    await withFakeForge({
      directory,
      forge: "gh",
      currentRows: "[]",
      operation: async () => {
        await expect(store.frontier.set({ repo: stack.repo })).rejects.toThrow(
          "branch stack/open has no pull request; open one with gh pr create"
        );
      },
    });
  });

  it("rejects malformed TSV, verdict, frontier, and inbox data", async () => {
    const { directory, store } = await initializedStore();

    await writeFile(join(directory, "units.tsv"), "wrong\n");
    await expect(store.units.list()).rejects.toThrow(
      "units.tsv has an invalid header"
    );
    await writeFile(
      join(directory, "units.tsv"),
      "id\ttrack\tstate\tbranch\tpr\tsha\tbrief\nshort\trow\n"
    );
    await expect(store.units.list()).rejects.toThrow(
      "units.tsv has a malformed row"
    );

    await writeFile(
      join(directory, "ledger.tsv"),
      "pr\tsha\tverdict\tevidence\tverifier\tts\n1\tsha\tinvalid\treport\tme\tnow\n"
    );
    await expect(store.ledger.summary()).rejects.toThrow(
      "ledger.tsv has invalid verdict invalid"
    );

    await writeFile(join(directory, "frontier.json"), '{"generation":"1"}\n');
    await expect(store.frontier.show()).rejects.toThrow(
      "frontier.json has an invalid shape"
    );

    await writeFile(join(directory, "inbox", "bad.tsv"), "too\tshort\n");
    await expect(store.inbox.peek()).rejects.toThrow(
      "inbox pointer bad.tsv is malformed"
    );
  });

  it("rejects operations after close", async () => {
    const { store } = await initializedStore();
    await store.close();
    await expect(store.units.list()).rejects.toThrow("store is closed");
    await expect(store.status.render()).rejects.toBeInstanceOf(UserError);
  });
});

describe("orch CLI", () => {
  it("prints commander help and rejects invalid parsing with exit 1", async () => {
    const help = runCli(["--help"]);
    expect(help.code).toBe(0);
    expect(help.stdout).toContain("Commands:");
    expect(help.stdout).toContain("unit");
    expect(help.stdout).toContain("ledger");

    const frontierHelp = runCli(["frontier", "set", "--help"]);
    expect(frontierHelp.code).toBe(0);
    expect(frontierHelp.stdout).toContain("--repo <dir>");
    expect(frontierHelp.stdout).toContain("--forge <forge>");
    expect(frontierHelp.stdout).toContain("--prs <n,...>");

    const directory = await makeDirectory();
    const invalid = runCli(["--store", directory, "unit", "add", "u1"]);
    expect(invalid.code).toBe(1);
    expect(invalid.stderr).toContain("required option '--track <track>'");

    const badForge = runCli([
      "--store",
      directory,
      "frontier",
      "set",
      "--repo",
      directory,
      "--forge",
      "gt",
    ]);
    expect(badForge.code).toBe(1);
    expect(badForge.stderr).toContain("Allowed choices are gh, origin");
  });

  it("accepts ORCH_STORE and emits complete JSON", async () => {
    const directory = await makeDirectory();
    const env = { ...process.env, ORCH_STORE: directory };
    expect(runCli(["init"], env).code).toBe(0);

    const added = runCli(
      ["unit", "add", "u1", "--track", "build", "--json"],
      env
    );
    expect(added.code).toBe(0);
    expect(JSON.parse(added.stdout)).toEqual({
      id: "u1",
      track: "build",
      state: "pending",
      branch: "",
      pr: "",
      sha: "",
      brief: "",
    });
  });

  it("maps user and not-found outcomes to the preserved exit codes", async () => {
    const directory = await makeDirectory();
    expect(runCli(["--store", directory, "init"]).code).toBe(0);

    const missingRepo = runCli([
      "--store",
      directory,
      "frontier",
      "set",
    ]);
    expect(missingRepo.code).toBe(1);
    expect(missingRepo.stderr).toContain(
      "set --repo <dir> or ORCH_REPO"
    );

    const userError = runCli([
      "--store",
      directory,
      "unit",
      "add",
      "",
      "--track",
      "build",
    ]);
    expect(userError.code).toBe(1);
    expect(userError.stderr).toContain("unit id must not be empty");

    const missingUnit = runCli([
      "--store",
      directory,
      "unit",
      "get",
      "missing",
    ]);
    expect(missingUnit.code).toBe(2);
    expect(missingUnit.stderr).toContain("unit missing not found");

    const missingLedger = runCli([
      "--store",
      directory,
      "--json",
      "ledger",
      "check",
      "184530",
      "abc123",
    ]);
    expect(missingLedger.code).toBe(2);
    expect(JSON.parse(missingLedger.stdout)).toEqual({
      pr: "184530",
      sha: "abc123",
      verdict: "NOT-VERIFIED",
    });
    expect(missingLedger.stderr).toBe("");
  });
});
