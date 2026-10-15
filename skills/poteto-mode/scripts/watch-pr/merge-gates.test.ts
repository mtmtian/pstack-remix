import { afterEach, describe, expect, it } from "bun:test";
import { chmodSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { type CliRuntime, main } from "./cli.ts";
import { GhGitHubReader } from "./github.ts";
import { fakeReader, pendingCheck } from "./fakes.test-helper.ts";
import type {
  FakeReaderOptions,
} from "./fakes.test-helper.ts";
import type {
  GitHubReader,
  PrContext,
  PullRequestFacts,
  WatcherVerdict,
} from "./types.ts";
import { parsePrNumber } from "./types.ts";

// GitHub merges a PR only when its own merge state agrees. These cases are
// what Babysit and Shipping act on: the exit code and the final JSON verdict.

type Facts = Partial<Omit<PullRequestFacts, "context">>;

/** A reader whose PR facts follow `byPr[n]` call by call, keeping the last. */
function changingReader(
  byPr: Record<number, readonly Facts[]>,
  options: FakeReaderOptions = {}
): GitHubReader {
  const base = fakeReader(options);
  const reads = new Map<number, number>();
  return {
    ...base,
    async pullRequest(pr: PrContext) {
      const sequence = byPr[pr.number] ?? [{}];
      const index = reads.get(pr.number) ?? 0;
      reads.set(pr.number, index + 1);
      const facts = await base.pullRequest(pr);
      return {
        ...facts,
        ...sequence[Math.min(index, sequence.length - 1)],
      } as PullRequestFacts;
    },
  };
}

async function watch(
  argv: readonly string[],
  reader: GitHubReader,
  maxSleeps = 0
): Promise<{
  readonly code: number;
  readonly verdicts: readonly WatcherVerdict[];
  readonly final: WatcherVerdict;
}> {
  const out: string[] = [];
  let now = 0;
  let sleeps = 0;
  const runtime: CliRuntime = {
    reader,
    clock: {
      now: () => now,
      observedAt: () => "2026-10-16T00:00:00.000Z",
      async sleep(seconds) {
        sleeps += 1;
        if (sleeps > maxSleeps) throw new Error(`unexpected sleep ${sleeps}`);
        now += seconds;
      },
    },
    stdout: (value) => out.push(value),
    stderr: () => {},
  };
  const code = await main(["--owner", "owner", "--repo", "repo", ...argv], runtime);
  const verdicts = out
    .join("")
    .trim()
    .split("\n")
    .map((line) => JSON.parse(line) as WatcherVerdict);
  const final = verdicts.at(-1);
  if (final === undefined) throw new Error("watch-pr printed no verdict");
  return { code, verdicts, final };
}

describe("merge gates GitHub enforces", () => {
  it("stops at review-required instead of READY when a required approval is missing", async () => {
    const { code, final } = await watch(
      ["--pr", "1"],
      fakeReader({
        facts: { mergeStateStatus: "BLOCKED", reviewDecision: "REVIEW_REQUIRED" },
      })
    );
    expect(final).toMatchObject({
      kind: "BLOCKER",
      exitCode: 6,
      blocker: { kind: "merge-gate", reason: "review-required", pr: { number: 1 } },
    });
    expect(code).toBe(6);
  });

  it("stops at merge-blocked when another protection rule holds an approved, green PR", async () => {
    for (const reviewDecision of ["APPROVED", null] as const) {
      const { code, final } = await watch(
        ["--pr", "1"],
        fakeReader({ facts: { mergeStateStatus: "BLOCKED", reviewDecision } })
      );
      expect(final).toMatchObject({
        kind: "BLOCKER",
        blocker: { kind: "merge-gate", reason: "merge-blocked" },
      });
      expect(code).toBe(6);
    }
  });

  it("stops at behind-base when the base requires an up-to-date branch", async () => {
    const { code, final } = await watch(
      ["--pr", "1"],
      fakeReader({ facts: { mergeStateStatus: "BEHIND" } })
    );
    expect(final).toMatchObject({
      kind: "BLOCKER",
      blocker: { kind: "merge-gate", reason: "behind-base" },
    });
    expect(code).toBe(6);
  });

  it("reports behind-base ahead of a required review, since updating can dismiss it", async () => {
    const { final } = await watch(
      ["--pr", "1"],
      fakeReader({
        facts: { mergeStateStatus: "BEHIND", reviewDecision: "REVIEW_REQUIRED" },
      })
    );
    expect(final).toMatchObject({ blocker: { reason: "behind-base" } });
  });

  it("reports behind-base without waiting for checks the update will restart", async () => {
    const { code, final } = await watch(
      ["--pr", "1", "--once"],
      fakeReader({
        facts: { mergeStateStatus: "BEHIND" },
        fastPath: { kind: "checks", checks: [pendingCheck()] },
      })
    );
    expect(final).toMatchObject({ kind: "BLOCKER", blocker: { reason: "behind-base" } });
    expect(code).toBe(6);
  });

  it("prints each gate's own next action with --pretty", async () => {
    const cases = [
      [{ mergeStateStatus: "BEHIND" }, "behind-base", "update the branch with its base"],
      [{ mergeStateStatus: "BLOCKED", reviewDecision: "REVIEW_REQUIRED" }, "review-required", "get the required approving review"],
      [{ mergeStateStatus: "BLOCKED" }, "merge-blocked", "find the branch protection rule"],
    ] as const;
    for (const [facts, reason, action] of cases) {
      const out: string[] = [];
      const runtime: CliRuntime = {
        reader: fakeReader({ facts }),
        clock: { now: () => 0, observedAt: () => "", sleep: async () => {} },
        stdout: (value) => out.push(value),
        stderr: () => {},
      };
      expect(await main(["--owner", "o", "--repo", "r", "--pr", "1", "--pretty"], runtime)).toBe(6);
      expect(out.join("")).toContain(`BLOCKER: ${reason}\npr=1\naction=${action}`);
    }
  });

  it("waits for pending checks before reporting review-required or merge-blocked", async () => {
    const { code, verdicts } = await watch(
      ["--pr", "1", "--once"],
      fakeReader({
        facts: { mergeStateStatus: "BLOCKED", reviewDecision: "REVIEW_REQUIRED" },
        fastPath: { kind: "checks", checks: [pendingCheck()] },
      })
    );
    expect(verdicts.map((verdict) => verdict.kind)).toEqual(["WAITING", "TIMEOUT"]);
    expect(verdicts[1]).toMatchObject({ reason: { kind: "pending-checks" } });
    expect(code).toBe(5);
  });
});

describe("mergeability GitHub has not computed", () => {
  it("waits instead of reporting READY", async () => {
    for (const facts of [
      { mergeable: "UNKNOWN", mergeStateStatus: "UNKNOWN" },
      { mergeable: "MERGEABLE", mergeStateStatus: "UNKNOWN" },
      { mergeable: "UNKNOWN", mergeStateStatus: "CLEAN" },
    ] as const) {
      const { code, verdicts } = await watch(
        ["--pr", "1", "--once"],
        fakeReader({ facts })
      );
      expect(verdicts).toMatchObject([
        { kind: "WAITING", reason: { kind: "mergeability-unknown" } },
        { kind: "TIMEOUT", exitCode: 5, reason: { kind: "mergeability-unknown" } },
      ]);
      expect(code).toBe(5);
    }
  });

  it("keeps polling until GitHub settles it, then reports READY", async () => {
    const unknown = { mergeable: "UNKNOWN", mergeStateStatus: "UNKNOWN" } as const;
    const { code, verdicts } = await watch(
      ["--pr", "1"],
      changingReader({ 1: [unknown, unknown, {}] }),
      1
    );
    expect(verdicts.map((verdict) => verdict.kind)).toEqual(["WAITING", "READY"]);
    expect(code).toBe(0);
  });
});

describe("stacks", () => {
  const open = [
    { number: parsePrNumber(1), headRefName: "one", baseRefName: "main" },
    { number: parsePrNumber(2), headRefName: "two", baseRefName: "one" },
  ];

  it("--stack stops at an upstack PR that still needs its approval", async () => {
    const { code, final } = await watch(
      ["--pr", "1", "--stack"],
      changingReader(
        { 2: [{ mergeStateStatus: "BLOCKED", reviewDecision: "REVIEW_REQUIRED" }] },
        { openPullRequests: open }
      )
    );
    expect(final).toMatchObject({
      kind: "BLOCKER",
      blocker: { reason: "review-required", pr: { number: 2 } },
    });
    expect(code).toBe(6);
  });

  it("--queued-stack reports the gate instead of a merge-queue wait on a frontier GitHub will not merge", async () => {
    const { code, final } = await watch(
      ["--queued-stack", "--stack-prs", "1,2", "--once"],
      changingReader({
        1: [{ mergeStateStatus: "BLOCKED", reviewDecision: "REVIEW_REQUIRED" }],
      })
    );
    expect(final).toMatchObject({
      kind: "BLOCKER",
      blocker: { reason: "review-required", pr: { number: 1 } },
    });
    expect(code).toBe(6);
  });

  it("--queued-stack waits on a frontier whose mergeability is unknown, not on the merge queue", async () => {
    const { verdicts } = await watch(
      ["--queued-stack", "--stack-prs", "1,2", "--once"],
      changingReader({ 1: [{ mergeable: "UNKNOWN" }] })
    );
    expect(verdicts.find((verdict) => verdict.kind === "WAITING")).toMatchObject({
      frontier: { number: 1 },
      reason: { kind: "mergeability-unknown" },
    });
  });
});

describe("one observation of head and base", () => {
  it("names the head and the base branch's current commit in READY", async () => {
    const { final } = await watch(["--pr", "1"], fakeReader());
    expect(final).toMatchObject({
      kind: "READY",
      scope: {
        pr: {
          proof: {
            revision: { headRefOid: "head", baseRefName: "main", baseRefOid: "base" },
          },
        },
      },
    });
  });

  it("re-reads instead of reporting READY when the base branch moves during the read", async () => {
    const { code, verdicts } = await watch(
      ["--pr", "1"],
      changingReader({
        1: [{ baseRefOid: "base-1" }, { baseRefOid: "base-2" }],
      }),
      1
    );
    expect(verdicts).toMatchObject([
      { kind: "RETRY", failure: { kind: "snapshot-changed", retryable: true } },
      { kind: "READY", scope: { pr: { proof: { revision: { baseRefOid: "base-2" } } } } },
    ]);
    expect(code).toBe(0);
  });

  it("re-reads when the head moves during the read", async () => {
    const { verdicts } = await watch(
      ["--pr", "1", "--once"],
      changingReader({ 1: [{ headRefOid: "old" }, { headRefOid: "new" }] })
    );
    expect(verdicts).toMatchObject([
      { kind: "BLOCKER", exitCode: 7, blocker: { failure: { kind: "snapshot-changed" } } },
    ]);
  });

  it("takes mergeability GitHub computed between the reads as the settled answer", async () => {
    const { code, final } = await watch(
      ["--pr", "1", "--once"],
      changingReader({
        1: [{ mergeable: "UNKNOWN", mergeStateStatus: "UNKNOWN" }, {}],
      })
    );
    expect(final).toMatchObject({ kind: "READY" });
    expect(code).toBe(0);
  });

  it("fails closed on an open PR whose base branch commit cannot be read", async () => {
    const { code, final } = await watch(
      ["--pr", "1", "--once"],
      fakeReader({ facts: { baseRefOid: null } })
    );
    expect(final).toMatchObject({
      kind: "BLOCKER",
      blocker: { kind: "status-query", failure: { kind: "missing-key" } },
    });
    expect(code).toBe(7);
  });
});

describe("a PR in a repository with no checks configured", () => {
  // `gh pr checks` exits 1 with this message and the head commit has no rollup.
  const noChecks = {
    fastPath: {
      kind: "unusable",
      exitCode: 1,
      stderr: "no checks reported on the 'feature' branch",
    },
  } as const;

  it("never reports READY: --once ends at a status-query blocker", async () => {
    const { code, final } = await watch(["--pr", "1", "--once"], fakeReader(noChecks));
    expect(final).toMatchObject({
      kind: "BLOCKER",
      exitCode: 7,
      blocker: { kind: "status-query", failure: { kind: "checks-unavailable" } },
    });
    expect(code).toBe(7);
  });

  it("drive mode retries within --max-query-errors, then stops at the same blocker", async () => {
    const { code, verdicts } = await watch(
      ["--pr", "1", "--max-query-errors", "3"],
      fakeReader(noChecks),
      2
    );
    expect(verdicts.map((verdict) => verdict.kind)).toEqual(["RETRY", "RETRY", "BLOCKER"]);
    expect(code).toBe(7);
  });
});

describe("GhGitHubReader PR facts", () => {
  const savedPath = process.env.PATH;
  const temporary: string[] = [];
  afterEach(() => {
    process.env.PATH = savedPath;
    delete process.env.FAKE_GH_ARGV;
    delete process.env.FAKE_GH_RESPONSE;
    for (const directory of temporary.splice(0)) rmSync(directory, { recursive: true, force: true });
  });

  function fakeGh(response: unknown): string {
    const directory = mkdtempSync(join(tmpdir(), "watch-pr-fake-gh-"));
    temporary.push(directory);
    const script = join(directory, "gh");
    writeFileSync(script, '#!/bin/sh\nprintf "%s\\n" "$@" > "$FAKE_GH_ARGV"\ncat "$FAKE_GH_RESPONSE"\n');
    chmodSync(script, 0o755);
    writeFileSync(join(directory, "response.json"), JSON.stringify(response));
    process.env.PATH = `${directory}:${savedPath}`;
    process.env.FAKE_GH_ARGV = join(directory, "argv");
    process.env.FAKE_GH_RESPONSE = join(directory, "response.json");
    return directory;
  }

  const context: PrContext = { owner: "o", repo: "r", number: parsePrNumber(7) };
  const pullRequest = {
    mergeable: "MERGEABLE",
    mergeStateStatus: "BEHIND",
    reviewDecision: null,
    headRefOid: "h1",
    headRefName: "feature",
    baseRefName: "main",
    baseRef: { target: { oid: "b2" } },
    state: "OPEN",
    mergedAt: null,
    isDraft: false,
  };

  it("reads head, mergeability, and the base branch's current commit from one GraphQL response", async () => {
    const directory = fakeGh({ data: { repository: { pullRequest } } });
    const facts = await new GhGitHubReader().pullRequest(context);
    expect(facts).toMatchObject({
      mergeStateStatus: "BEHIND",
      reviewDecision: null,
      headRefOid: "h1",
      baseRefName: "main",
      baseRefOid: "b2",
    });
    const argv = readFileSync(join(directory, "argv"), "utf8").split("\n");
    expect(argv.slice(0, 2)).toEqual(["api", "graphql"]);
    expect(argv).toContain("owner=o");
    expect(argv).toContain("repo=r");
    expect(argv).toContain("pr=7");
  });

  it("reads a deleted base branch as no base commit", async () => {
    fakeGh({
      data: { repository: { pullRequest: { ...pullRequest, state: "CLOSED", baseRef: null } } },
    });
    expect((await new GhGitHubReader().pullRequest(context)).baseRefOid).toBeNull();
  });
});
