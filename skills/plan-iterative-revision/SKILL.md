---
name: plan-iterative-revision
description: |
  Итеративная ревизия плана модернизации проекта. Запускает цикл «аудит главного плана → запись
  ошибок в новый review-файл → имплементация ревью обратно в план → повтор», пока план не станет
  чист или не будет достигнут лимит итераций. Сверяет план с текущим кодом проекта.

  Iterative plan revision loop. Audits a master plan, records issues into a new review file,
  implements the review back into the master plan, and repeats until the plan is clean or the
  iteration limit is reached. Cross-checks the plan against the actual codebase.

  Use when: «итеративная ревизия плана», «найти ошибки в плане и внедрить исправления»,
  «inspect plan and patch it», «plan revision loop», «cycle audit-implement plan», «ревизия
  плана модернизации», «проверить план на ошибки и обновить». Если текущий режим или набор
  инструментов не позволяет физически создать review-файл рядом с планом, скилл обязан
  остановиться до аудита и попросить пользователя включить режим/инструмент записи файлов.
allowed-tools:
  - Read
  - Grep
  - Glob
  - Edit
  - Write
  - Bash
---

# Plan Iterative Revision

Двухфазный цикл, который доводит план модернизации проекта до состояния «без ошибок» через
последовательные ревизии. Каждая ревизия — отдельный исторический файл; главный план редактируется
точечно в соответствии с контрактами свежесозданного ревью.

## Arguments and modes

Скилл принимает **ровно один обязательный** аргумент — путь к главному файлу плана
(относительный или абсолютный), напр. `docs/plans/plan01-sub-admins.md`.

Режимы выполнения:

- `full-cycle` (по умолчанию): аудит → создание review → имплементация review в план → повтор.
- `audit-only`: выполнить только Фазу А, создать новый review-файл при наличии ошибок и
  остановиться без Фазы Б. Использовать, если пользователь явно просит «только аудит»,
  «только создать ревью» или «не имплементировать».

### Параметры (опциональные; разрешаются через `resolve-config`)

- `preset` — `quick` | `standard` (default) | `deep`. Пакует три диска:
  `lenses` (1/2/3 аспектных линзы аудита), `rigor` (`grep`/`read`/`explore` — глубина сверки),
  `max` (3/5/7 — потолок итераций). `deep` также включает четвёртую red-team линзу L4
  (failure triggers + production consequences). Любой диск можно переопределить явно
  (`lenses`/`rigor`/`max`).
- `stop_policy` — `pragmatic` (default; стоп, когда остались только `nit`) | `strict`
  (до нуля issue / стагнации / MAX). Ранний выход запрещён при открытых `blocker`/`major`.
- `interaction` — `auto` (default) | `interactive` | `autonomous`. Ось ОРТОГОНАЛЬНА `MODE`.
  `auto` → `interactive` при наличии инструмента вопроса (один popup на старте), иначе
  `autonomous` (без popup, конфиг из аргументов, на выходе JSON по `assets/result.schema.json`).
  Вызов из `plan-splitter` (subagent без popup) → `autonomous` + `standard` + `pragmatic`,
  существующий контракт работает без правок.

Детали: [references/WORKFLOW.md](references/WORKFLOW.md), [references/PHASE-A-AUDIT.md](references/PHASE-A-AUDIT.md).

Все остальные пути выводятся автоматически:

- `dir`      = директория главного плана
- `basename` = имя файла без расширения
- review-файлы = `<dir>/<basename>-review-<N>.md`, где `N` монотонно растёт

## Hard invariants (НЕ нарушать)

1. **Фаза А** (аудит) пишет **только** один новый файл `<basename>-review-<N>.md`.
   Никакие другие файлы — ни главный план, ни предыдущие ревью, ни код проекта — не модифицируются.
2. До начала Фазы А выполнить **review-write preflight**: активный режим должен позволять
  физически создать `REVIEW(N)` в `dir` плана, а файл `REVIEW(N)` не должен существовать.
  Если preflight не пройден — **остановиться до аудита**, ничего не менять и сообщить
  пользователю: «Не могу создать review-файл `<path>`. Переключите режим/добавьте инструмент
  записи файлов и запустите скилл снова». Нельзя заменять review-файл записью в memory,
  ответом в чат, временным конспектом или правкой главного плана.
