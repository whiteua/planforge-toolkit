# Fix Loop

`fix`, `next` and `auto` add a FIX phase: repairing the **code** from an open report. AUDIT stays
the read-only pass of [WORKFLOW.md](WORKFLOW.md); FIX and AUDIT never mix in one phase.

## Modes

| Command | Behaviour |
|---|---|
| `<plan> fix` | one cycle: FIX from the last open report → AUDIT → stop |
| `<plan> next` | alias of `fix`, suggested after `auto` stops |
| `<plan> auto [limit]` | AUDIT (when no open report exists) → up to `limit` cycles of FIX → AUDIT; default `2` |

`<plan>` may be omitted for `fix`/`next`: use the plan of the conversation, else
`discover <workspace-root>` without a plan. Exit `0`: the single candidate; exit `1`: none or
several (`candidates`, plus `skipped` directories with an open report but no unique plan file):
show them and ask.

## Start

1. `discover <workspace-root> <plan>` → `plans_list`, `last_report`, `state`.
2. `closed` → say the plan is closed, write nothing.
3. `none` → `fix`/`next`: run a normal AUDIT (report 1) and stop, nothing to fix yet;
   `auto`: run AUDIT; if it is `-final`, finish.
4. `open` → the cycle.

## Cycle

```text
cycle = 1
loop:
  issues = open-issues LAST_REPORT
  if issues.blocked_by_drift: stop, action = ask-user   # the last audit was invalidated by workspace drift
  FIX(LAST_REPORT)
  if no issue got `applied`: stop, action = ask-user
  discover <workspace-root> <plan>
  AUDIT(plans_list)                        # subsequent pass → NEW_REPORT
  cycle-check LAST_REPORT NEW_REPORT cycle limit
  continue → LAST_REPORT = NEW_REPORT; cycle += 1; loop
  otherwise → stop, human gate
```

`fix`/`next` pass `cycle=1 limit=1`: any action but `complete` means stop and suggest `next`.

## FIX phase

1. `open-issues <LAST_REPORT>` → `fix_order` (critical → low) and compact issue fields; the JSON is
   enough, do not re-read the whole report. Then, before any fingerprint, the journal start
   (WORKFLOW.md, Chain journal): stage `audit` → `running` with `--reason audit-open`.
2. `protect <tmp-json> <plan> <all reports>` and `fingerprint-workspace <workspace-root> <fix-start-json>`
   (temp paths outside the workspace; `--base <last audit's current snapshot>` is optional and
   only saves rehashing).
3. For each issue in `fix_order`: read the code at `evidence` and the linked plan items; make the
   minimal change that closes the plan's contract, no refactoring of neighbouring code; run the
   existing read-only probe for the area if there is one; note the outcome: `applied`,
   `needs-user` or `skipped` (reason in the note).
4. `assert-protected <tmp-json>`: exit `1` → revert your edits to protected files if possible, mark
   the affected issues `needs-user`, stop.
5. `fingerprint-workspace <workspace-root> <fix-end-json> --base <fix-start-json>` and
   `snapshot-diff <fix-start-json> <fix-end-json>`: the authoritative list of changed files.
   Every changed path must belong to an `applied` issue; an unexplained change is reverted or
   reported to the user.
6. `mark-fix <LAST_REPORT> <id> <state> --files <paths from the diff> [--note ...]` per issue: the
   only allowed change to a past report, and it touches only the Fix Log.
7. Record every path of the diff as `fix_files` of the `audit` stage, as a repository-root path
   (WORKFLOW.md, Chain journal, FIX), so plan-executor's `commit` stage commits these fixes.

`needs-user`, not a fix, when: the issue means the plan itself is wrong or contradictory; the fix
needs a product or architecture choice the plan does not make; it needs dependency installs,
real-data migrations, secrets or external services.

## FIX invariants

- The master plan never changes; past reports change only through `mark-fix`.
- No git mutations, installs, migrations or destructive commands; changes stay uncommitted in the
  working tree for review.
- `applied` is the implementer's claim, not proof. Only the next AUDIT closes an issue
  (`✅ fixed` in the new report).

## AUDIT after FIX

Run AUDIT strictly by WORKFLOW.md with a new start fingerprint taken **after** FIX
(`--base` = the previous audit's current snapshot). Prefer a fresh subagent
(`/plan-resolver <plans_list...>`) so the audit does not inherit the fixer's confidence; otherwise
audit inline, re-reading the code rather than relying on memory of the edits.

## Stop and human gate

| `cycle-check.action` | Message |
|---|---|
| `complete` | path of the `-final` report; plan closed |
| `continue` | (`auto` only) next cycle, no question |
| `ask-user` | only `needs-user` issues remain (or the audit was blocked by drift): list the questions |
| `stop-stalled` | the cycle closed nothing; `claimed_not_fixed_ids`; manual review needed |
| `stop-limit` | cycle limit reached; open issues; `/plan-resolver <plan> next` |

Order of precedence: `complete` → `ask-user` → `stop-stalled` → `stop-limit` → `continue`.
The summary always lists the reports created, closed and open issues, and the changed files from
the Fix Log.

Every gate names the commit: `/plan-executor <plan> commit` commits the executor run's files and
the recorded `fix_files`; the resolver itself never commits. Without a confirmation channel,
`ask-user`, `stop-stalled` and `stop-limit` are recorded as a `journal-question` with the
decision they need (WORKFLOW.md, Chain journal): the audit that ended the cycle already set the
stage `done`, so first `journal-event … --stage audit --status running --reason audit-open` (the
report is open), then the question (the stage becomes `stopped`), then
`journal-export-findings`, then stop. The next start answers or stops on that question before
anything else.
