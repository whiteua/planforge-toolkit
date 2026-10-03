# plan-iterative-revision — Quick Reference

Audit an implementation plan against the codebase, record the errors in a review file, fix them in
the plan, and repeat until the plan is clean or a stop gate fires.

## How to Invoke

```
/plan-iterative-revision <plan-path> [preset=...] [stop_policy=...] [interaction=...] [audit-only]
/plan-iterative-revision help   # show this quick reference in the dialogue language, nothing else
```

### Usage Examples

```bash
# Minimal — defaults (preset=standard, stop_policy=pragmatic)
/plan-iterative-revision docs/plans/plan01-feature.md

# Quick shallow audit
/plan-iterative-revision docs/plans/plan01-feature.md preset=quick

# Deep red-team audit, strict zero-issues policy
/plan-iterative-revision docs/plans/plan01-feature.md preset=deep stop_policy=strict

# Audit only: one review file, the plan is not changed
/plan-iterative-revision docs/plans/plan01-feature.md audit-only

# Non-interactive run (as used by plan-splitter); prints one JSON result
/plan-iterative-revision docs/plans/plan01-feature.md interaction=autonomous
```

### Batch mode (after plan-splitter)

```bash
# Verify every part of a split plan in one run, one review trail per part
/plan-iterative-revision docs/plans/plan01-impl-roadmap.md interaction=autonomous

# Only parts a and c
/plan-iterative-revision docs/plans/plan01-impl-roadmap.md parts=a,c
```

## Arguments

| Argument | Required | Default | Description |
|---|---|---|---|
| Plan file path | **Yes** | — | Path to the master plan `.md` file |
| `preset` | No | `standard`; with an explicit `Chain` setting, its `revision`, else the tier | `quick` / `standard` / `deep`: lenses, code rigor, max iterations |
| `lenses` / `rigor` / `max` | No | from preset | Override one preset dial |
| `stop_policy` | No | `pragmatic`, or `stop` of an explicit `Chain` setting | `pragmatic` (stop when only nits remain) / `strict` (zero issues) |
| `interaction` | No | `auto` | `auto` / `interactive` / `autonomous` |
| `audit-only` | No | off | Audit once, write the review, do not change the plan |
| `parts` | No | all | Batch mode: which parts of a roadmap to verify (`a,c`) |

With a `> Chain:` line in the spec (or `**Chain:**` in an old plan header), `bootstrap` takes
`preset` and `stop_policy` from it and the skill does not ask; an argument you pass still wins.
When that line has no `revision` key, the preset is the tier (`> Tier: Deep` → `deep`), not
`standard`; only without a tier it is `standard`.
A run without a confirmation channel stops at the iteration limit without a question. A read
allowed for the whole run (`read=run`) lets the audit check that environment, read-only.

## Presets

| Preset | Lenses | Code rigor | Max iterations |
|---|---|---|---|
| `quick` | 1 | grep | 3 |
| `standard` | 2 | grep + read | 5 |
| `deep` | 4 (incl. red-team) | grep + read + Explore subagent | 7 |

## What Happens

```
bootstrap (numbering, language, config, write check)
  → Phase A: audit plan + code → issues JSON
  → record: gates + write review-N.md
  → Phase B: apply review-N to the plan
  → repeat
```

## Stop Conditions

| Condition | Result |
|---|---|
| No issues on the first audit | `clean`, no files created |
| No issues on a later audit | `converged`, `<plan>-completion.md` written |
| Only nits remain (`pragmatic`) | `converged`, final review with nits |
| Same issues as the previous audit | `stagnation` (unchanged) |
| New issues but nothing resolved for 2 audits | `stagnation` (churn) |
| A resolved issue comes back | `escalated` (regression) |
| One issue in 3 consecutive audits | `escalated` (stuck) |
| Max iterations reached | asks +3 / +5 / stop; autonomous: `limit` |

Only reviews created in the current run count for these gates.

## Output Files

- `<plan-basename>-review-N.md` — one per audit with issues (immutable history)
- `<plan-basename>-completion.md` — when the cycle converges
- `<goal>-chain.json` next to the spec — the chain journal: the `revision` stage (running, done with the last review and the completion file, stopped at a gate that needs you, with an open question when nobody could answer) and the code defects found on the way (also appended to `BACKLOG.md`)

## Prerequisites

- Python ≥ 3.8 in PATH, shell access for the helper script
- The plan's directory is writable

## Common Errors

| Symptom | Cause | Fix |
|---|---|---|
| "Cannot create review file" | Plan directory not writable | Check permissions |
| "Plan is clean" but you see issues | Preset too shallow | Re-run with `preset=deep` |
| Stagnation after 2 audits | The same issues survive plan edits | Resolve them manually, then re-run |

## Pipeline Position

```
plan-brainstorming → plan-writing → [YOU ARE HERE] → plan-splitter → plan-executor → plan-resolver
```

Usable at any stage to clean up a plan. `plan-splitter` also runs it on individual stages.
