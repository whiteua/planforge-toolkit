<div align="center">

# 🔨 PlanForge Toolkit

**A structured AI planning pipeline — from raw idea to verified implementation.**

[![Stars](https://img.shields.io/github/stars/whiteua/planforge-toolkit?style=for-the-badge&color=yellow)](https://github.com/whiteua/planforge-toolkit/stargazers)
[![License](https://img.shields.io/github/license/whiteua/planforge-toolkit?style=for-the-badge&color=blue)](LICENSE)
[![Issues](https://img.shields.io/github/issues/whiteua/planforge-toolkit?style=for-the-badge&color=red)](https://github.com/whiteua/planforge-toolkit/issues)
[![skills.sh](https://skills.sh/b/whiteua/planforge-toolkit)](https://skills.sh/whiteua/planforge-toolkit)

[Overview](#overview) · [Skills](#skills) · [Pipeline](#pipeline) · [Installation](#installation) · [Usage](#usage) · [Contributing](#contributing)

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

| Skill | Description | Depends on |
|---|---|---|
| [`plan-brainstorming`](skills/plan-brainstorming/) | Turn ideas into validated design specs through collaborative dialogue | — |
| [`plan-writing`](skills/plan-writing/) | Convert a spec into a detailed, step-by-step implementation plan | `plan-brainstorming` |
| [`plan-splitter`](skills/plan-splitter/) | Decompose a large plan into self-contained stages for parallel execution | — |
| [`plan-executor`](skills/plan-executor/) | Execute a plan one unit at a time with ledger-backed progress tracking | — |
| [`plan-iterative-revision`](skills/plan-iterative-revision/) | Iteratively audit and patch a plan until it is error-free | — |
| [`plan-resolver`](skills/plan-resolver/) | Audit implementation against the plan and produce a structured report | — |
| [`writing-skills`](skills/writing-skills/) | Create, test, and deploy new agent skills using TDD methodology | — |

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
      ┌──────▼──────┐         ┌──────────────────────────┐
      │large plan?  │──yes──► │    plan-splitter          │
      └──────┬──────┘         │  plan → stg00-roadmap.md  │
             │ no             └──────────┬───────────────┘
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

Install the full collection with one command:

```bash
npx skills add whiteua/planforge-toolkit
```

Or install a single skill:

```bash
npx skills add whiteua/planforge-toolkit/plan-brainstorming
```

### Option 2 — Clone and install manually

```bash
git clone https://github.com/whiteua/planforge-toolkit.git
cd planforge-toolkit
```

#### Claude Code — `~/.claude/skills/`

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

#### VS Code GitHub Copilot — `~/.copilot/skills/`

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

#### GitHub Copilot CLI — `.github/skills/` (project-level)

Copy the skills into your project's `.github/skills/` directory to activate them for GitHub Copilot CLI and cloud agents within that project:

```bash
# macOS / Linux
DEST=".github/skills"; mkdir -p "$DEST"
for skill in plan-brainstorming plan-writing plan-splitter plan-executor plan-resolver plan-iterative-revision writing-skills; do
  cp -r /path/to/planforge-toolkit/skills/$skill "$DEST/$skill"
done
```

#### Codex / inference.sh agents — `~/.agents/skills/`

```bash
# macOS / Linux
DEST="$HOME/.agents/skills"; mkdir -p "$DEST"
for skill in plan-brainstorming plan-writing plan-splitter plan-executor plan-resolver plan-iterative-revision writing-skills; do
  ln -s "$PWD/skills/$skill" "$DEST/$skill"
done
```

### Skill dependencies

> `plan-writing` reads contract files from `plan-brainstorming`. Both must be installed in the **same parent directory**.

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
