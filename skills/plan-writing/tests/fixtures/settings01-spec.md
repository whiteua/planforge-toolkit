> Tier: Standard
> Chain: split=never; resolver=skip
> Environment: `dev_db` (test) — read=run, write=task — "Run the smoke test on dev_db? — Yes, reads for the whole run, changes per task" (2026-10-01)
> Environment: `prod_db` (prod) — read=run, write=deny — "Read prod_db to compare counts? — Yes, read only" (2026-10-01)
> Backlog: verbose-flag

# Goal

`cli.py --verbose` is smoke-tested on the test database and compared with production counts.

## Architecture

Two test modules run against named environments; no production code changes.

## Components

- `tests/test_smoke.py`: loads two rows into `dev_db` and runs the CLI.
- `tests/test_counts.py`: reads one count from `prod_db`.

## Data Flow

Test fixture rows → `dev_db` → `cli.py --verbose` → assertion; `prod_db` → count → assertion.

## Error Handling

(none) — the tests add no runtime failure modes.

## Testing Strategy

The smoke test on `dev_db` and the read-only count on `prod_db` are the whole plan.

## Out of Scope

- Any change on `prod_db`.

## Open Questions

(none)
