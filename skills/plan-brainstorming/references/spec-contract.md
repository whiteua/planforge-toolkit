# Spec Contract

The structural contract every spec must satisfy before `plan-writing` consumes it, plus the
artifact names and hand-off rules shared by both skills.

## Required sections

A spec MUST contain these headings, in this order, in English verbatim (they are matched
literally even when the body is in another language):

1. `# Goal`
2. `## Architecture`
3. `## Components`
4. `## Data Flow`
5. `## Error Handling`
6. `## Testing Strategy`
7. `## Out of Scope`
8. `## Open Questions`

| Section | Must contain |
|---|---|
| Goal | One sentence describing the outcome. Not a list of features. |
| Architecture | 2-5 sentences on the approach and the decisions made, citing the existing code they rest on (`path:line`). |
| Components | Named units, each with a one-line responsibility; existing units cite their file. |
| Data Flow | How information moves between components, or `(none)` with rationale. |
| Error Handling | Failure modes and how each is surfaced or handled. |
| Testing Strategy | What is tested, at what level, and what is intentionally not tested. |
| Out of Scope | Explicit list of related work this spec does NOT cover. Never `(none)`. |
| Open Questions | Unresolved decisions. **Must be empty before plan-writing starts.** |

A heading with body `(none)` plus a one-line rationale is acceptable where a section does not
apply (e.g. Data Flow for a pure CLI tool); a missing heading is a violation. `# Goal` is the
document's only H1: no separate title heading.

Depth per section is tier-driven (`depth-tiers.md`); tiers change fill depth only.

## Tier line

Above `# Goal`: `> Tier: Quick|Standard|Deep` (bold forms such as `> **Tier:** Quick` are also
recognised). It is metadata, not a heading. `plan-brainstorming` writes the confirmed tier;
`plan-writing` reads it and defaults to Standard when it is missing or unknown
(`../../plan-writing/references/task-tiers.md`).

## Artifacts and naming

| Artifact | Path | Owner |
|---|---|---|
| goal / idea | goal file or chat input | user |
| spec | `<plan-root>-spec.md`, next to the goal file | `plan-brainstorming` |
| plan | `<plan-root>-impl.md`, same directory (`plan_tool.py plan-path`) | `plan-writing` |
| execution result | code in the working tree; the engineer commits | `plan-executor` |

`<plan-root>` = the goal file name without extension and without any descriptive suffix after
the numeric segment: `plan01.md` → `plan01-spec.md`; `plan02-goal.md` → `plan02-spec.md`;
`superplan03-abstract.md` → `superplan03-spec.md`; `review01.json` → `review01-spec.md`. A goal
file without a numeric segment keeps its whole stem (`goal.md` → `goal-spec.md`). Inline input has
no file: ask for the path and recommend a default. A user preference overrides the default.

## Hand-off rules

1. Spec → plan only after the spec self-review passed and the user explicitly approved the
   written spec file.
2. Plan → spec is never automatic: when `plan-writing` finds the spec non-conforming, it stops
   and asks the user to re-enter `plan-brainstorming`.
3. One owner per artifact: other skills read a spec or plan but never rewrite it.

## Preflight (run by plan-writing)

`python "<SKILL_DIR>/scripts/brainstorm_tool.py" spec-check <spec>` checks: all 8 headings
present and in order; no empty section; `Out of Scope` non-empty; `Open Questions` empty or
`(none)` (+ one-line rationale). Exit `1` → `plan-writing` stops and sends the user back to
`plan-brainstorming`; it never invokes it itself.

## Glossary

| Term | Meaning |
|---|---|
| spec | Design document: what and why. |
| plan | Implementation document: how, step by step. |
| task | A plan unit that fits 10 minutes or 100 lines of new code. |
| step | One action inside a task (2-5 minutes), tracked as `- [ ]`. |
| tier | Spec and plan depth level (Quick / Standard / Deep). |
