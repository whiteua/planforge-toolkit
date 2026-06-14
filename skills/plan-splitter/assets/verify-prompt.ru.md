Хотите запустить глубокую проверку микропланов через plan-iterative-revision?

- Что проверять (scope): `all` — все стадии · `stgNN[,stgNN...]` — выбранные · `none` — пропустить.
- Глубина: `quick` (быстро) · `standard` · `deep` (тщательно).
- Режим: `full-cycle` (правит стадии, по умолчанию) · `audit-only` (только отчёт).

Проверка идёт молча (Silent); по завершении покажу сводку.

--- Subagent contract ---

Каждый subagent ОБЯЗАН:
- прочитать `plan-iterative-revision/SKILL.md`;
- выполнить именно этот скилл с `interaction=autonomous`, выбранным `preset` и режимом `full-cycle` или `audit-only`;
- работать только с переданным файлом `stgNN.md` и его review-артефактами;
- вернуть строго JSON: `{"result":"clean|converged|stagnation|limit|escalated","iterations":N,"remaining_issues":N}`.

Запрещено:
- заменять `plan-iterative-revision` ручным/ad-hoc аудитом;
- задавать вызывающему агенту A/B/C или любые интерактивные вопросы;
- использовать `audit-only` как shortcut для обхода review-артефакта;
- сообщать успех без артефактов, требуемых `plan-iterative-revision` и машинным ledger.