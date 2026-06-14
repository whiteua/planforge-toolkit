# Revision 1: validator-sample

**Iteration**: 1
**Audited plan**: validator-sample.md
**Plan SHA-256**: 0000000000000000000000000000000000000000000000000000000000000000
**Plan size**: 100 bytes
**Audited at**: 2026-05-09T00:00:00Z
**Previous review**: none
**Issues found**: 1 (blocker: 0, major: 1, minor: 0, nit: 0)

## Summary

This fixture is missing the required Audit state section.

## Issues

### [1.1] major · contract · Validator contract check

- **Location in plan**: REVIEW-FILE-FORMAT.md
- **Location in code**: scripts/next_review_index.py
- **Code cross-check**: verified - validator implementation is present.
- **Problem**:
  The validator must enforce the documented review contract.
- **Evidence**:
  > Plan quote: Validator checks the review format.
- **Required fix (contract)**:
  Update the review validator to enforce required sections and Code cross-check vocabulary.
- **Acceptance**:
  This fixture fails because Audit state is missing.
- **Fingerprint**: e0171775
