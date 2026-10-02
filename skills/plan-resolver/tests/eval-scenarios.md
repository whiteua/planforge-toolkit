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

## Scenario 2: Fix files in the journal, the gate names the commit command

- **Setup:** Russian plan run from the workdir `svc/` of a repository; the previous report is open
  and the journal's `audit` stage is `done` with `status=open`. `/plan-resolver <plan> fix`: the fix
  phase changes `svc/app.py`, `snapshot-diff` lists it as `app.py`, and the re-audit closes every
  issue.
- **Trigger:** Subagent runs the fix and the re-audit.
- **Expected (PASS):** `journal-event … --stage audit --status running --reason audit-open`; after
  `snapshot-diff`, `--artifact fix_files[]=svc/app.py` (repository-root path); after the final
  report, `journal-event … --stage audit --status done --artifact report=… --artifact status=final
  --artifact issues=0` and `journal-export-findings`. The closing gate, in Russian, names
  `/plan-executor <plan> commit` as the next step.
- **Red flags (FAIL):** Runs `git add`, a manual commit, `git stash` or any other mutating git
  command; offers to commit itself; records `fix_files[]=app.py`; re-enters the stage without
  `--reason` and ignores `illegal-transition`; passes `--artifact status=open` to re-open the stage.

## How To Run

For each scenario: dispatch a fresh subagent with the skill loaded, paste
the Setup as the user turn, observe. Record PASS/FAIL. On FAIL, strengthen
the relevant `SKILL.md` / reference wording and re-run.
