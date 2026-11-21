---
name: architect
description: "Sketch types, signatures, and module structure before code, then stay in the loop while implementation fills in. Use for $architect, 'architect this', 'design this', or non-trivial work where jumping to code would lock in the wrong shape."
---

Read [the shared runtime contract](../../references/runtime.md) before this workflow.

# Architect

Before writing code, trace every system the change touches (the **how** skill), then sketch two different shapes for it (types, signatures, module boundaries) and pick the one where each piece of state has one owner, each task has one way to do it, and callers need to know least. Redesign instead of patching if workarounds repeat.

For a large or contested design, run the **arena** skill instead of sketching alone, with `architect runners` from the effective policy, or its `defaultPanel` when that panel is absent. For the hardest design work, such as cross-cutting ownership changes or subtle concurrency or algorithms, use `hardest architect runners` if the effective policy explicitly configures it, record why the design needs that tier, and pass the selected panel to arena. A large project alone does not require the harder panel.

After the design is settled, classify each implementation delegate by its own difficulty. Ordinary work uses its code-playbook role; only implementation that remains intrinsically difficult uses `hardest tasks`. Do not carry the design panel's model tier into downstream work.
