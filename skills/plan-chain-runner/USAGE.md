# plan-chain-runner — Quick Reference

Run the approved specs of one goal through the whole pipeline: plan, revision, split, execution, audit and commit. After a short start dialogue the runner works without questions, reports progress in one line, and stops with questions recorded in the chain journal; you answer them with `discuss` and resume with `continue`.

## Pipeline map

### Order of the skills

1. `plan-brainstorming` — idea, goal file, findings JSON or `BACKLOG.md` → approved spec `<X>-spec.md`, the chain journal `<goal>-chain.json` and the goal roadmap `<goal>-roadmap.md`.
2. `plan-writing` — spec → plan `<X>-impl.md`.
3. `plan-iterative-revision` — audits the plan against the code and fixes it: reviews `<X>-impl-review-N.md`.
4. `plan-splitter` — only for a large plan (`split=auto` lets its gate decide): roadmap `<X>-impl-roadmap.md` and parts `<X>-impl-a.md`, `<X>-impl-b.md`, …
5. `plan-executor` — executes the plan or the roadmap one task at a time with a ledger and rollback snapshots; at the end the diff report `<X>-diffs.md`.
6. `plan-resolver` — audits the code against the plan: report `<X>-impl-report-N.md` (`-final` when closed); `fix`/`auto` repair the code.
7. `plan-executor <plan> commit` — commits the run's files and the audit's fixes, with hooks, without push.

`plan-chain-runner` runs steps 2–7 for you; every skill can also be run by hand. `/<skill> help` shows that skill's quick reference.

### Typical scenarios

- **From idea to commit:** `/plan-brainstorming <goal>` → approve the spec → `/plan-chain-runner <spec>` → confirm the start card → wait for the summary.
- **From roadmap to commit:** `/plan-brainstorming <goal>` → approve the specs → its closing report names `/plan-chain-runner <goal>-roadmap.md` → the card shows the roadmap's order, groups and notes → confirm → wait for the summary. The writing and revision agents get the roadmap's notes for their spec and the handoff of its dependencies; the execution and audit agents get them as context (for the executor a note that changes a task is a question, a difference in wording a finding; for the audit a contradiction is a finding), the commit agent the notes only.
- **Several specs of one goal:** `/plan-chain-runner <spec-1> <spec-2>`; with `<goal>-roadmap.md` next to the journal the run takes its order and its edges between these specs and names a missing dependency; without it the runner proposes the dependency graph. Independent specs are written in parallel; code stages run for one plan at a time, and revision and split wait while another plan is in them.
- **Continue:** `/plan-chain-runner continue` after an interruption or after answering questions; finished stages are not repeated; a changed goal roadmap is shown first (`roadmap-changed`: apply it or keep the old graph).
- **Discuss:** the run stopped on questions → `/plan-chain-runner discuss` goes through them one by one with options and a recommendation; an answer that changes a spec sends you to `/plan-brainstorming <spec>` (amend mode).
- **One step by hand:** call the skill directly, e.g. `/plan-iterative-revision <plan>` or `/plan-resolver <plan> fix`; it records its stage in the same journal, so a later `continue` takes it into account.
- **The chain stopped:** `/plan-chain-runner status` shows where and why; then `discuss`, then `continue`. A corrupt journal: `brainstorm_tool.py journal-reconcile <journal> --rebuild`, then `continue` (the start card is shown again).

### Runner commands

| Command | What it does |
|---|---|
| `/plan-chain-runner <goal>-roadmap.md` | new run from the goal roadmap: its order, dependencies, groups and notes, then the loop |
| `/plan-chain-runner <spec> [<spec>…]` | new run of these specs: start dialogue, then the loop |
| `/plan-chain-runner continue [<goal>\|<roadmap>]` (`продолжить`) | resume from the journal |
| `/plan-chain-runner discuss [<goal>\|<roadmap>]` (`обсудить`) | answer the open questions one by one |
| `/plan-chain-runner status [<goal>\|<roadmap>]` (`статус`) | plans in `#` order with their groups, stages, progress, questions, ETA; changes nothing |
| `/plan-chain-runner help` | this quick reference, the map first |

Without `<goal>` the runner finds the journals with unfinished stages; with several it asks which.

### Where the artifacts are

