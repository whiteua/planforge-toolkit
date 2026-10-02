# Part File Format

## 1. File name

`<BASE>-<id>.md`, where `<id>` is the part letter: `a`, `b`, … `z`, `aa`, `ab`, … Get it from
`TOOL stage-name <BASE> <N>` (ordinal) or `TOOL part-id <N>`.

## 2. Required sections, in order

1. `# Stage <id>: <Title>` (`# Стадия <id>: …` in Russian)
2. A blockquote header: `Source`, `Roadmap`, `Depends on`, `Blocks`, `Weight`.
3. `## Goal` (`## Цель`)
4. `## Inputs` (`## Входные данные`)
5. `## Tasks` (`## Задачи`)
6. `## Completion criteria` (`## Критерии завершения`)
7. `## Outputs (handoff)` (`## Выходные данные (handoff)`)
8. `## Notes` (`## Примечания`)

A missing section makes `validate-stage` return `valid: false`.

## 3. Content rules

- **Goal**: one or two sentences describing the result, checkable by eye. Not a task list.
- **Inputs**: with no dependencies, "Original plan: [link]. No specific inputs." Otherwise the
  concrete artifacts, state and decisions handed over by each dependency; they must match that
  part's **Outputs** section word for word where possible.
- **Tasks**: a numbered list (`1.`, `2.`, …) of self-contained instructions. No back-references
  ("see above", "as in the original"). Enough context to act with only this file and the roadmap.
  8–15 tasks is the typical size; `validate-stage` warns above 15 (soft, does not fail).
  Numbered items inside code fences are not tasks; `validate-all` counts only top-level items.
- **Completion criteria**: a checkbox list of verifiable facts (a call succeeds, a file exists,
  a test passes). Not goals.
- **Outputs (handoff)**: what downstream parts receive: files, state, decisions, configs, phrased so
  the text can be reused as their **Inputs**.
- **Notes**: risks, open points, recommendations. May be empty, but the heading must exist.

## 4. Boundary heuristics

A part is a group of tasks that:

1. belongs to one module or layer (a module change is a candidate boundary);
2. shares one mental context;
3. ends in a checkable deliverable;
4. fits one agent pass (up to 15 tasks; smaller parts are fine when module boundaries give them).

## 5. Grouping rules

- Explicit phases or sections of the original are the starting point.
- A task that straddles two parts goes to the one whose result it depends on more.
- Shared or infrastructure tasks (setup, configs) go to the first part.
- A task whose artifact several parts need goes to a blocking part.

## 6. Content transformation (not a verbatim copy)

1. Rephrase tasks as self-contained instructions for an agent.
2. Add the context each part needs to be understood without the original.
3. Make abstract tasks concrete, checkable action items.
4. Preserve intent: nothing from the original is lost or distorted.

A plan from `plan-writing` (`### Task N:` headings with `**Files:**`, steps and done-states)
keeps that structure inside `## Tasks`: one numbered item per task, with its files, steps and
done-state as nested content. `plan-executor` runs a part as one unit, so the part text must be
executable as a whole.

`**External:**` and `**Size:**` lines are copied verbatim, character for character, into the part
task that holds the source task: `**External:**` carries the environment and the access kind the
executor's consent gate reads, `**Size:**` carries the justification of an oversized task, so
rephrasing (item 1) never applies to them. `validate-all` fails when one is missing. The part
header does not change.

## 7. Oversized part

If a part still holds more than 15 tasks after analysis (the `validate-stage` warning), add to its file:

```markdown
> ⚠️ This part may be too large for a single pass.
> Recommended: `plan-splitter <BASE>-<id>.md`
```

This is manual recursion under the user's control; the skill never splits recursively.
