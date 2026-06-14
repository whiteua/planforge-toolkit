# Stop Report

## Completed

{{completed_units}}

## Stopped at

Unit: `{{unit_id}}`
Checkpoint: `{{checkpoint_id}}`

## Last error

{{last_error}}

## Last diff

```diff
{{last_diff}}
```

## How to roll back

Use checkpoint `{{checkpoint_id}}` if git rollback is available, or perform manual rollback in step mode.

## How to resume

Run:

```bash
{{resume_command}}
```
