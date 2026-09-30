# Deep Verification (step 8)

Verifies the generated parts with `plan-iterative-revision` and accepts the result only through
the machine gate `verify-status`. Read this before step 8.

## Preconditions

- `plan-iterative-revision` is installed at `<SKILL_DIR>/../plan-iterative-revision/`
  (`REV_SKILL` = its `SKILL.md`, `VALIDATOR` = its `scripts/next_review_index.py`).
- A subagent tool is available. Without one, do not imitate the verification: say it was not run,
  keep the files, and do not print "done" for the selected parts.
- `scope` is `all` or a part list; `verify_depth` and `verify_mode` are resolved.

## Steps

1. Baseline: `TOOL verify-baseline DIR BASE --stages <scope>`; save stdout as
   `<BASE>-verify-baseline.json` (UTF-8). `all` takes the parts from the roadmap table.
2. Dispatch one subagent with this prompt (fill the placeholders):

   ```
   You are a plan verification agent. Read the skill at:
   <REV_SKILL>
   Run exactly that skill in batch mode on the roadmap:
   <DIR>/<BASE>-roadmap.md
   with interaction=autonomous, preset=<verify_depth>, mode=<verify_mode>, parts=<scope>.
   Parts are verified one after another; each gets its own review trail.

   Forbidden: replacing the skill with an ad-hoc audit; asking the caller any question;
   using audit-only as a shortcut around the review artifacts; reporting success without them.

   Return exactly the batch JSON the skill prints:
   {"result": "...", "remaining_issues": N, "counts": {...},
    "parts": {"<id>": {"result": "clean|converged|stagnation|limit|escalated",
                       "iterations": N, "remaining_issues": N, "stop_reason": ..., "escalated": [...]}}}
   ```

   A subagent failure is recorded, not hidden: save whatever JSON came back (or
   `{"parts": {"<id>": {"result": null, "error": "<text>"}}}` for parts without a result).
3. Record: `TOOL verify-record DIR BASE --results <json-file|-> --ledger <BASE>-verify-ledger.json --mode <verify_mode>`.
   The tool upserts one ledger entry per part and counts attempts.
4. Gate: `TOOL verify-status DIR BASE --baseline <BASE>-verify-baseline.json --ledger <BASE>-verify-ledger.json --validator <VALIDATOR> --stages <scope>`.

## Verdicts (from `verify-status`)

| Verdict | Meaning | Action |
|---|---|---|
| `satisfied` | `clean` with no new files and an unchanged part, or `converged` with a validated review, a changed part, `full-cycle` and 0 remaining issues | ok |
| `satisfied_with_warning` | validated review but remaining issues, `audit-only`, or `stagnation`/`limit`/`escalated` | ok, listed under warnings in the summary |
| `missing` | no ledger entry or no result for the part | re-dispatch those parts once (steps 2-4); still missing → stop |
| `inconsistent` | the ledger claims something the files do not show (e.g. `converged` without a validated review) | stop, name the parts and the reason |

Every new review file is validated with `next_review_index.py validate-review --strict-fingerprint`.

`exit 0` → print `assets/verify-summary.<LANG>.md` with one row per part (result, iterations,
remaining, verdict, stop reason), then `assets/completion.<LANG>.md`. Any other exit → no "done".
