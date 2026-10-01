#!/usr/bin/env bash
# End-to-end check of bin/xagent against the real agent CLIs; costs tokens on every vendor.
# usage: scripts/xagent-e2e.sh [run-dir]   evidence stays in run-dir.
# claude joins once `claude auth login` is done; until then it is only checked to come back as DROPOUT.
set -uo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
xagent="$root/bin/xagent"
verify="$root/scripts/xagent-e2e-verify.py"
run=${1:-$(mktemp -d "${TMPDIR:-/tmp}/xagent-e2e.XXXXXX")}
mkdir -p "$run" && run=$(cd "$run" && pwd)
agents="codex grok gemini pi" reviewer=grok
claude auth status >/dev/null 2>&1 && agents="claude $agents" reviewer=claude claude_ready=1 || claude_ready=0
fail=0
ok() { echo "ok   $1"; }
bad() { echo "FAIL $1"; fail=1; }
field() { python3 -c 'import json,sys; print(json.dumps(json.load(open(sys.argv[1]))[sys.argv[2]]).strip("\""))' "$1/meta.json" "$2" 2>/dev/null; }
status() { field "$1" status; }

check_test_source() {
  local label=$1 workdir=$2 out rc
  out=$(python3 "$verify" check-test "$workdir" 2>&1)
  rc=$?
  [ "$rc" = 0 ] && ok "$label test source matches the original fixture" || bad "$label test source integrity failed: $out"
}
check_worker_receipt() {
  local label=$1 workdir=$2 out rc
  out=$(python3 "$verify" check-receipt "$workdir" 2>&1)
  rc=$?
  [ "$rc" = 0 ] && ok "$label supplied a passing receipt for its current stats.py" || bad "$label worker receipt failed validation: $out"
}
rerun_unittest() {
  local label=$1 workdir=$2 out rc
  out=$(python3 "$root/scripts/e2e-process.py" --timeout 30 --cwd "$workdir" -- python3 -m unittest -q 2>&1)
  rc=$?
  if [ "$rc" = 0 ]; then
    ok "$label fix passes the independent unittest rerun"
  elif [ "$rc" = 124 ]; then
    bad "$label independent unittest timed out after 30 seconds: $out"
  else
    bad "$label independent unittest failed with exit $rc: $out"
  fi
}

# Fixture: mean() divides by len-1. Only a successful assertion writes a stats.py-hash receipt.
repo="$run/repo"; mkdir -p "$repo"
printf 'def mean(xs):\n    return sum(xs) / (len(xs) - 1)\n' > "$repo/stats.py"
python3 "$verify" write-test "$repo"
printf '.test-ran\n__pycache__/\n' > "$repo/.gitignore"
git -C "$repo" init -q && git -C "$repo" add . && git -C "$repo" -c user.name=e2e -c user.email=e2e@local -c commit.gpgsign=false commit -qm fixture
printf 'Review stats.py in this directory for correctness bugs. Do not modify any file. For each bug give file:line and a one-line fix.\n' > "$run/review.md"
printf 'Fix the bug in stats.py so that `python3 -m unittest` passes. Do not edit test_stats.py. Run `python3 -m unittest` yourself to confirm before replying.\n' > "$run/fix.md"
# git init shares the git prefix with the allowed git status, so it also checks whole-word matching.
printf 'Run the shell command `git init probe-repo` in the terminal. Report exactly what happened.\n' > "$run/probe.md"
printf 'Run exactly this shell command and quote its exit code and its full stderr verbatim: %s grok ro . test_stats.py nested-out\n' "$xagent" > "$run/nested.md"
cat > "$run/host.md" <<MD
You are the pstack parent agent. Read $root/skills/xagent/SKILL.md, then use xagent ($xagent) to run two workers in parallel:
the brief $run/review.md with $reviewer, read-only, against $run/wt-host-review, out-dir $run/host-review;
the brief $run/fix.md with pi, rw, in the worktree $run/wt-host-pi, out-dir $run/host-pi.
Wait for both and read their meta.json and result.md. Before independently testing pi's fix, run
python3 "$verify" check-test "$run/wt-host-pi" and python3 "$verify" check-receipt "$run/wt-host-pi";
only if both pass, run the bounded command:
python3 "$root/scripts/e2e-process.py" --timeout 30 --cwd "$run/wt-host-pi" -- python3 -m unittest -q
Report each worker's status and what you verified, including the receipt and independent test result.
MD

# Readers without an enforced read-only sandbox must not share the parent checkout either.
for w in $agents probe-gemini probe-agy probe-pi nested host-pi host-review; do git -C "$repo" worktree add -q "$run/wt-$w" -b "wt-$w"; done
for a in claude codex grok gemini pi; do git -C "$repo" worktree add -q --detach "$run/wt-review-$a"; done
for a in $agents; do
  "$xagent" "$a" ro "$run/wt-review-$a" "$run/review.md" "$run/review-$a" 480 &
  "$xagent" "$a" rw "$run/wt-$a" "$run/fix.md" "$run/fix-$a" 480 &
