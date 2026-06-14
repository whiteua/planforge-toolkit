# Clean Dogfooding Plan

## Goal

Verify that `plan-iterative-revision` exits without creating a review file when the plan is internally consistent and does not reference missing project code.

## Scope

- Input: one markdown plan file.
- Output: no review file when no issues are found.
- Review numbering: next index is computed from existing `*-review-N.md` files in the same directory.
- Language: artifact language follows the master plan language; if the plan is English, use English templates.

## Process

1. Read the plan.
2. Compute the next review number.
3. Run Phase A taxonomy sweep.
4. If no issues are found, emit a completion report and do not create a review file.

## Acceptance

- No `clean-plan-review-1.md` file is created.
- Completion report verdict says the plan is clean on first audit.
- No project code is modified.
