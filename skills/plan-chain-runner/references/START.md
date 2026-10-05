# START

The start dialogue of a new run: `/plan-chain-runner <goal>-roadmap.md` or `/plan-chain-runner <spec> [<spec>…]`. It is the only place where the runner asks the user before the loop; everything after the card is silent (SKILL.md, invariant 4). `C` and `J` as in SKILL.md, Tool.

## 1. Input

**A goal roadmap** (the argument ends with `-roadmap.md`; `<roadmap>` is its path):

1. `J roadmap-check <roadmap>`. Exit `1` → refuse the run and list its `errors` (a spec of the roadmap without its file is one of them, `spec-not-found`); the roadmap is fixed through `plan-brainstorming` (amend). Exit `2` → the file cannot be read: refuse and say so.
2. `J roadmap-parse <roadmap>`: the specs in `#` order with `file`, `title`, `depends`, `group`, `tier`, `estimate`, `notes`, `handoff`, and `groups`. Keep it for the card (4).
3. `J journal-path <roadmap>`: `kind` must be `goal-roadmap`; its `journal` is the goal's journal.
4. The spec steps 1–4 below for every spec of the roadmap (its `file`, next to the roadmap). Every spec must name this `journal`; otherwise refuse: one run is one goal (the roadmap and its specs belong to different goals).
5. `C subset-check <journal> --roadmap <roadmap>` (no `--spec`: every spec of the roadmap): `specs` and `graph` are the run (3); `not_in_roadmap` lists the journal's specs the roadmap does not name and `dropped_uncommitted` the plans that would leave the run with uncommitted changes (4).

**Specs** (the arguments are `*-spec.md`):

1. `J spec-check <spec>` for every spec. Exit `1` → refuse the run and list the `errors` per spec (fix them with `/plan-brainstorming <spec>`). Exit `2` → the spec cannot be read: refuse and say which. Show `warnings` in one line each. Keep `lang`, `chain`, `environments` and `backlog` of each result.
2. `J journal-path <spec>` for every spec. All results must name the same `journal`; otherwise refuse: one run is one goal. Propose one run per goal, listing the goal and its specs.
3. `J journal-path <spec> --create` for every spec: creates the journal or registers the spec in it. The specs of one goal lie next to their journal, so inside the journal a spec is named by its file name.
4. `J journal-show <journal>`. Open questions of an earlier run → propose `discuss` first (DISCUSS.md); the user may still start, the plans with open questions then wait. The journal file already has a `runner` section → the goal was run before: propose `continue` (LOOP.md, Continue); a new start writes `runner` again and keeps its `sessions`.
5. The goal roadmap `<goal>-roadmap.md` next to the journal (`goal` of `journal-path`); call it by its full path `<journal_dir>/<goal>-roadmap.md` (`<journal_dir>` = the journal's directory), since these commands run where the specs were given. It exists → it is the base of the run: `J roadmap-check` (exit `1` → refuse as in the roadmap form), `J roadmap-parse`, and `C subset-check <journal> --roadmap <journal_dir>/<goal>-roadmap.md --spec <spec>...`: the run is these specs in the roadmap's `#` order (`specs`) with the roadmap's edges inside the set (`graph`); `not_in_roadmap` → those specs stay out of the run (the card's warning, 4); `missing_dependencies` → the card names them (4). `subset-check` exits `2` `roadmap-mismatch` (the file names another goal) → refuse: one run is one goal. No such file → the graph dialogue (3), as before.

The dialogue language is the `lang` of the first spec's `spec-check` (SKILL.md, Language).

## 2. Profile

Detect the profile by the tools of this session (PROFILES.md, Detection) and say it in one line, e.g. "Profile: Claude Code — agents, models, parallel runs".

## 3. Graph

