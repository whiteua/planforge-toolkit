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
| [`plan-brainstorming`](skills/plan-brainstorming/) | Turn ideas into validated design specs through collaborative dialogue | — | Depth-tiered elaboration, spec contract validation |
| [`plan-writing`](skills/plan-writing/) | Convert a spec into a detailed, step-by-step implementation plan | `plan-brainstorming` | Contract-driven generation, plan lifecycle model |
| [`plan-splitter`](skills/plan-splitter/) | Decompose a large plan into self-contained stages for parallel execution | — | Gate-decision (5-factor), topological ordering + parallel groups, 3-level VERIFY, self-sufficiency invariant, SHA-256 origin fingerprint |
| [`plan-executor`](skills/plan-executor/) | Execute a plan one unit at a time with ledger-backed progress tracking | — | Persistent progress ledger, multi-session continuity, gated SDLC workflow |
| [`plan-iterative-revision`](skills/plan-iterative-revision/) | Iteratively audit and patch a plan until it is error-free | — | Set-algebraic flow analysis (new/resolved/persisted/reintroduced), SHA-1 issue fingerprinting, two-phase separation (audit ≠ implement), regression/churn/stagnation hard-stops, 10-class error taxonomy, immutable append-only review trail |
| [`plan-resolver`](skills/plan-resolver/) | Audit implementation against the plan and produce a structured report | — | task-census completeness gate, evidence anchors (`path#Lx-Ly`), confidence calibration, probe-gate (whitelist), self-consistency check, SHA-256 fingerprint, read-only invariant |
| [`writing-skills`](skills/writing-skills/) | Create, test, and deploy new agent skills using TDD methodology | — | Red-green-refactor for skills, subagent-based behavioural testing |

---

## Pipeline

```
  ┌─────────────────────┐
  │  plan-brainstorming │  ← Start here: idea → design spec
  └──────────┬──────────┘
             │ spec.md
  ┌──────────▼──────────┐
  │    plan-writing     │  ← spec → implementation plan
  └──────────┬──────────┘
             │ plan.md
             │
      ┌──────▼──────┐        ┌───────────────────────────┐
      │large plan?  │──yes──►│    plan-splitter          │
      └──────┬──────┘        │  plan → stg00-roadmap.md  │
             │ no            └──────────┬────────────────┘
             │                          │ stg01..stgN.md
             └──────────┬───────────────┘
                        │
  ┌─────────────────────▼─────────────────────┐
  │              plan-executor                │  ← execute with progress ledger
  └─────────────────────┬─────────────────────┘
                        │
  ┌─────────────────────▼─────────────────────┐
  │             plan-resolver                 │  ← audit implementation
  └───────────────────────────────────────────┘

  plan-iterative-revision  ← use at any stage to clean up a plan
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

> `plan-writing` reads contract files from `plan-brainstorming`. Both must be installed in the **same parent directory**.

---

## Updating

This repository follows a **rolling-release model** — every push to `main` is a release. There are no version tags or lockfiles; the latest commit is always the current version.

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
```

The skill will guide you through the full brainstorming → spec → plan cycle.

### Executing an existing plan

```
/plan-executor docs/plans/plan01-auth-impl.md
```

### Splitting a large plan into stages

```
/plan-splitter docs/plans/plan01-auth-impl.md
```

### Auditing implementation progress

```
/plan-resolver docs/plans/plan01-auth-impl.md
```

### Iteratively fixing a plan

```
/plan-iterative-revision docs/plans/plan01-auth-impl.md
```

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

**Used in:** `plan-resolver`, `plan-splitter`, `plan-executor`

---

### SHA-256 workspace fingerprint

A hash of all relevant workspace files is taken at the start of a pass and asserted again at the end. Any file mutation during a nominally read-only operation fails the `assert-readonly` check immediately. This catches accidental writes by the agent itself, not just intentional mutations.

**Used in:** `plan-resolver`, `plan-splitter`

---

### task-census completeness gate

Before a resolver report is accepted, a tool parses the plan and extracts every task unit syntactically. The census then cross-checks that each extracted unit has a corresponding coverage entry in the draft report. Exit 1 if any task is uncovered — the agent must add the missing entries before re-running. Zero extracted units (unstructured plan) produces a loud diagnostic signal rather than a silent pass.

**Used in:** `plan-resolver`

---

### Evidence anchors (`path#Lx-Ly`)

Every `✅ done` verdict in a resolver report must be backed by a concrete code reference in `path#Lx-Ly` format. On subsequent passes, the agent re-reads the referenced lines before reusing an anchor; if the lines have shifted or the content changed, the anchor is treated as stale and the verdict is re-derived from fresh evidence.

**Used in:** `plan-resolver`

---

### Confidence calibration

Each task coverage entry carries a `confidence: high | medium | low` field. The final report is blocked from closing if any entry is `low`. Intermediate reports may carry `low` entries with a warning. If a task stays in `⚠️ ambiguous` state across two consecutive passes without a change in evidence, the confidence is forced to `low` and human escalation is required.

**Used in:** `plan-resolver`

---

### Probe-gate (read-only shell whitelist)

For tasks marked as critical, the agent may run a shell probe to gather live evidence. Only commands from an explicit whitelist are permitted: `test`, `check`, `lint`, `type-check`. Commands that produce side effects (`migrate`, `seed`, `build`, `deploy`, `install`, `generate`, `git`) are blocked at the tool level, not by convention. Tasks where no suitable probe exists are marked `probe-needed` — a signal to the team to invest in test coverage, not a blocker.

