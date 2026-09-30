# Report Format

The source of truth for `<base>-report-N.md` / `<base>-report-N-final.md`; `validate-report`
checks exactly this structure. Templates: `assets/report-template.{ru,en}.md`.

## Header

YAML frontmatter; paths POSIX-relative to `PLAN_DIR`; values copied from `bootstrap.report_header`.

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
---
```

A `-final.md` report has `consecutive_open_invocations: 0`.

## Sections

| Russian report | English report | Required |
|---|---|---|
| `# Отчет о выполнении плана N` (`Отчёт` accepted) | `# Plan Implementation Report N` | yes |
| `## Основные стадии плана` | `## Plan Stages` | yes |
| `## Список ошибок` | `## Issues` | yes |
| `## Дополнительный контекст` | `## Additional Context` | optional, never empty |
| `## Задача` | `## Task` | yes |
| `## Предупреждения валидатора` | `## Validator Warnings` | when the validator warned |
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

- Task ids are `<phase>.<n>`; phase lines carry the phase number. `plan-splitter` part ids
  (`a`, `b`) are written as `- ✅ a: Title`.
- Every closed leaf (`✅` task, or `✅` phase without tasks of its own) needs an
  `evidence_anchor: path#Lx-Ly` (inline or on an indented detail line). Missing anchor: warning in
  an open report, error in `-final`. With `--root`, every anchor on `✅`/`⚠️` items and in issue
  `evidence` must point at an existing file and line range; otherwise the report is invalid.
- `⚠️ ambiguous` always needs an anchor; the same task with the same anchor as in the previous
  report is a `[WARNING] … stuck in ambiguous`.
- Optional `confidence: high|medium|low`. `low` on a `✅` task or a `fixed` issue: warning in an
  open report, error in `-final`.
- Propagation: a task takes its worst linked result; an open `critical`/`high` issue or missing or
  contradictory evidence forbids `✅`; `not-applicable` is ignored for closure.

## Issue blocks

Numbered from 1, stable across the report:

```markdown
1) Ошибка 1: ⭕️ not-fixed | critical | Short title        (English: "1) Error 1: …")
- **level**: critical
- **status**: ⭕️ not-fixed
- **title**: Short title
- **linked_items**: 1.2, 1.3
- **origin**: carry|new
- **evidence**: path/to/file.py#L10-L20
- **description**: at least 200 characters: symptom, cause, plan contract, actual behaviour, impact.
- **recommendations**: concrete actions to fix and to re-verify.
```

`level`: `critical`, `high`, `medium`, `low`. `status`: `✅ fixed`, `⚠️ fixed-with-errors`,
`⭕️ not-fixed`, `⚠️ regressed`. No issues: the section contains `Ошибок не найдено.` /
`No issues found.` and no blocks. `probe-needed` is a marker inside a block, never a status.

## Validator warnings

Copy each `[WARNING] …` line from `validate-report` verbatim into the warnings section, each with
one line of action (what to check or fix, or why it is acceptable for this open pass).

## Fix Log

Written only by `mark-fix`, only in the report a FIX phase worked from:

```markdown
- Ошибка 2: applied | files: src/app.py | note: empty-input check added
```

States: `applied`, `needs-user`, `skipped`. The validator ignores this section.

## Final report

`*-final.md` is valid only when every stage is `✅` or `not-applicable`, every issue (if any) is
`✅ fixed`, every closed leaf has an anchor, and `consecutive_open_invocations` is `0`.
