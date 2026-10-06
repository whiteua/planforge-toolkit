# Eval Scenarios

Subagent pressure tests for the `plan-splitter` skill. Format follows
`writing-skills/testing-skills-with-subagents.md` (RED-GREEN-REFACTOR):
load the skill into a fresh subagent, apply the Setup, and check behavior
against Expected / Red flags. A failing scenario means the skill wording
must be strengthened, not the test loosened.

## Scenario 1: Gate and split table in the plan's language

- **Setup:** Russian plan of 30 tasks (`detect-lang` gives `ru`), interactive run, no `split` in
  the settings.
- **Trigger:** Subagent reaches the gate decision and then the split-table confirmation.
- **Expected (PASS):** The verdict with its factors, the confirmation question, its option labels
  and descriptions and the final report are in Russian; file names and commands stay as they are.
- **Red flags (FAIL):** English verdict or options for a Russian plan; a mix of languages in one
  question.

## Scenario 2: The `split` stage in the journal

- **Setup:** Plan with a chain journal. Run A: `split=auto` and the gate decides not to split.
  Run B: `split=always`, three parts, `verify=all`.
- **Trigger:** Subagent finishes each run.
- **Expected (PASS):** Run A: `journal-event … --stage split --status skipped` with the reason in
  `--data`, no files written. Run B: `split` is `running` at the start and ends `done` with
  `--input <plan> --artifact roadmap=<base>-roadmap.md --artifact parts[]=<base>-a.md
  --artifact parts[]=<base>-b.md --artifact parts[]=<base>-c.md --artifact split_method=script`; the batch verification of the
  parts stays inside the `split` stage.
- **Red flags (FAIL):** The batch verification marks the plan's `revision` stage; `split done`
  without the parts; `split` left `running`; the source plan edited.

## Scenario 3: The script cuts the plan

- **Setup:** A copy of `docs/.plans/fix-02/fix-03-impl.md` (91 tasks, about 550 KB) in a temp folder
  with a chain journal; `split=auto`; no part files; run without a confirmation channel.
- **Trigger:** `/plan-splitter <copy>/fix-03-impl.md`.
- **Expected (PASS):** `gate` gives `split`; the agent reads `brainstorm_tool.py plan-tasks`, writes
  only `parts.json` outside the repository and calls `split-write` (a `dependency-order` error is
  fixed in `parts.json` and the call repeated); `validate-all` passes with `task_bodies.matched` 91;
  `split: done` with `--artifact roadmap=…`, the `parts[]` and `--artifact split_method=script`.
- **Red flags (FAIL):** Task text in the agent's output; Write or Edit on a part or the roadmap; the
  plan read whole; `split: done` without `split_method=script`.

## Scenario 4: A borderline plan is decided from the task list

- **Setup:** An English plan of 30 tasks in 2 modules, so `gate` gives `borderline`; interactive run.
- **Trigger:** Subagent reaches the gate decision.
- **Expected (PASS):** The verdict with the `reasons` lines; the decision comes from `plan-tasks`
  (ids, titles, files, refs), and the plan file is never opened; "keep" prints the gate-pass notice
  and records `skipped` with `why: gate`.
- **Red flags (FAIL):** Reading the plan file; scoring five factors by eye; writing parts by hand.

## Scenario 5: A silent run asks nothing

- **Setup:** A plan of 45 tasks in 2 modules with a linear chain (`gate` gives `borderline`, `silent_verdict: split`),
  a chain journal, `split=auto`, run without a confirmation channel (as a chain agent).
- **Trigger:** `/plan-splitter <plan>`.
- **Expected (PASS):** The decision is `silent_verdict`; no `journal-question` about the gate or the split table; the
  agent writes `parts.json` from `plan-tasks` and calls `split-write` at once; `split: done` carries `roadmap`, the
  `parts[]`, `split_method=script` and one `parts_table` string with the parts separated by ` | `.
- **Red flags (FAIL):** A question "split or keep?" or "confirm the table?"; the stage left `stopped`; `parts_table[]`
  as a list; the plan file read whole.

## Scenario 6: never, but the user answered split

- **Setup:** A plan of 45 tasks with `split=never`; the chain journal holds the runner's answered question
  `plan-oversized: 45 tasks, … bytes (budget 40 / 150000; plan sha256 …)` of this plan with the answer `split`; run
  without a confirmation channel (as a chain agent).
- **Trigger:** `/plan-splitter <plan>`.
- **Expected (PASS):** The `running` event of `split` carries `--reason user-request`; the gate decision is "split" as
  with always, named as the user's answer; `parts.json` from `plan-tasks`, `split-write`, `split: done` with `roadmap`,
  `parts[]`, `split_method=script`; the question is not marked `--applied` by the splitter.
- **Red flags (FAIL):** `split: skipped` with `why: split=never`; a new question "split anyway?"; `running` without
  the reason; the splitter marks the runner's question applied.

## How To Run

For each scenario: dispatch a fresh subagent with the skill loaded, paste
the Setup as the user turn, observe. Record PASS/FAIL. On FAIL, strengthen
the relevant `SKILL.md` / reference wording and re-run.
