# Gate Decision: split or not

Before decomposing, decide whether the plan needs splitting at all. The decision is numeric:
`TOOL gate PLAN` computes it with the shared task parser; the model reads neither the plan nor its
tasks for it.

## Settings

`split` from the chain settings of the source plan (SKILL.md, Inputs) comes first: `always` →
split without the gate; `never` → the splitter is not needed; `auto`, or no settings → run the
gate. In a chain with `split=auto` the runner calls the same gate (`gate_verdict`) before it
launches the splitter and skips the stage without an agent on `keep`.

## Factors

| Factor | How it is computed |
|---|---|
| `task_count` | `### Task N:` headings (`brainstorm_tool.parse_plan_tasks`) |
| `plan_bytes` | size of the plan file |
| `modules` | distinct folders, at most two levels deep, of the paths in the tasks' `Files` blocks (`.` for a file at the root) |
| `dependency_shape` | `linear` when no task has two or more incoming or outgoing Preconditions references (`refs`), else `groups` |

## Rule

| Verdict | When |
|---|---|
| `keep` | `task_count` ≤ 20, `plan_bytes` ≤ 100 000 and `modules` ≤ 3 |
| `split` | (`task_count` > 40 or `plan_bytes` > 150 000) and (`modules` > 3 or `dependency_shape: groups`) |
| `borderline` | anything else |

The thresholds are flags of `gate` (`--keep-tasks`, `--keep-bytes`, `--split-tasks`,
`--split-bytes`, `--modules`). 40 tasks and 150 000 bytes are the budget of `plan-oversized` in
`plan-check` (`brainstorm_tool.SIZE_BUDGET`); a contract test in `plan-writing/tests` holds them
equal. The result carries `factors`, `thresholds` and one `reasons` line per factor.

`borderline` is the only case the model decides: from `brainstorm_tool.py plan-tasks PLAN` (ids,
titles, files, refs, sizes), never from the plan text. Prefer "keep" when the tasks form one
module and a linear chain; split when they fall into groups that each fit one agent pass.

## Outcomes

- **Keep**: print `assets/gate-pass.<LANG>.md` with `{{PLAN_PATH}}` filled in and exit. This is
  the skill's visible result, not an error; no files are created; journal `skipped`, `why: gate`.
- **No tasks** (`gate` exit 1 `no-tasks`): the script has nothing to cut; exit without files,
  journal `skipped`, `why: no-tasks`. A roadmap for such a plan is written by hand.
- **Split**: continue with step 3 (analysis).
