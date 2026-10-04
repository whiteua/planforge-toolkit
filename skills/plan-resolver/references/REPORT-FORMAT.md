# Report Format

The source of truth for `<base>-report-N.md` / `<base>-report-N-final.md`; `validate-report`
checks exactly this structure. Templates: `assets/report-template.{ru,en}.md`.

## Header

YAML frontmatter; paths POSIX-relative to `PLAN_DIR`; values copied from `bootstrap.report_header`
(including `audited_at`; `consecutive_open_invocations` takes the `_if_open` or `_if_final` value).

```yaml
---
master_plan_path: review-plan.md
master_plan_sha256: <64 hex>
master_plan_size: 12345
audited_at: 2026-05-10T07:54:08Z
audit_iteration: 1
consecutive_open_invocations: 1
previous_report_path: review-plan-report-1.md      # null on the first pass
previous_report_sha256: <64 hex>                    # null on the first pass
language: ru
audit_scope: full                                   # incremental: written by carry-forward
audit_tasks: all                                    # incremental: [7, 8, 12, 12.1, 40]
---
```

A `-final.md` report has `consecutive_open_invocations: 0`.

`audit_scope` (`full` | `incremental`) and `audit_tasks` (`all`, or the plan's task ids the pass
re-audited) say what the pass read; plan-chain-runner's `run-stats` reads them for its reads model.
A report without them (older than this format) is read as `full`, with a warning, and so is
`incremental` without `audit_tasks`. With `--plan` every id of `audit_tasks` must be a task of the
plan. A `-final.md` report needs `audit_scope: full`.

## Sections

| Russian report | English report | Required |
|---|---|---|
| `# Отчет о выполнении плана N` (`Отчёт` accepted) | `# Plan Implementation Report N` | yes |
| `## Основные стадии плана` | `## Plan Stages` | yes |
| `## Список ошибок` | `## Issues` | yes |
| `## Дополнительный контекст` | `## Additional Context` | optional, never empty |
| `## Задача` | `## Task` | yes |
| `## Предупреждения валидатора` | `## Validator Warnings` | when the validator warned |
| `## Отпечаток улик` | `## Evidence fingerprint` | written only by `evidence-fingerprint` |
| `## Журнал исправлений` | `## Fix Log` | written only by `mark-fix` |

## Plan stages

One line per phase or task with a status marker:

| Marker | Meaning | Closes the plan |
|---|---|---|
| `✅` | implemented as specified | yes |
| `⚠️` | partial, defective, or `⚠️ ambiguous` (code found, cannot classify) | no |
| `⭕️` | missing | no |
| `‼️` | deviates from the plan | no |
| `not-applicable` | explanatory item, no code needed | ignored |

```markdown
- ✅ 1. Bootstrap CLI implemented evidence_anchor: scripts/cli.py#L1-L40
- ⚠️ 2. Readonly guard exists, drift scenario incomplete
  - ✅ 2.1 Start fingerprint evidence_anchor: scripts/cli.py#L120-L168
  - ⚠️ ambiguous 2.2 Drift path not covered by a test
    - evidence_anchor: tests/test_cli.py#L210-L236
```

Rules:

- Ids are the plan's own ids. A `plan-writing` plan (`### Task 1:`, `### Task 1.1:`) gives
  `- ✅ 1. Title evidence_anchor: …` and `- ✅ 1.1 Title evidence_anchor: …`; a plan with phases
  and nested items gives phase lines (`1`) with tasks `<phase>.<n>` under them. `plan-splitter` part ids
  (`a`, `b`) are written as `- ✅ a: Title`.
- Every closed leaf (`✅` task, or `✅` phase without tasks of its own) needs an
  `evidence_anchor: path#Lx-Ly` (inline or on an indented detail line; several anchors are
  fine). Missing anchor: warning in an open report, error in `-final`. With `--root`, every anchor
  on `✅`/`⚠️` items and in issue `evidence` must point at an existing file and line range;
  otherwise the report is invalid. `evidence: not found` has no anchor and is not checked.
