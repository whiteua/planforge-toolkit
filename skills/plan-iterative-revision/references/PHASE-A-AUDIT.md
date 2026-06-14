# PHASE A — AUDIT

Цель фазы: найти все ошибки в главном плане и записать их в **новый** review-файл.
Никакие другие файлы не трогаются.

## Inputs

- `PLAN` — путь к главному плану.
- `prev_review` — путь к последнему review-файлу или `null`.

## Historical context at i>1 — digest only

На итерации `i>1` единственный исторический контекст для Фазы А — вывод команды:

```bash
python "<SKILL_DIR>/scripts/next_review_index.py" digest "<DIR>" "<BASE>"
```

Использовать только агрегаты `active_contracts` / `resolved_contracts`. Полные файлы
`REVIEW(N)` не читаются повторно в качестве общего контекста. Исключение: точечный `Read`
одного блока `REVIEW` по `fingerprint`, если нужно разобрать `deferred-conflict` или
неясный `persisted`.

Step 1 — Contract verification остаётся обязательным: digest ограничивает исторический
контекст, но не отменяет проверку активных контрактов в текущем `PLAN`.

## Precondition — review file must be creatable

WORKFLOW обязан выполнить review-write preflight **до** запуска этой фазы. Если будущий
`REVIEW(N)` нельзя физически создать рядом с планом или текущий режим агента не предоставляет
инструмент записи файлов, Фаза А не начинается.

Запрещено проводить аудит «в уме», складывать найденные issues только в memory/session notes,
печатать их только в чат или править главный план без созданного review-файла. В такой ситуации
нужно остановиться и сообщить пользователю, какой `REVIEW(N)` не удалось создать и что требуется
переключить режим или добавить инструмент записи файлов.

## Output

- Список объектов `Issue` (см. структуру ниже). На основании этого списка
  WORKFLOW решит, создавать ли новый `REVIEW(N)` файл.

## Step 1 — Contract verification (если prev_review существует)

Для каждого issue из `prev_review`:

1. Найти его `Required fix (contract)` (поле обязательно по REVIEW-FILE-FORMAT.md).
2. Проверить, что в текущем `PLAN` это требование отражено: grep по ключевым фразам
   контракта, по нумерации раздела, по упомянутым символам/именам файлов.
3. Если **не** реализовано → создать новый Issue:
   - `category = unfulfilled-contract`
   - `severity = blocker`
   - `Required fix` = дословный контракт из предыдущего ревью.
   - `Evidence` включает ссылку на `<basename>-review-(N-1).md#issue-id`.
4. Если реализовано частично → создать Issue с `severity = major` и описанием расхождения.
5. Если в предыдущем ревью был `deferred-conflict` — повысить severity на ступень
   (minor → major, major → blocker, blocker остаётся blocker).
6. Если переоткрывается issue, который в предыдущей Фазе Б был помечен `deferred-conflict` —
   учитывать текущее значение `deferral_count[fingerprint]` для отображения в Audit state,
   но НЕ инкрементировать счётчик. Инкремент происходит исключительно при новой пометке
   `deferred-conflict` в Фазе Б (PHASE-B-IMPLEMENT.md). При успешном применении в Фазе Б
   счётчик сбрасывается. Достижение порога `K_STUCK` (3) обрабатывает WORKFLOW (эскалация, C3/E).

## Step 2 — Taxonomy sweep

## Multi-lens audit (C1) — число проходов = `lenses` из конфига

Фаза А выполняется как `lenses` последовательных проходов; каждый — ПОЛНОЕ чтение плана
со своим оценочным фокусом. Линзы добавляются по порядку 1 → 2 → 3 → 4:

| Линза | Фокус | Классы таксономии (преимущественно) |
|---|---|---|
| L1 (всегда) | техника + сверка с кодом | `code`, `db`, `ops`, `perf`, `security`, `math`, `code-plan-mismatch` |
| L2 (`lenses>=2`) | логика + связность + контракты | `logic`, `contract`, `unfulfilled-contract` |
| L3 (`lenses==3`) | полнота + edge-cases + критерии приёмки | `tests`, пропущенные сценарии/acceptance |
| L4 (`preset==deep`) | red-team: triggers / failure / production consequences / abuse | `security`, `ops`, `logic` (attacking focus) |

L4 включается только при `preset==deep`. Найденные L4 issues проходят тот же
`fingerprint` / flow pipeline, что и остальные issues. L4 issue невалиден, если
`required-fix` не называет trigger condition и production consequence. Это только
prompt-contract: формат `REVIEW` и `validate-review` не меняются. Для deep записывать
`lenses_used = 4`.

