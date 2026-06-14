---
name: plan-writing
description: Use when you have a spec or requirements for a multi-step task, before touching code
---

# Writing Plans

## Lifecycle & Vocabulary

This skill is the second stage of a two-stage pipeline. The shared contract
between stages lives in dedicated reference files - read them once before
you start producing a plan:

- `../plan-brainstorming/references/plan-lifecycle.md` - pipeline diagram and handoff rules.
- `../plan-brainstorming/references/spec-contract.md` - required structure of every spec document.

> **Install requirement:** `plan-brainstorming` must be installed in the same
> parent directory (the contract files above are loaded from it). If they are
> missing, STOP and tell the user to install `plan-brainstorming` alongside.

Same vocabulary is used by `plan-brainstorming`:

| Term | Meaning |
|---|---|
| spec | Design document - what & why. Produced by `plan-brainstorming`. |
| plan | Implementation document - how, step by step. Produced here. |
| task | Plan unit fitting 10 min OR 100 lines of new code. |
| step | Single action inside a task (2-5 min). |

## Overview

Write comprehensive implementation plans assuming the engineer has zero context for our codebase and questionable taste. Document everything they need to know: which files to touch for each task, code, testing, docs they might need to check, how to test it. Give them the whole plan as bite-sized tasks. DRY. YAGNI. TDD. Frequent commits.

Assume they are a skilled developer, but know almost nothing about our toolset or problem domain. Assume they don't know good test design very well.

**Announce at start:** "I'm using the plan-writing skill to create the implementation plan."

**Context:** If isolation is needed at execution time, the engineer creates a git worktree/branch before running `plan-executor`; this skill does not manage worktrees.

**Save plans to:** `<plan-root>-impl.md` in the same directory as the spec.
- `<plan-root>` = the plan filename stripped of its extension and any descriptive suffix after the numeric segment (same derivation as for `-spec.md`).
  - `plan01-spec.md` → implementation plan `plan01-impl.md`
  - `plan02-spec.md` → implementation plan `plan02-impl.md`
  - `superplan03-spec.md` → implementation plan `superplan03-impl.md`
- (User preferences for plan location override this default)

## Spec Contract Preflight

Before doing anything else, verify the input spec matches the contract.

**Required checks (all must pass):**

1. Spec file exists at the path the user pointed to.
2. Spec contains all 8 required headings from `../plan-brainstorming/references/spec-contract.md`, in the listed order.
3. No required section is empty; sections that genuinely do not apply use `(none)` with a one-line rationale.
4. `## Open Questions` is empty or contains only the literal text `(none)`.

**If any check fails:**

- STOP. Do NOT proceed to Scope Check or anything below.
- Tell the user exactly which check failed and which section is missing or incomplete.
- Ask the user to re-run `plan-brainstorming` on the missing part.
- Do NOT auto-invoke `plan-brainstorming` - backward transitions in the pipeline are user-initiated only (see `../plan-brainstorming/references/plan-lifecycle.md`).

Only when all 4 checks pass, continue to the Scope Check section.

**Read the tier (after the 4 checks pass):**

The spec carries a `Tier:` blockquote above `# Goal` (see
`../plan-brainstorming/references/spec-contract.md`). Read it and carry the
tier into task rendering (see `references/task-tiers.md`):

- `Quick` / `Standard` / `Deep` — use as-is.
- Missing or unrecognized — default to **Standard** and announce:
  "Spec has no Tier line; defaulting to Standard." Do NOT fail; legacy
  specs predate this field.

The tier selects how much ceremony each task expands to. It never removes
the task core (`Files`, `steps`, verifiable done-state).

## Scope Check

If the spec covers multiple independent subsystems, it should have been broken into sub-project specs during brainstorming. If it wasn't, suggest breaking this into separate plans — one per subsystem. Each plan should produce working, testable software on its own.

## File Structure

Before defining tasks, map out which files will be created or modified and what each one is responsible for. This is where decomposition decisions get locked in.

