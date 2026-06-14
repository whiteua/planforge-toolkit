# WORKFLOW

Полный алгоритм итеративной ревизии плана. Этот документ — единственный источник правды
по последовательности шагов. SKILL.md — краткое резюме; здесь — детали.

## Notation

- `PLAN`        — путь к главному плану (аргумент скилла).
- `DIR`         — `dirname(PLAN)`.
- `BASE`        — `basename(PLAN)` без расширения `.md`.
- `REVIEW(N)`   — `<DIR>/<BASE>-review-<N>.md`.
- `MAX`         — лимит итераций без вопросов, по умолчанию `7`.
- `i`           — счётчик пройденных итераций (начинается с `0`).
- `N`           — номер следующего ревью (вычисляется в Bootstrap).
- `S_i`         — множество fingerprint'ов issues текущей Фазы А; при записи review
                  тождественно множеству issue fingerprints в `REVIEW(N)`.
- `prev_review` — последний существующий review-файл или `null`.
- `MODE`        — `full-cycle` (по умолчанию) или `audit-only`.
- `CFG` — результат `resolve-config`: `{preset, lenses, rigor, max, stop_policy}`.
- `INTERACTION` — `interactive` | `autonomous` (после разрешения `auto`).

## Bootstrap

Prerequisite: интерпретатор `python` (≥3.8) должен быть доступен в PATH. Если команда
`python` недоступна, остановиться до Фазы А и сообщить пользователю, что утилита
`scripts/next_review_index.py` не может быть запущена.

1. Принять аргумент `PLAN`. Проверить:
   - Файл существует.
   - Расширение `.md` (предупредить, если нет).
   - Файл читается.
2. Вычислить `DIR`, `BASE`.
3. Запустить:

   ```bash
   python "<SKILL_DIR>/scripts/next_review_index.py" next "<DIR>" "<BASE>"
   ```

   Получить JSON: `{"next": N, "prev": "<path>"|null, "max": <int>}`.
4. Выполнить **review-write preflight** для `REVIEW(N)`:

    ```bash
    python "<SKILL_DIR>/scripts/next_review_index.py" preflight-review "<DIR>" "<BASE>" "<N>"
    ```

    Preflight должен подтвердить, что директория существует, `REVIEW(N)` ещё не существует,
    и файловая система позволяет создать временный probe-файл в `DIR` и удалить его. Отдельно
    проверить агентский контекст: в текущем режиме должен быть доступен инструмент, способный
    физически создать новый markdown-файл рядом с планом.

    Если файловый preflight или проверка доступных инструментов не пройдены — **остановиться
    до Фазы А**. Сообщить пользователю:

    > Не могу создать review-файл `<REVIEW(N)>`. Переключите режим/добавьте инструмент записи
    > файлов и запустите скилл снова.

    Нельзя продолжать аудит, сохранять найденные issues только в memory/session notes, отдавать
    их только в чате или редактировать главный план без созданного review-файла.
5. Определить язык плана (см. ниже **Language detection**).
6. Определить режим:
     - `full-cycle`, если пользователь не просил иначе.
     - `audit-only`, если пользователь явно просил только аудит / только создать ревью /
         не имплементировать ревью в главный план.
7. Инициализировать `i = 0`, `MAX = 7`.

### Configuration & interaction (Bootstrap, до Фазы А)

Скилл принимает обязательный `PLAN` и опциональные параметры. Конфиг разрешается централизованно:

```bash
python "<SKILL_DIR>/scripts/next_review_index.py" resolve-config \
    [--preset quick|standard|deep] [--lenses 1|2|3] \
    [--rigor grep|read|explore] [--max <int>] \
    [--stop-policy pragmatic|strict]
```

| Аргумент | Значения | Default |
|---|---|---|
| `PLAN` (позиционный) | путь к плану | — (обязателен) |
| `MODE` | `full-cycle` \| `audit-only` | `full-cycle` |
| `interaction` | `auto` \| `interactive` \| `autonomous` | `auto` |
| `preset` | `quick` \| `standard` \| `deep` | `standard` |
| `lenses` / `rigor` / `max` | переопределяют пресет | из пресета |
| `stop_policy` | `pragmatic` \| `strict` | `pragmatic` |

