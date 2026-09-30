# Phase B: Implement

Goal: apply every contract of the review just written by `record` to `PLAN`. Edit only `PLAN`.

## Inputs

- `R.review_path`: the review to apply. Read it once.
- `R.issues`: ids in application order (blocker → major → minor → nit, then plan order).

## Apply

For each issue, in order:

1. Locate the target by `Location in plan` in the plan text you have.
2. `Edit` with the smallest `old_string` that is unique, and a `new_string` that satisfies the
   `Required fix (contract)`. One issue can take several edits, but one edit never mixes issues.
3. If the edit fails (text not found or not unique), `Read` that section again and retry once.
   If it fails again, skip the issue (deferred). Never guess a "similar" `old_string`: a wrong
   replacement is worse than a deferred issue.

Rules:

- The review is read-only. If a contract is ambiguous, apply the change that follows it most
  closely, or skip it; the next audit will re-check it.
- A contract that asks for a new file or a code change becomes a step in the plan. You do not
  create files or change code.
- Keep the plan consistent with each change: summaries, lists or goals that restate the fixed
  text are updated as part of the same issue. Formatting damage caused by your own edit is
  repaired as part of that issue too.

## Self-check

After the last issue, read the changed parts of the plan (the whole plan if edits were spread out)
and check each applied issue's `Acceptance`. Allow one repair attempt per failed check; otherwise
count the issue as deferred.

In interactive mode, report in one line: applied ids, deferred ids with a short reason (autonomous
mode prints nothing here). Keep no counters: the next audit
carries unapplied contracts (Phase A, Step 1), and `record` stops the loop when an issue stays
stuck or nothing changes.
