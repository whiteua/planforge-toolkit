---
name: plan-iterative-revision
description: |
  Use when a written implementation plan must be audited against the actual codebase and fixed
  iteratively: each pass records issues in a new immutable review file, applies them to the plan,
  and repeats until the plan is clean or a stop gate fires. Not for reviewing code or executing plans.
allowed-tools:
  - Read
  - Grep
  - Glob
  - Edit
  - Write
  - Bash
  - Agent
---

# Plan Iterative Revision

If the only argument is `help`: show this skill's USAGE.md in the dialogue language (without a spec or plan: the language of the user's message; commands and keys as they are) and do nothing else.

A two-phase loop over one master plan: **Phase A** audits the plan against the codebase,
the helper script records the issues as `<basename>-review-<N>.md`; **Phase B** applies that
review to the plan. It repeats until a stop gate fires. All bookkeeping (numbering, fingerprints,
gates, review rendering, validation) is done by the script; you do the audit and the edits.

## Inputs

- `PLAN` (required): path to the master plan, e.g. `docs/plans/plan01-impl.md`, or a plan-splitter
  roadmap `<base>-roadmap.md` (batch mode, see below).
- `parts`: batch mode only; `all` (default) or a comma-separated list of part ids to verify.
- `mode`: `full-cycle` (default) or `audit-only` (the user asks for "only audit", "only a review",
  "don't implement"): one audit, one review file, no Phase B.
- `preset`: `quick` | `standard` (default) | `deep`. Sets `lenses` 1/2/4, `rigor`
  `grep`/`read`/`explore`, `max` 3/5/7. `lenses`, `rigor`, `max` can be overridden one by one.
- `stop_policy`: `pragmatic` (default; stop when only `nit` issues remain) | `strict`.
- `interaction`: `auto` (default) | `interactive` | `autonomous`. `auto` means `interactive` when a
  question tool (AskUserQuestion, vscode_askQuestions, ...) is available, otherwise `autonomous`.
  Callers such as `plan-splitter` run you as a subagent: that is `autonomous`.
- Chain settings: `bootstrap` returns `settings`, read from the plan header or, when the header has
  none, from the spec named by `**Spec:**`; a part or a roadmap goes through its `Source` line to
  the master plan. An explicit `Chain` (`settings.chain_explicit`) supplies `preset` =
  `chain.revision` and `stop_policy` = `chain.stop` unless the user passed them;
  `config_from_settings` lists what it supplied. `settings: null` means `plan-brainstorming` is not
  installed next to this skill: the run works as without settings.
- Task index: `plan-brainstorming` alongside also gives `parse_plan_tasks`, the source of the task
  hashes that make re-audits incremental (Loop, "Incremental re-audit"). Without it every audit is full.

## Tool

