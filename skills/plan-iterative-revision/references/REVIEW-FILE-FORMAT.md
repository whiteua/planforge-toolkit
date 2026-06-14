# REVIEW FILE FORMAT

Жёсткая схема файла `<basename>-review-<N>.md`. Этот формат — контракт между Фазой А (которая
его создаёт) и Фазой Б (которая его применяет). Любое отклонение ломает имплементацию.

## Filename

`<dir>/<basename>-review-<N>.md`, где:

- `<dir>`, `<basename>` — производные от пути главного плана.
- `<N>` — целое число, монотонно возрастает; вычисляется через `scripts/next_review_index.py`.

## Skeleton (русский вариант)

```markdown
# Ревизия N: <basename>

**Iteration**: N
**Audited plan**: <basename>.md
**Plan SHA-256**: <64-hex>
**Plan size**: <bytes> bytes
**Plan git blob**: <git-hash>            <!-- опционально -->
**Audited at**: <ISO-8601 UTC, напр. 2026-05-09T12:34:56Z>
**Previous review**: <basename>-review-<N-1>.md | none
**Issues found**: <total> (blocker: x, major: y, minor: z, nit: w)
**Flow**: +N / -R / P persisted / X reintro | Profile: (B,M,m,n)   <!-- опционально, observability -->

## Audit state

| Check | Status | Notes |
|---|---|---|
| Previous review contracts checked | yes/no/n-a | <кратко> |
| Taxonomy sweep completed | yes/no | 10 classes |
| Code cross-check completed | yes/no | verified / not found / ambiguous / not applicable statuses used |
| Review validated | yes/no | `validate-review` before Phase B |
| Deferred conflicts carried | <N> | <кратко> |
| Lenses used | <L> | опционально: число аспектных линз (C1) |
| Cache hits | <H> | опционально: пропущенных пересверок кода (C4) |

## Summary

<1–3 предложения: общая оценка плана и характер найденных проблем>

## Issues

### [N.1] <SEVERITY> · <category> · <title>

- **Location in plan**: <раздел / подраздел плана + якорь, если есть>
- **Location in code**: <file:line> | n/a
- **Code cross-check**: verified | not found | ambiguous | not applicable — <краткое обоснование>
- **Problem**:
  <развёрнутое описание проблемы>
- **Evidence**:
  > Цитата из плана:
  > <дословный фрагмент>

  > Цитата из кода (если применимо):
  > ```<lang>
  > <фрагмент>
  > ```
- **Required fix (contract)**:
  <однозначное описание того, что должно быть в плане ПОСЛЕ имплементации.
  Это поле — ОБЯЗАТЕЛЬНОЕ. Без него Фаза Б не сможет применить issue.>
- **Acceptance**:
  <как проверить, что исправлено: ключевые фразы / структура / отсутствие старого фрагмента>
- **Fingerprint**: <8 hex chars from `python scripts/next_review_index.py fingerprint <category> <required-fix>`>

### [N.2] ...

(и т.д.)

## Deferred from previous review (если есть)

- [<prev_id>] перенесено как [N.k] с повышенной severity (<old> → <new>): <причина>

## Notes for implementation

<необязательная секция: общие подсказки для Фазы Б, порядок применения, риски>
```

## Skeleton (English variant)

