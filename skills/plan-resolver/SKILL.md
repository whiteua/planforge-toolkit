---
name: plan-resolver
description: |
  Read-mostly аудит реализации мастер-плана. Принимает plans-list (мастер-план + прошлые
  отчёты), сверяет фазы/задачи и ранее зафиксированные ошибки с кодом, создаёт ровно один
  новый отчёт <base>-report-<N+1>.md или <base>-report-<N+1>-final.md рядом с мастер-планом.

  Use when: «проверь выполнение плана», «проверка реализации плана», «проверь реализацию
  плана», «resolve plan», «plan resolver», «resolve master plan», «master plan resolver»,
  «сформируй отчёт по плану», «audit plan implementation», «сделай очередной проход по плану».
  Если режим/инструменты не позволяют создать новый отчёт — стоп до аудита.
allowed-tools:
  - Read
  - Grep
  - Glob
  - Write
  - Bash
---

# Plan Resolver

Read-mostly workflow для проверки реализации мастер-плана. Скилл никогда не исправляет код,
мастер-план или прошлые отчёты; единственный writable artefact за один запуск — новый отчёт
`<base>-report-N.md` или `<base>-report-N-final.md` в каталоге мастер-плана.

## Arguments

Пользователь должен явно передать `plans-list`: первый путь — мастер-план, остальные пути —
прошлые отчёты. Скилл не восстанавливает список из attachments автоматически.

Пример:

```text
проверь реализацию плана: docs/main-plan.md docs/main-plan-report-1.md
```

## Read Before Acting

1. [references/WORKFLOW.md](references/WORKFLOW.md) — полный алгоритм и инварианты.
2. [references/BOOTSTRAP.md](references/BOOTSTRAP.md) — разбор `plans-list` и выбор `N+1`.
3. [references/PASS-FIRST.md](references/PASS-FIRST.md) — первый проход без прошлых отчётов.
4. [references/PASS-SUBSEQUENT.md](references/PASS-SUBSEQUENT.md) — повторный проход по прошлому отчёту.
5. [references/REPORT-FORMAT.md](references/REPORT-FORMAT.md) — единственный источник правды по схеме отчёта.
6. [references/STATUS-RULES.md](references/STATUS-RULES.md) и [references/ERROR-TAXONOMY.md](references/ERROR-TAXONOMY.md) — статусы, уровни, переходы.
7. [references/CODE-TRACING.md](references/CODE-TRACING.md), [references/PROBES.md](references/PROBES.md), [references/FINGERPRINT.md](references/FINGERPRINT.md) — безопасная сверка с кодом.
8. [references/TOOLING.md](references/TOOLING.md) — CLI-контракты `scripts/resolver_tool.py`.

## Prerequisites

- Python ≥ 3.8 in PATH (stdlib only).
- `<SKILL_DIR>` is the directory containing this `SKILL.md`. Always invoke the
  script by absolute path: `python "<SKILL_DIR>/scripts/resolver_tool.py" ...`.

## Mandatory Workflow

1. Запустить `python "<SKILL_DIR>/scripts/resolver_tool.py" bootstrap <workspace-root> <plan> [reports...]`.
   Если команда вернула exit `64`, план уже закрыт: сообщить пользователю и ничего не писать.
2. Запустить `preflight <plan-dir> <next-open-name> <next-final-name>`. Если preflight не прошёл,
   остановиться до аудита; не заменять отчёт memory/chat/terminal notes.
3. Создать путь для стартового fingerprint через `tempfile.mkstemp(prefix="fp-", suffix=".json", dir=tempfile.gettempdir())`, закрыть fd, затем вызвать `fingerprint-workspace`.
4. Выполнить один проход аудита: `first` по мастер-плану либо `subsequent` по `LAST_REPORT` + повторный полный скан мастер-плана.
5. Выбрать имя отчёта: `-final`, только если ошибок нет и все задачи `✅` или `not-applicable`; иначе open-имя.
6. Записать ровно один новый отчёт по [references/REPORT-FORMAT.md](references/REPORT-FORMAT.md). Первичная запись — create-new; overwrite существующего файла запрещён.
7. Запустить `validate-report`. Допустим один retry перезаписи того же отчёта, если validator нашёл структурную ошибку.
8. Снять текущий fingerprint и запустить `assert-readonly <start-json> <current-json> <selected-report-path>`. Если найден drift, перезаписать тот же отчёт blocker-ошибкой `probe-mutated-workspace`, заново выполнить только validator и остановиться со статусом `OPEN`.
9. Запустить `iteration-check` для non-final subsequent-проходов и вывести human gate: путь, статус, счётчики, next action.

## Language

Язык отчёта определяется содержимым мастер-плана (конвенция экосистемы plan-*,
см. plan-iterative-revision invariant #9): доля кириллицы среди букв > 5% → `ru`,
иначе `en`. Пустой или нечитаемый план → `ru`. Системная локаль агента и язык
прошлых отчётов роли не играют; конфликт можно отметить в `## Дополнительный контекст`.

## Forbidden Actions

- Не редактировать код, мастер-план, прошлые отчёты, конфиги и generated-файлы.
- Не запускать formatter/autofix/install/update/migration/generator/git-mutating команды.
- Не создавать несколько отчётов за один запуск.
- Не overwrite'ить существующий `NEXT_REPORT`; self-rewrite разрешён только для собственного отчёта текущей инвокации.
- Не сохранять результат аудита в memory/chat/terminal вместо файла.
- Не вызывать другие скиллы как автоматического исполнителя исправлений.