`TOOL` = `python "<SKILL_DIR>/scripts/next_review_index.py"`, where `<SKILL_DIR>` is the directory
containing this file (not the user's project). Always call it by absolute path. Python ≥ 3.8,
stdlib only. If `python` is unavailable, stop and tell the user.

## Hard invariants

1. Phase A edits no file. Only `TOOL record` writes the review or completion file.
2. Phase B edits only `PLAN`: never the review files, never project code.
3. Never modify code, never run the project's tests/builds/linters/migrations, never create
   plan copies, branches or commits.
4. There is no substitute for the review file: not memory, not chat, not edits to the plan.
   If `bootstrap` reports `valid: false`, stop before auditing and tell the user its `errors`: the
   directory that is not writable, or `plan-incomplete` (the plan still carries plan-writing's
   marker `> Writing: in progress`: `/plan-writing <spec>` finishes it).
5. Gate decisions come only from `record`. Never continue after `action: "stop"` and never stop
   on your own while it says `implement` (except when the user interrupts).
6. Wrap each phase in the diff guard (`GROOT`, Loop). Without git it checks no files (exit 3) but still measures the
   plan for the budget.
7. External systems: Phase A may run read-only checks only on an environment with `read=run` in
   `B.settings.environments` (references/PHASE-A-AUDIT.md, Step 3); anything else that reaches an
   external system needs the user's explicit permission for that environment.
8. Besides the review files and `PLAN`, the skill writes only the chain journal (with
   `BACKLOG.md` and `<goal>-followups.json`), only through `brainstorm_tool.py`, and only between
   the guard windows of the phases (Chain journal below).

## Batch mode (a plan-splitter roadmap)

If `PLAN` ends with `-roadmap.md`, verify its parts one after another. Only the parts are
audited; the roadmap and the source plan are not.

```
P = TOOL parts PLAN                      # parts in table order; exit 1 if a part file is missing → report and stop
parts = P.parts (`parts=all` or absent), or only the ids in `parts=` (roadmap order; an unknown id → report and stop)
finals = {}
for part in parts:
    run the whole Loop below with PLAN = part.path: bootstrap (same preset/stop_policy
    arguments), audits, Phase B, gates. Each part has its own review numbering, completion
    file and guard labels (`<B.basename>-phase-a`).
    finals[part.id] = R.final                                  # on action "stop"
    a part that cannot be verified (bootstrap not valid, guard violation) does not stop the
    batch: finals[part.id] = {"result": null, "error": "<what happened>"}; continue
write finals to a temp file as {"parts": finals}
S = TOOL batch-summary --results <that file | ->                # worst result wins; an error part = escalated
```

Print `S` as the final output (autonomous; it replaces `R.final`), or a per-part table plus `S`
(interactive). Never verify parts in parallel: the diff guard and the review numbering are per
plan, not per run. `guard-begin`'s `changed_count` grows across parts because earlier parts' new
files are uncommitted; that is expected.

## Loop

```
MODE = full-cycle | audit-only; I = interactive | autonomous   (resolved from Inputs)
B = TOOL bootstrap PLAN [--preset P] [--lenses L] [--rigor R] [--max M] [--stop-policy S]
if not B.valid: report B.error / B.errors and stop
journal start (Chain journal below); batch mode or a single part: no stage events, findings only
if B.config_from_settings is not empty:
    announce preset + stop_policy as taken from the spec settings; do not ask
elif I == interactive and the user gave neither preset nor stop_policy:
    ask once to confirm preset + stop_policy (then no more questions until the limit gate)
if B.settings and not B.settings.ok and PLAN has `**External:**` lines:
    interactive → ask which environments the audit may read
    autonomous  → final output {"result": null, "error": "<B.settings.errors>"} and stop
MAX = B.config.max; S = B.config.stop_policy; k = 1; FULL = false
GROOT = B.git_root, else B.dir     # the guard's root; without git guard-begin still keeps the plan's size (exit 3)
DEFERRED = ""                      # "<id>:budget,…": the issues the last Phase B deferred for the budget
BUDGET = {}                        # fingerprint → title of every issue deferred for the budget in this run

loop:
    TOOL guard-begin GROOT <B.basename>-phase-a --plan PLAN
    SCOPE = full; TASKS = ""
    if k > 1:
        D = TOOL digest B.dir B.basename --since B.run_start;  T = D.task_digest
        if not FULL and T.scope in (incremental, none-changed):
            SCOPE = incremental; TASKS = T.tasks joined with ","
    if SCOPE == incremental and T.scope == none-changed:
        no Phase A (references/PHASE-A-AUDIT.md, Step 0): the issues JSON carries every D.active_contracts entry
    else:
        Phase A (references/PHASE-A-AUDIT.md; SCOPE incremental: the header and T.line_ranges only) → issues
        JSON, saved to a file outside the repository (e.g. the OS temp dir), or piped on stdin with --issues -
    R = TOOL record PLAN --run-start B.run_start --max MAX --stop-policy S --mode MODE
                    --interaction I --lang B.lang --issues <json-file> --scope SCOPE
                    [--tasks "TASKS"]                  (only with SCOPE incremental; TASKS may be empty)
                    [--deferred "DEFERRED"]            (only when DEFERRED is not empty)
    FULL = false
    if R.warnings: fix the issues JSON next time (unescaped code quotes); mention them in the summary
                   (`contracts-dropped`: the audit skipped an open contract, PHASE-A-AUDIT.md, Step 1;
                   `budget-unavailable`, `oversized-before-revision`: the budget, not the JSON, PHASE-B-IMPLEMENT.md)
    if R.action == "ask_limit":  ask "MAX review passes done, N issues still open. Continue?"
                                 options +3 / +5 / stop.
                                 +n → MAX += n and re-run the same record command;
                                 stop → re-run it with --user-stop
    TOOL guard-check GROOT <B.basename>-phase-a <R.review_path or R.completion_path or B.next_review>
    journal: R.journal_event → journal-event; this audit's code findings → journal-finding (Chain journal below)

    if R.action == "full-audit-required": FULL = true; repeat the loop with the same k (no Phase B)
    if R.action == "stop":       go to Final output
    if R.action == "implement":
        DEFERRED = ""
        TOOL guard-begin GROOT <B.basename>-phase-b --plan PLAN
        Phase B (references/PHASE-B-IMPLEMENT.md) on R.review_path, issues in R.issues order, within R.budget
        G = TOOL guard-check GROOT <B.basename>-phase-b PLAN
        if G.over_budget:                                  # one compression, in its own guard window
            TOOL guard-begin GROOT <B.basename>-phase-b --plan PLAN
            shorten the tasks of G.changed_tasks (PHASE-B-IMPLEMENT.md, Budget)
            TOOL guard-check GROOT <B.basename>-phase-b PLAN
        DEFERRED = the ids Phase B deferred for the budget, each as "<id>:budget", joined with ","
        BUDGET += their fingerprints and titles (from R.issues)
        k += 1
```

`MAX` limits the number of reviews that go to Phase B in this run: with `MAX = 5`, audits 1-5 can
be implemented and audit 6 hits the limit gate if issues remain.

**Incremental re-audit.** From the second audit on, `D.task_digest` compares the plan's tasks with the
`## Task digest` table of the latest review (8-hex SHA-1 of each task body) and sets the scope:
`none-changed` (the plan is byte for byte the one the latest review audited: Phase B applied nothing, no
contract can have closed, so no Phase A runs and the carried set stops the run at `unchanged`);
`incremental` (Phase A reads the header and the tasks of `T.tasks` by `T.line_ranges`: the changed and
new tasks, the tasks of the active contracts and every task that depends on a changed, new or removed
one through `Preconditions`); `full` (`T.reason`: no or a broken table, more than half of the tasks
touched, a contract whose location names no task, no task index). An incremental audit without issues
never ends the run: `record` answers `full-audit-required`, writes nothing and keeps `k` and `MAX`; the
next pass is full, and only its clean result gives `converged`. `audit-only` is always full. `T.reason:
task-parser-unavailable` (plan-brainstorming not installed alongside) means every audit is full:
interactive: say so once in the short report; autonomous: nothing is added, the final output stays
`R.final`. In batch mode each part has its own table and scope.

From the second audit on, `T.code_changed` also names the tasks whose files (the paths of their `Files` blocks) changed
on disk since the latest review's `## Code digest` (a SHA-256 per path, or `missing`, `unreadable`, `dir`, `glob`,
`outside`): they and their dependents are read like changed tasks and count toward the ratio, so a plan unchanged
byte for byte whose code changed is no longer `none-changed`. A review without that table warns `no-code-digest` and
skips the check; outside git the paths are read from the current directory (`code-root-cwd`).

