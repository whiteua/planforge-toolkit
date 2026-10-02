# RESOLVER-PROPOSAL

When all units are done, present the ledger summary and the `plan-resolver` step. The executor never launches the resolver itself. If the ledger's `settings` has `chain_explicit: true`, the choice was made in the spec: announce `settings.chain.resolver` in one line in the plan's language (`audit` / `auto` = audit + fix / `skip`) with the command, and do not ask. Otherwise the engineer chooses:

- **audit** — `/plan-resolver <master-plan>`: one audit report.
- **audit + fix** — `/plan-resolver <master-plan> auto`: audit, fix code from the report, re-audit (up to 2 cycles).
- **skip** — keep `state.json` and `progress.md` as the execution record.

`<master-plan>` is the plan the units came from. For staged input it is the original plan the roadmap was split from (`<base>.md` next to `<base>-roadmap.md`), never the roadmap itself.

The proposal gives the resolver what it cannot see in the code:

- the `exec_dir` path (`state.json`, `progress.md`);
- the files this run changed (`run-diff`);
- every unit note (`unit-finish --note`): deviations agreed with the engineer;
- every `external` entry recorded on the units (`state.json` → `units[].external`), prod reads included: environment, read or write, kind, whose permission (`spec`, `session`, or the unit's `notes` entry `External: <env> (<access>) confirmed by the engineer for this task` written by `unit-finish --note`, GATE.md), the command and its result, since the audit will not repeat them without permission; the run-scope `consents`; and the `foreign_events` log (paths changed outside the run between units, `accepted` or `restored`, with the engineer's notes);
- the follow-ups file, if one was written.

The proposal also lists every unit whose final status is not `done` (failed, skipped, still pending) with its `last_error`. The resolver treats these as must-check items: each is reported open or closed with evidence from the code, never silently assumed done.
