# Workflow

Фаза AUDIT `plan-resolver` — один read-mostly проход аудита реализации мастер-плана, который
создаёт ровно один новый отчёт рядом с мастер-планом. Режимы `fix`/`next`/`auto` оборачивают
этот проход циклом исправлений по [FIX-LOOP.md](FIX-LOOP.md); инварианты ниже относятся к
каждому проходу AUDIT.

## Inputs

- `plans-list`: явный список путей, где первый элемент — MASTER_PLAN, остальные — прошлые отчёты.
- `WORKSPACE_ROOT`: текущий cwd агента/VS Code, передаётся в CLI `bootstrap`.

## Invariants

1. Writable-файл ровно один: выбранный `NEXT_REPORT`.
2. MASTER_PLAN и REPORTS[] read-only.
3. Код проекта read-only; допустимы только чтение, grep/glob и безопасные read-only probes.
4. Preflight обязателен до аудита.
5. Start/current fingerprint обязателен; допустимый diff — только выбранный `NEXT_REPORT`.
6. Один проход AUDIT = один отчёт; исправления кода внутри AUDIT запрещены (они — отдельная фаза FIX).
7. Report schema берётся только из [REPORT-FORMAT.md](REPORT-FORMAT.md).
8. Язык отчёта берётся из `bootstrap.language` (доля кириллицы в мастер-плане > 5% → `ru`, иначе `en`; пустой план → `ru`).
9. `task-census` обязателен перед сдачей: непокрытая задача (exit 1) блокирует отчёт. Все строки
	`[WARNING] …` из `validate-report` дословно отражаются в секции «Предупреждения валидатора».

## Command Sequence

```text
bootstrap <workspace-root> <plan> [reports...]
preflight <plan-dir> <next-open-name> <next-final-name>
fingerprint-workspace <workspace-root> <start-json>
# audit pass: first/subsequent
# write selected NEXT_REPORT
task-census <plan> <selected-report>
validate-report <selected-report>
fingerprint-workspace <workspace-root> <current-json> --base <start-json>
assert-readonly <start-json> <current-json> <selected-report-path>
iteration-check <last-report> 5   # only when applicable
```

## First Pass

Если прошлых отчётов нет, агент читает MASTER_PLAN, перечисляет фазы/задачи, сопоставляет их с
кодом и формирует первичный список ошибок. Каждая задача получает статус из
[STATUS-RULES.md](STATUS-RULES.md), каждая ошибка — level/status из
[ERROR-TAXONOMY.md](ERROR-TAXONOMY.md).

## Subsequent Pass

Если есть LAST_REPORT, агент сначала переоценивает старые ошибки, затем повторно сканирует весь
MASTER_PLAN по текущему коду. Итоговый список строится стабильно: carry-over ошибки в старом
порядке, затем новые ошибки в порядке обнаружения.

## Report Name

`<base>-report-N-final.md` выбирается только если итоговый список ошибок пуст и все задачи закрыты
(`✅` или `not-applicable`). Во всех остальных случаях используется `<base>-report-N.md`.

## Drift Handling

Если `assert-readonly` обнаружил изменения кроме `NEXT_REPORT`, агент добавляет в тот же отчёт
единственную blocker-ошибку `probe-mutated-workspace`, повторно запускает только validator и
останавливается со статусом `OPEN`. Повторный readonly-guard в этой инвокации запрещён.
