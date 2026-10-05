# Отчёт об остановке

## Выполнено

{{completed_units}}

## Остановлено на

Единица: `{{unit_id}}`
Причина: `{{stop_reason}}`
Откат к: `{{restore_to}}`
Делегирование: {{delegated}}

## Последняя ошибка

{{last_error}}

## Последний diff

```text
{{diff_stat}}
```

```diff
{{diff_excerpt}}
```

## Как откатиться

После подтверждения: `executor_tool.py checkpoint-restore <repo> {{restore_to}}`. Без git откатитесь вручную.

## Журнал цепочки

Открытый вопрос `{{question_id}}` в `{{journal_path}}`: {{question_text}}

Ответьте командой `brainstorm_tool.py journal-answer {{journal_path}} {{question_id}} --answer "<ответ>"`, затем продолжите. Дефекты вне плана: `{{followups_path}}`.

## Как продолжить

Запустите:

```bash
{{resume_command}}
```
