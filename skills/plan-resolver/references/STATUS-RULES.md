# Status Rules

Семантика статусов и их вывод. Форматные гейты (`evidence_anchor`, `confidence`, `⚠️ ambiguous`,
что из них warning, а что exit 1) определены только в [REPORT-FORMAT.md](REPORT-FORMAT.md).

## Task Statuses

| Marker | Canonical | Meaning | Final-blocking |
|---|---|---|---|
| `✅` | `verified` / `fully-implemented` | Контракт реализован полностью | no |
| `⚠️` | `partial` / `implemented-with-errors` | Реализовано частично или с дефектами | yes |
| `⭕️` | `missing` | Реализации нет | yes |
| `‼️` | `deviates` | Реализация противоречит плану | yes |
| `not-applicable` | `not-applicable` | Пояснительный пункт без реализации | no |

`ambiguous` — незакрывающее состояние: кодовый путь найден, но реализацию нельзя уверенно
классифицировать. Отображается как `⚠️ ambiguous`.

## Issue Statuses

| Marker | Canonical | Meaning |
|---|---|---|
| `✅` | `fixed` | Ошибка устранена |
| `⚠️` | `fixed-with-errors` | Устранена частично или с побочными дефектами |
| `⭕️` | `not-fixed` | Не исправлена |
| `⚠️` | `regressed` | Была закрыта, но снова проявилась |

## Propagation

- Статус задачи определяется худшим связанным результатом.
- Если у задачи есть open issue level `critical` или `high`, задача не может быть `✅`.
- Если evidence отсутствует или противоречив, задача не может быть `✅`.
- `not-applicable` не участвует в расчёте закрытия плана.
- Final report допустим только когда все задачи `✅`/`not-applicable`, а все issue-блоки `✅ fixed`.

## Self-Consistency

Для блокирующих вердиктов (`✅` на critical-задаче, `⭕️`, `‼️`) агент один раз пере-выводит
вердикт из того же evidence. Расхождение понижает задачу до `⚠️ ambiguous`. Перед следующим
проходом агент усиливает или заменяет evidence, иначе тот же якорь снова даст спорный результат.

Неразрешённую ссылку плана можно фиксировать как `AMBIGUOUS_REFERENCE`: агент не сканирует весь
план в поиске похожих совпадений, а явно отмечает неоднозначность и возвращается к ближайшему
проверяемому якорю.

## Stuck Open

`consecutive_open_invocations` — число открытых отчётов подряд (значение готово в
`bootstrap.report_header`); `iteration-check` поднимает `ask_required` при достижении лимита.
В режимах `fix`/`next`/`auto` застревание определяет `cycle-check` (см. [FIX-LOOP.md](FIX-LOOP.md)).

## Evidence Strengthening

Паттерны усиления evidence при расхождении:

- добавить ready read-only probe (тест/type-check) и записать exit-code;
- расширить якорь с одной строки до блока функции (`path#Lx-Ly` → весь метод);
- добавить cross-reference на тестовый файл, покрывающий контракт.
