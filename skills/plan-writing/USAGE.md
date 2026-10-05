# plan-writing — Quick Reference

Transform an approved spec into a detailed, bite-sized implementation plan.

## How to Invoke

```
/plan-writing <spec-file-path>
/plan-writing help   # show this quick reference in the dialogue language, nothing else
```

### Usage Examples

```bash
# Standard invocation with a spec from plan-brainstorming
/plan-writing .docs/.plans/my-feature/plan01-spec.md

# Any spec name works; the plan goes next to it
/plan-writing .docs/.plans/my-feature/auth-spec.md
```

You start it yourself after `plan-brainstorming` has approved the spec (its closing report names the command), or `plan-chain-runner` starts it; run it again to rewrite the plan.

## Arguments

| Argument | Required | Description |
|---|---|---|
| Spec file path | **Yes** | Path to a spec `.md` file that passes `spec-check` |

## What Happens

1. **Spec Preflight** — `plan-brainstorming/scripts/brainstorm_tool.py spec-check`: all 8 sections in order, none empty, `Open Questions` is `(none)`; it also returns the chain settings (`> Chain:`, `> Environment:`, `> Backlog:`), which stay in the spec. An old spec without them: the skill asks and writes the answers into the plan header
2. **Tier Read** — inherits the tier from the spec's `> Tier:` line (Standard if missing)
3. **Scope Check** — a spec with several independent subsystems stops for your choice of how to split it; a spec whose volume estimate (`spec-check` `volume`) or planned task count is over 40 tasks asks once whether to continue with one plan or return to `plan-brainstorming` (a run without you continues)
4. **File Structure** — maps out which files will be created/modified
5. **Task Generation** — tasks with TDD steps, exact code, file paths; no commit steps
6. **Check and Self-Review** — `scripts/plan_tool.py plan-check` for the format contract (it also returns `size_class` and warns `plan-oversized` over the budget; `--max-tasks`, `--max-bytes` override it), then spec coverage, consistency and task size (Deep: plus a reviewer subagent); the chain journal `<goal>-chain.json` next to the spec records the `writing` stage (running at the start, done with the plan), and a question asked in a run without you stops the skill and stays open in the journal
7. **Execution Handoff** — offers the next step (audit via `plan-iterative-revision`, split via `plan-splitter`, or execute via `plan-executor`) with the task count, plan size and `size_class` (`small` ≤ 15 tasks, `large` over 40 tasks or 150000 bytes, else `medium`); with `split=auto` the splitter's gate decides on the split; a `large` plan gets the advice to split the goal in `plan-brainstorming`; with an explicit `Chain` in the settings, `split=always|never` and `resolver=` are stated, not asked; waits for your explicit choice

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
- Cannot be split → `**Size:** <N> lines — <reason>` in the task; without it `plan-check` warns above 100 lines of code and fails above 150
- Creates or modifies `CLAUDE.md` → `**Structural event:** <skill|script|contract|convention|artifact> — <reason>` in the task; without it `plan-check` warns `claude-md-edit`, another key is an error

## Tier Effect on Tasks

| Tier | Done-state | Constraints | If stuck | Checkpoint tasks |
|---|---|---|---|---|
| Quick | One `Done when:` line | Omit | Omit | Not used |
| Standard | Full Preconditions + Postconditions | Only for a real fork | Only for likely traps | Allowed |
| Deep | Full Preconditions + Postconditions | Only for a real fork | Recommended | Allowed |

## Output

Plan file next to the spec: `<X>-spec.md` → `<X>-impl.md` (e.g. `plan01-spec.md` → `plan01-impl.md`), or a user-specified path.

The plan header carries `**Spec:**` and `**Tier:**`; tasks use `### Task N: <title>` headings. This is the format `plan-executor` and `plan-resolver` parse. Plans contain no commit steps; after the audit, `/plan-executor <plan> commit` commits the run's files and the audit's fixes.

Chain settings and external-system permissions are not copied into the plan: every skill reads them from the spec through `**Spec:**`. Only a plan written from an old spec without settings carries `**Chain:**`, `**Environments:**` (with `read=`/`write=` rights) and `**Backlog:**` in its header. A task that touches an external system has `` **External:** `name` (read|write) — what ``.

Language: the plan body follows the spec's language; the parsed markers (`### Task N:`, `**Files:**`, `**Step N:**`, ...) stay in English.

## Checklist Before Invoking

- [ ] Spec exists and passes preflight (all 8 sections, Open Questions empty)
- [ ] Spec has been reviewed and approved by the user
- [ ] Workspace is accessible for file structure analysis

## Helper Commands

`scripts/plan_tool.py` also serves plan-resolver, which calls these on its first and closing full passes:

| Command | Output |
|---|---|
| `python scripts/plan_tool.py skeleton <plan> [--tasks 1,7.1] [--code none\|signatures]` | The plan without code bodies: the header whole; per task its heading, `**Files:**`, `**Preconditions:**`/`**Postconditions:**`/`**Done when:**`/`**Constraints:**`/`**If stuck:**`, `**External:**`, `**Size:**`, `**Structural event:**`, step headings and `Run:`/`Expected:` lines; headings between tasks stay. Each code block becomes `[code <lang>, <N> lines: <signatures>]` (lines starting with `def`, `async def`, `class`, `function`, `export`, `func`, `interface`, `type`, `const`; at most five, then `…`); `--code none` and `markdown`/`text`/`json`/`yaml`/unlabelled blocks give only the language and the line count. `--tasks` keeps the header and the named tasks in plan order. |
| `python scripts/plan_tool.py task <plan> <id>` | One task byte for byte (its lines `line_start..line_end` from `plan-tasks`). |

Unlike every other command these two print text, not JSON: stdout is plan text, warnings (`no-tasks`, `unclosed-fence`) go to stderr, and an error is one JSON line on stderr with exit `2` (`plan-unreadable`, `task-not-found: <id>`, `plan-brainstorming not installed alongside`, an unknown `--code`). Nothing is stored: the skeleton is generated on demand, so it never goes stale.

## Common Errors

| Symptom | Cause | Fix |
|---|---|---|
| "Spec preflight failed" | Missing section or non-empty Open Questions | Return to `plan-brainstorming` to fix the spec |
| "plan-brainstorming not installed" | `../plan-brainstorming/scripts/brainstorm_tool.py` missing | Install both skills side by side |
| Tasks too large | Complex feature crammed into one task | The agent splits it; `plan-check` warns above 100 lines of code in a task |
| "No tier line" message | Legacy spec without `> Tier:` | Not an error — defaults to Standard |
| "needs the access type (read) or (write)" / "is not allowed: write=deny" | `External` line without the access type, or access the settings deny | Add `(read)`/`(write)`; a denied access means the plan must change or the user must change the spec |
| "settings are unavailable" | The plan has `External` lines, the spec at `**Spec:**` is missing and the header has no settings | Restore the spec path in `**Spec:**` |

## Pipeline Position

```
plan-brainstorming → [YOU ARE HERE] → plan-iterative-revision → plan-splitter → plan-executor → plan-resolver
```

**Previous:** `plan-brainstorming` (produces the spec)  
**Next:** `plan-iterative-revision` (validates the written plan)
