# plan-chain-runner — Quick Reference

Run the approved specs of one goal through the whole pipeline: plan, revision, split, execution, audit and commit. After a short start dialogue the runner works without questions, reports progress in one line, and stops with questions recorded in the chain journal; you answer them with `discuss` and resume with `continue`.

## Pipeline map

### Order of the skills

1. `plan-brainstorming` — idea, goal file, findings JSON or `BACKLOG.md` → approved spec `<X>-spec.md` and the chain journal `<goal>-chain.json`.
2. `plan-writing` — spec → plan `<X>-impl.md`.
3. `plan-iterative-revision` — audits the plan against the code and fixes it: reviews `<X>-impl-review-N.md`.
4. `plan-splitter` — only for a large plan (`split=auto` lets its gate decide): roadmap `<X>-impl-roadmap.md` and parts `<X>-impl-a.md`, `<X>-impl-b.md`, …
5. `plan-executor` — executes the plan or the roadmap one task at a time with a ledger and rollback snapshots; at the end the diff report `<X>-diffs.md`.
6. `plan-resolver` — audits the code against the plan: report `<X>-impl-report-N.md` (`-final` when closed); `fix`/`auto` repair the code.
7. `plan-executor <plan> commit` — commits the run's files and the audit's fixes, with hooks, without push.

`plan-chain-runner` runs steps 2–7 for you; every skill can also be run by hand. `/<skill> help` shows that skill's quick reference.

### Typical scenarios

- **From idea to commit:** `/plan-brainstorming <goal>` → approve the spec → `/plan-chain-runner <spec>` → confirm the start card → wait for the summary.
- **From roadmap to commit:** `/plan-brainstorming <goal>` → approve the specs → its closing report names `/plan-chain-runner <goal>-roadmap.md` → the card shows the roadmap's order, groups and notes → confirm → wait for the summary. The writing and revision agents get the roadmap's notes for their spec.
- **Several specs of one goal:** `/plan-chain-runner <spec-1> <spec-2>`; with `<goal>-roadmap.md` next to the journal the run takes its order and its edges between these specs and names a missing dependency; without it the runner proposes the dependency graph. Independent specs are planned in parallel, code stages run for one plan at a time.
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

1. **Start** — every spec is checked (`spec-check`); the runner names the host profile in one line; from a goal roadmap it takes the roadmap's order, dependencies, groups and notes (no graph proposal), otherwise it proposes the dependency graph; then it shows one start card: graph and order, models and effort per role, the specs' chain settings, environments with their rights, volume and ETA. You confirm or edit it once. A dirty working tree: the runner lists the files and asks whether to make a start commit.
2. **Loop** — `chain_tool.py run-next` says what may run now; each stage runs as an agent of its skill with the model of its role, in silent mode. Planning (writing, revision, split) of independent specs runs in parallel; execution, audit and commit run for one plan at a time; the audit runs alone. With `split=auto` the splitter's numeric gate runs first: a plan it keeps whole skips the split stage without an agent.
3. **Progress** — one line per stage start and end, during execution every 10 tasks or 10 minutes, with the remaining time.
4. **Stops** — a decision is recorded as a question in the journal; that plan and the plans depending on it wait, the others go on. At the end: one summary and all questions together.

## Settings

`~/.planforge/runner.json` holds the model and effort of each role (`writing`, `revision`, `split`, `execution`, `audit`, `commit`) per profile (`claude-code`, `github-copilot`, `fallback`) and `parallel`. Without the file the built-in defaults apply; `split` runs on `sonnet` with low effort, because it reads only the plan's task list. The `execution` role may also name `light`, a cheaper model for green tasks (documentation, test-only, Quick-tier tasks without `External`, not checkpoints) that the executor hands to a subagent; the default is none (no delegation), in `claude-code` it is an alias such as `"light": "haiku"`. A host that refuses it turns delegation off for the run without a question. The runner writes the file only when you agree to remember an edited table.

## Cost

`chain_tool.py run-stats <journal>` shows what a run cost: per plan and stage the files written, their size and code share, the minutes, the model, the host's token count when the runner recorded it (`basis: host`) or an estimate of input/output/effective tokens from what the stage read and wrote (bytes / 3, output weighted 4×; `basis: estimate`), and quality (audit status and issues, reviews, unit retries). The reads model follows the artifacts: an incremental review or report (`**Audit tasks**`, `audit_tasks`) counts only the named tasks, a script split (`split_method=script`) only the task list. `--plan <plan.md>` does the same for a plan without a journal (no durations); `--baseline <json>` adds deltas against an earlier result, absolute, per task and per KB of plan, and warns `basis-mixed` when a stage was measured differently on the two sides. The summary's "Volume" line is this number; the model, the baseline and the checkpoints of the toolkit's own refactoring are in `docs/COST.md`.

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
| `roadmap-missing` | The run's roadmap file is gone | Nothing: the run goes on with the journal's graph; restore the file to get the notes back |
| "Another runner session is active" | A session mark younger than 30 minutes, or an older one while a stage is still `running` (`session-stale-running`) | Continue here (takes it over) or stop |
| The runner stops: "the run was continued in another window" | Another session took the run over (`session-taken-over`) | Nothing: the other window goes on |
| `journal-corrupt` | The journal file is broken | `brainstorm_tool.py journal-reconcile <journal> --rebuild`, then `continue` |
| `journal-locked` | Another process holds the journal's lock | Wait for it, then `continue` |
| Settings file errors | Invalid `~/.planforge/runner.json` | Fix the file, or use the built-in defaults for this run |
| Stage "not confirmed" | After an agent returned (whatever it said, an error included) or was silent for 60 minutes, the journal does not show its stage moved, also after one repeat | `discuss`: retry or stop |
| A `model:` question | The host refused the role's model and its fallback | `discuss`: `retry <model>`, `retry` or `stop`, then `continue` |
| `blocked`, no open question, a plan waits | A stage was answered `stop`; plans that need the code stages wait as `code-busy` | Run that stage by hand, then `continue` |
| Rewriting a spec or plan | The plan stops once, on the `drift:` question of the earliest changed stage | `discuss`: `rewrite` there; the later stages follow without questions |
| `blocked` at the end | Everything left waits for answers | `discuss`, then `continue` |

## Pipeline Position

`plan-brainstorming` → **[YOU ARE HERE:** `plan-writing` → `plan-iterative-revision` → `plan-splitter` → `plan-executor` → `plan-resolver` → `plan-executor commit`**]**

**Previous:** `plan-brainstorming` (approved specs and the chain journal)
**Next:** `/plan-brainstorming <goal>-followups.json` or `/plan-brainstorming BACKLOG.md <goal>` for the next cycle
