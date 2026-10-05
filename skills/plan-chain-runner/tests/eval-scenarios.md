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

## Scenario 13: `plan-oversized` is one progress line

- **Setup:** Plan 1 of 2; its writing agent returns and the journal's last `stage-end` event of
  `writing` for that plan has `data: {"warnings": ["plan-oversized: 93 tasks, 486598 bytes
  (budget 40 tasks / 150000 bytes)"], "from": "running", "to": "done"}`.
- **Trigger:** The runner handles the returned agent (LOOP.md, After the agents).
- **Expected (PASS):** One line `[plan 1/2 · writing] plan-oversized: 93 tasks, 486598 bytes
  (budget 40 tasks / 150000 bytes)` in the dialogue language around the numbers; `run-next` is
  called and revision starts as usual.
- **Red flags (FAIL):** The chain stops or asks a question; the warning is repeated on every
  later stage; no line at all.

## Scenario 14: The gate skips the split stage

- **Setup:** Two plans with `split=auto`, both after revision. `run-next` returns
  `{"kind": "skip", "plan": "a-impl.md", "stage": "split", "why": "gate: keep (12 tasks, 40 KB, 1 modules, linear)"}`
  and a `run` of `plan-splitter` for `b-impl.md` with
  `"warnings": ["gate-unavailable: plan-splitter not installed alongside"]`.
- **Trigger:** The runner acts on the actions (LOOP.md, 1. Next actions).
- **Expected (PASS):** `journal-event … --plan a-impl --stage split --status skipped --data '{"why": "gate: keep (12 tasks, 40 KB, 1 modules, linear)"}'`
  without an agent; one progress line with the warning for plan b, then the splitter agent for
  plan b; `run-next` is called again before anything else is launched.
- **Red flags (FAIL):** A splitter agent for plan a; the chain stops or asks a question because of
  the warning; the warning repeated on every later stage.

## Scenario 15: A refused `light` model is no question

- **Setup:** `runner.models.execution` is `{"model": "opus", "effort": "medium", "light": "haiku"}`.
  The executor agent returns and says that its subagent could not start on `haiku`; the journal
  shows `execution` still `running`. `model-pick --journal … --role execution --light --unsupported haiku`
  exits `1` `no-model: execution`.
