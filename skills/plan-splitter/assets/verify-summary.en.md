## Deep verification summary

| Stage | Result | Iterations | Remaining | Verified |
|-------|--------|------------|-----------|----------|
{{VERIFY_TABLE}}

{{#IF_ALL_CLEAN}}
All selected stages passed verification with no remaining issues.
{{/IF_ALL_CLEAN}}

{{#IF_HAS_WARNINGS}}
⚠️ Stages with remaining issues or machine verdict `satisfied_with_warning`/`missing`/`inconsistent`: {{WARNING_STAGES}}.
Recommendation: run plan-iterative-revision manually on the flagged stages.
{{/IF_HAS_WARNINGS}}