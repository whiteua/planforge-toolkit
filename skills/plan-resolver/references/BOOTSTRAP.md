# Bootstrap

`bootstrap` валидирует `plans-list`, вычисляет следующий номер отчёта и возвращает JSON для
остального workflow.

## Path Rules

- Все пути должны находиться внутри `WORKSPACE_ROOT` (`os.path.commonpath`).
- MASTER_PLAN допускает расширения `.md`, `.markdown`, `.txt`, `.text`.
- Отчёты должны называться `<base>-report-<N>.md` или `<base>-report-<N>-final.md`.
- `<base>` отчёта обязан совпадать с именем MASTER_PLAN без расширения.
- Отчёты должны лежать в `PLAN_DIR`.

## Numbering

Нумерация отчётов непрерывная: при наличии `report-3` без `report-2` команда возвращает ошибку
`bootstrap-gap-in-reports`. Дубликаты номера дают `bootstrap-duplicate-report`.

## Closed Plan

Если последний отчёт имеет suffix `-final.md`, `bootstrap` возвращает exit `64` и `closed: true`.
Скилл останавливается без записи.

## Language

Язык отчёта определяется содержимым MASTER_PLAN: доля кириллицы среди букв > 5% → `ru`,
иначе `en`; пустой или нечитаемый план → `en`. Системная локаль не учитывается.

## Output Fields

Ключевые поля успешного ответа:

- `master_plan`, `master_plan_abs`, `master_plan_sha256`, `master_plan_size`;
- `plan_dir`, `plan_dir_abs`;
- `reports`, `last_report`;
- `next_n`, `next_open_name`, `next_final_name`, `next_open_path`, `next_final_path`;
- `language`, `pass_type`;
- `report_header` — готовые значения frontmatter нового отчёта: `master_plan_path` (относительно
  `PLAN_DIR`), `master_plan_sha256`, `master_plan_size`, `audit_iteration`,
  `consecutive_open_invocations_if_open` / `_if_final`, `previous_report_path`,
  `previous_report_sha256` (`null` на первом проходе), `language`. Агент копирует их, а не
  вычисляет заново.
