---
name: plan-executor
description: Use when executing a ready implementation plan, staged roadmap, or whole-plan task list that must advance one unit at a time with ledger-backed progress, gates, retries, checkpoints, and a final resolver proposal.
---

# plan-executor

## When to use

Use this skill when the plan already exists and the job is execution, not planning: staged plans from `plan-splitter`, whole plans with explicit Task headings, or implementation roadmaps that need deterministic progress tracking.

Do not use it to invent a plan. Use `plan-writing` or `plan-splitter` first when the input is still unstructured.

## Hard Invariants

1. Never edit source `*.md` plan or stage files while executing them.
2. Progress lives only in `state.json`; human progress is generated as `.exec/.../progress.md`.
3. `state.json` is modified only through `scripts/executor_tool.py` commands.
4. Destructive operations require explicit engineer confirmation.
5. A gate cannot pass silently when checks are absent; no tests means escalation, not fake success.

## Phases

- BOOTSTRAP: detect input, parse units, initialize ledger, detect checkpoints, and recommend parallel sessions.
- EXECUTE LOOP: claim the unit with `ledger-mark running`, execute exactly one ready unit, gate it, checkpoint it, then mark ledger done and render progress.
- FINALIZE: when all units are done, propose `plan-resolver` options without launching it automatically.

## Prerequisites

- Python ≥ 3.8 in PATH (stdlib only).
- `<SKILL_DIR>` is the directory containing this `SKILL.md`. Always invoke the
  script by absolute path: `python "<SKILL_DIR>/scripts/executor_tool.py" ...`.

## Core Tool

Run commands through:

```bash
python "<SKILL_DIR>/scripts/executor_tool.py" <command> [args...]
```

Core commands:

- `detect-input` (supports `--whole` to force whole-plan mode)
- `parse-roadmap`
- `parse-tasks`
- `ledger-init`
- `ledger-next`
- `ledger-mark`
- `ledger-status`
- `checkpoint-detect`
- `checkpoint-create`
- `checkpoint-restore`
- `recommend-gate`
- `recommend-strategy`
- `scope-context`
- `recommend-parallel`
- `render-progress`

## References

- [WORKFLOW.md](references/WORKFLOW.md)
- [INPUT-DETECTION.md](references/INPUT-DETECTION.md)
- [EXECUTION-STRATEGY.md](references/EXECUTION-STRATEGY.md)
- [GATE.md](references/GATE.md)
- [MULTI-SESSION.md](references/MULTI-SESSION.md)
- [RESOLVER-PROPOSAL.md](references/RESOLVER-PROPOSAL.md)

## Stop Reports

Use [stop-report.en.md](assets/stop-report.en.md) or [stop-report.ru.md](assets/stop-report.ru.md) when execution stops because retries are exhausted, stagnation is detected, rollback needs a decision, or the engineer must choose the next step.
