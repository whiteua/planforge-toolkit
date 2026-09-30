---
name: plan-brainstorming
description: "Use before implementing a new feature, component, or behavior change that needs design decisions. Explores intent, requirements and trade-offs through one-question-at-a-time dialogue and produces an approved spec for plan-writing. Also use when given a JSON list of code-review findings (file, line, summary, failure_scenario) to design their fixes."
---

# Brainstorming Ideas Into Designs

Turn ideas into approved designs and specs through collaborative dialogue:
understand the project context, ask questions one at a time, present the
design, get approval, write the spec, hand off to `plan-writing`.

Vocabulary (spec, plan, task, step, tier) and handoff rules:
`references/plan-lifecycle.md`. Spec structure: `references/spec-contract.md`.
Read them when you reach step 8, not before.

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

## Language

These instructions are in English. Talk to the user and write the spec body
in the language of the input (goal file, idea, or findings): Russian input
gives a Russian dialogue and spec. The `> Tier:` line and the 8 contract
headings stay in English verbatim, because `plan-writing` and `spec-check`
match them literally.

## Tool

`python "<SKILL_DIR>/scripts/brainstorm_tool.py" <command>`, where
`<SKILL_DIR>` is this skill's directory (absolute path). Stdlib Python 3.8+.
Exit codes: `0` ok, `1` check failed, `2` bad input or I/O error.

| Command | Use |
|---|---|
| `spec-check <spec.md>` | Contract check of the written spec (step 8). |
| `findings-parse <file.json\|-> [--root DIR]` | Findings mode, step 1. |
| `findings-coverage <file.json\|-> <spec.md>` | Findings mode, step 8. |

## Checklist

Complete these steps in order. On Standard and Deep, track each step as a
task. On Quick, one task for the whole checklist is enough.

1. **Explore project context** — files, docs, recent commits. Findings mode: parse and triage the findings (`references/findings-input.md` Steps A-B).
2. **Offer the visual companion** — only if visual questions are ahead. Its own message (see Visual Companion).
3. **Determine depth tier** — auto-classify Quick/Standard/Deep, state it, let the user confirm or adjust (`references/depth-tiers.md`).
4. **Ask clarifying questions** — purpose, constraints, success criteria (see Asking Questions).
5. **Propose 2-3 approaches** — with trade-offs; lead with your recommendation and why.
6. **Present the design** — in sections scaled to the tier; get approval after each section.
7. **Close underspecified areas** — ambiguity sweep (`references/clarify-checklist.md`) until `Open Questions` can be `(none)`. If an answer changes the approved design, re-present the affected section and get approval again.
8. **Write the spec** — see Writing the Spec. Run `spec-check` (and `findings-coverage` in findings mode) until both exit `0`.
9. **Self-review** — see below.
10. **User review** — ask the user to review the spec file; on approval, invoke `plan-writing`.

The terminal state is invoking `plan-writing`. Do not invoke any other skill after brainstorming.

## Understanding the Idea

- Assess scope first. If the request covers several independent subsystems (e.g. "a platform with chat, file storage, billing, and analytics"), say so immediately and help decompose it: the pieces, how they relate, the build order. Then brainstorm the first sub-project. Each sub-project gets its own spec → plan → implementation cycle.
- **Investigate before asking.** If the code, docs, or commits answer a question, find the answer yourself.
- **Verify claims about existing code.** When the user describes how code behaves, check it. If the code disagrees, surface the contradiction before designing on it.
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

## Writing the Spec

- Path: `<plan-root>-spec.md` in the same directory as the goal file.
  - `<plan-root>` = the goal filename without extension and without any descriptive suffix after the numeric segment: `plan01.md` → `plan01-spec.md`; `plan02-goal.md` → `plan02-spec.md`; `superplan03-abstract.md` → `superplan03-spec.md`.
  - No source file (inline idea or inline findings): ask for the path and recommend a default.
  - User preferences for the location override this default.
- First line: `> Tier: <Quick|Standard|Deep>` with the confirmed tier. `plan-writing` inherits it.
- Structure: exactly the 8 headings of `references/spec-contract.md`, in order. `Open Questions` is `(none)`.
- Short sentences, concrete nouns.
- Do not commit the spec. Leave version control to the user.

## Self-Review

`spec-check` covers structure and placeholder markers. Then read the spec with fresh eyes:

1. **Consistency** — no sections contradict each other; the architecture matches the components.
2. **Scope** — one implementation plan's worth, or does it need decomposition?
3. **Ambiguity** — a requirement with two readings gets one, made explicit.

Fix issues inline. On the Deep tier, if the host supports subagents, also dispatch a reviewer with `spec-document-reviewer-prompt.md` and fix what it reports.

## User Review Gate

> "Spec written to `<path>`. Please review it and let me know if you want any changes before we write the implementation plan."

Wait for the response. On changes: edit, re-run `spec-check` and the self-review, ask again.

**STOP-condition.** Invoke `plan-writing` only when ALL are true:

1. `spec-check` exits `0`; in findings mode, `findings-coverage` also exits `0`.
2. Self-review passed.
3. The user explicitly approved the written spec file.

## Visual Companion

A browser-based tool for mockups, diagrams, and visual comparisons. It is a tool, not a mode: after acceptance, decide per question whether seeing beats reading.

When upcoming questions will involve visual content, offer it once:
> "Some of what we're working on might be easier to explain if I can show it to you in a web browser. I can put together mockups, diagrams, comparisons, and other visuals as we go. This feature is still new and can be token-intensive. Want to try it? (Requires opening a local URL)"

**This offer MUST be its own message** — nothing else in it, no question, no summary. Wait for the answer. If declined, continue text-only. If accepted, read `visual-companion.md` (in this skill's directory) before the first visual question.
