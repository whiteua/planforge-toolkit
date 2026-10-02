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
| [`plan-brainstorming`](skills/plan-brainstorming/) | Turn ideas into validated design specs through collaborative dialogue | — | Depth-tiered elaboration, spec contract validation, chain settings and per-environment read/write consent recorded in the spec, shared `BACKLOG.md`, dialogue in the user's language |
| [`plan-writing`](skills/plan-writing/) | Convert a spec into a detailed, step-by-step implementation plan | `plan-brainstorming` | Spec preflight, plan format contract (`plan-check`), codebase grounding with `path:line` citations and a recorded test baseline, access type on external tasks, justified size exceptions (`**Size:**`) |
| [`plan-splitter`](skills/plan-splitter/) | Decompose a large plan into self-contained parts (`<base>-a.md`, `-b.md`, …) with a dependency roadmap | `plan-iterative-revision` (optional, deep verification); `plan-brainstorming` (optional, chain settings) | Gate-decision (5-factor) or the `split` setting, topological ordering + parallel groups, 3-level VERIFY, self-sufficiency invariant, SHA-256 origin hash, one batch verification run with a machine gate, `External` and `Size` lines carried verbatim |
| [`plan-executor`](skills/plan-executor/) | Execute a plan one unit at a time with ledger-backed progress tracking | `plan-brainstorming` (chain settings, `BACKLOG.md`) | Persistent progress ledger with resume, plan-drift and settings-drift detection, strictly ordered units with retry-first policy, risk-scaled gates, read/write consent per external system, foreign-change detection against an expected tree with per-file restore, rollback snapshots in hidden git refs (no branch commits), run diff, findings to `BACKLOG.md` |
| [`plan-iterative-revision`](skills/plan-iterative-revision/) | Iteratively audit and patch a plan (or every part of a split plan) until it is error-free | `plan-brainstorming` (chain settings) | Set-algebraic flow analysis (new/resolved/persisted/reintroduced), SHA-1 issue fingerprinting, two-phase separation (audit ≠ implement), single gate authority (regression/churn/unchanged/stuck/limit), 10-class error taxonomy, immutable append-only review trail, batch mode over split parts, preset and stop policy from the chain settings |
| [`plan-resolver`](skills/plan-resolver/) | Audit implementation against the plan and produce a structured report; optionally fix the code and re-audit (`fix` / `auto`) | `plan-brainstorming` (chain settings, `BACKLOG.md`) | task-census completeness gate, evidence anchors (`path#Lx-Ly`) verified against the workspace, confidence calibration, probe-gate (whitelist), self-consistency check, SHA-256 fingerprint, read-only audit invariant (report and `BACKLOG.md` only), separated fix → re-audit loop with protected plan, snapshot diff and bounded cycles |
| [`writing-skills`](skills/writing-skills/) | Create, test, and deploy new agent skills using TDD methodology | — | Red-green-refactor for skills, subagent-based behavioural testing |

---

## Pipeline

```
  ┌─────────────────────┐
  │  plan-brainstorming │  ← Start here: idea → design spec
  └──────────┬──────────┘
             │ *-spec.md
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
for skill in plan-brainstorming plan-writing plan-splitter plan-executor plan-resolver plan-iterative-revision writing-skills; do
  ln -s "$PWD/skills/$skill" "$DEST/$skill"
done

# Windows PowerShell (run as Administrator)
$src = "$PWD\skills"; $dest = "$env:USERPROFILE\.claude\skills"
foreach ($s in @("plan-brainstorming","plan-writing","plan-splitter","plan-executor","plan-resolver","plan-iterative-revision","writing-skills")) {
  New-Item -ItemType SymbolicLink -Path "$dest\$s" -Target "$src\$s"
}
```

**GitHub Copilot** (`~/.copilot/skills/`)

```bash
# macOS / Linux
DEST="$HOME/.copilot/skills"; mkdir -p "$DEST"
for skill in plan-brainstorming plan-writing plan-splitter plan-executor plan-resolver plan-iterative-revision writing-skills; do
  ln -s "$PWD/skills/$skill" "$DEST/$skill"
done

# Windows PowerShell (run as Administrator)
$src = "$PWD\skills"; $dest = "$env:USERPROFILE\.copilot\skills"
New-Item -ItemType Directory -Force -Path $dest
foreach ($s in @("plan-brainstorming","plan-writing","plan-splitter","plan-executor","plan-resolver","plan-iterative-revision","writing-skills")) {
  New-Item -ItemType SymbolicLink -Path "$dest\$s" -Target "$src\$s"
}
```

**Codex / Cursor / Cline / Warp** (`~/.agents/skills/` or `~/.codex/skills/`)

