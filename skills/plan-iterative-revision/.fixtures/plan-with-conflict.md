# Dogfooding Plan With Edit Conflict

## Goal

Exercise Phase B conflict handling when two issues target the same paragraph and the second edit must re-read the master plan before applying.

## Shared Paragraph

The skill writes review files and edits the master plan in the same phase, and it may batch several unrelated issue fixes in one edit transaction for speed.

## Expected Dogfooding Findings

1. Phase separation issue: review-file creation belongs to Phase A, while master-plan edits belong to Phase B.
2. Transaction issue: one issue must equal one edit transaction; unrelated fixes must not be batched.

## Expected Implementation Behavior

- First fix rewrites the shared paragraph to separate Phase A and Phase B.
- Second fix must re-read the paragraph before applying the transaction rule.
- If the second edit cannot be applied after 2 retries, mark it as `deferred-conflict`.