**Автодетект `interaction`:** при `auto` — если в текущем режиме агента доступен инструмент
интерактивного вопроса, режим `interactive` (один popup на старте: подтвердить `preset` +
`stop_policy`, далее тишина); иначе `autonomous` (popup запрещён, конфиг из аргументов/дефолтов,
на выходе печатается машинный JSON по `assets/result.schema.json`). Явный `interaction`
переопределяет автодетект.

**Обратная совместимость:** вызов из `plan-splitter` идёт через subagent без popup-инструмента →
`auto` разрешается в `autonomous` с дефолтами `standard` + `pragmatic`; существующий контракт
splitter работает без правок.

## Main loop

### Per-run state (in-memory, на один запуск; файлов не создаёт)

- `memo_cache: {claim_fingerprint -> {claim_text_hash, [(file, sha256)]}}` — кэш `verified` (C4).
- `recheck_set: set[claim_fingerprint]` — утверждения на принудительную перепроверку (C2).
- `deferral_count: {issue_fingerprint -> int}` — счётчик подряд-отложений (C3).
- `prev_issue_fingerprints: set` — детект стагнации (существует).
- Счётчики `cache_hits`, `cross_checks_performed`, `lenses_used` — инструментовка (в `Audit state` и JSON).

Эти структуры живут только в рамках одного запуска и НЕ персистятся → инвариант 1
(«Фаза А пишет только REVIEW(N)») и инвариант 13 (diff guard) не затрагиваются.

```
while True:
    before_A = changed snapshot (если проект под git)
    if i > 0:
        # В этом 0-based цикле это означает «после хотя бы одного REVIEW»;
        # в 1-based описаниях итераций это тот же порог, что `i > 1`.
        digest = run:
            python "<SKILL_DIR>/scripts/next_review_index.py" digest "<DIR>" "<BASE>"
        history_context = {
            "active_contracts": digest.active_contracts,
            "resolved_contracts": digest.resolved_contracts,
        }
        # Единственный исторический контекст Фазы А — этот compact digest.
        # Полные REVIEW-файлы не читаются и не инжектятся в prompt.
    else:
        history_context = null

    issues = run_phase_A(PLAN, history_context)   # см. PHASE-A-AUDIT.md

    if issues is empty:
        if i == 0:
            # План чист с первой проверки — файлов НЕ создавать.
            emit completion-report to chat (template из assets/, по языку)
            message: "Главный план чист — ошибок не найдено с первой проверки."
            EXIT with result = "clean"
        else:
            # Успешная сходимость — записать completion-файл на диск.
            completion_path = run:
                python "<SKILL_DIR>/scripts/next_review_index.py" completion-path "<DIR>" "<BASE>"
            write completion_path.path from template assets/completion-report.{lang}.md:
                {{basename}}           = BASE
                {{iterations}}         = i
                {{revisions_created}}  = N - 1  (количество review-файлов за прогон)
                {{final_plan_sha256}}  = hash(PLAN)
                {{finished_at_utc}}    = now() ISO-8601 UTC
                {{verdict}}            = "Цикл сошёлся за {i} итераций. Все контракты ревизий применены к плану."
                {{list_of_review_files}} = перечисление REVIEW(1..N-1) из текущего прогона
                {{deferred_or_final_issues_or_none}} = "(none)"

            # diff-guard для post-loop шага: completion_path — единственный allowed path.
            after_completion = changed snapshot
            check-allowed before_A after_completion completion_path.path

            emit completion-report to chat (тот же рендеренный текст)
            message: "Цикл сошёлся за i итераций. Completion-файл: {completion_path.path}"
            EXIT with result = "converged"

    S_i = {iss.fingerprint for iss in issues}

    # --- stop_policy gate (после merge линз, до записи REVIEW(N)) ---
    open_above_nit = [iss for iss in issues if iss.severity in ("blocker", "major", "minor")]
    if stop_policy == "pragmatic" and not open_above_nit and issues:
        # остались только nit → создать финальный REVIEW(N) с nit, Фазу Б не запускать
        write REVIEW(N); validate-review
        stop loop with result = "converged"   # remaining_issues = len(issues)
    # ЖЁСТКИЙ ИНВАРИАНТ: ранний выход НЕ происходит, пока есть blocker/major (обе политики)

    if i >= MAX:
        if INTERACTION == "interactive":
            ask user (vscode_askQuestions):
                "Лимит {MAX} итераций исчерпан. Найдено ещё {len(issues)} ошибок. Продолжить?"
                options: ["+3 прохода", "+5 проходов", "Остановить и сохранить остаток"]
            if user chose "Остановить":
                write REVIEW(N) с шапкой + всеми issues + пометкой
                "**Status**: FINAL — implementation skipped by user"
                validate REVIEW(N)
                EXIT
            else:
                MAX += chosen_increment
        elif INTERACTION == "autonomous":
            # НЕ спрашивать: остановиться с result = "limit"
            write REVIEW(N) с шапкой + всеми issues
            validate REVIEW(N)
            EXIT with result = "limit"

    write_review_file(REVIEW(N), issues, plan_metadata)   # см. REVIEW-FILE-FORMAT.md
    # на этом шаге запрещено трогать любой другой файл
    validate REVIEW(N):
        python scripts/next_review_index.py validate-review REVIEW(N)

    # S_i — ровно множество fingerprint'ов issues, записанных в REVIEW(N).
    # Это множество передаётся в flow-analyze как `--current`; при stdin-варианте
    # не создаётся дополнительный файл, поэтому Inv1 сохраняется.
    flow = run:
        python "<SKILL_DIR>/scripts/next_review_index.py" flow-analyze "<DIR>" "<BASE>" --current -
        stdin = {"fingerprints": sorted(S_i)}
    write/update header REVIEW(N):
        Flow: +<flow.flows.new> / -<flow.flows.resolved> / <flow.flows.persisted> persisted / <flow.flows.reintroduced> reintro
        Profile: (B,M,m,n)
    validate REVIEW(N) again after Flow/Profile header update

    after_A = changed snapshot (если проект под git)
    check allowed changes for Phase A: only REVIEW(N)

    # Применить flow-гейты из таблицы ниже. `flow.result` и `flow.stop_reason` —
    # deterministic suggester для наблюдаемости; authoritative-решение принимает
    # WORKFLOW по предикатам Flow gates.
    if Flow gates predicate == "regression": HARD STOP → result="escalated", stop_reason="regression"
    if Flow gates predicate == "churn":      STOP → result="stagnation", stop_reason="churn"

    if MODE == "audit-only":
        report REVIEW(N) path and EXIT

    before_B = changed snapshot (если проект под git)
    run_phase_B(PLAN, REVIEW(N))   # см. PHASE-B-IMPLEMENT.md
    # на этом шаге запрещено трогать любой другой файл, включая REVIEW(N)
    after_B = changed snapshot (если проект под git)
    check allowed changes for Phase B: only PLAN

    # --- escalation gate (после Фазы Б, при учёте deferred) ---
    for fp, cnt in deferral_count.items():
        if cnt >= K_STUCK:   # K_STUCK = 3
            write финальный REVIEW(N+1) с маркером **Status**: ESCALATED
            stop loop with result = "escalated"; escalated += [fp]

    i += 1
    prev_review = REVIEW(N)
    N += 1
```

