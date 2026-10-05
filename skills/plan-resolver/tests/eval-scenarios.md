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

## Scenario 3: The incremental pass reads its scope only

- **Setup:** English plan of 40 tasks; report 1 is open with one `⭕️ not-fixed` issue linked to
  task 7 and has an evidence fingerprint; the fix changed `src/a.py`, the anchor file of tasks 7 and
  12.1. `/plan-resolver <plan> fix`.
- **Trigger:** Subagent runs the audit after the fix.
- **Expected (PASS):** `rescan-scope` → `incremental` with `reaudit` 7, 12, 12.1; `carry-forward`
  writes report 2; the agent reads tasks 7, 12 and 12.1 by their `line_ranges` (Read with offset
  and limit) and the code of `src/a.py`, replaces the three stubs and re-verifies issue 1;
  `evidence-fingerprint`, `task-census` and `validate-report --root --plan` pass.
- **Red flags (FAIL):** Reads the whole plan or calls `PT skeleton`; edits or retypes carried
  lines; writes report 2 by hand instead of `carry-forward`; leaves a `<!-- reaudit -->` marker.

## Scenario 4: No `-final` after an incremental pass

- **Setup:** As in scenario 3, but the re-audit closes every task and issue 1.
- **Trigger:** Subagent names and writes the report.
- **Expected (PASS):** Report 2 keeps the open name, `audit_scope: incremental` and
  `consecutive_open_invocations: 0`; `cycle-check` → `full-audit-required`; the gate of `fix`
  names `/plan-resolver <plan> full` as the next step.
- **Red flags (FAIL):** Writes `<base>-report-2-final.md`; switches `audit_scope` to `full` without
  a full pass; reports the plan as closed.

## Scenario 5: The closing full pass runs in a fresh subagent

- **Setup:** `auto` with the default limit; cycle 1 ended with `full-audit-required`; the host has
  subagents.
- **Trigger:** Subagent continues the loop.
- **Expected (PASS):** A fresh subagent runs `/plan-resolver <plan> <reports…> full`: `bootstrap …
  --full` (`pass_type: subsequent-full`), the whole plan through `PT skeleton`, `-final` allowed; `cycle-check` after it
  gives `complete`, `continue` or `stop-limit`.
- **Red flags (FAIL):** Runs the closing full pass inline although subagents are available; runs
  another incremental pass; stops with `stop-stalled` after the full pass.

## Scenario 6: `full` as the last argument

- **Setup:** Plan with an open report 2 that has an evidence fingerprint; nothing changed since.
  `/plan-resolver <plan> <report-1> <report-2> full`.
- **Trigger:** Subagent starts the audit.
- **Expected (PASS):** `bootstrap … --full` and `pass_type: subsequent-full`; neither `rescan-scope`
  nor `carry-forward`; a full pass by AUDIT.md with `audit_scope: full`.
- **Red flags (FAIL):** Passes `full` to `bootstrap` as a report (`bootstrap-bad-report-name`);
  runs `rescan-scope` and audits incrementally.

## Scenario 7: The first pass reads the skeleton

- **Setup:** English plan of 30 tasks, more than half of its bytes in code blocks; `plan-writing`
  is installed next to `plan-resolver`; no earlier report. `/plan-resolver <plan>`.
- **Trigger:** Subagent runs the first audit pass.
- **Expected (PASS):** `PT skeleton <plan>` instead of a Read of the whole plan, its stdout sent to
  a file in the OS temp dir and that file read in chunks to its end (the skeleton is longer than a
  shell tool shows); the code is read in the repository; `PT task <plan> <id>` only for tasks whose
  verdict is `partial`, `ambiguous` or `deviates` or that have no `Files`; every closed task is one line
  `- ✅ <id> <title> evidence_anchor: path#Lx-Ly` (a second anchor only on the task's test file);
  `validate-report` gives no `verbose-closed-task` or `too-many-anchors` warning.
- **Red flags (FAIL):** Reads the whole plan; calls `PT task` for every task; writes detail lines
  under `✅` tasks; treats code quoted in the plan as evidence instead of the repository; judges
  tasks from a skeleton cut by the shell output limit (no file, no chunked Read to the end).

## Scenario 8: The closing full pass reads the skeleton, the incremental one does not

- **Setup:** As in scenario 4, then `/plan-resolver <plan> <report-1> <report-2> full`.
- **Trigger:** Subagent runs the incremental pass of scenario 4, then the closing full pass.
- **Expected (PASS):** The incremental pass reads its tasks by `line_ranges` and never calls
  `PT skeleton`; the closing full pass (`bootstrap … --full`) calls `PT skeleton <plan>` and opens
  single tasks with `PT task` only for disputed verdicts.
- **Red flags (FAIL):** The incremental pass calls `PT skeleton`; the full pass reads the whole plan
  while `plan-writing` is installed.

## Scenario 9: Without `plan-writing` alongside

- **Setup:** Only `plan-brainstorming` and `plan-resolver` are installed; `/plan-resolver <plan>`.
- **Trigger:** Subagent starts the first audit pass.
- **Expected (PASS):** `PT` is missing (or exits `2`); the subagent reads the plan in full and the
  human gate says so in one line; the report is written as usual.
- **Red flags (FAIL):** Stops the audit; writes its own skeleton by hand; hides that the plan was
  read in full.

## How To Run

For each scenario: dispatch a fresh subagent with the skill loaded, paste
the Setup as the user turn, observe. Record PASS/FAIL. On FAIL, strengthen
the relevant `SKILL.md` / reference wording and re-run.
