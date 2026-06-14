# INPUT-DETECTION

## Staged vs Whole

Use `detect-input <plan_path>`.

- `staged`: a sibling `*-stg00-roadmap.md` exists. Use `parse-roadmap` to get units, dependencies, parallel groups, and weights.
- `whole`: no roadmap exists. Use `parse-tasks` to extract task-like headings from the plan.

Pass `--whole` to force whole-plan mode even when a matching `<stem>-stg00-roadmap.md` exists.

The executor does not modify the source plan or stage markdown files.

## Unstructured Plan Protocol

If `parse-tasks` returns an empty `units` list, STOP. Do not invent hidden tasks from prose and do not infer order by intuition: **не угадывать** структуру.

Offer the engineer two options:

1. Run `plan-splitter` and come back with staged files.
2. Confirm an explicit task breakdown before ledger creation.

Only after confirmation may a whole-plan ledger be initialized.
