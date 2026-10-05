# Chain run: {{goal}}

Result: {{result}}
Journal: `{{journal_path}}`
Goal roadmap: {{goal_roadmap_path}}
Profile: {{profile}}; time: {{duration}}
Volume: {{cost_line}}

## Plans

<!-- One block per plan, in the run's order. A missing artifact: "—". -->

### {{plan_index}}. {{plan_id}} — {{plan_state}}

- Spec: `{{spec_path}}`
- Plan: `{{plan_path}}`
- Revision: {{review_path}} ({{revision_verdict}})
- Roadmap: {{roadmap_path}}
- Ledger: {{ledger_path}}
- Audit report: {{report_path}} ({{audit_status}})
- Diff report: {{diffs_path}}
- Commits: {{commits}}

## Follow-ups

- Defects outside the plans: `{{followups_path}}`
- BACKLOG.md, section `{{backlog_section}}`: {{backlog_lines}}
- Checklist after the run: {{checklist_lines}}

## Open questions

{{open_questions}}

## Next

{{next_step}}
