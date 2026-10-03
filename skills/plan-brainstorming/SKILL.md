---
name: plan-brainstorming
description: "Use before implementing a new feature, component, or behavior change that needs design decisions. Explores intent, requirements and trade-offs through one-question-at-a-time dialogue and produces an approved spec for plan-writing. Also use when given a JSON list of code-review findings (file, line, summary, failure_scenario) to design their fixes. Also use with the shared BACKLOG.md to turn its unchecked items into the next spec."
---

# Brainstorming Ideas Into Designs

If the only argument is `help`: show this skill's USAGE.md in the dialogue language (without a spec or plan: the language of the user's message; commands and keys as they are) and do nothing else.

Turn ideas into approved designs and specs through collaborative dialogue:
understand the project context, ask questions one at a time, present the
design, get approval, write the spec, hand off to `plan-writing`.

References are read at the step that needs them: `references/depth-tiers.md` at step 2,
`references/clarify-checklist.md` at step 7, `references/spec-contract.md` (spec structure,
naming, hand-off) at step 6 before presenting the design, `references/findings-input.md`
before step 1 in findings mode.

<HARD-GATE>
Do NOT invoke any implementation skill, write any code, scaffold any project, or take any implementation action until you have presented a design and the user has approved it. This applies to EVERY project regardless of perceived simplicity.
</HARD-GATE>

## Anti-Pattern: "This Is Too Simple To Need A Design"

Once this skill runs, every request goes through the process: a todo list, a single-function utility, a config change. "Simple" projects are where unexamined assumptions cause the most wasted work. The design can be a few sentences, but you MUST present it and get approval.

## Input Modes

- **Idea** (default): a goal file path or an inline description.
- **Findings**: a JSON array of code-review findings (`file`, `line`,
  `summary`, `failure_scenario`), as a `.json` path or pasted inline. Read
  `references/findings-input.md` before step 1. Findings are the problem
  statement, not the design. "Here are the bugs, just fix them" still needs
  an approved spec.
- **Backlog**: `/plan-brainstorming BACKLOG.md [section]`. Run `backlog-parse <file>
  [--section <section>]`; the unchecked items are the problem statement. Before the first
  question, run the backlog sweep (see Backlog sweep): items an approved spec already covers
  are checked off after the user confirms and are not offered again. The first question is
  which of the remaining items go into this spec (multiple choice, one option per item). Never
  edit BACKLOG.md lines by hand: after the user approves the spec file, `backlog-mark` checks
  off the items the spec took in (see Backlog).
- **Amend**: `/plan-brainstorming <…>-spec.md`, an existing spec (the file name ends in
  `-spec.md` and the file has a `# Goal` heading). Change that spec in place; see Amend mode.

## Language

These instructions are in English. Talk to the user and write the spec body
in the language of the input (goal file, idea, or findings): Russian input
gives a Russian dialogue and spec. The `> Tier:` line and the 8 contract
headings stay in English verbatim, because `plan-writing` and `spec-check`
match them literally.

