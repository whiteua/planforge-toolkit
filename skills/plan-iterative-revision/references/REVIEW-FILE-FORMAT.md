# Review File Format

`TOOL record` renders every `<basename>-review-<N>.md` and validates it with
`validate-review --strict-fingerprint` before returning. This document describes that format for
readers and for the validator. Other skills depend on it: `plan-splitter verify-status` runs the
same validator on new review files.

## File name

`<dir>/<basename>-review-<N>.md`. `N` is the highest existing number plus one; gaps are allowed.
Review files are immutable history once written.

## Layout

```markdown
# Revision N: <basename>            (Ревизия N: ... for Russian plans)

**Iteration**: N
**Audited plan**: <basename>.md
**Plan SHA-256**: <64 hex>
**Plan size**: <bytes> bytes
**Plan git blob**: <hash>           (only inside a git repository)
**Audited at**: <ISO-8601 UTC, e.g. 2026-05-09T12:34:56Z>
**Previous review**: <basename>-review-<N-1>.md | none
**Audit scope**: full | incremental
**Audit tasks**: all | <task ids of an incremental audit, comma-separated> | none
**Budget**: off — oversized before revision (<bytes> bytes > 150000)   (only when the plan was over the budget before Phase B)
**Code changed tasks**: <ids of the tasks whose Files changed on disk since the previous review> | none   (with the Task digest)
**Issues found**: <total> (blocker: x, major: y, minor: z, nit: w)
**Flow**: +new / -resolved / P persisted / X reintro | Profile: (B,M,m,n)
**Status**: FINAL — ... | ESCALATED — ...   (only on a final review)

## Audit state

| Check | Status | Notes |
|---|---|---|
| Previous review contracts checked | yes/no/n-a | ... |
| Taxonomy sweep completed | yes | 10 classes |
| Code cross-check completed | yes | ... |
| Review validated | yes | validate-review --strict-fingerprint |
| Deferred conflicts carried | <count> | <review#id, ...> |
| Lenses used | <L> | |

## Summary

<1-3 sentences>

## Issues

### [N.1] <severity> · <category> · <title>

- **Location in plan**: <section>
- **Location in code**: <file:line> | n/a
- **Code cross-check**: verified | not found | ambiguous | not applicable — <reason>
- **Carried from**: <basename>-review-<M>.md#<M.k>    (only for carried issues)
- **Problem**:
  <text>
- **Evidence**:                                        (optional)
  <quotes>
- **Required fix (contract)**:
  <what the plan must say after the fix>
- **Acceptance**:
  <how to verify the fix>
- **Fingerprint**: <8 hex>

## Deferred from previous review

- [N.k] carried from <review#id> | none
- [M.j] deferred: budget            (an issue of the previous review its Phase B deferred for the budget; record --deferred)

## Notes for implementation

<text> | none

## Task digest                      (with plan-brainstorming alongside and a plan with task headings)

| Task | Hash |
|---|---|
| 1 | 9f3c2a1b |
| 1.1 | 0e77ad21 |

## Code digest                      (with the Task digest)

| Path | Hash |
|---|---|
| skills/x/scripts/tool.py | 3f9a0c21b7e4 |
| skills/x/scripts/new.py | missing |
```

## Rules

- Issues are ordered by severity (blocker → major → minor → nit), then by input order. Ids are
  `N.k`, starting at 1.
- Multi-line field bodies are indented by two spaces, so their content cannot end a field early.
- Fingerprint: SHA-1 of `<category lowercase>\n<first 200 chars of the whitespace-normalized
  required fix>`, first 8 hex characters.
- Severity: `blocker`, `major`, `minor`, `nit`. Category: `logic`, `code`, `math`, `ops`, `db`,
  `contract`, `tests`, `security`, `perf`, `code-plan-mismatch`, `unfulfilled-contract` (legacy).
- `Audit scope`/`Audit tasks`: `full`/`all` for a full audit (always without plan-brainstorming
  alongside), `incremental` with the `--tasks` ids of `record` (`none` for an empty list). plan-chain-runner's
  `run-stats` reads both to count what the audit read.
- `## Task digest`: every `### Task N:` of the audited plan, its id as the shared parser writes it (normalised: `01` = `1`) and the first 8 hex of the
  SHA-1 of its body (`brainstorm_tool.parse_plan_tasks`). The next `digest` compares it with the plan to
  scope the next audit. There is no table without plan-brainstorming, for a plan without tasks or with
  repeated task ids.
- `**Budget**` (spec 1 of plan-refactoring-04): written by a `record` with `action: implement` when the plan was over
  the budget of 150 000 bytes before Phase B (`limit: off`); a plan with room has no such line.
- `**Code changed tasks**`: written with the Task digest; the tasks whose Files paths changed state on disk against the
  `## Code digest` of the run's previous review (`none` on the first audit or without that table).
- `## Code digest`: every distinct path of the Files blocks of the plan's tasks (the first name of an action line, two
  for `Move:`), relative to the git root (outside git, the current directory), with the first 12 hex of its SHA-256
  or a state: `missing`, `unreadable`, `dir`, `glob` (a `*`), `outside` (absolute or `..`). The next `digest` puts
  the tasks of a path whose state changed, and their dependents, into the audit (`code_changed`); `dir`, `glob` and
  `outside` never count. A row of another shape is skipped.
- `[N.k] deferred: budget` under `## Deferred from previous review`: one line per id of `record --deferred`; the issue
  stays open (carried when the audit left it out).

## Status markers

| Marker | Written when |
|---|---|
| `FINAL — implementation skipped by user` | the user chose "stop" at the limit question |
| `FINAL — iteration limit reached` | autonomous run hit `max` |
| `FINAL — only nit issues remain (pragmatic stop)` | `drain` gate |
| `FINAL — audit-only mode, Phase B not run` | `audit-only` mode |
| `FINAL — no progress between iterations` | `unchanged` or `churn` gate |
| `ESCALATED — stuck issue needs manual decision` | `regression` or `stuck` gate |

Phase B never runs on a review that has a `Status` line.

## Validator checks

Required headers and sections; severity, category and `Code cross-check` vocabulary; unique ids;
issue count and per-severity counts against `Issues found`; `Required fix`, `Acceptance` and an
8-hex `Fingerprint` in every issue; with `--strict-fingerprint`, each fingerprint recomputed. The
`Audit scope`/`Audit tasks` headers and the `## Task digest` table are optional; a table row that is
not `| <id> | <8 hex> |`, a repeated id or an empty table gives the warning `task-digest-malformed`,
never an error, so `plan-splitter verify-status` is not affected.
