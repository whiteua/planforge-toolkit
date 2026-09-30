# Stop Report

## Completed

{{completed_units}}

## Stopped at

Unit: `{{unit_id}}`
Reason: `{{stop_reason}}`
Restore to: `{{restore_to}}`

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

## How to resume

Run:

```bash
{{resume_command}}
```
