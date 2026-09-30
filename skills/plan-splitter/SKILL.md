---
name: plan-splitter
description: |
  Use when an implementation plan is too large for one agent pass and must be decomposed into
  self-contained parts (`<base>-a.md`, `<base>-b.md`, …) plus a dependency roadmap that
  plan-executor runs in order. Never modifies the source plan; optionally verifies the parts
  with plan-iterative-revision.
allowed-tools:
  - Read
  - Grep
  - Glob
  - Edit
  - Write
  - Bash
  - Agent
---

# Plan Splitter

Decomposes one large plan into parts. Each part is a self-contained file an agent can execute
without the original; a roadmap holds the dependency graph. The skill creates the roadmap and
the part files next to the source plan and **never edits the plan itself**.

## Inputs

- `PLAN` (required): path to the plan, e.g. `docs/plans/plan01-impl.md`.
- `verify`: `ask` (default) | `all` | `none` | a part list (`a,c`). Whether to run the deep
  verification of step 8 and for which parts. Non-interactive runs treat `ask` as `none`.
- `verify_depth`: `quick` | `standard` (default) | `deep`: the `preset` passed to
  `plan-iterative-revision`.
- `verify_mode`: `full-cycle` (default) | `audit-only`: whether verification may edit the parts.

Derived: `DIR` = the plan's directory; `BASE` = file name without `.md`;
`LANG` = `TOOL detect-lang PLAN` (`ru` when more than 5% of letters are Cyrillic, else `en`).

## Tool

`TOOL` = `python "<SKILL_DIR>/scripts/splitter_tool.py"`, `<SKILL_DIR>` being the directory of
this file. Always call it by absolute path. Python ≥ 3.8, stdlib only. Step 8 also needs
`plan-iterative-revision` installed next to this skill (`<SKILL_DIR>/../plan-iterative-revision/`);
without it, stop after step 7 and say so.

## Naming

| Artifact | Name |
|---|---|
| Roadmap | `<BASE>-roadmap.md` |
| Parts | `<BASE>-a.md`, `<BASE>-b.md`, … `<BASE>-z.md`, `<BASE>-aa.md`, … (`TOOL part-id N`) |
| Verification snapshot / ledger | `<BASE>-verify-baseline.json`, `<BASE>-verify-ledger.json` |
| Review trail per part (written by plan-iterative-revision) | `<BASE>-a-review-N.md`, `<BASE>-a-completion.md` |

Part ids in the roadmap table are the letters (`a`, `b`, …). plan-executor and plan-resolver
parse the same ids.

## Hard invariants

1. The source plan is never modified; its SHA-256 is the same after the run (`TOOL hash PLAN`).
2. One level of decomposition: parts are not split recursively. A part that is still too large
   gets a note recommending `plan-splitter <BASE>-<id>.md` by hand.
3. Write preflight before generating files; if `DIR` is not writable, stop before analysis.
4. Existing split artifacts for `BASE` are never overwritten without an explicit user choice
   (overwrite / different base / abort).
5. At most two rounds of draft → feedback → redraft; a second rejection ends the run without files.
6. Every part is self-contained: no "see above", "as in the original", "previous section".
7. All generated files are in the plan's language (`LANG`).
8. After step 8 only these files may differ from the pre-run state: roadmap, parts, the two
   verify JSONs, and the review/completion files of the verified parts.
9. A verified part is "done" only when `TOOL verify-status` exits 0. `missing` → one re-dispatch,
   then stop; `inconsistent` → stop immediately; never downgrade to a warning.

## Algorithm

```
1. BOOTSTRAP
   LANG = TOOL detect-lang PLAN
   P = TOOL preflight DIR BASE     # writable? existing split artifacts?
   if not P.writable: stop and report

2. GATE DECISION (references/GATE-DECISION.md)
   Score the 5 factors, tell the user the verdict.
   "do not split" → print assets/gate-pass.<LANG>.md and exit (a normal outcome).

3. ANALYSIS (references/STAGE-FORMAT.md §4-5, references/ROADMAP-FORMAT.md)
   Part boundaries, dependency graph, parallel groups, weights 🔴/🟡/🟢,
   one row per part: id (a, b, …), title, depends, group, weight, summary.

4. DRAFT & CONFIRM
   Show the split table; on rejection with feedback retry step 3 once; on a second
   rejection exit without files. Never generate without explicit confirmation.

5. GENERATE
   if P.existing: ask overwrite / other base / abort.
   Write <BASE>-roadmap.md from assets/roadmap-template.<LANG>.md and one
   <BASE>-<id>.md per part from assets/stage-template.<LANG>.md (names via TOOL stage-name).

6. VERIFY (three levels, at most 3 rounds)
   A/B: TOOL validate-all DIR BASE   # files, sections, DAG, depends, groups, task coverage,
                                     # original hash; also run TOOL validate-stage per part
                                     # for the granularity warning (> 15 tasks)
   C:   re-read every part: self-sufficiency, context, handoff (outputs of X cover the
        inputs of every Y that depends on X), consistency with the roadmap.
   Fix defects and repeat; after 3 failed rounds exit with a warning, files kept.

7. DONE NOTICE / VERIFY CHOICE
   Print assets/verify-prompt.<LANG>.md; resolve scope from `verify` or ask.
   scope = none → print assets/completion.<LANG>.md and exit.
   Otherwise do not announce "done" for the selected parts before step 8 passes.

8. GATED DEEP VERIFICATION (references/DEEP-VERIFY.md)
   TOOL verify-baseline DIR BASE --stages <scope>  > <BASE>-verify-baseline.json
   Run plan-iterative-revision ONCE on <BASE>-roadmap.md (batch mode, autonomous,
   preset=verify_depth, mode=verify_mode, parts=<scope>), sequentially per part.
   TOOL verify-record DIR BASE --results <its batch JSON> --ledger <BASE>-verify-ledger.json --mode verify_mode
   TOOL verify-status DIR BASE --baseline ... --ledger ... --validator <SKILL_DIR>/../plan-iterative-revision/scripts/next_review_index.py --stages <scope>
   exit 0 → print assets/verify-summary.<LANG>.md, then completion.
   missing → re-dispatch those parts once and repeat; still missing or any inconsistent → stop.
```

## References

- [references/GATE-DECISION.md](references/GATE-DECISION.md): split or not.
- [references/STAGE-FORMAT.md](references/STAGE-FORMAT.md): part file format, boundary heuristics,
  content rules.
- [references/ROADMAP-FORMAT.md](references/ROADMAP-FORMAT.md): roadmap format, parallel groups.
- [references/DEEP-VERIFY.md](references/DEEP-VERIFY.md): step 8 in detail (subagent prompt, ledger, gate).
