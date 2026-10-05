# Spec Set Reviewer Prompt Template

Use this template when dispatching the reviewer of a goal's spec set (`plan-brainstorming`, step 11).

**Purpose:** Find what the specs of one goal get wrong together, before plans are written from them.

**Dispatch after:** `spec-set-check <dir>` ran on two or more specs of the goal; always, on every tier.

```
Task tool (general-purpose):
  description: "Review the goal's spec set"
  prompt: |
    You review a set of specs that belong to one goal. Each spec was approved on its own;
    you check them together. Read every spec in full; read code only to settle a conflict.

    **Specs:** [SPEC_FILE_PATHS, in the order they were written]
    **spec-set-check JSON:** [JSON] (touchpoints, undeclared, numbered_items, self_edges)

    ## What to Check

    | Category | What to look for |
    |---|---|
    | Duplicated work | Two specs build the same unit, command, field or document section |
    | Contradicting decisions | Two specs decide differently about one component, format, name or default |
    | Undeclared dependency | A spec needs what another delivers, but neither names the other (start from `undeclared`) |
    | Delivery-order conflict | Two specs edit one section with hard numbering (`numbered_items`: §N, item N, step N) or one function, and no order is stated |
    | Terms and artifacts | One file, field or command named differently in two specs |
    | Gaps | Out of Scope items the goal needs that no spec takes |

    ## Calibration

    Flag only what would make two plans collide or leave the goal incomplete. A shared file is
    not a finding by itself: it is one when the specs change it in ways that conflict, or depend
    on an order nobody stated. Wording and depth differences are not findings.

    ## Output Format

    ## Spec Set Review

    **Status:** Consistent | Findings

    **Findings (if any):** one line each
    - [spec file] → [section] → [what is wrong] → [how to reconcile: which spec changes, or which order to declare]

    **Delivery order (advisory):** each shared point with the order you recommend and the spec that sets the final numbering.
```

**Reviewer returns:** Status, Findings, Delivery order. Without a subagent tool the agent runs the same check itself by this prompt and says so in one line.
