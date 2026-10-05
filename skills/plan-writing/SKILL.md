---
name: plan-writing
description: "Use when an approved spec (a `*-spec.md` from plan-brainstorming) must become a step-by-step implementation plan. Produces bite-sized TDD tasks with exact files, code and commands in the format plan-executor and plan-resolver parse."
---

# Writing Plans

If the only argument is `help`: show this skill's USAGE.md in the dialogue language (without a spec or plan: the language of the user's message; commands and keys as they are) and do nothing else.

Turn an approved spec into an implementation plan for an engineer who knows
nothing about this codebase: exact files, complete code, exact commands and
expected output, bite-sized tasks. DRY. YAGNI. TDD.

**Announce at start:** "I'm using the plan-writing skill to create the implementation plan."

> **Install requirement:** `plan-brainstorming` must be installed in the same
> parent directory: the spec contract and its checker live there. If
> `../plan-brainstorming/scripts/brainstorm_tool.py` is missing, STOP and tell
> the user to install `plan-brainstorming` alongside.

## Language

These instructions are in English. Write the plan body in the language of the
spec. Keep these tokens in English verbatim, because parsers match them:
`### Task N:`, `**Spec:**`, `**Tier:**`, `**Files:**`, `- Create:` /
`- Modify:` / `- Test:`, `**Preconditions:**`, `**Postconditions:**`,
`**Done when:**`, `- [ ] **Step N:**`.