| Artifact | Where |
|---|---|
| Spec | `<dir>/<X>-spec.md`, written by `plan-brainstorming` |
| Plan | `<dir>/<X>-impl.md`, next to the spec |
| Chain journal | `<dir>/<goal>-chain.json` (`<goal>` = the spec's `> Backlog:` value, else the spec name without `-spec.md`) |
| Reviews | `<dir>/<X>-impl-review-N.md`, `<X>-impl-completion.md` |
| Roadmap and parts | `<dir>/<X>-impl-roadmap.md`, `<X>-impl-a.md`, … |
| Goal roadmap | `<dir>/<goal>-roadmap.md`: order of the goal's specs, written by `plan-brainstorming` (`roadmap-write`); the runner's argument, recorded in the journal with its hash (`runner.roadmap`, `runner.roadmap_sha256`) |
| Ledger | `<repo parent>/.exec/<repo>-<plan>/state.json`, outside the repository |
| Audit report | `<dir>/<X>-impl-report-N.md`, `<X>-impl-report-N-final.md` |
| Diff report | `<dir>/<X>-diffs.md` |
| Follow-ups | `<dir>/<goal>-followups.json`: defects outside the plans, input for the next `plan-brainstorming` |
| Backlog | `BACKLOG.md` at the repository root, the goal's section |
| Runner settings | `~/.planforge/runner.json` (example: `assets/runner.example.json`); session marks in `~/.planforge/sessions/` |

## What Happens

1. **Start** — every spec is checked (`spec-check`); the runner names the host profile in one line; from a goal roadmap it takes the roadmap's order, dependencies, groups and notes (no graph proposal), otherwise it proposes the dependency graph; then it shows one start card: graph and order, models and effort per role, the specs' chain settings, environments with their rights, volume and ETA. You confirm or edit it once. A dirty working tree: the runner lists the files and asks whether to make a start commit; declined, it asks whether execution may run on them ("run on them / stop there"): "run on them" records the runner's `dirty-worktree:` question, answered `allow-dirty`, which the executor applies; "stop there" lets each execution stop on `dirty-worktree` for `discuss`.
2. **Loop** — `chain_tool.py run-next` says what may run now; each stage runs as an agent of its skill with the model of its role, in silent mode. Writing of independent specs runs in parallel; execution, audit and commit run for one plan at a time, and while one plan is in them the revision and split of the others wait (they read the code it changes); the audit runs alone. With `split=auto` the splitter's numeric gate runs first: a plan it keeps whole skips the split stage without an agent, and so does a borderline plan within the budget (`gate: borderline → keep (…; budget 40 tasks / 150 KB)`); when the splitter is missing or the gate fails (warning `gate-unavailable: …`), a splitter agent decides as before. A writer cut off by the host leaves the marker `> Writing: in progress` in its plan; `run-next` then returns `writing` with `resume: true`, and the runner relaunches it with the same brief until the stage ends, like the execution of a large plan. It does so after `failed` too, and after the answer to a `stopped` writing's question; three relaunches in a row without a new task or a changed byte stop it with a `stage-failed: writing` question. A host error of an agent call (overload, rate limit, a dropped connection, a time-out) is waited out — 1, 2, 5, 10, 10… minutes, an hour at most — and the stage repeats without a question; after an hour it fails with one `stage-failed:` question. While another plan's revision or split still reads the code, the next plan does not start its execution (`reading-busy`).
3. **Progress** — one line per stage start and end, during execution every 10 tasks or 10 minutes, with the remaining time.
4. **Stops** — a decision is recorded as a question in the journal; that plan and the plans depending on it wait, the others go on. At the end: one summary and all questions together, and, when the run is done, the checklist of what is left to do by hand (update installed skills, prune snapshots, repeat control checks, amend specs) appended to the goal's `BACKLOG.md` section by `run-checklist`.

## Settings

`~/.planforge/runner.json` holds the model and effort of each role (`writing`, `revision`, `split`, `execution`, `audit`, `commit`) per profile (`claude-code`, `github-copilot`, `fallback`) and `parallel`. Without the file the built-in defaults apply; `split` runs on `sonnet` with low effort, because it reads only the plan's task list. The `execution` role may also name `light`, a cheaper model for green tasks (documentation, test-only, Quick-tier tasks without `External`, not checkpoints) that the executor hands to a subagent; the default is none (no delegation), in `claude-code` it is an alias such as `"light": "haiku"`. A host that refuses it turns delegation off for the run without a question. The runner writes the file only when you agree to remember an edited table.

## Cost

`chain_tool.py run-stats <journal>` shows what a run cost: per plan and stage the files written, their size and code share, the minutes, the model, the host's token count when the runner recorded it (`basis: host`) or an estimate of input/output/effective tokens from what the stage read and wrote (bytes / 3, output weighted 4×; `basis: estimate`), and quality (audit status and issues, reviews, unit retries). The reads model follows the artifacts: an incremental review or report (`**Audit tasks**`, `audit_tasks`) counts only the named tasks, a script split (`split_method=script`) only the task list, and an incremental report only the evidence files changed since the previous report plus those of its tasks. With a journal every plan of the journal is a row: a plan outside the run carries `outside_run: true`; `totals` is the run's total and `journal_totals` the journal's. Both carry `actual_tokens`, the sum of the host's token counts of their plans (`null` when none has one), and each of their stages its own `actual_tokens`. `--plan <plan.md>` does the same for a plan without a journal (no durations); `--baseline <json>` adds deltas against an earlier result, absolute, per task and per KB of plan, and warns `basis-mixed` when a stage was measured differently on the two sides. The summary's "Volume" line is this number; the model, the baseline and the checkpoints of the toolkit's own refactoring are in `docs/COST.md`.

## Prerequisites

- Python 3.8 or newer in PATH; the six pipeline skills installed side by side with this one.
- Approved specs that pass `spec-check`; git for the start commit, the diff report and the commit stage (without git these are skipped).

## Common Errors

| Symptom | Cause | Fix |
|---|---|---|
| Refused at the start: specs of different goals | One run is one goal | Run each goal separately |
| `graph-cycle: a -> b -> a` | The edited graph has a cycle | Remove an edge in the start card |
| `roadmap-mismatch` | The roadmap is not in the journal's folder, or its `> Goal:` names another goal | Start from the roadmap of this goal, in its own folder |
| A `roadmap-changed` card on `continue` | The goal roadmap changed after the run started | Apply the change, or keep the old graph and amend the roadmap later |
| `not-in-roadmap` (exit 2 at the start) | A spec of the call is not a row of the goal roadmap | Add it to the roadmap through `plan-brainstorming`, or leave it out of the run |
| `unknown-spec` (exit 2 at the start) | The graph names a spec outside the run, or a spec is not registered in the journal | Fix the graph in the start card; register the spec through `plan-brainstorming` |
| Refused at the start: `spec-not-found` | `roadmap-check` found a roadmap row without its spec file | Restore the file, or fix the roadmap through `plan-brainstorming` (amend) |
| `roadmap-missing` | The run's roadmap file is gone | Nothing: the run goes on with the journal's graph; restore the file to get the notes back |
| "Another runner session is active" | A session mark younger than 30 minutes, or an older one while a stage is still `running` (`session-stale-running`) | Continue here (takes it over) or stop |
| The runner stops: "the run was continued in another window" | Another session took the run over (`session-taken-over`) | Nothing: the other window goes on |
| `journal-corrupt` | The journal file is broken | `brainstorm_tool.py journal-reconcile <journal> --rebuild`, then `continue` |
| `journal-locked` | Another process holds the journal's lock | Wait for it, then `continue` |
| Settings file errors | Invalid `~/.planforge/runner.json` | Fix the file, or use the built-in defaults for this run |
| Stage "not confirmed" | After an agent returned (whatever it said, an error included) or was silent for 60 minutes, the journal does not show its stage moved, also after one repeat | `discuss`: retry or stop |
| A `stage-failed:` question after host errors | The host refused the agent calls (529, 429, a dropped connection) for an hour | `discuss`: `retry` when the host is back, or `stop` |
| A `stage-failed: writing` question while the plan has the marker | Three relaunches of the writer in a row added no task and changed no byte | Look at the plan's last task; `discuss`: `retry` or `stop` |
| A `plan-oversized:` question | A `split=never` plan is over 40 tasks or 150 000 bytes when its split would be skipped | `discuss`: `continue` (run it whole), `split` (plan-splitter cuts it into parts) or `stop` (shorten the plan or amend the spec; a changed plan is asked again); a plan that cannot be measured is run whole with the warning `size-unavailable` |
| An `open-audit: <plan id>` question | A plan's audit stayed open, and a plan depending on it waits | `discuss`: `accept` (the dependent plan goes on) or `fix` (`/plan-resolver <plan> fix` runs) |
| `status` shows `reading-busy: <plan>` | Another plan's revision or split still reads the code | Nothing: the plan starts when that stage ends |
| A `model:` question | The host refused the role's model and its fallback | `discuss`: `retry <model>`, `retry` or `stop`, then `continue` |
| `blocked`, no open question, a plan waits | A stage was answered `stop`; plans that need the code stages wait as `code-busy` | Run that stage by hand, then `continue` |
| Rewriting a spec or plan | The plan stops once, on the `drift:` question of the earliest changed stage | `discuss`: `rewrite` there; the later stages follow without questions |
| `blocked` at the end | Everything left waits for answers | `discuss`, then `continue` |

## Pipeline Position

`plan-brainstorming` → **[YOU ARE HERE:** `plan-writing` → `plan-iterative-revision` → `plan-splitter` → `plan-executor` → `plan-resolver` → `plan-executor commit`**]**

**Previous:** `plan-brainstorming` (approved specs and the chain journal)
**Next:** `/plan-brainstorming <goal>-followups.json` or `/plan-brainstorming BACKLOG.md <goal>` for the next cycle
