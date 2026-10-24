# Agent guide

This repository is the Codex and Claude Code fork of cursor/plugins `pstack`, pinned in `UPSTREAM.json`. [ADAPTATION.md](ADAPTATION.md) records each local decision and its reason.

- Gate: `bash scripts/check.sh` (`runtime` or `build` for one half). On macOS, put coreutils' `gnubin` first in `PATH` as [docs/ci.md](docs/ci.md) shows.
- Upstream sync: run `node scripts/check-upstream.mjs`, then merge each changed file by the rules in [Upstream sync](ADAPTATION.md#upstream-sync). Never copy an upstream directory over this tree.
- A [fork guard](docs/ci.md#fork-guards) failure means a sync dropped a recorded decision or brought back Cursor-only wording. Fix the text, not the guard.
- Host caches and installed copies are generated installation artifacts, never edit targets. Edit this checkout.
- After maintained-source changes, refresh the installations with the commands under [Refresh installations](ADAPTATION.md#refresh-installations).