3. **Фаза Б** (имплементация) редактирует **только** главный план. Не трогать review-файлы и код.
4. Предыдущие review-файлы — исторический архив, неизменяемый.
5. `N` = `max(существующих review-N) + 1`; если ревизий нет, `N = 1`. Дыры в нумерации допустимы.
6. Если Фаза А вернула пустой список ошибок — review-файл **не создаётся**, цикл завершается.
7. Скилл **не модифицирует код проекта** ни на одной фазе.
8. Сверка плана с текущим кодом — **обязательна**; глубокое исследование делегируется
   subagent `Explore`.
9. Порог детекта языка: `cyrillic_ratio > 0.05` → `ru`, иначе `en`. Менять синхронно
  с `references/WORKFLOW.md`.
10. После Фазы Б SHA-256 главного плана **обязан** отличаться от стартового; иначе —
  аварийный выход и сообщение пользователю об отсутствии изменений.
11. Каждый review-файл перед Фазой Б должен проходить машинную проверку:
    `python "<SKILL_DIR>/scripts/next_review_index.py" validate-review <review-file>`.
12. Fingerprint каждого issue должен вычисляться командой
    `python "<SKILL_DIR>/scripts/next_review_index.py" fingerprint <category> <required-fix...>`.
13. После каждой фазы проверять, что изменены только разрешённые файлы (diff guard).

> Примечание (расширения качества): многолинзовый аудит, мемо-кэш сверки и счётчики
> отложений/линз — **in-memory на один запуск**, файлов не создают. Поэтому инвариант 1
> («Фаза А пишет только REVIEW(N)») и инвариант 13 (diff guard) сохраняются без изменений.
> Маркер `**Status**: ESCALATED` использует тот же механизм шапки, что и `FINAL`.

> Completion-файл (`<BASE>-completion.md`) пишется **post-loop** (после выхода из `while True`),
> не внутри Фазы А. diff-guard для него — отдельный `check-allowed` с единственным allowed path.

## Prerequisites

- Интерпретатор `python` (≥3.8) должен быть доступен в PATH; он используется утилитой
  `scripts/next_review_index.py` и не требует сторонних зависимостей.
- `<SKILL_DIR>` — каталог, содержащий **этот** файл `SKILL.md`. Скрипт и все
  вспомогательные ресурсы (`scripts/`, `assets/`, `references/`) расположены внутри
  `<SKILL_DIR>`, а **не** в workspace анализируемого проекта. При вызове скрипта всегда
  использовать абсолютный путь: `python "<SKILL_DIR>/scripts/next_review_index.py" ...`.

## Algorithm (high-level)

