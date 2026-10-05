---
master_plan_path: {{master_plan_path}}
master_plan_sha256: {{master_plan_sha256}}
master_plan_size: {{master_plan_size}}
audited_at: {{audited_at}}
audit_iteration: {{audit_iteration}}
consecutive_open_invocations: {{consecutive_open_invocations}}
previous_report_path: {{previous_report_path}}
previous_report_sha256: {{previous_report_sha256}}
language: ru
audit_scope: {{audit_scope}}
audit_tasks: {{audit_tasks}}
---
# Отчет о выполнении плана {{audit_iteration}}

## Основные стадии плана

<!-- Закрытая задача — одна строка с одним якорем (второй — только на файл теста задачи): - ✅ 1. Название evidence_anchor: path#Lx-Ly; строки деталей — только у ⚠️, ⭕️, ‼️ -->
{{plan_stages}}

## Список ошибок

{{issues}}

## Дополнительный контекст

{{additional_context}}

## Задача

{{task}}

## Отпечаток улик

{{evidence_fingerprint}}
