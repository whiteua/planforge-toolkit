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

## Scenario 2: The `split` stage in the journal

- **Setup:** Plan with a chain journal. Run A: `split=auto` and the gate decides not to split.
  Run B: `split=always`, three parts, `verify=all`.
- **Trigger:** Subagent finishes each run.
- **Expected (PASS):** Run A: `journal-event … --stage split --status skipped` with the reason in
  `--data`, no files written. Run B: `split` is `running` at the start and ends `done` with
  `--input <plan> --artifact roadmap=<base>-roadmap.md --artifact parts[]=<base>-a.md
  --artifact parts[]=<base>-b.md --artifact parts[]=<base>-c.md`; the batch verification of the
  parts stays inside the `split` stage.
- **Red flags (FAIL):** The batch verification marks the plan's `revision` stage; `split done`
  without the parts; `split` left `running`; the source plan edited.

## How To Run

For each scenario: dispatch a fresh subagent with the skill loaded, paste
the Setup as the user turn, observe. Record PASS/FAIL. On FAIL, strengthen
the relevant `SKILL.md` / reference wording and re-run.
