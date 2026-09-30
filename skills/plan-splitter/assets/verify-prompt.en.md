Run a deep verification of the parts via plan-iterative-revision?

- Scope: `all` — every part · `a,c` — selected parts · `none` — skip.
- Depth: `quick` · `standard` · `deep`.
- Mode: `full-cycle` (may edit the parts, default) · `audit-only` (reviews only).

One plan-iterative-revision run verifies the selected parts one after another, each with its own
review trail (`{{BASE_NAME}}-<id>-review-N.md`). It runs silently; a summary follows.
