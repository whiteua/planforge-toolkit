---
master_plan_path: {{master_plan_path}}
master_plan_sha256: {{master_plan_sha256}}
master_plan_size: {{master_plan_size}}
audited_at: {{audited_at}}
audit_iteration: {{audit_iteration}}
consecutive_open_invocations: {{consecutive_open_invocations}}
previous_report_path: {{previous_report_path}}
previous_report_sha256: {{previous_report_sha256}}
language: en
audit_scope: {{audit_scope}}
audit_tasks: {{audit_tasks}}
---
# Plan Implementation Report {{audit_iteration}}

## Plan Stages

<!-- A closed task is one line with one anchor (a second only on the task's test file): - ✅ 1. Title evidence_anchor: path#Lx-Ly; detail lines only under ⚠️, ⭕️, ‼️ -->
{{plan_stages}}

## Issues

{{issues}}

## Additional Context

{{additional_context}}

## Task

{{task}}

## Evidence fingerprint

{{evidence_fingerprint}}