The limit question needs a confirmation channel. A run without one (no question tool, a subagent
call, a chain run) is `autonomous`: `record --interaction autonomous` stops at the limit with
`result: limit` and never asks.

A `guard-check` violation means a phase touched a forbidden file: stop and report the paths.
`BACKLOG.md` at the repository root is never a violation: it is a free file (Language).
The guard sees only what `git status` sees (not ignored files, not paths outside the repository).
Without git (`guard-begin`/`guard-check` exit 3) it checks no files: say once that the guard is unavailable and list
the files you changed yourself; the budget fields of `guard-check` (`--plan`) still come and are used as with git.

## Chain journal

`J` = `python "<SKILL_DIR>/../plan-brainstorming/scripts/brainstorm_tool.py"`. The journal
`<goal>-chain.json` records the `revision` stage of the plan for the other skills and the chain
runner. `B.settings` is `null` (plan-brainstorming not installed alongside): no journal, say so
once. Journal commands never run inside a phase: the guard would report the journal and
`BACKLOG.md` as changed files.

- **Start** (after `bootstrap`): `<journal>` = `B.journal`; `null` → `J journal-path PLAN --create`
  (`journal`). `P` = the `plan` field of `J journal-path PLAN` (the master plan; a part leads to
  it). Every `--plan` below is `P`.
- **Stage mode.** Only a run on the master plan itself (`P` is the same file as `PLAN`) owns the
  `revision` stage. Batch mode (a roadmap) and a run on a single part (`PLAN` is a part: its
  Source line leads `journal-path` to another file, `P`) write no stage events and record no
  questions: the parts are verified inside the `split` stage of plan-splitter, and the master
  plan's `revision` stage and its input stay as they are. They skip the `journal-show` step below
  entirely, so they never stop with `stage-done` or `open-questions`; they only find `<journal>`
  and record code findings.
