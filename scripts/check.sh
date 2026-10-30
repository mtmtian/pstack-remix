#!/usr/bin/env bash
set -Eeuo pipefail
trap 'status=$?; printf "FAILED (%s): %s\n" "$status" "$BASH_COMMAND" >&2; exit "$status"' ERR

cd "$(dirname "${BASH_SOURCE[0]}")/.."
suite=${1:-all}
if [[ $# -gt 1 || ! "$suite" =~ ^(all|runtime|build)$ ]]; then
  printf 'Usage: bash scripts/check.sh [all|runtime|build]\n' >&2
  exit 2
fi

if [[ "$suite" != build ]]; then
  printf '\nRunning offline runtime checks\n'
  node --version
  python3 --version
  node scripts/check-fork.mjs
  if ! command -v timeout >/dev/null; then
    printf 'GNU timeout is required for the host regression tests. See docs/ci.md for macOS setup.\n' >&2
    exit 1
  fi
  timeout -k 1 1 true
  node --test scripts/*.test.mjs
  statechart_tests=()
  for test in skills/statechart/scripts/test/*.test.ts; do
    if [[ "$test" == */differential.test.ts ]] && ! node --input-type=module -e 'await import("fast-check")' 2>/dev/null; then
      printf 'Skipping %s: fast-check is not installed.\n' "$test"
      continue
    fi
    if [[ "$test" == */render.test.ts && "${STATECHART_INSTALL:-}" != 1 ]]; then
      printf 'Skipping %s: it installs Pele, Mermaid, and jsdom from npm; set STATECHART_INSTALL=1 to allow that.\n' "$test"
      continue
    fi
    statechart_tests+=("$test")
  done
  node --disable-warning=ExperimentalWarning --test "${statechart_tests[@]}"
  bash scripts/xagent-classify.test.sh
  for test in scripts/xagent.test.py scripts/xagent-e2e-verify.test.py scripts/e2e-process.test.py scripts/pstack-host-e2e.test.py scripts/pstack-host-e2e-native.test.py; do
    printf '\nRunning %s\n' "$test"
    python3 -B "$test"
  done
fi

if [[ "$suite" != runtime ]]; then
  printf '\nRunning source and build checks\n'
  bun --version
  (
    cd skills/poteto-mode/scripts
    bun run typecheck
    bun run test
  )
  python3 -B scripts/build-runtime.test.py
  python3 -B scripts/build-runtime.py --check
fi

printf '\n%s checks passed.\n' "$suite"
