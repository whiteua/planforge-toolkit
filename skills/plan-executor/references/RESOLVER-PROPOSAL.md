# RESOLVER-PROPOSAL

## Finalize Proposal

When all units are done, propose a final `plan-resolver` pass. The executor never performs the audit decision silently and `никогда автоматически` запускает resolver.

Present the completed ledger summary and ask the engineer to choose one option.

## Options

- `all`: run `plan-resolver` on the full plan and all completed stages.
- `subset`: run `plan-resolver` only on selected units or changed areas.
- `skip`: do not run resolver now; keep `state.json` and `progress.md` as execution records.
