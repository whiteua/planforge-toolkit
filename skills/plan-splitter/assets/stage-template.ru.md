# Стадия {{ID}}: {{TITLE}}

> Источник: [{{BASE_NAME}}.md](./{{BASE_NAME}}.md)
> Roadmap: [{{BASE_NAME}}-roadmap.md](./{{BASE_NAME}}-roadmap.md)
> Зависит от: {{DEPENDS_ON_OR_DASH}}
> Блокирует: {{BLOCKS_OR_DASH}}
> Вес: {{WEIGHT}}

## Цель

{{GOAL}}

## Входные данные

{{INPUTS}}

Контекст исходного плана (шапка, дословно):

{{PLAN_HEADER}}

## Задачи

{{TASK_LIST}}

Выполнять строго по порядку. Полный текст каждой задачи (Files, Preconditions, Postconditions, шаги, команды и ожидаемый вывод) — ниже, дословно из исходного плана.

{{TASK_BODIES}}

## Критерии завершения

{{CRITERIA}}

## Выходные данные (handoff)

{{OUTPUTS}}

## Примечания

{{NOTES}}

<!-- item:task -->
{{N}}. Task {{TASK_ID}}: {{TASK_TITLE}}
<!-- /item -->
<!-- item:criterion -->
- [ ] Task {{TASK_ID}}: {{TEXT}}
<!-- /item -->
<!-- item:criterion-empty -->
- [ ] Task {{TASK_ID}} выполнена: все её шаги пройдены.
<!-- /item -->
<!-- item:criterion-text -->
- [ ] {{TEXT}}
<!-- /item -->
