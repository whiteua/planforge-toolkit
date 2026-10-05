# Cost accounting

How PlanForge measures what a chain run costs, and the baseline the token-saving refactoring of
`plan-refactoring-01` is compared against. The measurement is deterministic and artifact-based: no
provider API is called. Where the host shows an agent's token usage, the runner records it and the
fact replaces the estimate.

## Model

`chain_tool.py run-stats` reads the files a run left next to the plan and, with a chain journal, the
journal's stages and events. For every stage it reports:

| Field | Meaning |
|---|---|
| `files[]` | the files the stage wrote (name, bytes, lines, share of lines inside code fences) |
| `bytes_written` | their size; `bytes_read_est` — what the stage read by the reads model below; `reads_mode` — the rule that applied |
| `tokens.input_est`, `tokens.output_est` | `bytes / 3`: a proxy of ≈ 3 characters per token for mixed prose and code, applied to the UTF-8 byte length (Cyrillic text is two bytes per character, so the estimate is higher than a per-character one: +13 % on `fix-03`) |
| `tokens.effective_est` | `input_est + 4 × output_est` — output tokens are priced several times above input |
| `tokens.actual`, `basis` | the host's token count when the runner recorded it (`cost_tokens` artifact): `basis: host`; otherwise `basis: estimate` |
| `minutes`, `model`, `effort` | from the journal: stage spans and the role's model |

