# Revision Cycle Completion Report

**Plan**: {{basename}}.md
**Iterations completed**: {{iterations}}
**Revisions created**: {{revisions_created}}
**Final Plan SHA-256**: {{final_plan_sha256}}
**Finished at**: {{finished_at_utc}}

## Verdict

{{verdict}}
<!--
Possible verdicts:
- "Plan is clean — no issues found on the first audit. No review file was created."
- "Cycle converged in {{iterations}} iterations. All review contracts have been applied to the plan."
- "Audit-only mode completed. Review file created and validated: {{final_review}}. Phase B was not run."
- "Iteration limit exhausted, user stopped the process. Final review: {{final_review}}."
- "Stagnation: the issue set did not change between iterations {{i-1}} and {{i}}. Cycle aborted."
-->

## Created revision files

{{list_of_review_files}}

## Unapplied contracts (deferred / final)

{{deferred_or_final_issues_or_none}}

## Recommendations

- Read the master plan end-to-end and confirm the final state matches expectations.
- Manually review the database changes and API contracts sections.
- Re-run the skill after manual edits if needed.

<!-- Only when result ∈ {escalated, stagnation}; not for result ∈ {clean, converged, limit} -->
## Escalation summary

- Stop reason: {{stop_reason}}
- Stuck contracts (fingerprint): {{escalated_fingerprints}}
- For regression — iteration where the issue was previously resolved: {{regression_origin}}
- Recommendation: manual decision on the listed contracts before re-running.