- `lenses==1` — поведение идентично единому taxonomy sweep ниже.
- **Scope clarification:** при `lenses==1` L1 покрывает ВСЕ 10 классов таксономии
  (идентично текущему единому sweep); при `lenses>=2` столбец «Классы таксономии
  (преимущественно)» указывает ПРИОРИТЕТНЫЙ фокус каждой линзы, а не эксклюзивную
  область — L1 по-прежнему проходит все 10 классов, но с акцентом на технические,
  в то время как L2/L3 добавляют дополнительный фокусированный проход по своим классам.
- Каждая линза порождает свои in-memory Issue-объекты.
- **Merge + dedup** по каноническому `fingerprint`: при коллизии берётся issue с ВЫСШЕЙ
  severity, поля `Location`/`Evidence` объединяются.
- Фактическое число использованных линз записывается строкой `| Lenses used | <L> | ... |`
  в таблицу `## Audit state` review-файла.

### Taxonomy sweep (per lens)

Пройти по главному плану **по одному классу за раз** (см. `ERROR-TAXONOMY.md`). На каждый
проход:

- Читать план целиком (или большими блоками).
- Для конкретного класса задавать себе вопросы из соответствующего раздела таксономии.
- Каждое найденное расхождение — новый Issue.

Не пытаться искать сразу все классы — это размывает внимание.

## Step 3 — Cross-check with code (ОБЯЗАТЕЛЬНО)

### Уровень строгости сверки — `rigor` из конфига

- `grep` — только `Grep` по символам/путям (быстро, минимальная сверка).
- `read` (default Standard) — `Grep` + `Read` определений упомянутых символов/файлов.
- `explore` (Deep) — дополнительно subagent `Explore` на крупные модули/подсистемы
  (правило крупных модулей ниже).

`rigor` задаёт глобальный уровень; отдельные утверждения могут быть углублены точечно
(см. перепроверку ambiguous, C2).

План без сверки с кодом — фантазия. Для каждого упоминания в плане:

| Что упомянуто в плане | Что проверить в коде |
|---|---|
| Путь к файлу (`src/x/y.ts`) | `Read` файла; путь существует, файл живой |
| Имя класса/функции/типа | `Grep` по `class X`, `function X`, `def X`, `type X = ` |
| Сигнатура (параметры, возвращаемое значение) | `Read` определения; сравнить параметры/типы |
| Имя таблицы / колонки БД | `Grep` по `models/`, `entities/`, `schema.sql`, `migrations/` |
| HTTP-эндпоинт (метод + путь) | `Grep` по роутингу; сравнить method, path, payload |
| Имя env-переменной / config-ключа | `Grep` по `.env*`, `appsettings*.json`, `config/` |
| Имя пакета / зависимости | `Read` `package.json` / `*.csproj` / `requirements.txt` / `Cargo.toml` |
| Миграция БД (номер, эффект) | `Read` соответствующего файла миграции |

**Правило крупных модулей**: если упомянут крупный модуль / подсистема (например,
«AdminService», «биллинг»), запустить subagent **Explore** с узким запросом, например:

> «Quick exploration: how is X implemented today? What public API does it expose?
> Return: list of public methods with signatures, list of related DB tables, current behavior
> in 3-5 bullet points. Do not edit anything.»

Полученный отчёт сравнить с тем, что описано в плане. Расхождения → Issues с
`category = code-plan-mismatch`.

### Traceable status for every checked claim

Для каждого утверждения плана о коде, файлах, API, таблицах, миграциях или конфигурации
назначить один из статусов и сохранить его в заметках аудита:

- `verified` — подтверждено чтением кода / grep / Explore.
- `not found` — объект не найден; создать issue, если план строится на этом объекте.
- `ambiguous` — найдено несколько кандидатов или не хватает контекста; создать issue, если
  неоднозначность влияет на реализацию.
- `not applicable` — утверждение не относится к текущему коду.

Каждый issue должен содержать поле `Code cross-check` с одним из этих статусов и кратким
обоснованием. Review-файл должен содержать таблицу `Audit state`, где указано, что code
cross-check выполнен.

### Memoized code cross-check (C4) — кэш `verified` на один запуск

- Кэшируется ТОЛЬКО статус `verified`. `ambiguous`, `not found`, `not applicable` — не кэшируются.
- **Ключ записи** = `claim_text_hash` И множество `SHA-256` ВСЕХ файлов, реально прочитанных
  при верификации этого утверждения (не только «упомянутого» в плане). Хеши — командой
  `python "<SKILL_DIR>/scripts/next_review_index.py" hash <file>`.
