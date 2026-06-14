# Tooling

Все команды находятся в `scripts/resolver_tool.py` (относительно директории скилла `<SKILL_DIR>`) и используют только Python stdlib.

## Commands

```text
python "<SKILL_DIR>/scripts/resolver_tool.py" bootstrap <workspace-root> <plan> [reports...]
python "<SKILL_DIR>/scripts/resolver_tool.py" preflight <plan-dir> <next-open-name> <next-final-name>
python "<SKILL_DIR>/scripts/resolver_tool.py" fingerprint-workspace <root> <out-json>
python "<SKILL_DIR>/scripts/resolver_tool.py" parse-report <report.md>
python "<SKILL_DIR>/scripts/resolver_tool.py" validate-report <report.md>
python "<SKILL_DIR>/scripts/resolver_tool.py" assert-readonly <start-json> <current-json> <allowed-path>
python "<SKILL_DIR>/scripts/resolver_tool.py" iteration-check <last-report> [limit]
```

## Exit Codes

- `0` — команда успешна;
- `1` — проверка выполнена, но контракт не соблюдён (`validate-report`, `assert-readonly`, target exists);
- `2` — входные данные/файловая система некорректны;
- `64` — `bootstrap` обнаружил последний `-final` отчёт, новых проходов не требуется.

## Temp Fingerprints

Агент создаёт путь через `tempfile.mkstemp(prefix="fp-", suffix=".json", dir=tempfile.gettempdir())`,
закрывает fd и передаёт путь в `fingerprint-workspace`. Путь обязан находиться вне `WORKSPACE_ROOT`.