```markdown
# Revision N: <basename>

**Iteration**: N
**Audited plan**: <basename>.md
**Plan SHA-256**: <64-hex>
**Plan size**: <bytes> bytes
**Plan git blob**: <git-hash>            <!-- optional -->
**Audited at**: <ISO-8601 UTC>
**Previous review**: <basename>-review-<N-1>.md | none
**Issues found**: <total> (blocker: x, major: y, minor: z, nit: w)
**Flow**: +N / -R / P persisted / X reintro | Profile: (B,M,m,n)   <!-- optional, observability -->

## Audit state

| Check | Status | Notes |
|---|---|---|
| Previous review contracts checked | yes/no/n-a | ... |
| Taxonomy sweep completed | yes/no | 10 classes |
| Code cross-check completed | yes/no | verified / not found / ambiguous / not applicable statuses used |
| Review validated | yes/no | `validate-review` before Phase B |
| Deferred conflicts carried | <N> | ... |
| Lenses used | <L> | optional: number of audit lenses (C1) |
| Cache hits | <H> | optional: skipped code cross-checks (C4) |

## Summary

<1–3 sentences>

## Issues

### [N.1] <SEVERITY> · <category> · <title>

- **Location in plan**: ...
- **Location in code**: ...
- **Code cross-check**: verified | not found | ambiguous | not applicable — ...
- **Problem**: ...
- **Evidence**:
  > Plan quote: ...
  > Code quote: ```...```
- **Required fix (contract)**: ...
- **Acceptance**: ...
- **Fingerprint**: <8 hex chars from `python scripts/next_review_index.py fingerprint <category> <required-fix>`>

## Deferred from previous review

...

## Notes for implementation

...
```

## Field rules

| Field | Required | Notes |
|---|---|---|
| `Plan SHA-256` | yes | вычисляется `scripts/next_review_index.py hash <PLAN>` |
| `Plan size` | yes | в байтах |
| `Audited at` | yes | UTC, ISO-8601 с суффиксом `Z` |
| `Plan git blob` | optional | только если git доступен и репо инициализировано |
| `Previous review` | yes | имя файла или дословно `none` |
| `Issues found` | yes | агрегаты обязательны |
| `Flow` | optional | observability: `+N / -R / P persisted / X reintro \| Profile: (B,M,m,n)`; validator не парсит |
| `Required fix (contract)` | yes | без него issue нельзя имплементировать |
| `Acceptance` | yes | без него нельзя верифицировать имплементацию |
| `Code cross-check` | yes | один из статусов: verified / not found / ambiguous / not applicable |
| `Fingerprint` | yes | детект залипания между итерациями, генерируется командой `fingerprint` |

## Severity / category vocabulary

- **Severity**: `blocker`, `major`, `minor`, `nit` (всё в нижнем регистре в строке заголовка
  issue, заглавными — в декоративной части).
- **Category**: `logic`, `code`, `math`, `ops`, `db`, `contract`, `tests`, `security`, `perf`,
  `code-plan-mismatch`, `unfulfilled-contract`.

## ID scheme

`[N.k]` — `N` совпадает с номером ревизии, `k` — порядковый номер issue внутри ревизии,
начиная с `1`. ID должны быть уникальны в пределах файла и устойчивы к перестановкам.

## Validation

Любой созданный review-файл обязан пройти:

```bash
python scripts/next_review_index.py validate-review <review-file>
```

Для новых ревью, где fingerprints сгенерированы канонической командой, можно включать строгий режим:

```bash
python scripts/next_review_index.py validate-review --strict-fingerprint <review-file>
```

Validator проверяет обязательные секции, обязательные поля, severity/category vocabulary,
`Code cross-check` vocabulary, количество issues и severity-агрегаты из `Issues found`.
В строгом режиме также сверяет fingerprint каждого issue.

## Final-revision marker

Если ревью создано на этапе пользовательского «остановить» (см. WORKFLOW), в шапке добавить
строку:

```
**Status**: FINAL — implementation skipped by user
```

И секцию `## Notes for implementation` оставить пустой (имплементация не будет выполнена).

Если ревью создано на этапе эскалации застрявшего issue (см. WORKFLOW / PHASE-B, C3), в шапке
вместо `FINAL` добавить:

```
**Status**: ESCALATED — stuck issue needs manual decision
```

Секцию `## Notes for implementation` оставить пустой (Фаза Б на финальном review не запускается).
Валидатор не проверяет значение `Status` и не парсит строки таблицы — оба расширения совместимы.
