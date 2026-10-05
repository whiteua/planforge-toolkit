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

If the only argument is `help`: show this skill's USAGE.md in the dialogue language (without a spec or plan: the language of the user's message; commands and keys as they are) and do nothing else.

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
- Chain settings: `S` = `python "<SKILL_DIR>/../plan-brainstorming/scripts/brainstorm_tool.py" settings PLAN`
  (the plan header, else the spec named by `**Spec:**`). `S.chain.split` decides step 2:
  `always` skips the gate, `never` means the splitter is not needed, `auto` runs the gate. In a
  run without a confirmation channel (a chain run, a subagent call) `verify` defaults to `none`:
  plan-iterative-revision has already audited the whole plan. An interactive run keeps
  `verify=ask` and asks, whatever `S.chain_explicit` says; an explicit `verify` argument always
  wins. With `S.ok` false, run the gate and keep `verify` as given. Without `plan-brainstorming`
  next to this skill nothing can be cut: `gate`, `split-write` and `validate-all` exit `2`
  (`plan-brainstorming not installed alongside`); stop and say so.

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
6. Every part is self-contained: `split-write` copies the plan header and the full text of its tasks
   into it; the fields the model writes (goal, inputs, outputs, notes, criteria) have no "see above",
   "as in the original", "previous section".
7. All generated files are in the plan's language (`LANG`).
8. After step 8 only these files may differ from the pre-run state: roadmap, parts, the two
   verify JSONs, the review/completion files of the verified parts, and the chain journal
   `<goal>-chain.json` with `BACKLOG.md` and `<goal>-followups.json` (written only through
   `brainstorm_tool.py`, Chain journal).
9. A verified part is "done" only when `TOOL verify-status` exits 0. `missing` → one re-dispatch,
   then stop; `inconsistent` → stop immediately; never downgrade to a warning.
10. Task texts are copied by `split-write` byte for byte, so every `**External:**`, `**Size:**` and `**Structural event:**`
    line stays in its task (references/STAGE-FORMAT.md §6); `validate-all` fails when a task body
    (`task_bodies`) or one of these lines is missing. The model never writes task text into a part.

## Algorithm

