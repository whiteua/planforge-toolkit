---
name: plan-writing
description: "Use when an approved spec (a `*-spec.md` from plan-brainstorming) must become a step-by-step implementation plan. Produces bite-sized TDD tasks with exact files, code and commands in the format plan-executor and plan-resolver parse."
---

# Writing Plans

Turn an approved spec into an implementation plan for an engineer who knows
nothing about this codebase: exact files, complete code, exact commands and
expected output, bite-sized tasks. DRY. YAGNI. TDD.

**Announce at start:** "I'm using the plan-writing skill to create the implementation plan."

> **Install requirement:** `plan-brainstorming` must be installed in the same
> parent directory: the spec contract and its checker live there. If
> `../plan-brainstorming/scripts/brainstorm_tool.py` is missing, STOP and tell
> the user to install `plan-brainstorming` alongside.

## Language

These instructions are in English. Write the plan body in the language of the
spec. Keep these tokens in English verbatim, because parsers match them:
`### Task N:`, `**Spec:**`, `**Tier:**`, `**Files:**`, `- Create:` /
`- Modify:` / `- Test:`, `**Preconditions:**`, `**Postconditions:**`,
`**Done when:**`, `- [ ] **Step N:**`.

## Tool

`python "<SKILL_DIR>/scripts/plan_tool.py" <command>` (`<SKILL_DIR>` = this
skill's directory, absolute). Exit codes: `0` ok, `1` check failed, `2` bad input.

| Command | Use |
|---|---|
| `plan-path <spec>` | Plan path: `<X>-spec.md` → `<X>-impl.md` next to the spec (user preference overrides). |
| `plan-check <plan> --root <project>` | Plan format contract, after writing the plan. |

## 1. Spec Preflight

Run `python "<SKILL_DIR>/../plan-brainstorming/scripts/brainstorm_tool.py" spec-check <spec>`.

- Exit `0`: continue. Show `warnings`, they do not block.
- Exit `1`: STOP. Show the `errors` and ask the user to re-run `plan-brainstorming` on the failing part. Never invoke it yourself: backward moves in the pipeline are the user's call.
- Exit `2`: STOP. The spec cannot be read.

Tier: the `tier` field of the result. `Quick` / `Standard` / `Deep` are used as-is. Missing or unknown: use **Standard** and announce "Spec has no Tier line; defaulting to Standard."

## 2. Scope Check

If the spec covers several independent subsystems, STOP and propose one plan per subsystem. Continue only after the user chooses. Each plan must produce working, testable software on its own.

## 3. File Structure

Before defining tasks, list the files to create or modify and each file's single responsibility. Follow existing patterns. Split a file you touch only when it has grown unwieldy. Files that change together live together.

**Read before you modify.** For every `Modify:` target, open the file first and record one line in the task's `Files` block: *current state / what changes / what must be preserved*. This makes `path:123-145` line ranges real instead of guessed.

## 4. Tasks

**Size.** A task fits **10 minutes of work OR 100 lines of new code**, whichever comes first. Otherwise split it into `Task N.1`, `Task N.2`, … recursively. Warning signs: more than ~5 implementation steps, new logic in more than 2-3 files, "and then" chains in the title. A **step** is one action of 2-5 minutes: write the failing test, run it, implement, run again.

**Tier** (from Preflight) decides how much each task expands. See `references/task-tiers.md` for the table and for when to add `Constraints` and `If stuck`. Every tier keeps the core: `Files`, numbered steps, and a verifiable done-state.

**No commit steps.** A plan never runs `git commit`: no skill commits on the engineer's branch; `plan-executor` keeps rollback snapshots in hidden refs, and the final commit is the engineer's.

### Plan header

```markdown
# [Feature Name] Implementation Plan

> **For agentic workers:** Execute this plan with the `plan-executor` skill (one unit at a time, ledger-backed, gated). If the plan has not been audited yet, run `plan-iterative-revision` on it first. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** [spec path relative to the plan]

**Tier:** [Quick|Standard|Deep]

**Goal:** [one sentence]

**Architecture:** [2-3 sentences]

**Tech Stack:** [key technologies]

---
```

### Task (Standard / Deep)

````markdown
### Task N: [Component Name]

**Files:**
- Create: `exact/path/to/file.py`
- Modify: `exact/path/to/existing.py:123-145` (current state / change / preserve)
- Test: `tests/exact/path/to/test_file.py`

**Preconditions:**
- [concrete artifact or passing test this task needs]

**Postconditions:**
- [observable artifact or check this task produces]
- [what is deliberately NOT changed, when scope creep is likely]

- [ ] **Step 1: Write the failing test**

```python
def test_specific_behavior():
    assert function(input) == expected
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/path/test_file.py::test_specific_behavior -v`
Expected: FAIL with "function not defined"

- [ ] **Step 3: Implement**

```python
def function(input):
    return expected
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/path/test_file.py -v`
Expected: PASS
````

On Quick, `Preconditions` and `Postconditions` collapse into one line: `**Done when:** <observable result>`.

A postcondition must be reachable by this task's own steps. If it needs work from another task, split or reorder. Dependencies on earlier tasks go in `Preconditions`.

### Checkpoint task (Standard / Deep only, optional)

After a logical group of tasks you may add one smoke test of the group. It is an ordinary task with its own number, so the executor tracks and gates it:

```markdown
### Task N: Checkpoint — [what this group proves]

- [ ] **Step 1: Run the smoke check**

Run: `<concrete command>`
Expected: `<observable result>`

**Done when:** [the expected result is observed]
```

No `Files` block is needed. If you cannot name a concrete command, leave the checkpoint out.

## 5. No Placeholders

Every step contains what the engineer needs. Plan failures:
- "TBD", "TODO", "implement later", "fill in details"
- "Add appropriate error handling" / "handle edge cases" without saying which
- "Write tests for the above" without test code
- "Similar to Task N": repeat the code, tasks may be read out of order
- a code step without a code block
- types, functions or methods not defined in any task

## 6. Check and Self-Review

1. Run `plan-check <plan> --root <project>` until it exits `0`. It enforces the header fields, task headings and unique ids, the task core per tier, backticked file paths, no commit steps, and no placeholders. Review its `warnings`: a missing `Modify:` target is fine only if an earlier task creates it, and a code-size warning means the task needs splitting.
2. Then check what the tool cannot:
   - **Spec coverage:** every spec requirement maps to a task. Add a task for each gap.
   - **Consistency:** names, types and signatures match across tasks (`clearLayers()` in Task 3 and `clearFullLayers()` in Task 7 is a bug).
   - **Size:** each task fits the limit. Split it if not.
3. On the Deep tier, if the host supports subagents, also dispatch a reviewer with `plan-document-reviewer-prompt.md` and fix what it reports.

Fix issues inline and re-run `plan-check`.

## 7. Execution Handoff

> "Plan complete and saved to `<path>`. Recommended next steps:
> 1. **Audit (recommended):** run `plan-iterative-revision` to cross-check the plan against the codebase.
> 2. **Split:** if the plan has more than 15–20 tasks or spans several modules, run `plan-splitter` (it decides with a 5-factor gate).
> 3. **Execute:** for small, audited plans, run `plan-executor`. The plan has no commit steps; committing the result is up to you.
>
> Which step?"

Do not invoke any skill automatically. Wait for the user's choice.
