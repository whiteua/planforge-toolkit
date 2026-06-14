# plan-brainstorming — Quick Reference

Turn ideas into validated design specs through collaborative dialogue.

## How to Invoke

In VS Code Copilot chat, type:

```
/plan-brainstorming <goal-file-path>
```

### Usage Examples

```bash
# With a goal file
/plan-brainstorming .docs/.plans/my-feature/goal.md

# Without a file — just describe the idea after the command
/plan-brainstorming I want to add WebSocket support to the notification system
```

You can also simply describe your idea in chat and mention "brainstorming" / "design" / "spec".

## Arguments

| Argument | Required | Description |
|---|---|---|
| Goal file path | Optional | Path to a `.md` file describing the idea. If omitted, describe the idea inline after the command. |

## Process (what happens)

1. Agent explores your project context (files, docs, commits)
2. Offers Visual Companion if visual questions are expected (you can decline)
3. Proposes a **depth tier** (Quick / Standard / Deep) — you confirm or adjust
4. Asks clarifying questions **one at a time** (prefer multiple-choice)
5. Proposes 2–3 approaches with trade-offs and a recommendation
6. Presents design section by section, asks for approval after each
7. Runs ambiguity sweep — closes all open questions
8. Writes the spec file and runs self-review
9. Asks you to review the written spec
10. On approval → invokes `plan-writing`

## Depth Tiers

| Tier | When | Spec size |
|---|---|---|
| Quick | Single-file change, bugfix, config tweak | Few sentences per section |
| Standard | Feature touching 2–5 components | Short paragraph per section |
| Deep | New subsystem, external integrations, complex failure modes | Full paragraphs, tables |

## Output

A spec file saved to `<dir>/<plan-root>-spec.md` next to the plan/goal file (or user-specified path).

Required sections: Goal, Architecture, Components, Data Flow, Error Handling, Testing Strategy, Out of Scope, Open Questions.

`Open Questions` **must be empty** (`(none)`) before handoff to plan-writing.

## Checklist Before Invoking

- [ ] You have a clear idea of what you want to build (even a rough one)
- [ ] Your workspace has the relevant project files accessible
- [ ] You're ready for a conversation (this skill asks questions interactively)

## Common Errors

| Symptom | Cause | Fix |
|---|---|---|
| Spec not written | Design not approved yet | Approve each section when asked |
| plan-writing not invoked | Open Questions remain | Answer all ambiguity questions |
| Visual Companion not working | Browser tools unavailable | Decline the companion; proceed text-only |

## Pipeline Position

```
[YOU ARE HERE] → plan-writing → plan-iterative-revision → plan-splitter → plan-executor → plan-resolver
```

**Previous:** (none — this is the entry point)  
**Next:** `plan-writing` (invoked automatically after spec approval)
