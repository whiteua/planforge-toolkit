# Probes

Probes — дополнительные проверки, которые можно запускать только если они read-only для проекта.

## Allowed

- `python -m unittest ...`, если тесты не пишут snapshots/generated files.
- `pytest ...`, если конфигурация не создаёт/не обновляет артефакты в workspace.
- `npm test -- --runInBand` или аналогичный read-only test command, если он уже есть в проекте.
- `npm run build`, `go test`, `cargo test`, `dotnet test` только если команда не меняет tracked/source files.
- Static commands: `python -m py_compile`, `tsc --noEmit`, `eslint` без `--fix`.

## Forbidden

- format/autofix: `black`, `ruff --fix`, `eslint --fix`, `prettier --write`, `go fmt`.
- install/update: `npm install`, `pip install`, `poetry update`, `cargo update`.
- generators/migrations that write files.
- `git add/commit/reset/checkout/clean`.
- любой probe, который требует интерактивного подтверждения и может изменить проект.

## Probe Gate

- Если готовый read-only probe уже существует, агент обязан запустить его и записать exit code в evidence.
- Побочные эффекты запрещены. Blacklist verbs: `migrate`, `seed`, `build`, `deploy`, `install`, `generate`, `git`.
- Whitelist verbs: `test`, `check`, `lint`, `type`.
- Safe default: нераспознанная команда (`npm run validate`, `cargo clippy`) НЕ запускается автоматически; задача получает `probe-needed`.
- Если готового read-only probe нет, агент НЕ генерирует probe самостоятельно; задача получает `probe-needed`.

## Recording Probe Results

Падение read-only probe становится issue только если оно связано с задачей плана. В evidence нужно
записать команду, exit code и короткий фрагмент stderr/stdout; полный лог в отчёт не вставлять.