**Dialogue language.** Everything the user sees is in the language of the primary task (the
goal, idea or findings in `plan-brainstorming`, the plan in every later skill): questions, option
labels and option descriptions in a question UI, status lines, confirmations, human gates, final
summaries and stop reports. Only tokens that parsers match stay in English: `### Task N:`,
`**Files:**`, `> Tier:`, command names and JSON field names. Sample phrases quoted in these
instructions ("Spec written to …", "MAX review passes done …", "I'm using the plan-writing
skill …") are templates: say them in the dialogue language, not verbatim. The language is
detected, not guessed: `ru` when more than 5% of the letters are Cyrillic, otherwise `en`.

**Free backlog.** `BACKLOG.md` at the repository root is a free file: the user writes to it at any moment, and no stage treats a change to it as a foreign change.

In this skill: the `lang` field of the `spec-check` result (section 1); `plan-check` reports the
written plan's `lang` by the same rule.

## Tool

`python "<SKILL_DIR>/scripts/plan_tool.py" <command>` (`<SKILL_DIR>` = this
skill's directory, absolute). Exit codes: `0` ok, `1` check failed, `2` bad input.

| Command | Use |
|---|---|
| `plan-path <spec>` | Plan path: `<X>-spec.md` → `<X>-impl.md` next to the spec (user preference overrides), and `writing_marker`: the plan's last line while it is being written, `> Writing: in progress (spec sha256 <first 12 hex of the spec's SHA-256>)` (`null` when the spec cannot be read; 4. Tasks, Writing order). |
| `plan-check <plan> --root <project>` | Plan format contract, after writing the plan. Also returns `settings` (read by the shared rule: plan header, else the spec at `**Spec:**`), `task_count`, `plan_bytes`, and `journal`: the chain journal the plan leads to, `null` when there is none. |
| `skeleton <plan> [--tasks ids] [--code none\|signatures]` | The plan without code bodies, for plan-resolver's first and closing full passes (this skill does not call it): the header, task headings, `Files`, conditions, `External`, `Size`, step headings, `Run:`/`Expected:`, one `[code <lang>, <N> lines: <signatures>]` line per code block. Text, not JSON; warnings on stderr. |
| `task <plan> <id>` | One task byte for byte, for the same callers. Text, not JSON. |

## Chain journal

The journal `<goal>-chain.json` next to the spec records the `writing` stage for the later skills
and the chain runner. `J` = `python "<SKILL_DIR>/../plan-brainstorming/scripts/brainstorm_tool.py"`;
`<plan>` = the plan path from `plan-path`.

- **Start**, as soon as `spec-check` in 1. Spec Preflight exits `0` (before the old-spec settings
  question): `J journal-path <spec> --create` → `journal` (it also
  creates the journal of a spec written before journals existed). Then `J journal-show <journal>`
  and take the entry of this plan from `plans` (`id` = the plan file name without `.md`); no entry
  means the stage is `pending`.
  - `pending`, `failed`, `running`, `stopped` without open questions → `J journal-event <journal> --skill plan-writing --plan <plan> --spec <spec> --stage writing --status running`.
  - `stopped` with open questions → with a confirmation channel ask each (its `text` and `options`,
    in the dialogue language) and record `J journal-answer <journal> <Qn> --answer "<answer>"`;
    without one stop and name the open ids. Answered questions: apply each answer, then
    `J journal-answer <journal> <Qn> --applied`, then `--status running` as above.
  - `done` → the plan was already written. First the drift check: `J journal-reconcile <journal>`,
    then look in the journal file's `questions` for one of this plan whose text starts with
    `drift: writing` and that is not `applied` (the spec changed after the stage ended):
    - `open` → with a confirmation channel ask it (rewrite the plan for the changed spec, or keep
      the plan) and record `J journal-answer <journal> <Qn> --answer "<rewrite | keep>"`; without
      one stop with a short report naming the question id;
    - answered `rewrite` (also when the user answered it outside the dialogue with
      `journal-answer`) → `J journal-event <journal> --skill plan-writing --plan <plan> --stage writing --status running --reason drift`,
      write the plan as usual, and after the stage's `done` event `J journal-answer <journal> <Qn> --applied`;
    - answered `keep` → `J journal-answer <journal> <Qn> --applied`, then
      `J journal-event <journal> --skill plan-writing --plan <plan> --stage writing --status done --input <spec>`
      (the same status: it binds the stage to the current spec without a rewrite), then as
      without drift;
    - no such question → say the plan is already written and go to 7. Execution Handoff; a
      rewrite the user still asks for runs without stage events (say so in one line).
- **Continuation**, right after the `running` event of Start when the stage was `running` or `failed` and the plan
  file exists: `J plan-tasks <plan>`. `incomplete: false` → the plan is written anew, as before. `incomplete: true`
  (the writing marker is in the file: a writer was cut off) → compare `marker_spec_sha` with the 12 hex in
  `writing_marker` of `plan-path`:
  - equal (the spec did not change) → keep the file: read it, redo 3. File Structure only for the tasks still to
    write, and go on with the task after the last one `plan-tasks` returned, by 4. Tasks, Writing order; say in one
    line after which task the writing continues;
  - different, or `null` (a marker without a fingerprint or with a broken one) → delete the plan file and write the
    plan anew.

  Neither case is a question.
- **End**, after 6. Check and Self-Review: `J journal-event <journal> --skill plan-writing --plan <plan> --stage writing --status done --input <spec> --artifact plan=<plan path relative to the journal's directory, forward slashes>`.
  When the `warnings` of the last `plan-check` contain a `plan-oversized: …` line, add
  `--data '{"warnings": ["<that line verbatim>"]}'`: the chain runner prints it, the chain does not stop.
  The `journal` of the last `plan-check` result must be this `<journal>`; `null` or another path
  means the plan's `**Spec:**` line does not lead to the spec: fix the link and re-run
  `plan-check`.
- **Questions.** A decision this skill would ask about (an old spec without settings, unless the brief carries the answers — see 1. Spec Preflight; the scope
  check; a deviation; never the size budget, see 2. Scope Check) without a confirmation channel: `J journal-question <journal> --skill plan-writing --plan <plan> --stage writing --text "<question>" [--option "<option>"]...`
  (the stage becomes `stopped`), then `J journal-export-findings <journal>`, then stop with a short
  report naming the question id. With a confirmation channel ask as usual and record the
  question with its answer: the same command with `--answer "<answer>"`.
- **Errors.** `journal-corrupt` (exit `2`): say it, propose `J journal-reconcile <journal> --rebuild`,
  continue without the journal. `journal-locked` (exit `1`): repeat once; still locked → ask
  whether to continue without the journal, or stop without a confirmation channel.
  `journal-write-failed` (exit `1`, the file system refused the write, e.g. a read-only journal):
  say it in one line with the error text and continue without the journal.

## 1. Spec Preflight

Run `python "<SKILL_DIR>/../plan-brainstorming/scripts/brainstorm_tool.py" spec-check <spec>`.

- Exit `0`: continue. Show `warnings`, they do not block.
- Exit `1`: STOP. Show the `errors` and ask the user to re-run `plan-brainstorming` on the failing part. Never invoke it yourself: backward moves in the pipeline are the user's call.
- Exit `2`: STOP. The spec cannot be read.

Tier: the `tier` field of the result. `Quick` / `Standard` / `Deep` are used as-is. Missing or unknown: use **Standard** and announce "Spec has no Tier line; defaulting to Standard."

**Settings.** `spec-check` also returns the chain settings: `chain`, `environments`, `backlog` (the spec's `> Chain:`, `> Environment:`, `> Backlog:` lines). They stay in the spec: do not copy them into the plan; `**Spec:**` is how every later skill finds them. An old spec has none of these lines (`chain` and `backlog` empty, `environments` empty). It cannot be rewritten (one owner per artifact), so ask as now: when steps touch external systems, which environments and with which rights, changes named first and separately from reads; in the same message propose the chain defaults from `spec-contract.md` and the backlog section (default: the plan name without `-impl`) for the user to confirm or edit. When the brief of a `plan-chain-runner` agent already carries these answers (the runner asked them in its start card: each environment with its rights, the user's question and answer quoted verbatim and the date, the chain settings, the backlog section), do not ask again and record no question: take them as they are. Write the answers into the plan header: `**Chain:**` with all four keys, `**Environments:**` with `read=`/`write=`, `**Backlog:**`. Settings in the plan header replace the spec's settings as a whole, so never add them to a plan whose spec has settings: if such a spec lacks an environment the steps need, stop and send the user back to `plan-brainstorming`.

## 2. Scope Check

If the spec covers several independent subsystems, STOP and propose one plan per subsystem. Continue only after the user chooses. Each plan must produce working, testable software on its own.

**Size budget.** Take `volume.estimate_tasks` and `volume.budget_tasks` (40 tasks; a plan's budget is also 150000 bytes) from the `spec-check` result of 1. Spec Preflight. After 3. File Structure, count the tasks you are about to write. When the estimate or your count is over the budget:

- with a confirmation channel, ask once: continue with one plan, or return to `plan-brainstorming` to split the goal into several specs (`<root>-N-spec.md`). Record it with `journal-question … --answer "<answer>"`. On "return": write no plan, run `J journal-event <journal> --skill plan-writing --plan <plan> --stage writing --status failed --data '{"why": "decomposition"}'` and stop with a one-line report; the backward move is the user's, never invoke `plan-brainstorming`;
- without one (a silent run), write the plan and go on: no question, no stop. `plan-check` reports `plan-oversized` and the End event carries it (Chain journal).

A `spec-check` result without `volume` (an older `plan-brainstorming`): only your count after 3. File Structure applies.

## 3. File Structure

Before defining tasks, list the files to create or modify and each file's single responsibility. Follow existing patterns. Split a file you touch only when it has grown unwieldy. Files that change together live together.

**Read before you modify.** For every `Modify:` target, open the file first and record one line in the task's `Files` block: *current state / what changes / what must be preserved*. This makes `path:123-145` line ranges real instead of guessed. Line numbers describe the repository as it is when the plan is written; earlier tasks shift them, so every step also quotes the code it replaces, and the quote wins when the numbers disagree.

**Ground every claim in the code.** A plan that names files, functions or commands that do not exist is fiction:

- Every existing symbol a step calls or extends is cited once as `path:line` where it is defined (in the `Files` line or the step text). Symbols the plan introduces are defined in a task before they are used.
- `Create:` targets must not exist yet; a file that exists is `Modify:`.
- The test command in a step must exist in the project (runner, script, config). Run the project's test suite once before writing tasks and record the command and result in the plan header (`**Baseline:** pytest -q → 128 passed`); a red baseline is reported to the user before planning continues.
- `plan-check --root` reports `Create:` targets that exist, `Test:`/`Modify:` targets and referenced paths that do not, and line ranges beyond the file; every warning is resolved or explained in the plan.

**External systems.** Investigation means reading the repository and running local commands without side effects (build, offline tests, grep). Anything that reaches an external system — a database, an API, a remote service, a cloud account — even a constant query, runs only after the user explicitly allows it and names the environment. A permission covers the named environment only: never extend it to another one, and never treat an existing project script that targets another environment as permission. Production needs a separate confirmation for every action. Pre-approved reads (`read=run` in the spec's `> Environment:` line, production included) cover the plan's steps and the read-only checks of plan-iterative-revision and plan-resolver; changes on production are never pre-approved. This applies to writing the plan (the baseline run uses offline tests only) and to the plan's own steps:

- Permissions are settings. They live in the spec (`> Environment:` lines with `read=` and `write=`, written by `plan-brainstorming`) and are not copied into the plan: every skill finds them through `**Spec:**`. Only for an old spec without settings does the plan header carry them (see 1. Spec Preflight): `**Environments:**`, one per line, `` - `name` (test|prod; read=run|task|deny, write=run|task|deny) — "the user's question and answer, quoted verbatim" (date) ``. An environment without a quote is not permitted; prod never gets `write=run`.
- A task whose steps run anything on an environment carries `` **External:** `name` (read|write) — what it does there `` after its `Files` block: `(read)` when the steps only read there, `(write)` when anything there changes. `plan-executor` runs it without a question when the settings say `run` for that access and asks otherwise.
- A project script that targets another environment is redirected to a permitted one in the step's command (or the user is asked); it is never run as it is.
- `plan-check` reads the settings by the shared rule (plan header if it has settings, else the spec at `**Spec:**`) and rejects: an environment without a quote, an `External` line that names an environment missing from the settings, a task that mentions a known environment without an `External` line, an `External` line without `(read)`/`(write)` when the environment has rights (an old header entry without rights: warning), `(write)` on `write=deny` or `(read)` on `read=deny`, and `External` lines when the settings cannot be read (spec missing, no settings in the plan header).

**Deviations from the spec.** The plan follows the spec. A deviation is allowed only by the user's explicit decision and is recorded in the header under `**Deviations from spec:**` (what the spec says → what the plan does → whose decision, when). A deviation that changes the spec's Goal, Components or Out of Scope is not a deviation: stop and send the user back to `plan-brainstorming`.

## 4. Tasks

**Size.** A task fits **10 minutes of work OR 100 lines of new code**, whichever comes first. Otherwise split it into `Task N.1`, `Task N.2`, … recursively. When a task cannot be split without breaking it (a migration and the test that checks the schema after it, a generated data table), keep it whole and add `**Size:** <N> lines — <why it cannot be split>` after its `Files` block; the reason is in the plan's language. `plan-check` warns about a task with more than 100 lines of code and no `**Size:**` line, fails above 150, and lists justified tasks as `oversized`. Size is never a question to the user, in an interactive or a silent run: split the task or justify it. Warning signs: more than ~5 implementation steps, new logic in more than 2-3 files, "and then" chains in the title. A **step** is one action of 2-5 minutes: write the failing test, run it, implement, run again.

**CLAUDE.md.** `CLAUDE.md` changes only on a structural event (its "Stability of this file" rule). A task whose `Files` block creates or modifies `CLAUDE.md` carries `**Structural event:** <key> — <reason>` after that block, next to `**External:**` and `**Size:**`: `<key>` is `skill` (a skill added or removed), `script` (a script added, renamed or moved), `contract` (a cross-skill contract changed), `convention` (a convention changed) or `artifact` (a new artifact that must never be committed); the reason is in the plan's language, the token stays English. `plan-check` fails on another key and warns `claude-md-edit` when the line is missing; the splitter copies it into the part. A new command, flag, field or error code is not such an event: it goes to the skill's `USAGE.md` and `docs/HELPER-CLIS.md`, not to `CLAUDE.md`.

**Tier** (from Preflight) decides how much each task expands. See `references/task-tiers.md` for the table and for when to add `Constraints` and `If stuck`. Every tier keeps the core: `Files`, numbered steps, and a verifiable done-state.

**No commit steps.** A plan never commits: `plan-executor` keeps rollback snapshots in hidden refs while it executes, and only its separate `commit` stage (`/plan-executor <plan> commit`, after the audit) commits the run's files and the audit's fixes.

**Writing order.** The plan file is written task by task, so a writer that is cut off (a host limit, an exhausted context) loses at most the task in hand. After 3. File Structure write the plan header (Plan header below) and then, after one blank line, `writing_marker` of `plan-path` verbatim as the file's last line: `> Writing: in progress (spec sha256 <12 hex>)`. A task goes into the file only when it is finished: whole, in one edit, inserted before the marker; the marker stays the last line. After the last task delete the marker line, then 6. Check and Self-Review and the End event. While the marker is in the file the plan is not a plan: `plan-check` fails with `plan-incomplete` as its first error, `journal-reconcile` does not take the file as the end of `writing`, and the splitter, the executor and the revision refuse it with `plan-incomplete`. Never delete the marker before the last task is written, and never write a task after it.

### Plan header

```markdown
# [Feature Name] Implementation Plan

> **For agentic workers:** Execute this plan with the `plan-executor` skill (one unit at a time, ledger-backed, gated). If the plan has not been audited yet, run `plan-iterative-revision` on it first. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** [spec path relative to the plan]

**Tier:** [Quick|Standard|Deep]

**Goal:** [one sentence]

**Architecture:** [2-3 sentences]

**Tech Stack:** [key technologies]

**Baseline:** [test command → result before this plan]

<!-- Settings below: only for an old spec without settings (see 1. Spec Preflight); all four Chain keys, defaults for the ones the user did not choose -->
**Chain:** split=[auto|always|never]; revision=[quick|standard|deep]; stop=[pragmatic|strict]; resolver=[audit|auto|skip]

**Backlog:** [goal section in BACKLOG.md]

**Environments:** (only when steps touch external systems)
- `[name]` ([test|prod]; read=[run|task|deny], write=[run|task|deny]) — "[the user's question and answer, verbatim]" ([date])

**Deviations from spec:** (only when the user decided to deviate)
- [spec says] → [plan does] — [who decided, when]

---
```

### Task (Standard / Deep)

````markdown
### Task N: [Component Name]

**Files:**
- Create: `exact/path/to/file.py`
- Modify: `exact/path/to/existing.py:123-145` (current state / change / preserve)
- Test: `tests/exact/path/to/test_file.py`

**Preconditions:**
- [concrete artifact or passing test this task needs]

**Postconditions:**
- [observable artifact or check this task produces]
- [what is deliberately NOT changed, when scope creep is likely]

- [ ] **Step 1: Write the failing test**

```python
def test_specific_behavior():
    assert function(input) == expected
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/path/test_file.py::test_specific_behavior -v`
Expected: FAIL with "function not defined"

- [ ] **Step 3: Implement**

```python
def function(input):
    return expected
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/path/test_file.py -v`
Expected: PASS
````

On Quick, `Preconditions` and `Postconditions` collapse into one line: `**Done when:** <observable result>`.

A postcondition must be reachable by this task's own steps. If it needs work from another task, split or reorder. Dependencies on earlier tasks go in `Preconditions`.

### Checkpoint task (Standard / Deep only, optional)

After a logical group of tasks you may add one smoke test of the group. It is an ordinary task with its own number, so the executor tracks and gates it:

```markdown
### Task N: Checkpoint — [what this group proves]

- [ ] **Step 1: Run the smoke check**

Run: `<concrete command>`
Expected: `<observable result>`

**Done when:** [the expected result is observed]
```

No `Files` block is needed. If you cannot name a concrete command, leave the checkpoint out.

## 5. No Placeholders

Every step contains what the engineer needs. Plan failures:
- "TBD", "TODO", "implement later", "fill in details"
- "Add appropriate error handling" / "handle edge cases" without saying which
- "Write tests for the above" without test code
- "Similar to Task N": repeat the code, tasks may be read out of order
- a code step without a code block
- types, functions or methods not defined in any task

## 6. Check and Self-Review

1. Run `plan-check <plan> --root <project>` until it exits `0`. It enforces the header fields, task headings and unique ids, the task core per tier, backticked file paths, no commit steps, no placeholders, and the `Environments`/`External` rules. Review its `warnings`: a missing `Modify:` target is fine only if an earlier task creates it, and a code-size warning (or the error above 150 lines) is closed by splitting the task or by a `**Size:** <N> lines — <reason>` line, never by asking the user. `plan-oversized: N tasks, M bytes (budget …)` is about the whole plan, not a task: show it to the user, never split tasks to hide it; the plan stays valid and the End event carries it (Chain journal). `plan-incomplete` means the writing marker is still in the file: delete it once the last task is written (4. Tasks, Writing order). `marker-spec-mismatch` comes only with the marker: its fingerprint is not the spec's (Chain journal, Continuation).
2. Then check what the tool cannot:
   - **Spec coverage:** every spec requirement maps to a task. Add a task for each gap.
   - **Grounding:** every `path:line` citation was actually read; `Create:` targets are new; the test command exists.
   - **Consistency:** names, types and signatures match across tasks (`clearLayers()` in Task 3 and `clearFullLayers()` in Task 7 is a bug).
   - **Size:** each task fits the limit. Split it if not; a task that cannot be split carries a `**Size:**` line whose reason names what splitting would break.
3. On the Deep tier, if the host supports subagents, also dispatch a reviewer with `plan-document-reviewer-prompt.md` and fix what it reports.

Fix issues inline and re-run `plan-check`.

## 7. Execution Handoff

Take `task_count` and `plan_bytes` from the last `plan-check` result, and the decisions from its `settings`: with `chain_explicit: true` the values `settings.chain.split` and `settings.chain.resolver` are decisions, including keys the defaults filled in; with `chain_explicit: false` or `settings: null` no decision is recorded: treat `split` as `auto` and do not announce `resolver`. Speak in the plan's language.

> "Plan complete and saved to `<path>` (<task_count> tasks, <plan_bytes> bytes, size: <size_class>). Recommended next steps:
> 1. **Audit (recommended):** run `plan-iterative-revision` to cross-check the plan against the codebase.
> 2. **Split:** `plan-splitter` decides with its gate whether the plan is cut into parts.
> 3. **Execute:** for small, audited plans, run `plan-executor`. The plan has no commit steps; after the audit, `/plan-executor <plan> commit` commits the result.
>
> Which step?"

Settings change this message:

- `size_class` is `large` (`plan-oversized` in the warnings): before the steps, recommend splitting the goal into several specs in `plan-brainstorming` and say that every later stage (revision, execution, audit) costs in proportion to the plan's size: "<task_count> tasks, <plan_bytes> bytes, over the budget of 40 tasks / 150000 bytes: consider returning to `plan-brainstorming` to split the goal; each later stage costs in proportion to the plan's size." The steps follow.
- `split` is `auto` (a decision with `chain_explicit: true`, or treated as `auto` because `chain_explicit` is false or `settings` is `null`): keep the Split option as in the template, the splitter's gate decides; never recommend the split by the task count alone.
- A `plan-check` result without `size_class` (an older `plan_tool.py`): leave `size: <size_class>` out of the message.
- `chain_explicit: true` and `split` is `always` or `never`: do not offer the split as an option; state the decision instead: "Settings: split=always, `plan-splitter` runs after the audit." / "Settings: split=never, the plan runs whole."
- `chain_explicit: true`: state the resolver choice after the steps: "After execution: resolver=<value> (from the settings)." Do not ask about it later. With `chain_explicit: false` or `settings: null` say nothing about the resolver here.

Do not invoke any skill automatically. Wait for the user's choice of the remaining options.
