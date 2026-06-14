# EXECUTION-STRATEGY

## One Diagnosis Three Params

Run `recommend-strategy <weight> --task-text <text>` per unit. The result has one coordinated decision:

- `isolation`: `main` or `subagent`
- `model_depth`: `light`, `medium`, or `deep`
- `gate_tier`: `green`, `yellow`, or `red`

Manual overrides are allowed, but record the reason in the working notes before execution.

## Context Scoping

Run `scope-context <stage_path>` for staged work. The command returns paths mentioned in Inputs, Outputs, or Files sections. The tool returns paths only; the agent reads the files itself and keeps source plan markdown read-only.

## Empty Scope Fallback

If `scope-context` returns no paths, use `Grep/Glob` searches for class, function, command, file, or feature names from the unit text. Do not build or rely on a Repo Map; keep context local to the unit.
