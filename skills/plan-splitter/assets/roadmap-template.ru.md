# Roadmap: {{PLAN_TITLE}}

> Источник: [{{BASE_NAME}}.md](./{{BASE_NAME}}.md)
> Сгенерировано: {{ISO8601_UTC}}
> Частей: {{N}}

## Обзор

{{OVERVIEW}}

## Граф зависимостей

| Стадия | Название | Зависит от | Параллельная группа | Вес |
|--------|----------|------------|---------------------|-----|
{{TABLE_ROWS}}

### Параллельные группы

{{GROUP_LINES}}

### Визуализация (Mermaid)

```mermaid
graph LR
{{MERMAID_EDGES}}
```

## Стадии

{{STAGE_SECTIONS}}

<!-- item:row -->
| {{ID}} | {{TITLE}} | {{DEPENDS}} | {{GROUP}} | {{WEIGHT}} |
<!-- /item -->
<!-- item:group -->
- **Группа {{GROUP}}**: {{MEMBERS}}
<!-- /item -->
<!-- item:stage -->
### {{ID}}: {{TITLE}}
- **Файл**: [{{BASE_NAME}}-{{ID}}.md](./{{BASE_NAME}}-{{ID}}.md)
- **Зависит от**: {{DEPENDS}}
- **Блокирует**: {{BLOCKS}}
- **Вес**: {{WEIGHT}}
- **Краткое содержание**: {{SUMMARY}}
<!-- /item -->
