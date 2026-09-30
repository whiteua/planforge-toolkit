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
| **Part** | Self-contained slice of a large plan (`<base>-a.md`, `<base>-b.md`, …). Produced by `plan-splitter`. |
| **Task** | Plan unit that fits ~10 minutes or ~100 lines of new code. |
| **Step** | Single action inside a task (2–5 minutes). |
| **Ledger** | Progress tracking file (`state.json`) maintained by `plan-executor`, stored outside the repository. |
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
    └──────┬──────┘        │  Plan → <base>-roadmap.md│
           │ no            └──────────┬──────────────┘
           │                         │ <base>-a.md, -b.md…
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
/plan-brainstorming <findings.json>   # JSON list of code-review findings
```

With a findings JSON (`file`, `line`, `summary`, `failure_scenario` per item), the skill validates the list, checks each finding against the code, and writes a fix spec. The spec traces every finding id to a fix or to Out of Scope.

**Process:**
1. Explores project context (files, docs, commits) and restates your request in one sentence
2. Proposes a depth tier: `Quick` / `Standard` / `Deep`
3. Offers the Visual Companion when the questions ahead are visual
4. Asks clarifying questions one at a time
5. Proposes approaches with trade-offs (2–3 on Standard/Deep, one on Quick)
6. Presents the design section by section, asks for approval
7. Runs the ambiguity sweep — closes all open questions (re-presents a design section if an answer changes it)
8. Writes the spec file, checks the contract with `brainstorm_tool.py spec-check`, runs the self-review including a fidelity check against your original request
9. Hands off to `plan-writing` after you approve the spec (the spec is not committed)

The dialogue and the spec body follow the language of your input; section headings stay in English.

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

**Prerequisites:** The spec must pass `plan-brainstorming`'s `brainstorm_tool.py spec-check` before the skill proceeds: all 8 required headings in order, no empty section, `## Open Questions` empty (or `(none)`).

**Output:** `<X>-impl.md` next to `<X>-spec.md`. The header carries `**Spec:**`, `**Tier:**` and `**Baseline:**` (the test command and result before planning); tasks use `### Task N: <title>` headings, the format `plan-executor` and `plan-resolver` parse. `scripts/plan_tool.py plan-check --root <project>` verifies that contract and that the files and paths the plan relies on exist (`Create:` targets must be new).

Each task in the plan specifies:
- Files to touch
- Exact steps (2–5 min each)
- How to test / verify done-state

Plans contain no `git commit` steps; committing the result is up to you. An optional `### Task N: Checkpoint — …` task smoke-tests a group of tasks (Standard/Deep).

---

### plan-splitter

**Purpose:** Decompose a large implementation plan into self-contained parts, each executable in a single agent pass.

**Invoke:**
```
/plan-splitter <plan-path> [verify=ask|all|none|a,c] [verify_depth=quick|standard|deep] [verify_mode=full-cycle|audit-only]
```

With `verify`, the skill runs `plan-iterative-revision` once over the roadmap (every selected part in turn, one review trail each) and accepts the result only through the machine gate `verify-status`. Requires `plan-iterative-revision` installed next to it.

**Gate decision:** The skill evaluates 5 factors and may decide the plan does NOT need splitting. This is a valid outcome — you'll get a `gate-pass` notice and can proceed directly to `plan-executor`.

**Output** (alongside the original plan, which is never modified):

| File | Purpose |
|---|---|
| `<base>-roadmap.md` | Part map with dependencies and parallel groups |
| `<base>-a.md`, `<base>-b.md`, … | Self-contained part files (letters continue with `aa`, `ab`, …) |

---

### plan-executor

**Purpose:** Execute a ready plan or staged roadmap one unit at a time with ledger-backed progress tracking, gates, and rollback snapshots.

**Invoke:**
```
/plan-executor <plan-or-roadmap-path>
```

**Input types:**

| Input | Detection | Behavior |
|---|---|---|
| Staged roadmap (`-roadmap.md`) | Has part table + dependencies | Executes parts in dependency order |
| Whole plan (with `### Task N:` headings) | Task headings outside code blocks | Executes tasks strictly in order; a failed task is retried before anything else |

**Phases:**
1. **BOOTSTRAP** — `ledger-init <exec_dir> <plan> --workdir <repo>`: parse units, create or resume the ledger in `exec_dir` (outside the repository or git-ignored; stops on a dirty repo or a changed plan/part), baseline snapshot
2. **LOOP** — `unit-begin` (unit text + files) → execute → gate → `unit-finish` (snapshot + done, or retry/stop)
3. **FINALIZE** — propose `plan-resolver` (audit, or `auto` to audit and fix)

