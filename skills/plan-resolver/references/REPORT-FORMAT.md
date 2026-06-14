# Report Format

Этот файл — источник правды для `main-plan-report-N.md` / `<base>-report-N.md`.
`validate-report` проверяет именно эту структуру.

## Header

Рекомендуемый формат — YAML frontmatter. Все пути POSIX-relative к `PLAN_DIR`.

```yaml
---
master_plan_path: review-plan.md
master_plan_sha256: 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
master_plan_size: 12345
audited_at: 2026-05-10T07:54:08Z
audit_iteration: 1
consecutive_open_invocations: 1
previous_report_path: review-plan-report-1.md
previous_report_sha256: 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
language: ru
---
```

Для первого прохода `previous_report_path: null` и `previous_report_sha256: null`.
Для `-final.md` обязательно `consecutive_open_invocations: 0`.

## Required Sections

Русский отчёт:

```markdown
# Отчет о выполнении плана N

## Основные стадии плана

## Список ошибок

## Дополнительный контекст

## Задача
```

English report:

```markdown
# Plan Implementation Report N

## Plan Stages

## Issues

## Additional Context

## Task
```

`## Дополнительный контекст` / `## Additional Context` опционален, но если секция есть, она не
должна быть пустой.

## Plan Stages

Каждая стадия/задача должна иметь статус:

- `✅` — реализовано полностью;
- `⚠️` — реализовано частично или с ошибками;
- `⭕️` — отсутствует;
- `‼️` — реализовано с отклонением от плана;
- `not-applicable` — пояснительный пункт, не блокирует final.

Пример:

```markdown
- ✅ 1. Bootstrap CLI реализован и проверен
- ⚠️ 2. Readonly guard есть, но drift-сценарий требует доработки
```

### Evidence on closed tasks

Закрытая задача со статусом `✅` и dotted id (`1.2`, `2.3.4`) должна иметь доказательный якорь
`evidence_anchor: path#Lx-Ly`, указывающий на конкретный участок кода или документации.

Пример:

```markdown
- ✅ 1.2 Validate-report проверяет report metadata
    - evidence_anchor: scripts/resolver_tool.py#L120-L168
```

Если `evidence_anchor` отсутствует у закрытой dotted-задачи:

- в промежуточном отчёте валидатор выдаёт `[WARNING] ...`;
- в `*-final.md` валидатор завершает проверку с exit code `1`.

Фазовые строки без dotted id (`1`, `2`, `3`) не требуют собственного `evidence_anchor`, если
доказательства привязаны к закрытым задачам внутри фазы.

### Confidence

У задачи или issue-блока может быть необязательное поле `confidence: high|medium|low`. Отсутствие
поля не является ошибкой.

`confidence: low` означает, что закрытие требует дополнительной проверки:

- в промежуточном отчёте валидатор выдаёт `[WARNING] ...`;
- в `*-final.md` задача со статусом `✅` или issue со статусом `fixed` не могут закрываться с
    `confidence: low`.

### Ambiguous tasks

Если статус задачи нельзя определить уверенно, используйте `⚠️ ambiguous` и обязательно укажите
`evidence_anchor: path#Lx-Ly`.

Пример:

```markdown
- ⚠️ ambiguous 3.4 Поведение edge-case не подтверждено тестом
    - evidence_anchor: tests/test_resolver_tool.py#L210-L236
```

Если тот же task id с тем же `evidence_anchor` уже был отмечен как ambiguous в предыдущем отчёте,
валидатор выдаёт только предупреждение, а не новую ошибку.

## Issue Blocks

Ошибки пишутся в стабильной нумерации от 1:

```markdown
1) Ошибка 1: ⭕️ not-fixed | critical | Короткий заголовок
- **level**: critical
- **status**: ⭕️ not-fixed
- **title**: Короткий заголовок
- **linked_items**: 1.2, 1.3
- **origin**: carry|new
- **evidence**: path/to/file.py#L10-L20
- **description**: Подробное описание минимум 200 символов: симптом, причина, контракт плана,
  фактическое поведение, почему это блокирует или ухудшает реализацию.
- **recommendations**: Конкретные действия для исправления и повторной проверки.
```

Допустимые `level`: `critical`, `high`, `medium`, `low`.
Допустимые `status`: `fixed`, `fixed-with-errors`, `not-fixed`, `regressed`.

Если ошибок нет, секция содержит фразу `Ошибок не найдено.` / `No issues found.` и issue-блоки не
создаются.

## Probe-Needed Marker

`probe-needed` — это внутриблочный маркер необходимости дополнительной проверки, а не статус
стадии, задачи или issue-блока. Он может использоваться внутри описания, рекомендаций или
дополнительных полей блока, но не заменяет допустимые значения `status`.

## Validator Warnings

Если `validate-report` вернул предупреждения, агент переносит точные строки `[WARNING] ...` в
фиксированную секцию отчёта:

- русский отчёт: `## Предупреждения валидатора`;
- English report: `## Validator Warnings`.

Каждое предупреждение сопровождается одной строкой действия: что проверить, исправить или почему
предупреждение допустимо для текущего промежуточного прохода. Если предупреждений нет, секция может
быть опущена.

## Final Report Invariant

Файл `*-final.md` валиден только если:

- все стадии имеют `✅` или `not-applicable`;
- issue-блоков нет либо все они имеют `status: ✅ fixed`;
- `consecutive_open_invocations: 0`.
