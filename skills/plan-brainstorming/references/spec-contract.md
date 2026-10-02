# Spec Contract

The structural contract every spec must satisfy before `plan-writing` consumes it, plus the
artifact names and hand-off rules shared by both skills.

## Required sections

A spec MUST contain these headings, in this order, in English verbatim (they are matched
literally even when the body is in another language):

1. `# Goal`
2. `## Architecture`
3. `## Components`
4. `## Data Flow`
5. `## Error Handling`
6. `## Testing Strategy`
7. `## Out of Scope`
8. `## Open Questions`

| Section | Must contain |
|---|---|
| Goal | One sentence describing the outcome. Not a list of features. |
| Architecture | 2-5 sentences on the approach and the decisions made, citing the existing code they rest on (`path:line`). |
| Components | Named units, each with a one-line responsibility; existing units cite their file. |
| Data Flow | How information moves between components, or `(none)` with rationale. |
| Error Handling | Failure modes and how each is surfaced or handled. |
| Testing Strategy | What is tested, at what level, and what is intentionally not tested. |
| Out of Scope | Explicit list of related work this spec does NOT cover. Never `(none)`. |
| Open Questions | Unresolved decisions. **Must be empty before plan-writing starts.** |

A heading with body `(none)` plus a one-line rationale is acceptable where a section does not
apply (e.g. Data Flow for a pure CLI tool); a missing heading is a violation. `# Goal` is the
document's only H1: no separate title heading.

Depth per section is tier-driven (`depth-tiers.md`); tiers change fill depth only.

## Tier line

Above `# Goal`: `> Tier: Quick|Standard|Deep` (bold forms such as `> **Tier:** Quick` are also
recognised). It is metadata, not a heading. `plan-brainstorming` writes the confirmed tier;
`plan-writing` reads it and defaults to Standard when it is missing or unknown
(`../../plan-writing/references/task-tiers.md`).

## Chain, Environment and Backlog lines

Next to the Tier line, above `# Goal`, the spec records the decisions the rest of the chain
would otherwise ask about. `plan-brainstorming` writes them after the user confirmed them;
`spec-check` validates them and returns them as `chain`, `environments` and `backlog`. Format
tokens are English; quotes are in the language of the dialogue.

- `> Chain: split=auto; revision=deep; stop=pragmatic; resolver=audit` — `key=value` pairs
  separated by `;`, in any order. An unknown key or value is an error. A missing key takes its
  default:

| Key | Values | Default | Replaces |
|---|---|---|---|
| `split` | `auto` / `always` / `never` | `auto` (the splitter's gate decides) | the "Which step?" question after the plan |
| `revision` | `quick` / `standard` / `deep` | the tier: Quick → `quick`, Standard → `standard`, Deep → `deep` | the preset confirmation of `plan-iterative-revision` |
| `stop` | `pragmatic` / `strict` | `pragmatic` | the stop-policy confirmation |
| `resolver` | `audit` / `auto` / `skip` | `audit` | the choice offered after execution |

- `` > Environment: `app_test` (test) — read=run, write=run — "Tests and migrations on app_test? — Yes, app_test only" (2026-10-01) ``
  — one line per external system: the name in backticks; the kind `test` or `prod`; both
  `read=` and `write=`, each `run` (for the whole run), `task` (ask before each task) or `deny`
  (forbidden); the quote; the date. The dash may be `—` or `-`; the quote may use `"…"`, `«…»`
  or `“…”`.
  - `prod` with `write=run` is an error: changes on prod are `task` or `deny` only. `read=run` on
    prod is allowed when the user's answer says exactly that.
  - The quote is a short question and the user's answer, in the user's words. Interface markers
    that a question UI adds to an option (`(Recommended)`, `(рекомендую)`) are not the user's
    words and are an error.
  - A line without `read=` or `write=` is an error: a spec has no old form.
- `> Backlog: <section name>` — the section of `BACKLOG.md` for this goal.

**Reading rule.** The spec is the single source of these settings; the plan does not copy them.
Skills read them with `brainstorm_tool.py settings <file>` (or `resolve_settings`, loaded as a
module): a roadmap or a part follows its `> Source:` / `> Источник:` link to the master plan; a
plan uses settings in its own header when present, else the spec named by `**Spec:**`; a spec
reads its own lines. Settings in a plan header (`**Chain:**`, `**Environments:**` with rights,
`**Backlog:**`) exist only for an old spec without these lines: the spec is never rewritten
(hand-off rule 3), so `plan-writing` asks and records the answers there. A missing `**Spec:**`
or `Source` target gives `ok: false` and `settings-source-missing: <path>`.

## Unverified claims

A claim about the behaviour of an external system (database, API, service) is either verified
or designed around:

- **Verified**: the user allowed the check and named the environment; the spec records where and
  when ("checked 2026-09-30 on SQL Server 16.0, test database `X`").
- **Not verified**: the design uses the cautious reading, and `## Testing Strategy` carries a
  line "Verified during implementation: <claim> — <which test, on which permitted environment>".

Either way `## Open Questions` stays empty: this is a decision with a planned check, not an
open question. Environments the user permitted are recorded as `> Environment:` lines with
separate read and write rights and the user's words (see above). These rights cover the plan's
steps and the audit checks of `plan-iterative-revision` and `plan-resolver`. They do not cover
the investigation in `plan-brainstorming`: it happens before the spec exists, so every check on
an external system there still needs the user's explicit permission.

## Artifacts and naming

| Artifact | Path | Owner |
|---|---|---|
| goal / idea | goal file or chat input | user |
| spec | `<plan-root>-spec.md`, next to the goal file | `plan-brainstorming` |
| plan | `<plan-root>-impl.md`, same directory (`plan_tool.py plan-path`) | `plan-writing` |
| execution result | code in the working tree; the engineer commits | `plan-executor` |
| backlog | `BACKLOG.md` at the repository root (`git rev-parse --show-toplevel` of the spec's or plan's directory; outside git the working directory) | `plan-brainstorming` (format, `backlog-append`, `backlog-parse`); writers: `plan-brainstorming`, `plan-executor`, `plan-resolver` |

`<plan-root>` = the goal file name without extension and without any descriptive suffix after
the numeric segment: `plan01.md` → `plan01-spec.md`; `plan02-goal.md` → `plan02-spec.md`;
`superplan03-abstract.md` → `superplan03-spec.md`; `review01.json` → `review01-spec.md`. A goal
file without a numeric segment keeps its whole stem (`goal.md` → `goal-spec.md`). Inline input has
no file: ask for the path and recommend a default. A user preference overrides the default.

Several specs of one goal (decomposition) take a numeric suffix by default:
`values-fix-1-spec.md`, `values-fix-2-spec.md`, … (plans `values-fix-1-impl.md`, …). A
descriptive suffix (`review01-conn-spec.md`) only when the user asks for it. A spec added to a
goal that already has specs takes the next free number; existing specs are never renamed.

`BACKLOG.md` is append-only for the skills:

- `## My notes` (`## Свои заметки` in a file created from a Russian spec) belongs to the user;
  skills never write there. Then one `## <goal>` section per goal: `<goal>` = the settings
  `backlog` value (`> Backlog:` of the spec, `**Backlog:**` of an old plan header), else the
  spec or plan file name without `-spec.md` / `-impl.md`.
- Item: `- [ ] <what> — <skill>, <artifact>, <YYYY-MM-DD>`. Spec map: `- <spec file> — <what it
  covers>`, no checkbox.
- Skills append only at the end of their goal's section, through `brainstorm_tool.py
  backlog-append`: it refuses to change any other byte (exit `1`, file not written) and skips
  an entry already present from the same source (`action: exists`). Only the user marks `[x]`
  or deletes lines.
- `/plan-brainstorming BACKLOG.md [section]` starts the next cycle from the unchecked items.

## Hand-off rules

1. Spec → plan only after the spec self-review passed and the user explicitly approved the
   written spec file.
2. Plan → spec is never automatic: when `plan-writing` finds the spec non-conforming, it stops
   and asks the user to re-enter `plan-brainstorming`.
3. One owner per artifact: other skills read a spec or plan but never rewrite it.

## Preflight (run by plan-writing)

`python "<SKILL_DIR>/scripts/brainstorm_tool.py" spec-check <spec>` checks: all 8 headings
present and in order; no empty section; `Out of Scope` non-empty; `Open Questions` empty or
`(none)` (+ one-line rationale); the `> Chain:`, `> Environment:` and `> Backlog:` lines (known
keys and values, the environment format with both rights, no `write=run` on prod, no interface
markers in quotes). Exit `1` → `plan-writing` stops and sends the user back to
`plan-brainstorming`; it never invokes it itself.

## Glossary

| Term | Meaning |
|---|---|
| spec | Design document: what and why. |
| plan | Implementation document: how, step by step. |
| task | A plan unit that fits 10 minutes or 100 lines of new code. |
| step | One action inside a task (2-5 minutes), tracked as `- [ ]`. |
| tier | Spec and plan depth level (Quick / Standard / Deep). |
