# writing-skills — Quick Reference

Create a new skill, edit an existing one, or verify that a skill works before deployment, by
test-driven development applied to documentation: no skill without a failing test first.

## How to Invoke

```
/writing-skills                  # create, edit or verify a skill
/writing-skills help             # show this quick reference in the dialogue language, nothing else
```

The skill also loads on its own when you ask to create, edit or test a skill.

## What Happens

```
PLAN (non-trivial skills)  — state the purpose in one sentence; unclear → plan-brainstorming; multi-file → plan-writing
RED                        — run pressure scenarios with a subagent WITHOUT the skill; record its choices and rationalizations verbatim
GREEN                      — write the minimal skill that answers those failures; run the same scenarios WITH it until the agent complies
REFACTOR                   — every new rationalization gets an explicit counter (rationalization table, red flags); re-test until bulletproof
STOP                       — finish the checklist for this skill before starting the next one
```

The Iron Law holds for new skills and for edits alike: a skill written or changed before its
test failed is deleted and started over.

## Architecture Tiers

| Tier | Structure | Use when |
|---|---|---|
| 1 — Pure doc (default) | `SKILL.md` only | Judgment calls, patterns, references, single-step techniques |
| 2 — Doc + tool | `SKILL.md` + `scripts/` or `example.*` | One deterministic operation that is painful by hand |
| 3 — Hybrid state | `SKILL.md` + `scripts/core.py` + `state.json` + `references/` | A multi-step loop whose progress must survive `/clear` or a crash |

## Output

- `skills/<name>/SKILL.md` — YAML frontmatter (`name`, `description` starting with "Use when…", triggers only) and the skill
- Supporting files only for heavy reference (100+ lines) or reusable tools
- Optionally, pressure scenarios saved under `tests/` for cheap re-runs (plain prompts, no runner)
- In this repository also the files of "Skills in this repository" in `SKILL.md`, File Organization

## Prerequisites

- A tool that starts a subagent, for the pressure scenarios
- `plan-brainstorming` and `plan-writing` for non-trivial skills (recommended)

## Common Mistakes

| Symptom | Cause | Fix |
|---|---|---|
| The agent follows the description instead of the skill | The description summarizes the workflow | Describe only the triggering conditions |
| The skill passes but teaches the wrong thing | No baseline run without the skill | Run RED first and record the failures |
| Several skills written in one batch | Testing skipped "for efficiency" | Finish the checklist for each skill before the next |

## Pipeline Position

```
writing-skills — meta-skill for authoring and testing skills, outside the plan pipeline
```

**Uses:** `plan-brainstorming` (goals and scope) and `plan-writing` (task decomposition) for non-trivial skills
