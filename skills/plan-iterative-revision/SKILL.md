---
name: plan-iterative-revision
description: |
  Use when a written implementation plan must be audited against the actual codebase and fixed
  iteratively: each pass records issues in a new immutable review file, applies them to the plan,
  and repeats until the plan is clean or a stop gate fires. Not for reviewing code or executing plans.
allowed-tools:
  - Read
  - Grep
  - Glob
  - Edit
  - Write
  - Bash
  - Agent
---

# Plan Iterative Revision

A two-phase loop over one master plan: **Phase A** audits the plan against the codebase,
the helper script records the issues as `<basename>-review-<N>.md`; **Phase B** applies that
review to the plan. It repeats until a stop gate fires. All bookkeeping (numbering, fingerprints,
gates, review rendering, validation) is done by the script; you do the audit and the edits.

## Inputs

- `PLAN` (required): path to the master plan, e.g. `docs/plans/plan01-impl.md`, or a plan-splitter
  roadmap `<base>-roadmap.md` (batch mode, see below).
- `parts`: batch mode only; a comma-separated list of part ids to verify (default: all).
- `mode`: `full-cycle` (default) or `audit-only` (the user asks for "only audit", "only a review",
  "don't implement"): one audit, one review file, no Phase B.
- `preset`: `quick` | `standard` (default) | `deep`. Sets `lenses` 1/2/4, `rigor`
  `grep`/`read`/`explore`, `max` 3/5/7. `lenses`, `rigor`, `max` can be overridden one by one.
- `stop_policy`: `pragmatic` (default; stop when only `nit` issues remain) | `strict`.
- `interaction`: `auto` (default) | `interactive` | `autonomous`. `auto` means `interactive` when a
  question tool (AskUserQuestion, vscode_askQuestions, ...) is available, otherwise `autonomous`.
  Callers such as `plan-splitter` run you as a subagent: that is `autonomous`.

## Tool

