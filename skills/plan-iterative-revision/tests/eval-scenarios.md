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

## Scenario 2: Silent stop at the iteration limit goes to the journal

- **Setup:** `interaction=autonomous` run of a plan with a chain journal; the last allowed audit
  still has issues, and `record` returns `stop_reason: limit` with
  `journal_event: {stage: revision, status: stopped, …}`.
- **Trigger:** Subagent receives this `record` result.
- **Expected (PASS):** Passes `journal_event` to `journal-event` and records
  `journal-question <journal> --skill plan-iterative-revision --plan <plan> --stage revision
  --text "…" --option "<resolve by hand and re-run>" --option "<accept the plan as it is>"`
  without `--answer`; the stage ends `stopped` with the question open; runs
  `journal-export-findings` and returns the result JSON naming `Qn`.
- **Red flags (FAIL):** Continues past the limit; raises the limit by itself; marks the stage
  `done`; asks in chat with nobody to answer.

## Scenario 3: A remark about the code becomes a finding, not a plan issue

- **Setup:** While auditing, the subagent sees that `api/client.py:40` swallows a timeout; no plan
  task touches that code and the plan needs no change.
- **Trigger:** Subagent prepares the issues JSON for `record`.
- **Expected (PASS):** Runs `journal-finding <journal> --skill plan-iterative-revision --plan <plan>
  --file api/client.py --line 40 --summary "…" --failure-scenario "…" --backlog-root <repo root>`;
  the issues JSON has no entry for it.
- **Red flags (FAIL):** A plan issue invented to carry a code defect; a task added to the plan for
  unrelated code; the remark only in chat.

## Scenario 4: "Accept the plan as it is" ends the stage without a new audit

- **Setup:** The run of Scenario 2 after the stop. The user answered `Q1` with
  `journal-answer <journal> Q1 --answer "accept the plan as it is"`; `journal-show --plan <plan>`
  reports the `revision` stage `stopped` and `next_action: resume`.
- **Trigger:** `interaction=autonomous` run on the same plan.
- **Expected (PASS):** `journal-answer <journal> Q1 --applied`, then
  `journal-event … --stage revision --status running` and at once
  `journal-event … --stage revision --status done --input <plan> --artifact verdict=accepted`;
  final output `stage-done: revision (accepted, Q1)`. No review file is written and the plan is
  unchanged.
- **Red flags (FAIL):** A new audit (Phase A) or a new review file; any edit of the plan; a new
  journal question about the same limit; the stage left `running` or `stopped`.

## Scenario 5: The second audit reads only its scope

- **Setup:** Audit `k = 2` of a 60-task plan; `digest` returns `task_digest.scope: incremental`,
  `tasks: ["3", "4", "7"]` and `line_ranges` for `header`, `3`, `4`, `7`.
- **Trigger:** Subagent starts Phase A.
- **Expected (PASS):** Reads the header and the three ranges with `Read` offset/limit, cross-checks only
  their claims, and calls `record … --scope incremental --tasks "3,4,7"`.
- **Red flags (FAIL):** A `Read` of the whole plan file; `--scope full`; other ids in `--tasks`;
  cross-checks of claims in unchanged tasks.

## Scenario 6: An unchanged plan skips the audit

- **Setup:** Phase B deferred every issue; `digest` returns `task_digest.scope: none-changed` and two
  `active_contracts`.
- **Trigger:** Subagent reaches Phase A of audit `k = 2`.
- **Expected (PASS):** No Phase A (no plan read, no code cross-check); the issues JSON carries both
  contracts with their own severity; `record --scope incremental --tasks "<task_digest.tasks>"` stops
  with `stagnation` / `unchanged`.
- **Red flags (FAIL):** Phase A runs; a contract missing from the carries; a new issue invented.

## Scenario 7: A clean incremental audit does not end the run

- **Setup:** The incremental audit found nothing; `record` returns `action: full-audit-required`.
- **Trigger:** Subagent receives this result.
- **Expected (PASS):** No Phase B and the same `k`; the next Phase A reads the whole plan and `record`
  gets `--scope full`; only its clean result is reported as `converged`.
- **Red flags (FAIL):** The run reported as `clean` or `converged` after the incremental pass; Phase B
  runs; a second incremental pass.

## Scenario 8: Every active contract is re-checked

- **Setup:** Incremental audit with three active contracts: two applied in changed tasks, one still
  open in a task of `focus`.
- **Trigger:** Subagent prepares the issues JSON.
- **Expected (PASS):** The open contract is carried by its fingerprint (`carry`); the applied ones are
  left out; `record` returns no `contracts-dropped` warning.
- **Red flags (FAIL):** The open contract left out (`record` warns `contracts-dropped`); an applied one
  carried; an open contract re-stated as a new issue with other wording.

## Scenario 9: Evidence quotes are short

- **Setup:** Full audit of a plan whose Task 4 calls `load_config(path)` while the code defines
  `load_config(path, env)`; the step around the call is 60 lines of code.
- **Trigger:** Subagent prepares the issues JSON.
- **Expected (PASS):** `evidence` quotes the one plan line with the call and the one code line with
  the definition (well under 600 characters); `record` returns no `evidence-too-long` warning.
- **Red flags (FAIL):** `evidence` copies the whole step or the whole function; `record` warns
  `evidence-too-long`; the agent cuts the text by hand after the warning instead of quoting less in
  the next audit.

## Scenario 10: Phase B stays within the budget

- **Setup:** A plan of 148 000 bytes; `record` returns `action: implement` with `budget.headroom_bytes` 2 000 and
  `limit: on`; the review has three issues, the third asks for a new 3 000-byte task.
- **Trigger:** Subagent runs Phase B and the rest of the loop pass.
- **Expected (PASS):** The first two issues are applied; the third is applied in fewer words within the headroom or
  deferred with the reason `budget`; the next `record` gets `--deferred "<id>:budget"`; when `guard-check` returns
  `over_budget: true`, one compression in a new guard window touches only the tasks of `changed_tasks`; at the end an
  issue deferred for the budget and still open becomes `journal-finding` `budget: <title>`.
- **Red flags (FAIL):** The plan grows past 150 000 bytes without a compression; the compression edits a task outside
  `changed_tasks` or drops a contract; the deferred id is not passed to `record`; a second compression pass.

## How To Run

For each scenario: dispatch a fresh subagent with the skill loaded, paste
the Setup as the user turn, observe. Record PASS/FAIL. On FAIL, strengthen
the relevant `SKILL.md` / reference wording and re-run.
