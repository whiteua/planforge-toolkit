# Tooling

Все команды находятся в `scripts/resolver_tool.py` (относительно директории скилла `<SKILL_DIR>`) и используют только Python stdlib.

## Commands

```text
python "<SKILL_DIR>/scripts/resolver_tool.py" bootstrap <workspace-root> <plan> [reports...]
python "<SKILL_DIR>/scripts/resolver_tool.py" preflight <plan-dir> <next-open-name> <next-final-name>
python "<SKILL_DIR>/scripts/resolver_tool.py" fingerprint-workspace <root> <out-json> [--base <prev-json>]
python "<SKILL_DIR>/scripts/resolver_tool.py" parse-report <report.md>
python "<SKILL_DIR>/scripts/resolver_tool.py" validate-report <report.md>
python "<SKILL_DIR>/scripts/resolver_tool.py" assert-readonly <start-json> <current-json> <allowed-path>
python "<SKILL_DIR>/scripts/resolver_tool.py" iteration-check <last-report> [limit]
python "<SKILL_DIR>/scripts/resolver_tool.py" task-census <plan> <report>
```

Fix loop ([FIX-LOOP.md](FIX-LOOP.md)):

```text
python "<SKILL_DIR>/scripts/resolver_tool.py" discover <workspace-root> [plan]
python "<SKILL_DIR>/scripts/resolver_tool.py" open-issues <report>
python "<SKILL_DIR>/scripts/resolver_tool.py" protect <out-json> <path>...
python "<SKILL_DIR>/scripts/resolver_tool.py" assert-protected <snapshot-json>
python "<SKILL_DIR>/scripts/resolver_tool.py" mark-fix <report> <issue-id> applied|needs-user|skipped [--files F...] [--note TEXT]
python "<SKILL_DIR>/scripts/resolver_tool.py" cycle-check <prev-report> <new-report> <cycle> [limit=2]
```

- `discover` с планом → `plans_list`, `last_report`, `state` (`none|open|closed`); без плана →
  `candidates` (планы с открытым последним отчётом), exit `1` если кандидатов не ровно один.
- `open-issues` → `fix_order` (critical → low) и поля `id/level/status/title/linked_items/evidence/description/recommendations`.
- `mark-fix` upsert'ит строку в `## Журнал исправлений` / `## Fix Log`; exit `1` для `-final`,
  неизвестной или уже `fixed` ошибки.
- `cycle-check.action`: `complete | continue | stop-limit | stop-stalled | ask-user`.

## Exit Codes

- `0` — команда успешна;
- `1` — проверка выполнена, но контракт не соблюдён (`validate-report`, `assert-readonly`, `assert-protected`, `task-census`, `mark-fix`, target exists);
- `2` — входные данные/файловая система некорректны;
- `64` — `bootstrap` обнаружил последний `-final` отчёт, новых проходов не требуется.

## Temp Fingerprints

Агент создаёт путь через `tempfile.mkstemp(prefix="fp-", suffix=".json", dir=tempfile.gettempdir())`,
закрывает fd и передаёт путь в `fingerprint-workspace`. Путь обязан находиться вне `WORKSPACE_ROOT`.