**Used in:** `plan-resolver`, `plan-splitter`

---

### Gate-decision heuristic (5-factor)

Before decomposing a plan, `plan-splitter` evaluates five factors: estimated plan size, task complexity distribution, potential for parallel execution, context-window overflow risk, and team topology. If the plan scores below a threshold, splitting is skipped and the agent recommends executing the original plan directly. This prevents unnecessary fragmentation of small, coherent plans.

**Used in:** `plan-splitter`

---

### Self-sufficiency invariant

No generated stage file may contain back-references to another stage or to the original plan's context. Every stage carries all the information an agent needs to execute it in a single pass, in isolation. This prevents context bleed — the gradual degradation that occurs when later stages rely on implicit state accumulated by earlier ones.

**Used in:** `plan-splitter`

---

### Topological ordering + parallel groups

The dependency graph of plan tasks is resolved into a partial order. Independent tasks are grouped into parallel execution sets; dependent tasks are sequenced. The roadmap file (`-stg00-roadmap.md`) encodes both the sequential chains and the parallel groups explicitly, so the executor or a human can schedule work optimally.

**Used in:** `plan-splitter`

---

### 3-level VERIFY

After stage generation, three verification passes run in order:
- **Level A — structural:** DAG validity, required sections present, dependency declarations well-formed.
- **Level B — coverage:** SHA-256 of the original plan matches, total task count across all stages is ≥ original task count.
- **Level C — semantic:** each stage is self-sufficient, handoff conditions between stages are explicit, no contradictory instructions across stages.

All three levels must pass before output files are finalised. Up to three retry iterations are permitted; persistent failure produces an annotated diagnostic rather than partial output.

**Used in:** `plan-splitter`

---

### Persistent progress ledger

`plan-executor` writes a structured ledger file alongside the plan. Each task has an explicit state (`not-started`, `in-progress`, `done`, `blocked`). The ledger survives session restarts: a new agent session picks up the ledger and resumes from the last known state without re-reading the entire plan history.

**Used in:** `plan-executor`

---

### Set-algebraic flow analysis

After each audit pass, the tool computes four sets over issue fingerprints:

| Set | Formula | Meaning |
|---|---|---|
| **new** | `current − cumulative` | First-time issues never seen in any prior iteration |
| **resolved** | `prev − current` | Issues present in the last iteration but gone now |
| **persisted** | `prev ∩ current` | Issues present in both the last iteration and now |
| **reintroduced** | `(cumulative − prev) ∩ current` | Issues that existed before, disappeared, and have reappeared |

These four categories drive **hard-stop decisions**: if `reintroduced ≠ ∅` after 3+ iterations the loop halts with `ESCALATED` (regression detected); if `resolved = ∅` and `new ≠ ∅` over a sliding window of 2 iterations, `STAGNATION` is declared (churn). The agent cannot override these stops — they are computed deterministically by the tool script.

**Used in:** `plan-iterative-revision`

---

### SHA-1 issue fingerprinting

Every issue found during audit receives a stable 8-character fingerprint: `SHA-1(category + normalized_required_fix)[:8]`. The same conceptual issue always produces the same fingerprint regardless of iteration number, phrasing variations, or surrounding context. This enables precise cross-iteration tracking: the system distinguishes “new bug” from “same bug resurfaced” without relying on textual similarity heuristics. Fingerprints are validated by the tool and form the atoms of the flow-analysis algebra.

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

Audit passes are structured around 10 orthogonal error classes: `logic`, `code`, `math`, `ops`, `db`, `contract`, `tests`, `security`, `perf`, `code-plan-mismatch`. The agent performs **one complete lens pass per class** — re-reading the plan with a specific focus each time — rather than scanning for everything at once. This prevents attention scattering and ensures coverage across all concern domains. Depth is configurable: `quick` (L1 only), `standard` (L1+L2), `deep` (L1–L4 with red-team attack pass).

**Used in:** `plan-iterative-revision`

---

### Immutable append-only review trail

Each iteration produces a numbered review file (`-review-1.md`, `-review-2.md`, …) that is never overwritten or modified after creation. Review files carry mandatory machine-validated headers (plan SHA-256, timestamp, severity counts, flow profile) and serve as:
- Legal audit trail of what errors were found and when
- Input for contract verification (each “Required fix” becomes a contractual obligation checked in the next iteration)
- Source data for the flow-analysis algebra

The tool validates review structure deterministically (`validate-review --strict-fingerprint`) before the agent proceeds.

**Used in:** `plan-iterative-revision`

---

### Contract-driven plan generation

`plan-writing` reads a spec contract produced by `plan-brainstorming` and validates that the generated plan satisfies every contract clause before writing the output file. This creates a verifiable link from the original design intent to the implementation plan, preventing scope drift during the writing step.

**Used in:** `plan-writing`, `plan-brainstorming`

---

### Subagent-based behavioural skill testing

`writing-skills` tests new skills not by reading their source but by spawning a subagent with the skill loaded and observing its behaviour on a set of canonical scenarios. This mirrors how the skill will be used in production and catches description-matching failures, missing reference files, and incorrect workflow sequencing that static analysis cannot find.

**Used in:** `writing-skills`
