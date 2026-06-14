# Code Tracing

Code tracing связывает пункты MASTER_PLAN и ошибки LAST_REPORT с фактическим кодом.

## Token Extraction

Из каждого item выделять:

- `path/like/file.ext`, имена директорий;
- `CamelCase`, `snake_case`, `kebab-case`, constants;
- route/endpoints `/api/...`;
- table/column/migration names;
- config/env names.

## Search Order

1. Exact file/dir lookup через Glob.
2. Grep по точным identifiers.
3. Grep по ключевым словам из контекста item.
4. Read найденных файлов вокруг совпадений.
5. Read-only probe из [PROBES.md](PROBES.md), если он уже стандартен для проекта и не меняет файлы.

## Evidence Rules

- Evidence должен быть проверяемым: путь + 1-based line number/range.
- Если совпадений больше 20, сузить запрос контекстом из MASTER_PLAN.
- Если evidence нет, писать `not found`, а не придумывать файл.
- Если найдено несколько конфликтующих реализаций, статус `ambiguous`.

## Verdict Rules

- `verified`: код соответствует контракту по смыслу и edge cases.
- `partial`: часть контракта реализована.
- `missing`: trace отсутствует.
- `deviates`: trace есть, но поведение иное.
- `ambiguous`: evidence недостаточен или противоречив.
- `not-applicable`: пункт плана не требует кода.
