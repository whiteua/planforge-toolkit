# plan-iterative-revision — Quick Reference

Audit an implementation plan against the codebase, find errors, and fix them in automated cycles until the plan is clean.

## How to Invoke

In VS Code Copilot chat, type:

```
/plan-iterative-revision <plan-path> [preset=...] [stop_policy=...] [interaction=...]
```

### Usage Examples

```bash
# Minimal — defaults (preset=standard, stop_policy=pragmatic)
/plan-iterative-revision docs/plans/plan01-feature.md

# Quick shallow audit
/plan-iterative-revision docs/plans/plan01-feature.md preset=quick

# Deep red-team audit, strict zero-issues policy
/plan-iterative-revision docs/plans/plan01-feature.md preset=deep stop_policy=strict

# Audit-only (no fixes, just produce review file)
/plan-iterative-revision docs/plans/plan01-feature.md preset=standard interaction=autonomous

# All arguments at once
/plan-iterative-revision .docs/.plans/refactor/plan.md preset=deep stop_policy=strict interaction=interactive
```

## Arguments

| Argument | Required | Default | Description |
|---|---|---|---|
| Plan file path | **Yes** | — | Path to the master plan `.md` file |
| `preset` | No | `standard` | `quick` / `standard` / `deep` — controls lenses, rigor, max iterations |
| `stop_policy` | No | `pragmatic` | `pragmatic` (stop when only nits remain) / `strict` (zero issues) |
| `interaction` | No | `auto` | `auto` / `interactive` / `autonomous` |

## Presets Explained

| Preset | Lenses | Code Rigor | Max Iterations |
|---|---|---|---|
| `quick` | 1 aspect lens | grep-level | 3 |
| `standard` | 2 aspect lenses | read-level | 5 |
| `deep` | 3 lenses + red-team L4 | explore (subagent) | 7 |

## Modes

| Mode | Behavior |
|---|---|
| `full-cycle` (default) | Audit → create review → implement fixes → repeat until clean |
| `audit-only` | Audit → create review file → stop (no fixes applied) |

## What Happens (Full Cycle)

```
Phase A (Audit):  Read plan → verify against code → find issues → write review-N.md
    ↓
Phase B (Implement):  Apply fixes from review to the plan (blocker→major→minor→nit)
    ↓
Repeat until: issues empty / max reached / stagnation detected
```

## Stop Conditions

| Condition | Result |
|---|---|
| No issues found (first pass) | "Plan is clean" — no files created |
| No issues found (pass N>1) | `<plan>-completion.md` written, converged |
| Max iterations reached | Asks: +3 / +5 / stop |
| Stagnation (same issues repeat) | Auto-stop with verdict |
| Regression (old issues reappear) | Hard stop, escalation |
| Only nits remain (`pragmatic`) | Stop, final review with nits |

## Output Files

- `<plan-basename>-review-N.md` — one per audit iteration (historical, immutable)
- `<plan-basename>-completion.md` — written when cycle converges

## Prerequisites

- Python ≥ 3.8 in PATH
- File write tools available (cannot substitute with memory/chat)

## Checklist Before Invoking

- [ ] Plan file exists and is a valid implementation plan
- [ ] Workspace/codebase is accessible for verification
- [ ] File creation is possible in the plan's directory

## Common Errors

| Symptom | Cause | Fix |
|---|---|---|
| "Cannot create review file" | Write tools unavailable or directory not writable | Enable file write mode / check permissions |
| "Plan is clean" but you see issues | Preset too shallow | Re-run with `preset=deep` |
| Stagnation after 2 iterations | Issues cannot be resolved by plan edits alone | Review the stagnated issues manually |

## Pipeline Position

```
plan-brainstorming → plan-writing → [YOU ARE HERE] → plan-splitter → plan-executor → plan-resolver
```

**Previous:** `plan-writing` (produces the plan)  
**Next:** `plan-splitter` (breaks large plans into stages) or `plan-executor` (if plan is small enough)
