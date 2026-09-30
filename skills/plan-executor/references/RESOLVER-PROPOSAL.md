# RESOLVER-PROPOSAL

When all units are done, present the ledger summary and propose a `plan-resolver` pass. The executor never launches the resolver itself; the engineer chooses:

- **audit** — `/plan-resolver <master-plan>`: one audit report.
- **audit + fix** — `/plan-resolver <master-plan> auto`: audit, fix code from the report, re-audit (up to 2 cycles).
- **skip** — keep `state.json` and `progress.md` as the execution record.

`<master-plan>` is the plan the units came from. For staged input it is the original plan the roadmap was split from (`<base>.md` next to `<base>-roadmap.md`), never the roadmap itself.
