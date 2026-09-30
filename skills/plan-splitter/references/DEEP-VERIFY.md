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

1. Baseline: `TOOL verify-baseline DIR BASE --stages <scope> --out DIR/<BASE>-verify-baseline.json`.
   `all` takes the parts from the roadmap table. Both verify JSONs live in `DIR`, next to the parts.
2. Dispatch one subagent with this prompt (fill the placeholders):

   ```
   You are a plan verification agent. Read the skill at:
   <REV_SKILL>
   Run exactly that skill in batch mode on the roadmap:
   <DIR>/<BASE>-roadmap.md
   with interaction=autonomous, preset=<verify_depth>, mode=<verify_mode><, parts=a,c when the
   scope is a list; nothing for all>.
   Parts are verified one after another; each gets its own review trail.

   Forbidden: replacing the skill with an ad-hoc audit; asking the caller any question;
   using audit-only as a shortcut around the review artifacts; reporting success without them.

   Return the batch JSON the skill prints, unchanged (extra fields are fine):
   {"result": "...", "remaining_issues": N, "counts": {...},
    "parts": {"<id>": {"result": "clean|converged|stagnation|limit|escalated",
                       "iterations": N, "remaining_issues": N, "stop_reason": ..., "escalated": [...]}}}
   ```

   Save the returned JSON to a temp file outside the repository. A subagent failure is
   recorded, not hidden: for parts without a result write
   `{"parts": {"<id>": {"result": null, "error": "<text>"}}}`; the gate reports them as `missing`.
   A dispatch that returns nothing at all counts the same way. Before the one allowed
   re-dispatch, run `verify-baseline` again and compare it with the saved baseline: identical →
   re-dispatch; different (the dead subagent left reviews or edited parts) → stop and report.
3. Record: `TOOL verify-record DIR BASE --results <json-file|-> --ledger DIR/<BASE>-verify-ledger.json --mode <verify_mode>`.
   The tool upserts one ledger entry per part and counts attempts.
4. Gate: `TOOL verify-status DIR BASE --baseline DIR/<BASE>-verify-baseline.json --ledger DIR/<BASE>-verify-ledger.json --validator <VALIDATOR> --stages <scope>`
   (with `all`, the gate covers the parts present in the baseline).
5. `full-cycle` only, after the gate passed: the parts were edited, so run `TOOL validate-all DIR BASE`
   again and re-check the handoff (outputs of X still cover the inputs of every Y that depends
   on X). A failure here is fixed like a step-6 defect.

## Verdicts (from `verify-status`)

| Verdict | Meaning | Action |
|---|---|---|
| `satisfied` | `clean` with no new files and an unchanged part, or `converged` with a validated review, a changed part, `full-cycle` and 0 remaining issues | ok |
| `satisfied_with_warning` | validated review but remaining issues, `audit-only`, or `stagnation`/`limit`/`escalated` | ok, listed under warnings in the summary |
| `missing` | no ledger entry, or an entry without a result (recorded failure) | re-dispatch those parts once (steps 2-4); still missing → stop |
| `inconsistent` | the ledger claims something the files do not show (e.g. `converged` without a validated review) | stop, name the parts and the reason |

Every new review file is validated with `next_review_index.py validate-review --strict-fingerprint`.

`exit 0` → print `assets/verify-summary.<LANG>.md` with one row per part (result, iterations =
review files written, remaining, verdict, stop reason or `—`), then `assets/completion.<LANG>.md`
and one line listing the verification artifacts now in `DIR` (the two verify JSONs, the review
and completion files) and, in `full-cycle`, that the parts were edited. The "all clean" block is
for all verdicts `satisfied`; otherwise the warnings block. Any other exit → no "done".

If the same issue was found in several parts, it comes from the source plan: say so and
recommend running `plan-iterative-revision` on the source plan before the next split.
