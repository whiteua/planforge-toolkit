# INPUT-DETECTION

## Staged vs Whole

`ledger-init` calls `detect-input` itself:

- `staged`: the input is `*-roadmap.md` or a sibling `<stem>-roadmap.md` exists. Units, dependencies, groups and weights come from the roadmap table; each unit's text is its part file `<base>-<id>.md`, where `<id>` is the part letter from the table (`a`, `b`, … `aa`; other ids are `invalid-stage-id`, exit 2). Ids and dependencies are lower-cased; dependencies may be comma- or space-separated. A dependency on a part missing from the table is `unknown-dependency` (exit 2). The drift fingerprint covers the roadmap and every part file.
- `whole`: no roadmap. Units come from task headings (below); each unit's text is its section of the plan.

`--whole` forces whole-plan mode even when a roadmap exists. The executor never modifies the plan or stage files.

## Task headings

```
<##|###|####> <keyword> <id> <separator> <title>
```

- Keywords (case-insensitive): `Task`, `Step`, `Phase`, `Stage`, `Задача`, `Шаг`, `Фаза`, `Этап`.
- Separators: `:`, `-`, `—`, or `. ` (period + space).
- Headings inside fenced code blocks are ignored.

If the plan has at least one `Task`/`Задача` heading, only those become units (`task-<id>`); `Phase`/`Stage` headings set their `parallel_group` and `Step` headings are ignored. Otherwise every recognised heading is a unit. Duplicate ids are `duplicate-unit-id` (exit 2).

`plan-writing` plans: `### Task N: <title>` headings; a checkpoint is an ordinary task `### Task N: Checkpoint — <what it proves>`. The `**Tier:**` header sets the unit weight: Quick → green, Standard → yellow, Deep → red (yellow when absent).

## No task headings

- Without `--whole`: `no-units` (exit 2), no ledger is written. STOP; do not invent tasks from prose. Offer the engineer: run `plan-splitter`, add `## Task N: title` headings, or re-run with `--whole`.
- With `--whole`: one unit `whole` is created (title from the H1 or the file name) and the loop continues normally.