**Invariants:**
- Never edits source plan or part files.
- Progress lives only in `state.json`.
- Nothing is committed to your branch: snapshots live in hidden refs `refs/plan-executor/<run>/<unit>`; the final commit is yours.
- Destructive operations (restore) require explicit engineer confirmation.
- A gate cannot pass silently when checks are absent.
- A task marked `**External:** <environment>` runs only after you confirm it.

The ledger lives in `<repo parent>/.exec/<repo>-<plan>/` by default; the agent tells you the path at the start. At the end it shows what the run changed (`run-diff`, separate from work that was uncommitted before) and writes defects it noticed but did not fix to `<plan>-followups.json`, which `plan-brainstorming` accepts as input.

**Prerequisites:** Python ≥ 3.8 in PATH.

---

### plan-iterative-revision

**Purpose:** Audit an implementation plan against the codebase and fix errors in automated cycles until the plan is clean.

**Invoke:**
```
/plan-iterative-revision <plan-path> [preset=quick|standard|deep] [stop_policy=pragmatic|strict] [interaction=auto|interactive|autonomous] [audit-only]
/plan-iterative-revision <base>-roadmap.md [parts=a,c] …     # batch: every part of a split plan, one review trail each
```

**Presets:**

| Preset | Lenses | Code Rigor | Max Iterations |
|---|---|---|---|
| `quick` | 1 | grep-level | 3 |
| `standard` | 2 | read-level | 5 |
| `deep` | 4 (incl. red-team L4) | explore | 7 |

**Modes:**
- `full-cycle` (default) — audit → fix → repeat
- `audit-only` — audit → write review file → stop

**Stop conditions:**
- No issues on the first audit → `clean`, no files; no issues on a later audit → `converged` + completion file
- Max iterations reached → asks: +3 / +5 / stop (autonomous runs stop with `limit`)
- Same issue set as the previous audit, or nothing resolved for 2 audits → stagnation
- A previously resolved issue comes back, or one issue survives 3 audits → escalation
- Only nits remain (`pragmatic` policy) → stop

Stop decisions use only the reviews of the current run.

**Output:** `<plan-basename>-review-N.md` per iteration; `<plan-basename>-completion.md` on convergence.

**Prerequisites:** Python ≥ 3.8 in PATH. The plan's directory must be writable.

---

### plan-resolver

**Purpose:** Audit how well a plan was implemented in code. Produces a structured report. Optional `fix`/`next`/`auto` modes repair the code from the report and re-audit; the plan is never modified.

**Invoke:**
```
/plan-resolver <plan-path> [previous-report-1] [previous-report-2] ...   # audit
/plan-resolver [plan-path] fix     # fix the latest open report's issues, then re-audit once
/plan-resolver [plan-path] next    # same as fix; use after auto stops
/plan-resolver <plan-path> auto [limit]   # audit → fix → audit until final, max 2 fix cycles by default
```

In audit mode, always provide the full list of previous reports for delta analysis. `fix`/`next`/`auto` discover the reports next to the plan. The fix phase records each outcome (`applied` / `needs-user` / `skipped`) in the report's "Fix Log" section; only the following audit can mark an issue `✅ fixed`. Code changes are left uncommitted.

**Report types:**

| Type | When |
|---|---|
| `<base>-report-N.md` | Issues found — open report |
| `<base>-report-N-final.md` | All tasks ✅ — closing report |

**Task statuses:**

| Status | Meaning |
|---|---|
| ✅ | Implemented as specified; needs an evidence anchor `path#Lx-Ly` that the validator checks against the code |
| ⚠️ | Partial, defective, or ambiguous |
| ⭕️ | Missing |
| ‼️ | Deviates from the plan |
| `not-applicable` | Explanatory item, nothing to implement |

**Invariants:** The resolver never edits the plan. An audit pass never edits code or previous reports and creates exactly one report, validated with `validate-report --root` (structure, statuses, anchors pointing at real lines) and `task-census` (every plan task covered). The fix phase edits code only; previous reports change only through the Fix Log (`mark-fix`).

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

No installation of the CLI itself is required — `npx` runs it on demand.

#### Flags reference

| Flag | Short | Description |
|---|---|---|
| `--global` | `-g` | Install to home directory (`~/`) — available in **all** projects on the machine |
| `--agent <name...>` | `-a` | Target one or more specific agents; CLI auto-detects if omitted |
| `--skill <name...>` | `-s` | Install only specific skills by name; use `'*'` for all |
| `--list` | `-l` | List available skills without installing anything |
| `--copy` | | Copy files instead of creating symlinks |
| `--yes` | `-y` | Skip all confirmation prompts (CI/CD friendly) |
| `--all` | | Shorthand for `--skill '*' --agent '*' -y` |

