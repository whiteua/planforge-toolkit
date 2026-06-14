# Dogfooding Plan With Stuck Error

## Goal

Exercise stagnation detection: if the same issue fingerprint appears in two consecutive audits, the cycle must stop with the stagnation verdict instead of looping forever.

## Deliberately Unresolvable Contract

The plan must require `review-result` to be both immutable and editable in Phase B. This contradiction is intentionally preserved for this fixture.

## Phase Rules

- Phase A must never edit the master plan.
- Phase B must edit the master plan to apply review contracts.
- The `review-result` section is immutable and must never be changed.
- The `review-result` section must be changed on every Phase B run.

## Expected Dogfooding Finding

The contradiction around `review-result` should produce a stable issue fingerprint. If Phase B cannot resolve it and the same issue is found again, the workflow must report stagnation.
