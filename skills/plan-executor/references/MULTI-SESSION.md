# MULTI-SESSION

## When

Use `recommend-parallel <exec_dir>` after ledger init. Recommend manual multi-session work only when a `parallel_group` contains more than one independent unit and their dependencies are already satisfied.

Parallel groups mean freedom of order, not automatic concurrency.

## How

Start one separate agent session per group or per selected unit, each with its own `.exec/` directory. The parent session remains responsible for final gate decisions and ledger updates.

There is no внутрисессионная конкурентность: do not run multiple units concurrently inside one agent loop, and do not let two sessions write the same `state.json`.
