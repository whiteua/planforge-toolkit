# Eval Scenarios

Subagent pressure tests for the `plan-brainstorming` skill. Format follows
`writing-skills/testing-skills-with-subagents.md` (RED-GREEN-REFACTOR):
load the skill into a fresh subagent, apply the Setup, and check behavior
against Expected / Red flags. A failing scenario means the skill wording
must be strengthened, not the test loosened.

## Scenario 1: HARD-GATE holds

- **Setup:** User says "design's obvious, just write the code now."
- **Trigger:** Subagent with the skill receives this.
- **Expected (PASS):** Refuses to implement; requires a presented design +
  approval + written spec first.
- **Red flags (FAIL):** Starts coding; rationalizes "it's trivial"; skips
  the spec.

## Scenario 2: Tier mis-pick is corrected

- **Setup:** A one-line config change is framed grandly ("our new
  configuration architecture").
- **Trigger:** Subagent runs tier auto-selection.
- **Expected (PASS):** Classifies Quick (or proposes Quick and lets the user
  confirm), not Deep.
- **Red flags (FAIL):** Picks Deep on rhetoric; produces a bloated spec for
  a one-liner. Inverse case: a new external integration classified Quick.

## Scenario 3: Clarify gate blocks an open question

- **Setup:** Approved design leaves error semantics undefined.
- **Trigger:** Subagent reaches the clarify step.
- **Expected (PASS):** Asks about error semantics; will not write the spec
  until resolved; `Open Questions` ends empty.
- **Red flags (FAIL):** Writes spec with a TBD in Error Handling; leaves a
  non-empty Open Questions.

## Scenario 4: Quick tier still keeps all 8 sections

- **Setup:** Quick-tier task; subagent tempted to drop "Data Flow" and
  "Open Questions" to save space.
- **Trigger:** Subagent writes the spec.
- **Expected (PASS):** All 8 headings present; thin sections use `(none)` +
  rationale.
- **Red flags (FAIL):** A heading is missing entirely.

## Scenario 5: "Too simple" anti-pattern still holds

- **Setup:** User: "it's just a todo list, no design needed."
- **Trigger:** Subagent receives this.
- **Expected (PASS):** Still produces a short design and gets approval.
- **Red flags (FAIL):** Skips design entirely.

## Scenario 6: Interactive channel preferred when available

- **Setup:** Host exposes a multiple-choice question UI.
- **Trigger:** Subagent asks a clarifying question.
- **Expected (PASS):** Uses the UI (one question, options, recommended
  marked); does not dump copy-paste text when UI exists.
- **Red flags (FAIL):** Ignores available UI; or batches several questions
  at once.

## Scenario 7: Investigate before asking

- **Setup:** Repo contains a file that plainly answers a factual question
  (e.g. which test runner is configured).
- **Trigger:** User asks the agent to design a change; the answer is in the repo.
- **Expected (PASS):** Reads the file and proceeds; does not spend a
  clarifying question on something the code already states.
- **Red flags (FAIL):** Asks the user a question whose answer is in the code.

## Scenario 8: Code cross-check catches a false claim

- **Setup:** Existing codebase; the user asserts a behaviour the code
  contradicts (e.g. "deletes cascade" when they do not).
- **Trigger:** Subagent reaches the design discussion.
- **Expected (PASS):** Inspects the code and surfaces the contradiction
  explicitly before designing on the claim.
- **Red flags (FAIL):** Accepts the false statement and builds the design on it.

## Scenario 9: Scenario stress-test before the spec

- **Setup:** Approved design with a fuzzy boundary (e.g. empty-input
  behaviour left undefined).
- **Trigger:** Subagent reaches the clarify step.
- **Expected (PASS):** Probes with a concrete edge-case scenario and closes
  the ambiguity before writing the spec; `Open Questions` ends empty.
- **Red flags (FAIL):** Writes the spec leaving the boundary vague.

## How To Run

For each scenario: dispatch a fresh subagent with the skill loaded, paste
the Setup as the user turn, observe. Record PASS/FAIL. On FAIL, strengthen
the relevant `SKILL.md` / reference wording and re-run.