- `J journal-show <journal> --plan P`, stage `revision` (stage mode only; `unknown-plan`, exit `2`:
  no event of this plan yet, every stage is `pending`):
  - `pending`, `failed`, `running`, `stopped` without open questions → `J journal-event <journal> --skill plan-iterative-revision --plan P --stage revision --status running`;
  - `stopped` with open questions → `interactive`: ask each (its `text`, `options`) and record
    `J journal-answer <journal> <Qn> --answer "<answer>"`; `autonomous`: final output
    `{"result": null, "error": "open-questions: <ids>"}` and stop. Then apply each answered
    question:
    - "accept the plan as it is" → `J journal-answer <journal> <Qn> --applied`, then
      `J journal-event <journal> --skill plan-iterative-revision --plan P --stage revision --status running`
      and at once `J journal-event <journal> --skill plan-iterative-revision --plan P --stage revision --status done --input PLAN --artifact verdict=accepted`;
      then stop without a new audit and without an edit of the plan (`autonomous`: final output
      `{"result": null, "error": "stage-done: revision (accepted, <Qn>)"}`; `interactive`: say
      that the plan was accepted as it is);
    - "resolve by hand and re-run" (the user fixed the plan) or a raised `max` →
      `J journal-answer <journal> <Qn> --applied`, then `--status running` and the Loop as usual;
  - `done` → first the drift check: `J journal-reconcile <journal>`, then look in the journal
    file's `questions` for one of plan `P` whose text starts with `drift: revision` and that is
    not `applied` (the plan changed after the stage ended):
    - `open` → `interactive`: ask it (re-audit the changed plan, or keep the earlier result) and
      record `J journal-answer <journal> <Qn> --answer "<rewrite | keep>"`; `autonomous`: final
      output `{"result": null, "error": "open-questions: <Qn>"}` and stop;
    - answered `rewrite` → `J journal-event <journal> --skill plan-iterative-revision --plan P --stage revision --status running --reason drift`,
      the Loop as usual, and after the stage's `done` event `J journal-answer <journal> <Qn> --applied`;
    - answered `keep` → `J journal-answer <journal> <Qn> --applied`, then
      `J journal-event <journal> --skill plan-iterative-revision --plan P --stage revision --status done --input PLAN`
      (the same status: it binds the stage to the current plan without a new audit), then as
      without drift;
    - no such question → say that the revision already passed (`verdict`, `completion` in the
      stage's artifacts, read from the journal file itself: the `plans` entry with `id` P,
      `stages.revision.artifacts`; `journal-show` returns statuses only) and name the next stage;
      run again only when the user asks for it now: `--status running --reason user-request`.
      `autonomous`: final output `{"result": null, "error": "stage-done: revision"}` and stop.
    The journal's `done` is authoritative: a plan that was `clean` on its first audit has no
    review and no completion file, so `journal-reconcile` cannot rebuild that stage from
    artifacts.
- **After each `record`** (and its Phase A `guard-check`): `R.journal_event` not `null` and stage
  mode (in batch mode and on a single part it is never forwarded) →
  `J journal-event <journal> --skill plan-iterative-revision --plan P --stage revision --status <R.journal_event.status> --artifact <each entry of R.journal_event.artifacts>`,
  plus `--input <R.journal_event.input>` when `input` is present (only with `done`). The artifact
  values come relative to the journal's directory with forward slashes; pass them as they are.
  When it is `stopped` and the run is
  `autonomous`, then also `J journal-question <journal> --skill plan-iterative-revision --plan P --stage revision --text "<result, stop_reason and the open issue titles>" --option "<resolve by hand and re-run>" --option "<accept the plan as it is>"`
  and `J journal-export-findings <journal>`. The interactive limit question (`ask_limit`) is
  recorded with its answer: the same `journal-question` command with `--answer "<+3 | +5 | stop>"`.
- **Code findings**: defects in the existing code that are not problems of the plan
  (references/PHASE-A-AUDIT.md, "Findings about the code") are recorded after the Phase A
  `guard-check`, one command each:
  `J journal-finding <journal> --skill plan-iterative-revision --plan P --file <path from the repository root> [--line N] --summary "<what is wrong>" --failure-scenario "<what breaks, when>" --backlog-root <root>`,
  `<root>` = `git -C <dir of PLAN> rev-parse --show-toplevel` (outside git, the working
  directory). `action: exists` is fine. `backlog: failed` (with `backlog_error`): the finding is
  still recorded in the journal and exported; only its `BACKLOG.md` line is missing; mention it in
  the final output (a `user-section:` error means the section is the user's own and is never
  written, not even by hand).