#### Installation scope

By default skills are installed **project-locally** — into a hidden agent directory at the root of your current working directory (e.g. `.claude/skills/`). These files can be committed and shared with your team.

Add `-g` / `--global` to install into your home directory instead, making the skills available in **every project** on the machine.

| Scope | Flag | Where files land |
|---|---|---|
| Project (default) | _(none)_ | `.claude/skills/…`, `.agents/skills/…`, etc. |
| Global | `-g` | `~/.claude/skills/…`, `~/.copilot/skills/…`, etc. |

#### Supported agents (`--agent`)

The CLI auto-detects which agents are installed on your machine. Use `--agent` to explicitly target one or more.

| Agent | Slug | Project path | Global path |
|---|---|---|---|
| Claude Code | `claude-code` | `.claude/skills/` | `~/.claude/skills/` |
| GitHub Copilot | `github-copilot` | `.agents/skills/` | `~/.copilot/skills/` |
| Codex | `codex` | `.agents/skills/` | `~/.codex/skills/` |
| Cursor | `cursor` | `.agents/skills/` | `~/.cursor/skills/` |
| Windsurf | `windsurf` | `.windsurf/skills/` | `~/.codeium/windsurf/skills/` |
| Gemini CLI | `gemini-cli` | `.agents/skills/` | `~/.gemini/skills/` |
| OpenCode | `opencode` | `.agents/skills/` | `~/.config/opencode/skills/` |
| Cline / Warp / Zed | `cline` / `warp` / `zed` | `.agents/skills/` | `~/.agents/skills/` |
| Amp / Replit | `amp` / `replit` | `.agents/skills/` | `~/.config/agents/skills/` |

