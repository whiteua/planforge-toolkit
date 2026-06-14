# Revision 1: validator-sample

**Iteration**: 1
**Audited plan**: validator-sample.md
**Plan SHA-256**: 0000000000000000000000000000000000000000000000000000000000000000
**Plan size**: 100 bytes
**Audited at**: 2026-05-09T00:00:00Z
**Previous review**: none
**Issues found**: 1 (blocker: 0, major: 1, minor: 0, nit: 0)

## Audit state

| Check | Status | Notes |
|---|---|---|
| Previous review contracts checked | n-a | none |
| Taxonomy sweep completed | yes | 10 classes |
| Code cross-check completed | yes | invalid status fixture |
| Review validated | yes | validator fixture |
| Deferred conflicts carried | 0 | none |

## Summary

This fixture uses an invalid Code cross-check status.

## Issues

### [1.1] major · contract · Validator contract check

- **Location in plan**: REVIEW-FILE-FORMAT.md
- **Location in code**: scripts/next_review_index.py
- **Code cross-check**: pending - this is not an allowed status.
- **Problem**:
  The validator must reject invalid Code cross-check vocabulary.
- **Evidence**:
  > Plan quote: Code cross-check has a fixed vocabulary.
- **Required fix (contract)**:
  Update the review validator to enforce required sections and Code cross-check vocabulary.
- **Acceptance**:
  This fixture fails because Code cross-check starts with pending.
- **Fingerprint**: e0171775

## Deferred from previous review

None.

## Notes for implementation

None.