- Design units with clear boundaries and well-defined interfaces. Each file should have one clear responsibility.
- You reason best about code you can hold in context at once, and your edits are more reliable when files are focused. Prefer smaller, focused files over large ones that do too much.
- Files that change together should live together. Split by responsibility, not by technical layer.
- In existing codebases, follow established patterns. If the codebase uses large files, don't unilaterally restructure - but if a file you're modifying has grown unwieldy, including a split in the plan is reasonable.

This structure informs the task decomposition. Each task should produce self-contained changes that make sense independently.

**Read before you modify.** Before writing any task that contains a
`Modify:` of an existing file, open that file and record one line in the
task's `Files` block: *current state / what changes / what must be
preserved*. This is what makes the exact line numbers in `Modify:
path:123-145` real instead of guessed, and it catches false assumptions
before they reach the implementer. For `Create:` targets this is not needed.

## Bite-Sized Task Granularity

**Each step is one action (2-5 minutes):**
- "Write the failing test" - step
- "Run it to make sure it fails" - step
- "Implement the minimal code to make the test pass" - step
- "Run the tests and make sure they pass" - step
- "Commit" - step

**Task size limit:** A single task must fit within **10 minutes of work OR 100 lines of new code** - whichever comes first.

If a task exceeds either limit, split it into sub-tasks (`Task N.1`, `Task N.2`, ...). Apply this rule recursively: each sub-task must also fit the limit.

Indicators a task is too big:
- More than ~5 implementation steps, excluding test/run/commit steps
- Touches more than 2-3 files with new logic
- The task title or steps contain multiple "and then" / "after that" chains

These indicators are prompts to re-check the hard 10-minute / 100-lines limit, not additional hard thresholds.

**Tier scales ceremony, not core.** How much of each task expands —
`Preconditions`/`Postconditions`/`Constraints`/`If stuck` — depends on the
spec tier read at Preflight. See `references/task-tiers.md`. The core
(`Files`, `steps`, a verifiable done-state) is mandatory in every tier.

## Plan Document Header

**Every plan MUST start with this header:**

```markdown
# [Feature Name] Implementation Plan

> **For agentic workers:** Execute this plan with the `plan-executor` skill (one unit at a time, ledger-backed, gated). If the plan has not been audited yet, run `plan-iterative-revision` on it first. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** [One sentence describing what this builds]

**Architecture:** [2-3 sentences about approach]

**Tech Stack:** [Key technologies/libraries]

---
```

## Task Structure

````markdown
### Task N: [Component Name]

**Constraints:** (optional - include only when there is a real fork in approach)
- Use: [specific tool/pattern chosen for this task]
- Don't use: [explicit anti-patterns the agent might drift into]
- Scope boundary: [what this task does NOT solve, even if it looks logical]

**Files:**
- Create: `exact/path/to/file.py`
- Modify: `exact/path/to/existing.py:123-145`
- Test: `tests/exact/path/to/test.py`

**Preconditions:** (state required before this task can start)
- [Concrete artifact that must exist, e.g. "file X contains function Y"]
- [Test from previous task passes]

**Postconditions:** (definition of done - objective checklist)
- [Concrete artifact produced]
- [Test passes with N cases]
- [What is NOT changed - guard against scope creep]

- [ ] **Step 1: Write the failing test**

```python
def test_specific_behavior():
    result = function(input)
    assert result == expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/path/test.py::test_name -v`
Expected: FAIL with "function not defined"

- [ ] **Step 3: Write minimal implementation**

```python
def function(input):
    return expected
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/path/test.py::test_name -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/path/test.py src/path/file.py
git commit -m "feat: add specific feature"
```

**If stuck:** (optional - 2-3 most likely failure modes, not exhaustive)
- [Specific symptom] -> [where to look / what to check]
- [Specific symptom] -> [where to look]
````

Use `Constraints` as the task's decision corridor. Include it only when (a) there are multiple reasonable approaches and the choice is already made, or (b) agents are likely to over-engineer this kind of task. Each constraint should remove a plausible wrong branch: name the tool or pattern to use, the tempting anti-pattern to avoid, and the scope boundary that must not be crossed. Do not pad every task with empty constraints - it adds noise.