> 70+ supported agents — full list: [skills.sh/docs/cli#supported-agents](https://www.skills.sh/docs/cli#supported-agents)

#### Recipes

```bash
# Install all 7 skills — CLI auto-detects your agent
npx skills add whiteua/planforge-toolkit

# Install all skills globally (available in every project on this machine)
npx skills add whiteua/planforge-toolkit -g

# Install all skills globally for Claude Code only
npx skills add whiteua/planforge-toolkit -g -a claude-code

# Install all skills project-locally for GitHub Copilot
npx skills add whiteua/planforge-toolkit -a github-copilot

# Install a single skill globally for Claude Code
npx skills add whiteua/planforge-toolkit -s plan-executor -g -a claude-code

# Install the core pipeline only — non-interactive (CI/CD)
npx skills add whiteua/planforge-toolkit \
  -s plan-brainstorming -s plan-writing -s plan-executor -s plan-resolver \
  -g -a claude-code -y

# Install to multiple agents at once
npx skills add whiteua/planforge-toolkit -g -a claude-code -a github-copilot -a cursor

# Install to all detected agents without any prompts
npx skills add whiteua/planforge-toolkit --all

# Preview what would be installed (dry run)
npx skills add whiteua/planforge-toolkit --list
```

### Via git clone

Use this option when you want a single source of truth on disk and prefer to
manage updates via `git pull`.

```bash
git clone https://github.com/whiteua/planforge-toolkit.git
cd planforge-toolkit
```

**Claude Code** — symlink into `~/.claude/skills/`:

```bash
# macOS / Linux
DEST="$HOME/.claude/skills"
for skill in plan-brainstorming plan-writing plan-splitter plan-executor plan-resolver plan-iterative-revision writing-skills; do
  ln -s "$PWD/skills/$skill" "$DEST/$skill"
done

# Windows PowerShell (run as Administrator)
$src = "$PWD\skills"
$dest = "$env:USERPROFILE\.claude\skills"
foreach ($skill in @("plan-brainstorming","plan-writing","plan-splitter","plan-executor","plan-resolver","plan-iterative-revision","writing-skills")) {
  New-Item -ItemType SymbolicLink -Path "$dest\$skill" -Target "$src\$skill"
}
```

**GitHub Copilot** — symlink into `~/.copilot/skills/`:

```bash
# macOS / Linux
DEST="$HOME/.copilot/skills"
mkdir -p "$DEST"
for skill in plan-brainstorming plan-writing plan-splitter plan-executor plan-resolver plan-iterative-revision writing-skills; do
  ln -s "$PWD/skills/$skill" "$DEST/$skill"
done

# Windows PowerShell (run as Administrator)
$src = "$PWD\skills"
$dest = "$env:USERPROFILE\.copilot\skills"
New-Item -ItemType Directory -Force -Path $dest
foreach ($skill in @("plan-brainstorming","plan-writing","plan-splitter","plan-executor","plan-resolver","plan-iterative-revision","writing-skills")) {
  New-Item -ItemType SymbolicLink -Path "$dest\$skill" -Target "$src\$skill"
}
```

**Codex / Cursor / Cline / Warp** — symlink into agent-specific directory:

```bash
# macOS / Linux — adjust DEST for your agent
DEST="$HOME/.codex/skills"   # or ~/.cursor/skills, ~/.agents/skills, etc.
mkdir -p "$DEST"
for skill in plan-brainstorming plan-writing plan-splitter plan-executor plan-resolver plan-iterative-revision writing-skills; do
  ln -s "$PWD/skills/$skill" "$DEST/$skill"
done
```

> **Note:** `plan-writing` reads contract files from `plan-brainstorming`. Both must be installed in the **same parent directory**.

---

## Typical Workflows

### New feature from scratch

```
/plan-brainstorming I want to add WebSocket notifications to the API
  → asks where to save the spec (inline idea, no goal file); e.g. docs/plans/plan01-spec.md

/plan-writing docs/plans/plan01-spec.md
  → saves: docs/plans/plan01-impl.md

/plan-iterative-revision docs/plans/plan01-impl.md      # optional audit of the plan against the code

/plan-executor docs/plans/plan01-impl.md

/plan-resolver docs/plans/plan01-impl.md
```

### Large refactor

```
/plan-brainstorming  ...
/plan-writing        ...  → plan01-impl.md
/plan-splitter docs/plans/plan01-impl.md verify=all
  → saves: plan01-impl-roadmap.md, plan01-impl-a.md … plan01-impl-e.md
  → verifies every part with plan-iterative-revision (plan01-impl-a-review-1.md, …)

/plan-executor docs/plans/plan01-impl-roadmap.md
/plan-resolver docs/plans/plan01-impl.md
```

### Auditing an existing plan before execution

```
/plan-iterative-revision docs/plans/plan01-impl.md preset=deep
  → saves: plan01-impl-review-1.md (with issues)
  → fixes the plan
  → saves: plan01-impl-review-2.md
  → no issues left → converged → saves: plan01-impl-completion.md
```

### Verifying every part of a split plan

```
/plan-iterative-revision docs/plans/plan01-impl-roadmap.md
  → plan01-impl-a-review-1.md, plan01-impl-a-completion.md, plan01-impl-b-review-1.md, …
  → one summary: worst part result wins
```

### External systems

No skill reaches a database, API or remote service without your explicit permission for a named environment. The permission is not widened to other environments, and an existing project script aimed at production is not permission. A plan lists the permitted environments in its header with your words quoted, marks the tasks that use them with `**External:**`, and the executor asks before each of them. The audits flag a step that ran somewhere it was not permitted, and mark tasks they could not re-verify as closed on the executor's report.

### Version control

No skill commits on your branch: specs, plans, reviews, roadmaps and parts are written to disk uncommitted, `plan-resolver`'s fixes stay in the working tree, and `plan-executor` keeps rollback snapshots in hidden refs (`refs/plan-executor/…`). Commit when a block of work is verified.

---

## File Naming Conventions

| Pattern | Produced by | Description |
|---|---|---|
| `<base>-spec.md` | `plan-brainstorming` | Design spec |
| `<base>-impl.md` | `plan-writing` | Implementation plan |
| `<base>-roadmap.md` | `plan-splitter` | Part roadmap |
| `<base>-a.md`, `<base>-b.md`, … | `plan-splitter` | Individual part |
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
| `plan-executor` stops at a gate with no checks | No tests exist for the unit | Add at least a smoke test; the gate never passes silently |
| `plan-iterative-revision` cannot create review file | Plan directory not writable, or no shell/Python for the helper script | Check directory permissions; enable shell commands and Python in your agent |
| `plan-iterative-revision` stops with stagnation/escalated | The same issues survive plan edits, or a fixed issue came back | Resolve the listed issues by hand, then re-run |
| `plan-resolver`: `anchor file not found` / `beyond end of file` | The report cites code that is not there | The audit must cite real lines; fix the report |
| `plan-resolver` `auto` stops with ask-user / stop-stalled | Issues need a decision, or a cycle closed nothing | Answer the questions or fix by hand, then `/plan-resolver next` |
| `plan-writing` cannot find contract files | `plan-brainstorming` not installed in same directory | Install both skills side-by-side |
