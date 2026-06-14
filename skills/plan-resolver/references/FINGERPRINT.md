# Fingerprint

Readonly-guard сравнивает SHA-256 снимок рабочего дерева до и после аудита.

## Algorithm

1. Обойти `WORKSPACE_ROOT` рекурсивно.
2. Исключить записи из корневого `.gitignore` и фиксированный список ниже.
3. Для каждого файла посчитать SHA-256 содержимого. `mtime` и `size` не используются как замена.
4. Сохранить сортированный JSON `{path: sha256}` во временный файл вне workspace.
5. Если после исключений больше 200 000 файлов — остановиться до аудита и попросить сузить scope.

## Fixed Exclusions

- `node_modules`
- `.git/objects`
- `__pycache__`
- `dist`
- `build`
- `target`
- `out`
- `bin`
- `obj`
- `.next`
- `.gradle`
- `.venv`
- `venv`

## Allowed Diff

После записи отчёта допустим только один изменённый путь: выбранный `NEXT_REPORT`.
Любой другой added/removed/modified путь превращается в blocker `probe-mutated-workspace`.
