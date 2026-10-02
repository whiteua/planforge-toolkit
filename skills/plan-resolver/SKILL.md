---
name: plan-resolver
description: |
  Use when a plan has been executed and the implementation must be audited against the code:
  traces every task and previously reported issue to real files and lines, and writes one
  structured report next to the master plan. `fix`/`next` repair the code from the last open
  report and re-audit; `auto` loops audit → fix → audit until the plan closes or a limit is hit.
allowed-tools:
  - Read
  - Grep
  - Glob
  - Write
  - Edit
  - Bash
  - Agent
---

# Plan Resolver

Audits the implementation of a master plan against the code. **AUDIT** is read-mostly: it never
changes code, the plan or past reports, and writes exactly one new report,
`<base>-report-N.md` or `<base>-report-N-final.md`, in the plan's directory; after the read-only
check it records the `audit` stage and the defects outside the plan in the chain journal
`<goal>-chain.json` (which appends them to `BACKLOG.md` at the repository root and exports
`<goal>-followups.json`). **FIX** (modes `fix`/`next`/`auto`) repairs the **code** from an open
report; the plan is never modified. Committing is not the resolver's job: its gate names
`/plan-executor <plan> commit`.

## Modes

The mode is the last argument when it is `fix`, `next` or `auto` (`auto` takes an optional cycle
limit, default `2`).

| Call | Mode |
|---|---|
| `<plan> [reports...]` | **audit**: one audit pass; list the plan first, then earlier reports in order |
| `[<plan>] fix` / `[<plan>] next` | one FIX → AUDIT cycle, then stop |
| `<plan> auto [limit]` | AUDIT → FIX → AUDIT … until `-final` or the limit |

`fix`/`next`/`auto` start with `TOOL discover` (FIX-LOOP.md, "Start"), which builds the report
list; without a plan path, `fix`/`next` take the plan from the conversation or the single plan
with an open last report.

```text
/plan-resolver docs/plan-impl.md docs/plan-impl-report-1.md
/plan-resolver docs/plan-impl.md fix
/plan-resolver docs/plan-impl.md auto
```

## Tool

`TOOL` = `python "<SKILL_DIR>/scripts/resolver_tool.py"`, `<SKILL_DIR>` being the directory of
this file; always call it by absolute path. Python ≥ 3.8, stdlib only. Commands, exit codes and
JSON fields: [references/WORKFLOW.md](references/WORKFLOW.md).

## Read before acting

| When | Read |
|---|---|
| Always | [references/WORKFLOW.md](references/WORKFLOW.md), [references/REPORT-FORMAT.md](references/REPORT-FORMAT.md) |
| Before the audit pass | [references/AUDIT.md](references/AUDIT.md) |
| Modes `fix`/`next`/`auto` | [references/FIX-LOOP.md](references/FIX-LOOP.md) |

## AUDIT phase (summary; WORKFLOW.md is authoritative)

1. `TOOL bootstrap <workspace-root> <plan> [reports...]`: exit `64` means the plan is closed;
   say so and write nothing. Copy `report_header` into the report frontmatter as is.
2. `TOOL preflight <plan-dir> <next-open-name> <next-final-name>`: on failure stop before auditing.
   Then the journal start (WORKFLOW.md, Chain journal): stage `audit` → `running`.
3. Start fingerprint: `TOOL fingerprint-workspace <workspace-root> <start-json>` (temp file outside
   the workspace).
4. One audit pass (AUDIT.md): `first` over the plan, or `subsequent` over the last report plus a
   full re-scan of the plan. Every closed item and every issue carries an evidence anchor
   `path#Lx-Ly` that points at real code; probes are read-only.
5. Report name: `-final` only when there are no issues and every task is `✅` or
   `not-applicable`; otherwise the open name.
6. Write exactly one new report (never overwrite an existing one). Defects outside the plan go
   into its Additional Context and are recorded after step 9 (AUDIT.md, "Defects outside the
   plan").
7. `TOOL task-census <plan> <report>`: exit `1` → add the uncovered tasks to the same report.
8. `TOOL validate-report <report> --root <workspace-root> --plan <plan>`: one rewrite of the same
   report is allowed to fix it; copy every `[WARNING]` line into the report's validator-warnings section.
9. `TOOL fingerprint-workspace <workspace-root> <current-json> --base <start-json>` and
   `TOOL assert-readonly <start-json> <current-json> <report> <BACKLOG.md>` (`BACKLOG.md` only
   when it lies inside the workspace root). Drift → rewrite the same report
   with the single blocker issue `probe-mutated-workspace`, run only the validator again, stop OPEN.
   Then the journal end (WORKFLOW.md, Chain journal): `journal-finding` per defect outside the
   plan, `journal-event` stage `audit` `done` with the report's status, `journal-export-findings`.
10. Human gate: report path, status, counts, next action (audit mode with open issues: suggest
    `/plan-resolver <plan> fix`). Inside `fix`/`next`/`auto` the gate is printed once, when the
    loop stops (FIX-LOOP.md, "Stop and human gate"), not after every audit. If `bootstrap.stuck_open.ask_required` is true and the report
    stayed open, say that five audits in a row ended open and ask how to proceed instead of
    proposing another pass. Every gate also names the commit: `/plan-executor <plan> commit`
    commits the executor run's files and the fixes (the resolver never commits). Without a
    confirmation channel, a decision the gate needs is recorded with `journal-question` before
    stopping, after the `audit` stage was moved back to `running` (`--reason audit-open`) so that
    the question stops it (WORKFLOW.md, Chain journal).

## FIX phase

Only in `fix`/`next`/`auto`, strictly by [references/FIX-LOOP.md](references/FIX-LOOP.md):
`open-issues` → journal stage `audit` → `running` (`--reason audit-open`) → `protect` + fix-start
fingerprint → minimal code changes in `fix_order` → `assert-protected` + `snapshot-diff` (the
authoritative list of changed files) → `mark-fix` per issue → the changed files as `fix_files[]`
in the journal (repository-root paths) → AUDIT → `cycle-check`.

## Language

The report language is `bootstrap.language`: `ru` when more than 5% of the plan's letters are
Cyrillic, otherwise `en` (empty or unreadable plan → `en`). Instructions in this skill are English.

**Dialogue language.** Everything the user sees is in the language of the primary task (the
goal, idea or findings in `plan-brainstorming`, the plan in every later skill): questions, option
labels and option descriptions in a question UI, status lines, confirmations, human gates, final
summaries and stop reports. Only tokens that parsers match stay in English: `### Task N:`,
`**Files:**`, `> Tier:`, command names and JSON field names. Sample phrases quoted in these
instructions ("Spec written to …", "MAX review passes done …", "I'm using the plan-writing
skill …") are templates: say them in the dialogue language, not verbatim. The language is
detected, not guessed: `ru` when more than 5% of the letters are Cyrillic, otherwise `en`.

In this skill: `bootstrap.language`.

## Forbidden

- Editing the master plan, ever.
- Editing past reports except the Fix Log section, and only through `mark-fix`.
- In AUDIT: editing code, configs or generated files; more than one report per pass; overwriting an
  existing `NEXT_REPORT` (rewriting your own report of this pass is allowed).
- In any phase: git mutations (`add/commit/reset/checkout/clean/stash`), dependency install or
  update, migrations, project-wide formatters or autofix. Code changes from FIX stay uncommitted
  in the working tree for the engineer's review.
- Replacing the report file with memory, chat or terminal notes; delegating fixes to other skills.