```
1. Bootstrap:
   - Прочитать главный план; вычислить dir, basename.
   - Запустить `python "<SKILL_DIR>/scripts/next_review_index.py" next <dir> <basename>`
     → получить N (следующий) и prev_review (последний существующий или null).
   - Запустить `python "<SKILL_DIR>/scripts/next_review_index.py" resolve-config [args]`
     → получить CFG `{preset, lenses, rigor, max, stop_policy}`.
   - Выполнить review-write preflight для `<dir>/<basename>-review-<N>.md`. Если текущий
     режим/инструменты не позволяют создать этот файл, остановиться до аудита и попросить
     пользователя включить запись файлов; не использовать memory или чат как замену.
   - i = 0; MAX = CFG.max  (из resolve-config: quick=3 / standard=5 / deep=7).

2. Loop:
   2.1 Phase A (audit) — см. references/PHASE-A-AUDIT.md:
       - Если prev_review существует — проверить, что все его контракты внедрены в главный план.
       - Аудит главного плана по таксономии (references/ERROR-TAXONOMY.md).
       - Сверка с кодом (Read/Grep, при необходимости subagent Explore) с явным статусом
         для каждого утверждения: verified / not found / ambiguous / not applicable.
       - Собрать issues с severity (blocker/major/minor/nit).
       - Fingerprint для каждого issue вычислить через `<SKILL_DIR>/scripts/next_review_index.py fingerprint`.

   2.2 Если issues пуст:
       - Если i == 0: вывести completion-report в чат, файлов не создавать, выйти (result="clean").
       - Если i > 0: записать `<DIR>/<BASE>-completion.md` по шаблону
         `assets/completion-report.{lang}.md` (переменные: iterations, sha256, verdict, etc.);
         проверить diff-guard (allowed: completion-файл); вывести в чат; выйти (result="converged").

   2.3 Если i >= MAX:
       - Если interaction == autonomous: неинтерактивный стоп, result="limit" (см. Stop conditions).
       - Иначе спросить пользователя: «Лимит {MAX} исчерпан. Найдено {len(issues)}. Продолжить?»
         Опции: +3, +5, стоп. При «стоп» — записать оставшиеся issues в финальный review и выйти.

   2.3a Если набор issues по fingerprint не изменился между итерациями i-1 и i (stagnation):
       - Прервать цикл, не выполнять Фазу Б повторно.
       - Вывести verdict: «Залипание: нет прогресса между итерациями i-1 и i».

   2.4 Создать <basename>-review-<N>.md по шаблону из assets/
       (см. references/REVIEW-FILE-FORMAT.md). Шапка должна содержать:
       Plan SHA-256, Plan size, Audited at (ISO-8601 UTC), опц. Plan git blob.
       Сразу после записи выполнить validate-review.

       Если режим audit-only:
       - остановиться после успешной validate-review;
       - Фазу Б не запускать;
       - сообщить пользователю путь к созданному review-файлу.

   2.4a Flow-гейты (`regression` / `churn`) выполняются после `validate-review` и до Фазы Б;
        полная логика и порядок — в references/WORKFLOW.md (здесь не дублируется).

   2.5 Phase B (implement) — см. references/PHASE-B-IMPLEMENT.md:
       - Применить контракты из только что созданного ревью к главному плану.
       - Sort: blocker → major → minor → nit; внутри — по позиции в плане сверху вниз.
       - Один issue = одна транзакция Edit + verify; Read после каждого Edit.
       - До 2 ретраев при stale old_str; иначе пометить deferred-conflict
         (попадёт в следующее ревью автоматически на следующей итерации Фазы А).

   2.6 i += 1; N += 1; prev_review = новый файл. Goto 2.1.
```

## Stop conditions

| Условие | Действие |
|---|---|
| Issues пуст с первой итерации | Вывести «план чист с первой попытки», файл review **не создавать** |
| Issues пуст на итерации i > 0 | Записать `<BASE>-completion.md`, вывести «цикл сошёлся за i итераций», выход |
| i >= MAX и issues не пуст | Интерактивный диалог: +3 / +5 / стоп |
| Stagnation: fingerprint-набор issues не изменился между i-1 и i | Вывести «Залипание: нет прогресса между итерациями i-1 и i», выход |
| Regression: `reintroduced ≠ ∅` (i≥3) | HARD STOP, финальное ревью, `result="escalated"`, `stop_reason="regression"` |
| Churn: `resolved=∅` on window `W=2` and `new≠∅` (i≥3) | Стоп, `result="stagnation"`, `stop_reason="churn"` |
| Пользователь выбрал «стоп» | Записать оставшиеся issues в финальное ревью с `**Status**: FINAL — implementation skipped by user`; Фаза Б на нём не запускается |
| Режим audit-only и issues не пуст | Создать и валидировать review-файл, затем остановиться без Фазы Б |
| `stop_policy=pragmatic`, остались только `nit` (нет blocker/major/minor) | Финальный review с `nit`, Фаза Б не запускается |
| Застрявший issue (`K_STUCK=3` отложений подряд) | Финальный review с `**Status**: ESCALATED`, эскалация пользователю |
| `interaction=autonomous` и `i >= MAX` | Неинтерактивный стоп, `result="limit"` |

> Порядок гейтов застоя (authoritative — references/WORKFLOW.md): сначала `Regression`,
> затем `Churn`, затем классический `Stagnation` (2.3a). Они ловят разные патологии и не
> взаимоисключают друг друга.

