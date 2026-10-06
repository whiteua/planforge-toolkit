<div align="center">

# 🔨 PlanForge Toolkit

**A structured AI planning pipeline — from raw idea to verified implementation.**

[![Stars](https://img.shields.io/github/stars/whiteua/planforge-toolkit?style=for-the-badge&color=yellow)](https://github.com/whiteua/planforge-toolkit/stargazers)
[![License](https://img.shields.io/github/license/whiteua/planforge-toolkit?style=for-the-badge&color=blue)](LICENSE)
[![Issues](https://img.shields.io/github/issues/whiteua/planforge-toolkit?style=for-the-badge&color=red)](https://github.com/whiteua/planforge-toolkit/issues)
[![skills.sh](https://skills.sh/b/whiteua/planforge-toolkit)](https://skills.sh/whiteua/planforge-toolkit)

[Overview](#overview) · [Skills](#skills) · [Pipeline](#pipeline) · [Installation](#installation) · [Updating](#updating) · [Usage](#usage) · [Contributing](#contributing)

</div>

---

## Overview

PlanForge Toolkit is a collection of **AI agent skills** that guide an AI coding assistant through the entire software development lifecycle — from initial brainstorming to verified implementation.

Each skill is an independent, installable module. Together they form a coherent pipeline that transforms a vague idea into production-ready code through structured, repeatable steps.

**Works with:**
- [Claude Code](https://claude.ai/code) — `~/.claude/skills/`
- [VS Code GitHub Copilot](https://github.com/features/copilot) — `~/.copilot/skills/`
- [GitHub Copilot CLI](https://github.com/features/copilot) — `.github/skills/` (project-level)
- [Codex / inference.sh agents](https://inference.sh) — `~/.agents/skills/`
- Any agent runtime that follows the [agentskills.io](https://agentskills.io) SKILL.md convention

**Skill discovery** is automatic — agents scan the skills directory for `SKILL.md` files and match the `description` field semantically to the user's request.

---

## Skills

| Skill | Description | Depends on | Techniques |
|---|---|---|---|
| [`plan-brainstorming`](skills/plan-brainstorming/) | Turn ideas or several input files into validated design specs and a goal roadmap through collaborative dialogue; stops there | — | Depth-tiered elaboration, spec contract validation, chain settings and per-environment read/write consent recorded in the spec, shared `BACKLOG.md`, multi-input intake, spec-set consistency check, goal roadmap (`<goal>-roadmap.md`, DAG + Mermaid), dialogue in the user's language |
| [`plan-writing`](skills/plan-writing/) | Convert a spec into a detailed, step-by-step implementation plan | `plan-brainstorming` | Spec preflight, plan format contract (`plan-check`), codebase grounding with `path:line` citations and a recorded test baseline, access type on external tasks, justified size exceptions (`**Size:**`) |
| [`plan-splitter`](skills/plan-splitter/) | Decompose a large plan into self-contained parts (`<base>-a.md`, `-b.md`, …) with a dependency roadmap | `plan-iterative-revision` (optional, deep verification); `plan-brainstorming` (required: task parser for `gate`, `split-write`, `validate-all`; chain settings) | Numeric gate (`gate`: tasks, bytes, modules, dependency shape) or the `split` setting, parts written by script (`split-write`: task texts byte for byte, checked by hash), topological ordering + parallel groups, 3-level VERIFY, self-sufficiency invariant, SHA-256 origin hash, one batch verification run with a machine gate, `External` and `Size` lines carried verbatim |
| [`plan-executor`](skills/plan-executor/) | Execute a plan one unit at a time with ledger-backed progress tracking | `plan-brainstorming` (chain settings, `BACKLOG.md`) | Persistent progress ledger with resume, plan-drift and settings-drift detection, strictly ordered units with retry-first policy (a split plan runs task by task with one checkpoint per part), risk-scaled gates, read/write consent per external system, foreign-change detection against an expected tree with per-file restore, rollback snapshots in hidden git refs (no branch commits), run diff, findings to `BACKLOG.md` |
| [`plan-iterative-revision`](skills/plan-iterative-revision/) | Iteratively audit and patch a plan (or every part of a split plan) until it is error-free | `plan-brainstorming` (chain settings, task hashes for incremental re-audits) | Set-algebraic flow analysis (new/resolved/persisted/reintroduced), SHA-1 issue fingerprinting, two-phase separation (audit ≠ implement), single gate authority (regression/churn/unchanged/stuck/limit), 10-class error taxonomy, immutable append-only review trail, batch mode over split parts, preset and stop policy from the chain settings, incremental re-audit by task hash |
| [`plan-resolver`](skills/plan-resolver/) | Audit implementation against the plan and produce a structured report; optionally fix the code and re-audit (`fix` / `auto`) | `plan-brainstorming` (chain settings, `BACKLOG.md`) | task-census completeness gate, evidence anchors (`path#Lx-Ly`) verified against the workspace, confidence calibration, probe-gate (whitelist), self-consistency check, SHA-256 fingerprint, read-only audit invariant (report and `BACKLOG.md` only), separated fix → re-audit loop with protected plan, snapshot diff and bounded cycles |
| [`plan-chain-runner`](skills/plan-chain-runner/) | Run the approved specs of one goal through writing → revision → [split] → execution → audit → commit after one start dialogue; questions are collected in the chain journal | all six pipeline skills (`plan-brainstorming` for the journal and settings) | Dependency-graph scheduler (`run-next`) fed by the goal roadmap (`<goal>-roadmap.md`: order, groups, notes in the planning briefs), host profiles (`claude-code`, `github-copilot`, `fallback`) with a model per role, artifact trust through `journal-reconcile`, session mark with heartbeat outside the working tree, ETA from the journal's history, `continue` / `discuss` / `status`, `help` |
| [`writing-skills`](skills/writing-skills/) | Create, test, and deploy new agent skills using TDD methodology | — | Red-green-refactor for skills, subagent-based behavioural testing |

---

## Pipeline

```
  ┌─────────────────────┐
  │  plan-brainstorming │  ← Start here: idea(s) → specs + goal roadmap, then stops
  └──────────┬──────────┘
             │ *-spec.md, <goal>-roadmap.md
  ┌──────────▼──────────┐
  │    plan-writing     │  ← spec → implementation plan
  └──────────┬──────────┘
             │ *-impl.md
             │
      ┌──────▼──────┐        ┌───────────────────────────┐
      │large plan?  │──yes──►│    plan-splitter          │
      └──────┬──────┘        │  plan → <base>-roadmap.md │
             │ no            └──────────┬────────────────┘
             │                          │ <base>-a.md, -b.md, …
             └──────────┬───────────────┘
                        │
  ┌─────────────────────▼─────────────────────┐
  │              plan-executor                │  ← execute with progress ledger
  └─────────────────────┬─────────────────────┘
                        │
  ┌─────────────────────▼─────────────────────┐
  │             plan-resolver                 │  ← audit implementation
  └───────────────────────────────────────────┘

  plan-iterative-revision  ← use at any stage to clean up a plan; on a roadmap it verifies every part
  plan-chain-runner        ← runs the whole chain from the goal roadmap (or approved specs), by their dependencies
```

---

## Installation

### Option 1 — Install via `npx skills` (recommended)

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
| Project (default) | _(none)_ | `.claude/skills/plan-brainstorming/`, `.agents/skills/…`, etc. |
| Global | `-g` | `~/.claude/skills/`, `~/.copilot/skills/`, etc. |

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
# Install all 8 skills — CLI auto-detects your agent
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

### Option 2 — Clone and symlink manually

Use this option when you want a single source of truth on disk and prefer to
manage updates via `git pull`.

```bash
git clone https://github.com/whiteua/planforge-toolkit.git
cd planforge-toolkit
```

**Claude Code** (`~/.claude/skills/`)

```bash
# macOS / Linux
DEST="$HOME/.claude/skills"
for skill in plan-brainstorming plan-writing plan-splitter plan-executor plan-resolver plan-iterative-revision plan-chain-runner writing-skills; do
  ln -s "$PWD/skills/$skill" "$DEST/$skill"
done

# Windows PowerShell (run as Administrator)
$src = "$PWD\skills"; $dest = "$env:USERPROFILE\.claude\skills"
foreach ($s in @("plan-brainstorming","plan-writing","plan-splitter","plan-executor","plan-resolver","plan-iterative-revision","plan-chain-runner","writing-skills")) {
  New-Item -ItemType SymbolicLink -Path "$dest\$s" -Target "$src\$s"
}
```

**GitHub Copilot** (`~/.copilot/skills/`)

```bash
# macOS / Linux
DEST="$HOME/.copilot/skills"; mkdir -p "$DEST"
for skill in plan-brainstorming plan-writing plan-splitter plan-executor plan-resolver plan-iterative-revision plan-chain-runner writing-skills; do
  ln -s "$PWD/skills/$skill" "$DEST/$skill"
done

# Windows PowerShell (run as Administrator)
$src = "$PWD\skills"; $dest = "$env:USERPROFILE\.copilot\skills"
New-Item -ItemType Directory -Force -Path $dest
foreach ($s in @("plan-brainstorming","plan-writing","plan-splitter","plan-executor","plan-resolver","plan-iterative-revision","plan-chain-runner","writing-skills")) {
  New-Item -ItemType SymbolicLink -Path "$dest\$s" -Target "$src\$s"
}
```

**Codex / Cursor / Cline / Warp** (`~/.agents/skills/` or `~/.codex/skills/`)

```bash
# macOS / Linux — adjust DEST for your agent
DEST="$HOME/.codex/skills"   # or ~/.cursor/skills, ~/.agents/skills, etc.
mkdir -p "$DEST"
for skill in plan-brainstorming plan-writing plan-splitter plan-executor plan-resolver plan-iterative-revision plan-chain-runner writing-skills; do
  ln -s "$PWD/skills/$skill" "$DEST/$skill"
done
```

### Skill dependencies

> `plan-writing` reads contract files from `plan-brainstorming`, and `plan-splitter`'s deep verification (step 8) runs `plan-iterative-revision`. `plan-executor`, `plan-iterative-revision`, `plan-splitter` and `plan-resolver` read the chain settings through `plan-brainstorming`'s helper script, and `plan-executor` and `plan-resolver` also write `BACKLOG.md` through it; without it they warn and work without the settings. `plan-chain-runner` loads that script too (it needs it for the journal; without it only `settings-load` and `model-pick` without `--journal` work) and launches the six pipeline skills by name. Each pair must be installed in the **same parent directory**.

---

## Updating

This repository follows a **rolling-release model** — every push to `main` is a release. There are no version tags or lockfiles; the latest commit is always the current version.

> **Before updating:** an update replaces the installed skills without a prompt. Changes that break plans in progress are listed in [CHANGELOG.md](CHANGELOG.md). The 2026-09-30 release renames split-plan files, requires an `Environments` block for steps on external systems, and tightens `plan-resolver` reports. The 2026-10 release adds chain settings and read/write consent in the spec, stops `plan-executor` on files changed between tasks, and makes `plan-check` fail a task over 150 lines of code without a `**Size:**` line.

### How the CLI knows what to update

When you install via `npx skills add whiteua/planforge-toolkit`, the CLI stores the source reference (`whiteua/planforge-toolkit`) alongside each installed skill. On update, it fetches the latest state of the `main` branch from GitHub and replaces local files.

### Update commands

```bash
# Update all installed PlanForge skills (interactive scope prompt)
npx skills update

# Update all skills non-interactively (auto-detects scope)
npx skills update -y

# Update only global skills
npx skills update -g

# Update only project-local skills
npx skills update -p

# Update a single skill by name
npx skills update plan-executor

# Update several specific skills
npx skills update plan-brainstorming plan-writing plan-executor
```

#### Update flags

| Flag | Short | Description |
|---|---|---|
| `--global` | `-g` | Only update globally installed skills |
| `--project` | `-p` | Only update project-locally installed skills |
| `--yes` | `-y` | Skip scope prompt (auto-detect: project if in a project dir, else global) |
| `[skills...]` | | Update specific skills by name instead of all |

### Updating a manual (git clone) installation

If you installed via Option 2 (clone + symlink), updates are just a `git pull`:

```bash
cd planforge-toolkit
git pull origin main
```

Since your agent directories are symlinked to the cloned repo, updated files are picked up immediately — no reinstallation needed.

### Checking installed versions

```bash
# List all installed skills with their source
npx skills list

# List only global skills
npx skills ls -g
```

The CLI does not currently display commit hashes or dates. To verify you are on the latest version, compare `npx skills list` output with the [latest commits](https://github.com/whiteua/planforge-toolkit/commits/main).

---

## Usage

### Starting a new feature

```
/plan-brainstorming I want to add OAuth2 authentication to my API
/plan-brainstorming BACKLOG.md        # next cycle: the unchecked items of the shared backlog
```

The skill guides you from the idea to approved specs and the goal roadmap `<goal>-roadmap.md`, then stops; its closing report names the next command (`/plan-chain-runner <goal>-roadmap.md` or `/plan-writing <spec>`).

### Executing an existing plan

```
/plan-executor docs/plans/plan01-auth-impl.md
/plan-executor docs/plans/plan01-auth-impl.md commit   # after the audit: commit the run's files and the audit's fixes
```

### Splitting a large plan into parts

```
/plan-splitter docs/plans/plan01-auth-impl.md                      # gate decision, then <base>-roadmap.md + <base>-a.md, -b.md, …
/plan-splitter docs/plans/plan01-auth-impl.md verify=all           # …and verify every part with plan-iterative-revision
/plan-executor docs/plans/plan01-auth-impl-roadmap.md              # execute the parts in dependency order
```

### Auditing implementation progress

```
/plan-resolver docs/plans/plan01-auth-impl.md          # audit only
/plan-resolver docs/plans/plan01-auth-impl.md fix      # fix last report's issues, re-audit
/plan-resolver docs/plans/plan01-auth-impl.md auto     # audit → fix → audit, up to 2 cycles
```

### Iteratively fixing a plan

```
/plan-iterative-revision docs/plans/plan01-auth-impl.md                    # one plan
/plan-iterative-revision docs/plans/plan01-auth-impl-roadmap.md            # every part of a split plan, one review trail each
/plan-iterative-revision docs/plans/plan01-auth-impl.md preset=deep audit-only
```

### Running the whole chain

```
/plan-chain-runner docs/plans/plan01-roadmap.md      # from the goal roadmap: its order, groups and notes
/plan-chain-runner docs/plans/plan01-1-spec.md docs/plans/plan01-2-spec.md   # launch card, then the chain without questions
/plan-chain-runner continue      # resume from the journal (also: продолжить)
/plan-chain-runner discuss       # answer the open questions one by one (also: обсудить)
/plan-chain-runner status        # summary only (also: статус)
/plan-chain-runner help          # pipeline map; /plan-<skill> help shows that skill's USAGE.md
```

### Version control

No skill touches an external system without you. A database, API or remote service is reached only after you allow it for a named environment, separately for reading and for changes: `read=` and `write=` each take `run` (the whole run), `task` (ask before each task) or `deny`. The permission is never widened to another environment, changes on production are never allowed for a whole run, and an existing project script aimed at production is not permission. The spec records the environments with your own words, tasks that use them are marked `External` with `(read)` or `(write)`, and `plan-executor` asks before such a task unless that access is allowed for the whole run. A read allowed for the whole run also covers the read-only checks of `plan-iterative-revision` and `plan-resolver`.

Only `plan-executor` commits on your branch, and only at its commit stage: `/plan-executor <plan> commit` (or the chain, after the audit) commits the run's files and the files the audit fixed, with your hooks; a manual run with audit fixes lists them and waits for your "yes". It never pushes, amends or forces. Everything else stays uncommitted: `plan-brainstorming` and `plan-writing` write files; `plan-iterative-revision` and `plan-splitter` only add review, roadmap and part files; `plan-resolver`'s fix phase leaves code changes in the working tree and runs no git command that changes anything; `plan-executor` keeps per-unit rollback snapshots in hidden refs (`refs/plan-executor/<run>/<unit>`, removable with `checkpoint-prune`). After the run, `<base>-diffs.md` next to the plan shows what changed, file by file. Without git there is no diff report and no commit.

For detailed usage of each skill, see the [`USAGE.md`](skills/plan-brainstorming/USAGE.md) file inside each skill directory, or the full [User Guide](docs/USERGUIDE.md).

---

## Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.

If you find a bug or have a feature request, open an [issue](https://github.com/whiteua/planforge-toolkit/issues).

---

## Contact

**whiteua** — [github.com/whiteua](https://github.com/whiteua)

Project: [github.com/whiteua/planforge-toolkit](https://github.com/whiteua/planforge-toolkit)

---

## License

Distributed under the MIT License. See [LICENSE](LICENSE) for details.

---

## Technical Design

This section documents the engineering techniques applied across the toolkit. Each pattern is named, described, and mapped to the skill(s) where it is used.

### Deterministic / LLM boundary

Cheap, exact operations (file parsing, counting, hashing, shell probes) run as CLI tool commands with machine-readable exit codes. Semantic judgment (is this task implemented? is this plan coherent?) stays inside `SKILL.md` reference docs and is never mixed with deterministic checks. This separation prevents hallucinations from contaminating objective results and keeps tool logic testable independently.

**Used in:** `plan-resolver`, `plan-splitter`, `plan-executor`, `plan-brainstorming` (spec check, findings input), `plan-writing` (plan check), `plan-chain-runner` (scheduler)

---

### SHA-256 workspace fingerprint

A hash of all relevant workspace files is taken at the start of a pass and asserted again at the end. Any file mutation during a nominally read-only operation, other than the explicitly allowed outputs (the resolver's report and appended lines of `BACKLOG.md`), fails the `assert-readonly` check immediately. This catches accidental writes by the agent itself, not just intentional mutations.

The resolver also writes the SHA-256 of its evidence files into every report (`## Evidence fingerprint`: the files its anchors and the plan tasks' `Files` name), taken from the audit's start snapshot. The next pass compares that table with its own snapshot (`rescan-scope`) and re-audits only the tasks whose evidence changed, plus open tasks and the tasks of open issues; the closed lines of the other tasks are copied by script (`carry-forward`). A changed plan, an older report without the table or more than half of the tasks touched give a full pass, and only a full pass may close the plan with `-final`.

**Used in:** `plan-resolver` (`plan-splitter` hashes only the source plan and the part files to detect drift)

---

### task-census completeness gate

Before a resolver report is accepted, a tool parses the plan and extracts every task unit syntactically. The census then cross-checks that each extracted unit has a corresponding coverage entry in the draft report. Exit 1 if any task is uncovered — the agent must add the missing entries before re-running. Zero extracted units (unstructured plan) produces a loud diagnostic signal rather than a silent pass.

**Used in:** `plan-resolver`

---

### Evidence anchors (`path#Lx-Ly`)

Every `✅` verdict in a resolver report must be backed by a concrete code reference in `path#Lx-Ly` format, and `validate-report --root` checks that the file exists and the line range is inside it, for closed tasks and for issue evidence alike: a report that cites code that is not there is invalid. On subsequent passes, the agent re-reads the referenced lines before reusing an anchor; if the lines have shifted or the content changed, the anchor is treated as stale and the verdict is re-derived from fresh evidence. An incremental pass carries an anchor over without re-reading it only while the file's hash in the evidence fingerprint is unchanged; an anchor on a changed file sends its task to the re-audit. A closed task is one compact line with one anchor (a second only on the task's test file); detail lines belong to open tasks, and `validate-report` warns `verbose-closed-task` and `too-many-anchors` instead of failing older reports.

**Used in:** `plan-resolver`

---

### Confidence calibration

A task or issue may carry `confidence: high | medium | low`. A final report cannot close a task or an issue with `low`; open reports carry it as a warning. A task that stays `⚠️ ambiguous` with the same evidence anchor as in the previous pass is flagged as stuck, and the agent must strengthen or replace the evidence before the next pass.

**Used in:** `plan-resolver`

---

### Probe-gate (read-only shell whitelist)

For tasks marked as critical, the agent may run a shell probe to gather live evidence. Only commands from an explicit whitelist are permitted: `test`, `check`, `lint`, `type-check`. Commands that produce side effects (`migrate`, `seed`, `build`, `deploy`, `install`, `generate`, `git`) are blocked at the tool level, not by convention. Tasks where no suitable probe exists are marked `probe-needed` — a signal to the team to invest in test coverage, not a blocker. Tool caches that probes create (`.pytest_cache`, `.mypy_cache`, …) are excluded from the workspace fingerprint.

**Used in:** `plan-resolver`

---

### Gate-decision heuristic (numeric)

Before decomposing a plan, `splitter_tool.py gate` computes four factors with the shared task parser: task count, plan size in bytes, modules (distinct folders of the tasks' `Files`, two levels deep) and the shape of the Preconditions references (linear or groups). Up to 20 tasks, 100 KB and 3 modules the plan is kept whole; over 40 tasks or 150 KB with more than 3 modules or grouped dependencies it is split; anything between is borderline and the model decides from the task list alone, never from the plan text. In a chain with `split=auto` the runner calls the same gate and skips the split stage without an agent when it says keep. This prevents unnecessary fragmentation of small, coherent plans and costs no model tokens.

**Used in:** `plan-splitter`

---

### Self-sufficiency invariant

No generated part file (`<base>-a.md`, `<base>-b.md`, …) may contain back-references to another part or to the original plan's context. Every part carries all the information an agent needs to execute it in a single pass, in isolation. This prevents context bleed — the gradual degradation that occurs when later parts rely on implicit state accumulated by earlier ones. `split-write` guarantees it mechanically: every part carries the plan header and the full text of its tasks, copied byte for byte, and `validate-all` checks the copy by hash.

**Used in:** `plan-splitter`

---

### Topological ordering + parallel groups

The dependency graph of plan tasks is resolved into a partial order. Independent tasks are grouped into parallel execution sets; dependent tasks are sequenced. The roadmap file (`<base>-roadmap.md`) encodes both the sequential chains and the parallel groups explicitly, so the executor or a human can schedule work optimally.

**Used in:** `plan-splitter`

---

### 3-level VERIFY

After part generation, three verification passes run in order:
- **Level A — structural:** DAG validity, required sections present, part ids and dependencies well-formed.
- **Level B — coverage:** SHA-256 of the original plan matches, the parts hold exactly the plan's tasks, and every task body is found once, byte for byte (`task_bodies`, by hash).
- **Level C — handoff:** the outputs of each part cover the inputs of the parts that depend on it; the parts are not re-read, because the script copied their task text.

All three levels must pass before the split is announced. Up to three retry iterations are permitted; persistent failure produces an annotated diagnostic rather than partial output. An optional fourth step runs `plan-iterative-revision` once over the roadmap (every part in turn, one review trail each) and accepts the result only through the machine gate `verify-status`, which checks the claimed results against the review files and part hashes.

**Used in:** `plan-splitter`

---

### Persistent progress ledger

`plan-executor` writes a structured ledger (`state.json`) into an `exec_dir` outside the repository, by default `<repo parent>/.exec/<repo>-<plan>/`; a directory inside the repository or the OS temp dir is refused. Each unit has an explicit state (`pending`, `running`, `done`, `failed`) and an attempt count; a rendered `progress.md` sits beside it. The ledger survives session restarts: re-running `ledger-init` resumes it, and a changed plan or part file is reported as `plan-drift` until the engineer accepts it. The ledger also stores the chain settings with the hash of their source (`settings-drift` on resume), consents given during the run and the expected file tree used by foreign-change detection. A split plan runs task by task as well: the units of a roadmap are the `### Task N:` headings of its parts, and each part ends with a checkpoint unit over its completion criteria and handoff.

**Used in:** `plan-executor`

---

### Foreign-change detection (expected tree)

The ledger keeps the git tree the working copy must have before the next unit (`expected_tree`), built with the same temporary index as the snapshots but without a commit. `unit-begin` compares the working copy with it and, on any difference, returns `reason: foreign-changes` with the added, modified and deleted paths instead of starting the unit. The engineer accepts the changes (`accept-changes`), restores those files (`checkpoint-restore --paths … --exec-dir …`) or stops; a run without a confirmation channel stops with a report. `unit-finish` moves the expected tree forward, so a retry after a failure raises no false alarm; `BACKLOG.md` is not compared.

**Used in:** `plan-executor`

---

### Read/write consent per environment

An external system is permitted separately for reading and for changes: `read=` and `write=` each take `run` (the whole run), `task` (ask before every task) or `deny`. Production changes are never `run`: `spec-check`, `plan-check` and the executor's `consent` command reject it. Tasks declare `` **External:** `name` (read|write) ``, and `plan-check` rejects an access the environment denies. `unit-begin` returns each access with `confirmed` and its `source` (`spec`, or `session` for a consent given during the run, cleared on resume). A read allowed for the run also covers the read-only checks of the plan and code audits.

**Used in:** `plan-brainstorming`, `plan-writing`, `plan-executor`, `plan-iterative-revision`, `plan-resolver`

---

### Set-algebraic flow analysis

After each audit pass, the tool computes four sets over issue fingerprints:

| Set | Formula | Meaning |
|---|---|---|
| **new** | `current − cumulative` | First-time issues never seen in any prior iteration |
| **resolved** | `prev − current` | Issues present in the last iteration but gone now |
| **persisted** | `prev ∩ current` | Issues present in both the last iteration and now |
| **reintroduced** | `(cumulative − prev) ∩ current` | Issues that existed before, disappeared, and have reappeared |

These four categories drive **hard-stop decisions**: if `reintroduced ≠ ∅` after 3+ iterations the loop halts with `ESCALATED` (regression detected); if the fingerprint set is identical to the previous audit, or `resolved = ∅` and `new ≠ ∅` over a sliding window of 2 iterations, `STAGNATION` is declared (unchanged / churn); a fingerprint present in 3 consecutive audits is `ESCALATED` as stuck. History covers the current run only, so reviews from earlier runs never trigger a stop. The agent cannot override these stops: a single `record` call computes them deterministically, together with fingerprints, rendering and validation of the review file.

**Used in:** `plan-iterative-revision`

---

### SHA-1 issue fingerprinting

Every issue found during audit receives a stable 8-character fingerprint: `SHA-1(category + normalized_required_fix)[:8]`. The same conceptual issue always produces the same fingerprint regardless of iteration number, phrasing variations, or surrounding context. This enables precise cross-iteration tracking: the system distinguishes “new bug” from “same bug resurfaced” without relying on textual similarity heuristics. Fingerprints are computed by the tool, never by the agent, and form the atoms of the flow-analysis algebra. When a contract from the previous review is still unapplied, the agent re-reports it by fingerprint (`carry`), and the tool copies its category and required fix verbatim, so the identity cannot drift through rephrasing.

**Used in:** `plan-iterative-revision`

---

### Two-phase separation (audit ≠ implement)

`plan-iterative-revision` enforces strict separation of duties within each iteration:

- **Phase A (Audit)** — reads the plan and code, writes exactly one new review file. The plan is never modified.
- **Phase B (Implement)** — reads the review file, applies surgical edits to the plan. Review files are never modified.

This mirrors the Fagan Inspection pattern (IBM, 1976): the inspector and the fixer are never the same actor in the same step. Applied to an LLM agent, it prevents the common failure mode where an agent “finds and fixes” in one pass, silently masking issues it introduced.

**Used in:** `plan-iterative-revision`

---

### 10-class error taxonomy with multi-lens sweep

Audit passes are structured around 10 orthogonal error classes: `logic`, `code`, `math`, `ops`, `db`, `contract`, `tests`, `security`, `perf`, `code-plan-mismatch`. The agent reads the plan once in a full audit (an incremental audit reads the header and the tasks in scope) and then checks **one class at a time** within each lens, rather than scanning for everything at once. This prevents attention scattering and ensures coverage across all concern domains. Depth is configurable: `quick` (L1 only), `standard` (L1+L2), `deep` (L1–L4 with red-team attack pass).

**Used in:** `plan-iterative-revision`

---

### Immutable append-only review trail

Each iteration produces a numbered review file (`-review-1.md`, `-review-2.md`, …) that is never overwritten or modified after creation. Review files carry mandatory machine-validated headers (plan SHA-256, timestamp, severity counts, flow profile) and serve as:
- Legal audit trail of what errors were found and when
- Input for contract verification (each “Required fix” becomes a contractual obligation checked in the next iteration)
- Source data for the flow-analysis algebra

The agent hands its findings to the tool as JSON; the tool renders the review file and validates it deterministically (`validate-review --strict-fingerprint`) before the agent proceeds.

**Used in:** `plan-iterative-revision`

---

### Incremental re-audit by task hash

Every review ends with a `## Task digest` table: the id and an 8-hex SHA-1 of each task body, the same hash `plan-splitter` checks parts by. Before the next audit, `digest` compares the plan with that table and returns the audit's scope: the changed and new tasks, the tasks of the open contracts, and every task that depends on a changed, new or removed one through `Preconditions` (transitive closure), with their line ranges. The agent reads only the plan's header and those ranges and cross-checks only their claims; a plan unchanged byte for byte whose tasks' `Files` are unchanged on disk is not audited at all; a changed file (the review's `## Code digest`) puts its tasks and their dependents into the scope. The scope falls back to a full audit when more than half of the tasks are touched, when a contract cannot be mapped to a task, or without a table. Quality is held by one rule in the gate authority: an incremental audit that finds nothing returns `full-audit-required`, and only a full audit can declare `converged`. A contract of an unchanged task that the incremental audit skipped is carried back by the tool itself (`contracts-dropped`).

**Used in:** `plan-iterative-revision`

---

### Contract-driven plan generation

`plan-writing` starts by running `plan-brainstorming`'s `spec-check` on the spec (8 mandatory sections, empty `Open Questions`) and stops when it fails; the plan it writes is then checked by `plan-check --root`, which enforces the header, `### Task N:` headings, the task core per tier, no placeholders, no commit steps, and that `Create:` targets are new while `Modify:`/`Test:` targets and cited paths exist in the repository. Every existing symbol a task relies on is cited as `path:line`, and the plan header records the test baseline taken before planning. This keeps the plan traceable to the design and grounded in the code rather than in guesses. A task over 100 lines of code is split or carries `**Size:** <N> lines — <reason>`; without it `plan-check` warns above 100 lines and fails above 150, and justified tasks are listed as `oversized`.

**Used in:** `plan-writing`, `plan-brainstorming`

---

### Shared task parser

`brainstorm_tool.py plan-tasks` (`parse_plan_tasks`) is the one parser of plan tasks: for each `### Task N: <title>` outside code fences it returns the id, title, 1-based line range (a task ends at the next task heading or a heading of its level or higher), the `**Files:**` entries, the task ids named in `**Preconditions:**`, the body's size, code line count and SHA-1, plus malformed and duplicate headings. `plan-check`, the executor's units, the resolver's `task-census`, the splitter's task count and the runner's `run-stats` read this result, so every stage sees the same tasks and boundaries; plans outside the contract and installations without `plan-brainstorming` keep each script's own parser. A contract test in `plan-writing/tests` runs all consumers on a reference plan and a fixture of tricky cases. A plan that plan-writing is still writing ends with the marker `> Writing: in progress (spec sha256 <12 hex>)`: `plan-tasks` returns the tasks before it with `incomplete: true` and `marker_spec_sha`, and `plan-check`, `journal-reconcile`, the splitter's `preflight`, the executor's `ledger-init` and the revision's `bootstrap` refuse that plan (`plan-incomplete`), so a cut-off writer is continued, never executed half-written.

**Used in:** `plan-brainstorming`, `plan-writing`, `plan-executor`, `plan-resolver`, `plan-splitter`, `plan-chain-runner`

---

### Plan skeleton

`plan_tool.py skeleton <plan>` prints the plan without code bodies: the header whole, and per task its heading, `**Files:**`, the conditions, `**External:**`, `**Size:**`, `**Structural event:**`, the step headings and `Run:`/`Expected:` lines, with one `[code <lang>, <N> lines: <signatures>]` line in place of each code block; `plan_tool.py task <plan> <id>` prints one task byte for byte. plan-resolver's first and closing full passes read the skeleton, because they check the code in the repository, not the code quoted in the plan, and open a task in full only for a disputed verdict. The skeleton is generated on demand and never stored, so it cannot go stale; plan-iterative-revision keeps reading the plan (it checks the plan's code), and the incremental passes read their tasks by line range.

**Used in:** `plan-writing`, `plan-resolver`

---

### Size budgets

One plan's budget is 40 tasks or 150000 bytes, defined once as `SIZE_BUDGET` in `brainstorm_tool.py`. Before a plan exists, `spec-check` estimates a spec's volume (`estimate_tasks = Components items × tier factor 1/2/3 + Testing Strategy items`), and `plan-brainstorming` shows the estimate in the Chain Settings message and proposes several specs of one goal above the budget. After the plan is written, `plan-check` returns `size_class` (`small`/`medium`/`large`) and the warning `plan-oversized`; `plan-writing`'s hand-off advises decomposition instead of a task-count split rule, and in a chain the warning rides on the `writing` event and the runner prints it as one progress line without stopping. Every later stage costs in proportion to the plan's size, so the budget is checked where it is still cheap to change the scope. A contract test keeps the fallback in `plan_tool.py` and the splitter gate's thresholds equal to `SIZE_BUDGET`.

**Used in:** `plan-brainstorming`, `plan-writing`, `plan-chain-runner`

---

### Spec-owned chain settings

Every decision the chain needs is taken once, in the spec dialogue, and written above `# Goal`: `> Chain: split=…; revision=…; stop=…; resolver=…`, one `> Environment:` line per external system and `> Backlog: <section>`. `spec-check` validates them and the plan does not copy them. Later skills find them through one reading rule (`brainstorm_tool.py settings`: the plan header if it has settings, else the spec named by `**Spec:**`; parts and roadmaps go through their Source link), so the revision takes its preset and stop policy, the splitter its `split` decision and the executor its resolver choice without asking. When a decision is missing and nobody can be asked, the skill stops with a report instead of guessing. For a spec written before settings existed, `plan-writing` asks as before and records the answers in the plan header.

**Used in:** `plan-brainstorming`, `plan-writing`, `plan-iterative-revision`, `plan-splitter`, `plan-executor`, `plan-resolver`

---

### Shared append-only backlog

One `BACKLOG.md` at the repository root collects what the chain deferred: Out of Scope items of approved specs, findings of the executor and defects of the resolver outside the plan. Its format belongs to `plan-brainstorming`: `backlog-append` adds one line at the end of a goal's section, verifies that every other byte is unchanged and skips duplicates. The `My notes` section is the user's. An item is open `[ ]`, taken into an approved spec `[x]` or cancelled `[-]` (set only by the user; a cancelled item is never appended again). `backlog-mark` checks off the items an approved spec took in and `backlog-unmark` unchecks the items an amended or withdrawn spec no longer covers, each after the user confirms and changing only the checkbox byte. `backlog-sweep` (read-only) gives the agent the open items of a section and the specs of its chain journal, so that items a spec already covers are found by meaning and checked off after confirmation. `/plan-brainstorming BACKLOG.md` turns the unchecked items into the next task. The file is free: the user writes to it at any moment, and no stage counts its change as a foreign change (the executor's foreign check, the revision's diff guard, the resolver's evidence). `commit-run` appends the plan's deviations from the spec as `amend spec …` lines, and the runner's `run-checklist` the checklist after a run.

**Used in:** `plan-brainstorming`, `plan-executor`, `plan-resolver`

---

### Chain journal

One `<goal>-chain.json` next to the spec records, for each plan of the goal, seven stages (`writing`, `revision`, `split`, `execution`, `diffs`, `audit`, `commit`) with the statuses `pending`, `running`, `done`, `stopped`, `failed`, `skipped`, the artifacts each skill produced and an append-only event log. Every skill marks its own stage through `brainstorm_tool.py journal-event`, which refuses a transition outside the state machine (`illegal-transition`); a finished stage re-opens only for a named reason (`drift`, `audit-open`, `recommit`, `user-request`). The SHA-256 of the stage input stored on `done` turns a changed spec or plan into a drift question; the skill that owns the stage asks it and re-runs the stage (`--reason drift`) or keeps its result for the changed input. A run without a confirmation channel records its question (`Qn`, `open → answered → applied`) and stops; the next run reads `journal-show`, applies the answer and continues. Writes go through a lock file (`journal-locked` after 10 s, takeover of a lock older than 60 s) and an atomic replace; `journal-reconcile` restores the statuses from the artifacts after a crash and `journal-validate` replays the events and checks the time fields. A question asked before `plan-writing` names its spec (`journal-question --spec`), so the plan's entry is bound to it from the start. Manual runs keep the journal too; a skill without `plan-brainstorming` beside it works without one.

**Used in:** all six pipeline skills and `plan-chain-runner`

---

### Goal roadmap

After the last spec of a goal, `plan-brainstorming` writes `<goal>-roadmap.md` next to the specs from a JSON the agent assembles in the dialogue. `roadmap-write` checks it against the chain journal and the disk (every spec of the journal present, known and acyclic dependencies, no spec in its dependency's group, shared touchpoints in an order that follows the execution order) and writes the file atomically from a template: the execution order `#` (topological, by levels), a Mermaid `graph LR` with one node per spec and a subgraph per parallel group, the shared touchpoints that `spec-set-check` found in the specs' Components, notes and hand-offs per spec, and the inputs of the call. `roadmap-check` parses the file back and requires the Mermaid edges to equal the table; `roadmap-parse` returns it as JSON for `plan-chain-runner`. Before the roadmap, `spec-set-check` and a reviewer subagent check the set of specs together, so conflicts between specs written one at a time surface before any plan exists. `journal-path` maps the roadmap to the goal's journal, and `plan-executor` refuses it as a split roadmap.

**Used in:** `plan-brainstorming`, `plan-executor`, `plan-chain-runner`

---

### Single findings stream

Defects outside the plan found by the executor's gates, the resolver's audit and the revision's reading of the code go through one command, `journal-finding`: the journal keeps one entry per `file` + `summary`, `BACKLOG.md` gets the line at once (a failed append is recorded, not fatal), and `journal-export-findings` rewrites `<goal>-followups.json` in the input format of `/plan-brainstorming`, so the next cycle starts from that file.

**Used in:** `plan-executor`, `plan-resolver`, `plan-iterative-revision`, `plan-brainstorming`

---

### Run diff report

After the last unit, `run-diff --markdown` writes `<base>-diffs.md` next to the plan: a table of the changed files (status `A`/`M`/`D`/`R`, added and removed lines, a link to the file), then one `diff` block per file between the baseline snapshot and the last unit's snapshot. A fence is one backtick longer than any backtick run inside it, a binary file is listed only, and a file diff is cut at 400 lines with the command for the full diff. Pipeline artifacts (`BACKLOG.md`, the run's journal and, in the run's plan folder only, specs, plans, parts, roadmaps, reviews, reports, completion files, journals, diff reports, follow-ups) are left out and listed in a section of their own, so a project file caught by these rules is visible; an audit fix file that git ignores is listed under "Not included (ignored by git)". The user's git config (colour, prefixes, external diff, textconv) does not change the report. Without git there is no report: the `diffs` stage is `skipped`.

**Used in:** `plan-executor`

---

### Commit stage

Only `plan-executor` commits, through `commit-run`, after the audit: in a chain automatically, by hand with `/plan-executor <plan> commit`. The set is the run's files plus the files the resolver fixed (`fix_files`), minus pipeline artifacts and files already committed. Before anything is written, `commit-run` refuses a non-empty index (`index-not-empty`), files that held uncommitted work before the run and were changed by it (`mixed-files`, judged against `baseline_head`, the HEAD at the start of the run), files changed outside the run (`foreign-changes`), a run with a unit still running (`run-incomplete`), files of a failed unit that differ from the last done snapshot and are not audit fixes (`failed-attempt`: the attempt was not rolled back or the files changed outside the run; they are restored with `checkpoint-restore --paths`) and a `HEAD` that no longer contains `baseline_head` (`head-moved`, another branch checked out). When only the expected tree was garbage-collected, `snapshots-missing` names `accept-changes`, which resets it. The commit runs the repository hooks; a failing hook leaves the index as it was. Push, amend, force and `--no-verify` are never used. A manual run with audit fixes lists them and waits for an explicit "yes"; a later call commits only new fixes, as `fix(<scope>): …`. The resolver stays git-read-only: its gate only names the command. Without git the stage is `skipped`.

**Used in:** `plan-executor`, `plan-resolver`

---

### Dialogue in the plan's language

Everything the user sees — questions, answer options, status lines, gates, summaries, stop reports — is in the language of the first task statement; only parser tokens stay in English. The language is detected by one deterministic rule (Cyrillic letters over 5% of all letters → Russian), exposed as `detect-lang` and as the `lang` field of `spec-check` and `plan-check`.

**Used in:** all six pipeline skills and `plan-chain-runner`

---

### Host profiles

`plan-chain-runner` has one core (start dialogue, dependency graph, loop, scheduling rules, `continue`, `discuss`, progress lines) and a profile per host, chosen at start from the tools it has. The `claude-code` profile (Claude Code) launches each stage as an `Agent` with the model of its role (with `subagent_type: planforge-<role>` when you agreed to agent-definition files that also set the effort or a pinned model: an alias such as `sonnet` does not pin the version, a full model id such as `claude-sonnet-5-5` does); the `github-copilot` profile (GitHub Copilot CLI) uses the `task` tool with a model, and the effort is inherited from the session; the `fallback` profile runs every stage in the same session, one at a time. A missing capability moves the runner to the next profile. Models and effort per role come from `~/.planforge/runner.json` (built-in defaults when it is missing), are shown in the launch card for confirmation and recorded in the journal; a model the host refuses is replaced by the role's `fallback` (`model-pick --unsupported`). `split` runs on `sonnet` with low effort by default, since it reads only the task list; the `execution` role may also name `light`, a cheaper model (e.g. `haiku`) the executor gives green tasks to (off by default; a host that refuses it turns delegation off for the run without a question).

**Used in:** `plan-chain-runner`

---

### Dependency-graph scheduler

`chain_tool.py run-next` decides what runs now from the journal alone. The stages of one plan go strictly in order (writing → revision → split → execution → diffs → audit → commit). Independent specs are written in parallel, up to `parallel`. Execution, diffs, audit and commit run for one plan at a time, and while a plan is in them the revision and split of the others wait as `code-busy`, because the revision's diff guard compares a snapshot of the whole tree and would take the executor's edits for a violation; nothing else is issued while an audit runs, because the resolver fingerprints the whole working tree and the executor stops on foreign changes. A spec that depends on another starts only after that spec's commit; when its audit stayed open, the dependent spec waits for your `accept` or `fix`. A plan with an open question waits with the specs that depend on it, and the rest go on; a failed stage is retried once, then asked about. The runner handles each agent as it returns and tells `run-next` which agents are still in flight (`--in-flight`), so a fast plan is not held up by a long execution of another. A plan stopped inside the code stages keeps them (its changes are uncommitted in the shared tree): the other plans' revision, split and execution wait as `code-busy`, and `status` and `discuss` show such waits. After a `rewrite` answer on a `drift:` question, the later stages of that plan are redone without asking again. Questions the scheduler acts on carry fixed prefixes (`open-audit:`, `not-confirmed:`, `stage-failed:`, `drift:`, `plan-oversized:`) and are answered with fixed tokens.

Given the goal roadmap (`/plan-chain-runner <goal>-roadmap.md`), the run's order and dependencies come from that checked file, not from a guess in the dialogue: `run-init --roadmap` stores the specs in the roadmap's `#` order with the file's name and SHA-256, `subset-check` cuts the graph to the specs chosen and names missing dependencies and plans that would leave the run with uncommitted changes, and `run-status` compares the hash on every `continue`: a changed roadmap is shown as a `roadmap-changed` card and applied only after you confirm it. Groups stay documentation; the width is still `parallel`. The roadmap's notes reach the writing and revision agents of their spec.

**Used in:** `plan-chain-runner`

---

### Artifact trust

The runner does not believe an agent's report. After every agent it runs `journal-reconcile` and `journal-show`: a stage counts as done only when the journal and the files the skill left say so. An agent whose stage the journal does not confirm — whatever it reported, an error or silence included, and one silent for 60 minutes — is launched once more, then the stage gets a `not-confirmed:` question and its plan waits. An executor that ran out of context leaves `execution` running; a new executor agent continues from the ledger until the stage is `done`, `failed` or `stopped`.

**Used in:** `plan-chain-runner`

---

### Runner sessions

A run in progress is marked by a session file outside the working tree, `~/.planforge/sessions/<sha1 of the journal path>.json`, with a heartbeat at every step and at least every 10 minutes. A mark younger than 30 minutes means another runner is active, and you decide whether to continue here; an older mark is abandoned, unless a stage is still `running` in the journal, and then you are asked too. The mark is created exclusively and carries the session id: a runner whose mark was taken over gets `session-taken-over` on its next heartbeat and stops without writing. The journal keeps only the history (`runner.sessions`: start, end and how it ended). While an audit runs, the runner writes nothing into the journal, not even a question, so the resolver's read-only fingerprint stays valid.

**Used in:** `plan-chain-runner`

---

### Artifact-based cost accounting

`chain_tool.py run-stats` measures a run from what it left behind: per stage the files written, their size and code share, the minutes and the model from the journal, and a token estimate (bytes / 3, output weighted 4× because it is priced several times above input) whose reads model follows the artifacts, so an incremental review, an incremental audit (only the evidence changed since the previous report and that of its re-audited tasks) or a script split is counted as what it read. With a journal every plan of the journal is a row: `totals` is the run's, `journal_totals` adds the plans of earlier runs of the goal (`outside_run: true`). Where the host showed an agent's token usage, the runner recorded it and the fact replaces the estimate (`basis: host`). Quality rides along (audit status and issues, reviews, unit retries), and `--baseline` compares two results per task and per KB of plan, so a token saving that worsens the audit is visible as such. The model, the toolkit's own baseline and the checkpoints of its refactoring are in [docs/COST.md](docs/COST.md).

**Used in:** `plan-chain-runner`

---

### Subagent-based behavioural skill testing

`writing-skills` tests new skills not by reading their source but by spawning a subagent with the skill loaded and observing its behaviour on a set of canonical scenarios. This mirrors how the skill will be used in production and catches description-matching failures, missing reference files, and incorrect workflow sequencing that static analysis cannot find.

**Used in:** `writing-skills`
