# Phase B: Implement

Goal: apply every contract of the review just written by `record` to `PLAN`. Edit only `PLAN`.

## Inputs

- `R.review_path`: the review to apply. Read it once.
- `R.issues`: ids in application order (blocker → major → minor → nit, then plan order).
- `R.budget`: the plan's room in the budget of 150 000 bytes (`headroom_bytes`, `limit`; Budget below), `null` without plan-brainstorming alongside.

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

## Budget

A plan over 150 000 bytes costs every later stage more, and a chain stops on it (spec 1 of plan-refactoring-04).
With `R.budget.limit` `on`:

- Keep a running sum of `bytes(new_string) − bytes(old_string)` (UTF-8 bytes) over your edits. Before an issue,
  estimate what its edits add; when the sum would go over `R.budget.headroom_bytes`, apply the issue in fewer words
  (the contract still holds), or skip it as deferred with the reason `budget`.
- Remember the ids you deferred for the budget: the loop passes them to the next `record` as
  `--deferred "<id>:budget,…"` (SKILL.md, Loop), which writes `[<id>] deferred: budget` into the next review and keeps
  the issue open.

`limit: off` (the plan was over the budget before this revision; `record` warned `oversized-before-revision`) or
`R.budget: null`: no limit, apply every issue; the size is left to the splitter's gate or the runner's
`plan-oversized:` question.

After Phase B, `guard-check` returns `plan_bytes_before`, `plan_bytes_after`, `changed_tasks` and `over_budget`.
`over_budget: true` (the edits took the plan over the budget) → one compression pass in a new guard window (SKILL.md,
Loop): shorten only the text of the tasks in `changed_tasks` — repeated sentences, restated context, prose the code
already says — never a contract of this review, never what a code block does; then stop, even when the plan is still
over.

## Self-check

After the last issue, read only the tasks your edits changed (each by its `### Task N:` heading, the
header when you edited it), never the whole plan, and check each applied issue's `Acceptance`. Allow
one repair attempt per failed check; otherwise count the issue as deferred.

In interactive mode, report in one line: applied ids, deferred ids with a short reason (`budget` for the ones deferred for the budget) (autonomous
mode prints nothing here). Keep no counters: the next audit
carries unapplied contracts (Phase A, Step 1), and `record` stops the loop when an issue stays
stuck or nothing changes.