### Final output

- INTERACTION == interactive → человекочитаемый `completion-report` (assets/), плюс служебный
  JSON-блок (см. ниже) для логов.
- INTERACTION == autonomous → напечатать РОВНО один JSON-объект по `assets/result.schema.json`:

  ```json
  {"result":"clean|converged|stagnation|limit|escalated","iterations":N,
   "remaining_issues":N,"escalated":["<fp>"],"lenses_used":L,"cache_hits":H}
  ```

  Поля `result/iterations/remaining_issues` сохраняют семантику, ожидаемую splitter;
  `escalated/lenses_used/cache_hits` — аддитивные.

## Stop conditions

| Условие | Действие |
|---|---|
| `REVIEW(N)` нельзя создать или нет write-инструмента | Остановиться до Фазы А; сообщить путь review-файла и попросить включить запись файлов |
| Issues пуст с первой итерации | Вывести «план чист с первой попытки», файл review **не создавать** |
| Issues пуст на итерации i > 0 | Записать `<BASE>-completion.md`, вывести «цикл сошёлся за i итераций», выход |
| i >= MAX и issues не пуст | Интерактивный диалог: +3 / +5 / стоп |
| Flow gate `churn`: нет resolved на окне `W=2`, но появляются новые issues | Вывести «Залипание: нет прогресса между итерациями», `result="stagnation"` |
| Пользователь выбрал «стоп» | Записать оставшиеся issues в финальное ревью с `**Status**: FINAL — implementation skipped by user`; Фаза Б на нём не запускается |
| Режим audit-only и issues не пуст | Создать и валидировать review-файл, затем остановиться без Фазы Б |
| `stop_policy=pragmatic`, остались только `nit` (нет blocker/major/minor) | Записать финальный review с `nit`, Фазу Б не запускать, `result="converged"` |
| Застрявший issue: один fingerprint отложен `K_STUCK=3` раза подряд | Записать финальный review с `**Status**: ESCALATED`, `result="escalated"` |
| `interaction=autonomous` и `i >= MAX` | Неинтерактивный стоп, финальный review, `result="limit"` |

