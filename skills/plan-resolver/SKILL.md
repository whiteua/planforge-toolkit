---
name: plan-resolver
description: |
  Audit plan implementation against the codebase. Cross-checks phases, tasks, and previously
  reported issues with actual code, then produces a single structured report file alongside
  the master plan. With `fix`/`next` it repairs the code from the last open report and re-audits;
  with `auto` it loops audit → fix → audit until the plan closes or the cycle limit is hit.
allowed-tools:
  - Read
  - Grep
  - Glob
  - Write
  - Edit
  - Bash
---

# Plan Resolver

Проверка реализации мастер-плана по коду. Фаза AUDIT — read-mostly: не меняет код, мастер-план
и прошлые отчёты, пишет ровно один новый отчёт `<base>-report-N.md` или `<base>-report-N-final.md`
в каталоге мастер-плана. Фаза FIX (только режимы `fix`/`next`/`auto`) исправляет **код** по
открытому отчёту; мастер-план не меняется никогда.

## Modes

Режим — последний аргумент, если он равен `fix`, `next` или `auto` (у `auto` может быть число —
лимит циклов, по умолчанию `2`).

| Вызов | Режим |
|---|---|
| `<plan> [reports...]` | **audit** — один проход аудита, как раньше |
| `[<plan>] fix` / `[<plan>] next` | один цикл FIX → AUDIT, затем стоп |
| `<plan> auto [limit]` | AUDIT → FIX → AUDIT … до `-final` или лимита |

В режиме audit `plans-list` передаётся явно: первый путь — мастер-план, остальные — прошлые
отчёты. В `fix`/`next`/`auto` список строит `discover` (см. [references/FIX-LOOP.md](references/FIX-LOOP.md)).

```text
/plan-resolver docs/plan-impl.md docs/plan-impl-report-1.md
/plan-resolver docs/plan-impl.md fix
/plan-resolver docs/plan-impl.md auto
```

## Read Before Acting

Читать только то, что нужно текущей фазе:

| Когда | Файлы |
|---|---|
| Всегда (AUDIT) | [WORKFLOW.md](references/WORKFLOW.md), [REPORT-FORMAT.md](references/REPORT-FORMAT.md), [STATUS-RULES.md](references/STATUS-RULES.md) |
| `pass_type == first` | [PASS-FIRST.md](references/PASS-FIRST.md), [CODE-TRACING.md](references/CODE-TRACING.md) |
| `pass_type == subsequent` | [PASS-SUBSEQUENT.md](references/PASS-SUBSEQUENT.md), [CODE-TRACING.md](references/CODE-TRACING.md) |
| Нужна проба / выбор level | [PROBES.md](references/PROBES.md), [ERROR-TAXONOMY.md](references/ERROR-TAXONOMY.md) |
| Режимы `fix`/`next`/`auto` | [FIX-LOOP.md](references/FIX-LOOP.md) |
| Ошибка CLI, неясный exit code | [TOOLING.md](references/TOOLING.md), [BOOTSTRAP.md](references/BOOTSTRAP.md), [FINGERPRINT.md](references/FINGERPRINT.md) |

## Prerequisites

- Python ≥ 3.8 in PATH (stdlib only).
- `<SKILL_DIR>` is the directory containing this `SKILL.md`. Always invoke the
  script by absolute path: `python "<SKILL_DIR>/scripts/resolver_tool.py" ...`.

## AUDIT Phase

1. `bootstrap <workspace-root> <plan> [reports...]`. Exit `64` — план уже закрыт: сообщить и
   ничего не писать. Поля `report_header` использовать для frontmatter отчёта как есть.
2. `preflight <plan-dir> <next-open-name> <next-final-name>`. Не прошёл — остановиться до аудита;
   не заменять отчёт memory/chat/terminal notes.
3. Путь для стартового fingerprint: `tempfile.mkstemp(prefix="fp-", suffix=".json", dir=tempfile.gettempdir())`, закрыть fd, вызвать `fingerprint-workspace`.
4. Один проход аудита: `first` по мастер-плану либо `subsequent` по `LAST_REPORT` + полный
   повторный скан мастер-плана.
5. Имя отчёта: `-final` только если ошибок нет и все задачи `✅`/`not-applicable`
   (`consecutive_open_invocations: 0`); иначе open-имя
   (`consecutive_open_invocations_if_open`).
6. Записать ровно один новый отчёт (create-new, overwrite запрещён).
7. `task-census <plan> <report>`: exit `1` — дописать непокрытые задачи в тот же отчёт.
8. `validate-report <report>`: допустим один retry перезаписи того же отчёта; `[WARNING]`
   переносить в секцию предупреждений.
9. Текущий fingerprint (`--base <start-json>` — перехешируются только изменённые по size/mtime файлы) + `assert-readonly <start-json> <current-json> <report>`. Drift →
   перезаписать тот же отчёт blocker-ошибкой `probe-mutated-workspace`, повторить только
   validator и остановиться со статусом `OPEN`.
10. Для non-final subsequent-прохода — `iteration-check`. Вывести human gate: путь, статус,
    счётчики, next action (в режиме audit с открытыми ошибками предложить `/plan-resolver <plan> fix`).

## FIX Phase

Только в режимах `fix`/`next`/`auto`, строго по [references/FIX-LOOP.md](references/FIX-LOOP.md):
`open-issues` → защита плана и отчётов (`protect`) → минимальные правки кода по `fix_order` →
`assert-protected` → `mark-fix` для каждой ошибки → AUDIT → `cycle-check`.

## Language

Язык отчёта определяется содержимым мастер-плана (конвенция экосистемы plan-*,
см. `detect_lang` в plan-iterative-revision/scripts/next_review_index.py): доля кириллицы среди букв > 5% → `ru`,
иначе `en`. Пустой или нечитаемый план → `en`. Значение готово в `bootstrap.language`.

## Forbidden Actions

- Никогда не редактировать мастер-план.
- Прошлые отчёты: менять только секцию журнала исправлений и только через `mark-fix`.
- В фазе AUDIT не редактировать код, конфиги и generated-файлы; не создавать несколько отчётов;
  не overwrite'ить существующий `NEXT_REPORT` (self-rewrite — только собственного отчёта текущего прохода).
- Ни в одной фазе: git-мутации, install/update зависимостей, миграции, formatter/autofix по всему проекту.
- Не сохранять результат аудита в memory/chat/terminal вместо файла.
- Не вызывать другие скиллы как исполнителя исправлений.
