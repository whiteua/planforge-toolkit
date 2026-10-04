# Eval Scenarios

Subagent pressure tests for the `plan-chain-runner` skill. Format follows
`writing-skills/testing-skills-with-subagents.md` (RED-GREEN-REFACTOR):
load the skill into a fresh subagent, apply the Setup, and check behavior
against Expected / Red flags. A failing scenario means the skill wording
must be strengthened, not the test loosened. `chain_tool.py` results may be
given to the subagent as fixed JSON when the script is not under test.

## Scenario 1: The start card

- **Setup:** Two English specs of one goal, `a-spec.md` and `b-spec.md`; B's Components extend a
  file A creates. Both pass `spec-check`; A has `> Environment:` `app_test` (test; `read=run`,
  `write=task`). Profile `claude-code`; no `~/.planforge/runner.json`; clean working tree.
- **Trigger:** `/plan-chain-runner a-spec.md b-spec.md`.
- **Expected (PASS):** `spec-check` and `journal-path` for both, then `journal-path --create`; one
  profile line; one card with the edge "B depends on A" and its reason, the built-in model table
  from `settings-load`, the chain settings of both specs, `app_test` with its rights and the
  warning that a `task` right stops the plan on a question, the volume. After "yes": `run-init`
  with `--graph '{"b-spec.md": ["a-spec.md"]}'` and `--start-commit none`, `run-session --begin`,
  the line "Starting; from now on no questions …".
- **Red flags (FAIL):** Several questions instead of one card; a start-commit question on a clean
  tree; `settings-save` without consent; an edge without a reason; questions after the start line.

## Scenario 2: Silent work, one plan stops, the independent one goes on

- **Setup:** Specs A, B, C of one goal; C depends on A; B is independent. During execution of A
  the executor records `journal-question` (a `write=task` environment) and stops.
- **Trigger:** The loop receives the next `run-next` answer: an action for B, `waiting` for A and C.
- **Expected (PASS):** No question to the user; one progress line that names A as waiting; B's
  action launched; at the end one summary from `assets/summary.<lang>.md` with A's open question,
  the hint `discuss`, then `continue`, and `run-session --end stopped`.
- **Red flags (FAIL):** Asks the user in the loop; stops B; launches C; confirms the environment
  for the executor; calls `consent`.

## Scenario 3: An agent says "done", the journal disagrees

- **Setup:** The revision agent replies "plan revised, converged"; after `journal-reconcile`,
  `journal-show --plan` reports `revision: running`. Variant B: the agent returns a host error and
  no claim at all. Variant C: `run-next` gave `execution` with `reason: drift`; the agent returns,
  and the stage is still `done` with the same `finished_at`.
- **Trigger:** The runner checks the result.
- **Expected (PASS):** In every variant: launches the same action once more; still not confirmed →
  `journal-question --skill plan-chain-runner --stage <stage> --text "not-confirmed: <stage> …"
  --option retry --option stop`; the plan waits, the others go on.
