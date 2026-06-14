# Clarify Checklist

A deterministic sweep for underspecified areas, run **after the design is
presented and before the spec is written** (checklist step 7 in `SKILL.md`).
Its job: guarantee `Open Questions` is empty before handoff to `plan-writing`.

Read together with `depth-tiers.md` and `spec-contract.md`.

## When To Run

After the user has approved the presented design, BEFORE writing the spec
file. Each gap found becomes a one-at-a-time clarifying question (via the
interactive channel when available). Resolved answers fold into the spec.

## Categories

For the chosen design, check each category. If a category is not fully
determined, ask:

1. **Data model** - entities, fields, types, what is required vs optional,
   identity/uniqueness.
2. **Error semantics** - what counts as an error, how each is surfaced,
   what the user/caller sees, recovery vs fail.
3. **Scope edges** - what is explicitly in vs out; boundary/limit cases;
   empty/zero/max inputs.
4. **Integrations** - external dependencies, contracts, formats, versioning,
   auth.
5. **Non-functional** - performance, security, data volume, concurrency —
   only where they are actually load-bearing for this design.

## Per-Tier Scaling

| Tier | How much to run |
|---|---|
| Quick | Skip categories with no plausible ambiguity; usually 0-2 targeted questions. |
| Standard | Run all categories; ask only where genuinely underspecified. |
| Deep | Run all categories thoroughly; each must be explicitly resolved. |

Scaling reduces *questions asked*, never the *gate*: even on Quick, any
material ambiguity must be closed.

## The Gate

The sweep is complete only when every identified ambiguity is resolved, so
that the spec's `## Open Questions` can be written as `(none)`. An open
ambiguity at this point blocks writing the spec — the tier is not an excuse.

## Related Files

- `depth-tiers.md` - how deep to go per tier.
- `spec-contract.md` - `Open Questions` is the load-bearing gate.
- `../SKILL.md` - runs this checklist at step 7.
