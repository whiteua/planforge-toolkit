---
name: plan-executor
description: Use when executing a ready implementation plan, staged roadmap, or whole-plan task list that must advance one unit at a time with ledger-backed progress, gates, retries, rollback snapshots, and a final resolver proposal.
---

# plan-executor

If the only argument is `help`: show this skill's USAGE.md in the dialogue language (without a spec or plan: the language of the user's message; commands and keys as they are) and do nothing else.

## When to use

Use this skill when the plan already exists and the job is execution, not planning: staged plans from `plan-splitter`, plans from `plan-writing` (`### Task N:` headings), or other plans with explicit task headings.

Do not use it to invent a plan. Use `plan-writing` or `plan-splitter` first when the input is still unstructured.

## Hard Invariants

1. Never edit source `*.md` plan or stage files while executing them.
2. Progress lives only in `state.json`, changed only through `scripts/executor_tool.py`; `progress.md` is generated.
3. Exactly one unit runs at a time. A failed unit is retried or stops the run before anything else runs.
4. Only `commit-run` commits to the user's branch: in a chain after the audit, manually with the `commit` mode (`/plan-executor <plan> commit`). Snapshots are hidden refs `refs/plan-executor/<run>/<unit>`; never push, amend or force.
5. Destructive operations (`checkpoint-restore`) require explicit engineer confirmation. Every restore the executor makes passes `--exec-dir <exec_dir>`; otherwise the next `unit-begin` reports the restore itself as `foreign-changes`.
6. A gate cannot pass silently when checks are absent; no tests means escalation, not fake success.
7. A unit marked `**External:**` runs only when each of its `external` entries is `confirmed` (`run` in the settings, or a run-scope `consent`) or the engineer confirms it for that environment and access. `deny` stops the run; changes on prod are confirmed task by task, never for the whole run. Never run a step on an environment the plan does not list, and never widen a permission to another environment or from read to write.
8. Work beyond the unit's text happens only with the engineer's consent and is recorded with `unit-finish … --note`.

## Tool

`<SKILL_DIR>` is the directory containing this `SKILL.md`. Python ≥ 3.8, stdlib only. Every command prints JSON; errors print `{"ok": false, "errors": [...]}` with exit `2` (input/filesystem) or `1` (contract violation).

```bash
T="python <SKILL_DIR>/scripts/executor_tool.py"
$T ledger-init <exec_dir|auto> <plan_path> --workdir <repo> [--whole] [--allow-dirty] [--accept-drift] [--light <model>]  # --light: light=<model> of this launch
$T unit-begin  <exec_dir>
$T unit-finish <exec_dir> <unit_id> pass|fail [--error "<signature>"] [--note "<agreed deviation or External confirmation>"]... [--delegated <model>]  # --note repeats: one note per entry; --delegated: a subagent made this attempt
$T consent     <exec_dir> <env> read|write  # the engineer chose "the whole run"; refused for prod write and deny
$T run-diff    <exec_dir> [--markdown <file> [--include-fixes <journal>]]   # what this run changed: baseline vs last unit snapshot; --markdown writes the diff report
$T accept-changes <exec_dir> [--note "<why>"]   # the engineer keeps files changed outside the run
$T checkpoint-restore <repo> <sha> [--paths <file> ...] --exec-dir <exec_dir>   # only after engineer confirmation
$T checkpoint-prune <exec_dir>            # after the run, with confirmation
$T ledger-path <plan_path> --workdir <repo>   # commit mode: where this plan's ledger is; reads only
$T commit-run  <exec_dir> --message-file <file> [--journal <journal>]   # commit mode only: the run's files + the audit's fixes, with hooks
$T delegate-check <repo> --snapshot-out <exec_dir>/delegate-<unit>.json   # a delegated unit: the snapshot before its subagent
$T delegate-check <repo> --snapshot <exec_dir>/delegate-<unit>.json --files <path>...   # after it: verdict pass|fail
```

Other commands (`ledger-next`, `ledger-mark`, `ledger-status`, `parse-tasks`, …) are listed in [TOOLING.md](references/TOOLING.md); the loop does not need them.

## Workflow

