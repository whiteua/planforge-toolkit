# plan-iterative-revision — Quick Reference

Audit an implementation plan against the codebase, record the errors in a review file, fix them in
the plan, and repeat until the plan is clean or a stop gate fires.

## How to Invoke

```
/plan-iterative-revision <plan-path> [preset=...] [lenses=...] [rigor=...] [max=...] [stop_policy=...] [interaction=...] [audit-only] [parts=...]
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
bootstrap (numbering, language, config, write check; a plan still carrying plan-writing's marker is plan-incomplete)
  → Phase A: audit plan + code → issues JSON
  → record: gates + write review-N.md (with the hash of every task and of every file the tasks name);
    with issues to apply it also returns the plan's room in the budget of 150 000 bytes
  → Phase B: apply review-N to the plan within that room; an issue that does not fit is deferred
    (budget) and stays open in the next review; a plan pushed over the budget gets one compression
    of the tasks Phase B changed
  → digest: which tasks changed, and which tasks' files changed on disk → the next audit reads only
    them, their dependents and the open contracts' tasks (incremental); an unchanged plan with
    unchanged code skips the audit
  → each phase runs inside the diff guard: a snapshot of the working tree by `git status` (HEAD,
    every changed path git does not ignore, the plan folder's ignored files with their hashes); a
    change outside the phase's own file or a commit stops the run, any ignored path outside the
    plan folder that appeared, vanished or changed is `ignored_changed` (information only, not
    written into the review), while other plans' pipeline files (a plan written in parallel, the chain journal)
    are only counted in the next review's `**Concurrent pipeline files**` line
  → repeat; a clean incremental audit is followed by one full audit before `converged`
```

## Stop Conditions

| Condition | Result |
|---|---|
| No issues on the first audit | `clean`, no files created |
| No issues on a later audit | `converged`, `<plan>-completion.md` written |
| No issues on an incremental audit | not a stop: one full audit follows; only its clean result is `converged` |
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
- `<goal>-chain.json` next to the spec — the chain journal: the `revision` stage (running, done with the last review and the completion file, stopped at a gate that needs you, with an open question when nobody could answer) and the code defects found on the way, plus the issues deferred for the budget that stayed open (`budget: <title>`) (also appended to `BACKLOG.md`)

## Prerequisites

- Python ≥ 3.8 in PATH, shell access for the helper script
- The plan's directory is writable
- `plan-brainstorming` installed alongside for incremental re-audits (without it every audit reads the whole plan),
  for the budget (without it `budget-unavailable`, no budget) and for the diff guard's snapshot (without it the
  guard falls back to plain `git status`, warning `snapshot-unavailable`, and does not hash the plan folder's
  ignored files)
- Git for the diff guard: without it the guard checks no files (exit 3) and only measures the plan for the budget

## Common Errors

| Symptom | Cause | Fix |
|---|---|---|
| "Cannot create review file" | Plan directory not writable | Check permissions |
| "Plan is clean" but you see issues | Preset too shallow | Re-run with `preset=deep` |
| Stagnation after 2 audits | The same issues survive plan edits | Resolve them manually, then re-run |
| Guard violation (`guard-check` exit 1) | A phase changed a file outside its own file, or `HEAD` moved | The run stops with the paths; review them, then re-run |
| `snapshot-failed` from `guard-begin` (exit 1) | `git status` or `git hash-object` failed; no phase runs unguarded | Fix the repository (e.g. a stale lock file), re-run |
| `plan-incomplete` from `bootstrap` | The plan still carries plan-writing's marker `> Writing: in progress` | Finish the plan: `/plan-writing <spec>` |

## Pipeline Position

```
plan-brainstorming → plan-writing → [YOU ARE HERE] → plan-splitter → plan-executor → plan-resolver
```

Usable at any stage to clean up a plan. `plan-splitter` also runs it on individual stages.
