# EXECUTION-STRATEGY

## One Diagnosis, Three Params

`unit-begin` returns `strategy` for the unit, derived from its weight and title:

- `isolation`: `main` or `subagent`
- `model_depth`: `light`, `medium`, or `deep`
- `gate_tier`: `green`, `yellow`, or `red` (see `GATE.md`)
- `delegable`: `true` only for `model_depth: light` with `isolation: main`, not a checkpoint and without an `**External:**` line (Delegation below)

A unit's weight is the plan's tier (Quick → green, Standard → yellow, Deep → red), lowered where the expensive gate buys nothing: a checkpoint task and a task whose files are all documentation are green; a task that touches only test files goes one step down.

Titles with whole words such as refactor, architecture, security, migration, concurrency, auth/OAuth raise `isolation`/`model_depth` to `subagent`/`deep` without changing `gate_tier`. Manual overrides are allowed; record the reason in the working notes.

## Context

Work from `unit-begin`'s `text` (the unit's own task: its section of the plan or of a part; for `part-<id>-done`, the part's completion criteria and handoff; for a hand-written part, the whole part file) and `files` (paths from its `Files`/`Inputs`/`Outputs` blocks, with `lines` hints such as `4-6`). Read those files yourself; do not re-read the whole plan for every unit. `lines` describe the file before the plan started; earlier units shift them, so locate the code by the quote in the step, not by the number.

If `files` is empty, search with Grep/Glob for class, function, command or file names from `text`. Do not build or rely on a repo map; keep context local to the unit.

## Delegation

Off unless the launch names a `light` model. `unit-begin`'s `strategy.delegable` is computed, never chosen: a unit with `delegable: false` is never delegated; a `delegable` unit may still be done in the main agent.

**The model.** `light` comes from the launch: the argument `/plan-executor <plan> light=<model>` or the runner's brief item "Model for green units: `<model>`" (`light`). It is read on every launch, never from the ledger: pass it as `ledger-init … --light <model>`, which stores `settings.light` for `run-stats` only. Without `light` the executor works as before and says nothing about it. With `light` but no tool that starts a subagent with a model (Claude Code: `Agent` with `model`; GitHub Copilot CLI: `task` with `model`), say once at the start "light=<model> given, no subagent tool: every unit runs in the main agent" and run them so; finish each `delegable` unit that passes there with `unit-finish <exec_dir> <unit> pass --note subagent-unavailable` (this exact token, as a note: the unit did not fail, so never `--error`; a chain looks for the token in the ledger's notes). When the host refuses the model at a launch, say in one line "light <model> unavailable, the rest of the run in the main agent": that unit and the rest run in the main agent, without `--delegated`; in a chain the agent's reply names the refusal, and the runner handles it (plan-chain-runner LOOP.md, After the agents, 4).

**The subagent's brief** (`model: <light>`), for a unit with `delegable: true`, in this order and nothing more:

1. The repository: `<repo>` (absolute path); the unit's text: `text` of `unit-begin`, verbatim.
2. Its files: the `path` of every entry of `files`, relative to `<repo>` (`lines` are hints).
3. Change only these files and write only inside `<repo>`: every path relative to `<repo>`, never an absolute path, a `..` path or a path in another folder; run the commands of the steps and keep their output.
4. Return every path you wrote, created files included, relative to `<repo>`, and the output of every command you ran.
5. Do not read the plan, do not call `executor_tool.py` (no `unit-finish`), do not commit or run other git commands that write, do not reach any database, API or remote service.

**File check.** By the tool, never by hand. Before the launch: `delegate-check <repo> --snapshot-out <exec_dir>/delegate-<unit>.json` (a snapshot of `git status --porcelain=v1 --untracked-files=all --no-renames` and the `hash-object` of every listed path; the file lies next to the ledger, outside the repository). After the subagent returns: `delegate-check <repo> --snapshot <exec_dir>/delegate-<unit>.json --files <every path the subagent named>`. The result's `verdict` (`pass`/`fail`) comes with `outside` (a named path that leaves `<repo>` after `realpath`: `..`, an absolute path elsewhere, a link out of it), `unreported` (changed, not named; `BACKLOG.md`, the chain journal and the pipeline's own files that nobody named are left out: other agents of a chain may write them meanwhile), `phantom` (named, not changed) and `changed`. The attempt fails (`fail`, not repaired by the parent within this attempt) on `verdict: fail`, when the subagent returned no result, or when a path of `changed` that is not a pipeline file (`BACKLOG.md`, the run's journal and the chain-file names that `unreported` leaves out) is not in `files` of `unit-begin`; the error signature names the field and the paths (`delegate-check: outside ../notes/b.md`). `no-git` (exit `1`) or `snapshot-invalid` (exit `2`) before the launch: the unit is not delegated, run it in the main agent. The check does not see a write outside `<repo>` that the subagent did not name, nor a write into a file git ignores: there the host's sandbox is the only guard; name such a path in the final summary when the subagent's reply shows it.

**Gate and finish.** The parent gates the unit itself by `gate_tier` (GATE.md, Delegated Units) and finishes it: `unit-finish <exec_dir> <unit> pass|fail [--error "<signature>"] --delegated <light>`. `--delegated` records `units[].delegated` in the ledger and `delegated` in the journal's `unit-finish` event; `run-stats` counts them as `quality.delegated` (`units`, `retries`).

**Retry.** After a `fail` of a delegated attempt the retry (`retry-available`) always runs in the main agent, without `--delegated`: one failure of the cheap model is a quality signal, it is not risked twice. Retry and rollback as in GATE.md, Retry & Rollback.

Never delegated: units with `isolation: subagent` (heavy keywords), `**External:**` units, checkpoints (`Checkpoint — …`, `part-<id>-done`), every unit that is not green, a retry.
