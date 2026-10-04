# Roadmap: {{PLAN_TITLE}}

> Source: [{{BASE_NAME}}.md](./{{BASE_NAME}}.md)
> Generated: {{ISO8601_UTC}}
> Parts: {{N}}

## Overview

{{OVERVIEW}}

## Dependency graph

| Stage | Title | Depends on | Parallel group | Weight |
|-------|-------|------------|----------------|--------|
{{TABLE_ROWS}}

### Parallel groups

{{GROUP_LINES}}

### Visualization (Mermaid)

```mermaid
graph LR
{{MERMAID_EDGES}}
```

## Stages

{{STAGE_SECTIONS}}

<!-- item:row -->
| {{ID}} | {{TITLE}} | {{DEPENDS}} | {{GROUP}} | {{WEIGHT}} |
<!-- /item -->
<!-- item:group -->
- **Group {{GROUP}}**: {{MEMBERS}}
<!-- /item -->
<!-- item:stage -->
### {{ID}}: {{TITLE}}
- **File**: [{{BASE_NAME}}-{{ID}}.md](./{{BASE_NAME}}-{{ID}}.md)
- **Depends on**: {{DEPENDS}}
- **Blocks**: {{BLOCKS}}
- **Weight**: {{WEIGHT}}
- **Summary**: {{SUMMARY}}
<!-- /item -->
