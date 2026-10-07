---
name: plan-chain-runner
description: "Use when one or more approved specs (`*-spec.md`) of one goal, given as spec files or the goal roadmap (`<goal>-roadmap.md`), should go through the whole pipeline (plan, revision, split, execution, audit, commit) without the user launching each skill. Also use to continue such a run, to discuss the questions it stopped on, to show its status, or with `help` for a map of the pipeline."
---

# plan-chain-runner

If the only argument is `help`: show this skill's USAGE.md in the dialogue language (without a spec or plan: the language of the user's message; commands and keys as they are) and do nothing else.

Runs the approved specs of one goal — named by the goal roadmap `<goal>-roadmap.md` or given as files — through `plan-writing → plan-iterative-revision → [plan-splitter] → plan-executor → plan-resolver → plan-executor commit`. After a short start dialogue it works without questions: each stage is done by its own skill, launched as an agent with the model of its role; the runner decides what runs next from the chain journal `<goal>-chain.json`, reports progress in one line, and stops with questions recorded in the journal.

## Commands

| Call | What it does |
|---|---|
| `/plan-chain-runner <goal>-roadmap.md` | new run from the goal roadmap: its specs, `#` order, dependencies, groups and notes ([START.md](references/START.md)), then the loop |
| `/plan-chain-runner <spec> [<spec>…]` | new run of these specs (a subset of the goal roadmap when there is one): start dialogue ([START.md](references/START.md)), then the loop |
| `/plan-chain-runner continue [<goal>\|<roadmap>]` (`продолжить`) | resume from the journal ([LOOP.md](references/LOOP.md), Continue) |
| `/plan-chain-runner discuss [<goal>\|<roadmap>]` (`обсудить`) | the open questions one by one ([DISCUSS.md](references/DISCUSS.md)) |
| `/plan-chain-runner status [<goal>\|<roadmap>]` (`статус`) | summary from `run-status`; changes nothing |
| `/plan-chain-runner help` | USAGE.md, which opens with the pipeline map |

Without `<goal>` the runner looks for `*-chain.json` journals with unfinished stages in the spec folders of the repository: one → it is taken; several → ask which; none → say so. `help` together with other arguments is not `help`: the arguments are read as above. A goal roadmap in place of `<goal>` names its goal: `J journal-path <roadmap>` gives the journal.

## Hard Invariants

