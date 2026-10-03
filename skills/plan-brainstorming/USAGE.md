# plan-brainstorming — Quick Reference

Turn ideas into validated design specs through collaborative dialogue.

## How to Invoke

```
/plan-brainstorming <goal-file-path>
/plan-brainstorming <spec-file-path>   # amend mode: change an approved spec in place
/plan-brainstorming help   # show this quick reference in the dialogue language, nothing else
```

### Usage Examples

```bash
# With a goal file
/plan-brainstorming .docs/.plans/my-feature/goal.md

# Without a file — just describe the idea after the command
/plan-brainstorming I want to add WebSocket support to the notification system

# With a JSON list of code-review findings (file or pasted inline)
/plan-brainstorming .docs/reviews/review01.json

# From the unchecked items of the shared backlog (optionally one section)
/plan-brainstorming BACKLOG.md values-fix

# Amend an approved spec in place (for example after /plan-chain-runner discuss)
/plan-brainstorming .docs/.plans/my-feature/plan01-spec.md
```

You can also simply describe your idea in chat and mention "brainstorming" / "design" / "spec".

## Arguments

| Argument | Required | Description |
|---|---|---|
| Goal file path | Optional | Path to a `.md` file describing the idea. If omitted, describe the idea inline after the command. |
| Findings JSON | Optional | Path to a `.json` file (or inline JSON) with an array of findings: `file`, `line` (optional), `summary`, `failure_scenario`. Switches to findings mode. |
| `BACKLOG.md` [section] | Optional | The shared backlog at the repository root. Its unchecked items (of one section, when given) become the problem statement. First the agent matches them with the approved specs of the section (`backlog-sweep`) and, after you confirm, checks off `[x]` the ones a spec already covers; then it asks which of the rest go into this spec. After the spec is approved, its Out of Scope items are appended back to `BACKLOG.md`, and the items it took in are checked off `[x]` (`backlog-mark`). |
| Spec file path (`*-spec.md`) | Optional | An approved spec with `# Goal`. Switches to amend mode: only the change is discussed, the spec is edited in place and re-checked, no new plan is written. |

### Findings mode

The input is a list of defects instead of an idea. The agent:

1. Validates the JSON with `scripts/brainstorm_tool.py findings-parse` and assigns ids `F1`..`Fn`.
2. Checks every finding against the code: `confirmed`, `partial`, `disputed`, or `stale` (more than 10 findings: split across subagents when the host supports them).
3. Asks which findings go into this spec, then runs the normal flow.
4. Writes a `### Findings Traceability` table under `## Components`. Excluded findings go to `## Out of Scope`.
5. Runs `brainstorm_tool.py findings-coverage` so that no finding id is lost.

Spec path: `review01.json` → `review01-spec.md` next to it. With inline JSON the agent asks for the path.

### Amend mode

The input is an approved spec that must change. The agent discusses only the change, edits the spec in place, runs `spec-check` and the self-review, and asks for your approval; new Out of Scope items go to `BACKLOG.md`, and the `BACKLOG.md` items the change took in are checked off `[x]`. Checked items the change removed from the spec are unchecked (`backlog-unmark`) after you confirm. Withdrawing a spec goes the same way: its items are unchecked after you confirm, and you remove or rename the spec file yourself. Items marked `[-]` (cancelled) are yours: the skills never set or clear them. It writes no new plan: the chain journal sees the changed spec, and the next `/plan-chain-runner continue` (or `/plan-writing <spec>`) asks whether to rewrite the plan.

## Process (what happens)

1. Agent explores your project context (files, docs, commits); in findings mode it validates and triages the findings; in backlog mode it matches the unchecked items with the approved specs of their section and offers to check off the covered ones
2. Proposes a **depth tier** (Quick / Standard / Deep) — you confirm or adjust
3. Offers the Visual Companion when the questions ahead are visual (you can decline)
4. Asks clarifying questions **one at a time** (prefer multiple-choice)
5. Proposes approaches with trade-offs and a recommendation (2–3 on Standard/Deep, one on Quick)
6. Presents design section by section, asks for approval after each
7. Runs ambiguity sweep — closes all open questions; if an answer changes the design, re-presents that section. Then proposes the chain settings in one message (`Chain`, external environments with read and write rights, changes named first) — you confirm or edit them; they are written above `# Goal`
8. Writes the spec file, checks it with `brainstorm_tool.py spec-check`, runs self-review incl. a fidelity check against your original request (Deep: plus a reviewer subagent)
9. Asks you to review the written spec
10. On approval → appends the spec's Out of Scope items (and the spec map, when the goal was split into several specs) to `BACKLOG.md` at the repository root (in backlog mode it also checks off the items the spec took in), then invokes `plan-writing`

## Depth Tiers

| Tier | When | Spec size |
|---|---|---|
| Quick | Single-file change, bugfix, config tweak | Few sentences per section |
| Standard | Feature touching 2–5 components | Short paragraph per section |
| Deep | New subsystem, external integrations, complex failure modes | Full paragraphs, tables |

## Output

A spec file saved to `<dir>/<plan-root>-spec.md` next to the goal file (or user-specified path). The skill does not commit it. After your approval it also creates the chain journal `<goal>-chain.json` next to the spec, where the later skills record their stages, questions and findings; the findings come back as `<goal>-followups.json` (`/plan-brainstorming <goal>-followups.json` starts the next cycle from them).

Language: the dialogue and the spec body follow the language of your input (a Russian goal gives a Russian spec). The `> Tier:` line and the section headings stay in English.

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
| plan-writing not invoked | Open Questions remain or `spec-check` fails | Answer all ambiguity questions; the agent fixes the spec structure |
| Visual Companion not working | Browser tools unavailable | Decline the companion; proceed text-only |
| Mockup files appear in the repo | Companion sessions persist in `.planforge/brainstorm/` | Add `.planforge/` to `.gitignore` |
| Findings mode stops right away | `brainstorm_tool.py findings-parse` reported errors (missing field, bad `line`, invalid JSON) | Fix the listed items in the JSON and re-run |

## Pipeline Position

```
[YOU ARE HERE] → plan-writing → plan-iterative-revision → plan-splitter → plan-executor → plan-resolver
```

**Previous:** (none — this is the entry point)  
**Next:** `plan-writing` (invoked automatically after spec approval)