- A task that leaves no code (a checkpoint, a manual verification) is closed with
  `evidence_probe: <command> → <exit code or observed result>` instead of an anchor. With `--plan`,
  a task whose plan `Files` block has `Create:`/`Modify:` cannot be closed by a probe alone.
- A task the audit could not re-verify (it needs an external system) carries
  `verification: executor-reported` next to its evidence. The validator lists such tasks in a
  `[WARNING]` and in `summary.executor_reported`; the human gate names them.
- `⚠️ ambiguous` always needs an anchor; the same task with the same anchor as in the previous
  report is a `[WARNING] … stuck in ambiguous`.
- Optional `confidence: high|medium|low`. `low` on a `✅` task or a `fixed` issue: warning in an
  open report, error in `-final`.
- Propagation: a task takes its worst linked result; an open `critical`/`high` issue or missing or
  contradictory evidence forbids `✅`; `not-applicable` is ignored for closure.
- A stub `- <id>. <title> <!-- reaudit -->` (written by `carry-forward`) has no marker yet: the
  incremental pass replaces it with the task's line. A stub left in the report is an error
  (`unfilled placeholder`), and so is `<!-- re-verify -->` left on an issue's head line.

## Issue blocks

Numbered from 1, stable across the report:

```markdown
1) Ошибка 1: ⭕️ not-fixed | critical | Short title        (English: "1) Error 1: …")
- **level**: critical
- **status**: ⭕️ not-fixed
- **title**: Short title
- **linked_items**: 1.2, 1.3
- **origin**: carry|new
- **category**: logic            (optional; one of the AUDIT.md categories)
- **evidence**: path/to/file.py#L10-L20      (or `not found` when the code does not exist)
- **description**: at least 200 characters: symptom, cause, plan contract, actual behaviour, impact.
- **recommendations**: concrete actions to fix and to re-verify.
```

One issue per defect that needs its own fix (a wrong branch and a missing test are two issues).
A carry-over issue keeps its title, description and evidence field verbatim, also when it is now
`✅ fixed`; its recommendations become what was verified.

`level`: `critical`, `high`, `medium`, `low`. `status`: `✅ fixed`, `⚠️ fixed-with-errors`,
`⭕️ not-fixed`, `⚠️ regressed`. No issues: the section contains `Ошибок не найдено.` /
`No issues found.` and no blocks. `probe-needed` is a marker inside a block, never a status.

## Validator warnings

Copy each `[WARNING] …` line from `validate-report` verbatim into the warnings section, each with
one line of action (what to check or fix, or why it is acceptable for this open pass).

## Evidence fingerprint

Written only by `evidence-fingerprint` ([WORKFLOW.md](WORKFLOW.md)), before the Fix Log or at the
end; the templates end with the placeholder `{{evidence_fingerprint}}`, which the command replaces:

```markdown
## Evidence fingerprint

| File | SHA-256 |
|---|---|
| skills/x/scripts/tool.py | <64 hex> |
| BACKLOG.md | excluded |
```

One row per evidence file: the anchors of the stages section and of issue `evidence`, and the files
of the plan tasks' `Files` blocks. The value is the file's SHA-256 at the start of the audit,
`excluded` (outside the snapshot) or `missing` (an anchored file that does not exist); any other
row is an error. The next pass compares the table with its own start snapshot (`rescan-scope`).

## Fix Log

Written only by `mark-fix`, only in the report a FIX phase worked from:

```markdown
- Ошибка 2: applied | files: src/app.py | note: empty-input check added
```

States: `applied`, `needs-user`, `skipped`. The validator ignores this section.

## Final report

`*-final.md` is valid only when every stage is `✅` or `not-applicable`, every issue (if any) is
`✅ fixed`, every closed leaf has an anchor, `consecutive_open_invocations` is `0`, and
`audit_scope` is `full` (or absent in an older report).