**With a roadmap** (1): no edges are proposed. The run's graph is `graph` of `subset-check`, its order `specs` (the roadmap's `#`). Sources of the graph, the first wins: the roadmap → the card's edits (this run only) → the dialogue below (only without a roadmap). The runner never edits the roadmap. The user may change an edge or the order in the card; an order change is made as an edge (B after A: B depends on A), because `run-init --roadmap` keeps the specs in `#` order. The card says that such an edit holds for this run only: the roadmap is better amended through `plan-brainstorming`, otherwise a new start from it proposes its own graph again.

**Without a roadmap:** one spec: no graph. Several: read each spec's Goal, Components and Out of Scope and the places where one spec names another. Propose the edges "B depends on A" with one reason each ("B extends the journal that A introduces"), and the order that follows. No edge without a reason taken from the specs; independent specs stay independent. The edges point from a spec to the specs it needs; a cycle is an error, not an order.

Stages that are already `done` in the journal (`journal-show`) are not repeated: `run-next` skips them. Say which plans are already partly done.

## 4. The start card

One message, for confirmation or edits:

- **Graph and order** from 3. With a roadmap: a table `#` / spec / depends on / group / tier / estimate from `roadmap-parse` (the run's specs only), the edges in one line as the roadmap's `## Graph` draws them (`s1 --> s2; s2 --> s3`), and each spec's `notes` in one line. Say plainly that `#` orders only within `parallel` and for the code stages: independent specs of one level start together.
- **Roadmap warnings:** `not-in-roadmap: <spec>` for each spec of `not_in_roadmap` (it stays in the journal without agents). `missing_dependencies` → name them and offer "add them to the run / stop": add → `subset-check` again with them in `--spec`, then the card again. `dropped_uncommitted` → refuse to start without that plan: its execution started and is not committed, so another plan would execute over its changes; commit it first (`/plan-executor <plan> commit`) or, when the roadmap names its spec, add it to the run.
- **Models:** `C settings-load --profile <profile>`: a table role / model / effort / fallback / pinned, the `light` of `execution` in its row (the model of delegated green units; none = no delegation, the default), and `parallel`; each of its `warnings` (`light-ignored: <role>`) in one line. An alias does not pin the version, a full model id does (`pinned`; PROFILES.md, Pinned models). Exit `2` → show the `errors`, and offer the built-in defaults for this run (PROFILES.md, Built-in defaults). When the user edits the table, ask in the same message whether to remember it: "yes" → `C settings-save --profile <profile> --roles '<edited roles JSON>'`, "no" → the edits hold for this run only (they go to the journal through `run-init`).
- **Chain settings** of each spec: `split`, `revision`, `stop`, `resolver` from `spec-check`.
- **Environments** with their rights (`read=`, `write=`) from `spec-check`. A separate warning: any task whose environment has the right `task`, a write on prod included, will stop its plan on a question; the run cannot confirm it. A plan stopped in execution, diffs, audit or commit keeps those stages (its changes are uncommitted in the shared working copy): the independent plans are still written, revised and split, but their execution waits (`code-busy`) until that question is answered. The same holds for a plan that drift sent back to writing, revision or split after its execution started: it keeps the code stages until it commits, and when it stops on a question there, the hold lasts until the user acts (`code-busy`).
- **Volume and ETA:** the number of plans and of stages still to run. `C run-eta <journal>` only when the journal already has a `runner` section; give `eta_minutes` when `basis` is not `none`, else leave the ETA out.
- **Old spec without `> Chain:`** (`chain` is `null` in `spec-check`): ask here the questions plan-writing would otherwise ask (1. Spec Preflight of plan-writing): the environments the steps touch and their rights, changes named first; the chain defaults (spec-contract.md) to confirm or edit; the backlog section. Keep, for each environment, the user's question and answer verbatim with today's date, and the confirmed chain settings and backlog section: they go to the plan-writing agent in its brief in that form (LOOP.md, Brief, 7), and it writes them into the plan header without asking again (plan-writing, 1. Spec Preflight).
- **Effort and pinned models, profile `claude-code`:** when a role's effort differs from the session's (unknown counts as different), or its model is pinned, offer once to create the agent definitions `~/.claude/agents/planforge-<role>.md` (PROFILES.md, Agent definitions), and say that the host's support of the `effort` key in them is not confirmed (PROFILES.md, Verified) while no entry there has the verdict `verified`: the role may still run with the session's effort. Without consent the effort is inherited, and a pinned role runs through `Agent` with its full model id.

Apply the edits and show the card again only when the user changed the graph or the models.

## 5. Dirty working tree

First, with or without git, before anything is written (the start commit, the questions of this step, `run-init`): when the journal already has a `runner` section (1.4), `C run-status <journal>`. Its `session` with `active: true` (another session of this goal was active `age_seconds` ago), or with `active: false` while a stage of some plan is `running` in `plans[].stages` (perhaps a long agent of another window, an audit included) → ask "continue here / stop", naming the stage and the age. Stop → end here, nothing written. Continue → go on; 6.2 then passes `--takeover` at once, without asking again.

Then, only with git (`git -C <repo> rev-parse --show-toplevel` succeeds; `<repo>` is its output). `git -C <repo> status --porcelain --untracked-files=all` lists changed and untracked files one by one, with paths from the repository root (a rename gives both paths; a new folder is not folded into one line); leave out the chain's own files even when they appeared during step 1: the journal and its `.lock`, `*-diffs.md`, `*-followups.json`, the goal roadmap `<goal>-roadmap.md`, review, completion and report files. Specs and the goal file stay in the list; the user may strike them.

- Empty list → `start_commit` is `none`.
- Otherwise show the list, explain in two sentences why a start commit helps (the run's diff report and commit then hold only the run's own changes; a rollback has a clean point), and ask "yes / no".
- "Yes" → `git -C <repo> add -- <the listed files>`, then `git -C <repo> commit -m "chore: snapshot before plan-chain-runner run" -- <the listed files>`: only the listed paths are committed, also when other files were staged before; no push. `start_commit` = `git -C <repo> rev-parse HEAD`.
- "No" → `start_commit` is `declined`. In the same answer say that the execution of each plan will stop on `dirty-worktree` because of these files, and ask whether execution may run on them ("run on them / stop there"). "Run on them" → for every plan of the run, from the journal's directory, `J journal-question <journal> --skill plan-chain-runner --plan <X>-impl.md --spec <X>-spec.md --stage execution --text "dirty-worktree: <the user's words>, <date>; files: <the list>" --option allow-dirty --option stop --answer allow-dirty`, where `<X>-impl.md` is the plan name derived from the spec `<X>-spec.md` (the plan may not be written yet); the executor's brief carries it (LOOP.md, Brief, 8). "Stop there" → nothing recorded; the executor stops on `dirty-worktree` and `discuss` takes it then.
- The user struck files from the list → they stay uncommitted: the same follow-up question as for "No".
- A hook fails → show its output; never retry with `--no-verify`. Ask "continue without the start commit / stop": continue → `declined`.

No git → no question, `start_commit` is `none`.

## 6. Start

1. From the journal's directory, so that the spec file names resolve: `C run-init <journal> --profile <profile> --spec <spec file>... --graph '<JSON>' --models '<JSON>' --parallel <N> --start-commit <sha|declined|none>`. `--parallel` is the confirmed `parallel` of the card: it is stored as `runner.parallel`, and `run-next` takes it from there (on `continue` too), so an edit not remembered in the settings file still holds for the whole run. `--graph` maps a spec file name to the spec file names it depends on (`{}` for one spec); with a roadmap (1) add `--roadmap <goal>-roadmap.md` (its file name, like the spec file names: `run-init` runs from the journal's directory, and a path given from elsewhere resolves wrongly to `roadmap-mismatch`) and take `--spec` (in that order) and `--graph` from `subset-check` (`specs`, `graph`) with the card's edits: `run-init` stores the specs in `#` order and writes `runner.roadmap` (the file name) and `runner.roadmap_sha256`; `--models` maps every role to `{"model": …, "effort": …, "fallback": …}` from the confirmed card (`fallback` as `settings-load` gave it; `model-pick --journal` reads it there), `execution` also with its `"light": …` (`run-init` keeps it only when set).
   - exit `1` `graph-cycle: a -> b -> a` → show the cycle and ask to fix the graph in the card;
   - exit `2` `unknown-spec` → a spec was not registered: repeat step 1.3 for it.
   - exit `2` `roadmap-mismatch` (the roadmap is not a file in the journal's directory, or its `> Goal:` names another goal) → refuse: one run is one goal;
   - exit `2` `not-in-roadmap: <spec>` → the roadmap does not name that spec: leave it out of `--spec` (the card's warning).
2. `C run-session <journal> --begin --host <profile>`; keep the `id` of the result: every later `--heartbeat` and `--end` passes `--id <id>` (LOOP.md, Session mark). Exit `1` `session-active` → another session of this goal was active `age_seconds` ago: ask "continue here / stop"; continue → the same command with `--takeover`. Exit `1` `session-stale-running` → the mark is older than 30 minutes, but the journal has `stage` of `plan` `running` (perhaps a long agent of another window, an audit included): ask the same question, naming the stage and the age; continue → `--takeover`.
3. Say one line: "Starting; from now on no questions, I stop only if your decision is needed." Then the loop (LOOP.md).

## Roadmap changed

`run-status` gives `roadmap.sha_matches: false` with `missing: false`: the goal roadmap changed after `run-init` read it (on `continue`: LOOP.md, Continue, 4). A new graph never applies before the user confirms it. `<roadmap>` here is `<journal_dir>/<runner.roadmap>` (`runner.roadmap` is a file name in the journal's directory).

1. `J roadmap-check <roadmap>`. Exit `1` → show its `errors` one per line (a cycle is `dependency-cycle`); the card offers only "go on with the old graph / stop".
2. `J roadmap-parse <roadmap>` and `C subset-check <journal> --roadmap <roadmap>`. Compare them with `runner.specs` and `runner.graph` of the journal file: edges added and removed, order changes, specs added (in the roadmap, not in `runner.specs`) and gone (in `runner.specs`, not in the roadmap).
3. The card `roadmap-changed`, one message: those differences and "apply / keep the old graph". Each spec of `dropped_uncommitted` is named with the refusal to drop it: its execution started and is not committed, so another plan would execute over its changes; commit it first (`/plan-executor <plan> commit`) or keep the old graph. While there is such a spec, the options are "keep the old graph / stop".
4. Apply → for each added spec `J spec-check <spec>` (exit `1` → its errors; the change is not applied) and `J journal-path <spec> --create`. Then, from the journal's directory, `C run-init <journal> --profile <runner.profile> --spec <specs of subset-check>... --graph '<its graph>' --models '<runner.models>' --roadmap <runner.roadmap>` (the file name: this call runs from the journal's directory): the profile, the models and `parallel` stay; no `--start-commit` (the old value stays). Stages already `done` are not repeated; an added spec enters with `pending` stages; a spec gone from the roadmap stays in the journal without agents, like a plan outside the run. Exit `1` `graph-cycle` → show it; the old graph stays.
5. Keep the old graph → nothing is written; the loop runs on `runner.graph`, and the next `continue` shows this card again while the file differs.

## Rebuilt journal

`journal-reconcile --rebuild` drops the `runner` section, the questions and the answers; `run-session --begin` then exits `1` `runner-missing`. Show the card again (graph and models, without step 5), run `run-init` without `--start-commit`, then `run-session --begin`; decisions made before are asked again when their stage meets them.
