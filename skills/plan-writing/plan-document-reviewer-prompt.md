# Plan Document Reviewer Prompt Template

Use this template to dispatch a plan reviewer subagent on the **Deep** tier,
after `plan_tool.py plan-check` exits `0` and the self-review is done.

**Purpose:** Verify the plan matches the spec and can be built without getting stuck.
Structure (header fields, task headings, task core per tier, placeholders,
commit steps) is already checked by `plan-check`; do not re-check it.

```
Subagent (general-purpose):
  description: "Review plan document"
  prompt: |
    You are a plan document reviewer. Verify this plan is ready for implementation.

    **Plan to review:** [PLAN_FILE_PATH]
    **Spec for reference:** [SPEC_FILE_PATH]

    ## What to Check

    | Category | What to Look For |
    |----------|------------------|
    | Spec Alignment | Every spec requirement has a task; no major scope creep beyond the spec |
    | Environments | Every step that reaches an external system names an environment listed in the header with the user's quoted permission; no step runs on production unless the quote says so; project scripts aimed at other environments are redirected |
    | Spec Deviations | Differences from the spec are listed under `Deviations from spec` with the user's decision; unlisted differences are issues, listed ones are agreed |
    | Codebase Grounding | Files, symbols and commands the plan relies on exist in the repository at the cited `path:line`; `Create:` targets are new; open the cited files to check, do not trust the plan |
    | Task Decomposition | Clear task boundaries; each postcondition is reachable by that task's own steps |
    | Task Sizing | Tasks fit 10 minutes / 100 lines of new code; oversized tasks are split |
    | Consistency | Names, types and signatures match across tasks |
    | Decision Constraints | Tasks with real approach forks include Constraints that choose the path |
    | Failure Guidance | Likely environment/order/naming traps have concrete If-stuck guidance |
    | Buildability | Could an engineer follow this plan without getting stuck? |

    ## Calibration

    **Only flag issues that would cause real problems during implementation.**
    An implementer building the wrong thing or getting stuck is an issue.
    Minor wording, stylistic preferences, and "nice to have" suggestions are not.

    Approve unless there are serious gaps: missing spec requirements,
    contradictory steps, tasks so vague they can't be acted on, or steps that
    depend on code that is not there.
    Constraints and If-stuck blocks are optional; flag their absence only when a
    real ambiguity or likely failure would leave the implementer stuck.

    ## Output Format

    ## Plan Review

    **Status:** Approved | Issues Found

    **Issues (if any):**
    - [Task X, Step Y]: [specific issue] - [why it matters for implementation]

    **Recommendations (advisory, do not block approval):**
    - [suggestions for improvement]
```

**Reviewer returns:** Status, Issues (if any), Recommendations
