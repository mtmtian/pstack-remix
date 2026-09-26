### Worktree and simulator cleanup

**You own the disk and the safety gate.** This playbook is an audit and a
human-confirmed cleanup procedure. It never treats a suggested bucket as
permission, and it never removes user changes, IDE state, or every simulator
by default.

1. Snapshot and audit. Record `df -h /`, then run `bash <plugin-root>/skills/poteto-mode/scripts/worktree-audit.sh` with an explicit repository path. It reads paths from `git worktree list` and leaves `LAST_CHAT=unknown` when no supported host session index is available. A dirty worktree, including untracked files, is held.
2. Treat every bucket as advice. Cross-check each exact path against active agent work, the branch upstream, the PR state, and the diff. `unknown`, `ambiguous`, `CLOSED`, or missing forge data stays held for review. Do not infer liveness from filesystem timestamps or IDE history.
3. Before any deletion, inspect `git status --short`, preserve or export any unique files, and obtain explicit confirmation for the exact path. A clean, merged worktree can still be in use; an uncommitted worktree is never an automatic candidate.
4. Prune only the confirmed set, one exact path at a time. Prefer `git worktree remove <path>` without `--force`; use `--force` only after the confirmation explicitly names that path and accepts its uncommitted contents. Do not run broad `rm -rf`; if ignored artifacts remain, list them and ask separately. Run `git worktree prune` only after the path result is recorded.
5. Simulators and other reclaimers are opt-in and scoped. Inspect first with `xcrun simctl list`, then delete only named unavailable devices or named test clones after confirmation. Never run `delete all`, delete runtimes, or remove application support, DerivedData, device support, or package caches as a blanket step. Any cache cleanup must name exact paths and retain data the user asked to keep.

This is the one playbook that deletes user state with no code review to catch a slip, so the gates above are the review.

**Reply:** `df -h /` before and after with space reclaimed, the worktrees pruned, and a one-line reason for each held back (in-use by which chat, or uncommitted work).