1. **BOOTSTRAP** — the journal first (Chain journal below), then `ledger-init auto …`: the ledger goes to `<repo parent>/.exec/<repo>-<plan>/`, outside the repository and stable across sessions (a temp directory is refused as `exec-dir-ephemeral`). Tell the engineer the `exec_dir` from the result in one line before the first unit. With `light=<model>` in the arguments or the brief's `light` item, pass `--light <model>` on every launch ([EXECUTION-STRATEGY.md](references/EXECUTION-STRATEGY.md), Delegation). Show the result's `warnings`. Stop and ask the engineer on these errors: `no-units`, `dirty-worktree`, `plan-drift`, `settings-drift`, `settings-unavailable`, `exec-dir-inside-workdir`, `not-a-split-roadmap` (a goal roadmap of `plan-brainstorming` was given: tell the engineer to run `/plan-chain-runner <file>`). Details: [INPUT-DETECTION.md](references/INPUT-DETECTION.md).
2. **LOOP** — `unit-begin` → act on `reason`:

   | `reason` | Action |
   |---|---|
   | `ready`, `retry-available` | For every `external` entry: `confirmed` → one line, no question; otherwise ask (only this task / the whole run / stop; "the whole run" only for an entry with `access` and a known environment) or STOP on `deny` ([GATE.md](references/GATE.md)). Execute exactly this unit using `text` and `files` from the result (do not re-read the whole plan), then gate it with `strategy` ([EXECUTION-STRATEGY.md](references/EXECUTION-STRATEGY.md)) and call `unit-finish`. With `strategy.delegable: true` and a `light` model, the unit may go to a subagent on that model (EXECUTION-STRATEGY.md, Delegation); the file check (`delegate-check` before and after), the gate and `unit-finish … --delegated <model>` stay with you, and a retry always runs in the main agent. |
   | `in-progress` | A previous attempt was not finished: gate the current state and call `unit-finish`. |
   | `foreign-changes` | Files changed outside the run since the last unit (`foreign_changes`: `{path, status}`); nothing is marked running. Ask the engineer: accept / restore these files / stop ([GATE.md](references/GATE.md)). Without a confirmation channel, STOP with a stop-report listing the files. |
   | `exhausted`, `stagnated`, `blocked` | STOP with a stop-report. |
   | `all-done` | Go to FINALIZE. |

   `unit-finish … pass` snapshots and marks done (a failed snapshot turns into `fail`). `unit-finish … fail` returns `decision` (`retry`/`stop`) and `restore_to`; ask the engineer before `checkpoint-restore <repo> <restore_to> --exec-dir <exec_dir>`, then loop. Both move the ledger's `expected_tree`, so a retry is not reported as foreign. `foreign_changes: null` means the check is off (no git, or a ledger from before the check, where it starts after the next finished unit): show `foreign_warning` to the engineer in one line and continue.

   In a roadmap run each unit is one task of a part; `part-<id>-done` closes the part: check its completion criteria and handoff against the tasks just done, run what they name, then `unit-finish`. A unit without `text` (a part without those sections) is checked by its title.
3. **FINALIZE** — write the diff report `run-diff <exec_dir> --markdown <plan dir>/<base>-diffs.md` (the run's own changes, separate from work that was uncommitted before) and record the `diffs` stage; record out-of-scope findings with `journal-finding` (they go to `BACKLOG.md` too) and export them with `journal-export-findings` to `<goal>-followups.json`; propose `plan-resolver` per [RESOLVER-PROPOSAL.md](references/RESOLVER-PROPOSAL.md). Details: [WORKFLOW.md](references/WORKFLOW.md), FINALIZE.
4. **COMMIT** — a separate call, `/plan-executor <plan> commit`, after the audit (the resolver's gate names it) or after `resolver=skip`: `ledger-path` finds the ledger, the diff report is rebuilt with the audit's fixes, `commit-run` commits only the run's files and the audit's fixes with the repository's hooks. Details and every refusal: WORKFLOW.md, COMMIT. Offer `checkpoint-prune` only after this stage is `done`: it needs the run's snapshots.

Units of one `parallel_group` may run in any order, but always one at a time in one session.

## Chain journal

`J` = `python "<SKILL_DIR>/../plan-brainstorming/scripts/brainstorm_tool.py"`. The journal
`<goal>-chain.json` records the stages `execution`, `diffs` and `commit` of the plan for the other
skills and the chain runner; the rules per stage status: [WORKFLOW.md](references/WORKFLOW.md),
Chain journal. `ledger-init`, `unit-begin` and `unit-finish` write the `execution` stage and the
unit events themselves (a `journal_error` in their result: say it in one line and continue). The
agent writes the rest, always with `--plan <P>`, the master plan:

- before `ledger-init` (and in COMMIT): `J journal-path <plan> --create` → `journal`, `plan` (= `P`),
  then `J journal-show <journal> --plan <P>`; open questions of the stage you are about to run are
  asked (interactive) or stop the run (silent); answered ones are applied and marked with
  `J journal-answer <journal> <Qn> --applied`;
- a question asked interactively that decides how the run goes (External confirmation, foreign
  changes, retry or restore, the commit confirmation): `J journal-question <journal> --skill plan-executor --plan <P> --stage <stage> --text "<question>" [--option "<option>"]... --answer "<answer>"`;
- every STOP without a confirmation channel: the same command without `--answer` (a `running`
  stage becomes `stopped`; after `exhausted`/`stagnated`/`blocked` it stays `failed` with the
  question open), then `J journal-export-findings <journal>`, then the stop report. A stop in
  BOOTSTRAP (`dirty-worktree`, `plan-drift`, `settings-drift`, `settings-unavailable`) comes before
  `ledger-init` has moved `execution`: first `J journal-event <journal> --skill plan-executor --plan <P> --stage execution --status running`,
  then the question, so that it stops the stage (WORKFLOW.md, Chain journal);
- a defect outside the unit's text that is not fixed: `J journal-finding …` at once
  ([GATE.md](references/GATE.md), Deviations), never a file of its own.

Without `plan-brainstorming` alongside, the run works without the journal; say once
`plan-brainstorming not installed alongside`.

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

In this skill: `executor_tool.py detect-lang <plan>`; the stop reports below use the same language.

## Stop Reports

Use [stop-report.en.md](assets/stop-report.en.md) or [stop-report.ru.md](assets/stop-report.ru.md) according to `executor_tool.py detect-lang <plan>` (`ru` when more than 5% of the plan's letters are Cyrillic, otherwise `en`). Put `git diff --stat` and at most ~80 lines of diff into the report, not the full diff. Fill `{{delegated}}` with the unit's `delegated` model and whether that attempt failed, or "no" (in the plan's language). Without a confirmation channel, record the decision the stop needs first (`journal-question`, then `journal-export-findings`, Chain journal) and fill the report's journal section with the question id and text, the journal path and the exported follow-ups path; without a journal, leave that section out.
