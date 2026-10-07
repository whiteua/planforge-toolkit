# plan-splitter — Quick Reference

Decompose a large plan into self-contained parts (`<base>-a.md`, `<base>-b.md`, …) with a
dependency roadmap, each part executable in a single agent pass.

## How to Invoke

```
/plan-splitter <plan-path> [verify=ask|all|none|a,c] [verify_depth=quick|standard|deep] [verify_mode=full-cycle|audit-only]
/plan-splitter help   # show this quick reference in the dialogue language, nothing else
```

### Usage Examples

```bash
# Minimal — the skill decides whether to split at all
/plan-splitter docs/plans/plan01-impl.md

# Split and deep-verify every part
/plan-splitter docs/plans/plan01-impl.md verify=all verify_depth=deep

# Verify only parts a and c, reviews only (parts are not edited)
/plan-splitter docs/plans/plan01-impl.md verify=a,c verify_mode=audit-only

# Skip deep verification
/plan-splitter docs/plans/plan01-impl.md verify=none
```

## Arguments

| Argument | Required | Default | Description |
|---|---|---|---|
| Plan file path | **Yes** | — | Path to the plan `.md` |
| `verify` | No | `ask`; `none` in a run without a confirmation channel (chain run, subagent) | `ask` / `all` / `none` / part list — deep verification scope (non-interactive `ask` = `none`) |
| `verify_depth` | No | `standard` | `quick` / `standard` / `deep` — `preset` for plan-iterative-revision |
| `verify_mode` | No | `full-cycle` | `full-cycle` / `audit-only` — may verification edit the parts |

## What Happens

```
1. BOOTSTRAP        — language, write preflight, existing artifacts
2. GATE DECISION    — split setting: always → split, never → not needed (except after your answer split to the runner's plan-oversized: question: then as always); auto or none → `gate` (numbers: tasks, bytes, modules, dependency shape; "keep" is a normal outcome; without a confirmation channel `silent_verdict` decides borderline)
                      keep: ≤ 20 tasks, ≤ 100000 bytes and ≤ 3 modules; split: (> 40 tasks or > 150000 bytes) and (> 3 modules or dependency shape `groups`); else borderline.
                      silent_verdict: borderline → keep within 40 tasks and 150000 bytes, else split.
                      Overrides: --keep-tasks, --keep-bytes, --split-tasks, --split-bytes, --modules.
                      In a chain with split=auto the runner calls the same gate itself: keep, or borderline → keep, skips the stage without an agent.
3. ANALYSIS         — boundaries from `plan-tasks` (the plan is not read): dependency graph, parallel groups, weights 🔴/🟡/🟢
4. DRAFT & CONFIRM  — in a dialogue you approve the split table (one retry); without a confirmation channel nothing is shown or asked, and the table goes to the journal as `parts_table`
5. GENERATE         — `split-write`: <base>-roadmap.md + <base>-a.md, -b.md, …, task texts copied byte for byte
6. VERIFY           — validate-all (files, DAG, equal task coverage, task bodies, External/Size/Structural event lines, hash) + handoff check
7. VERIFY CHOICE    — deep verification? (scope, depth, mode)
8. DEEP VERIFY      — one plan-iterative-revision batch run over the parts, machine gate
```

## Output Files

All files are created next to the original plan, which is never modified:

| File | Purpose |
|---|---|
| `<base>-roadmap.md` | Part map: dependencies, parallel groups, weights |
| `<base>-a.md`, `<base>-b.md`, … (`aa`, `ab` after `z`) | Self-contained parts |
| `<base>-verify-baseline.json`, `<base>-verify-ledger.json` | Deep-verification snapshot and ledger |
| `<base>-<id>-review-N.md`, `<base>-<id>-completion.md` | Review trail per part (written by plan-iterative-revision) |
| `<goal>-chain.json` (next to the spec) | Chain journal: the `split` stage, `done` with the roadmap and the parts, or `skipped` when the plan stays whole |

## Deep Verification

`plan-iterative-revision` runs once on the roadmap and verifies the selected parts one after
another. `verify-status` then checks every claim against the files: a `converged` part needs a
validated review and a changed file, a `clean` part needs neither. `missing` parts are
re-dispatched once; `inconsistent` stops the run. Parts with warnings are listed in the summary.

## Prerequisites

- Python ≥ 3.8 in PATH
- `plan-brainstorming` installed next to this skill: `gate`, `split-write` and `validate-all` exit 2 without its task parser
- Writable plan directory
- For deep verification: `plan-iterative-revision` installed next to this skill, and a subagent tool

## Common Errors

| Symptom | Cause | Fix |
|---|---|---|
| "Gate: keep" | Plan is small or focused enough | Not an error; run plan-executor directly |
| `no-tasks` from `gate` | The plan has no `### Task N:` headings | Write the roadmap by hand, or add task headings |
| `dependency-order` / `missing-depends` from `split-write` | A Preconditions reference crosses the part boundaries | Move the task, or add the dependency in parts.json |
| `tasks-unassigned` / `tasks-duplicated` / `tasks-unknown`, `part-ids-not-sequential`, `unknown-dependency`, `dependency-cycle`, `group-conflict` from `split-write` (exit 1) | parts.json does not cover the plan's tasks exactly once, or its ids, dependencies or groups are inconsistent | Fix parts.json and repeat; nothing was written |
| `parts-json-invalid` from `split-write` (exit 2) | parts.json is not valid JSON or has the wrong shape | Fix parts.json and repeat |
| `plan-task-headings` from `split-write` (exit 1) | The plan has a malformed or repeated `### Task N:` heading | Fix the plan's headings (`plan-check`), then split again |
| `exists` from `split-write` (exit 1) | Parts or the roadmap of this base already exist | Overwrite (`--force`), another base, or abort |
| `plan-changed` from `split-write` (exit 1) | The source plan changed while the parts were written (`written` lists them) | Let the plan settle, then repeat with `--force` |
| `plan-brainstorming not installed alongside` (exit 2) | The shared task parser is missing | Install `plan-brainstorming` next to this skill |
| "Cannot write to directory" | Directory not writable | Check permissions |
| Existing split artifacts | A previous split exists | Choose overwrite / another base / abort |
| `plan-incomplete` from `preflight` (exit 1) | The plan still carries plan-writing's marker `> Writing: in progress` | Finish the plan: `/plan-writing <spec>` |
| Part too large (> 15 tasks) | Coarse split | Re-run the splitter on that part |
| `invalid stage id` | Roadmap row id is not letters | Use `a`, `b`, … in the Stage column |

## Pipeline Position

```
plan-brainstorming → plan-writing → plan-iterative-revision → [YOU ARE HERE] → plan-executor → plan-resolver
```

**Previous:** `plan-writing` or `plan-iterative-revision`
**Next:** `plan-executor` on `<base>-roadmap.md`
