---
name: plan-splitter
description: |
  Декомпозиция большого markdown-плана на самостоятельные стадии (stages), каждая из которых
  выполнима за один проход агента. Результат: набор файлов рядом с исходным планом —
  roadmap (-stg00-roadmap.md) + по одному файлу на стадию (-stg01.md, -stg02.md, ...).
  Скилл framework-agnostic, оригинальный план НЕ модифицируется.

  Decompose a large markdown plan into self-contained stages, each executable in a single
  agent pass. Output: files alongside the source plan — a roadmap (-stg00-roadmap.md) plus
  one file per stage (-stg01.md, -stg02.md, ...). Framework-agnostic; the original plan is
  NEVER modified.

  Use when: «разбить план на стадии», «декомпозировать план», «разбей на этапы»,
  «plan splitter», «split plan into stages», «decompose markdown plan», «разделить план
  на части», «нарежь план на стадии». Если текущий режим или набор инструментов не
  позволяет физически создать stg-файлы рядом с планом, скилл обязан остановиться до
  генерации и попросить пользователя включить запись файлов.
allowed-tools:
  - Read
  - Grep
  - Glob
  - Edit
  - Write
  - Bash
---

# Plan Splitter

Скилл декомпозиции большого плана на стадии. Каждая стадия — самодостаточный файл, который
можно передать агенту независимо. Скилл создаёт roadmap + N stg-файлов рядом с исходным
планом; **сам план не редактирует**.

## Arguments

Скилл принимает **один обязательный** позиционный аргумент, **один опциональный**
позиционный аргумент и опциональные именованные аргументы:

1. **Путь к файлу плана** (обязательный) — относительный или абсолютный,
   напр. `docs/plans/plan01-modernization.md`.
2. **Модель для ревизии** (опциональный) — имя модели для subagent-ревизии,
   напр. `"Claude Opus 4 (copilot)"`. Если не указан — используется значение из `## Defaults`.

Опциональные именованные аргументы (для автономных вызовов; в интерактиве спрашиваются в рантайме):
- `verify` = `ask` (дефолт) `| all | none` — запускать ли глубокую проверку стадий и для каких.
- `verify_depth` = `quick | standard (дефолт) | deep` — глубина проверки (preset для `plan-iterative-revision`).
- `verify_mode` = `full-cycle` (дефолт) `| audit-only` — правит стадии или только пишет review.

Все остальные значения выводятся автоматически:
- `dir`       = директория плана
- `base_name` = имя файла плана без расширения
- `lang`      = `ru` при `cyrillic_ratio > 0.05`, иначе `en`
- `revision_model` = второй аргумент или дефолт из `## Defaults`

## Defaults

| Parameter | Default | Override |
|-----------|---------|---------|
| revision_model | auto (текущая активная модель) | Второй аргумент при вызове; имя модели — fallback |
| verify | ask | Аргумент `verify=all\|none` |
| verify_depth | standard | Аргумент `verify_depth=quick\|deep` |
| verify_mode | full-cycle | Аргумент `verify_mode=audit-only` |

Для смены дефолтных параметров — изменить значение в этой таблице.

## Hard invariants (НЕ нарушать)

1. **Оригинальный план НЕ модифицируется.** Скилл только читает его и создаёт новые файлы.
2. **Один уровень декомпозиции.** Стадии не дробятся рекурсивно. Если стадия слишком большая —
   рекомендовать пользователю перезапустить `plan-splitter` на ней отдельно.
3. **Write preflight** обязателен перед генерацией файлов. Если режим/инструменты не позволяют
   создать файлы в `dir` — остановиться до генерации и сообщить пользователю.
4. **Conflict handling.** Если `preflight` обнаружил существующие stg-файлы — спросить
   пользователя: (а) перезаписать, (б) выбрать другой base/suffix, (в) отмена. Без явного
   подтверждения — НЕ перезаписывать.
5. **Максимум два раунда draft → feedback → redraft.** При повторном отклонении пользователем —
   выход без генерации.
