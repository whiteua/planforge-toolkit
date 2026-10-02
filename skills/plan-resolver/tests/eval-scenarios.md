# Eval Scenarios

Subagent pressure tests for the `plan-resolver` skill. Format follows
`writing-skills/testing-skills-with-subagents.md` (RED-GREEN-REFACTOR):
load the skill into a fresh subagent, apply the Setup, and check behavior
against Expected / Red flags. A failing scenario means the skill wording
must be strengthened, not the test loosened.

## Scenario 1: Fix question and summary in the plan's language

- **Setup:** Russian plan (`bootstrap.language` is `ru`); the audit writes an open report with
  two issues; the host has a question UI.
- **Trigger:** Subagent finishes the audit pass and offers the next action.
- **Expected (PASS):** The human gate, the question about `fix` / `next`, its option labels and
  descriptions and the final summary are in Russian; status markers and file names stay as they
  are.
- **Red flags (FAIL):** English question or options for a Russian plan; an English summary after
  a Russian report.

## How To Run

For each scenario: dispatch a fresh subagent with the skill loaded, paste
the Setup as the user turn, observe. Record PASS/FAIL. On FAIL, strengthen
the relevant `SKILL.md` / reference wording and re-run.
