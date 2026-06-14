# Spec Contract

The structural contract every spec document must satisfy before
`plan-writing` is allowed to consume it.

Read together with `plan-lifecycle.md`.

## Required Sections

A spec document MUST contain these top-level sections, in this order:

1. `# Goal`
2. `## Architecture`
3. `## Components`
4. `## Data Flow`
5. `## Error Handling`
6. `## Testing Strategy`
7. `## Out of Scope`
8. `## Open Questions`

All eight headings are mandatory. A heading with body text "(none)" is
acceptable for sections that genuinely do not apply (e.g. `Data Flow` for
a pure CLI tool); a missing heading is a contract violation.

The **depth** to which each section is filled is tier-driven (Quick /
Standard / Deep) — see `depth-tiers.md`. Tiers change fill depth only; they
never remove a heading and never relax the `Open Questions` gate.

## Tier Metadata Line

Above `# Goal`, a spec SHOULD carry a one-line tier marker as a blockquote:

```markdown
> Tier: Standard
```

- Allowed values: `Quick`, `Standard`, `Deep` (see `depth-tiers.md`).
- It is **additive metadata**, not a heading — it does not count toward or
  alter the 8 mandatory sections, and its absence is NOT a contract
  violation (legacy specs predate it).
- `plan-brainstorming` writes it from the confirmed tier; `plan-writing`
  reads it at Preflight and defaults to **Standard** when it is missing or
  unrecognized (see `../../plan-writing/references/task-tiers.md`).

## Section Definitions

| Section | Must contain |
|---|---|
| Goal | One sentence describing the outcome. Not a list of features. |
| Architecture | 2-5 sentences on the approach and major decisions made. |
| Components | Named units, each with one-line responsibility. |
| Data Flow | How information moves between components, or `(none)` with rationale. |
| Error Handling | Failure modes and how each is surfaced/handled. |
| Testing Strategy | What is tested, at what level, and what is intentionally not tested. |
| Out of Scope | Explicit list of related work that this spec does NOT cover. |
| Open Questions | Unresolved decisions. **Must be empty before plan-writing starts.** |

## Preflight Checklist

Used by `plan-writing` before producing a plan.

- [ ] All 8 required headings present, in the listed order.
- [ ] No section is empty (use `(none)` with one-line rationale instead).
- [ ] `## Out of Scope` is non-empty (explicit, even if short).
- [ ] `## Open Questions` is empty or contains only the literal text `(none)`.

If any checkbox is unchecked, `plan-writing` MUST STOP and direct the user
back to `plan-brainstorming`. It MUST NOT auto-invoke `plan-brainstorming`.

## Why these sections

- `Goal` / `Architecture` keep planning anchored to intent.
- `Components` + `Data Flow` give the plan author the unit boundaries.
- `Error Handling` + `Testing Strategy` ensure tasks can produce real
  tests (TDD requires knowing failure modes ahead of time).
- `Out of Scope` prevents scope creep into the plan.
- `Open Questions` is the load-bearing gate: an unresolved decision in
  the spec turns the plan into guesswork.

## Related Files

- `plan-lifecycle.md` - pipeline and handoff rules.
- `depth-tiers.md` - per-tier section depth (presence rules unchanged).
- `../SKILL.md` - `plan-brainstorming` produces specs matching this contract.
- `../../plan-writing/SKILL.md` - `plan-writing` enforces this contract at preflight.