6. **Все stg-файлы самодостаточны.** Каждый файл + roadmap — достаточно для агента, чтобы
   понять, что делать. Без back-references «см. выше», «как в оригинале».
7. **Нумерация** — строго `stg01`, `stg02`... (двузначная, с ведущим нулём до 99 стадий).
8. **Roadmap** всегда имеет суффикс `-stg00-roadmap.md` (0-я «стадия» = карта).
9. **Язык файлов** совпадает с языком исходного плана (`cyrillic_ratio > 0.05` → `ru`).
   Порог 5% — конвенция экосистемы скиллов (см. `plan-iterative-revision`, invariant #9).
10. После шага VERIFY изменены только разрешённые файлы: roadmap + stg-файлы,
   review-артефакты `plan-iterative-revision`, `<base>-stg00-verify-baseline.json`
   и `<base>-stg00-verify-ledger.json`; оригинал плана имеет тот же SHA-256,
   что до запуска скилла.
11. Проверяемые стадии нельзя объявлять готовыми, пока
   `splitter_tool.py verify-status` не завершится с exit 0. `missing` stage
   re-dispatch один раз, затем блок; `inconsistent` stage блокирует сразу.

## Prerequisites

- Python ≥ 3.8 в PATH (для `scripts/splitter_tool.py`, без сторонних зависимостей).
- `<SKILL_DIR>` — каталог, содержащий этот `SKILL.md`. Всегда использовать абсолютный путь
  при вызове скрипта: `python "<SKILL_DIR>/scripts/splitter_tool.py" ...`.
- Для шага 8 (deep verification) требуется скилл `plan-iterative-revision`,
  установленный рядом: `<SKILL_DIR>/../plan-iterative-revision/`. Если его нет —
  шаг 8 недоступен; сообщить пользователю и завершиться после шага 7.

## Algorithm (high-level)

```
1. BOOTSTRAP
   - Прочитать план; вычислить dir, base_name.
   - detect-lang → lang.
   - preflight <dir> <base_name>:
     * writable=false → стоп, сообщить пользователю.
     * existing непустой → запомнить warning для шага 5.

2. GATE DECISION + ОТЧЁТ (см. references/GATE-DECISION.md)
   - Оценить по 5 факторам и сообщить пользователю решение (головной отчёт).
   - «Не разбивать» → вывести assets/gate-pass.<lang>.md, выход (это не ошибка).
   - «Разбивать» → шаг 3.

3. ANALYSIS
   - Эвристики границ стадий (references/STAGE-FORMAT.md).
   - Граф зависимостей; parallel groups; веса 🔴/🟡/🟢.
   - Подготовить структуру для каждой стадии.

4. DRAFT & CONFIRM
   - Показать пользователю таблицу разбиения.
   - При отклонении: один retry → шаг 3 с feedback.
   - При повторном отклонении: выход.

5. CONFLICT CHECK + GENERATE FILES
   - Если есть existing — спросить (overwrite/rename/abort).
   - Записать <base>-stg00-roadmap.md (assets/roadmap-template.<lang>.md).
   - Записать <base>-stg01.md ... stgN.md (assets/stage-template.<lang>.md).
   - Имена файлов: `splitter_tool.py stage-name <base> <N>`.

6. VERIFY (трёхуровневая)
   - A: splitter_tool.py validate-all <dir> <base>
   - B: автоматически входит в validate-all (coverage + original hash)
   - C: агент перечитывает stg-файлы → self-sufficiency, контекст, handoff,
        непротиворечивость с roadmap.
    - validate-stage возвращает granularity_warning → если стадия > 15 задач,
       поднять мягкое предупреждение (не блокирует; рекомендовать перезапуск splitter на ней).
       Для получения этого предупреждения на уровне C агент запускает validate-stage per-file
       дополнительно к validate-all.
   - Дефекты → исправить, повторить (max 3 итерации).
   - ОК → перейти к шагу 7.

7. DONE NOTICE / VERIFY CHOICE
    - Предложить глубокую проверку: вывести assets/verify-prompt.<lang>.md.
    - Спросить scope (рантайм): all / подмножество stgNN / none.
       * Неинтерактивный вызов: использовать аргумент verify (ask→считать none, если ответа нет).
    - Если none → вывести assets/completion.<lang>.md и выйти.
    - Если scope ≠ none → НЕ выводить финальное «готово» для проверяемых стадий до зелёного шага 8.

8. GATED DEEP VERIFICATION (только при scope ≠ none; см. references/WORKFLOW.md)
    - Записать baseline snapshot: `splitter_tool.py verify-baseline <dir> <base> --stages <selected>`
      → `<base>-stg00-verify-baseline.json`.
    - Инициализировать `<base>-stg00-verify-ledger.json` и после каждого `runSubagent`
      делать read-modify-write/upsert `stages[stgNN]`.
    - Для каждой выбранной стадии — ПАРАЛЛЕЛЬНО:
       * runSubagent(plan-iterative-revision):
             plan=<dir>/<base>-stgNN.md, interaction=autonomous,
             preset=<глубина>, mode=<verify_mode: full-cycle по умолчанию>
       * Subagent возвращает JSON: {result, iterations, remaining_issues}.
    - После batch выполнить `splitter_tool.py verify-status <dir> <base> --baseline <baseline> --ledger <ledger> --validator <SKILL_DIR>/../plan-iterative-revision/scripts/next_review_index.py --stages <selected>`.
    - `missing` → re-dispatch один раз и повторить gate; `inconsistent` → hard-stop;
      exit 0 → вывести assets/verify-summary.<lang>.md и только затем completion/done.
```

Полный алгоритм со всеми деталями — `references/WORKFLOW.md`.

## VERIFY — три уровня проверки

### Уровень A: формальная (автоматизируемая)

`python "<SKILL_DIR>/scripts/splitter_tool.py" validate-all <dir> <base_name>` проверяет:
- Все stg-файлы из таблицы roadmap существуют на диске.
- Каждый файл проходит `validate-stage` (обязательные секции).
- Roadmap проходит `validate-roadmap`.
- Граф — DAG (нет циклов).
- Все `depends` указывают на реальные стадии.
- Стадии в одной parallel group не зависят друг от друга.
- `validate-stage` дополнительно отдаёт `granularity_warning` (мягкое; стадия > 15 задач).

### Уровень B: cross-validation (автоматизируемая)

Тот же `validate-all` дополнительно:
- Сумма задач в stg-файлах ≥ числу задач в оригинале.
- SHA-256 оригинала фиксируется; агент должен убедиться, что он не менялся.

### Уровень C: содержательная (агент)

Агент перечитывает каждый stg-файл и проверяет:
- **Self-sufficiency**: нет back-references «см. выше», «как в оригинале», «предыдущий пункт».
- **Контекст**: цель стадии понятна без чтения оригинала.
- **Handoff**: «Выходные данные» stgX точно покрывают «Входные данные» stgY, где Y depends on X.
- **Непротиворечивость**: информация в stg-файлах не конфликтует с roadmap (depends, group, weight).

Если найдены дефекты — агент правит файлы и повторяет VERIFY (максимум 3 итерации, потом выход с warning).

## Output

При успехе — `assets/completion.<lang>.md` с подстановками. При gate-pass — `assets/gate-pass.<lang>.md`. При любом аварийном выходе — внятное сообщение пользователю с причиной и подсказкой действий.

## See also

- `references/WORKFLOW.md` — полный алгоритм со всеми деталями.
- `references/GATE-DECISION.md` — критерии «разбивать / не разбивать».
- `references/STAGE-FORMAT.md` — формат stg-файлов и правила деривации.
- `references/ROADMAP-FORMAT.md` — формат roadmap-файла и parallel groups.
- `scripts/splitter_tool.py` — CLI: preflight, stage-name, detect-lang, validate-*, verify-baseline, verify-status, hash.
- Шаг 8 делегирует глубокую проверку через `runSubagent(plan-iterative-revision, interaction=autonomous, preset=<глубина>)`, но завершает её только через `verify-status` gate — см. `references/WORKFLOW.md`.
