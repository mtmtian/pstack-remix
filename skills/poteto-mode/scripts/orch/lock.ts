import { randomUUID } from "node:crypto";
import {
  link,
  mkdir,
  readFile,
  readdir,
  rename,
  rm,
  unlink,
  writeFile,
} from "node:fs/promises";
import { join } from "node:path";
import { setTimeout as sleep } from "node:timers/promises";
import { UserError, errorCode } from "./errors.ts";

const LOCK_FILE = ".orch.lock";
const TAKEOVER_DIR = `${LOCK_FILE}.takeover`;
// A writer killed mid-claim leaves its private pid file or staged claim behind.
const PRIVATE_ENTRY = /^\.orch\.lock\.(?:takeover\.)?(\d+)\.[0-9a-f-]{36}$/;
// link() codes that mean the filesystem has no hard links, not that it failed.
const NO_HARD_LINKS = new Set(["ENOTSUP", "EOPNOTSUPP", "EPERM", "ENOSYS"]);

export interface LockOptions {
  readonly force?: boolean;
  readonly onLockStolen?: (holder: string) => void;
  readonly onStaleLock?: (holder: string) => void;
}

function holderIsDead(holder: string): boolean {
  const pid = Number.parseInt(holder, 10);
  if (!Number.isSafeInteger(pid) || pid <= 0 || String(pid) !== holder) {
    return false;
  }
  try {
    process.kill(pid, 0);
    return false;
  } catch (error) {
    return errorCode(error) === "ESRCH";
  }
}

async function sweepDeadEntries(store: string): Promise<void> {
  for (const name of await readdir(store).catch(() => [])) {
    const owner = PRIVATE_ENTRY.exec(name)?.[1];
    if (owner !== undefined && holderIsDead(owner)) {
      await rm(join(store, name), { recursive: true, force: true });
    }
  }
}

export async function acquireLock(
  store: string,
  options: LockOptions
): Promise<() => Promise<void>> {
  const path = join(store, LOCK_FILE);
  const takeover = join(store, TAKEOVER_DIR);
  const pid = String(process.pid);
  await sweepDeadEntries(store);

  // The lock's contents, or null when there is none.
  const readLock = async (): Promise<string | null> => {
    try {
      return (await readFile(path, "utf8")).trim();
    } catch (error) {
      if (errorCode(error) === "ENOENT") {
        return null;
      }
      throw error;
    }
  };
  const holderOf = (contents: string | null): string => contents || "unknown";

  // A writer killed between an exclusive open and its write would leave an
  // empty lock, which names no pid to judge dead. The pid goes into a private
  // file that is hard-linked into place, so the lock appears with its pid in
  // it. A filesystem without hard links gets the exclusive open.
  const create = async (): Promise<void> => {
    const pidFile = `${path}.${pid}.${randomUUID()}`;
    await writeFile(pidFile, `${pid}\n`, { flag: "wx" });
    try {
      await link(pidFile, path);
    } catch (error) {
      if (!NO_HARD_LINKS.has(errorCode(error) ?? "")) {
        throw error;
      }
      await writeFile(path, `${pid}\n`, { flag: "wx" });
    } finally {
      await rm(pidFile, { force: true });
    }
  };

  // POSIX cannot unlink a file only if it still holds what was read, so every
  // read-then-unlink of the lock runs behind a claim: a directory that holds
  // one file named for the claimant's pid. rename cannot replace a directory
  // that holds a file, so one claim excludes every other, and a dead
  // claimant's file is removed by name, which cannot remove a live one's.
  // Resolves to false, without running the body, while a live writer holds it.
  const claimed = async (body: () => Promise<void>): Promise<boolean> => {
    const staged = `${takeover}.${pid}.${randomUUID()}`;
    await mkdir(staged);
    try {
      await writeFile(join(staged, pid), "");
      for (const claimant of await readdir(takeover).catch(() => [])) {
        if (holderIsDead(claimant)) {
          await rm(join(takeover, claimant), { force: true });
        }
      }
      await rename(staged, takeover);
    } catch (error) {
      await rm(staged, { recursive: true, force: true });
      const code = errorCode(error);
      if (code === "ENOTEMPTY" || code === "EEXIST") {
        return false;
      }
      throw error;
    }
    try {
      await body();
    } finally {
      await rename(takeover, staged).catch(() => {});
      await rm(staged, { recursive: true, force: true });
    }
    return true;
  };

  // Every removal of the lock runs behind the claim, so a lock read here can
  // only vanish with the store directory itself.
  const unlinkLock = async (): Promise<void> => {
    try {
      await unlink(path);
    } catch (error) {
      if (errorCode(error) !== "ENOENT") {
        throw error;
      }
    }
  };

  const takeOver = async (holder: string): Promise<void> => {
    const replaced = await claimed(async () => {
      const current = await readLock();
      if (current !== null) {
        if (holderOf(current) !== holder) {
          throw new UserError(`store lock held by pid ${holderOf(current)}`);
        }
        await unlinkLock();
      }
      try {
        await create();
      } catch (error) {
        if (errorCode(error) !== "EEXIST") {
          throw error;
        }
        throw new UserError(
          `store lock held by pid ${holderOf(await readLock())}`
        );
      }
    });
    if (!replaced) {
      throw new UserError(
        `store lock held by pid ${holder} is being released or replaced; retry`
      );
    }
  };

  try {
    await create();
  } catch (error) {
    if (errorCode(error) !== "EEXIST") {
      throw error;
    }
    const holder = holderOf(await readLock());
    if (holderIsDead(holder)) {
      options.onStaleLock?.(holder);
      await takeOver(holder);
    } else if (options.force) {
      options.onLockStolen?.(holder);
      await takeOver(holder);
    } else {
      throw new UserError(`store lock held by pid ${holder}`);
    }
  }

  // A live claimant that refuses the release is replacing the lock. It
  // finishes or dies, and the next claim sweeps a dead one, so retry. A store
  // removed while held has no lock left to release.
  return async (): Promise<void> => {
    const removeOwn = async (): Promise<void> => {
      if ((await readLock()) === pid) {
        await unlinkLock();
      }
    };
    try {
      while (!(await claimed(removeOwn))) {
        await sleep(10);
      }
    } catch (error) {
      if (errorCode(error) !== "ENOENT") {
        throw error;
      }
    }
  };
}
