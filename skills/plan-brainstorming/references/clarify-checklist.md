# Clarify Checklist

A deterministic sweep for underspecified areas, run after the design is approved and before the
spec is written (checklist step 7). Its job: `Open Questions` is empty at hand-off. Each gap
found becomes one clarifying question at a time; answers fold into the spec.

## Categories

1. **Data model**: entities, fields, types, required vs optional, identity and uniqueness.
2. **Error semantics**: what counts as an error, how each is surfaced, what the caller sees,
   recover vs fail.
3. **Scope edges**: explicitly in vs out; boundary and limit cases; empty, zero, maximum inputs.
4. **Integrations**: external dependencies, contracts, formats, versioning, auth; which
   environments exist and which of them the user permits for checks (`spec-contract.md`,
   "Unverified claims").
5. **Non-functional**: performance, security, data volume, concurrency, only where load-bearing.

## Scenario stress-test

The categories are a passive checklist; this is the active move. For a concept whose boundaries
feel fuzzy, invent a concrete edge case and ask which way it resolves ("What happens when the
input is empty / at the maximum / arrives twice?", "If X and Y both apply, which wins?"). A
scenario the user cannot answer cleanly is an unresolved ambiguity: ask about it before writing.

## Per-tier scaling

| Tier | How much to run |
|---|---|
| Quick | Skip categories with no plausible ambiguity; usually 0-2 targeted questions, 0-1 scenario. |
| Standard | All categories; ask only where genuinely underspecified. |
| Deep | All categories thoroughly; probe each fuzzy boundary with a scenario. |

Scaling reduces the questions asked, never the gate: an open ambiguity blocks the spec in every
tier.
