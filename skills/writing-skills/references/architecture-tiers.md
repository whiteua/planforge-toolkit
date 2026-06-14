# Architecture Tiers — Tier 3 Details

Loaded on demand when you author a Tier 3 (Hybrid state) skill. If you're
writing Tier 1 or 2, you don't need this file.

## Hard Invariants for Tier 3 Skills

1. **The LLM is stateless; the ledger is stateful.** Always ask the core tool
   "what's next" — never rely on conversation memory for progress.
2. **No direct mutation.** The agent MUST NEVER write/echo to `state.json`.
   Every state change goes through the core tool's CLI.
3. **One source of truth.** The ledger is authoritative. If the tool and the
   transcript disagree, the tool wins. But if the tool itself is in an invalid
   state (corrupted/incompatible ledger), the agent MUST stop and escalate —
   never silently override the tool to "keep going".
4. **(Conditional) Immutability check.** Only when other skills depend on an
   input being unchanged: have the core verify a content hash (e.g. SHA-256).
   Do NOT add hashing "just in case" — it's weight unless a real dependency exists.

**Testing a Tier 3 skill** = two RED scenarios, not one:
(a) markdown-layer: agent rationalizes skipping a step;
(b) state-layer: agent edits `state.json` by hand or claims a step is done
without calling the tool. GREEN = agent queries the tool and the ledger stays valid.

## Skill Handoff Contract

When one skill delegates to another:

1. **Explicit input.** The caller passes exact file paths and required args —
   never "you know the context".
2. **Structured output.** The callee returns a locatable result (report path,
   exit status), not just prose in the transcript.
3. **Context isolation.** The callee MUST be self-sufficient: it cannot depend
   on the caller's conversation state. (Same principle as self-contained
   stage files in `plan-splitter`.)

## Size Budget by Tier

Budgets are on SKILL.md *body* lines (frontmatter excluded), consistent with
the project's line-based rule. Push everything else into references/.

| Tier | SKILL.md body | Where the bulk lives |
|---|---|---|
| 1 | < 200 lines | inline |
| 2 | < 300 lines | inline + `scripts/` help text |
| 3 | < 200 lines | `references/` (workflow, formats); core tool emits "Read references/X.md" at the right phase |

Tier 3 keeps SKILL.md *smaller*, not larger: the protocol lives in references/,
loaded on demand. A fat Tier 3 SKILL.md is a smell.