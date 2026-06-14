# Contributing to PlanForge Toolkit

Thank you for your interest in contributing!

## Ways to Contribute

- **Bug reports** — open an [issue](https://github.com/whiteua/planforge-toolkit/issues) describing the unexpected behavior, the skill involved, and steps to reproduce.
- **Improvements to existing skills** — corrections to instructions, better examples, closed loopholes.
- **New skills** — use the `writing-skills` skill to develop and test them before submitting.

## Pull Request Process

1. Fork the repository and create a feature branch:
   ```bash
   git checkout -b feature/my-improvement
   ```

2. Make your changes. Keep each PR focused on a single skill or concern.

3. For **skill changes**: run the skill's test scenarios (if any) against a subagent to verify compliance before and after your change.

4. Update `USAGE.md` if you add or change any invocation arguments.

5. Open a pull request with a clear description of what changed and why.

## Skill Structure

Each skill lives in its own top-level directory:

```
my-skill/
  SKILL.md        ← required: YAML frontmatter + instructions
  USAGE.md        ← recommended: quick reference
  references/     ← supporting documents loaded by the skill
  scripts/        ← helper scripts (Python ≥ 3.8, no extra deps)
  tests/          ← test scenarios / pytest files
  assets/         ← templates, schemas, examples
```

The `SKILL.md` frontmatter must include `name` and `description`:

```yaml
---
name: my-skill
description: "Single sentence describing when to invoke this skill."
---
```

## Code Style

- Markdown: ATX headings (`#`), fenced code blocks with language tags.
- Python scripts: stdlib only, Python ≥ 3.8, no external dependencies.
- File names: kebab-case.

## License

By contributing you agree that your contributions will be licensed under the [MIT License](LICENSE).