- **Инвалидация:** на итерации i+1 запись валидна, только если (а) текст утверждения в плане
  не изменился И (б) SHA-256 каждого файла записи совпадает с текущим. Иначе — полная пересверка.
- **Fail-safe:** если список реально прочитанных файлов для утверждения не зафиксирован — НЕ
  кэшировать (сверить заново).
- Полный taxonomy sweep по ТЕКСТУ плана выполняется КАЖДУЮ итерацию — кэш экономит только
  повторное чтение неизменившегося кода, но не пропускает аудит логики/полноты.
- **Инструментовка (обязательна):** инкрементировать `cache_hits` при пропуске пересверки и
  `cross_checks_performed` при выполнении; обе цифры — в `## Audit state` (`| Cache hits | H | ... |`)
  и в финальном JSON (`cache_hits`).

### Forced re-verification of ambiguous / not found (C2)

- Утверждения со статусом `ambiguous` или `not found` на итерации i заносятся в `recheck_set`.
- На итерации i+1 такие утверждения НЕ берутся из `memo_cache` и сверяются заново с точечным
  повышением `rigor` (до `read`/`explore` для конкретного утверждения), даже если глобальный
  `rigor` ниже. Это ловит ошибки, замаскированные под «неоднозначность».
- Числовой confidence-score НЕ вводится.

## Issue structure

Каждый Issue (in-memory, перед записью в файл):

```json
{
  "id": "<N>.<seq>",
  "severity": "blocker | major | minor | nit",
  "category": "logic | code | math | ops | db | contract | tests | security | perf | code-plan-mismatch | unfulfilled-contract",
  "title": "<краткое>",
  "location_in_plan": "## раздел / подраздел [+ якорь]",
  "location_in_code": "<file:line>"  | null,
  "problem": "<описание>",
  "evidence": "<цитаты из плана + цитаты из кода>",
  "required_fix": "<контракт: что должно появиться/измениться в плане>",
  "acceptance": "<как проверить, что исправлено>",
  "fingerprint": "<результат scripts/next_review_index.py fingerprint>"
}
```

Поле `fingerprint` нужно WORKFLOW для детекта залипания (тот же набор две итерации подряд).
Вычислять только командой:

```bash
python "<SKILL_DIR>/scripts/next_review_index.py" fingerprint "<category>" "<required_fix>"
```

### Стабильность fingerprint

`fingerprint = hash(category + required-fix)`. От него зависят `deferral_count` и flow sets,
поэтому Фаза А не должна без необходимости перефразировать persisted `required-fix`.

## Severity rubric

- **blocker** — план в текущем виде нельзя реализовать (противоречие, ссылка на несуществующий
  код, схема БД сломает прод, миграция без rollback и т.п.). Также: невыполненный контракт
  предыдущего ревью.
- **major** — реализация по плану приведёт к серьёзному багу / переработке (неверная сигнатура,
  пропущенный индекс, отсутствие критериев приёмки на ключевую фичу).
- **minor** — несоответствие, ухудшающее качество, но не блокирующее (нет упоминания edge case,
  устаревшее имя файла, отсутствие тривиального теста).
- **nit** — стилистика, нумерация, форматирование. Включать только если их много и они мешают
  имплементации.

## Forbidden in Phase A

- Любые `Edit` / `Write` в файлы, кроме `REVIEW(N)` (а сам `REVIEW(N)` пишется только после
  возврата управления в WORKFLOW).
- Продолжать аудит, если review-write preflight не пройден или в текущем режиме нет инструмента
  для создания `REVIEW(N)`.
- Использовать memory/session notes, чат-ответ или правку главного плана как замену
  `REVIEW(N)`.
- Любые правки кода.
- Любые правки предыдущих ревью.
- Запуск тестов, сборок, линтеров, миграций.
- Создание snapshot-копий плана.

## Done criteria for Phase A

- Пройдена contract verification (если был prev_review).
- Review-write preflight был пройден до начала аудита; если не пройден — фаза не стартовала.
- Пройден taxonomy sweep по всем 10 классам.
- Сделана cross-check с кодом для всех упомянутых символов / файлов / схем.
- Сформирован список Issues с обязательными полями (см. структуру).
- Для каждого issue есть `Code cross-check`, `Required fix (contract)`, `Acceptance` и
  канонический `Fingerprint`.
- Созданный review-файл проходит
  `python scripts/next_review_index.py validate-review <review-file>` до передачи в Фазу Б.
- Управление возвращено в WORKFLOW для записи review-файла или выхода.
