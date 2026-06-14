# Отчёт об остановке

## Выполнено

{{completed_units}}

## Остановлено на

Единица: `{{unit_id}}`
Чекпоинт: `{{checkpoint_id}}`

## Последняя ошибка

{{last_error}}

## Последний diff

```diff
{{last_diff}}
```

## Как откатиться

Используйте checkpoint `{{checkpoint_id}}`, если доступен git-откат, или выполните ручной откат в step mode.

## Как продолжить

Запустите:

```bash
{{resume_command}}
```
