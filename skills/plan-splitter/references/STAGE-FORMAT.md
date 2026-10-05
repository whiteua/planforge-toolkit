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
- **Tasks**: written by `split-write` (§6): a numbered list `Task N: <title>`, then the full task
  texts verbatim. 8–15 tasks is the typical size; `validate-stage` warns above 15 (soft, does not
  fail). Tasks are counted by their `### Task N:` bodies; a hand-written part without them by its
  top-level numbered items outside code fences.
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

## 6. Who writes what

`TOOL split-write PLAN --parts parts.json [--lang ru|en] [--force]` writes the roadmap and every
part from `assets/roadmap-template.<LANG>.md` and `assets/stage-template.<LANG>.md` (`--lang`
defaults to `TOOL detect-lang PLAN`). The model writes only `parts.json`:

```json
{"title": "optional roadmap title (default: the plan's H1)",
 "overview": "optional 2-3 sentences (default: the plan's **Goal:**)",
 "parts": [{"id": "a", "title": "…", "depends": [], "group": "A", "weight": "🟡 medium",
            "goal": "…", "inputs": "…", "outputs": "…", "notes": "",
            "criteria": ["optional; default: one line per task from its Postconditions / Done when"],
            "tasks": ["1", "2", "2.1"]}]}
```

The script copies, never the model:

1. the plan header (the lines before the first task, without the H1 and a closing `---`) into
   `## Inputs`, after the model's `inputs`;
2. into `## Tasks`, in plan order: a numbered list `Task N: <title>`, then each task's text from its
   heading to the line before the next task, byte for byte;
3. completion criteria from `criteria`, else from each task's done-state.

So `**External:**`, `**Size:**` and `**Structural event:**` lines stay in their tasks as they are. `validate-all` checks the
task bodies (`task_bodies`, by the shared parser's `sha1`) and these lines. `split-write` checks the
whole `parts.json` before writing anything: each plan task in exactly one part, ids `a, b, …` in
order, known and acyclic dependencies, no part in the parallel group of its dependency, no
Preconditions reference into a later part or into a part the referring one does not depend on
(directly or through other parts). `plan-executor` runs each task of a part as its own unit and
closes the part with a checkpoint over `## Completion criteria` and `## Outputs (handoff)`.

## 7. Oversized part

If a part still holds more than 15 tasks after analysis (the `validate-stage` warning), add to its file:

```markdown
> ⚠️ This part may be too large for a single pass.
> Recommended: `plan-splitter <BASE>-<id>.md`
```

This is manual recursion under the user's control; the skill never splits recursively.
