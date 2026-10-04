# Stage {{ID}}: {{TITLE}}

> Source: [{{BASE_NAME}}.md](./{{BASE_NAME}}.md)
> Roadmap: [{{BASE_NAME}}-roadmap.md](./{{BASE_NAME}}-roadmap.md)
> Depends on: {{DEPENDS_ON_OR_DASH}}
> Blocks: {{BLOCKS_OR_DASH}}
> Weight: {{WEIGHT}}

## Goal

{{GOAL}}

## Inputs

{{INPUTS}}

Source plan context (header, verbatim):

{{PLAN_HEADER}}

## Tasks

{{TASK_LIST}}

Run them strictly in order. The full text of each task (Files, Preconditions, Postconditions, steps, commands and expected output) follows, verbatim from the source plan.

{{TASK_BODIES}}

## Completion criteria

{{CRITERIA}}

## Outputs (handoff)

{{OUTPUTS}}

## Notes

{{NOTES}}

<!-- item:task -->
{{N}}. Task {{TASK_ID}}: {{TASK_TITLE}}
<!-- /item -->
<!-- item:criterion -->
- [ ] Task {{TASK_ID}}: {{TEXT}}
<!-- /item -->
<!-- item:criterion-empty -->
- [ ] Task {{TASK_ID}} is done: all its steps passed.
<!-- /item -->
<!-- item:criterion-text -->
- [ ] {{TEXT}}
<!-- /item -->