```bash
# macOS / Linux — adjust DEST for your agent
DEST="$HOME/.codex/skills"   # or ~/.cursor/skills, ~/.agents/skills, etc.
mkdir -p "$DEST"
for skill in plan-brainstorming plan-writing plan-splitter plan-executor plan-resolver plan-iterative-revision writing-skills; do
  ln -s "$PWD/skills/$skill" "$DEST/$skill"
done
```

### Skill dependencies

> `plan-writing` reads contract files from `plan-brainstorming`, and `plan-splitter`'s deep verification (step 8) runs `plan-iterative-revision`. `plan-executor`, `plan-iterative-revision`, `plan-splitter` and `plan-resolver` read the chain settings through `plan-brainstorming`'s helper script, and `plan-executor` and `plan-resolver` also write `BACKLOG.md` through it; without it they warn and work without the settings. Each pair must be installed in the **same parent directory**.

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

The skill will guide you through the full brainstorming → spec → plan cycle.

### Executing an existing plan

```
/plan-executor docs/plans/plan01-auth-impl.md
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

### Version control

No skill touches an external system without you. A database, API or remote service is reached only after you allow it for a named environment, separately for reading and for changes: `read=` and `write=` each take `run` (the whole run), `task` (ask before each task) or `deny`. The permission is never widened to another environment, changes on production are never allowed for a whole run, and an existing project script aimed at production is not permission. The spec records the environments with your own words, tasks that use them are marked `External` with `(read)` or `(write)`, and `plan-executor` asks before such a task unless that access is allowed for the whole run. A read allowed for the whole run also covers the read-only checks of `plan-iterative-revision` and `plan-resolver`.

No skill commits on your branch. `plan-brainstorming` and `plan-writing` write files and leave them uncommitted; `plan-iterative-revision` and `plan-splitter` only add review, roadmap and part files; `plan-resolver`'s fix phase leaves code changes in the working tree for review; `plan-executor` keeps per-unit rollback snapshots in hidden refs (`refs/plan-executor/<run>/<unit>`, removable with `checkpoint-prune`) and never touches your branch. Commit when a block of work is verified, with the message you choose.

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

**Used in:** `plan-resolver`, `plan-splitter`, `plan-executor`, `plan-brainstorming` (spec check, findings input), `plan-writing` (plan check)

---

### SHA-256 workspace fingerprint

A hash of all relevant workspace files is taken at the start of a pass and asserted again at the end. Any file mutation during a nominally read-only operation, other than the explicitly allowed outputs (the resolver's report and appended lines of `BACKLOG.md`), fails the `assert-readonly` check immediately. This catches accidental writes by the agent itself, not just intentional mutations.

**Used in:** `plan-resolver` (`plan-splitter` hashes only the source plan and the part files to detect drift)

---

### task-census completeness gate

Before a resolver report is accepted, a tool parses the plan and extracts every task unit syntactically. The census then cross-checks that each extracted unit has a corresponding coverage entry in the draft report. Exit 1 if any task is uncovered — the agent must add the missing entries before re-running. Zero extracted units (unstructured plan) produces a loud diagnostic signal rather than a silent pass.

**Used in:** `plan-resolver`

---

### Evidence anchors (`path#Lx-Ly`)

Every `✅` verdict in a resolver report must be backed by a concrete code reference in `path#Lx-Ly` format, and `validate-report --root` checks that the file exists and the line range is inside it, for closed tasks and for issue evidence alike: a report that cites code that is not there is invalid. On subsequent passes, the agent re-reads the referenced lines before reusing an anchor; if the lines have shifted or the content changed, the anchor is treated as stale and the verdict is re-derived from fresh evidence.

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

### Gate-decision heuristic (5-factor)

Before decomposing a plan, `plan-splitter` evaluates five factors: task count, domain spread across modules, blocking dependencies between task groups, whether the plan fits one agent pass, and parallelism. It splits when two factors say so or one factor alone blocks a single pass; otherwise it prints a gate-pass notice and the plan goes straight to `plan-executor`. This prevents unnecessary fragmentation of small, coherent plans.

**Used in:** `plan-splitter`

---

### Self-sufficiency invariant

No generated part file (`<base>-a.md`, `<base>-b.md`, …) may contain back-references to another part or to the original plan's context. Every part carries all the information an agent needs to execute it in a single pass, in isolation. This prevents context bleed — the gradual degradation that occurs when later parts rely on implicit state accumulated by earlier ones.

**Used in:** `plan-splitter`

---

### Topological ordering + parallel groups

The dependency graph of plan tasks is resolved into a partial order. Independent tasks are grouped into parallel execution sets; dependent tasks are sequenced. The roadmap file (`<base>-roadmap.md`) encodes both the sequential chains and the parallel groups explicitly, so the executor or a human can schedule work optimally.

**Used in:** `plan-splitter`

---

### 3-level VERIFY

