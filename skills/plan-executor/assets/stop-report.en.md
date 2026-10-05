# Stop Report

## Completed

{{completed_units}}

## Stopped at

Unit: `{{unit_id}}`
Reason: `{{stop_reason}}`
Restore to: `{{restore_to}}`
Delegated: {{delegated}}

## Last error

{{last_error}}

## Last diff

```text
{{diff_stat}}
```

```diff
{{diff_excerpt}}
```

## How to roll back

After confirmation: `executor_tool.py checkpoint-restore <repo> {{restore_to}}`. Without git, roll back manually.

## Chain journal

Open question `{{question_id}}` in `{{journal_path}}`: {{question_text}}

Answer it with `brainstorm_tool.py journal-answer {{journal_path}} {{question_id}} --answer "<answer>"`, then resume. Defects outside the plan: `{{followups_path}}`.

## How to resume

Run:

```bash
{{resume_command}}
```