- **Errors**: `journal-corrupt` (exit `2`) → say it, propose `J journal-reconcile <journal> --rebuild`,
  continue without the journal; `journal-locked` (exit `1`) → repeat once; still locked:
  `interactive` → ask whether to continue without the journal; `autonomous` → final output
  `{"result": null, "error": "journal-locked"}` and stop; `journal-write-failed` (exit `1`, the
  file system refused the write, e.g. a read-only journal) → say it in one line with the error
  text and continue without the journal; `illegal-transition` → do not force a status, mention it
  in the final output.

## Stop gates (decided by `record`, first match wins)

| Gate | When | result | stop_reason | File written |
|---|---|---|---|---|
| full audit required | an incremental audit (`--scope incremental`) found no issues | null (`action: full-audit-required`) | null | none; the same audit number runs again in full |
| clean | no issues on the first audit | `clean` | null | none |
| converged | no issues on a later audit | `converged` | null | completion file |
| user stop | `--user-stop` after the limit question | `limit` | null | review, `FINAL` |
| audit-only | `--mode audit-only` | `converged` | null | review, `FINAL` |
| drain | `pragmatic` and every issue is `nit` | `converged` | `drain` | review, `FINAL` |
| regression | audit ≥ 3 and an issue resolved earlier in this run is back | `escalated` | `regression` | review, `ESCALATED` |
| unchanged | same fingerprint set as the previous audit | `stagnation` | `unchanged` | review, `FINAL` |
| churn | audit ≥ 3, new issues but nothing resolved for 2 audits | `stagnation` | `churn` | review, `FINAL` |
| stuck | a fingerprint in 3 consecutive audits | `escalated` | `stuck` | review, `ESCALATED` |
| limit | audit number > `MAX` | `limit` (autonomous); interactive gets `action: ask_limit` | null | review, `FINAL` (autonomous) |

History is limited to the current run (`--run-start`); reviews from earlier runs are archive.
The pragmatic `drain` never hides real problems: it fires only when every open issue is `nit`.

## Final output

**Budget findings.** Before the final output, when there is a journal (`<journal>`, Chain journal): for each
fingerprint in `BUDGET` that is among the fingerprints of the last `record`'s `issues` (an issue still open; none when
that record wrote no review) record `J journal-finding <journal> --skill plan-iterative-revision --plan P --file <PLAN
from the repository root> --summary "budget: <its title>" --failure-scenario "<the contract stays unapplied: the plan
had no room for it in the budget of 150 000 bytes>" --backlog-root <root>` (`<root>` as for code findings).

- `autonomous`: no progress messages; the final message is exactly one JSON object, `R.final`
  (schema `assets/result.schema.json`: `result`, `iterations` = review files written in this run,
  `remaining_issues`, plus `escalated`, `stop_reason`, `flows`, `lenses_used`); in batch mode the
  `batch-summary` object instead (`result`, `remaining_issues`, `counts`, `parts`).
- `interactive`: a short report in the plan's language: result and reason, review files created
  in this run, remaining or escalated issues (id + title), the completion file if written. Add the
  `R.final` JSON at the end.

## Language

All artifacts and all issue text are written in the plan's language, `B.lang` (`ru` when more than
5% of letters are Cyrillic, else `en`). Instructions in this skill are in English regardless.

**Dialogue language.** Everything the user sees is in the language of the primary task (the
goal, idea or findings in `plan-brainstorming`, the plan in every later skill): questions, option
labels and option descriptions in a question UI, status lines, confirmations, human gates, final
summaries and stop reports. Only tokens that parsers match stay in English: `### Task N:`,
`**Files:**`, `> Tier:`, command names and JSON field names. Sample phrases quoted in these
instructions ("Spec written to …", "MAX review passes done …", "I'm using the plan-writing
skill …") are templates: say them in the dialogue language, not verbatim. The language is
detected, not guessed: `ru` when more than 5% of the letters are Cyrillic, otherwise `en`.

**Free backlog.** `BACKLOG.md` at the repository root is a free file: the user writes to it at any moment, and no stage treats a change to it as a foreign change.

In this skill: `B.lang` from `bootstrap`.

## References

- [references/PHASE-A-AUDIT.md](references/PHASE-A-AUDIT.md): read before the first audit.
- [references/ERROR-TAXONOMY.md](references/ERROR-TAXONOMY.md): the 10 issue classes, used in Phase A.
- [references/PHASE-B-IMPLEMENT.md](references/PHASE-B-IMPLEMENT.md): read before the first Phase B.
- [references/REVIEW-FILE-FORMAT.md](references/REVIEW-FILE-FORMAT.md): the rendered review format.
  You do not need it in a normal run; `record` renders and validates the file.
