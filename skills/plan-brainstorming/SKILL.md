---
name: plan-brainstorming
description: "Use before implementing a new feature, component, or behavior change that needs design decisions. Explores intent, requirements and trade-offs through one-question-at-a-time dialogue and produces an approved spec for plan-writing. Also use when given a JSON list of code-review findings (file, line, summary, failure_scenario) to design their fixes. Also use with the shared BACKLOG.md to turn its unchecked items into the next spec."
---

# Brainstorming Ideas Into Designs

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
  [--section <section>]`; the unchecked items are the problem statement. The first question
  is which items go into this spec (multiple choice, one option per item). Only the user
  marks an item `[x]`: never edit BACKLOG.md lines yourself (see Backlog).

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
| `backlog-parse <BACKLOG.md> [--section S]` | Backlog mode, step 1. |
| `backlog-append <root> --section S --source "plan-brainstorming, <spec file>" --item TEXT [--lang ru\|en] [--plain]` | After the user approves the spec (see Backlog). |
| `settings <file>` | Chain settings, environments and backlog of a spec, plan, roadmap or part (single reading rule; other skills load it as a module). |

## Checklist

Complete these steps in order. On Standard and Deep, keep them as todo items; on Quick, one
item for the whole checklist is enough.

1. **Explore project context** — files, docs, recent commits. Restate the request in one sentence: this is the fidelity anchor for step 9. Findings mode: parse and triage the findings (`references/findings-input.md` Steps A-B). Backlog mode: `backlog-parse` and show the unchecked items.
2. **Determine depth tier** — auto-classify Quick/Standard/Deep, state it, let the user confirm or adjust (`references/depth-tiers.md`). Findings mode: show the triage table in the same message.
3. **Offer the visual companion** — only when the questions ahead are visual (layouts, flows, comparisons). Its own message (see Visual Companion); skip it otherwise.
4. **Ask clarifying questions** — purpose, constraints, success criteria (see Asking Questions). Findings mode: first the scope question (`references/findings-input.md` Step C). Backlog mode: first the question which items go into this spec.
5. **Propose approaches** — Standard/Deep: 2-3 with trade-offs, lead with your recommendation and why. Quick: one approach, unless a real fork exists.
6. **Present the design** — in sections scaled to the tier; get approval after each section.
7. **Close underspecified areas** — ambiguity sweep (`references/clarify-checklist.md`) until `Open Questions` can be `(none)`. If an answer changes the approved design, re-present the affected section and get approval again. Then propose the chain settings in one message (see Chain Settings) and wait for the user to confirm or adjust them.
8. **Write the spec** — first tell the user in one line what happens next: "Design approved. Writing the spec and running the checks; project code is not changed. I will come back with the file for your approval." Then see Writing the Spec. Run `spec-check` (and `findings-coverage` in findings mode) until both exit `0`.
9. **Self-review** — see below.
10. **User review** — ask the user to review the spec file; on approval, append to BACKLOG.md (see Backlog), then invoke `plan-writing`.

The terminal state is invoking `plan-writing`. Do not invoke any other skill after brainstorming.

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

**STOP-condition.** Invoke `plan-writing` only when ALL are true:

1. `spec-check` exits `0`; in findings mode, `findings-coverage` also exits `0`.
2. Self-review passed.
3. The user explicitly approved the written spec file.

## Backlog

`BACKLOG.md` lies at the repository root: `<root>` = `git -C <spec dir> rev-parse --show-toplevel`,
outside git the current working directory. Format and ownership: `references/spec-contract.md`
("Artifacts and naming"). Write only through `backlog-append`, never by hand; the user's
section (`## My notes` / `## Свои заметки`) is never touched.

After the user approved the spec file, before invoking `plan-writing`:

1. Every `## Out of Scope` item that no other spec of the same goal covers:
   `backlog-append <root> --section <S> --source "plan-brainstorming, <spec file name>"
   --item "<item, one line>" --lang <detect-lang of the spec>`. `<S>` = the spec's
   `> Backlog:` value, else the spec file name without `-spec.md`.
2. The goal was decomposed into several specs: one `--plain` line per spec, in build order,
   `--item "<spec file name> — <what it covers>"` (the spec map).
3. Backlog mode: name the BACKLOG.md items (text and line) the approved spec covers and remind
   the user that they mark them `[x]` when the work is done.
4. Report in one line: how many lines were appended, how many already existed (`exists`).
   Exit `1` (the file would change outside the section end, or is not UTF-8): nothing was
   written; show the error and continue. The backlog is not a gate.

## Visual Companion

A browser-based tool for mockups, diagrams, and visual comparisons. It is a tool, not a mode: after acceptance, decide per question whether seeing beats reading.

When upcoming questions will involve visual content, offer it once:
> "Some of what we're working on might be easier to explain if I can show it to you in a web browser. I can put together mockups, diagrams, comparisons, and other visuals as we go. This feature is still new and can be token-intensive. Want to try it? (Requires opening a local URL)"

**This offer MUST be its own message** — nothing else in it, no question, no summary. Wait for the answer. If declined, continue text-only. If accepted, read `visual-companion.md` (in this skill's directory) before the first visual question.