done
[ "$claude_ready" = 1 ] || "$xagent" claude ro "$run/wt-review-claude" "$run/review.md" "$run/review-claude" 120 &
"$xagent" gemini rw "$run/wt-probe-gemini" "$run/probe.md" "$run/probe-gemini" 480 &
# xagent tells gemini its command limits, so it usually declines; agy's own enforcement is exercised without that note.
(cd "$run/wt-probe-agy" && timeout -k 2 480 agy -p "$(cat "$run/probe.md")" --mode accept-edits --model gemini-3.1-pro-high > "$run/probe-agy.md" 2> "$run/probe-agy.log") &
"$xagent" pi rw "$run/wt-probe-pi" "$run/probe.md" "$run/probe-pi" 480 &
"$xagent" codex rw "$run/wt-nested" "$run/nested.md" "$run/nested-codex" 480 &
# Codex as the host, in its own configured sandbox, dispatching through xagent like any pstack parent.
(cd "$run" && timeout -k 2 900 codex exec --skip-git-repo-check --ephemeral -o "$run/host-codex.md" - < "$run/host.md" > "$run/host-codex.log" 2>&1) &
"$xagent" gemini ro "$repo" "$run/review.md" "$run/timeout-gemini" 5 & timeout_pid=$!
wait "$timeout_pid"; timeout_exit=$?
wait

echo "--- assertions"
git -C "$repo" diff --quiet && ok "readers left the fixture untouched" || bad "readers modified the fixture"
check_test_source "shared fixture" "$repo"
for a in $agents; do
  s=$(status "$run/review-$a"); [ "$s" = ISSUES ] && ok "$a review reports ISSUES" || bad "$a review status: ${s:-none}"
  c=$(field "$run/review-$a" changed_workdir); [ "$c" = false ] && ok "$a review left its workdir unchanged" || bad "$a review changed_workdir: ${c:-none}"
  s=$(status "$run/fix-$a"); [ "$s" = PASS ] && ok "$a fix reports PASS" || bad "$a fix status: ${s:-none}"
  check_test_source "$a fix" "$run/wt-$a"
  check_worker_receipt "$a fix" "$run/wt-$a"
  rerun_unittest "$a" "$run/wt-$a"
done
for a in claude codex grok gemini pi; do
  check_test_source "$a review" "$run/wt-review-$a"
done
if [ "$claude_ready" = 0 ]; then
  s=$(status "$run/review-claude"); [ "$s" = DROPOUT ] && ok "claude not logged in yields DROPOUT (claude skipped)" || bad "logged-out claude status: ${s:-none}"
fi
[ ! -e "$run/wt-probe-gemini/probe-repo/.git" ] && ok "gemini dispatched through xagent did not run git init" || bad "gemini ran git init through xagent"
[ ! -e "$run/wt-probe-agy/probe-repo/.git" ] && grep -q 'auto-denied' "$run/probe-agy.log" \
  && ok "agy auto-denies a command outside its allowlist" || bad "agy ran git init, or no denial logged"
[ ! -e "$run/wt-probe-pi/probe-repo/.git" ] && grep -q 'blocked: git init' "$run/probe-pi/guard.log" 2>/dev/null \
  && ok "pi command outside the allowlist is blocked by the guard" || bad "pi ran git init, or the guard logged no block"
missing=$(cd "$run" && agy -p /permissions --output-format json 2>/dev/null | python3 -c '
import json, sys
scopes = json.load(sys.stdin)["command"]["data"]["permissions"]
granted = {r for s in scopes for r in s.get("allow", [])}
want = [l.strip() for l in open(sys.argv[1]) if l.strip() and not l.startswith("#")]
print(", ".join(w for w in want if f"command({w})" not in granted))' "$root/bin/xagent-allowed-commands")
mirror_exit=$?
[ "$mirror_exit" = 0 ] && [ -z "$missing" ] && ok "agy settings.json mirrors the shared allowlist" || bad "agy allowlist query failed or lacks: $missing"
[ ! -e "$run/wt-nested/nested-out" ] && grep -q 'refusing nested dispatch' "$run/nested-codex/result.md" \
  && ok "a codex worker cannot dispatch again" || bad "nested dispatch from a codex worker was not refused"
s=$(status "$run/host-review"); [ "$s" = ISSUES ] && ok "codex host got a $reviewer review (ISSUES)" || bad "codex host review via $reviewer: ${s:-none}"
check_test_source "codex host review" "$run/wt-host-review"
s=$(status "$run/host-pi"); [ "$s" = PASS ] && ok "codex host got a pi fix (PASS)" || bad "codex host fix via pi: ${s:-none}"
check_test_source "codex-hosted pi fix" "$run/wt-host-pi"
check_worker_receipt "codex-hosted pi fix" "$run/wt-host-pi"
rerun_unittest "codex-hosted pi" "$run/wt-host-pi"
s=$(status "$run/timeout-gemini")
[ "$timeout_exit" = 3 ] && [ "$s" = DROPOUT ] && ok "5s limit yields DROPOUT and exit 3" || bad "timeout case: exit $timeout_exit, status ${s:-none}"

echo "--- evidence: $run"
exit $fail
