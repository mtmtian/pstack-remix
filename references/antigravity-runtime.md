# Antigravity runtime

This adapter shares the pstack configuration view with Codex and Claude Code. It does not claim that Antigravity exposes the same native agent, model, or delegation APIs.

## Read shared policy

Resolve `<plugin-root>` from this skill's installed path and run:

```sh
node <plugin-root>/bin/config.mjs show --host antigravity
```

The command reads `~/.config/pstack/config.json`. It returns the common `roles`, `panels`, `reasoning_effort`, `required_panel_members`, `auxiliary_panel_members`, and `xagent_effort_caps` values. It ignores the Codex and Claude Code host overrides, because the stored schema defines no Antigravity-specific preferences. If the file is absent, it prints inherited defaults and creates neither the file nor its parent directory.

`update --host antigravity` is unsupported and must fail without changing preferences. Use an existing supported setup or update path only for an explicitly requested configuration change.

## Apply only observed capabilities

The JSON output is a shared-policy snapshot, not proof that Antigravity supports a named model, reasoning-effort value, native agent interface, process tool, goal, scheduler, or plugin invocation. Check the tools exposed in the current session and the applicable user, project, and host instructions before using any policy value. Do not infer Codex or Claude behavior from the configuration output.

`xagent:<agent>` and `required_panel_members` are displayed for visibility. They do not grant permission or start an external process. Delegate only when the user authorized it, Antigravity exposes a suitable execution tool, and the task scope permits it. Keep the same scope, read/write boundary, and evidence standard as for other hosts.
