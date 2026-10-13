import { describe, expect, it } from "bun:test";
import { parseArgs } from "./cli.ts";
import { WatcherQueryError } from "./github.ts";
import { runQueued, runSimple, type RunDependencies } from "./policy.ts";
import { fakeReader, pendingCheck } from "./fakes.test-helper.ts";
import type {
  GitHubReader,
  NonEmpty,
  PollingOptions,
  PrContext,
} from "./types.ts";
import { parsePrNumber } from "./types.ts";

const context = (number: number): PrContext => ({
  owner: "owner",
  repo: "repo",
  number: parsePrNumber(number),
});
const once = {
  interval: 60,
  sweepInterval: 300,
  timeout: 0,
  maxQueryErrors: 5,
  allowDraft: false,
  once: true,
} satisfies PollingOptions;

function recorder(reader: GitHubReader) {
  const timeline: string[] = [];
  const dependencies: RunDependencies = {
    reader,
    clock: {
      now: () => 0,
      observedAt: () => "2026-10-13T00:00:00.000Z",
      async sleep(seconds) {
        timeline.push(`sleep:${seconds}`);
        throw new Error(`--once slept for ${seconds}s`);
      },
    },
    emit(verdict) {
      timeline.push(`emit:${verdict.kind}`);
    },
  };
  return { timeline, dependencies };
}

describe("--once", () => {
  it("parses as a polling option", () => {
    const silent = { stdout: () => {}, stderr: () => {} };
    expect(parseArgs(["--pr", "1", "--once"], silent).polling.once).toBe(true);
    expect(parseArgs(["--pr", "1"], silent).polling.once).toBe(false);
  });

  it("classifies one PR with pending checks once and exits TIMEOUT without sleeping", async () => {
    const { timeline, dependencies } = recorder(
      fakeReader({ fastPath: { kind: "checks", checks: [pendingCheck()] } })
    );
    const verdict = await runSimple({
      dependencies,
      contexts: [context(1)],
      mode: "single",
      statusOnly: false,
      options: once,
    });
    expect(timeline).toEqual(["emit:WAITING"]);
    expect(verdict).toMatchObject({
      kind: "TIMEOUT",
      exitCode: 5,
      reason: { kind: "pending-checks" },
    });
  });

  it("returns a ready PR's READY verdict unchanged", async () => {
    const { timeline, dependencies } = recorder(fakeReader());
    const verdict = await runSimple({
      dependencies,
      contexts: [context(1)],
      mode: "single",
      statusOnly: false,
      options: once,
    });
    expect(timeline).toEqual([]);
    expect(verdict).toMatchObject({ kind: "READY", exitCode: 0 });
  });

  it("reports a retryable query failure at once instead of backing off", async () => {
    const base = fakeReader();
    const reader = {
      ...base,
      async pullRequest() {
        throw new WatcherQueryError({
          kind: "command-exit",
          retryable: true,
          detail: "rate limited",
          code: 1,
        });
      },
    } satisfies GitHubReader;
    const { timeline, dependencies } = recorder(reader);
    const verdict = await runSimple({
      dependencies,
      contexts: [context(1)],
      mode: "single",
      statusOnly: false,
      options: once,
    });
    expect(timeline).toEqual([]);
    expect(verdict).toMatchObject({
      kind: "BLOCKER",
      exitCode: 7,
      blocker: { kind: "status-query", failures: 1 },
    });
  });

  it("sweeps a queued stack once and reports the current frontier wait before TIMEOUT", async () => {
    const { timeline, dependencies } = recorder(fakeReader());
    const queue = [context(20), context(21)] satisfies NonEmpty<PrContext>;
    const waits: unknown[] = [];
    const verdict = await runQueued({
      dependencies: {
        ...dependencies,
        emit(verdict) {
          dependencies.emit(verdict);
          if (verdict.kind === "WAITING") waits.push(verdict.reason);
        },
      },
      contexts: queue,
      options: once,
    });
    expect(timeline).toEqual(["emit:QUEUE", "emit:STATUS", "emit:WAITING"]);
    expect(waits).toEqual([{ kind: "merge-queue", unmergedCount: 2 }]);
    expect(verdict).toMatchObject({
      kind: "TIMEOUT",
      exitCode: 5,
      reason: { kind: "queued-stack", frontier: { number: 20 }, unmergedCount: 2 },
    });
  });
});
