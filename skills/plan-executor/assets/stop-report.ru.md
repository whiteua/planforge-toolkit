# Отчёт об остановке

## Выполнено

{{completed_units}}

## Остановлено на

Единица: `{{unit_id}}`
Причина: `{{stop_reason}}`
Откат к: `{{restore_to}}`

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

## Как продолжить

Запустите:

```bash
{{resume_command}}
```
