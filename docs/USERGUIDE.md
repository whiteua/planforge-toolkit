# PlanForge Toolkit — User Guide

> A structured AI planning pipeline from raw idea to verified implementation.

---

## Table of Contents

1. [What is PlanForge Toolkit?](#what-is-planforge-toolkit)
2. [Core Concepts](#core-concepts)
3. [Pipeline Overview](#pipeline-overview)
4. [Skills Reference](#skills-reference)
   - [plan-brainstorming](#plan-brainstorming)
   - [plan-writing](#plan-writing)
   - [plan-splitter](#plan-splitter)
   - [plan-executor](#plan-executor)
   - [plan-iterative-revision](#plan-iterative-revision)
   - [plan-resolver](#plan-resolver)
   - [plan-chain-runner](#plan-chain-runner)
   - [writing-skills](#writing-skills)
5. [Installation](#installation)
6. [Typical Workflows](#typical-workflows)
7. [File Naming Conventions](#file-naming-conventions)
8. [Troubleshooting](#troubleshooting)

---

## What is PlanForge Toolkit?

PlanForge Toolkit is a collection of **AI agent skills** that impose structure on the software development lifecycle. Rather than asking an AI assistant to "just implement this", the toolkit guides both the human and the AI through an explicit pipeline:

```
Idea → Design Spec → Implementation Plan → Staged Execution → Verified Result
```

Each skill is an independent module with a well-defined input, output, and invariants. Skills can be used individually or chained together for larger projects.

---

## Core Concepts

| Term | Meaning |
|---|---|
| **Spec** | Design document — *what* to build and *why*. Produced by `plan-brainstorming`. |
| **Plan** | Implementation document — *how* to build it, step by step. Produced by `plan-writing`. |
| **Part** | Self-contained slice of a large plan (`<base>-a.md`, `<base>-b.md`, …). Produced by `plan-splitter`. |
| **Task** | Plan unit that fits ~10 minutes or ~100 lines of new code; a task that cannot be split carries a `**Size:**` line with the reason. |
| **Step** | Single action inside a task (2–5 minutes). |
| **Ledger** | Progress tracking file (`state.json`) maintained by `plan-executor`, stored outside the repository. |
| **Review** | Audit file produced by `plan-iterative-revision` listing errors in the plan. |
| **Report** | Audit file produced by `plan-resolver` listing implementation vs. plan findings. |
| **Chain settings** | Decisions for the whole chain (`split`, `revision`, `stop`, `resolver`), external environments with read/write rights and the backlog section. Recorded in the spec by `plan-brainstorming`; later skills read them instead of asking. |
| **Backlog** | `BACKLOG.md` at the repository root: what the skills deferred, one section per goal. `plan-brainstorming` checks off the items an approved spec took in; it unchecks only what an amended or withdrawn spec no longer covers, after you confirm; `[-]` (cancelled) is yours alone. |
| **Dialogue language** | The language of your first task statement. Every question, option and summary of every skill uses it. |
| **Chain journal** | `<goal>-chain.json` next to the spec: the stage of each plan (`writing`, `revision`, `split`, `execution`, `diffs`, `audit`, `commit`), questions waiting for your answer, findings. Every skill keeps it, manual runs too. |
| **Follow-ups** | `<goal>-followups.json` next to the journal: defects found outside the plans, in the input format of `plan-brainstorming`. |
| **Diff report** | `<base>-diffs.md` next to the plan: what the run changed, file by file. |
| **Chain runner** | `plan-chain-runner`: takes the approved specs of one goal (from the goal roadmap `<goal>-roadmap.md` or as spec files) through every stage in the order of their dependencies, launches an agent per stage with the model of its role, and stops with questions in the chain journal (`continue`, `discuss`, `status`). |

---

## Pipeline Overview

```
┌──────────────────────┐
│  plan-brainstorming  │  Idea(s) → Specs + Goal Roadmap
└──────────┬───────────┘
           │ *-spec.md, <goal>-roadmap.md
┌──────────▼───────────┐
│     plan-writing     │  Spec → Implementation Plan
└──────────┬───────────┘
           │ *-impl.md
           │
    ┌──────▼──────┐        ┌─────────────────────────┐
    │ large plan? │──yes──►│      plan-splitter       │
    └──────┬──────┘        │  Plan → <base>-roadmap.md│
           │ no            └──────────┬──────────────┘
           │                         │ <base>-a.md, -b.md…
           └─────────────┬───────────┘
                         │
┌────────────────────────▼────────────────────────────┐
│                   plan-executor                     │
│  Execute one unit at a time, ledger-backed          │
└────────────────────────┬────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────┐
│                   plan-resolver                     │
│  Audit implementation against plan → report         │
└─────────────────────────────────────────────────────┘

plan-iterative-revision  — use at any stage to clean up a plan before execution
plan-executor <plan> commit — after plan-resolver: commit the run's files and the audit's fixes
plan-chain-runner <roadmap> — runs the whole chain from the goal roadmap (or approved specs), by their dependencies
```

---

## Skills Reference

### plan-brainstorming

**Purpose:** Turn a vague idea, or several input files with an instruction, into validated design specs and a goal roadmap through structured dialogue; the skill stops there and you start the next step.

**Invoke:**
```
/plan-brainstorming <goal-file-or-inline-description>
/plan-brainstorming <file>… <free text>   # several inputs; the text says how to use them
/plan-brainstorming <findings.json>   # JSON list of code-review findings
/plan-brainstorming BACKLOG.md        # unchecked items of the shared backlog become the task
/plan-brainstorming <spec.md>         # amend mode: change an approved spec in place
/plan-brainstorming help              # this skill's USAGE.md
```

With a findings JSON (`file`, `line`, `summary`, `failure_scenario` per item), the skill validates the list, checks each finding against the code, and writes a fix spec. The spec traces every finding id to a fix or to Out of Scope.

**Process:**
1. Explores project context (files, docs, commits) and restates your request in one sentence
2. Proposes a depth tier: `Quick` / `Standard` / `Deep`
3. Offers the Visual Companion when the questions ahead are visual
4. Asks clarifying questions one at a time
5. Proposes approaches with trade-offs (2–3 on Standard/Deep, one on Quick)
6. Presents the design section by section, asks for approval
7. Runs the ambiguity sweep — closes all open questions (re-presents a design section if an answer changes it)
8. Writes the spec file, checks the contract with `brainstorm_tool.py spec-check`, runs the self-review including a fidelity check against your original request
9. After you approve the spec: the next spec of the goal (when you chose several), then the check of two or more specs together (`spec-set-check` and a reviewer subagent), then `<goal>-roadmap.md` and one closing report with the command to run next (the specs are not committed; no later skill is started)

Every message you see (questions, answer options, summaries) and the spec body follow the language of your input (goal file, findings JSON or message; `brainstorm_tool.py detect-lang`); section headings and format tokens stay in English. The same rule holds in every skill of the pipeline.

**Chain settings.** Before writing the spec, the skill proposes in one message the settings the rest of the chain will use, and you confirm or edit them. They are written above `# Goal`, next to `> Tier:`:

- `> Chain: split=auto; revision=deep; stop=pragmatic; resolver=audit` — `split` is `auto|always|never`, `revision` is `quick|standard|deep` (default: the tier), `stop` is `pragmatic|strict`, `resolver` is `audit|auto|skip`.
- `` > Environment: `app_test` (test) — read=run, write=task — "question — your answer" (date) `` — one line per external system. Changes are asked first and separately from reading: `run` allows the access for the whole run, `task` asks before each task, `deny` forbids it. Production changes are only `task` or `deny`.
- `> Backlog: <section>` — the section of `BACKLOG.md` for this goal.

`spec-check` rejects unknown keys, an environment line without `read=` or `write=`, `write=run` on prod, and interface labels such as "(Recommended)" in the quote.

**Volume estimate.** The Chain Settings message also shows how large the plan is likely to be: "Volume estimate: ~N tasks — M components × k, tier T; budget 40" (k is 1 on Quick, 2 on Standard, 3 on Deep, plus one task per Testing Strategy item; `spec-check` returns the same numbers as `volume`). Above 40 tasks the skill proposes splitting the goal into several specs (`<root>-1-spec.md`, `<root>-2-spec.md`, …) and waits for your choice. The estimate is never written into the spec.

**Backlog.** After you approve the spec, its Out of Scope items (and, when one task is split into several specs, the spec map) are appended to `BACKLOG.md` at the repository root, in the section of this goal. In backlog mode the items the spec took in are listed in the "Spec written" message and checked off `[x]` after your approval (`backlog-mark`); `[x]` means "taken into an approved spec", not "done". Before the first question, backlog mode matches the unchecked items with the approved specs of their section (`backlog-sweep`) and, after you confirm, checks off the ones a spec already covers. Items marked `[-]` are cancelled by you; the skills never set or clear that mark and never append such an item again. Several specs of one goal are numbered `<root>-1-spec.md`, `<root>-2-spec.md` unless you ask for descriptive names.

**Several inputs.** `/plan-brainstorming goal.md research.md review.json <text>` takes every existing file as an input and the rest of the line as the instruction. `brainstorm_tool.py inputs` classifies each file (`goal`, `markdown`, `findings`, `backlog`, `spec`, `plan`, `goal-roadmap`, `json`, `text`, `binary`, `missing`) and returns the mode of the call; the agent restates which file plays which role, and you correct it. Without an instruction the goal file and other notes are the problem statement and background, findings go to the spec that takes them, a spec or a plan is read only.

**Several specs, the set check and the goal roadmap.** After the first step the skill proposes one spec or several (by size, your instruction and independent subsystems); you choose the set and the order, and the specs are written one after the other. With two or more specs of a goal, `spec-set-check` lists the files and symbols they share, the pairs that do not mention each other and the numbered sections several specs edit, and a reviewer subagent checks the set for duplicated work, contradicting decisions and order conflicts; accepted fixes go into the specs with your approval, rejected ones into the roadmap's notes. Then `roadmap-write` writes `<goal>-roadmap.md` next to the specs — also for one spec: the execution order `#`, dependencies, parallel groups, tier and size estimate per spec, shared touchpoints with their delivery order, a Mermaid graph, notes and the inputs — and `roadmap-check` validates it. The closing report names the command you run next (`/plan-chain-runner <goal>-roadmap.md`, or `/plan-writing <spec>`); the skill never starts it.

**Output:** `*-spec.md` in the same directory as the goal file. After you approve it, the skill creates the chain journal `<goal>-chain.json` next to it (`<goal>` is the `Backlog` setting, else the spec name without `-spec.md`); the dialogue questions are not recorded there.

**Amend mode.** Given an approved spec (`*-spec.md` with `# Goal`), the skill discusses only the change, edits the file in place, re-runs `spec-check` and the self-review, asks for your approval, appends the new Out of Scope items to `BACKLOG.md` and checks off `[x]` the `BACKLOG.md` items the change took in and, after you confirm, unchecks (`backlog-unmark`) the ones it removed from the spec. Withdrawing a spec goes through the same mode: its items are unchecked after you confirm, and you remove or rename the spec file. It writes no new plan: the chain journal sees the changed spec, and the next `/plan-chain-runner continue` or `/plan-writing <spec>` asks whether to rewrite the plan (`drift`).

**Depth tiers:**

| Tier | When | Spec size |
|---|---|---|
| Quick | Single-file change, bugfix, config tweak | A few sentences per section |
| Standard | Feature touching 2–5 components | Short paragraph per section |
| Deep | New subsystem, external integrations, complex failure modes | Full paragraphs, tables |

> **Dependency:** `plan-writing` reads contract files from this skill, and `plan-executor`, `plan-iterative-revision`, `plan-splitter` and `plan-resolver` read the chain settings through its `brainstorm_tool.py`; `plan-executor` and `plan-resolver` also write `BACKLOG.md` through it, and every skill keeps the chain journal through it. Install them in the same parent directory.

---

### plan-writing

**Purpose:** Convert a validated design spec into a detailed, step-by-step implementation plan.

**Invoke:**
```
/plan-writing <spec-path>
```

**Prerequisites:** The spec must pass `plan-brainstorming`'s `brainstorm_tool.py spec-check` before the skill proceeds: all 8 required headings in order, no empty section, `## Open Questions` empty (or `(none)`).

**Output:** `<X>-impl.md` next to `<X>-spec.md`. The header carries `**Spec:**`, `**Tier:**` and `**Baseline:**` (the test command and result before planning); tasks use `### Task N: <title>` headings, the format `plan-executor` and `plan-resolver` parse. `scripts/plan_tool.py plan-check --root <project>` verifies that contract and that the files and paths the plan relies on exist (`Create:` targets must be new).

`scripts/plan_tool.py skeleton <plan>` prints the plan without code bodies (the header, task headings, `Files`, conditions, step headings, `Run:`/`Expected:`, one `[code <lang>, <N> lines: <signatures>]` line per code block) and `scripts/plan_tool.py task <plan> <id>` one task byte for byte. plan-resolver reads them on its first and closing full passes; both print text, not JSON.

**Writing order.** The skill writes the plan file task by task: the header, then the marker `> Writing: in progress (spec sha256 <12 hex>)` as the last line, each finished task before it, and the marker removed after the last task. A writer cut off by the host is started again (by you or by `plan-chain-runner`, whose `run-next` returns the stage with `resume: true`) and continues after the last written task; if the spec changed in between, the plan is written anew. While the marker is there, `plan-check`, the splitter, the executor and the revision refuse the plan with `plan-incomplete`.

Each task in the plan specifies:
- Files to touch
- Exact steps (2–5 min each)
- How to test / verify done-state

Plans contain no `git commit` steps; after the audit, `/plan-executor <plan> commit` commits the result. An optional `### Task N: Checkpoint — …` task smoke-tests a group of tasks (Standard/Deep).

Settings are not copied into the plan: `plan-check` reads them from the spec named by `**Spec:**`. For an older spec without settings, the skill asks as before and records the answers in the plan header (`**Chain:**`, `**Environments:**` with `read=`/`write=` rights, `**Backlog:**`). Tasks on external systems carry `` **External:** `name` (read|write) — what ``, and `plan-check` rejects an access the environment denies.

**Task size.** A task over 100 lines of code is split; if it cannot be split, it carries `**Size:** <N> lines — <reason>`. Without that line `plan-check` warns above 100 lines and fails above 150. The plan's budget is 40 tasks or 150000 bytes: `plan-check` returns `size_class` (`small` up to 15 tasks, `large` over the budget, else `medium`) and warns `plan-oversized` above it without failing the plan. The hand-off names the task count, the plan size and the class; with `split=auto` the splitter's gate decides on the split, and a `large` plan gets the advice to split the goal in `plan-brainstorming`, since every later stage costs in proportion to the plan's size. Before writing, a spec whose estimate is over the budget makes the skill ask once whether to continue with one plan (a run without you continues, and the chain runner prints the warning as one line).

**CLAUDE.md.** A task that creates or modifies `CLAUDE.md` names the structural event it serves: `**Structural event:** <skill|script|contract|convention|artifact> — <reason>`. Without it `plan-check` warns `claude-md-edit`; another key is an error. `spec-check` warns `claude-md-in-components` when a spec's Components name `CLAUDE.md`. The executor makes such an edit without asking.

---

### plan-splitter

**Purpose:** Decompose a large implementation plan into self-contained parts, each executable in a single agent pass.

**Invoke:**
```
/plan-splitter <plan-path> [verify=ask|all|none|a,c] [verify_depth=quick|standard|deep] [verify_mode=full-cycle|audit-only]
```

With `verify`, the skill runs `plan-iterative-revision` once over the roadmap (every selected part in turn, one review trail each) and accepts the result only through the machine gate `verify-status`. Requires `plan-iterative-revision` installed next to it.

**Gate decision:** `splitter_tool.py gate` decides by numbers (tasks, bytes, modules, dependency shape) and may decide the plan does NOT need splitting. This is a valid outcome — you'll get a `gate-pass` notice and can proceed directly to `plan-executor`. When the plan is split, the model only chooses the part boundaries from the task list; `split-write` writes the roadmap and the parts and copies every task's text byte for byte, and `validate-all` checks the copy.

In a chain, the `split` setting decides: `always` skips the gate, `never` means no split (except after your answer `split` to the runner's `plan-oversized:` question: a `split=never` plan over 40 tasks or 150 000 bytes stops the chain on it). `**External:**`, `**Size:**` and `**Structural event:**` lines of tasks are copied into the parts verbatim.

**Output** (alongside the original plan, which is never modified):

| File | Purpose |
|---|---|
| `<base>-roadmap.md` | Part map with dependencies and parallel groups |
| `<base>-a.md`, `<base>-b.md`, … | Self-contained part files (letters continue with `aa`, `ab`, …) |

---

### plan-executor

**Purpose:** Execute a ready plan or staged roadmap one unit at a time with ledger-backed progress tracking, gates, and rollback snapshots.

**Invoke:**
```
/plan-executor <plan-or-roadmap-path>
/plan-executor <plan-path> commit      # after the audit: commit the run's files and the audit's fixes
```

**Input types:**

| Input | Detection | Behavior |
|---|---|---|
| Staged roadmap (`-roadmap.md`) | Has part table + dependencies | Executes the tasks of each part in dependency order, one task per unit, and closes each part with a checkpoint unit |
| Whole plan (with `### Task N:` headings) | Task headings outside code blocks | Executes tasks strictly in order; a failed task is retried before anything else |

**Phases:**
1. **BOOTSTRAP** — `ledger-init <exec_dir> <plan> --workdir <repo>`: parse units, create or resume the ledger in `exec_dir` (outside the repository or git-ignored; stops on a dirty repo (the pipeline's own files, the run's journal and `BACKLOG.md` do not count), on a changed plan/part (`plan-drift`) or on changed chain settings (`settings-drift`, continue with `--accept-drift`)), store the chain settings and the expected file tree, baseline snapshot
2. **LOOP** — `unit-begin` (checks for files changed since the last unit, returns the unit text, files and external accesses) → execute → gate → `unit-finish` (snapshot + done, or retry/stop)
3. **FINALIZE** — `run-diff --markdown` writes `<base>-diffs.md` next to the plan (without git the `diffs` stage is `skipped`); findings outside the plan go to the chain journal and `BACKLOG.md` (`journal-finding`) and `<goal>-followups.json` is exported; `plan-resolver` is proposed (audit, or `auto` to audit and fix), or the `resolver=` setting is announced instead of asked

**Invariants:**
- Never edits source plan or part files.
- Progress lives only in `state.json`.
- Only `commit-run` commits on your branch: in a chain after the audit, by hand with `/plan-executor <plan> commit`. Snapshots live in hidden refs `refs/plan-executor/<run>/<unit>`; push, amend and force are never used.
- Destructive operations (restore) require explicit engineer confirmation.
- A gate cannot pass silently when checks are absent.
- A task marked `` **External:** `env` (read|write) `` runs without a question only when that access is `run` in the settings or you allowed it for this run (`consent`); `task` asks "this task only / the whole run / stop", `deny` stops, and a run without a confirmation channel stops with a report. Consents given during a run are cleared when the run resumes.
- Files changed between tasks by someone else are reported (`foreign-changes`) before the next task starts: accept them (`accept-changes`), restore those files (`checkpoint-restore --paths … --exec-dir …`), or stop. A run without a confirmation channel stops with the list.

The ledger lives in `<repo parent>/.exec/<repo>-<plan>/` by default; the agent tells you the path at the start. At the end it writes `<base>-diffs.md` next to the plan (what the run changed, separate from work that was uncommitted before) and records defects it noticed but did not fix in the chain journal and in `BACKLOG.md` (section from the `Backlog` setting, else the goal); `<goal>-followups.json` next to the spec collects them for `plan-brainstorming`. A run that stops without anyone to ask writes its question into the journal; the next run applies your answer and continues from the ledger.

**Delegation (`light`, off by default).** `/plan-executor <plan> light=haiku` (or the runner's `light` setting of the `execution` role) lets the executor hand green tasks — documentation, test-only and Quick-tier tasks without `External`, not checkpoints (`unit-begin` marks them `delegable`) — to a subagent on that model, with the task's text and files only. The subagent changes only those files and ends its reply with a `Written files:` block (paths relative to the repository inside it, absolute outside it, or `none`); the executor saves the reply next to the ledger and checks it with `executor_tool.py delegate-check --reply` against a `git status` snapshot taken before the launch, with the plan folder's ignored files hashed (a missing block, a path outside the repository, a changed file the subagent did not name, a named file it did not change, or a commit fails the attempt; a new ignored file outside the plan folder is only reported), runs the gate itself and records `unit-finish --delegated`. A failed delegated task is retried in the main agent. The ledger (`delegated`, `settings.light`), the journal and `run-stats` (`quality.delegated`) record it, so the quality can be measured before it becomes a default ([docs/COST.md](COST.md), Delegation). Without a tool that starts a subagent with a model, those tasks run in the main agent and the ledger notes `subagent-unavailable`.

**Commit stage.** `/plan-executor <plan> commit` finds the ledger without changing it (`ledger-path`) and the journal, rebuilds `<base>-diffs.md` with the audit's fixes, writes the message (`<type>(<scope>): …`, the spec's goal, the audit status, the fixed files) and calls `commit-run`, which commits only the run's files and the audit's fixes, with your hooks. With audit fixes, a manual run lists them first and waits for your explicit "yes"; "no" leaves everything uncommitted. It stops instead of committing when something is already staged (`index-not-empty`), when a file held your uncommitted work before the run and the run changed it too (`mixed-files`), when a file changed outside the run (`foreign-changes`), or when a task failed and files the commit would take differ from the last finished task (`failed-attempt`: the half-done attempt was not rolled back, or the files changed outside the run; the agent restores only those files, so the audit's fixes stay). A second call after new audit fixes commits only them. Without git the stage is `skipped`.

**Prerequisites:** Python ≥ 3.8 in PATH.

---

### plan-iterative-revision

**Purpose:** Audit an implementation plan against the codebase and fix errors in automated cycles until the plan is clean.

**Invoke:**
```
/plan-iterative-revision <plan-path> [preset=quick|standard|deep] [stop_policy=pragmatic|strict] [interaction=auto|interactive|autonomous] [audit-only]
/plan-iterative-revision <base>-roadmap.md [parts=a,c] …     # batch: every part of a split plan, one review trail each
```

**Presets:**

| Preset | Lenses | Code Rigor | Max Iterations |
|---|---|---|---|
| `quick` | 1 | grep-level | 3 |
| `standard` | 2 | read-level | 5 |
| `deep` | 4 (incl. red-team L4) | explore | 7 |

**Modes:**
- `full-cycle` (default) — audit → fix → repeat
- `audit-only` — audit → write review file → stop

**Stop conditions:**
- No issues on the first audit → `clean`, no files; no issues on a later audit → `converged` + completion file
- Max iterations reached → asks: +3 / +5 / stop (autonomous runs stop with `limit`)
- Same issue set as the previous audit, or nothing resolved for 2 audits → stagnation
- A previously resolved issue comes back, or one issue survives 3 audits → escalation
- Only nits remain (`pragmatic` policy) → stop

Stop decisions use only the reviews of the current run.

**Incremental re-audits.** From the second audit on, the review's table of task hashes tells which tasks Phase B changed: the next audit reads the plan's header plus the changed and new tasks, the tasks of the open contracts and the tasks that depend on them through `Preconditions`, and cross-checks only those against the code. A plan unchanged byte for byte, with unchanged files in its tasks' `Files` blocks (the review's `## Code digest`), skips the audit, while a changed file puts its tasks into the scope; more than half of the tasks touched, or a contract that names no task, makes it full. A clean incremental audit is always followed by one full audit, and only that one ends the run as `converged`. Without `plan-brainstorming` alongside every audit is full.

In a chain, the preset and the stop policy come from the `Chain` setting of the spec and are not asked; a run without a confirmation channel stops at the iteration limit. A read allowed for the whole run (`read=run`) lets the audit check that environment, read-only. A remark about the code rather than the plan goes to the chain journal and `BACKLOG.md` (`journal-finding`), and a stop that needs your decision is recorded there as a question.

**Output:** `<plan-basename>-review-N.md` per iteration; `<plan-basename>-completion.md` on convergence.

**Prerequisites:** Python ≥ 3.8 in PATH. The plan's directory must be writable.

---

### plan-resolver

**Purpose:** Audit how well a plan was implemented in code. Produces a structured report. Optional `fix`/`next`/`auto` modes repair the code from the report and re-audit; the plan is never modified.

**Invoke:**
```
/plan-resolver <plan-path> [previous-report-1] [previous-report-2] ...   # audit
/plan-resolver <plan-path> [previous-report-1] ... full   # audit, always a full pass (closes after an incremental one)
/plan-resolver [plan-path] fix     # fix the latest open report's issues, then re-audit once
/plan-resolver [plan-path] next    # same as fix; use after auto stops
/plan-resolver <plan-path> auto [limit]   # audit → fix → audit until final, max 2 fix cycles by default
```

In audit mode, always provide the full list of previous reports for delta analysis. `fix`/`next`/`auto` discover the reports next to the plan. The fix phase records each outcome (`applied` / `needs-user` / `skipped`) in the report's "Fix Log" section; only the following audit can mark an issue `✅ fixed`. Code changes are left uncommitted: the files the fix phase changed are recorded in the chain journal (`fix_files`), and the closing gate names `/plan-executor <plan> commit` to commit them with the run. The resolver itself never runs a git command that changes anything.

**Incremental re-audit.** Every report ends with an evidence fingerprint: the SHA-256 of each file its anchors and the plan tasks' `Files` name, taken at the start of the audit. The next pass (`rescan-scope`) re-audits only the tasks whose evidence changed, the tasks not yet `✅` and the tasks of open issues; `carry-forward` copies the other lines of the last report by script, so the agent reads only those tasks (by their plan line ranges) and the changed code. A changed plan, an older report without a fingerprint or more than half of the tasks touched give a full pass. An incremental pass never writes `-final`: when it closes everything, a full pass follows (in `auto` by a fresh subagent when the host has them; by hand `/plan-resolver <plan> <reports…> full`).

**Skeleton and compact report.** The first and the closing full pass read the plan's skeleton (`plan_tool.py skeleton` of `plan-writing`) instead of the whole plan and open a task in full (`plan_tool.py task`) only for a `partial`, `ambiguous` or `deviates` verdict or a task without `Files`; the code itself is read in the repository either way. Without `plan-writing` installed alongside, the resolver reads the plan in full and says so. A closed task is one report line with one anchor (a second only on the task's test file); detail lines are written for open tasks only, and `validate-report` warns `verbose-closed-task` and `too-many-anchors` without failing older reports.

**Report types:**

| Type | When |
|---|---|
| `<base>-report-N.md` | Issues found — open report |
| `<base>-report-N-final.md` | All tasks ✅ — closing report |

**Task statuses:**

| Status | Meaning |
|---|---|
| ✅ | Implemented as specified; needs an evidence anchor `path#Lx-Ly` that the validator checks against the code |
| ⚠️ | Partial, defective, or ambiguous |
| ⭕️ | Missing |
| ‼️ | Deviates from the plan |
| `not-applicable` | Explanatory item, nothing to implement |

**Invariants:** The resolver never edits the plan. An audit pass never edits code or previous reports and creates exactly one report (plus appended lines in `BACKLOG.md` for defects outside the plan; `assert-readonly` allows only these two paths), validated with `validate-report --root` (structure, statuses, anchors pointing at real lines) and `task-census` (every plan task covered). The fix phase edits code only; previous reports change only through the Fix Log (`mark-fix`). With `read=run` in the settings, tasks marked `External (read)` are re-checked by the audit itself instead of being closed on the executor's record. Every report carries its evidence fingerprint (`evidence-fingerprint`), and only a full pass may write `-final`.

**Prerequisites:** Python ≥ 3.8 in PATH.

---

### plan-chain-runner

**Purpose:** Run the approved specs of one goal through the whole chain — writing → revision → [split] → execution → audit → commit — after one short start dialogue, then without questions until a decision is needed.

**Invoke:**
```
/plan-chain-runner <goal>-roadmap.md     # new run from the goal roadmap: its order, groups and notes
/plan-chain-runner <spec> [<spec> …]     # new run of these specs: launch card, then the loop
/plan-chain-runner continue [<goal>|<roadmap>]   # resume from the journal (also: продолжить)
/plan-chain-runner discuss [<goal>|<roadmap>]    # answer the open questions one by one (also: обсудить)
/plan-chain-runner status [<goal>|<roadmap>]     # summary only, changes nothing (also: статус)
/plan-chain-runner help                  # pipeline map
```

Without a goal the runner looks for `*-chain.json` journals with unfinished stages in the spec folders of the repository: one is taken, several are asked about.

**Start dialogue.** Every spec must pass `spec-check` and belong to the same goal (otherwise: separate runs). The runner names the host profile in one line, proposes the dependency graph of the specs with a reason for each edge (stages already `done` in the journal are not repeated) and shows one launch card: graph and order, models and effort per role (edits can be saved to `~/.planforge/runner.json`), the chain settings of the specs, and the environments with their rights (a task with `task` rights, a production write included, stops its plan on a question), plus the size and ETA when there is history. A spec without `> Chain:` gets plan-writing's questions here. With a dirty working tree the runner lists the files and offers a start commit (`chore: snapshot before plan-chain-runner run`, no push); the chain's own files are never in it.

**From the goal roadmap.** `/plan-chain-runner <goal>-roadmap.md` checks the roadmap (`roadmap-check`) and takes its specs, `#` order, dependencies, groups, tiers, estimates and notes (`roadmap-parse`); the card shows them instead of proposing edges and says that `#` orders only within `parallel` and the code stages. Specs given by name while the goal has a roadmap run as a subset of it: in its order, with its edges between them; a dependency outside the set that is not committed yet is named in the card (add it or stop). An edit of the graph in the card holds for that run only; amend the roadmap through `plan-brainstorming` to keep it. The journal records the roadmap and its hash (`runner.roadmap`, `runner.roadmap_sha256`); on `continue` a changed roadmap is shown as a `roadmap-changed` card (apply it or keep the old graph), a missing one as `roadmap-missing`. The writing and revision agents get the roadmap's notes for their spec and the handoff of its dependencies; the spec outranks the notes. The execution and audit agents get them too, as context: a note that changes a task is the executor's question, a difference in wording or a contradiction found by the audit is a finding; the commit agent gets the notes only.

**Loop.** `run-next` names the stages to run now; each is launched as an agent of the host profile with the model of its role and a silent brief: run `/<skill> <args>`, there is no confirmation channel, a needed decision is recorded with `journal-question` and the agent stops. After each agent the runner checks the journal and the artifacts, never the agent's word. Progress lines in the spec's language: start and end of each stage with the remaining time, execution progress every 10 tasks or 10 minutes, and a line when an agent is silent for more than 10 minutes.

**Scheduling.** The stages of a plan go in order; independent specs are written in parallel; execution, diffs, audit and commit run for one plan at a time, and while a plan is in them the revision and split of the others wait (`code-busy`); nothing else runs during an audit; a spec that depends on another starts after that spec's commit. A plan stopped on a question waits with the specs that depend on it; the others go on. With `split=auto` the splitter's gate runs before the split stage: a plan it keeps whole skips the stage without an agent. A borderline plan within the budget (40 tasks, 150 KB) is kept whole the same way. The plan that would start its execution next waits while another plan's revision or split still reads the code (`reading-busy`), and no new revision or split starts meanwhile. A host error of an agent call (overload, rate limit, a dropped connection, a time-out) is waited out with growing pauses (1, 2, 5, 10, 10… minutes, an hour at most) and the stage repeated without a question; after an hour it fails with one `stage-failed:` question. A writer relaunched three times without a new task or byte stops on `stage-failed: writing`.

**Stops and questions.** At the end you get one summary (per plan: the plan, reviews, roadmap, ledger, report, `-diffs.md`, commits; plus `<goal>-followups.json`, the BACKLOG lines and the checklist after the run, which `run-checklist` appends to the goal's section) and all open questions at once, with one push notification where the host has one (Claude Code: `PushNotification`). The agents' notes worth knowing are recorded as findings in the journal and `BACKLOG.md`. `discuss` takes them one by one with options and a recommendation and records your answers; an answer that changes a spec's Goal, Components or Out of Scope is handed to `/plan-brainstorming <spec>` (amend mode). `continue` resumes: the owner of each stage applies the answers.

**Profiles and models.**

| Profile | Agents | Model | Effort |
|---|---|---|---|
| `claude-code` (Claude Code) | `Agent` tool, in parallel | per role | inherited, or set by `~/.claude/agents/planforge-<role>.md` if you agree to create them |
| `github-copilot` (GitHub Copilot CLI) | `task` tool, in parallel | per role | inherited from the session |
| `fallback` | none: one stage at a time in the same session | — | — |

Roles: `writing`, `revision`, `split`, `execution`, `audit`, `commit`. An alias (`sonnet`, `opus`, `haiku`, `fable`) does not pin the version; a full model id (`claude-sonnet-5-5`) does, and such a role runs through its agent definition `~/.claude/agents/planforge-<role>.md`. The built-in defaults are in `skills/plan-chain-runner/references/PROFILES.md`; your own table lives in `~/.planforge/runner.json`. `split` runs on `sonnet` with low effort by default (it reads only the task list). `execution` may also name `light`, the model of the green tasks the executor delegates (none by default; a host that refuses it turns delegation off for the run without a question).

**Output:** the chain's usual artifacts plus the `runner` section of `<goal>-chain.json` (profile, specs, graph, models, start commit, sessions, and with a goal roadmap `roadmap` and `roadmap_sha256`). Apart from the optional start commit and the chain journal (`runner` section, skipped events, questions, answers), the runner writes nothing in the repository.

**Cost:** `chain_tool.py run-stats <journal>` (or `--plan <plan.md>` without a journal) reports per plan and stage the files written, their size and code share, the minutes, the model, the host's token count when the runner recorded it or an estimate of input, output and effective tokens derived from what the stage read and wrote, plus quality (audit status and issues, reviews, unit retries); `--baseline <json>` compares with an earlier result per task and per KB of plan. With a journal every plan of the journal is a row; `totals` is the run's and `journal_totals` the journal's. The summary's "Volume" line is the run's number. Model, baseline and checkpoints: [docs/COST.md](COST.md).

**Prerequisites:** all six pipeline skills installed side by side (the runner loads `plan-brainstorming`'s `brainstorm_tool.py` by path and launches the others by name); Python ≥ 3.8 in PATH.

---

### writing-skills

**Purpose:** Create, test, and deploy new AI agent skills using a TDD methodology.

**Invoke:**
```
/writing-skills
```

**Philosophy:** Writing a skill IS Test-Driven Development applied to process documentation.

| TDD Concept | Skill Creation |
|---|---|
| Test case | Pressure scenario with a subagent |
| Production code | Skill document (`SKILL.md`) |
| RED | Agent violates rule without the skill (baseline) |
| GREEN | Agent complies with the skill present |
| Refactor | Close loopholes while maintaining compliance |

**Skill structure:**

```
my-skill/
  SKILL.md          ← main skill document (YAML frontmatter + instructions)
  USAGE.md          ← quick reference (optional but recommended)
  references/       ← supporting reference files
  scripts/          ← helper scripts (Python, JS, etc.)
  tests/            ← TDD test scenarios
  assets/           ← templates, schemas, examples
```

**Frontmatter format:**
```yaml
---
name: my-skill
description: "Single sentence describing when to invoke this skill."
---
```

---

## Installation

### Via `npx skills`

No installation of the CLI itself is required — `npx` runs it on demand.

#### Flags reference

| Flag | Short | Description |
|---|---|---|
| `--global` | `-g` | Install to home directory (`~/`) — available in **all** projects on the machine |
| `--agent <name...>` | `-a` | Target one or more specific agents; CLI auto-detects if omitted |
| `--skill <name...>` | `-s` | Install only specific skills by name; use `'*'` for all |
| `--list` | `-l` | List available skills without installing anything |
| `--copy` | | Copy files instead of creating symlinks |
| `--yes` | `-y` | Skip all confirmation prompts (CI/CD friendly) |
| `--all` | | Shorthand for `--skill '*' --agent '*' -y` |

#### Installation scope

By default skills are installed **project-locally** — into a hidden agent directory at the root of your current working directory (e.g. `.claude/skills/`). These files can be committed and shared with your team.

Add `-g` / `--global` to install into your home directory instead, making the skills available in **every project** on the machine.

| Scope | Flag | Where files land |
|---|---|---|
| Project (default) | _(none)_ | `.claude/skills/…`, `.agents/skills/…`, etc. |
| Global | `-g` | `~/.claude/skills/…`, `~/.copilot/skills/…`, etc. |

#### Supported agents (`--agent`)

The CLI auto-detects which agents are installed on your machine. Use `--agent` to explicitly target one or more.

| Agent | Slug | Project path | Global path |
|---|---|---|---|
| Claude Code | `claude-code` | `.claude/skills/` | `~/.claude/skills/` |
| GitHub Copilot | `github-copilot` | `.agents/skills/` | `~/.copilot/skills/` |
| Codex | `codex` | `.agents/skills/` | `~/.codex/skills/` |
| Cursor | `cursor` | `.agents/skills/` | `~/.cursor/skills/` |
| Windsurf | `windsurf` | `.windsurf/skills/` | `~/.codeium/windsurf/skills/` |
| Gemini CLI | `gemini-cli` | `.agents/skills/` | `~/.gemini/skills/` |
| OpenCode | `opencode` | `.agents/skills/` | `~/.config/opencode/skills/` |
| Cline / Warp / Zed | `cline` / `warp` / `zed` | `.agents/skills/` | `~/.agents/skills/` |
| Amp / Replit | `amp` / `replit` | `.agents/skills/` | `~/.config/agents/skills/` |

> 70+ supported agents — full list: [skills.sh/docs/cli#supported-agents](https://www.skills.sh/docs/cli#supported-agents)

#### Recipes

```bash
# Install all 8 skills — CLI auto-detects your agent
npx skills add whiteua/planforge-toolkit

# Install all skills globally (available in every project on this machine)
npx skills add whiteua/planforge-toolkit -g

# Install all skills globally for Claude Code only
npx skills add whiteua/planforge-toolkit -g -a claude-code

# Install all skills project-locally for GitHub Copilot
npx skills add whiteua/planforge-toolkit -a github-copilot

# Install a single skill globally for Claude Code
npx skills add whiteua/planforge-toolkit -s plan-executor -g -a claude-code

# Install the core pipeline only — non-interactive (CI/CD)
npx skills add whiteua/planforge-toolkit \
  -s plan-brainstorming -s plan-writing -s plan-executor -s plan-resolver \
  -g -a claude-code -y

# Install to multiple agents at once
npx skills add whiteua/planforge-toolkit -g -a claude-code -a github-copilot -a cursor

# Install to all detected agents without any prompts
npx skills add whiteua/planforge-toolkit --all

# Preview what would be installed (dry run)
npx skills add whiteua/planforge-toolkit --list
```

### Via git clone

Use this option when you want a single source of truth on disk and prefer to
manage updates via `git pull`.

```bash
git clone https://github.com/whiteua/planforge-toolkit.git
cd planforge-toolkit
```

**Claude Code** — symlink into `~/.claude/skills/`:

```bash
# macOS / Linux
DEST="$HOME/.claude/skills"
for skill in plan-brainstorming plan-writing plan-splitter plan-executor plan-resolver plan-iterative-revision plan-chain-runner writing-skills; do
  ln -s "$PWD/skills/$skill" "$DEST/$skill"
done

# Windows PowerShell (run as Administrator)
$src = "$PWD\skills"
$dest = "$env:USERPROFILE\.claude\skills"
foreach ($skill in @("plan-brainstorming","plan-writing","plan-splitter","plan-executor","plan-resolver","plan-iterative-revision","plan-chain-runner","writing-skills")) {
  New-Item -ItemType SymbolicLink -Path "$dest\$skill" -Target "$src\$skill"
}
```

**GitHub Copilot** — symlink into `~/.copilot/skills/`:

```bash
# macOS / Linux
DEST="$HOME/.copilot/skills"
mkdir -p "$DEST"
for skill in plan-brainstorming plan-writing plan-splitter plan-executor plan-resolver plan-iterative-revision plan-chain-runner writing-skills; do
  ln -s "$PWD/skills/$skill" "$DEST/$skill"
done

# Windows PowerShell (run as Administrator)
$src = "$PWD\skills"
$dest = "$env:USERPROFILE\.copilot\skills"
New-Item -ItemType Directory -Force -Path $dest
foreach ($skill in @("plan-brainstorming","plan-writing","plan-splitter","plan-executor","plan-resolver","plan-iterative-revision","plan-chain-runner","writing-skills")) {
  New-Item -ItemType SymbolicLink -Path "$dest\$skill" -Target "$src\$skill"
}
```

**Codex / Cursor / Cline / Warp** — symlink into agent-specific directory:

```bash
# macOS / Linux — adjust DEST for your agent
DEST="$HOME/.codex/skills"   # or ~/.cursor/skills, ~/.agents/skills, etc.
mkdir -p "$DEST"
for skill in plan-brainstorming plan-writing plan-splitter plan-executor plan-resolver plan-iterative-revision plan-chain-runner writing-skills; do
  ln -s "$PWD/skills/$skill" "$DEST/$skill"
done
```

> **Note:** `plan-writing` reads contract files from `plan-brainstorming`, and `plan-executor`, `plan-iterative-revision`, `plan-splitter` and `plan-resolver` read the chain settings through it; `plan-executor` and `plan-resolver` also write `BACKLOG.md` through it. `plan-chain-runner` loads it too and launches the six pipeline skills by name. Install them in the **same parent directory**.

---

## Typical Workflows

### New feature from scratch

```
/plan-brainstorming I want to add WebSocket notifications to the API
  → asks where to save the spec (inline idea, no goal file); e.g. docs/plans/plan01-spec.md
  → after your approval writes docs/plans/plan01-roadmap.md and stops; its report names the next command

/plan-writing docs/plans/plan01-spec.md
  → saves: docs/plans/plan01-impl.md

/plan-iterative-revision docs/plans/plan01-impl.md      # optional audit of the plan against the code

/plan-executor docs/plans/plan01-impl.md

/plan-resolver docs/plans/plan01-impl.md

/plan-executor docs/plans/plan01-impl.md commit          # commit the run's files and the audit's fixes
```

### Large refactor

```
/plan-brainstorming  ...
/plan-writing        ...  → plan01-impl.md
/plan-splitter docs/plans/plan01-impl.md verify=all
  → saves: plan01-impl-roadmap.md, plan01-impl-a.md … plan01-impl-e.md
  → verifies every part with plan-iterative-revision (plan01-impl-a-review-1.md, …)

/plan-executor docs/plans/plan01-impl-roadmap.md
/plan-resolver docs/plans/plan01-impl.md
```

### Auditing an existing plan before execution

```
/plan-iterative-revision docs/plans/plan01-impl.md preset=deep
  → saves: plan01-impl-review-1.md (with issues)
  → fixes the plan
  → saves: plan01-impl-review-2.md
  → no issues left → converged → saves: plan01-impl-completion.md
```

### Verifying every part of a split plan

```
/plan-iterative-revision docs/plans/plan01-impl-roadmap.md
  → plan01-impl-a-review-1.md, plan01-impl-a-completion.md, plan01-impl-b-review-1.md, …
  → one summary: worst part result wins
```

### Whole chain with plan-chain-runner

```
/plan-brainstorming I want to add WebSocket notifications to the API
  → approved specs docs/plans/ws-1-spec.md, docs/plans/ws-2-spec.md, the goal roadmap docs/plans/ws-roadmap.md and the journal ws-chain.json

/plan-chain-runner docs/plans/ws-roadmap.md
  → launch card: the roadmap's order and groups (ws-2 after ws-1), its notes, models per role, settings, environments → you confirm
  → per plan: writing → revision → [split] → execution → diffs → audit → commit, without questions; writing, revision, execution and audit get the roadmap's notes, the commit its notes only
  → one summary and the open questions, if any

/plan-chain-runner discuss       # answer the questions one by one
/plan-chain-runner continue      # resume; a changed roadmap is shown first
```

### Help

`/plan-chain-runner help` prints the pipeline map: the order of the skills, typical scenarios, the runner's commands and where the artifacts are. `/plan-<skill> help` (`plan-brainstorming`, `plan-writing`, `plan-iterative-revision`, `plan-splitter`, `plan-executor`, `plan-resolver`) shows that skill's `USAGE.md` in your language and does nothing else; `help` together with other arguments is an ordinary call.

### Chain journal and resuming

Every skill records its stage of each plan in `<goal>-chain.json` next to the spec. When a skill needs a decision and there is nobody to ask (a subagent or a chained run), it writes the question into the journal, marks its stage `stopped` and stops with a report. Answer with `brainstorm_tool.py journal-answer <journal> Q1 --answer "…"` or run the skill again interactively: on start it reads `journal-show --plan <plan>`, applies the answer, marks it applied and continues where it stopped (the ledger for the executor, the last report for the resolver, a new run for the revision). `journal-show` prints each plan's stages, open questions and the next action; after a crash `journal-reconcile` restores the statuses from the files the skills left, and a corrupt journal is rebuilt with `journal-reconcile --rebuild`. When a spec or plan changes after the stage that read it is done, `journal-reconcile` records a `drift: <stage> …` question; the skill that owns the stage asks it on its next start and, by your answer, runs the stage again (`rewrite`) or keeps its result for the changed file (`keep`).

### External systems

No skill reaches a database, API or remote service without your explicit permission for a named environment, given separately for reading and for changes (`read=` / `write=`: `run`, `task` or `deny`). The permission is not widened to other environments, production changes are never allowed for a whole run, and an existing project script aimed at production is not permission. The spec lists the environments with your words quoted, tasks that use them are marked `**External:**` with `(read)` or `(write)`, and the executor asks before each of them unless that access is allowed for the whole run. The audits flag a step that ran somewhere it was not permitted; a read allowed for the run lets them re-check such tasks themselves.

### Next cycle from the backlog

`BACKLOG.md` at the repository root collects Out of Scope items, the executor's findings and the resolver's defects outside the plan, one section per goal; your own notes go into `My notes` (`Свои заметки`), which the skills never touch. The file is free: you write to it at any moment, and no stage counts your change as a foreign change. `commit-run` adds the plan's deviations from the spec (`amend spec …`), and the runner's `run-checklist` what is left to do by hand after a run. The items an approved spec took in are checked off by `plan-brainstorming` (`backlog-mark`, also after a confirmed backlog sweep), the rest by you; `plan-brainstorming` unchecks only what an amended or withdrawn spec no longer covers (`backlog-unmark`, after you confirm), and `[-]` (cancelled) is yours alone; `/plan-brainstorming BACKLOG.md` starts the next cycle from the unchecked ones.

### Version control

Only `plan-executor` commits on your branch, at its commit stage (`/plan-executor <plan> commit`, or the chain after the audit): the run's files and the audit's fixes, with your hooks, never push, amend or force. Specs, plans, reviews, roadmaps, parts, reports, the journal and `<base>-diffs.md` are written to disk uncommitted, `plan-resolver`'s fixes stay in the working tree until that stage, and `plan-executor` keeps rollback snapshots in hidden refs (`refs/plan-executor/…`). Without git there is no diff report and no commit stage.

---

## File Naming Conventions

| Pattern | Produced by | Description |
|---|---|---|
| `<base>-spec.md` | `plan-brainstorming` | Design spec |
| `<root>-1-spec.md`, `<root>-2-spec.md`, … | `plan-brainstorming` | Several specs of one goal |
| `<goal>-roadmap.md` | `plan-brainstorming` (`roadmap-write`) | Goal roadmap: order of the specs, dependencies, groups, shared touchpoints, Mermaid graph; the argument of `plan-chain-runner`, recorded in the journal as `runner.roadmap` with its hash |
| `BACKLOG.md` (repository root) | `plan-brainstorming`, `plan-executor`, `plan-resolver` | Shared backlog; skills only append |
| `<base>-impl.md` | `plan-writing` | Implementation plan |
| `<base>-roadmap.md` | `plan-splitter` | Part roadmap |
| `<base>-a.md`, `<base>-b.md`, … | `plan-splitter` | Individual part |
| `<base>-review-N.md` | `plan-iterative-revision` | Audit review (per iteration) |
| `<base>-completion.md` | `plan-iterative-revision` | Convergence notice |
| `<base>-report-N.md` | `plan-resolver` | Implementation audit report |
| `<base>-report-N-final.md` | `plan-resolver` | Final closing report |
| `<goal>-chain.json` | every pipeline skill | Chain journal: stages of each plan, questions, findings |
| `<goal>-followups.json` | `plan-executor`, `plan-resolver`, `plan-iterative-revision` (`journal-export-findings`) | Findings outside the plans; input for `plan-brainstorming` |
| `<base>-diffs.md` | `plan-executor` | What the run changed, file by file |
| `~/.planforge/runner.json` | `plan-chain-runner` (`settings-save`, with your consent) | Models and effort per profile and role; outside the repository |
| `~/.planforge/sessions/<sha1>.json` | `plan-chain-runner` | Mark of the active run with its heartbeat; outside the repository |
| `~/.claude/agents/planforge-<role>.md` | `plan-chain-runner` (Claude Code, with your consent) | Agent definitions that set a role's model and effort |

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `plan-writing` fails spec contract check | Spec is incomplete | Re-run `plan-brainstorming` to close open sections |
| `plan-splitter` says "don't split" | Plan is small enough | Proceed directly to `plan-executor` |
| `plan-executor` stops at a gate with no checks | No tests exist for the unit | Add at least a smoke test; the gate never passes silently |
| `plan-iterative-revision` cannot create review file | Plan directory not writable, or no shell/Python for the helper script | Check directory permissions; enable shell commands and Python in your agent |
| `plan-iterative-revision` stops with stagnation/escalated | The same issues survive plan edits, or a fixed issue came back | Resolve the listed issues by hand, then re-run |
| `plan-resolver`: `anchor file not found` / `beyond end of file` | The report cites code that is not there | The audit must cite real lines; fix the report |
| `plan-resolver` `auto` stops with ask-user / stop-stalled | Issues need a decision, or a cycle closed nothing | Answer the questions or fix by hand, then `/plan-resolver next` |
| `plan-writing` cannot find contract files | `plan-brainstorming` not installed in same directory | Install both skills side-by-side |
| `plan-check`: `lines of code (limit 100, error above 150)` | A task is too large and has no justification | Split the task, or add `**Size:** <N> lines — <reason>` |
| `plan-executor` stops with `foreign-changes` | Files changed between tasks outside the run | Accept them, restore the listed files, or stop |
| `plan-executor` stops with `settings-drift` | The spec (or plan header) with the settings changed since the last session | Check the changed keys, then resume with `--accept-drift` |
| `spec-check` / `plan-check` reject `write=run` | Production changes cannot be allowed for a whole run | Use `write=task` or `write=deny` |
| `journal-locked` | Another skill is writing the chain journal, or a crashed run left `<journal>.lock` (taken over after 60 s) | Wait and re-run the skill |
| `journal-corrupt` | `<goal>-chain.json` is not valid JSON | `brainstorm_tool.py journal-reconcile <journal> --rebuild` (the old file is kept as `.corrupt-<time>`) |
| `commit-run`: `mixed-files` | A file held your uncommitted changes before the run, and the run changed it too | Commit or set aside your part yourself, then re-run `/plan-executor <plan> commit` |
| `commit-run`: `index-not-empty` | Something is already staged | Commit or unstage it, then re-run |
| `commit-run`: `baseline-head-unknown` | The ledger was created before the commit stage existed | Commit by hand or start a new run |
| `commit-run`: `run-incomplete` | A task of the run is still `running` (the run was interrupted) | Resume with `/plan-executor <plan>`, then commit |
| `commit-run`: `failed-attempt` | A task failed and the files the commit would take differ from the last finished task (its edits were not rolled back, or the files changed outside the run) | Restore only those files (`checkpoint-restore <repo> <restore_to> --paths <files> --exec-dir <exec_dir>`), then commit; or commit by hand |
| `commit-run`: `snapshots-missing` | The run's snapshots were garbage-collected; or only the expected tree was (the error names `accept-changes`) | Commit by hand; for the expected tree run `accept-changes <exec_dir>`, then commit again |
| `commit-run`: `head-moved` | The current branch does not contain the commit the run started from | Switch back to that branch, or commit by hand |
| No `<base>-diffs.md`, `diffs` and `commit` are `skipped` | The project is not a git repository | Expected: the diff report and the commit need git |
| `plan-chain-runner` asks whether another run is active | A session mark younger than 30 minutes exists (another window, or a run that has just crashed), or an older one while a stage is still `running` (`session-stale-running`) | Stop the other run, or continue here to take over |
| The runner stops with `session-taken-over` | Another window took the run over | Nothing to do: that window goes on |
| `run-init`: `graph-cycle` | The dependency graph in the launch card has a cycle | Fix the graph in the card |
| `run-init`: `roadmap-mismatch` | The roadmap is not in the journal's folder, or its `> Goal:` names another goal | Start from the roadmap of this goal, in its own folder |
| A `roadmap-changed` card on `continue` | The goal roadmap changed after the run started | Apply the change, or keep the old graph and amend the roadmap later |
| `settings-load` fails | `~/.planforge/runner.json` is not valid JSON or names an unknown profile or role | Fix or delete the file; the runner offers the built-in defaults for this run |
| A `model: <role>` question | The host refused the role's model and its fallback (`model-pick`: `no-model`) | `/plan-chain-runner discuss`: `retry <model>` names the model to use, then `continue` |
| `status` shows a plan waiting without a question | A stage was answered `stop` (`stage-failed:`, `not-confirmed:`, `model:`); plans that need the code stages wait as `code-busy` | Run that stage by hand, then `/plan-chain-runner continue` |
| A `not-confirmed:` question | After the agent returned (whatever it reported) or was silent for 60 minutes, and after one retry, the journal and the files still do not confirm its stage | `/plan-chain-runner discuss`: `retry` or `stop` |