Treat `Preconditions` and `Postconditions` as the task's explicit input/output contract. Preconditions must name concrete prerequisites before work starts: repo state (for example, dependencies installed), artifacts that already exist, prior test results, or previous task outputs. Postconditions must name the observable artifacts and checks produced by this task: files changed, functions/classes available, tests passing, and deliberate non-changes that guard scope when scope creep is likely. On Standard and Deep tiers every task MUST include both blocks; if a postcondition requires implementation work from another task, split or reorder the tasks. On Quick tier these two blocks collapse into a single `Done when: <observable result>` line (see `references/task-tiers.md`) — the verifiable done-state never disappears, it only shrinks. The task core is never optional on any tier. Dependencies on prior task outputs belong in `Preconditions` and are normal.

Use `If stuck` as targeted failure guidance, not generic debugging advice. Include it only for likely, specific failure modes: environment issues, dependency/order problems, naming collisions, or common agent mistakes. Write symptoms and first checks (`[symptom] -> [where to look / what to verify]`). Do not list generic advice like "read the error message." If you cannot identify 2-3 useful failure modes, omit the block.

## Phase Checkpoints

Optional. Standard and Deep tiers only — never on Quick.

After a logical group of tasks, you may insert one **phase checkpoint**: a
single written step that smoke-tests the group as a whole, with a concrete
command and an expected result. It catches integration breakage before the
end of the plan instead of after the last task.

A checkpoint is a *written plan step*, not something `plan-writing`
executes — runtime belongs to the execution skills. Like any step it obeys
`No Placeholders`: show the real command and the expected output. If you
cannot name a concrete check, omit the checkpoint.

Format:

```markdown
### Phase Checkpoint: [what this group proves]

- [ ] Run: `<concrete command>`
      Expected: `<observable result>`
```

## No Placeholders

Every step must contain the actual content an engineer needs. These are **plan failures** — never write them:
- "TBD", "TODO", "implement later", "fill in details"
- "Add appropriate error handling" / "add validation" / "handle edge cases"
- "Write tests for the above" (without actual test code)
- "Similar to Task N" (repeat the code — the engineer may be reading tasks out of order)
- Steps that describe what to do without showing how (code blocks required for code steps)
- References to types, functions, or methods not defined in any task

## Remember
- Exact file paths always
- Complete code in every step — if a step changes code, show the code
- Exact commands with expected output
- DRY, YAGNI, TDD, frequent commits

## Self-Review

After writing the complete plan, look at the spec with fresh eyes and check the plan against it. This is a checklist you run yourself — not a subagent dispatch.

**1. Spec coverage:** Skim each section/requirement in the spec. Can you point to a task that implements it? List any gaps.

**2. Placeholder scan:** Search your plan for red flags — any of the patterns from the "No Placeholders" section above. Fix them.

**3. Type consistency:** Do the types, method signatures, and property names you used in later tasks match what you defined in earlier tasks? A function called `clearLayers()` in Task 3 but `clearFullLayers()` in Task 7 is a bug.

**4. Task size:** Does every task fit the 10-minute / 100-lines-of-new-code limit? If not, split it into sub-tasks and re-check recursively.

**5. Done-state reachability:** For each task, can you verify its done-state by reading only that task's steps? On Standard/Deep this means the `Postconditions`; on Quick it means the `Done when:` line. If the done-state requires implementation work described in another task, the task boundaries are wrong - fix them. Dependencies on earlier task outputs are fine when they appear as preconditions (or, on Quick, are implied by task order).

**6. Core presence (all tiers):** Every task — Quick included — has `Files`, numbered `steps`, and a verifiable done-state. A task missing any of these is a plan failure regardless of tier (see `references/task-tiers.md`).

If you find issues, fix them inline. No need to re-review — just fix and move on. If you find a spec requirement with no task, add the task.

## Execution Handoff

After saving the plan, offer the next pipeline step:

**"Plan complete and saved to `<dir>/<plan-root>-impl.md`. Recommended next steps:**

**1. Audit (recommended)** — run `plan-iterative-revision` on the plan to cross-check it against the codebase before execution.

**2. Split** — if the plan has more than ~15 tasks, run `plan-splitter` to decompose it into stages.

**3. Execute directly** — for small, already-audited plans, run `plan-executor`.

**Which step?"**

Do not invoke any skill automatically. Wait for the user's explicit choice.