After part generation, three verification passes run in order:
- **Level A — structural:** DAG validity, required sections present, part ids and dependencies well-formed.
- **Level B — coverage:** SHA-256 of the original plan matches, total task count across all parts is ≥ original task count.
- **Level C — semantic:** each part is self-sufficient, handoff conditions between parts are explicit, no contradictory instructions across parts.

All three levels must pass before the split is announced. Up to three retry iterations are permitted; persistent failure produces an annotated diagnostic rather than partial output. An optional fourth step runs `plan-iterative-revision` once over the roadmap (every part in turn, one review trail each) and accepts the result only through the machine gate `verify-status`, which checks the claimed results against the review files and part hashes.

**Used in:** `plan-splitter`

---

### Persistent progress ledger

`plan-executor` writes a structured ledger (`state.json`) into an `exec_dir` outside the repository, by default `<repo parent>/.exec/<repo>-<plan>/`; a directory inside the repository or the OS temp dir is refused. Each unit has an explicit state (`pending`, `running`, `done`, `failed`) and an attempt count; a rendered `progress.md` sits beside it. The ledger survives session restarts: re-running `ledger-init` resumes it, and a changed plan or part file is reported as `plan-drift` until the engineer accepts it. The ledger also stores the chain settings with the hash of their source (`settings-drift` on resume), consents given during the run and the expected file tree used by foreign-change detection.

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

Audit passes are structured around 10 orthogonal error classes: `logic`, `code`, `math`, `ops`, `db`, `contract`, `tests`, `security`, `perf`, `code-plan-mismatch`. The agent reads the plan once and then checks **one class at a time** within each lens, rather than scanning for everything at once. This prevents attention scattering and ensures coverage across all concern domains. Depth is configurable: `quick` (L1 only), `standard` (L1+L2), `deep` (L1–L4 with red-team attack pass).

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

### Contract-driven plan generation

`plan-writing` starts by running `plan-brainstorming`'s `spec-check` on the spec (8 mandatory sections, empty `Open Questions`) and stops when it fails; the plan it writes is then checked by `plan-check --root`, which enforces the header, `### Task N:` headings, the task core per tier, no placeholders, no commit steps, and that `Create:` targets are new while `Modify:`/`Test:` targets and cited paths exist in the repository. Every existing symbol a task relies on is cited as `path:line`, and the plan header records the test baseline taken before planning. This keeps the plan traceable to the design and grounded in the code rather than in guesses. A task over 100 lines of code is split or carries `**Size:** <N> lines — <reason>`; without it `plan-check` warns above 100 lines and fails above 150, and justified tasks are listed as `oversized`.

**Used in:** `plan-writing`, `plan-brainstorming`

---

### Spec-owned chain settings

Every decision the chain needs is taken once, in the spec dialogue, and written above `# Goal`: `> Chain: split=…; revision=…; stop=…; resolver=…`, one `> Environment:` line per external system and `> Backlog: <section>`. `spec-check` validates them and the plan does not copy them. Later skills find them through one reading rule (`brainstorm_tool.py settings`: the plan header if it has settings, else the spec named by `**Spec:**`; parts and roadmaps go through their Source link), so the revision takes its preset and stop policy, the splitter its `split` decision and the executor its resolver choice without asking. When a decision is missing and nobody can be asked, the skill stops with a report instead of guessing. For a spec written before settings existed, `plan-writing` asks as before and records the answers in the plan header.

**Used in:** `plan-brainstorming`, `plan-writing`, `plan-iterative-revision`, `plan-splitter`, `plan-executor`, `plan-resolver`

---

### Shared append-only backlog

One `BACKLOG.md` at the repository root collects what the chain deferred: Out of Scope items of approved specs, findings of the executor and defects of the resolver outside the plan. Its format belongs to `plan-brainstorming`: `backlog-append` adds one line at the end of a goal's section, verifies that every other byte is unchanged and skips duplicates. The `My notes` section is the user's, and only the user checks items off. `/plan-brainstorming BACKLOG.md` turns the unchecked items into the next task.

**Used in:** `plan-brainstorming`, `plan-executor`, `plan-resolver`

---

### Dialogue in the plan's language

Everything the user sees — questions, answer options, status lines, gates, summaries, stop reports — is in the language of the first task statement; only parser tokens stay in English. The language is detected by one deterministic rule (Cyrillic letters over 5% of all letters → Russian), exposed as `detect-lang` and as the `lang` field of `spec-check` and `plan-check`.

**Used in:** all six pipeline skills

---

### Subagent-based behavioural skill testing

`writing-skills` tests new skills not by reading their source but by spawning a subagent with the skill loaded and observing its behaviour on a set of canonical scenarios. This mirrors how the skill will be used in production and catches description-matching failures, missing reference files, and incorrect workflow sequencing that static analysis cannot find.

**Used in:** `writing-skills`
