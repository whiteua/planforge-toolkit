# Depth Tiers

Scale-adaptive depth for spec documents. Tiers change **how deeply each
section is filled**, never **which sections exist**. All 8 headings from
`spec-contract.md` are mandatory in every tier.

Read together with `spec-contract.md` and `clarify-checklist.md`.

## The Three Tiers

| Tier | When | Typical spec size |
|---|---|---|
| Quick | Single-file change, bugfix, config tweak, no new integrations. | A few sentences per section; several may be `(none)` + rationale. |
| Standard | A feature touching 2-5 components, mostly within existing code. | One short paragraph per section. |
| Deep | New subsystem, external integrations, multiple new components, non-trivial failure modes. | Full paragraphs; tables where useful. |

## Auto-Selection Heuristic

Classify by the strongest signal present (a single Deep signal wins):

- **Deep** if any: new external integration; 3+ new components; persistent
  data model introduced; concurrency/security/perf is a stated concern.
- **Standard** if: 2-5 components touched, no external integration, change
  fits existing architecture.
- **Quick** if: one file/component, no new interfaces, no new dependencies.

When signals conflict, pick the higher tier — under-specifying is more
expensive than over-specifying.

## Confirm Rule

After auto-classifying, state the chosen tier to the user and let them
raise or lower it in one reply (or one UI selection). Do not silently
proceed on the auto-choice; do not block waiting if the user already
implied a tier.

## Per-Section Depth

| Section | Quick | Standard | Deep |
|---|---|---|---|
| Goal | 1 sentence | 1 sentence | 1 sentence |
| Architecture | 1-2 sentences | 2-3 sentences | full, decisions justified |
| Components | bullet list, 1 line each | table, 1 line each | table + responsibilities |
| Data Flow | `(none)` allowed if trivial | short prose | prose or diagram |
| Error Handling | main failure only | key failures | all failure modes |
| Testing Strategy | what proves it works | per-level | per-level + non-tested |
| Out of Scope | 1-2 bullets | explicit list | explicit list |
| Open Questions | must be empty | must be empty | must be empty |

Every row keeps its heading in every tier. `(none)` + a one-line rationale
is the ONLY allowed shrink; deletion is a contract violation.

## Invariant

Tier never removes a heading and never excuses a non-empty `Open Questions`.
A material ambiguity is closed regardless of tier (see `clarify-checklist.md`).

## Related Files

- `spec-contract.md` - the 8 mandatory sections.
- `clarify-checklist.md` - closing ambiguities before the spec is written.
- `../SKILL.md` - declares and confirms the tier early in the process.