### Flow gates

Параметры: `W = 2` (окно churn), `K_STUCK = 3`. `churn`/`regression` armed только
при `i >= 3`. Множество `--current S_i` для `flow-analyze` тождественно равно
множеству issue fingerprints в `REVIEW(i)` / текущем `REVIEW(N)`.

`flow-analyze.result/stop_reason` — детерминированный SUGGESTER; authoritative-решение
принимает WORKFLOW по предикатам ниже. `persisted_counts` — observability-only, НЕ
триггер stuck. Stuck определяется только из `deferral_count` Фазы Б.

| Гейт | Условие | result | stop_reason |
|---|---|---|---|
| clean | `S_i = ∅` | clean | null |
| converged (pragmatic) | `new=∅ ∧ persisted⊆nit ∧ stop_policy=pragmatic` | converged | drain |
| regression | `reintroduced ≠ ∅` (`i >= 3`) → HARD STOP | escalated | regression |
| churn | `resolved=∅` на окне `W=2` ∧ `new≠∅` (`i >= 3`) | stagnation | churn |
| stuck (per-issue) | `deferral_count(fp) >= K_STUCK` (`K_STUCK=3`, Фаза Б) | escalated | stuck |
| limit | достигнут `MAX` | limit | null |

- Список issue для применения Фазой Б = `S_i \ escalated_set` (эскалированные остаются
    в плане, но не редактируются).
- Осцилляция A→B→A ловится `regression` (вернувшийся issue попадает в `reintroduced`);
    отдельный детектор не вводится.

## Utility commands

Все команды выполняются через `python scripts/next_review_index.py`:

- `next <dir> <basename>` — найти следующий номер review.
- `digest <dir> <basename>` — вывести компактный JSON исторического контекста для Фазы А:
        `{iteration, active_contracts[], resolved_contracts[]}`. Команда не вычисляет flows,
        потому что `S_i` ещё неизвестен.
- `flow-analyze <dir> <basename> --current <fps.json|->` — посчитать
        `new/resolved/persisted/reintroduced`, `persisted_counts` и suggested
        `result/stop_reason` для текущего множества `S_i`; WORKFLOW остаётся authoritative.
- `completion-path <dir> <basename>` — JSON `{"path": ..., "exists": ...}` для детерминированного
    пути completion-файла. Не создаёт файл.
- `preflight-review <dir> <basename> <N>` — fail-fast проверка перед Фазой А: директория
    существует, `REVIEW(N)` ещё не существует, временный probe-файл можно создать и удалить.
    Даже успешный результат не отменяет обязательную проверку, что текущий режим агента имеет
    файловый write-инструмент; если такого инструмента нет, скилл останавливается.
- `hash <file>` — SHA-256 по сырым байтам файла.
- `fingerprint <category> <required-fix...>` — канонический 8-символьный fingerprint.
- `validate-review [--strict-fingerprint] <review-file>` — машинная проверка структуры ревью.
- `changed <git-root>` — JSON snapshot изменённых файлов по `git status --porcelain`.
- `check-allowed <before-json> <after-json> <allowed-path>...` — diff guard: проверить,
    что новые изменения между snapshot-ами затронули только разрешённые пути.
- `resolve-config [--preset ...] [--lenses ...] [--rigor ...] [--max ...] [--stop-policy ...]`
  — разрешить конфиг (пресет + переопределения) в JSON `{preset,lenses,rigor,max,stop_policy}`.

## Language detection

```
text = read(PLAN)
cyrillic = count(c for c in text if 'А' <= c <= 'я' or c in 'ЁёІіЇїЄєҐґ')
total    = count(c for c in text if c.isalpha())
ratio    = cyrillic / total if total else 0
language = "ru" if ratio > 0.05 else "en"
```

Этот язык определяет, какой шаблон брать (`*.ru.md` vs `*.en.md`) и на каком языке писать
все артефакты.

