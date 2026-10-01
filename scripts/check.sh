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
  node --test scripts/*.test.mjs
  bash scripts/xagent-classify.test.sh
  for test in scripts/xagent.test.py scripts/xagent-e2e-verify.test.py scripts/e2e-process.test.py scripts/pstack-host-e2e.test.py; do
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
