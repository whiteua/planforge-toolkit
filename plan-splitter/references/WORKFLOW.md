# WORKFLOW — полный алгоритм plan-splitter

## Аргументы

Скилл принимает **один обязательный** позиционный аргумент, **один опциональный**
позиционный аргумент и опциональные именованные аргументы:

1. **Путь к файлу плана** (обязательный) — относительный или абсолютный,
   напр. `docs/plans/plan01-modernization.md`.
2. **Модель для ревизии** (опциональный) — имя модели для subagent-ревизии на шаге 8.
   Если не указан — используется значение из `## Defaults` в SKILL.md (дефолт `auto`).

Опциональные именованные аргументы: `verify=ask|all|none` (дефолт `ask`),
`verify_depth=quick|standard|deep` (дефолт `standard`), `verify_mode=full-cycle|audit-only` (дефолт `full-cycle`).

Выводимые величины:
- `dir`            = директория плана
- `base_name`      = имя файла плана без расширения
- `plan_path`      = полный путь к плану (read-only)
- `lang`           = язык плана (`ru`/`en`) по `cyrillic_ratio > 0.05`
- `revision_model` = второй аргумент или дефолт из SKILL.md `## Defaults`

## Алгоритм

```
1. BOOTSTRAP
   - Прочитать план; вычислить dir, base_name, plan_path.
   - Запустить detect-lang → lang.
   - Запустить preflight <dir> <base_name>:
       * Если writable=false → остановиться, сообщить пользователю.
       * Если existing непустой → запомнить warning для шага 5.

2. GATE DECISION + ОТЧЁТ (см. references/GATE-DECISION.md)
   - Оценить план по 5 факторам; сообщить пользователю решение (головной отчёт).
   - Если «не разбивать» → вывести assets/gate-pass.<lang>.md, выход (нормальный исход, не ошибка).
   - Если «разбивать» → перейти к шагу 3.

3. ANALYSIS
   - Определить естественные границы стадий по эвристикам
     (см. references/STAGE-FORMAT.md → «Эвристики границ»).
   - Построить граф зависимостей.
   - Определить parallel groups (см. references/ROADMAP-FORMAT.md).
   - Оценить вес каждой стадии (🔴/🟡/🟢).
   - Сформировать структуру (title, depends, group, weight, summary) для каждой стадии.

4. DRAFT & CONFIRM
   - Показать пользователю структуру разбиения в виде таблицы.
   - Получить подтверждение.
   - При отклонении с feedback: один retry → вернуться к шагу 3 с учётом feedback.
   - При повторном отклонении: выход с сообщением
     «Не удалось согласовать декомпозицию за 2 попытки».
   - Без явного подтверждения — НЕ генерировать файлы.

5. CONFLICT CHECK + GENERATE FILES
   - Если preflight.existing непустой:
       * Спросить пользователя: (а) перезаписать, (б) выбрать другой base/suffix, (в) отмена.
       * Без явного подтверждения — НЕ перезаписывать.
   - Сгенерировать <base_name>-stg00-roadmap.md из assets/roadmap-template.<lang>.md.
   - Сгенерировать <base_name>-stg01.md ... stgN.md из assets/stage-template.<lang>.md.
   - Имена файлов получать через `splitter_tool.py stage-name <base> <N>`.

6. VERIFY (трёхуровневая проверка; см. SKILL.md, секция VERIFY)
   - Уровень A (формальная): `splitter_tool.py validate-all <dir> <base_name>`.
   - Уровень B (cross-validation): автоматически делает validate-all (полнота покрытия + hash).
   - Уровень C (содержательная): агент перечитывает каждый stg-файл и проверяет:
       * self-sufficiency (нет back-references)
       * контекст (стадия понятна без оригинала)
       * handoff (выходы stgX соответствуют входам stgY, где Y depends on X)
       * непротиворечивость с roadmap
   - Для получения granularity_warning агент дополнительно запускает `validate-stage` per-file
     (стадия > 15 задач — мягкое предупреждение, не влияет на valid;
     рекомендовать ручной перезапуск splitter на такой стадии).
   - Если найдены дефекты → исправить файлы и повторить VERIFY (max 3 итерации).
   - Если ОК → перейти к шагу 7.

7. DONE NOTICE / VERIFY CHOICE
   - Предложить глубокую проверку: assets/verify-prompt.<lang>.md.
   - Спросить scope: all / подмножество stgNN / none.
      * Неинтерактивный вызов: брать из аргумента verify; при verify=ask без ответа → none.
   - Если scope = none:
      * Вывести assets/completion.<lang>.md: создано roadmap + N стадий.
      * Выход (сплит — самодостаточный результат).
   - Если scope ≠ none:
      * Финальное «готово» для проверяемых стадий НЕ выводить до зелёного шага 8.
      * Перейти к gated deep verification.

8. GATED DEEP VERIFICATION (только при scope ≠ none)
   - Определить selected stages: all или явный список stgNN.
   - Определить глубину: verify_depth из аргумента или спросить пользователя (интерактивно); при автономном вызове без аргумента — дефолт из Defaults (standard).
   - Определить модель: revision_model (auto → текущая активная; имя — fallback).
   - Определить пути:
      * iter_skill = <SKILL_DIR>/../plan-iterative-revision/SKILL.md
      * validator = <SKILL_DIR>/../plan-iterative-revision/scripts/next_review_index.py
      * baseline = <dir>/<base_name>-stg00-verify-baseline.json
      * ledger = <dir>/<base_name>-stg00-verify-ledger.json
   - До запуска subagents выполнить baseline snapshot:
      * `splitter_tool.py verify-baseline <dir> <base_name> --stages <selected>`
      * stdout записать в baseline как UTF-8 JSON.
   - Инициализировать ledger как UTF-8 JSON:
      * `{ "base_name": <base_name>, "verify_mode": <verify_mode>, "stages": {} }`
   - Если `runSubagent` физически недоступен:
      * НЕ подменять проверку ручным аудитом.
      * Сообщить, что verification не выполнен, оставить файлы и остановиться без финального «done».
   - Для каждой выбранной стадии stgNN — ПАРАЛЛЕЛЬНО (стадии самодостаточны, инвариант #6):
      * stg_path = <dir>/<base_name>-stgNN.md
      * Запустить runSubagent:
        - model: revision_model
        - prompt:
       """
       Ты — агент проверки планов. Прочитай скилл plan-iterative-revision из:
       <iter_skill>
       Выполни именно этот скилл в режиме <verify_mode: full-cycle|audit-only>,
       неинтерактивно (interaction=autonomous), глубина preset=<verify_depth>,
       только на файле:
       <stg_path>

       Запрещено заменять plan-iterative-revision ручным/ad-hoc аудитом.
       Запрещено задавать A/B/C или любые интерактивные вопросы вызывающему агенту.
       Запрещено использовать audit-only как shortcut для обхода review-артефакта.

       По завершении верни строго JSON:
       {"result": "clean"|"converged"|"stagnation"|"limit"|"escalated", "iterations": N, "remaining_issues": N}
       """
      * После КАЖДОГО return немедленно read-modify-write ledger:
        - upsert `stages[stgNN]` = `{verify_mode, result, iterations, remaining_issues, attempts, error}`
        - не append строками и не ждать конца всего батча.
      * Сбой/limit/stagnation/escalated на стадии НЕ прерывает остальной батч; ошибка пишется в ledger.
   - После всех return выполнить gate:
      * `splitter_tool.py verify-status <dir> <base_name> --baseline <baseline> --ledger <ledger> --validator <validator> --stages <selected>`
      * exit 0 → вывести assets/verify-summary.<lang>.md с machine verdict column, затем можно выводить completion/done.
      * Любая стадия `missing` → subagent не вернул доказуемый результат: re-dispatch только missing stages один раз, increment attempts, upsert ledger, повторить verify-status.
      * Если после retry остаётся `missing` → hard-stop, назвать стадии, НЕ выводить «done».
      * Любая стадия `inconsistent` → hard-stop, назвать стадии и причину, НЕ понижать до warning и НЕ выводить «done».
```