```
1. BOOTSTRAP
   LANG = TOOL detect-lang PLAN
   S = brainstorm_tool.py settings PLAN   # Inputs, "Chain settings"
   P = TOOL preflight DIR BASE     # writable? existing split artifacts?
   if not P.writable or P.error: stop and report   # plan-incomplete: plan-writing has not finished the plan
   journal start: stage split → running (Chain journal below)

2. GATE DECISION (references/GATE-DECISION.md)
   S.chain.split == always → verdict "split" without the gate; say it comes from the settings.
   S.chain.split == never  → the splitter is not needed: without a confirmation channel exit
                             without files; interactively ask whether to split anyway.
   otherwise: G = TOOL gate PLAN; tell the user the verdict with G.reasons.
     exit 1 no-tasks → journal: split skipped (why: no-tasks); exit without files (a roadmap
                       for a plan without task headings is written by hand).
     keep            → journal: split skipped (why: gate); print assets/gate-pass.<LANG>.md, exit.
     split           → step 3.
     borderline      → with a confirmation channel decide from T (step 3) alone, never from the plan
                       text; without one take G.silent_verdict (keep within 40 tasks / 150 000 bytes,
                       else split), no question; "keep" as above.

3. ANALYSIS (references/STAGE-FORMAT.md §4-5, references/ROADMAP-FORMAT.md)
   T = python "<SKILL_DIR>/../plan-brainstorming/scripts/brainstorm_tool.py" plan-tasks PLAN
   # ids, titles, files, refs, sizes: the only view of the plan; do not read the plan itself.
   Group T's tasks into parts: ids a, b, … in order, title, depends, parallel group, weight
   🔴/🟡/🟢, goal, inputs, outputs, notes, optional criteria. A task's refs never point into a
   later part, nor into a part its own part does not depend on (directly or through others).

4. DRAFT & CONFIRM
   Write the boundaries as parts.json (references/STAGE-FORMAT.md §6) in a temp folder outside
   the repository. In a dialogue show the split table (id, title, tasks, depends, group, weight);
   on rejection with feedback retry step 3 once; on a second rejection exit without files.
   In a dialogue never generate without explicit confirmation. Without a confirmation channel
   (a chain run, a subagent call) there is nothing to confirm: no table, no question; parts.json
   goes straight to step 5, and the table reaches the journal as `parts_table` (Split done).

5. GENERATE
   R = TOOL split-write PLAN --parts <parts.json>
   exit 1 exists → ask overwrite (repeat with --force) / other base / abort (invariant 4).
   exit 1 boundary errors (tasks-*, part-ids-not-sequential, unknown-dependency, dependency-cycle,
   group-conflict, dependency-order, missing-depends) → fix parts.json and repeat; nothing was written.
   R.warnings (subtask-separated, lines-outside-tasks) → mention them in the parts' notes when they
   matter for the executor; never edit task text. Lines outside parsed task bodies are copied into
   the part after their task, but an executor unit's text is the parsed body only: name such lines
   in the notes of their part.

6. VERIFY (at most 3 rounds)
   A/B: TOOL validate-all DIR BASE   # files, sections, DAG, depends, groups, task coverage (equal),
                                     # task bodies byte for byte (task_bodies), External/Size lines,
                                     # original hash; also TOOL validate-stage per part
                                     # for the granularity warning (> 15 tasks)
   C:   handoff only, from parts.json: the outputs of X cover the inputs of every Y that depends
        on X. No part is re-read.
   A failure: fix parts.json, split-write --force, repeat; after 3 failed rounds exit with a
   warning, files kept.

7. DONE NOTICE / VERIFY CHOICE
   Scope comes from `verify` (`none` by default without a confirmation channel, see Inputs);
   only when it is `ask` (interactive), print assets/verify-prompt.<LANG>.md and ask.
   scope = none → journal: split done; print assets/completion.<LANG>.md and exit.
   Otherwise do not announce "done" for the selected parts before step 8 passes.

8. GATED DEEP VERIFICATION (references/DEEP-VERIFY.md)
   TOOL verify-baseline DIR BASE --stages <scope> --out DIR/<BASE>-verify-baseline.json
   Run plan-iterative-revision ONCE on <BASE>-roadmap.md (batch mode, autonomous,
   preset=verify_depth, mode=verify_mode, parts=<list> unless the scope is all), sequentially per part.
   TOOL verify-record DIR BASE --results <its batch JSON file> --ledger DIR/<BASE>-verify-ledger.json --mode verify_mode
   TOOL verify-status DIR BASE --baseline ... --ledger ... --validator <SKILL_DIR>/../plan-iterative-revision/scripts/next_review_index.py --stages <scope>
   exit 0 → (full-cycle: TOOL validate-all DIR BASE --skip-task-bodies, the parts were edited) → journal: split done → print assets/verify-summary.<LANG>.md, then completion.
   missing → re-dispatch those parts once and repeat; still missing or any inconsistent → stop.
```

## Chain journal

`J` = `python "<SKILL_DIR>/../plan-brainstorming/scripts/brainstorm_tool.py"`; without
`plan-brainstorming` alongside there is no journal (say so once). The stage is `split`;
`<journal>` and `P` = the `journal` and `plan` fields of `J journal-path PLAN --create`. Every
`--plan` below is `P`.

- **Start** (step 1, after preflight): `J journal-show <journal> --plan P`, stage `split`
  (`unknown-plan`, exit `2`: no event of this plan yet, every stage is `pending`):
  `pending`, `failed`, `running`, `stopped` without open questions → `J journal-event <journal> --skill plan-splitter --plan P --stage split --status running`.
  `stopped` with open questions → with a confirmation channel ask each and record
  `J journal-answer <journal> <Qn> --answer "<answer>"`; without one stop and name the ids.
  Answered questions: apply each, `J journal-answer <journal> <Qn> --applied`, then `running`
  (the step-8 question: "accept the parts as they are" → at once the **Split done** event below,
  no new split; "fix the parts by hand" → step 8 again; "split again" → a new split from step 1).
  `done` → first the drift check: `J journal-reconcile <journal>`, then look in the journal
  file's `questions` for one of plan `P` whose text starts with `drift: split` and that is not
  `applied` (the plan changed after the split). `open` → with a confirmation channel ask it
  (split the changed plan again, or keep the parts) and record
  `J journal-answer <journal> <Qn> --answer "<rewrite | keep>"`; without one stop and name the id.
  Answered `rewrite` → `J journal-event <journal> --skill plan-splitter --plan P --stage split --status running --reason drift`,
  split as usual, and after the stage's `done` event `J journal-answer <journal> <Qn> --applied`.
  Answered `keep` → `J journal-answer <journal> <Qn> --applied`, then
  `J journal-event <journal> --skill plan-splitter --plan P --stage split --status done --input PLAN`
  (the same status: it binds the stage to the current plan without a new split), then as without
  drift. No such question, or `skipped` → say that the split was already decided (`roadmap`,
  `parts` in the stage's artifacts, read from the journal file itself: the `plans` entry with
  `id` P, `stages.split.artifacts`; `journal-show` returns statuses only) and name
  `plan-executor`; stop.
