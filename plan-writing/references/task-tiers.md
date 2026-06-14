# Task Tiers

Scale-adaptive depth for plan **tasks**. The tier is chosen during
`plan-brainstorming` (see `../../plan-brainstorming/references/depth-tiers.md`)
and recorded as a `Tier:` line in the spec. `plan-writing` reads it at
Preflight and renders each task at the matching depth.

Tiers change **how much task ceremony is expanded**, never the task **core**.

## Core — mandatory in every tier

Every task, regardless of tier, MUST have:

- `Files:` — exact create/modify/test paths.
- numbered `steps` — concrete actions with real content (no placeholders).
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
| Phase Checkpoints | not used | allowed | allowed |

## Quick collapse rule

On Quick, `Preconditions`/`Postconditions`/`Constraints`/`If stuck` are
replaced by one `Done when: <observable result>` line. The done-state does
not disappear — it shrinks. This mirrors the spec-side invariant in
`depth-tiers.md`: depth changes, presence of a checkable result does not.

## Missing or unknown tier

If the spec has no `Tier:` line, or an unrecognized value, `plan-writing`
defaults to **Standard** and announces the assumption. The spec's recorded
`Tier:` line is the single source of truth when present.

## Related Files

- `../../plan-brainstorming/references/depth-tiers.md` — spec-side tiers.
- `../SKILL.md` — declares Preflight tier-read and applies this mapping.
- `../plan-document-reviewer-prompt.md` — validates a plan against its tier.
