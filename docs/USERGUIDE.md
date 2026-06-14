# PlanForge Toolkit — User Guide

> A structured AI planning pipeline from raw idea to verified implementation.

---

## Table of Contents

1. [What is PlanForge Toolkit?](#what-is-planforge-toolkit)
2. [Core Concepts](#core-concepts)
3. [Pipeline Overview](#pipeline-overview)
4. [Skills Reference](#skills-reference)
   - [plan-brainstorming](#plan-brainstorming)
   - [plan-writing](#plan-writing)
   - [plan-splitter](#plan-splitter)
   - [plan-executor](#plan-executor)
   - [plan-iterative-revision](#plan-iterative-revision)
   - [plan-resolver](#plan-resolver)
   - [writing-skills](#writing-skills)
5. [Installation](#installation)
6. [Typical Workflows](#typical-workflows)
7. [File Naming Conventions](#file-naming-conventions)
8. [Troubleshooting](#troubleshooting)

---

## What is PlanForge Toolkit?

PlanForge Toolkit is a collection of **AI agent skills** that impose structure on the software development lifecycle. Rather than asking an AI assistant to "just implement this", the toolkit guides both the human and the AI through an explicit pipeline:

```
Idea → Design Spec → Implementation Plan → Staged Execution → Verified Result
```

Each skill is an independent module with a well-defined input, output, and invariants. Skills can be used individually or chained together for larger projects.

---

## Core Concepts

| Term | Meaning |
|---|---|
| **Spec** | Design document — *what* to build and *why*. Produced by `plan-brainstorming`. |
| **Plan** | Implementation document — *how* to build it, step by step. Produced by `plan-writing`. |
| **Stage** | Self-contained slice of a large plan. Produced by `plan-splitter`. |
| **Task** | Plan unit that fits ~10 minutes or ~100 lines of new code. |
| **Step** | Single action inside a task (2–5 minutes). |
| **Ledger** | Progress tracking file (`state.json`) maintained by `plan-executor`. |
| **Review** | Audit file produced by `plan-iterative-revision` listing errors in the plan. |
| **Report** | Audit file produced by `plan-resolver` listing implementation vs. plan findings. |

---

## Pipeline Overview

```
┌──────────────────────┐
│  plan-brainstorming  │  Idea → Design Spec
└──────────┬───────────┘
           │ *-spec.md
┌──────────▼───────────┐
│     plan-writing     │  Spec → Implementation Plan
└──────────┬───────────┘
           │ *-impl.md
           │
    ┌──────▼──────┐        ┌─────────────────────────┐
    │ large plan? │──yes──►│      plan-splitter       │
    └──────┬──────┘        │  Plan → stg00-roadmap.md │
           │ no            └──────────┬──────────────┘
           │                         │ stgNN.md
           └─────────────┬───────────┘
                         │
┌────────────────────────▼────────────────────────────┐
│                   plan-executor                     │
│  Execute one unit at a time, ledger-backed          │
└────────────────────────┬────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────┐
│                   plan-resolver                     │
│  Audit implementation against plan → report         │
└─────────────────────────────────────────────────────┘

plan-iterative-revision  — use at any stage to clean up a plan before execution
```

---

## Skills Reference

### plan-brainstorming

**Purpose:** Turn a vague idea into a validated design spec through structured dialogue.

**Invoke:**
```
/plan-brainstorming <goal-file-or-inline-description>
```

**Process:**
1. Explores project context (files, docs, commits)
2. Offers Visual Companion if visual questions are expected
3. Proposes a depth tier: `Quick` / `Standard` / `Deep`
4. Asks clarifying questions one at a time
5. Proposes 2–3 approaches with trade-offs
6. Presents design section by section, asks for approval
7. Runs ambiguity sweep — closes all open questions
8. Writes the spec file and runs self-review
9. Hands off to `plan-writing`

**Output:** `*-spec.md` in the same directory as the goal file.

**Depth tiers:**

| Tier | When | Spec size |
|---|---|---|
| Quick | Single-file change, bugfix, config tweak | A few sentences per section |
| Standard | Feature touching 2–5 components | Short paragraph per section |
| Deep | New subsystem, external integrations, complex failure modes | Full paragraphs, tables |

> **Dependency:** `plan-writing` reads contract files from this skill. Both must be installed in the same parent directory.

---

### plan-writing

**Purpose:** Convert a validated design spec into a detailed, step-by-step implementation plan.

**Invoke:**
```
/plan-writing <spec-path>
```

**Prerequisites:** The spec must pass a 4-point contract check before the skill proceeds:
1. Spec file exists.
2. All 8 required headings are present.
3. No required section is empty.
4. `## Open Questions` is empty (or `(none)`).

**Output:** `*-impl.md` in the same directory as the spec.

Each task in the plan specifies:
- Files to touch
- Exact steps (2–5 min each)
- How to test / verify done-state

---

### plan-splitter

**Purpose:** Decompose a large implementation plan into self-contained stages, each executable in a single agent pass.

**Invoke:**
```
/plan-splitter <plan-path> [verify=ask|all|none] [verify_depth=quick|standard|deep]
```

**Gate decision:** The skill evaluates 5 factors and may decide the plan does NOT need splitting. This is a valid outcome — you'll get a `gate-pass` notice and can proceed directly to `plan-executor`.

**Output** (alongside the original plan, which is never modified):

| File | Purpose |
|---|---|
| `<base>-stg00-roadmap.md` | Stage map with dependencies and parallel groups |
| `<base>-stg01.md` … `<base>-stgNN.md` | Self-contained stage files |

---

### plan-executor

**Purpose:** Execute a ready plan or staged roadmap one unit at a time with ledger-backed progress tracking, gates, and checkpoints.

**Invoke:**
```
/plan-executor <plan-or-roadmap-path>
```

**Input types:**

| Input | Detection | Behavior |
|---|---|---|
| Staged roadmap (`-stg00-roadmap.md`) | Has stage table + dependencies | Executes stages in dependency order |
| Whole plan (with `### Task N:` headings) | Has explicit task headings | Executes tasks sequentially |

**Phases:**
1. **BOOTSTRAP** — detect input, parse units, initialize ledger, detect checkpoints
2. **EXECUTE LOOP** — claim unit → execute → gate → checkpoint → mark done
3. **FINALIZE** — propose `plan-resolver` options

**Invariants:**
- Never edits source plan or stage files.
- Progress lives only in `state.json`.
- Destructive operations require explicit engineer confirmation.
- A gate cannot pass silently when checks are absent.

**Prerequisites:** Python ≥ 3.8 in PATH.

---

### plan-iterative-revision

**Purpose:** Audit an implementation plan against the codebase and fix errors in automated cycles until the plan is clean.

**Invoke:**
```
/plan-iterative-revision <plan-path> [preset=quick|standard|deep] [stop_policy=pragmatic|strict]
```

**Presets:**

| Preset | Lenses | Code Rigor | Max Iterations |
|---|---|---|---|
| `quick` | 1 | grep-level | 3 |
| `standard` | 2 | read-level | 5 |
| `deep` | 3 + red-team L4 | explore | 7 |

**Modes:**
- `full-cycle` (default) — audit → fix → repeat
- `audit-only` — audit → write review file → stop

**Stop conditions:**
- No issues found → "Plan is clean"
- Max iterations reached → asks: continue / stop
- Stagnation (same issues repeat) → auto-stop
- Only nits remain (`pragmatic` policy) → stop

**Output:** `<plan-basename>-review-N.md` per iteration; `<plan-basename>-completion.md` on convergence.

**Prerequisites:** Python ≥ 3.8 in PATH. File write tools must be available.

---

### plan-resolver

**Purpose:** Audit how well a plan was implemented in code. Produces a structured report — never modifies code or the plan.

**Invoke:**
```
/plan-resolver <plan-path> [previous-report-1] [previous-report-2] ...
```

Always provide the full list of previous reports for delta analysis.

**Report types:**

| Type | When |
|---|---|
| `<base>-report-N.md` | Issues found — open report |
| `<base>-report-N-final.md` | All tasks ✅ — closing report |

**Task statuses:**

| Status | Meaning |
|---|---|
| ✅ | Correctly implemented |
| ⚠️ | Partially implemented or minor issues |
| ❌ | Not implemented or critically wrong |
| N/A | Not applicable |

**Invariants:** The resolver never edits code, the plan, or previous reports. It never creates multiple reports per invocation.

**Prerequisites:** Python ≥ 3.8 in PATH.

---

### writing-skills

**Purpose:** Create, test, and deploy new AI agent skills using a TDD methodology.

**Invoke:**
```
/writing-skills
```

**Philosophy:** Writing a skill IS Test-Driven Development applied to process documentation.

| TDD Concept | Skill Creation |
|---|---|
| Test case | Pressure scenario with a subagent |
| Production code | Skill document (`SKILL.md`) |
| RED | Agent violates rule without the skill (baseline) |
| GREEN | Agent complies with the skill present |
| Refactor | Close loopholes while maintaining compliance |

**Skill structure:**

```
my-skill/
  SKILL.md          ← main skill document (YAML frontmatter + instructions)
  USAGE.md          ← quick reference (optional but recommended)
  references/       ← supporting reference files
  scripts/          ← helper scripts (Python, JS, etc.)
  tests/            ← TDD test scenarios
  assets/           ← templates, schemas, examples
```

**Frontmatter format:**
```yaml
---
name: my-skill
description: "Single sentence describing when to invoke this skill."
---
```

---

## Installation

### Via `npx skills`

```bash
# Install individual skills
npx skills add whiteua/planforge-toolkit/plan-brainstorming
npx skills add whiteua/planforge-toolkit/plan-writing
npx skills add whiteua/planforge-toolkit/plan-splitter
npx skills add whiteua/planforge-toolkit/plan-executor
npx skills add whiteua/planforge-toolkit/plan-resolver
npx skills add whiteua/planforge-toolkit/plan-iterative-revision
npx skills add whiteua/planforge-toolkit/writing-skills
```

### Via git clone

```bash
git clone https://github.com/whiteua/planforge-toolkit.git
```

**Claude Code** — symlink or copy into `~/.claude/skills/`:

```bash
# macOS / Linux
DEST="$HOME/.claude/skills"
for skill in plan-brainstorming plan-writing plan-splitter plan-executor plan-resolver plan-iterative-revision writing-skills; do
  ln -s "$PWD/$skill" "$DEST/$skill"
done

# Windows PowerShell (run as Administrator)
$src = "$PWD"
$dest = "$env:USERPROFILE\.claude\skills"
foreach ($skill in @("plan-brainstorming","plan-writing","plan-splitter","plan-executor","plan-resolver","plan-iterative-revision","writing-skills")) {
  New-Item -ItemType SymbolicLink -Path "$dest\$skill" -Target "$src\$skill"
}
```

**VS Code GitHub Copilot** — symlink or copy into `~/.copilot/skills/`:

```bash
# macOS / Linux
DEST="$HOME/.copilot/skills"
mkdir -p "$DEST"
for skill in plan-brainstorming plan-writing plan-splitter plan-executor plan-resolver plan-iterative-revision writing-skills; do
  ln -s "$PWD/$skill" "$DEST/$skill"
done

# Windows PowerShell (run as Administrator)
$src = "$PWD"
$dest = "$env:USERPROFILE\.copilot\skills"
New-Item -ItemType Directory -Force -Path $dest
foreach ($skill in @("plan-brainstorming","plan-writing","plan-splitter","plan-executor","plan-resolver","plan-iterative-revision","writing-skills")) {
  New-Item -ItemType SymbolicLink -Path "$dest\$skill" -Target "$src\$skill"
}
```

> **Note:** `plan-writing` reads contract files from `plan-brainstorming`. Both must be installed in the **same parent directory**.

---

## Typical Workflows

### New feature from scratch

```
/plan-brainstorming I want to add WebSocket notifications to the API
  → saves: docs/plans/plan01-notifications-spec.md

/plan-writing docs/plans/plan01-notifications-spec.md
  → saves: docs/plans/plan01-notifications-impl.md

/plan-executor docs/plans/plan01-notifications-impl.md

/plan-resolver docs/plans/plan01-notifications-impl.md
```

### Large refactor

```
/plan-brainstorming  ...
/plan-writing        ...  → plan01-impl.md
/plan-splitter docs/plans/plan01-impl.md
  → saves: plan01-stg00-roadmap.md, plan01-stg01.md … plan01-stg05.md

/plan-executor docs/plans/plan01-stg00-roadmap.md
/plan-resolver docs/plans/plan01-impl.md
```

### Auditing an existing plan before execution

```
/plan-iterative-revision docs/plans/plan01-impl.md preset=deep
  → saves: plan01-review-1.md (with issues)
  → fixes the plan
  → saves: plan01-review-2.md
  → "Plan is clean" → saves: plan01-completion.md
```

---

## File Naming Conventions

| Pattern | Produced by | Description |
|---|---|---|
| `<base>-spec.md` | `plan-brainstorming` | Design spec |
| `<base>-impl.md` | `plan-writing` | Implementation plan |
| `<base>-stg00-roadmap.md` | `plan-splitter` | Stage roadmap |
| `<base>-stgNN.md` | `plan-splitter` | Individual stage |
| `<base>-review-N.md` | `plan-iterative-revision` | Audit review (per iteration) |
| `<base>-completion.md` | `plan-iterative-revision` | Convergence notice |
| `<base>-report-N.md` | `plan-resolver` | Implementation audit report |
| `<base>-report-N-final.md` | `plan-resolver` | Final closing report |

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `plan-writing` fails spec contract check | Spec is incomplete | Re-run `plan-brainstorming` to close open sections |
| `plan-splitter` says "don't split" | Plan is small enough | Proceed directly to `plan-executor` |
| `plan-executor` gate fails silently | No tests exist | Write at least a smoke test; executor will escalate |
| `plan-iterative-revision` cannot create review file | Write tools disabled | Enable file write mode in your agent |
| `plan-resolver` reports stagnation | Same issues repeat | Review the stagnated issues manually; update the plan |
| `plan-writing` cannot find contract files | `plan-brainstorming` not installed in same directory | Install both skills side-by-side |
