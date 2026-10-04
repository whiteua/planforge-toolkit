# EXECUTION-STRATEGY

## One Diagnosis, Three Params

`unit-begin` returns `strategy` for the unit, derived from its weight and title:

- `isolation`: `main` or `subagent`
- `model_depth`: `light`, `medium`, or `deep`
- `gate_tier`: `green`, `yellow`, or `red` (see `GATE.md`)

A unit's weight is the plan's tier (Quick → green, Standard → yellow, Deep → red), lowered where the expensive gate buys nothing: a checkpoint task and a task whose files are all documentation are green; a task that touches only test files goes one step down.

Titles with whole words such as refactor, architecture, security, migration, concurrency, auth/OAuth raise `isolation`/`model_depth` to `subagent`/`deep` without changing `gate_tier`. Manual overrides are allowed; record the reason in the working notes.

## Context

Work from `unit-begin`'s `text` (the unit's own task: its section of the plan or of a part; for `part-<id>-done`, the part's completion criteria and handoff; for a hand-written part, the whole part file) and `files` (paths from its `Files`/`Inputs`/`Outputs` blocks, with `lines` hints such as `4-6`). Read those files yourself; do not re-read the whole plan for every unit. `lines` describe the file before the plan started; earlier units shift them, so locate the code by the quote in the step, not by the number.

If `files` is empty, search with Grep/Glob for class, function, command or file names from `text`. Do not build or rely on a repo map; keep context local to the unit.
