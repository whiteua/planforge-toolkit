# EXECUTION-STRATEGY

## One Diagnosis, Three Params

`unit-begin` returns `strategy` for the unit, derived from its weight and title:

- `isolation`: `main` or `subagent`
- `model_depth`: `light`, `medium`, or `deep`
- `gate_tier`: `green`, `yellow`, or `red` (see `GATE.md`)

Titles with whole words such as refactor, architecture, security, migration, concurrency, auth/OAuth raise `isolation`/`model_depth` to `subagent`/`deep` without changing `gate_tier`. Manual overrides are allowed; record the reason in the working notes.

## Context

Work from `unit-begin`'s `text` (the unit's own section or stage file) and `files` (paths from its `Files`/`Inputs`/`Outputs` blocks, with `lines` hints such as `4-6`). Read those files yourself; do not re-read the whole plan for every unit.

If `files` is empty, search with Grep/Glob for class, function, command or file names from `text`. Do not build or rely on a repo map; keep context local to the unit.
