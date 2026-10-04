# Depth Tiers

Scale-adaptive depth for specs. Tiers change **how deeply each section is filled**, never
**which sections exist**: all 8 headings of `spec-contract.md` stay in every tier, and a
material ambiguity is closed regardless of tier (`clarify-checklist.md`).

## The three tiers

| Tier | When | Typical spec size |
|---|---|---|
| Quick | Single-file change, bugfix, config tweak, no new integrations. | A few sentences per section; several may be `(none)` + rationale. |
| Standard | A feature touching 2-5 components, mostly within existing code. | One short paragraph per section. |
| Deep | New subsystem, external integrations, several new components, non-trivial failure modes. | Full paragraphs; tables where useful. |

## Auto-selection

Classify by the strongest signal (one Deep signal wins):

- **Deep** if any: new external integration; 3+ new components; a persistent data model is
  introduced; concurrency, security or performance is a stated concern.
- **Standard** if: 2-5 components touched, no external integration, fits the existing architecture.
- **Quick** if: one file or component, no new interfaces, no new dependencies.

State the chosen tier and let the user raise or lower it in one reply. Do not proceed silently;
do not block when the user already implied a tier. Prefer the higher tier when signals conflict:
under-specifying costs more than over-specifying.

## Per-section depth

| Section | Quick | Standard | Deep |
|---|---|---|---|
| Goal | 1 sentence | 1 sentence | 1 sentence |
| Architecture | 1-2 sentences | 2-3 sentences | full, decisions justified |
| Components | bullet list, 1 line each | table, 1 line each | table + responsibilities |
| Data Flow | `(none)` allowed if trivial | short prose | prose or diagram |
| Error Handling | main failure only | key failures | all failure modes |
| Testing Strategy | what proves it works | per level | per level + what is not tested |
| Out of Scope | 1-2 bullets | explicit list | explicit list |
| Open Questions | empty | empty | empty |

`(none)` + a one-line rationale is the only allowed shrink; deleting a heading is a violation.

## Size budget

The tier also sets how many plan tasks one Components item is expected to cost in `spec-check`'s
volume estimate: Quick 1, Standard 2, Deep 3, plus one task per Testing Strategy item. One spec
should fit one plan of at most 40 tasks or 150000 bytes; above it, decompose the goal into several
specs (`spec-contract.md`, Volume estimate).
