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

## How To Run

For each scenario: dispatch a fresh subagent with the skill loaded, paste
the Setup as the user turn, observe. Record PASS/FAIL. On FAIL, strengthen
the relevant `SKILL.md` wording and re-run.