1. One run, one goal; one spec, one plan. Specs of different goals, or a goal roadmap whose specs lie in another goal's journal, are refused with the proposal to run them separately; specs are never merged into one plan.
2. The status of a stage comes only from the journal and the artifacts (`journal-reconcile`, `journal-show`, `run-status`), never from an agent's report.
3. What runs next is decided only by `run-next`. Never launch a stage it did not return, never do a stage's work yourself in a profile with agents, never edit the journal, a spec, a plan or the goal roadmap by hand. The runner only reads the roadmap: its order and graph reach the run through `run-init` after the user confirmed the card.
4. After the start card no questions to the user: a decision is a `journal-question` without `--answer`, that plan waits, the independent plans go on; all questions come together at the end.
5. While an `audit` agent runs, write nothing to the journal and nothing into the working copy: no questions, no `journal-reconcile`, no `run-session --begin/--end`. Only `run-session --heartbeat`, whose file is outside the working copy.
6. Commits: only the start commit the user agreed to (START.md) and plan-executor's `commit` stage. Never push, never `--no-verify`, never amend.
7. **External systems.** Investigation means reading the repository and running local commands without side effects (build, offline tests, grep). Anything that reaches an external system — a database, an API, a remote service, a cloud account — even a constant query, runs only after the user explicitly allows it and names the environment. A permission covers the named environment only: never extend it to another one, and never treat an existing project script that targets another environment as permission. Production needs a separate confirmation for every action. Pre-approved reads (`read=run` in the spec's `> Environment:` line, production included) cover the plan's steps and the read-only checks of plan-iterative-revision and plan-resolver; changes on production are never pre-approved. The runner reaches no external system itself and never confirms one for an agent: a task with a `task` right, a write on prod included, stops its plan with a question, and the runner cannot work around it.

## Tool

`<SKILL_DIR>` is the directory containing this file; always call the scripts by absolute path. Python 3.8 or newer, stdlib only. Every command prints JSON; errors are `{"ok": false, "errors": [...]}` with exit `2` (input, unreadable file, `unknown-spec`, `roadmap-mismatch`, `not-in-roadmap`, journal input errors) or `1` (contract: `graph-cycle`, `session-active`, `session-stale-running`, `session-taken-over`, `runner-missing`, `no-model`, `stage-not-open`, `no-marker`, `open-questions` from `host-wait`; `scheduler-bug` from `run-next`, `run-eta`, `run-status`, `run-stats`, `subset-check`, `run-checklist`). `session-taken-over` from `--heartbeat` or `--end` means another window took the run over: stop at once with one line, write nothing to the journal, no `--end`.

`C` = `python "<SKILL_DIR>/scripts/chain_tool.py"`; `J` = `python "<SKILL_DIR>/../plan-brainstorming/scripts/brainstorm_tool.py"`.

| Command | Use |
|---|---|
| `C settings-load [--file F] --profile P` | models, effort and `parallel` of a profile (`~/.planforge/runner.json`, else built-in) |
| `C settings-save --profile P --roles JSON [--file F]` | remember the edited table, only with the user's consent |
| `C model-pick --profile P --role R [--journal J] [--file F] [--light] [--unsupported MODEL]...` | the fallback model after a refusal; with `--journal` from the journal's `runner.models` (the loop always passes it); `--light` (role `execution`): the `light` model of delegated green units instead of the role's model |
| `C run-init <journal> --profile P --spec S... --graph JSON --models JSON [--parallel N] [--start-commit SHA\|declined\|none] [--roadmap R]` | write the journal's `runner` section (`parallel`: the card's value, read by `run-next`; `--roadmap`: the specs in the roadmap's `#` order, `runner.roadmap` and `runner.roadmap_sha256`, kept by a later call without it) |
| `C subset-check <journal> --roadmap R [--spec S]...` | the run a goal roadmap allows for these specs (none: all of them): `specs` in `#` order, `not_in_roadmap`, `missing_dependencies`, `graph` inside the set, `dropped_uncommitted` ([START.md](references/START.md)) |
| `C run-session <journal> --begin [--host H] [--takeover]` / `--heartbeat --id ID` / `--end stopped\|complete\|interrupted --id ID` | the active-session mark; `ID` is the `id` that `--begin` returned |
| `C run-next <journal> [--parallel N] [--in-flight PLAN:STAGE]...` | the actions to launch now (not the in-flight pairs, which still count), the waiting plans (among the reasons `host-wait: <N>s` and `reading-busy: <plan id>`), `done`, `blocked` (`false` during a host wait) |
| `C host-wait <journal> --plan P --stage S --error TEXT` | after the launch tool's error, never the agent's reply: `host_error: false` → the not-confirmed rule; else the pause (`attempt`, `wait_seconds`, `waited_total`, `wait_until`) or `exhausted: true` (the stage is `failed`, `run-next` asks `stage-failed:` at once); exit `1` `stage-not-open` for a `done` or `skipped` stage ([LOOP.md](references/LOOP.md), After the agents, 3) |
| `C writing-resume <journal> --plan P` | before each relaunch of a writer with `resume: true`, not after a host wait: records the plan's task count and sha256; three equal records in a row make `run-next` ask `stage-failed: writing`; exit `1` `no-marker`, `2` without the plan file ([LOOP.md](references/LOOP.md), 4) |
| `C run-eta <journal>` / `C run-status <journal>` | ETA; the per-plan status table, with `roadmap` (`path`, `sha_matches`, `missing`, `not_in_roadmap`; `null` without one) and `order` (`plan`, `n` — the `#`, `group`) |
| `C run-stats (<journal> \| --plan <plan.md>) [--baseline <json>] [--json-out <file>]` | sizes, durations, token cost (the host's fact when recorded, else an estimate from the artifacts) and quality per stage; the summary's volume line; deltas against an earlier result ([docs/COST.md](../../docs/COST.md)) |
| `C run-checklist <journal> [--backlog-root R]` | at the end of a finished run (`done: true`) the checklist after it as lines of the goal's `BACKLOG.md` section: installed skills after commits under `skills/`, `checkpoint-prune` of the committed plans, units noted `subagent-unavailable`, specs to amend after deviations; only the plans of `runner.specs`; a line already there is not repeated (`appended`, `exists`); `warnings` (`backlog-unavailable`, `backlog-write-failed`, `executor-not-installed`) never stop the summary ([LOOP.md](references/LOOP.md), 7. End) |

Journal commands: `J spec-check`, `roadmap-check`, `roadmap-parse`, `journal-path --create`, `journal-event`, `journal-question`, `journal-answer`, `journal-finding`, `journal-show`, `journal-reconcile`, `journal-export-findings`, `backlog-parse`. `executor_tool.py` is used only through the plan-executor skill.

## The loop (LOOP.md is authoritative)

1. `C run-next <journal> --in-flight <plan id>:<stage>...` at the start and whenever an agent returns, naming the agents still working; never while an audit agent works.
2. `skip` → `J journal-event … --status skipped`; `ask` → `J journal-question … --skill plan-chain-runner --spec <spec>`; `answer` → `J journal-answer … --answer rewrite` (the drift cascade); `run` → an agent of the profile with the role's model and the silent brief ([PROFILES.md](references/PROFILES.md)); the `run` actions of one answer start together.
3. After each agent: `J journal-reconcile`, `J journal-show --plan`, a progress line, its notes worth knowing as `J journal-finding` ([LOOP.md](references/LOOP.md), After the agents, 7); a launch tool's error goes to `C host-wait` first (a pause, then the same action; after an hour `stage-failed:`); a stage the journal does not confirm after the agent returned (whatever it said) gets one repeat, then a `not-confirmed:` question; an agent silent for 60 minutes counts as failed.
4. `actions` empty → (`done: true`: `C run-checklist <journal>`,) the summary ([summary.en.md](assets/summary.en.md) / [summary.ru.md](assets/summary.ru.md)), the open questions with the hint `discuss`, one push line (PROFILES.md, Notifications and questions), then `C run-session <journal> --end … --id <id>`.

## Language

**Dialogue language.** Everything the user sees is in the language of the primary task (the
goal, idea or findings in `plan-brainstorming`, the plan in every later skill): questions, option
labels and option descriptions in a question UI, status lines, confirmations, human gates, final
summaries and stop reports. Only tokens that parsers match stay in English: `### Task N:`,
`**Files:**`, `> Tier:`, command names and JSON field names. Sample phrases quoted in these
instructions ("Spec written to …", "MAX review passes done …", "I'm using the plan-writing
skill …") are templates: say them in the dialogue language, not verbatim. The language is
detected, not guessed: `ru` when more than 5% of the letters are Cyrillic, otherwise `en`.

**Free backlog.** `BACKLOG.md` at the repository root is a free file: the user writes to it at any moment, and no stage treats a change to it as a foreign change.

In this skill: the `lang` field of `spec-check` of the first spec at the start, then the journal's `lang` (`journal-show`); the summary uses the same language; `help` without a spec or journal answers in the language of the user's message.