`TOOL` = `python "<SKILL_DIR>/scripts/next_review_index.py"`, where `<SKILL_DIR>` is the directory
containing this file (not the user's project). Always call it by absolute path. Python ≥ 3.8,
stdlib only. If `python` is unavailable, stop and tell the user.

## Hard invariants

1. Phase A edits no file. Only `TOOL record` writes the review or completion file.
2. Phase B edits only `PLAN`: never the review files, never project code.
3. Never modify code, never run the project's tests/builds/linters/migrations, never create
   plan copies, branches or commits.
4. There is no substitute for the review file: not memory, not chat, not edits to the plan.
   If `bootstrap` reports `valid: false`, stop before auditing and tell the user which directory
   is not writable.
5. Gate decisions come only from `record`. Never continue after `action: "stop"` and never stop
   on your own while it says `implement` (except when the user interrupts).
6. Wrap each phase in the diff guard when `git_root` is not null.

## Batch mode (a plan-splitter roadmap)

If `PLAN` ends with `-roadmap.md`, verify its parts one after another:

```
P = TOOL parts PLAN                      # parts in table order; exit 1 if a part file is missing
parts = P.parts filtered by the `parts=` argument if given (ids like a,c), else all
finals = {}
for part in parts:
    run the Loop below with PLAN = part.path (its own reviews, completion file and guard labels)
    finals[part.id] = R.final
S = TOOL batch-summary --results <json {"parts": finals}>   # worst result wins
```

Print `S` as the final output (autonomous), or a per-part table plus `S` (interactive). Never
verify parts in parallel: the diff guard and the review numbering are per plan, not per run.

## Loop

```
MODE = full-cycle | audit-only; I = interactive | autonomous   (resolved from Inputs)
B = TOOL bootstrap PLAN [--preset P] [--lenses L] [--rigor R] [--max M] [--stop-policy S]
if not B.valid: report B.error / B.errors and stop
if I == interactive and the user gave neither preset nor stop_policy:
    ask once to confirm preset + stop_policy (then no more questions until the limit gate)
MAX = B.config.max; S = B.config.stop_policy; k = 1

loop:
    TOOL guard-begin B.git_root <B.basename>-phase-a
    if k > 1: D = TOOL digest B.dir B.basename --since B.run_start
    Phase A (references/PHASE-A-AUDIT.md) → issues JSON, saved to a file in the OS temp dir
        (never inside the repository), or piped on stdin with --issues -
    R = TOOL record PLAN --run-start B.run_start --max MAX --stop-policy S --mode MODE
                    --interaction I --lang B.lang --issues <json-file>
    if R.action == "ask_limit":  ask "MAX review passes done, N issues still open. Continue?"
                                 options +3 / +5 / stop.
                                 +n → MAX += n and re-run the same record command;
                                 stop → re-run it with --user-stop
    TOOL guard-check B.git_root <B.basename>-phase-a <R.review_path or R.completion_path or B.next_review>

    if R.action == "stop":       go to Final output
    if R.action == "implement":
        TOOL guard-begin B.git_root <B.basename>-phase-b
        Phase B (references/PHASE-B-IMPLEMENT.md) on R.review_path, issues in R.issues order
        TOOL guard-check B.git_root <B.basename>-phase-b PLAN
        k += 1
```

`MAX` limits the number of reviews that go to Phase B in this run: with `MAX = 5`, audits 1-5 can
be implemented and audit 6 hits the limit gate if issues remain.

A `guard-check` violation means a phase touched a forbidden file: stop and report the paths.
The guard sees only what `git status` sees (not ignored files, not paths outside the repository).
Without git, say that the guard is unavailable and list the files you changed yourself.

## Stop gates (decided by `record`, first match wins)

| Gate | When | result | stop_reason | File written |
|---|---|---|---|---|
| clean | no issues on the first audit | `clean` | null | none |
| converged | no issues on a later audit | `converged` | null | completion file |
| user stop | `--user-stop` after the limit question | `limit` | null | review, `FINAL` |
| audit-only | `--mode audit-only` | `converged` | null | review, `FINAL` |
| drain | `pragmatic` and every issue is `nit` | `converged` | `drain` | review, `FINAL` |
| regression | audit ≥ 3 and an issue resolved earlier in this run is back | `escalated` | `regression` | review, `ESCALATED` |
| unchanged | same fingerprint set as the previous audit | `stagnation` | `unchanged` | review, `FINAL` |
| churn | audit ≥ 3, new issues but nothing resolved for 2 audits | `stagnation` | `churn` | review, `FINAL` |
| stuck | a fingerprint in 3 consecutive audits | `escalated` | `stuck` | review, `ESCALATED` |
| limit | audit number > `MAX` | `limit` (autonomous); interactive gets `action: ask_limit` | null | review, `FINAL` (autonomous) |

History is limited to the current run (`--run-start`); reviews from earlier runs are archive.
The pragmatic `drain` never hides real problems: it fires only when every open issue is `nit`.

## Final output

- `autonomous`: no progress messages; the final message is exactly one JSON object, `R.final`
  (schema `assets/result.schema.json`: `result`, `iterations` = review files written in this run,
  `remaining_issues`, plus `escalated`, `stop_reason`, `flows`, `lenses_used`).
- `interactive`: a short report in the plan's language: result and reason, review files created
  in this run, remaining or escalated issues (id + title), the completion file if written. Add the
  `R.final` JSON at the end.

## Language

All artifacts and all issue text are written in the plan's language, `B.lang` (`ru` when more than
5% of letters are Cyrillic, else `en`). Instructions in this skill are in English regardless.

## References

- [references/PHASE-A-AUDIT.md](references/PHASE-A-AUDIT.md): read before the first audit.
- [references/ERROR-TAXONOMY.md](references/ERROR-TAXONOMY.md): the 10 issue classes, used in Phase A.
- [references/PHASE-B-IMPLEMENT.md](references/PHASE-B-IMPLEMENT.md): read before the first Phase B.
- [references/REVIEW-FILE-FORMAT.md](references/REVIEW-FILE-FORMAT.md): the rendered review format.
  You do not need it in a normal run; `record` renders and validates the file.
