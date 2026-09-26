# Codex adapter

Read [the shared runtime](./runtime.md) first. This file defines only Codex-specific behavior.

- Entry points keep the existing namespace, such as `$pstack-codex:poteto-mode` and `$pstack-codex:setup-pstack`.
- Resolve preferences with `node <plugin-root>/bin/config.mjs show --host codex`. Validate concrete IDs and effort against the current collaboration schema. Fixed-model roles cannot be overridden. `inherit-parent`/`auto` omit the model field. Pass `reasoning_effort` only if the selected role and actual schema accept it.
- Use exposed collaboration tools, which may include `spawn_agent`, `send_message`, `followup_task`, `list_agents`, `wait_agent`, and `interrupt_agent`. Use the real `agent_type` and available role names. Do not send Claude/Cursor-only fields such as `subagent_type`, `run_in_background`, `readonly`, `environment`, or `cloud_base_branch`.
- `agents/poteto-agent.md` and `agents/comment-sicko.md` are prompt templates here, not registered Codex roles. Pass the file pointer to an appropriate supported role. Claude frontmatter in those shared files does not register a Codex role or enforce its tools; enforce scope through the selected host role and brief.
- Close children only after a final answer, explicit completion event, or confirmed completed/failed/canceled status. Preserve host-specific cancellation and progress rules.
- Create a native goal only on an explicit user request. Use actual `create_goal`, `get_goal`, and `update_goal` schemas. Reuse a matching active goal, never replace another one implicitly. Mark complete only with evidence; pause only on request; use blocked only under the tool's repeated-blocker conditions. Set a token budget only when the user requested one. Retain returned final usage accounting when applicable.
- Native goals do not imply timers. Use available process/session waits, events, or separately authorized automations. Report missing continuation or scheduling honestly.
- Prefer supported Codex task/history tools for prior sessions. Apply the user's current AGENTS.md and applicable local rules; do not copy user-specific rules into the plugin.
