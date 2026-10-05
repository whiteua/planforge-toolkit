# INPUT-DETECTION

## Staged vs Whole

`ledger-init` calls `detect-input` itself:

- `staged`: the input is a split roadmap `*-roadmap.md` (from `plan-splitter`) or a sibling `<stem>-roadmap.md` of that kind exists. A roadmap with `> Goal:` among its first ten lines is the goal roadmap of `plan-brainstorming`, not a split roadmap: as the input `detect-input`, `parse-roadmap` and `ledger-init` answer `not-a-split-roadmap` (exit 2; the run is started by `/plan-chain-runner <file>`), and a sibling one does not make the plan `staged`. Parts, their dependencies, groups and weights come from the roadmap table; each part is the file `<base>-<id>.md`, where `<id>` is the part letter from the table (`a`, `b`, … `aa`; other ids are `invalid-stage-id`, exit 2). Ids and dependencies are lower-cased; dependencies may be comma- or space-separated. A dependency on a part missing from the table is `unknown-dependency` (exit 2). Inside each part, in table order, its `### Task N:` headings are the units (`task-<id>`, by the shared parser; `source` = the part file and the task's lines, `part` = the part id, `parallel_group` = the part's group, weight by the task and the master plan's `**Tier:**`), followed by a checkpoint unit `part-<id>-done` (green; its text is the part's `## Completion criteria` and `## Outputs (handoff)`; without them its title says what to check and `ledger-init` warns `part-without-criteria`). The first task of a part depends on the checkpoints of the parts in its `Depends on`, every other unit on the one before it. A part without task headings (written by hand) stays one unit `<id>` with its whole file as text and the warning `part-without-tasks`. One task id in two parts is `duplicate-unit-id` (exit 2). The drift fingerprint covers the roadmap and every part file; a ledger from before task units (units `a`, `b`) resumes as it is; accepting drift on such a ledger rebuilds its units as tasks (`removed`: the part ids, `added`: the task ids) and every task starts `pending`, so finish the old run before changing a part file.
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