**Dialogue language.** Everything the user sees is in the language of the primary task (the
goal, idea or findings in `plan-brainstorming`, the plan in every later skill): questions, option
labels and option descriptions in a question UI, status lines, confirmations, human gates, final
summaries and stop reports. Only tokens that parsers match stay in English: `### Task N:`,
`**Files:**`, `> Tier:`, command names and JSON field names. Sample phrases quoted in these
instructions ("Spec written to …", "MAX review passes done …", "I'm using the plan-writing
skill …") are templates: say them in the dialogue language, not verbatim. The language is
detected, not guessed: `ru` when more than 5% of the letters are Cyrillic, otherwise `en`.

In this skill: `brainstorm_tool.py detect-lang <file>` for a goal file or a findings JSON; for an
inline idea, the language of the user's message.

## Tool

`python "<SKILL_DIR>/scripts/brainstorm_tool.py" <command>`, where
`<SKILL_DIR>` is this skill's directory (absolute path). Stdlib Python 3.8+.
Exit codes: `0` ok, `1` check failed, `2` bad input or I/O error.

| Command | Use |
|---|---|
| `detect-lang <file\|->` | Dialogue language of a goal file or findings JSON (step 1). |
| `spec-check <spec.md>` | Contract check of the written spec (step 8). |
| `findings-parse <file.json\|-> [--root DIR]` | Findings mode, step 1. |
| `findings-coverage <file.json\|-> <spec.md>` | Findings mode, step 8. |
| `backlog-parse <BACKLOG.md> [--section S] [--state open\|done\|cancelled\|all]` | Backlog mode, step 1; amend mode with `--state done`. Each item has `state`: `open` `[ ]`, `done` `[x]`, `cancelled` `[-]`; default `open`. |
| `backlog-sweep <root> --section S [--journal J]` | Read-only input of the backlog sweep: the open items of the section and the specs of its chain journal with excerpts (see Backlog sweep). Exit `1` for `ambiguous-journal`. |
| `backlog-append <root> --section S --source "plan-brainstorming, <spec file>" --item TEXT [--lang ru\|en] [--plain]` | After the user approves the spec (see Backlog). |
| `backlog-mark <root> --section S --item TEXT` | After the user approves the spec, and after a confirmed backlog sweep: checks off one item (see Backlog). Exit `1` for `not-found`, `ambiguous` and `cancelled` (a `[-]` line). |
| `backlog-unmark <root> --section S --item TEXT` | Amend mode and a withdrawn spec, after the user confirms: unchecks one `[x]` item the spec no longer covers. `unmarked`, `already` (exit `0`); `cancelled`, `not-found`, `ambiguous` (exit `1`, nothing written). |
| `settings <file>` | Chain settings, environments and backlog of a spec, plan, roadmap or part (single reading rule; other skills load it as a module). |
| `journal-path <spec\|plan\|roadmap\|part> [--create]` | Path and goal of the chain journal `<goal>-chain.json` (a roadmap or part leads to its master plan, a plan to its spec). `--create` creates the journal and registers the spec: after the spec is approved (see Chain journal); given a plan, roadmap or part it also registers the master plan (every stage `pending`). |
| `journal-event`, `journal-unit`, `journal-question`, `journal-answer`, `journal-finding`, `journal-commit`, `journal-export-findings`, `journal-show`, `journal-reconcile [--rebuild]`, `journal-validate` (each takes `<journal>` first) | The journal API of the later skills: stage transitions, unit events, questions and answers, findings outside the plan (appended to `BACKLOG.md`), commits, the `<goal>-followups.json` export, a summary, repair and validation. Format: `assets/chain-journal.schema.json`. |

## Checklist

Complete these steps in order. On Standard and Deep, keep them as todo items; on Quick, one
item for the whole checklist is enough.

1. **Explore project context** — files, docs, recent commits. Restate the request in one sentence: this is the fidelity anchor for step 9. Findings mode: parse and triage the findings (`references/findings-input.md` Steps A-B). Backlog mode: `backlog-parse`, the backlog sweep (see Backlog sweep), then show the remaining unchecked items.
2. **Determine depth tier** — auto-classify Quick/Standard/Deep, state it, let the user confirm or adjust (`references/depth-tiers.md`). Findings mode: show the triage table in the same message.
3. **Offer the visual companion** — only when the questions ahead are visual (layouts, flows, comparisons). Its own message (see Visual Companion); skip it otherwise.
4. **Ask clarifying questions** — purpose, constraints, success criteria (see Asking Questions). Findings mode: first the scope question (`references/findings-input.md` Step C). Backlog mode: first the question which of the remaining items go into this spec.
5. **Propose approaches** — Standard/Deep: 2-3 with trade-offs, lead with your recommendation and why. Quick: one approach, unless a real fork exists.
6. **Present the design** — in sections scaled to the tier; get approval after each section.
7. **Close underspecified areas** — ambiguity sweep (`references/clarify-checklist.md`) until `Open Questions` can be `(none)`. If an answer changes the approved design, re-present the affected section and get approval again. Then propose the chain settings in one message (see Chain Settings) and wait for the user to confirm or adjust them.
8. **Write the spec** — first tell the user in one line what happens next: "Design approved. Writing the spec and running the checks; project code is not changed. I will come back with the file for your approval." Then see Writing the Spec. Run `spec-check` (and `findings-coverage` in findings mode) until both exit `0`.
9. **Self-review** — see below.
10. **User review** — ask the user to review the spec file; on approval, append to BACKLOG.md and check off the items the spec took in (see Backlog), create the chain journal (see Chain journal), then invoke `plan-writing`.

The terminal state is invoking `plan-writing` (in amend mode: the closing report, see Amend mode). Do not invoke any other skill after brainstorming.

## Understanding the Idea

- Assess scope first. If the request covers several independent subsystems (e.g. "a platform with chat, file storage, billing, and analytics"), say so immediately and help decompose it: the pieces, how they relate, the build order. Then brainstorm the first sub-project. Each sub-project gets its own spec → plan → implementation cycle.
- **Investigate before asking.** If the code, docs, or commits answer a question, find the answer yourself.
- **Verify claims about existing code.** When the user describes how code behaves, check it. If the code disagrees, surface the contradiction before designing on it. What you verified goes into the spec as `path:line` citations in Architecture and Components, so `plan-writing` does not rediscover it.
- **External systems need permission.** Investigation means reading the repository and running local commands without side effects (build, offline tests, grep). Anything that reaches an external system — a database, an API, a remote service, a cloud account — even a constant query, runs only after the user explicitly allows it and names the environment. A permission covers the named environment only: never extend it to another one, and never treat an existing project script that targets another environment as permission. Production needs a separate confirmation for every action. Pre-approved reads (`read=run` in the spec's `> Environment:` line, production included) cover the plan's steps and the read-only checks of plan-iterative-revision and plan-resolver; changes on production are never pre-approved. This skill investigates before the spec exists, so it still asks. Without permission the claim stays unverified: design on the cautious reading and record how it will be verified (`references/spec-contract.md`, "Unverified claims").
- Follow existing patterns. Include targeted improvements where existing code blocks the work (a file doing too much, tangled boundaries), but no unrelated refactoring.

## Asking Questions

- **One question per message.** Split a big topic into several questions.
- Prefer multiple choice; open-ended is fine when choices would be artificial.
- **Order questions by dependency.** Ask what other answers depend on first; let each answer reshape what you ask next.
- **Surface interpretations.** When a request has several readings, name them and let the user choose.
- **State assumptions out loud.** When an answer is genuinely unavailable, pick the least-disruptive interpretation, say it is an assumption, and record it.
- If the host has an interactive question UI (buttons / multiple choice), use it: one question per prompt, options listed, recommended option marked, free-text answer allowed. Otherwise ask inline.

## Designing

- **YAGNI ruthlessly.** No speculative features, premature abstractions, or error handling for cases that cannot happen.
- **Investigate broadly, scope narrowly.** Understand the whole context, then propose the smallest design that meets the goal.
- **Prefer reversible designs.** Between viable options, favour the one easier to undo.
- Units with one clear purpose and well-defined interfaces: for each, you can say what it does, how to use it, and what it depends on.
- Cover architecture, components, data flow, error handling, and testing. Scale depth to the tier: a few sentences on Quick, full paragraphs on Deep.

## Chain Settings

Before writing the spec, send ONE message that proposes the decisions the rest of the chain would otherwise ask about; the user confirms or adjusts them, like the tier at step 2. This is a confirmation of defaults, the one deliberate exception to one question per message. The confirmed values become the `> Chain:` and `> Environment:` lines (`references/spec-contract.md`, "Chain, Environment and Backlog lines"); later skills read them instead of asking.

- **Chain:** propose the defaults unless the dialogue gave a reason to differ: `split=auto`, `revision=` the tier (Quick → `quick`, Standard → `standard`, Deep → `deep`), `stop=pragmatic`, `resolver=audit`. One short line per key saying what it decides.
- **Environment:** one entry per external system the plan's steps will touch, with its kind (`test` or `prod`); if there is none, say so in one line. Ask for the rights as two separate choices and name the **changes first**: what the plan will write, migrate or delete there and `write=run|task|deny`; only then the reads and `read=run|task|deny`. `run` = for the whole run, `task` = ask before each task, `deny` = forbidden. On `prod` offer only `write=task` or `write=deny`; record `read=run` on prod only when the user's answer says exactly that.
- **Quote:** record the short question and the user's answer in the user's words (`"Tests and migrations on app_test? — Yes, app_test only"`). Never copy interface markers such as `(Recommended)` or `(рекомендую)` from the options: `spec-check` rejects them.

## Writing the Spec

- Path: `<plan-root>-spec.md` in the same directory as the goal file.
  - `<plan-root>` = the goal filename without extension and without any descriptive suffix after the numeric segment: `plan01.md` → `plan01-spec.md`; `plan02-goal.md` → `plan02-spec.md`; `superplan03-abstract.md` → `superplan03-spec.md`.
  - No source file (inline idea or inline findings): ask for the path and recommend a default.
  - User preferences for the location override this default.
  - Several specs of one goal (decomposition): numeric suffix by default, `<plan-root>-1-spec.md`,
    `<plan-root>-2-spec.md`, …; a descriptive suffix only when the user asks for it. A spec
    added to a goal that already has specs takes the next free number; existing specs are
    never renamed.
  - Backlog mode has no goal file: ask for the path and recommend `<section>-spec.md`, or the
    next free `<section>-N-spec.md` when specs of that section already exist.
- First line: `> Tier: <Quick|Standard|Deep>` with the confirmed tier. `plan-writing` inherits it.
- Then the confirmed `> Chain:` line with all four keys and one `> Environment:` line per environment (format: `references/spec-contract.md`, "Chain, Environment and Backlog lines"). `spec-check` validates them.
- `> Backlog: <goal>` among the metadata lines above `# Goal`: the BACKLOG.md section of this
  goal. Default: `<plan-root>` (for several specs of one goal, the shared root without `-N`);
  in backlog mode, the section the items came from.
- Structure: exactly the 8 headings of `references/spec-contract.md`, in order; `# Goal` is the only H1. `Open Questions` is `(none)`.
- Short sentences, concrete nouns.
- Do not commit the spec. Leave version control to the user.

## Self-Review

`spec-check` covers structure and placeholder markers. Then read the spec with fresh eyes:

1. **Fidelity** — compare `# Goal` and `## Out of Scope` with the one-sentence restatement from step 1. Anything the user asked for that is now out of scope, or anything added that they did not ask for, is drift: name it and ask before proceeding.
2. **Consistency** — no sections contradict each other; the architecture matches the components.
3. **Scope** — one implementation plan's worth, or does it need decomposition?
4. **Ambiguity** — a requirement with two readings gets one, made explicit.

Fix issues inline. On the Deep tier, if the host supports subagents, also dispatch a reviewer with `spec-document-reviewer-prompt.md`. Tell the user what it found. A finding that changes the approved design is shown to the user before the spec is edited (the step-7 rule); other findings are fixed inline. A finding that can only be settled by an external system follows the permission rule above.

## User Review Gate

> "Spec written to `<path>`. Please review it and let me know if you want any changes before we write the implementation plan."

Wait for the response. On changes: edit, re-run `spec-check` and the self-review, ask again.

Backlog mode, and amend mode when the change took in BACKLOG.md items: the same message lists the
items the spec covers (section, text and line, as `backlog-parse` gave them) and says that they
will be checked off `[x]` once the file is approved. On changes that alter the list, show it again.

**STOP-condition.** Invoke `plan-writing` only when ALL are true:

1. `spec-check` exits `0`; in findings mode, `findings-coverage` also exits `0`.
2. Self-review passed.
3. The user explicitly approved the written spec file.

## Backlog

`BACKLOG.md` lies at the repository root: `<root>` = `git -C <spec dir> rev-parse --show-toplevel`,
outside git the current working directory. Format and ownership: `references/spec-contract.md`
("Artifacts and naming"). Write only through `backlog-append`, `backlog-mark` and `backlog-unmark`, never by hand; the user's
section (`## My notes` / `## Свои заметки`) is never touched.

After the user approved the spec file, before invoking `plan-writing`:

1. Every `## Out of Scope` item that no other spec of the same goal covers:
   `backlog-append <root> --section <S> --source "plan-brainstorming, <spec file name>"
   --item "<item, one line>" --lang <detect-lang of the spec>`. `<S>` = the spec's
   `> Backlog:` value, else the spec file name without `-spec.md`.
2. The goal was decomposed into several specs: one `--plain` line per spec, in build order,
   `--item "<spec file name> — <what it covers>"` (the spec map).
3. Backlog mode: for each item listed in the "Spec written" message,
   `backlog-mark <root> --section <the item's section> --item "<its text as backlog-parse gave it>"`.
   `[x]` means "taken into an approved spec", not "done"; `[ ]` is open and `[-]` cancelled. `[-]`
   is set and changed only by the user: this skill never sets or clears it, and `backlog-mark` /
   `backlog-unmark` refuse such a line (`cancelled`). Unchecking goes through `backlog-unmark`, only
   in amend mode and for a withdrawn spec (see Amend mode).
4. Report in one line: how many lines were appended, how many already existed (`exists`); how many
   items were checked off (`marked`) or unchecked (`unmarked`), were already in that state
   (`already`), and which were not found (`not-found`), matched several lines (`ambiguous`) or are
   cancelled (`cancelled`); nothing is written for the last three. Exit `1` of `backlog-append` (the
   file would change outside the section end, or is not UTF-8), of `backlog-mark` or of
   `backlog-unmark`: show the error and continue. The backlog is not a gate.

### Backlog sweep

Finds the open items that an approved spec of the same section already covers, so that they are
checked off instead of being offered again. It runs only in backlog mode (for every section with open
items; the user section is skipped) and in amend mode (for the spec's `> Backlog:` section), once per
session.

1. `backlog-sweep <root> --section <S>`. Backlog mode: `<root>` is the directory of the `BACKLOG.md`
   file given, and `<S>` each `## <S>` section with open items except the user's own. Amend mode:
   `<root>` and `<S>` as in Backlog, step 1 (`<S>` is the spec's `> Backlog:` value, else the spec
   file name without `-spec.md`). It returns the open items of `## <S>` and the specs registered in the
   section's chain journal `<S>-chain.json` (found under `<root>` by its exact name), each with its
   `goal`, the item heads of `components` and `findings`, and its `out_of_scope` items. It writes
   nothing.
2. Match each open item with the specs by meaning. A spec covers an item when its Goal,
   Architecture, Components or Findings Traceability takes the item in (read the spec file for
   Architecture). A mention in Out of Scope is not coverage. A spec with `missing: true` (the user
   removed or renamed the file) or with `error` covers nothing.
3. Show the pairs "item → spec, reason", one per line; the user confirms them or strikes lines out.
   Nothing is written before that.
4. `backlog-mark <root> --section <S> --item "<text>"` for each confirmed pair, report as in Backlog,
   step 4, and read the open items again (`backlog-parse`).

`ambiguous-journal` (exit `1`, `journals` lists the paths): ask which journal belongs to the section
and repeat with `--journal <path>`. `journal: null` or `specs: []`: say in one line that the section
has no approved specs to match against, and go on. Any other failure: one line, go on; the sweep is
not a gate.

## Chain journal

After the user approved the spec file and the Backlog step is done, create the goal's chain
journal: `journal-path <spec> --create`. It writes `<goal>-chain.json` next to the spec (`<goal>` =
the spec's `> Backlog:` value, else the spec file name without `-spec.md`) and registers the spec;
another spec of the same goal joins the same journal. Report the `journal` path in one line.

The dialogue's questions are not recorded: the journal starts with the approved spec. The later
skills record their stages, questions and findings there with the `journal-*` commands (table
above); their findings come back as `<goal>-followups.json`, a findings input of this skill.

The journal is not a gate:
- exit `2` `journal-corrupt` → say it, propose `journal-reconcile <journal> --rebuild`, and invoke
  `plan-writing` anyway;
- exit `1` `journal-locked` → repeat the command once; still locked → say it in one line and
  continue without the journal;
- exit `1` `journal-write-failed` (the file system refused the write, e.g. a read-only journal) →
  say it in one line with the error text and continue without the journal.

## Amend mode

The input is an approved spec that must change: an answer given in `/plan-chain-runner discuss`
that touches the spec, or the user's own request. You own the spec: edit the file in place and
never write a second spec beside it. This mode replaces the Checklist; Asking Questions,
Designing, Self-Review, the User Review Gate and Backlog still apply. Dialogue language:
`detect-lang <spec>`.

1. Read the spec with its `> Tier:` and settings lines. Restate the requested change in one
   sentence: it is the fidelity anchor of the self-review. Before any edit, `journal-path <spec>`
   (without `--create`) and, when that journal exists, `journal-show <journal>`: a stage `audit`
   that is `running` means a `plan-resolver` audit may be fingerprinting the working copy, and
   any edit would invalidate it. Then edit nothing: say that an audit is running and propose to
   come back when it has ended (or to go on only if the user confirms no audit agent is working).
   Otherwise run the backlog sweep for the spec's `> Backlog:` section (see Backlog sweep), except
   when the request is to withdraw the spec (see "Withdrawing a spec" below).
2. Discuss only the change, one question per message; the rest of the approved spec is not
   reopened. A change of the tier or of the `> Chain:` / `> Environment:` lines is proposed in one
   message, as in Chain Settings.
3. Present the changed sections and get approval for each.
4. Edit the spec in place and run `spec-check` until it exits `0`, then the Self-Review: fidelity
   compares the edit with the one-sentence change and with the Goal.
5. User Review Gate: name what changed and wait for explicit approval of the file.
6. After approval, append to BACKLOG.md only the Out of Scope items this change added (Backlog,
   step 1), and check off only the BACKLOG.md items this change took in (Backlog, step 3). Then
   `backlog-parse BACKLOG.md --section <S> --state done`: pick the checked items that the change
   removed from the spec, show them as "item — why the spec no longer covers it", and after the user
   confirms run `backlog-unmark <root> --section <S> --item "<text>"` for each (report as in
   Backlog, step 4).
7. Close with one report and stop: the file, what changed, the BACKLOG lines. Do not invoke
   `plan-writing` and do not create or edit the chain journal: the journal sees the changed spec
   through the input hash of the `writing` stage, and the next `journal-reconcile` asks a
   `drift: writing …` question whose answer `rewrite` rewrites the plan. Name the next step:
   `/plan-chain-runner continue`, or `/plan-writing <spec>` without the runner (it runs the drift
   check itself).

**Withdrawing a spec** goes through this mode too: the request is to cancel the spec, not to change
it. Only the audit check of step 1 applies; the backlog sweep (it would offer to check off the
items of the spec being withdrawn) and steps 2-5 (discussion, edit, `spec-check`, approval of the
file) are skipped. Run `backlog-parse BACKLOG.md --section <S> --state done`, pick the items the
spec's text took in, show them, and after the user confirms run `backlog-unmark` for each. The skill never deletes or
renames the spec file: say that the user should remove or rename it, otherwise the next backlog sweep
offers the same items again. The journal is not edited.

## Visual Companion

A browser-based tool for mockups, diagrams, and visual comparisons. It is a tool, not a mode: after acceptance, decide per question whether seeing beats reading.

When upcoming questions will involve visual content, offer it once:
> "Some of what we're working on might be easier to explain if I can show it to you in a web browser. I can put together mockups, diagrams, comparisons, and other visuals as we go. This feature is still new and can be token-intensive. Want to try it? (Requires opening a local URL)"

**This offer MUST be its own message** — nothing else in it, no question, no summary. Wait for the answer. If declined, continue text-only. If accepted, read `visual-companion.md` (in this skill's directory) before the first visual question.
