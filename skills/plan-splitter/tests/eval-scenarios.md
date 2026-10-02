# Eval Scenarios

Subagent pressure tests for the `plan-splitter` skill. Format follows
`writing-skills/testing-skills-with-subagents.md` (RED-GREEN-REFACTOR):
load the skill into a fresh subagent, apply the Setup, and check behavior
against Expected / Red flags. A failing scenario means the skill wording
must be strengthened, not the test loosened.

## Scenario 1: Gate and split table in the plan's language

- **Setup:** Russian plan of 30 tasks (`detect-lang` gives `ru`), interactive run, no `split` in
  the settings.
- **Trigger:** Subagent reaches the gate decision and then the split-table confirmation.
- **Expected (PASS):** The verdict with its factors, the confirmation question, its option labels
  and descriptions and the final report are in Russian; file names and commands stay as they are.
- **Red flags (FAIL):** English verdict or options for a Russian plan; a mix of languages in one
  question.

## How To Run

For each scenario: dispatch a fresh subagent with the skill loaded, paste
the Setup as the user turn, observe. Record PASS/FAIL. On FAIL, strengthen
the relevant `SKILL.md` / reference wording and re-run.