**Reads model.** What each stage puts through the model is derived from the artifacts, so the
measurement sees the savings of the later specs as they land: writing reads the spec; revision reads
the plan once per review, or, for a review with `**Audit scope**: incremental`, the plan's header plus
the tasks named in `**Audit tasks**`; split reads the plan and its parts, or only the task list
(≈ 300 bytes per task) when the stage recorded `split_method=script`, nothing when skipped; execution
reads the parts of a roadmap run, else the plan; audit reads the plan (the skeleton, `plan × (1 −
code_share)`, once plan-writing's `skeleton` exists) and the earlier reports on every full pass, and
for a report with `audit_scope: incremental` the header plus the tasks of `audit_tasks` plus the
evidence files of its fingerprint table; diffs and commit read nothing. Where a scope cannot be
resolved (no task list, an unknown id) the pass counts as full with `scope-unresolved`. The cache is
not modelled: it does not carry between agents, and inside one agent it is not observable from the
artifacts.

**Host facts.** In the `claude-code` profile the runner must record the token usage of every agent it
launched (the token count in the usage block of the `Agent` result; PROFILES.md marks the field name `subagent_tokens` as unverified) and add it to the stage's running total, so `cost_tokens` is the sum over all agents of the stage (repeats and re-entries included), not the cost of the last one; a stage with a fact has `basis: host`. Estimates and
facts are not directly comparable: `--baseline` warns `basis-mixed: <stage>` when the two sides of a
stage differ, and the checkpoints below compare like with like.

Quality travels with cost: `quality.audit_status` and `audit_issues` (the last resolver report),
`reviews` and `review_remaining`, `unit_retries`, `failed_stages`. A saving that worsens these is
not a saving.

Token estimates are estimates. Token count is a weak proxy of billed cost in tool-heavy agents;
compare *cost per closed plan*, and read the deltas per task and per KB of plan when plans differ
in size.

## Commands

```bash
python skills/plan-chain-runner/scripts/chain_tool.py run-stats <goal>-chain.json            # a chain run
python skills/plan-chain-runner/scripts/chain_tool.py run-stats --plan docs/plans/x-impl.md   # a plan folder, no durations
python skills/plan-chain-runner/scripts/chain_tool.py run-stats <journal> --baseline before.json --json-out after.json
```

`--baseline` adds `delta` (absolute, per task, per KB of plan) on the totals and per stage;
`minutes` deltas exist only when both sides have durations. `--json-out` is the command's only
write; do not point it inside a working copy while a chain runs (the executor would see a foreign
change). `run-status` carries the same totals as `cost`, and the runner's summary prints them as
the "Volume" line.

## Baseline (2026-10-04, before the refactoring)

`docs/.plans` is not part of the repository, so the numbers are recorded here. All of them are
estimates (`basis: estimate`): no host fact was recorded before this command existed.

| Run | Tasks | Plan | Parts | Reviews | Reports | Effective tokens (est.) | Minutes |
|---|---|---|---|---|---|---|---|
| `fix-03-impl` (plan mode) | 91 | 550955 bytes, code share 0.535 | 8 parts, 611903 bytes (+ roadmap 5440) | 3 (69138 bytes) | 1 open (60089 bytes) | 2866596 | — |
| `plan-chain-runner-2-impl` | 77 | 519247 bytes, code share 0.595 | 6 parts, 578530 bytes (+ roadmap 5406) | 3 (98082 bytes) | 1 final (45360 bytes) | 3219073 | writing 98, revision 375, execution 73, audit 13 |
| `plan-chain-followups-3-impl` | 14 | 77827 bytes, code share 0.513 | — | 1 (12003 bytes) | 1 final (9030 bytes) | 285197 | 59 / 12 / 53 / 12 |
| `plan-chain-x-m-impl` (journal) | 12 | 80490 bytes, code share 0.594 | — | 1 (10269 bytes) | 1 final (7437 bytes) | 342659 | 13 / 7 / 22 / 9 |

Sizes, task counts and effective tokens come from `run-stats --plan <plan>` (the same numbers as journal mode, which adds the minutes). Minutes are writing / revision / execution / audit from the stage spans of `plan-chain-runner-chain.json`: `run-stats <journal>` reports only the plans of the runner's current `specs` (`plan-chain-x-m-impl` in that journal), so the minutes of the three earlier plans were read from the same journal with the command's journal layer over all of its plans. `fix-03` has 91 tasks outside code fences (`plan-check` agrees); a plain grep finds 93 because the plan quotes a two-task fixture plan inside a fenced block.

Sizes are UTF-8 bytes as `run-stats` counts them; the research report counts characters (487 KB and 529 KB for `fix-03`); for this Russian-language plan the byte count is 13 % higher.

Where the tokens went in `fix-03`: the parts are a verbatim copy of the plan (all code lines of the
plan appear in the parts byte for byte), the three reviews each re-read the whole plan, the audit
re-read the plan and traced every task. The research report of the refactoring
(`plan-refactoring-01-research.md`, section 2) has the details.

## Checkpoints

The measurement set of the refactoring is the refactoring itself: the specs of `plan-refactoring-01`
run through the chain one after another. After the `commit` of each spec, the runner (LOOP.md, End)
or the user runs `run-stats <journal> --json-out <temp dir>/<spec>.json` and copies the totals into
this table (one row per spec; `basis` says whether the row is a host fact or an estimate).

| Spec | Tasks | Plan KB | Effective tokens | Basis | Minutes | Audit | Notes |
|---|---|---|---|---|---|---|---|
| 1 | | | | | | | first row with `run-stats` itself |

Mandatory comparisons, by the criteria of "Что считать успехом" in the research report:

- after spec 3 (split by script): `stages.split.bytes_written` unchanged, `bytes_read_est` of the split
  stage and the model's own output down to the task list;
- after spec 6 (incremental resolver): on goals with two or more resolver passes, `stages.audit`
  output tokens down; input tokens down from the second FIX cycle on (one cycle is not cheaper);
- after spec 8 (cheap models): `quality.delegated` retries no higher than the rest and the audit
  issues of delegated units not growing; otherwise `light` stays an option.

Spec 5 (incremental revision) is judged on goals with two or more reviews and on output tokens. With
one cycle of edits it costs the same or about 10 % more than before (a full audit, an incremental one
and the closing full audit against two full audits); the saving starts with the second cycle: on
`fix-03` audits 2 and 3 would read about 25–40 thousand input tokens each instead of about 160 thousand,
with a third of the cross-checks, and the reviews' output shrinks from the first incremental pass on.
`run-stats` counts an incremental review as the plan's header plus the tasks of `**Audit tasks**`; the
resolver's issue counts on the next goals (`quality`) show whether the quality held. Spec 7 (skeleton):
`plan_tool.py skeleton docs/.plans/fix-02/fix-03-impl.md` is 43.1 % of the plan in characters (209519
of 486598; the research report counts characters) and 47.6 % in UTF-8 bytes (262390 of 550955: the
prose it keeps is Cyrillic, two bytes a letter, while the code it drops is mostly ASCII); with
`--code none` 40.7 % and 45.6 %. `run-stats` models a full resolver pass as `plan × (1 − code_share)`,
46.5 % of the bytes on `fix-03`, close to the measured 47.6 %. `validate-report` keeps the old
`fix-03-impl-report-1.md` valid and warns 55 × `verbose-closed-task` and 53 × `too-many-anchors`.

Spec 6 (incremental resolver) is judged the same way: on goals with two or more resolver passes and on
output tokens. With one FIX cycle the incremental audit after the fix comes on top of the closing full
pass, so the input is not lower than today's single full audit after FIX; the input saving starts with
the second cycle (`auto` with several cycles, repeated `fix`/`next`). The output drops at once: the
model writes only the re-audited lines and `carry-forward` copies the rest (on `fix-03` the stages
section of report 1 is about 53 KB). The reads model counts an incremental report as the plan's header
plus the tasks of `audit_tasks` plus every file of its evidence table; on `fix-03` that table names 54
files of 1.34 MB, more than the plan (551 KB), so until the model counts only the changed files
(BACKLOG, section `plan-refactoring-01`) `bytes_read_est` overstates an incremental pass, and the
comparison uses `bytes_written` and the output tokens.

## How to compare

1. Before a change: `run-stats <journal> --json-out before.json` on a finished run of a reference
   goal (or `--plan` on its plan).
2. After the change, on the next real run of a goal of the same class: `run-stats <journal>
   --baseline before.json`.
3. Read `delta.totals.effective_tokens_est.per_task` and `.per_kb`, then `quality`: accept the change
   only when the audit status and the issue counts are no worse. A `basis-mixed` warning means the two
   sides were measured differently: compare the estimates of both (`tokens.*_est`) instead.

## Size budgets

One plan's budget is 40 tasks or 150000 bytes (`SIZE_BUDGET` in `skills/plan-brainstorming/scripts/brainstorm_tool.py`). `spec-check` estimates a spec's volume before any plan exists: `estimate_tasks = components × k + testing_items`, k = 1 (Quick), 2 (Standard), 3 (Deep); `over_budget` above 40 tasks makes `plan-brainstorming` propose several specs of one goal. `plan-check` returns `size_class` (`small` ≤ 15 tasks, `large` over the budget, else `medium`) and warns `plan-oversized`; the splitter gate uses the same 40 tasks / 150000 bytes. Every stage costs in proportion to the plan's size and the revision more than linearly, so the budget is held before the plan is written.

### Calibration

The estimate is a formula, not a measurement. After each spec of a goal is planned, add a row: the tier and estimate from `spec-check`, the plan's `task_count` from `plan-check`, and the deviation `(task_count − estimate) / estimate`. Change the tier factors only when several goals deviate the same way; `run-stats` of the same plans shows what the deviation cost.

| Spec | Tier | estimate_tasks | task_count | Deviation |
|---|---|---|---|---|
| plan-refactoring-01-1 | Standard | 29 | 17 | −41% |