## Plan metadata (для шапки ревью)

При создании каждого `REVIEW(N)`:

- `Plan SHA-256` — `python "<SKILL_DIR>/scripts/next_review_index.py" hash "<PLAN>"`.
- `Plan size`    — размер файла в байтах.
- `Audited at`   — текущее время в формате ISO-8601 UTC, напр. `2026-05-09T12:34:56Z`.
- `Plan git blob` — опционально, если в `DIR` есть `.git` или родительский git-репо:
  `git hash-object "<PLAN>"` (если команда не доступна — поле пропустить).

## Canonical fingerprints

Каждый issue получает `Fingerprint`, вычисленный только так:

```bash
python "<SKILL_DIR>/scripts/next_review_index.py" fingerprint "<category>" "<Required fix text>"
```

Алгоритм: whitespace-normalization для `Required fix`, затем SHA-1 от
`<category-lowercase> + "\\n" + first 200 chars`, первые 8 hex-символов.

## Review validation

После записи любого review-файла и до Фазы Б выполнить:

```bash
python "<SKILL_DIR>/scripts/next_review_index.py" validate-review "<REVIEW(N)>"
```

Если validator вернул ошибку, не запускать Фазу Б. Исправить создаваемый review-файл можно
только пока Фаза А ещё активна; после перехода в Фазу Б review становится историческим.

`--strict-fingerprint` применять для новых ревью, если все fingerprints сгенерированы
канонической командой. Для старых ревью без канонических fingerprints использовать обычный режим.

## Diff guard

Если рабочая директория находится в git-репозитории, каждая фаза оборачивается snapshot-ами:

```bash
python "<SKILL_DIR>/scripts/next_review_index.py" changed "<git-root>" > before.json
# run phase
python "<SKILL_DIR>/scripts/next_review_index.py" changed "<git-root>" > after.json
python "<SKILL_DIR>/scripts/next_review_index.py" check-allowed before.json after.json "<allowed-path>"
```

- Фаза А: `<allowed-path>` = путь нового `REVIEW(N)` относительно git-root.
- Фаза Б: `<allowed-path>` = путь `PLAN` относительно git-root.
- Snapshot хранит не только путь, но и SHA-256 изменённого файла, поэтому `check-allowed`
    ловит даже дополнительную правку файла, который уже был dirty до начала фазы.
- Если git недоступен или файл вне git-root, выполнить ручную проверку списка изменённых файлов
    и явно сообщить об ограничении.

## Traceable code cross-check

Для каждого утверждения плана о коде, файлах, API, таблицах, миграциях или конфигурации
Фаза А присваивает один из статусов:

- `verified` — утверждение подтверждено чтением кода / grep / Explore.
- `not found` — упомянутый объект не найден; обычно это issue.
- `ambiguous` — найдено несколько кандидатов или контекст недостаточен; обычно это issue.
- `not applicable` — утверждение не относится к текущему коду (например, чисто процессное).

Статусы отражаются в поле `Code cross-check` каждого issue и в таблице `Audit state` review-файла.

## Deferred conflicts

Если в Фазе Б какой-то issue не удалось применить даже после 2 ретраев, он помечается
тегом `deferred-conflict` (см. PHASE-B-IMPLEMENT.md). Такие issue **не теряются**:
на следующей итерации Фаза А автоматически их обнаружит как «контракт предыдущего ревью
не реализован» и включит в новое ревью с severity на ступень выше (или blocker, если уже был
blocker).

## Safety nets

- Перед записью `REVIEW(N)` убедиться, что файла с таким именем нет (на случай гонки).
- Review-write preflight выполняется **до Фазы А**, чтобы не проводить аудит, который нельзя
    сохранить в обязательный исторический файл. Memory/session notes и ответ в чат не являются
    допустимой заменой `REVIEW(N)`.
- После Фазы А: diff-снимок (mental) — изменён должен быть только `REVIEW(N)`.
- После Фазы Б: сравнить SHA-256 главного плана с тем, что был перед фазой; SHA должен
  отличаться (иначе ничего не применилось — это ошибка, отчитаться пользователю).
- Залипание определяется flow-гейтами: `churn` по окну `W=2`, а per-issue `stuck` только
    через `deferral_count(fp) >= K_STUCK`. `persisted_counts` из `flow-analyze` используется
    только для наблюдаемости и не является триггером эскалации.
