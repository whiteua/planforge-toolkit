# plan-writing — Quick Reference

Transform an approved spec into a detailed, bite-sized implementation plan.

## How to Invoke

```
/plan-writing <spec-file-path>
```

### Usage Examples

```bash
# Standard invocation with a spec from plan-brainstorming
/plan-writing .docs/.plans/my-feature/plan01-spec.md

# Any spec name works; the plan goes next to it
/plan-writing .docs/.plans/my-feature/auth-spec.md
```

Usually invoked **automatically** by `plan-brainstorming` after spec approval — manual invocation needed only if you skipped brainstorming or want to re-run.

## Arguments

| Argument | Required | Description |
|---|---|---|
| Spec file path | **Yes** | Path to a spec `.md` file that passes `spec-check` |

## What Happens

1. **Spec Preflight** — `plan-brainstorming/scripts/brainstorm_tool.py spec-check`: all 8 sections in order, none empty, `Open Questions` is `(none)`
2. **Tier Read** — inherits the tier from the spec's `> Tier:` line (Standard if missing)
3. **Scope Check** — a spec with several independent subsystems stops for your choice of how to split it
4. **File Structure** — maps out which files will be created/modified
5. **Task Generation** — tasks with TDD steps, exact code, file paths; no commit steps
6. **Check and Self-Review** — `scripts/plan_tool.py plan-check` for the format contract, then spec coverage, consistency and task size (Deep: plus a reviewer subagent)
7. **Execution Handoff** — offers the next step (audit via `plan-iterative-revision`, split via `plan-splitter`, or execute via `plan-executor`); waits for your explicit choice

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

| Tier | Done-state | Constraints | If stuck | Checkpoint tasks |
|---|---|---|---|---|
| Quick | One `Done when:` line | Omit | Omit | Not used |
| Standard | Full Preconditions + Postconditions | Only for a real fork | Only for likely traps | Allowed |
| Deep | Full Preconditions + Postconditions | Only for a real fork | Recommended | Allowed |

## Output

Plan file next to the spec: `<X>-spec.md` → `<X>-impl.md` (e.g. `plan01-spec.md` → `plan01-impl.md`), or a user-specified path.

The plan header carries `**Spec:**` and `**Tier:**`; tasks use `### Task N: <title>` headings. This is the format `plan-executor` and `plan-resolver` parse. Plans contain no `git commit` steps; committing the result is up to you.

Language: the plan body follows the spec's language; the parsed markers (`### Task N:`, `**Files:**`, `**Step N:**`, ...) stay in English.

## Checklist Before Invoking

- [ ] Spec exists and passes preflight (all 8 sections, Open Questions empty)
- [ ] Spec has been reviewed and approved by the user
- [ ] Workspace is accessible for file structure analysis

## Common Errors

| Symptom | Cause | Fix |
|---|---|---|
| "Spec preflight failed" | Missing section or non-empty Open Questions | Return to `plan-brainstorming` to fix the spec |
| "plan-brainstorming not installed" | `../plan-brainstorming/scripts/brainstorm_tool.py` missing | Install both skills side by side |
| Tasks too large | Complex feature crammed into one task | The agent splits it; `plan-check` warns above 100 lines of code in a task |
| "No tier line" message | Legacy spec without `> Tier:` | Not an error — defaults to Standard |

## Pipeline Position

```
plan-brainstorming → [YOU ARE HERE] → plan-iterative-revision → plan-splitter → plan-executor → plan-resolver
```

**Previous:** `plan-brainstorming` (produces the spec)  
**Next:** `plan-iterative-revision` (validates the written plan)
