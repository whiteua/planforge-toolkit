## Deep verification summary

| Part | Result | Iterations | Remaining | Verdict | Stop reason |
|------|--------|------------|-----------|---------|-------------|
{{VERIFY_TABLE}}

{{#IF_ALL_CLEAN}}
All selected parts passed verification with no remaining issues.
{{/IF_ALL_CLEAN}}

{{#IF_HAS_WARNINGS}}
⚠️ Parts with remaining issues or verdict `satisfied_with_warning`: {{WARNING_PARTS}}.
Recommendation: run `/plan-iterative-revision {{BASE_NAME}}-<id>.md` on them by hand.
{{/IF_HAS_WARNINGS}}
