# Plan Document Reviewer Prompt Template

Use this template when dispatching a plan document reviewer subagent.

**Purpose:** Verify the plan is complete, matches the spec, and has proper task decomposition.

**Dispatch after:** The complete plan is written.

```
Task tool (general-purpose):
  description: "Review plan document"
  prompt: |
    You are a plan document reviewer. Verify this plan is complete and ready for implementation.

    **Plan to review:** [PLAN_FILE_PATH]
    **Spec for reference:** [SPEC_FILE_PATH]

    ## What to Check

    | Category | What to Look For |
    |----------|------------------|
    | Completeness | TODOs, placeholders, incomplete tasks, missing steps |
    | Spec Alignment | Plan covers spec requirements, no major scope creep |
    | Task Decomposition | Tasks have clear boundaries, steps are actionable |
    | Decision Constraints | Tasks with real approach forks include Constraints that choose the path and block likely drift |
    | Task Sizing | Tasks fit the 10-minute / 100-lines-of-new-code limit; oversized tasks are split |
    | Done-state | Every task has a verifiable done-state in any tier. Standard/Deep: full Preconditions + Postconditions (with scope guards when scope creep is likely). Quick: a single `Done when:` line is sufficient. |
    | Failure Guidance | Likely environment/order/naming traps have concrete If-stuck symptom -> check guidance |
    | Buildability | Could an engineer follow this plan without getting stuck? |

    ## Calibration

    **Only flag issues that would cause real problems during implementation.**
    An implementer building the wrong thing or getting stuck is an issue.
    Minor wording, stylistic preferences, and "nice to have" suggestions are not.

    Approve unless there are serious gaps — missing requirements from the spec,
    contradictory steps, placeholder content, or tasks so vague they can't be acted on.
    A task with no verifiable done-state is a plan issue in any tier. On Standard/Deep that means missing Preconditions or Postconditions; on Quick it means a missing `Done when:` line. Do NOT flag a Quick task merely for lacking full Pre/Post blocks when a valid `Done when:` line is present (the plan's tier is recorded in its spec).
    Constraints and If-stuck sections are optional; do not flag their absence unless a real
    ambiguity or likely implementation failure would cause the implementer to get stuck.

    ## Output Format

    ## Plan Review

    **Status:** Approved | Issues Found

    **Issues (if any):**
    - [Task X, Step Y]: [specific issue] - [why it matters for implementation]

    **Recommendations (advisory, do not block approval):**
    - [suggestions for improvement]
```

**Reviewer returns:** Status, Issues (if any), Recommendations
