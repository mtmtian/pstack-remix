# benny

Before using this pack, read [`references/runtime.md`](./references/runtime.md). It is the shared Codex host contract.

Benny gives you two dormant host goal-run profiles for Slack issue reports. One triages each report. The other reproduces confirmed bugs and may prepare a small draft fix. The pack does not create, arm, enable, or invoke a scheduler, event binding, Slack message, tracker write, or pull request by itself.

The files in this directory are dormant setup and run sources. They do not appear as slash skills. A goal is an optional finite durable objective; it does not replace a recurring scheduler or an incoming-event subscription. A single report may also be handled by a manual run or an actually registered event trigger.

## set it up

1. Ask the agent to read [`FOR_AGENTS.md`](./FOR_AGENTS.md) and name the target repository.
2. Let setup merge this whole directory into the target at `.agents/automations/benny/`. It must preserve destination-only files and review conflicts instead of overwriting local edits.
3. Let setup verify that the pstack plugin for the current host and the required shared skills resolve for a fresh target agent. A local target may use project or user scope; a remote runner must pass its own independent check. It must not edit `.cursor/settings.json` or another plugin manifest.
4. Keep user-owned configuration outside the copied pack, for example in `.agents/benny/`. Adapt [`configuration.example.yaml`](./templates/configuration.example.yaml) and [`feature-map.example.md`](./skills/reproduce-and-fix-issues/references/feature-map.example.md).
5. Commit `.agents/automations/benny/` and any secret-free configuration before a run reads them.
6. Review the generated configuration and two goal prompt drafts. Establish a native goal only after the user explicitly authorizes that target and the host exposes the required tools. A missing Slack event or scheduler interface leaves the drafts dormant; a manual single run remains available per report.
7. Run the harmless adapter check and thread-safety checks before allowing any external write. Use only Slack, tracker, repository, browser, and pull-request capabilities that are actually exposed in the current host.
