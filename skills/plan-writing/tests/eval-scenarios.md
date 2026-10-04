# Eval Scenarios

Subagent pressure tests for the `plan-writing` skill. Format follows
`writing-skills/testing-skills-with-subagents.md` (RED-GREEN-REFACTOR):
load the skill into a fresh subagent, apply the Setup, and check behavior
against Expected / Red flags. A failing scenario means the skill wording
must be strengthened, not the test loosened.

## Scenario 1: Hand-off in the plan's language

- **Setup:** Russian spec (`spec-check` reports `"lang": "ru"`); the host has a multiple-choice
  question UI.
- **Trigger:** Subagent has written the plan and reaches 7. Execution Handoff.
- **Expected (PASS):** The "Plan complete and saved to …" message, the question and every option
  label and description are in Russian; only command names and file paths stay as they are.
- **Red flags (FAIL):** The template phrase copied in English; Russian question with English
  options; English status lines while the plan body is Russian.

## Scenario 2: Silent run records the question and stops

- **Setup:** Subagent run without a question tool. The spec passes `spec-check` but has no
  `> Chain:` line (written before chain settings), and the caller gave no settings.
- **Trigger:** Subagent reaches the point where an old spec's settings must be asked.
- **Expected (PASS):** As soon as `spec-check` exits `0`, before the settings question, has run
  `journal-path <spec> --create` and `journal-event … --stage writing --status running`; records `journal-question <journal> --skill plan-writing --plan <plan path>
  --stage writing --text "…"` with options and without `--answer`, runs `journal-export-findings`
  and stops with a report in the spec's language that names `Qn`. No plan header with guessed
  settings.
- **Red flags (FAIL):** Writes default settings into the plan header; marks `writing` `done`;
  asks in chat and continues; records the question with `--answer`.

## Scenario 3: No split advice by task count

- **Setup:** A spec with `> Chain: split=auto; …`; the written plan has 16 tasks and 60 KB;
  `plan-check` returns `size_class: medium` and no `plan-oversized`.
- **Trigger:** Subagent reaches 7. Execution Handoff.
- **Expected (PASS):** The message names 16 tasks, the bytes and `medium`; Audit is the first
  step; the Split option says the splitter's gate decides.
- **Red flags (FAIL):** "split with `plan-splitter` before execution" put first because of more
  than 15 tasks; no size class in the message.

## Scenario 4: Oversized plan in a silent run

- **Setup:** Subagent run without a question tool; `spec-check` gives `volume.estimate_tasks: 52`;
  the written plan has 45 tasks and `plan-check` warns `plan-oversized: 45 tasks, 170000 bytes
  (budget 40 tasks / 150000 bytes)`.
- **Trigger:** Subagent passes 3. File Structure and later reaches the End event.
- **Expected (PASS):** No `journal-question` about the size and no stop; the plan is written;
  the End event is `journal-event … --status done … --data '{"warnings": ["plan-oversized: 45
  tasks, 170000 bytes (budget 40 tasks / 150000 bytes)"]}'`; the report advises splitting the
  goal in `plan-brainstorming` and says every later stage costs in proportion to the size.
- **Red flags (FAIL):** Stops on a size question; marks `writing` `failed`; drops the warning
  from the event; splits tasks or deletes tasks to get under the budget.

## How To Run

For each scenario: dispatch a fresh subagent with the skill loaded, paste
the Setup as the user turn, observe. Record PASS/FAIL. On FAIL, strengthen
the relevant `SKILL.md` wording and re-run.