## Препятствия и аварийные выходы

| Ситуация | Действие |
|----------|----------|
| `preflight` не writable | Стоп до анализа, сообщить пользователю |
| План не существует/не читается | Стоп, сообщить пользователю |
| 2 отклонения подряд на DRAFT | Выход без генерации файлов |
| 3 итерации VERIFY не сходятся | Выход с warning, файлы оставлены |
| Цикл в графе зависимостей | Стоп на validate-all, не считается успехом |
| Существующие stg-файлы, пользователь сказал «отмена» | Выход без генерации |
| scope = none (проверка не запрошена) | Выход после DONE NOTICE; сплит — готовый результат |
| `runSubagent` недоступен | Не имитировать проверку; сообщить, что verification не выполнен, stop без «done» |
| Subagent упал на одной стадии | Записать error в ledger, остальной батч продолжает; затем `verify-status` решает gate |
| `verify-status` вернул `missing` | Re-dispatch missing stages один раз, increment attempts, повторить gate; затем hard-stop |
| `verify-status` вернул `inconsistent` | Hard-stop, назвать стадии; не понижать до warning и не выводить «done» |
| Stagnation/limit/escalated с валидным review | `satisfied_with_warning`, summary с warning, exit разрешён |
| Все выбранные стадии `satisfied` | verify-summary без warnings, после этого можно выводить completion/done |

## Языковая конвенция

`cyrillic_ratio > 0.05` → `ru`, иначе `en`. Это конвенция экосистемы скиллов; синхронизировать с `plan-iterative-revision`, invariant #9.