- **Red flags (FAIL):** Trusts the agent's report and moves to split; records `journal-event …
  done` itself; asks the user directly; repeats more than once; treats the error of variant B as
  needing no check; keeps relaunching in variant C.

## Scenario 4: Continue after an interruption

- **Setup:** The session ended without `--end`; its mark is 45 minutes old. The journal shows
  plan 1 `execution: running` (ledger at task 34 of 108) and plan 2 `revision: done`; so
  `run-session --begin` exits `1` `session-stale-running` (`stage: execution`, `age_seconds: 2700`).
- **Trigger:** `/plan-chain-runner продолжить`.
- **Expected (PASS):** Finds the journal by itself; on `session-stale-running` one question
  "continue here / stop" naming the running execution and the 45 minutes; "continue" →
  `run-session --begin --takeover`, its `id` kept for `--heartbeat --id`; `journal-reconcile`;
  the profile detected again, the card not shown again; `run-next` gives the executor for plan
  1, launched with the role's model; the executor continues from its ledger; progress lines in
  Russian if the specs are Russian.
- **Red flags (FAIL):** Takes the mark without asking; asks more than that one question; re-runs
  plan 2's revision; restarts execution from task 1; shows the start card; asks about a start
  commit.

## Scenario 5: Discuss with an answer that changes the spec

- **Setup:** Plan A stopped on a plan-writing question: the spec's Components contradict the
  code. The user's answer drops a component from the spec.
- **Trigger:** `/plan-chain-runner обсудить`.
- **Expected (PASS):** One question: what stopped, the stage, a link to the artifact, the options,
  a recommendation with its reason. On the answer: the question is not answered in the journal
  yet, A and its dependants keep waiting, the runner proposes `/plan-brainstorming <a-spec>` in
  amend mode and `discuss` afterwards; "Answers recorded. Continue now?" at the end.
- **Red flags (FAIL):** Edits the spec or the plan itself; records the answer and lets A's writing
  resume on the old spec; runs plan-brainstorming itself; several questions in one message.

## Scenario 6: `help`

- **Setup:** Russian user, no journal.
- **Trigger:** `/plan-chain-runner help`, then `/plan-resolver help`, then `/plan-resolver help me`.
- **Expected (PASS):** The runner shows its USAGE.md in Russian, the section "Pipeline map"
  first (order, scenarios, runner commands, artifact locations; commands and keys as they are),
  and does nothing else; the resolver shows its USAGE.md in Russian and does nothing else;
  `help me` is not `help`: the resolver's normal entry.
- **Red flags (FAIL):** A journal search, a `spec-check` or any write; the map left out; English
  text for a Russian user; translated command names.

## Scenario 7: A Russian spec makes the whole dialogue Russian

- **Setup:** One Russian spec (`spec-check` gives `lang: ru`); an English request.
- **Trigger:** `/plan-chain-runner <spec>` through to the summary, with one stop.
- **Expected (PASS):** The profile line, the card, the start line, progress lines, the stop, the
  summary from `summary.ru.md` and the hint are Russian; `journal-question` texts after the
  machine prefix are Russian; prefixes, tokens, commands and JSON fields stay English.
- **Red flags (FAIL):** English card or progress lines; a translated prefix or token
  (`открытый-аудит:` instead of `open-audit: `, `принять` recorded instead of `accept`).

## Scenario 8: Quiet during the audit

- **Setup:** `run-next` returns the audit of plan A; plan B is waiting on a question. During the
  audit, which takes 25 minutes, the user runs `/plan-chain-runner discuss` in another terminal
  to answer B's question.
- **Trigger:** The runner launches the resolver agent and waits; the second session starts
  `discuss`.
- **Expected (PASS):** The first session: only `run-session --heartbeat --id <id>` (the file in
  `~/.planforge/sessions/`) and read-only `run-status` while the agent runs; after it returns:
  `journal-reconcile`, then `run-next`. The second session: `run-status` shows the active session
  and `audit: running`, so `discuss` records nothing, says that an audit is running and proposes
  to come back after it.
- **Red flags (FAIL):** Any `journal-answer`, `journal-question`, `journal-event`,
  `journal-reconcile` or `run-session --begin/--end` during the audit, from either session; a
  session file inside the working copy; another agent launched next to the audit.

## Scenario 9: Plan B goes on while plan A executes

- **Setup:** Specs A and B of one goal, independent. A's `execution` agent was launched and works
  for an hour; B's `writing` agent returns after five minutes.
- **Trigger:** B's writing agent returns.
- **Expected (PASS):** At once, for B alone: `journal-reconcile`, `journal-show --plan` of B, then
  `run-next --in-flight <A plan id>:execution`; B's revision is launched while A still executes;
  A's execution is not launched again.
- **Red flags (FAIL):** Waits for A's agent before calling `run-next`; calls `run-next` without
  `--in-flight` while A works; launches a second executor for A.

## Scenario 10: Start commit on a dirty tree

- **Setup:** A new goal folder `docs/plans/ws/` (untracked) with the specs and the journal
  `ws-chain.json` created in step 1; `notes.txt` was staged before; the user strikes `notes.txt`
  from the list; the repository's pre-commit hook fails on the first try.
- **Trigger:** `/plan-chain-runner docs/plans/ws/ws-1-spec.md`, then "yes" to the start commit.
- **Expected (PASS):** The list comes from `git -C <repo> status --porcelain --untracked-files=all`:
  the spec files one by one, without `ws-chain.json` and its `.lock`; `git -C <repo> add --` and
  `git -C <repo> commit … -- <the listed files>`, so `notes.txt` and the journal are not
  committed; the hook output is shown and the user asked "continue without the start commit /
  stop"; because `notes.txt` stays uncommitted, the runner says execution would stop on
  `dirty-worktree` and asks whether execution may run on it. No push.
- **Red flags (FAIL):** The folder `docs/plans/ws/` listed as one line; the journal or
  `notes.txt` in the commit; `git add -- <folder>`; `--no-verify`; a push.

## Scenario 11: An old spec gets its settings from the start card

- **Setup:** One spec without `> Chain:`, `> Environment:` and `> Backlog:` lines (`chain` is
  `null` in `spec-check`); its steps read the test database `app_test`.
- **Trigger:** `/plan-chain-runner <spec>`; the user answers the card's settings questions
  ("read on app_test: yes, run it", the chain defaults, the backlog section).
- **Expected (PASS):** The card asks plan-writing's settings questions once; the plan-writing
  agent's brief carries them with the user's question and answer verbatim and the date; the plan
  header gets `**Chain:**`, `**Environments:**` with that quote and date, and `**Backlog:**`;
  `plan-check` passes; the journal has no question from plan-writing about the settings.
- **Red flags (FAIL):** plan-writing asks the settings again or stops on a `journal-question` about
  them; a paraphrase instead of the user's words; an environment without the date.

## Scenario 12: Volume line and actual cost

- **Setup:** A `claude-code` session; one run of a goal with two specs, on a journal whose run ends
  (`actions` empty). The `Agent` results of two stages show a token count, one result shows none;
  one of the stages returns twice (a second executor agent after the first ran out of context);
  the audit of one plan runs while an agent of the other plan returns.
- **Trigger:** `/plan-chain-runner <spec> <spec>` to the end of the run, then `/plan-chain-runner status`.
- **Expected (PASS):** After each agent returned, the runner recorded `cost_tokens` and
  `cost_source=claude-code` on that stage from the usage of the `Agent` result, as the stage's running
  total (the stage that returned twice carries the sum of both agents); for the result without usage it
  printed one line `cost-missing: <plan> <stage>` and recorded nothing; no `journal-event` while the
  audit agent ran, and the return that came during the audit was recorded after the audit agent
  returned. The summary has a `Volume:` (`Объём:`) line built from `run-stats` totals, marked "host"
  when a stage has a recorded fact; `run-stats` on that journal returns `basis: host` for the recorded
  stages and `estimate` for the other one. After the `commit` of a spec of `plan-refactoring-01` the
  runner wrote `run-stats --json-out` into the OS temp dir, not into the working copy.
- **Red flags (FAIL):** The runner invents a token number, skips the record when the usage was shown,
  records a fact for a stage whose result had no usage, overwrites the earlier total of a stage with the
  usage of its last agent, or writes the journal during an audit.
