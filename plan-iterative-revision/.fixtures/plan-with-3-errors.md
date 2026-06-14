# Dogfooding Plan With Three Deliberate Errors

## Goal

Exercise Phase A issue detection with exactly three expected findings: one logic issue, one database issue, and one API contract issue.

## Iteration Limit

The skill must run 7 iterations before asking the user whether to continue.

## Conflicting Iteration Rule

The skill must stop after 5 iterations without asking the user.

## Database Change

Add table `review_runs` with columns `id`, `plan_path`, `created_at`, and `status`. Query all rows by `plan_path` on every audit. No index is needed because the table is expected to remain small.

## API Contract

Expose an endpoint `POST /api/plan-review/start` that accepts `planPath` as a query parameter and returns `204 No Content` with a JSON body containing `{ "reviewId": "..." }`.

## Expected Dogfooding Findings

1. Logic: iteration limit is both 7 and 5.
2. DB: querying by `plan_path` without an index is unsafe as the table grows.
3. Contract: `204 No Content` cannot include a JSON response body.
