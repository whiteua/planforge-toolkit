# LOOP

The main loop after the start (START.md) and after `continue`. `C` and `J` as in SKILL.md, Tool. `<journal>` is the absolute path of `<goal>-chain.json`.

**Paths.** `spec`, `plan` and file `args` in the results of `run-next` and `run-status` are relative to the journal's directory, which `run-next` returns as `journal_dir`. Join them with `journal_dir` before passing them to an agent. For `J journal-*` commands `--plan` takes the plan id (the plan file name without `.md`) or that joined path.

## 1. Next actions

Call `C run-next <journal> [--in-flight <plan id>:<stage>]...` at the start and each time an agent returns, with one `--in-flight` per agent of this run that is still working (`<plan id>` = the plan file name without `.md`). Those pairs are not returned again, but they count toward `parallel` and the rules that keep the code stages and the audit to one plan. Without `--parallel`, `run-next` takes the width from `runner.parallel` (the value confirmed in the card, written by `run-init`), on `continue` too. Keep the set of launched pairs: never launch a pair that is in it. While an audit agent is in flight, do not call `run-next` and write nothing (While an audit runs). Act on every entry of `actions`:

| `kind` | Action |
|---|---|
| `skip` | `J journal-event <journal> --skill plan-chain-runner --plan <plan> --stage <stage> --status skipped --data '{"why": "<why>"}'` |
| `ask` | `J journal-question <journal> --skill plan-chain-runner --plan <plan> --stage <stage> --text "<prefix> <explanation in the dialogue language>" --option <token>...` with the `prefix` and the `options` of the action as they are |
| `answer` | `J journal-answer <journal> <qid> --answer <answer>`: the cascade of a `rewrite` (below); no question to the user |
| `run` | launch `/<skill> <args>` as an agent of the profile (2) |

**Drift cascade.** After the user answered `rewrite` on `drift: <stage>` of a plan, the stages after it are entered again with `reason: drift`, in order, without new questions. `journal-reconcile` still asks `drift: <later stage>` for each of them whose input changed; for such an open question of the same plan, given after the later stage finished, `run-next` returns `answer` with `answer: "rewrite"`: record it as it is, like `skip`. A `keep` answer on `drift: <stage>` keeps that stage: it is not entered again. So a rewritten spec or plan costs the user one stop: the `drift:` question of the earliest changed stage.

**Code stages and recommit.** One plan at a time holds the code stages (execution, diffs, audit, commit): the one with an agent in them, else a plan in them whose changes are uncommitted (its execution started and no `commit` done or skipped since), else the first in runner order. A plan that drift sent back to writing, revision or split after its execution started keeps the hold until it commits, so a committed plan that drift brings back to execution never runs over another plan's uncommitted changes; the others wait with `code-busy: <plan id>`. A `done` commit that finished before the last `execution` or `audit` of its plan is entered again with `reason: recommit`.

All `run` actions of one answer start together in a profile with agents (PROFILES.md), next to the agents still in flight; in `fallback` one after another. `waiting` lists the plans that wait and why: it feeds the progress lines, it needs no action. After `skip`, `ask` and `answer` call `run-next` again before launching anything: the answer may change.

Machine questions are answered with exactly one token (DISCUSS.md): `open-audit: <plan id>` → `accept` / `fix`; `not-confirmed: <stage>` and `stage-failed: <stage>` → `retry` / `stop`; `drift: <stage> …` (written by `journal-reconcile`) → `rewrite` / `keep`; `model: <role>` → `retry <model>` / `retry` / `stop` (3; `retry <model>` is the one answer of two tokens). The runner records answers. Marking a skill's question `--applied` is the job of the stage's owner when it resumes; the questions with `--skill plan-chain-runner` are the runner's own (except `dirty-worktree:`, which the executor applies: Brief, 8), and it marks them itself with `J journal-answer <journal> <Qn> --applied`, never while an audit agent runs:

- `open-audit:` → after `run-next` freed the dependent spec (`accept`) or returned the `fix` run (`fix`);
- `stage-failed:`, `not-confirmed:`, `model:` answered `retry` → after the repeat was launched (`model:`: after `run-init` with the new model, Continue);
- answered `stop` → once the stage has moved (the user ran it by hand, or it ended `done`, `skipped` or `failed`).

One question of a skill is marked by the runner too: `drift: <stage>` (written by `journal-reconcile`) answered `keep`. That stage is not entered again, so no owner resumes to apply it: `J journal-answer <journal> <Qn> --applied` after a `run-next` whose `actions` hold no `run` of that plan and stage, never while an audit agent runs.

## 2. Brief

Model and effort of the role (`role` of the action): `runner.models[<role>]` of the journal file, the table the user confirmed. How the profile passes them: PROFILES.md. The brief, in this order, nothing more:

1. Run `/<skill> <args>` (the joined paths).
2. There is no confirmation channel: this is a silent run of the skill.
3. When a decision is needed, record it with `journal-question` without `--answer` and stop.
4. Journal: `<journal>`.
5. Model of the role: `<model>` (effort `<effort>`, or inherited).
6. Only when the action has `reason`: the stage is `done` (or a running fix audit) and is entered again; its `running` event carries `--reason <reason>`.
7. Only for `plan-writing` of an old spec: the settings answers of the start card (START.md, 4) to write into the plan header without a question: `**Chain:**` with the four keys, `**Backlog:**`, and under `**Environments:**` one line per environment in plan-writing's form, `` - `name` (test|prod; read=…, write=…) — "<the user's question and answer, verbatim>" (<date>) ``.
8. Only for `plan-executor`'s `execution` when the journal has the runner's answered `dirty-worktree:` question of this plan (START.md, 5): the user allowed the run on the uncommitted changes listed at the start; apply that question (`ledger-init … --allow-dirty`), then `J journal-answer <journal> <Qn> --applied`.

Never add "report back that it is done" style requests: the journal is the report.

## 3. After the agents

Each time one agent returns (or fails to start), for that agent alone; the others keep working:

1. `J journal-reconcile <journal>`, then `J journal-show <journal> --plan <plan>` for its plan. Then remove its pair from the in-flight set and go to 1 (Next actions).
2. The stage of the action is `done` or `skipped` → fine. `stopped` → the plan waits on its question. `failed` → nothing to do here: `run-next` repeats it once and asks `stage-failed:` the second time.
3. Whatever the agent did — said it finished, failed, returned an error, or returned without a word — the stage is not confirmed when the journal does not show it moved: still `pending` or `running` (and it is not the execution case of 4), or, for an action with `reason`, still `done` with the same `finished_at` as before the launch. Not confirmed → launch the same action once more. Still not confirmed → `J journal-question <journal> --skill plan-chain-runner --plan <plan> --stage <stage> --text "not-confirmed: <stage> <what the agent said and what the journal shows>" --option retry --option stop`. An agent that has not returned and left no new journal event for 60 minutes counts as failed under the same rule: stop waiting for it and launch the repeat.
4. The host refused the model or its effort → `C model-pick --journal <journal> --profile <profile> --role <role> --unsupported <model>` (one `--unsupported` per model refused so far): with `--journal` the role's model, effort and `fallback` come from `runner.models` of the journal, the table the agent was launched with, not from the settings file. The outcomes:
   - `fallback_used: true` → one line "model X unavailable, using Y", relaunch with that model;
   - `fallback_used: false` with a model other than the refused one → the same line, launch with it;
   - the refused model again, exit `1` `no-model`, or exit `2` → `J journal-question <journal> --skill plan-chain-runner --plan <plan> --stage <stage> --text "model: <role> <which model failed, the error>" --option retry --option stop`; the plan waits. In `discuss` the user answers `retry <model>` (the model to use for the role), `retry` (the same model again) or `stop`; on `continue` the runner applies it itself (Continue).

   A role launched through `subagent_type: planforge-<role>` (PROFILES.md, Agent definitions) has its model in that file: to use another model, launch the role without `subagent_type` and with `model`, and say in the line that the role's effort is now inherited.
5. One progress line per finished stage (5).

## 4. A large plan's execution

An executor agent may run out of context. When `execution` is still `running` with no `failed` or `stopped`, `run-next` returns it again: launch a new executor agent with the same brief; it continues from its ledger. Repeat until the stage is `done`, `failed` or `stopped`.

## 5. Progress messages

One line each, in the dialogue language; numbers from `C run-status <journal>` and `C run-eta <journal>`. Templates (said in the dialogue language):

- a stage starts or ends: `[plan 1/2 · revision] done: review-3, converged. Next: split. ≈ 1 h 20 min left`;
- during execution, every 10 tasks or every 10 minutes, whichever comes first: `execution: 34/108 tasks, ≈ 55 min`;
- an agent silent for more than 10 minutes: `revision of plan 1 has been running for 14 min, waiting`.

`eta_minutes: null` → leave the time out. Do not report more than this.

## 6. Session mark

`C run-session <journal> --heartbeat --id <id>` (the `id` returned by `--begin`) at every step of the loop and at least every 10 minutes while waiting for a long agent; it writes only the session file in `~/.planforge/sessions/`. Exit `1` `session-taken-over` (the mark has another id or is gone) → another window continued this run: stop at once with one line ("the run was continued in another window"), no journal write, no `--end`. Where the host can run agents in the background and notify on completion, launch them so and heartbeat while waiting. A mark older than 30 minutes looks abandoned to another session. Exit `2` (the mark cannot be read, e.g. `cannot read …`) → repeat once; still exit `2` → stop with a short report (the session file, the error), no journal write.

## While an audit runs

