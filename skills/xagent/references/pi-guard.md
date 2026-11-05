# pi write guard

Read before dispatching pi through [xagent](../SKILL.md).

The pi write guard accepts plain relative or absolute paths, including paths through existing internal symlinks. Use plain paths instead of `@`, `~`, URI or Unicode-space aliases that pi would normalize. Bash checks accept a limited non-expanding command syntax with ordinary quoted arguments, and reject output redirection and `--output` options. Tests/build scripts still execute project code, so this is an accident guard, not a sandbox.
