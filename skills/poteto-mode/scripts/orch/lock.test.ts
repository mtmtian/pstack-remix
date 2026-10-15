import { afterEach, describe, expect, it } from "bun:test";
import { readFile, readdir, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import {
  cleanupStores,
  initializedStore,
  makeDirectory,
  useStore,
} from "./store.test-helper.ts";

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

afterEach(cleanupStores);

describe("Store lock", () => {
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
      expect(await lockFiles(directory)).toEqual([]);
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
});