From the launch of a `plan-resolver` agent until it returns: no `journal-question`, `journal-event`, `journal-answer`, `journal-reconcile`, no `run-session --begin/--end`, no file written in the working copy. The resolver fingerprints the working copy before and after its audit, and any such write invalidates it (`probe-mutated-workspace`). Reading (`run-status`, `journal-show`) and `run-session --heartbeat` are allowed. `run-next` never starts anything next to an audit.

## 7. End

`actions` is empty:

1. `J journal-export-findings <journal>`; `J backlog-parse <repo root>/BACKLOG.md --section <goal>` for the goal's backlog lines.
2. The summary from `assets/summary.<lang>.md` (`lang` = the journal's `lang`): per plan the links from the journal file's `plans[].stages.<stage>.artifacts` — plan (`writing.plan`), last review (`revision.review` when the stopping audit wrote one, else found on disk: `<plan base>-review-N.md` next to the plan with the highest `N`; a converged run records only the completion and the verdict) and completion (`revision`), roadmap and parts (`split`), ledger (`execution.exec_dir` + `/state.json`), report and its status (`audit`), diff report (`diffs.diffs`), commits (`commit.commits`) — then `<goal>-followups.json` and the backlog lines. Fill one plan block per plan.
3. `done: true` → `C run-session <journal> --end complete --id <id>`.
4. Otherwise (`blocked: true`, or plans waiting) → the summary's open-questions section lists the open questions (`run-status` `open_questions`: id, plan, stage, text) and the waits without a question (`run-status` `waits`: `stage-failed: stop`, `not-confirmed: stop`, a `model:` answered `stop`, and `code-busy: <plan id>` for the plans they hold, each with the way out: run that stage by hand, then `continue`), and ends with the hint: `discuss`, then `continue`. Then `C run-session <journal> --end stopped --id <id>`.

The user interrupts the run → `C run-session <journal> --end interrupted --id <id>` when there is still a turn to do it, but never while an audit agent may still be working: then leave the mark; it ages out, and the next `--begin` asks (`session-stale-running`).

## Journal errors

- `journal-locked` (exit `1`) → repeat once; still locked → stop with a short report (journal path, the command), `run-session --end stopped --id <id>`.
- `journal-corrupt` (exit `2`) → stop with a report and propose `J journal-reconcile <journal> --rebuild`; after it, `continue` shows the card again (START.md, Rebuilt journal).
- `journal-write-failed` → stop with the error text.

## Continue

`/plan-chain-runner continue [<goal>]` (`продолжить`):

1. Find the journal (SKILL.md, Commands).
2. `C run-session <journal> --begin --host <profile>`; keep the `id` (Session mark). `session-active` (a mark younger than 30 minutes) → ask "continue here / stop"; continue → `--takeover`. An older mark is abandoned: `--begin` takes it without a question, unless the journal has a stage `running`: exit `1` `session-stale-running` (`stage`, `plan`, `age_seconds`) → ask "continue here / stop", naming the stage and how old the mark is (an audit of another window may still be working); continue → `--takeover`. `runner-missing` → START.md, Rebuilt journal.
3. `J journal-reconcile <journal>`.
4. Detect the profile again (PROFILES.md). It differs from `runner.profile` of the journal file → one line about it, `C settings-load --profile <new>`, then `C run-init` from the journal's directory (START.md, 6) with the same specs, graph and `start_commit` and the new profile's models and `parallel`. The card is not shown again.
5. The runner's answered `model: <role>` questions (journal file's `questions`, `skill: plan-chain-runner`, status `answered`) are applied by the runner itself, an exception to "the owner applies": `retry <model>` → `C run-init` from the journal's directory with the same specs, graph, `start_commit` and `parallel` and that model for the role (the other roles as in `runner.models`), then `J journal-answer <journal> <Qn> --applied` (until then `run-next` keeps the plan waiting with `model: retry`); `retry` alone → `--applied` (the same model is tried again); `stop` → `run-next` keeps that plan waiting (`model: stop` in `waiting` and in `run-status` `waits`) until the stage moves (the user runs it by hand); mark the question `--applied` once the stage has moved.
6. The loop from 1. Stages left `running` by the interrupted session come back from `run-next`; their owners resume them their own way (the executor from its ledger, the revision with a new pass, the resolver with a new audit pass, or through `discover` in its fix loop) and apply the answered questions of their stage, marking them `--applied`. A `running` audit comes back as `/plan-resolver <plan>`, or as `/plan-resolver <plan> fix` when an `open-audit:` answer `fix` started it (its last `stage-start` has the reason `audit-open`): launch it as returned. The resolver goes on from the code as it is (fixes already made stay, their `fix_files` are in the journal); a report that is still open after a plain audit brings the `open-audit:` question again.

## Status

`/plan-chain-runner status [<goal>]` (`статус`): `C run-status <journal>`, rendered in the journal's language: per plan the stages, the current stage, progress, then the open questions, the waits without a question (`waits`), the ETA and whether a session is active. It writes nothing: no `journal-reconcile`, no session mark.
