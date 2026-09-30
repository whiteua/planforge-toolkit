# Gate Decision: split or not

Before decomposing, decide whether the plan needs splitting at all.

## Factors

| Factor | Points to "split" | Points to "keep" |
|---|---|---|
| Task count | > 15–20 concrete steps | ≤ 10 steps |
| Domain spread | > 3 unrelated modules or layers | one module, linear flow |
| Dependencies | groups of tasks that block each other | a linear chain |
| Context size | does not fit one agent pass | doable in one session |
| Parallelism | tasks that could run in parallel | nothing to parallelize |

## Rule

Split when **either** ≥ 2 factors point to "split", **or** one factor alone blocks a single pass
(context size or domain spread). Otherwise keep. In borderline cases prefer "keep": the user
can re-run the skill if the plan really needs it.

The same threshold ("more than 15–20 tasks or several modules") is what `plan-writing`
suggests at hand-off.

## Outcomes

- **Keep**: print `assets/gate-pass.<LANG>.md` with `{{PLAN_PATH}}` filled in and exit. This is
  the skill's visible result, not an error; no files are created.
- **Split**: continue with step 3 (analysis).

A plan that already has explicit stages (`## Stage 1`, `## Stage 2`, …) is a "split" signal;
reuse its boundaries.
