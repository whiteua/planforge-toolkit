# INPUT-DETECTION

## Staged vs Whole

Use `detect-input <plan_path>`.

- `staged`: a sibling `*-stg00-roadmap.md` exists. Use `parse-roadmap` to get units, dependencies, parallel groups, and weights.
- `whole`: no roadmap exists. Use `parse-tasks` to extract task-like headings from the plan.

Pass `--whole` to force whole-plan mode even when a matching `<stem>-stg00-roadmap.md` exists.

The executor does not modify the source plan or stage markdown files.

## Unstructured Plan Protocol

If `parse-tasks` returns an empty `units` list:

**With `--whole`:** A single unit `{id: "whole", title: <H1 or filename stem>, weight: "yellow"}` is synthesized automatically. No agent action required — `ledger-init` handles this transparently. The executor continues in the normal EXECUTE LOOP.

**Without `--whole`:** STOP. Do not invent hidden tasks from prose and do not infer order by intuition: **не угадывать** структуру.

Offer the engineer two options:

1. Run `plan-splitter` and come back with staged files.
2. Confirm an explicit task breakdown before ledger creation (then re-run `ledger-init` with `--whole` to use the whole-plan fallback, or add `## Task N: title` headings to the plan).

Only after confirmation may a whole-plan ledger be initialized.

## Accepted heading formats

`parse-tasks` recognizes headings of the form:

```
## <keyword> <id> <separator> <title>
```

- **Keywords (case-insensitive):** `Task`, `Step`, `Phase`, `Stage`, `Задача`, `Шаг`, `Фаза`, `Этап`
- **Separators:** `:` (colon), `.` (period), `-` (hyphen), `—` (em-dash)
- **Heading depth:** `##`, `###`, or `####`

Examples that all produce a unit:
- `## Task 1: Implement feature`
- `## Step 2 — Add types`
- `### Phase 3. Refactor`
- `#### Этап 4 - Написать тесты`
