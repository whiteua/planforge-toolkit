# Eval Scenarios

Subagent pressure tests for the `plan-iterative-revision` skill. Format follows
`writing-skills/testing-skills-with-subagents.md` (RED-GREEN-REFACTOR):
load the skill into a fresh subagent, apply the Setup, and check behavior
against Expected / Red flags. A failing scenario means the skill wording
must be strengthened, not the test loosened.

## Scenario 1: Questions and summary in the plan's language

- **Setup:** Russian plan (`bootstrap` reports `lang: ru`), interactive run, no `Chain` in the
  settings, the user gave neither preset nor stop_policy.
- **Trigger:** Subagent starts the run, later the loop ends.
- **Expected (PASS):** The preset/stop_policy confirmation, its option labels and descriptions,
  the limit question and the final summary are in Russian.
- **Red flags (FAIL):** "MAX review passes done …" or other template phrases said in English;
  Russian question with English options; English final summary for a Russian plan.

## How To Run

For each scenario: dispatch a fresh subagent with the skill loaded, paste
the Setup as the user turn, observe. Record PASS/FAIL. On FAIL, strengthen
the relevant `SKILL.md` / reference wording and re-run.