- **No split** (the gate's verdict "do not split", `S.chain.split == never` without a
  confirmation channel, or the user's "do not split" at the `never` question):
  `J journal-event <journal> --skill plan-splitter --plan P --stage split --status skipped --data '{"why": "<gate | no-tasks | split=never | user>"}'`
  (`no-tasks`: `gate` exit `1`, the plan has no `### Task N:` headings).
- **Split done** (step 7 with `scope = none`, or step 8 after `verify-status` exit 0):
  `J journal-event <journal> --skill plan-splitter --plan P --stage split --status done --input PLAN --artifact roadmap=<BASE>-roadmap.md --artifact parts[]=<BASE>-a.md --artifact parts[]=<BASE>-b.md ... --artifact split_method=script --artifact "parts_table=<id>: <title> — tasks <ids>; depends <ids>; group <g>; weight <w> | …"`
  (one `parts[]` per part; paths relative to the journal's directory, forward slashes;
  `split_method=script` tells `chain_tool.py run-stats` that the stage read the task list, not the plan; `parts_table` is the split table of step 4 as one string, the parts separated by ` | ` and `depends —` for none: each event replaces it, so a new split after drift leaves no row of the old one). The batch
  verification of step 8 belongs to this stage: plan-iterative-revision writes no stage events on
  a roadmap.
- **No usable split** (second rejection of the draft, step 6 failing after 3 rounds):
  `--status failed --data '{"why": "<what happened>"}'`; a later run retries.
- **A stop in step 8** (parts still missing or inconsistent after the verification) needs a
  person's decision, not a retry: without a confirmation channel
  `J journal-question <journal> --skill plan-splitter --plan P --stage split --text "<the parts and their result>" --option "<fix the parts by hand and re-run the verification>" --option "<accept the parts as they are>" --option "<split again>"`
  (the stage becomes `stopped`), `J journal-export-findings <journal>`, stop with a short report;
  with one, ask as usual and record it with `--answer "<answer>"`.
- **Questions**: a decision the settings do not make (split anyway at `never`, overwrite existing
  artifacts, verification scope) without a confirmation channel →
  `J journal-question <journal> --skill plan-splitter --plan P --stage split --text "<question>" [--option "<option>"]...`
  (the stage becomes `stopped`), `J journal-export-findings <journal>`, stop with a short report.
  Asked interactively, the same command with `--answer "<answer>"` records it.
- **Errors**: `journal-corrupt` (exit `2`) → say it, propose `J journal-reconcile <journal> --rebuild`,
  continue without the journal; `journal-locked` (exit `1`) → repeat once; still locked: with a
  confirmation channel ask whether to continue without the journal, without one stop with a
  short report; `journal-write-failed` (exit `1`, the file system refused the write, e.g. a
  read-only journal) → say it in one line with the error text and continue without the journal.

## Language

**Dialogue language.** Everything the user sees is in the language of the primary task (the
goal, idea or findings in `plan-brainstorming`, the plan in every later skill): questions, option
labels and option descriptions in a question UI, status lines, confirmations, human gates, final
summaries and stop reports. Only tokens that parsers match stay in English: `### Task N:`,
`**Files:**`, `> Tier:`, command names and JSON field names. Sample phrases quoted in these
instructions ("Spec written to …", "MAX review passes done …", "I'm using the plan-writing
skill …") are templates: say them in the dialogue language, not verbatim. The language is
detected, not guessed: `ru` when more than 5% of the letters are Cyrillic, otherwise `en`.

**Free backlog.** `BACKLOG.md` at the repository root is a free file: the user writes to it at any moment, and no stage treats a change to it as a foreign change.

In this skill: `LANG` from `TOOL detect-lang PLAN` (see Inputs).

## References

- [references/GATE-DECISION.md](references/GATE-DECISION.md): split or not.
- [references/STAGE-FORMAT.md](references/STAGE-FORMAT.md): part file format, boundary heuristics,
  content rules.
- [references/ROADMAP-FORMAT.md](references/ROADMAP-FORMAT.md): roadmap format, parallel groups.
- [references/DEEP-VERIFY.md](references/DEEP-VERIFY.md): step 8 in detail (subagent prompt, ledger, gate).
