# Project and personal skills

Read this when creating, placing, or substantially editing a skill.

Keep new project skills in `.agents/skills/<name>/` and personal skills in `~/.agents/skills/<name>/`. First inspect existing `.agents/skills/` and `.claude/skills/`; an existing skill remains authoritative. Resolve symlinks and do not create two copies of one feature map.

When creating a new shared skill on this local filesystem, expose the canonical directory to Claude Code with a relative directory symlink from `.claude/skills/<name>` to `../../.agents/skills/<name>` (the same relative layout works for personal skills). Create the parent directory if needed; do not overwrite a file, directory, or different symlink already at the destination. Check the resolved target and actual host discovery. If linking is unavailable, keep one canonical copy and report the discovery limitation; direct reading still works. Do not link the entire shared skills directory over existing Claude skills.

For authoring, use an available skill-creator when present. Otherwise edit SKILL.md directly with `name` and `description`, validate YAML and local references, then exercise the behavior it teaches. Do not require a Codex-only authoring skill in Claude Code.

## Verification skills

A generated verification skill, from `$create-verification-skill` or `$create-formal-verification-skill`, is a personal local skill by default: its files stay on this machine and out of the repository's history and `.gitignore`. Generate it in the repository, shared with the team, only when the user explicitly asks for that. An existing verification skill keeps the placement it already has.

**Personal local skill (the default).**

1. Put the canonical directory outside every repository, in the personal skill directory the user's or host's instructions name, otherwise `~/.agents/local-skills/<name>/`. Do not use `~/.agents/skills/`, which hosts load in every project. Run `git init` there and add no remote; commit the skill's changes there.
2. Copy [`link-into`](./link-into) to `<skill-dir>/bin/link-into` and keep it executable.
3. Once `<skill-dir>/SKILL.md` exists, run `bin/link-into <checkout-root>` from `<skill-dir>` for the main checkout and again for each worktree the skill drives. It links `.agents/skills/<name>` to the canonical directory and `.claude/skills/<name>` to `../../.agents/skills/<name>`, never over an existing file, directory, or different link, and adds `/.agents/skills/<name>`, `/.claude/skills/<name>`, and `/.verify/` to `$(git rev-parse --git-common-dir)/info/exclude`, the one exclude file that every worktree of the repository shares. The two link lines have no trailing slash because git sees a symlink as a file, and a pattern ending in `/` matches only directories.
4. Confirm `git status --porcelain` lists nothing from the skill or `.verify/` in each checkout, and `git check-ignore -v .agents/skills/<name> .claude/skills/<name> .verify/x` names `info/exclude`.
5. Name the canonical directory and the `bin/link-into` command in the generated skill's body, so a later agent in a new worktree links it instead of copying it.

**Shared in the repository (only on the user's explicit request).** Write the canonical directory at `.agents/skills/<name>/`, add the Claude link above, and add `.verify/` to `.gitignore` if the repository does not ignore it yet. The skill and its feature map are then committed like any project file; evidence still is not.
