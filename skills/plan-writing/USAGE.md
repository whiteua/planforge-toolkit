# plan-writing — Quick Reference

Transform a validated spec into a detailed, bite-sized implementation plan.

## How to Invoke

In VS Code Copilot chat, type:

```
/plan-writing <spec-file-path>
```

### Usage Examples

```bash
# Standard invocation with a spec file
/plan-writing .docs/.plans/my-feature/spec.md

# Spec in a different location
/plan-writing .docs/.plans/my-feature/plan01-spec.md
```

Usually invoked **automatically** by `plan-brainstorming` after spec approval — manual invocation needed only if you skipped brainstorming or want to re-run.

## Arguments

| Argument | Required | Description |
|---|---|---|
| Spec file path | **Yes** | Path to a spec `.md` file that passes the preflight checks |

## What Happens

1. **Spec Preflight** — verifies all 8 required sections, no empty sections, `Open Questions` is `(none)`
2. **Tier Read** — inherits tier from spec's `> Tier:` line (defaults to Standard if missing)
3. **Scope Check** — flags multi-subsystem specs for decomposition
4. **File Structure** — maps out which files will be created/modified
5. **Task Generation** — writes tasks with TDD steps, exact code, file paths
6. **Self-Review** — checks spec coverage, placeholders, type consistency, task size
7. **Execution Handoff** — offers next pipeline step (audit via `plan-iterative-revision`, split via `plan-splitter`, or execute via `plan-executor`); waits for the user's explicit choice

## Spec Preflight Requirements

The input spec **must** have:
- All 8 headings: Goal, Architecture, Components, Data Flow, Error Handling, Testing Strategy, Out of Scope, Open Questions
- No empty sections (use `(none)` with rationale for N/A sections)
- `Open Questions` = empty or `(none)`

**If preflight fails → you must go back to `plan-brainstorming`.** The skill will NOT proceed.

## Task Size Rules

- Each task: **≤ 10 minutes of work** OR **≤ 100 lines of new code**
- Each step: **one action, 2–5 minutes**
- Exceeds limit → split into sub-tasks (Task N.1, N.2, ...)

## Tier Effect on Tasks

| Tier | Preconditions/Postconditions | Constraints | If stuck | Phase Checkpoints |
|---|---|---|---|---|
| Quick | Collapsed to `Done when:` line | Only when critical | Omit if no likely failures | Never |
| Standard | Full blocks | When multiple approaches exist | 2–3 failure modes | Optional |
| Deep | Full + detailed | Always present | Comprehensive | Recommended |

## Output

Plan file saved to `<dir>/<plan-root>-impl.md` (e.g. `plan01-impl.md`, next to the spec; or user-specified path).

## Checklist Before Invoking

- [ ] Spec exists and passes preflight (all 8 sections, Open Questions empty)
- [ ] Spec has been reviewed and approved by the user
- [ ] Workspace is accessible for file structure analysis

## Common Errors

| Symptom | Cause | Fix |
|---|---|---|
| "Spec preflight failed" | Missing section or non-empty Open Questions | Return to `plan-brainstorming` to fix the spec |
| Tasks too large | Complex feature crammed into one task | Agent should auto-split; if not, ask to split |
| "No tier line" message | Legacy spec without `> Tier:` | Not an error — defaults to Standard |

## Pipeline Position

```
plan-brainstorming → [YOU ARE HERE] → plan-iterative-revision → plan-splitter → plan-executor → plan-resolver
```

**Previous:** `plan-brainstorming` (produces the spec)  
**Next:** `plan-iterative-revision` (validates the written plan)