- **Trigger:** The runner handles the returned agent (LOOP.md, After the agents, 4).
- **Expected (PASS):** One line "light unavailable, running green units in the main agent"; no
  `journal-question`; the next executor brief has no `light` item (Brief, 9); the execution goes on
  (LOOP.md, 4. A large plan's execution).
- **Red flags (FAIL):** A `model:` question; the plan waits; the runner relaunches with `haiku`; the
  role's `model` changes; the brief still names `haiku`.

## Scenario 16: The start from a roadmap shows its graph, not a proposal

- **Setup:** Goal `g` with `g-roadmap.md` (`roadmap-check` valid): `#1 g-1-spec.md` (group A),
  `#2 g-3-spec.md` (group B, depends on g-1), `#3 g-2-spec.md` (group C, depends on g-3, notes
  "write after 3: it reuses 3's parser"). All three pass `spec-check`; profile `claude-code`; clean tree.
- **Trigger:** `/plan-chain-runner g-roadmap.md`.
- **Expected (PASS):** `roadmap-check`, `roadmap-parse`, `journal-path g-roadmap.md` (`kind: goal-roadmap`),
  the spec steps for each spec, `subset-check … --roadmap g-roadmap.md`; one card with the table in the order
  g-1, g-3, g-2 (`#`, depends on, group, tier, estimate), the edges line, the notes one line each and the
  sentence that `#` orders only within `parallel` and the code stages. After "yes": `run-init … --spec
  g-1-spec.md --spec g-3-spec.md --spec g-2-spec.md --graph '{"g-3-spec.md": ["g-1-spec.md"], "g-2-spec.md":
  ["g-3-spec.md"]}' … --roadmap g-roadmap.md`.
- **Red flags (FAIL):** Edges proposed with reasons as in the dialogue without a roadmap; the order of the
  file numbers (1, 2, 3); `run-init` without `--roadmap`; the roadmap edited.

## Scenario 17: Roadmap notes reach writing and revision, not execution

- **Setup:** The run of Scenario 16 after `run-init`. `run-next` returns a `run` of `/plan-writing
  g-2-spec.md` (role `writing`); later a `run` of `/plan-executor g-1-impl.md` (role `execution`).
- **Trigger:** The runner launches both agents (LOOP.md, Brief).
- **Expected (PASS):** `roadmap-parse g-roadmap.md` at the launch of the writing agent; its brief has the
  `roadmap` item with "write after 3: it reuses 3's parser" verbatim, the handoff of g-3 and "the spec
  outranks the notes". The executor's brief has no `roadmap` item.
- **Red flags (FAIL):** The notes paraphrased or cut; a `roadmap` item in an execution, audit or commit
  brief; the roadmap copied into the journal.

## Scenario 18: A changed roadmap on `continue`

- **Setup:** A journal with `runner.roadmap: g-roadmap.md`. After the run stopped, the roadmap was amended:
  g-2 no longer depends on g-3. `run-status` returns `roadmap.sha_matches: false`; no plan has uncommitted
  execution.
- **Trigger:** `/plan-chain-runner continue`.
- **Expected (PASS):** Before the loop: `roadmap-check`, `roadmap-parse`, `subset-check … --roadmap
  g-roadmap.md`; the card `roadmap-changed` names the removed edge g-2 → g-3. "Apply" → `run-init` from the
  journal's directory with the same profile, models and `parallel`, the new graph and `--roadmap
  g-roadmap.md`, without `--start-commit`; then `run-next`. "Keep the old graph" → nothing written, the loop
  runs on `runner.graph`.
- **Red flags (FAIL):** The new graph applied without confirmation; `run-init` before the card; `done`
  stages repeated; a `journal-question` instead of the card.

## Scenario 19: Specs given while the goal has a roadmap

- **Setup:** Goal `g` of Scenario 16 with `g-roadmap.md` next to the journal; g-1 is committed (`commit`
  done); g-3 and g-2 have not started.
- **Trigger:** `/plan-chain-runner g-2-spec.md`.
- **Expected (PASS):** After the spec steps: `roadmap-check g-roadmap.md` and `subset-check … --roadmap
  g-roadmap.md --spec g-2-spec.md` → `missing_dependencies: ["g-3-spec.md"]`; the card names g-3 and offers
  "add it to the run / stop". "Add" → `subset-check` with both specs, the run in the order g-3, g-2, and
  `run-init … --roadmap g-roadmap.md`.
- **Red flags (FAIL):** The graph dialogue as without a roadmap; g-2 started without g-3; an edge to a spec
  outside the run passed to `run-init` (`unknown-spec`).

## Scenario 20: `status` names `#` and groups

- **Setup:** A run from `g-roadmap.md`; `run-status` returns `order` `[{"plan": "g-1-impl.md", "n": 1,
  "group": "A"}, {"plan": "g-3-impl.md", "n": 2, "group": "B"}, {"plan": "g-2-impl.md", "n": 3, "group":
  "C"}]` and `roadmap` `{"path": "g-roadmap.md", "sha_matches": true, "missing": false, "not_in_roadmap": []}`.
- **Trigger:** `/plan-chain-runner status g-roadmap.md`.
- **Expected (PASS):** `journal-path g-roadmap.md` finds the journal; the plans in the order #1, #2, #3
  with their groups and the roadmap's path; nothing written.
- **Red flags (FAIL):** The order of the file numbers; `journal-reconcile` or a session mark; the roadmap
  applied again.

## Scenario 21: A roadmap of another goal is refused

- **Setup:** `h-roadmap.md` (`> Goal: h`, `roadmap-check` valid) lists `g-1-spec.md`, whose `journal-path`
  gives `g-chain.json`.
- **Trigger:** `/plan-chain-runner h-roadmap.md`.
- **Expected (PASS):** Refusal "one run is one goal" naming both journals, before `journal-path --create`;
  nothing written.
- **Red flags (FAIL):** A run started; the spec registered in h's journal; the roadmap edited.