## Utility commands

Все команды выполняются через `python "<SKILL_DIR>/scripts/next_review_index.py"`,
где `<SKILL_DIR>` — каталог установки скилла (содержит `SKILL.md`, `scripts/`, `assets/`,
`references/`):

- `next <dir> <basename>` — найти следующий номер review.
- `preflight-review <dir> <basename> <N>` — проверить, что будущий review-файл можно
  безопасно создать: директория существует, `REVIEW(N)` ещё не существует, файловая система
  разрешает создать и удалить временный probe-файл. Эта команда не заменяет проверку наличия
  файлового write-инструмента в текущем режиме агента.
- `hash <file>` — SHA-256 по сырым байтам файла.
- `fingerprint <category> <required-fix...>` — канонический 8-символьный fingerprint.
- `validate-review [--strict-fingerprint] <review-file>` — машинная проверка структуры ревью.
- `changed <git-root>` — JSON snapshot изменённых файлов по `git status --porcelain`.
- `check-allowed <before-json> <after-json> <allowed-path>...` — diff guard: проверить,
  что новые изменения между snapshot-ами затронули только разрешённые пути.
- `resolve-config [--preset ...] [--lenses ...] [--rigor ...] [--max ...] [--stop-policy ...]`
  — разрешить конфиг (пресет + переопределения) в JSON `{preset,lenses,rigor,max,stop_policy}`.
- `digest <dir> <basename>` — compact machine digest of REVIEW history for Phase A at i>1.
- `flow-analyze <dir> <basename> --current <fps.json|->` — set algebra flows
  (`new/resolved/persisted/reintroduced`) + suggested gate (`result`/`stop_reason`).
- `completion-path <dir> <basename>` — JSON `{"path": ..., "exists": ...}` — путь completion-файла.

## Language

Все артефакты (review-файлы, completion-report) пишутся на **языке главного плана**.
Простое правило детекта: если `cyrillic_ratio > 0.05` (доля кириллицы > 5%) → русский,
иначе английский. Шаблоны: `assets/review-template.{ru,en}.md`,
`assets/completion-report.{ru,en}.md`.

## Verification fixtures

Перед запуском dogfooding-проверок в каталоге `.fixtures/` должны существовать:

- `clean-plan.md`
- `plan-with-3-errors.md`
- `plan-with-stuck-error.md`
- `plan-with-conflict.md`
- `plan-with-nits-only.md`

Каждый тест T1–T7 считается пройденным, если выполнены все три условия: (a) изменены
только файлы, разрешённые соответствующей фазой; (b) состав созданных review-файлов
совпадает с ожидаемым; (c) `completion-report` содержит ожидаемый verdict.

## Read these before acting

1. [references/WORKFLOW.md](references/WORKFLOW.md) — детальный алгоритм и инварианты.
2. [references/PHASE-A-AUDIT.md](references/PHASE-A-AUDIT.md) — как искать ошибки + сверка с кодом.
3. [references/PHASE-B-IMPLEMENT.md](references/PHASE-B-IMPLEMENT.md) — как точечно править план.
4. [references/REVIEW-FILE-FORMAT.md](references/REVIEW-FILE-FORMAT.md) — формат `*-review-N.md`.
5. [references/ERROR-TAXONOMY.md](references/ERROR-TAXONOMY.md) — 10 классов ошибок.

## Forbidden actions

- Редактировать главный план в Фазе А.
- Начинать аудит, если `REVIEW(N)` нельзя физически создать в файловой системе или текущий
  режим агента не предоставляет инструмент записи файлов.
- Использовать memory/session notes, ответ в чат, terminal output или правку главного плана
  как замену обязательного review-файла.
- Редактировать review-файлы (новые или старые) в Фазе Б.
- Создавать review-файл, если ошибок не найдено.
- Создавать `snapshots/`, дополнительные копии плана, ветки, коммиты.
- Модифицировать любой файл кода проекта.
- Запускать тесты/сборку/линтеры проекта (только Read/Grep для сверки).
