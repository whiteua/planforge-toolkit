# Task Tiers

Scale-adaptive depth for plan **tasks**. The tier is chosen during
`plan-brainstorming` (see `../../plan-brainstorming/references/depth-tiers.md`),
recorded as a `Tier:` line in the spec, and copied into the plan header as
`**Tier:**`. `plan-writing` renders each task at the matching depth and
`plan_tool.py plan-check` enforces the done-state rules below.

Tiers change **how much task ceremony is expanded**, never the task **core**.

## Core — mandatory in every tier

Every task, regardless of tier, MUST have:

- `Files:` — exact create/modify/test paths in backticks (checkpoint tasks excepted).
- numbered `steps` — `- [ ] **Step N: ...**` with real content (no placeholders).
- a **verifiable done-state** — either full `Postconditions` or a single
  `Done when:` line naming an observable, checkable result.

A task missing any of these is a plan failure. Tier never excuses the core.

## Tier → task format

| Element | Quick | Standard | Deep |
|---|---|---|---|
| `Files` | required | required | required |
| `steps` | required | required | required |
| done-state | one `Done when:` line | full `Preconditions` + `Postconditions` | full `Preconditions` + `Postconditions` |
| `Constraints` | omit | optional (real fork only) | optional (real fork only) |
| `If stuck` | omit | optional (likely traps only) | recommended |
| Checkpoint tasks | not used | allowed | allowed |

A checkpoint task (`### Task N: Checkpoint — ...`) always uses a `Done when:`
line, in every tier where it is allowed.

## Quick collapse rule

On Quick, `Preconditions`/`Postconditions`/`Constraints`/`If stuck` are
replaced by one `Done when: <observable result>` line. The done-state does
not disappear — it shrinks. This mirrors the spec-side invariant in
`depth-tiers.md`: depth changes, presence of a checkable result does not.

## Optional blocks

Place both blocks inside the task, after `Files`.

**`Constraints`** — the task's decision corridor. Add it only when there are
several reasonable approaches and the choice is already made, or when agents
tend to over-engineer this kind of task. Each line removes a plausible wrong
branch:

```markdown
**Constraints:**
- Use: [tool or pattern chosen for this task]
- Don't use: [tempting anti-pattern]
- Scope boundary: [what this task does NOT solve, even if it looks logical]
```

**`If stuck`** — targeted failure guidance, not generic debugging advice. Add
it only for 2-3 likely, specific failure modes: environment, dependency or
order problems, naming collisions, common agent mistakes. Omit it if you
cannot name them.

```markdown
**If stuck:**
- [specific symptom] -> [where to look / what to check]
```

## Missing or unknown tier

If the spec has no `Tier:` line, or an unrecognized value, `plan-writing`
defaults to **Standard**, announces the assumption, and writes
`**Tier:** Standard` into the plan header. The spec's recorded `Tier:` line is
the single source of truth when present.

## Related Files

- `../../plan-brainstorming/references/depth-tiers.md` — spec-side tiers.
- `../SKILL.md` — reads the tier at Preflight and applies this mapping.
- `../plan-document-reviewer-prompt.md` — Deep-tier reviewer.
