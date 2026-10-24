# Project and personal skills

Read this when creating, placing, or substantially editing a skill.

Keep new project skills in `.agents/skills/<name>/` and personal skills in `~/.agents/skills/<name>/`. First inspect existing `.agents/skills/` and `.claude/skills/`; an existing skill remains authoritative. Resolve symlinks and do not create two copies of one feature map.

When creating a new shared skill on this local filesystem, expose the canonical directory to Claude Code with a relative directory symlink from `.claude/skills/<name>` to `../../.agents/skills/<name>` (the same relative layout works for personal skills). Create the parent directory if needed; do not overwrite a file, directory, or different symlink already at the destination. Check the resolved target and actual host discovery. If linking is unavailable, keep one canonical copy and report the discovery limitation; direct reading still works. Do not link the entire shared skills directory over existing Claude skills.

For authoring, use an available skill-creator when present. Otherwise edit SKILL.md directly with `name` and `description`, validate YAML and local references, then exercise the behavior it teaches. Do not require a Codex-only authoring skill in Claude Code. Generated verification skills and their feature maps stay project-local.
