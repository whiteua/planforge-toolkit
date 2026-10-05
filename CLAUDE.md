# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

PlanForge Toolkit is a collection of **agent skills** (agentskills.io `SKILL.md` convention), not an application. Each directory under `skills/` is an independently installable skill, distributed via `npx skills add whiteua/planforge-toolkit` or by symlinking `skills/<name>` into an agent's skills directory. Rolling release: every push to `main` is a release, so there are no version tags.

The skills form one pipeline:

```
plan-brainstorming (specs + <goal>-roadmap.md, then stops) → plan-writing → [plan-splitter] → plan-executor → plan-resolver
                                  plan-iterative-revision (usable at any stage)
plan-chain-runner — runs approved specs of one goal through writing → revision → [split] → execution → audit → commit
writing-skills — meta-skill for authoring/testing new skills
```

`skills.sh.json` groups the skills for the skills.sh catalog. Update it when adding a skill.

## Commands

Python ≥ 3.8, **stdlib only**. Never add third-party dependencies to scripts. Tests use `unittest` and run under pytest.

```bash
python -m pytest skills -q                                   # all tests
python -m pytest skills/plan-executor/tests/ -q              # one skill
python -m pytest skills/plan-resolver/tests/test_resolver_tool.py -k census   # single test/filter
python skills/<skill>/scripts/<tool>.py <command> [args...]  # run a helper CLI directly
```

Tests load the script by file path through `importlib.util.spec_from_file_location` (the scripts are not packages), and they also call it as a subprocess to check exit codes and JSON output.

## Skill anatomy

```
skills/<name>/
  SKILL.md      YAML frontmatter (name MUST equal directory name; description = 2–4 sentence trigger hint, no keyword stuffing) + core instructions
  USAGE.md      human quick reference; update when invocation arguments change
  references/   detailed phase docs loaded on demand from SKILL.md (part of the skill's published contract; don't change them casually)
  scripts/      single-file Python CLI tool; returns JSON, exit 2 = input error, exit 1 = contract/state error
  assets/       output templates (paired *.en.md / *.ru.md; keep both languages in sync), JSON schemas
  tests/        pytest/unittest for the script
```

Skills refer to their own scripts as `python "<SKILL_DIR>/scripts/<tool>.py"` (absolute path), because they run from the user's project directory rather than from this repo.

## Design rules

**Deterministic/LLM boundary.** The main design rule. Exact, cheap operations (parsing plans, hashing, ledger state, validation, set algebra over issue fingerprints) live in the skill's Python CLI and return JSON plus machine-readable exit codes. Semantic judgment lives in `SKILL.md` and `references/*.md`. When a behaviour changes, decide which side it belongs on; a change usually needs both a script update (with tests) and a reference-doc update that describes how the agent calls it.

**Shared paragraphs.** Three paragraphs are repeated word for word across the pipeline skills and must stay identical when edited anywhere: the **External systems** rule (databases, APIs and remote services are off limits without the user's explicit permission for a named environment; plans list `**Environments:**`, tasks declare `**External:**`, pre-approved reads come from `read=run` in the spec's `> Environment:` line, changes on production are never pre-approved), the **Dialogue language** paragraph in `## Language` of all seven pipeline `SKILL.md` files (the skill talks to the user in the language of the primary task; `ru` when more than 5% of letters are Cyrillic, detected by each tool's `detect-lang`/`lang` field; only parser tokens stay English) and the **Free backlog** paragraph right after it in the same section, quoted whole below (`plan-writing/tests/test_shared_paragraphs.py` compares the copies). Take the current wording from any pipeline `SKILL.md`.

**Free backlog.** `BACKLOG.md` at the repository root is a free file: the user writes to it at any moment, and no stage treats a change to it as a foreign change.

**Commits by skills.** Only `plan-executor` commits on the user's branch, and only through `executor_tool.py commit-run` (in a chain after the audit, or by hand with `/plan-executor <plan> commit`), with the repository hooks and never `--no-verify`, `--amend`, `--force` or push. Per-unit snapshots are hidden refs. `plan-resolver` is git-read-only in every phase. Without git the `diffs` and `commit` stages are `skipped`.

**Ledger.** The execution ledger (`state.json`, `assets/ledger.schema.json`) is changed only through `executor_tool.py`.

## Helper CLIs

One Python tool per skill. Every command, flag, field and error code is described in the skill's `USAGE.md` and `references/`, and consolidated in `docs/HELPER-CLIS.md`; this table names only what each script owns.

**Stability of this file.** `CLAUDE.md` changes only on a structural event: a skill is added or removed; a script is added, renamed or moved; a cross-skill contract changes (a format parsed by another skill, the chain journal); a convention changes; a new artifact must never be committed. A new command, flag, field or error code is not such an event: it goes to the skill's `USAGE.md`, `docs/HELPER-CLIS.md` and, for a technique, `docs/TECHNOLOGIES.md`. A plan task that modifies `CLAUDE.md` must name the structural event it serves.

| Script | Owns |
|---|---|
| `plan-brainstorming/scripts/brainstorm_tool.py` | The formats shared by all skills: the spec contract and size budget, chain settings (the only parser of `> Chain:`/`> Environment:`/`> Backlog:` and `**Chain:**`/`**Environments:**`/`**Backlog:**`), the plan task parser, the shared `BACKLOG.md`, the chain journal `<goal>-chain.json` (schema in `assets/chain-journal.schema.json`), findings, the goal roadmap `<goal>-roadmap.md`. Also a Node visual-companion server (`server.cjs`). |
| `plan-writing/scripts/plan_tool.py` | The plan format contract (`plan-check`), plan paths, the plan skeleton. Reference plan in `tests/fixtures/`. |
| `plan-iterative-revision/scripts/next_review_index.py` | The review loop: bootstrap, the single authority for loop gates and issue fingerprints, review/completion files, audit scope, diff-guard snapshots. Fixtures in `.fixtures/`. |
| `plan-splitter/scripts/splitter_tool.py` | The split gate, parts `<base>-a.md`, `<base>-b.md`, … and `<base>-roadmap.md`: writing, validation, verify ledger. |
| `plan-executor/scripts/executor_tool.py` | The execution ledger and run loop, snapshots as hidden refs `refs/plan-executor/<run>/<unit>`, the diff report `<base>-diffs.md`, the run commit. |
| `plan-resolver/scripts/resolver_tool.py` | The audit: workspace fingerprint and read-only guard, report parsing and validation, task census, incremental re-audit scope, the fix loop. |
| `plan-chain-runner/scripts/chain_tool.py` | The runner's deterministic scheduler, the journal's `runner` section, settings and sessions (`~/.planforge/`, `PLANFORGE_HOME`), run statistics and cost. Host profiles `claude-code`, `github-copilot`, `fallback`. |

## Cross-skill contracts

- **`brainstorm_tool.py` is loaded by path** (`../plan-brainstorming/scripts/brainstorm_tool.py`, `importlib`) by `plan_tool.py`, `executor_tool.py`, `next_review_index.py` and `chain_tool.py`, and called as a CLI by every pipeline agent (settings, backlog, journal). Skills must be installed side by side; without it settings come back empty with the warning `plan-brainstorming not installed alongside` and the skills run without a journal (`chain_tool.py` journal commands fail with exit 2). Don't rename or move that script or `plan-brainstorming/references/spec-contract.md`.
- **Output formats are contracts between skills.** Roadmap/part formats are parsed by `splitter_tool.py`, `executor_tool.py parse-roadmap` and `next_review_index.py parts`; part ids are letters and the three parsers must agree. Plan task headings `### Task N: <title>` are enforced by `plan-check` and parsed by the executor and the resolver's `task-census`. `**External:**`, `**Size:**` and `**Structural event:**` lines are task lines: `plan-check` checks them, the splitter carries them into parts verbatim and `validate-all` compares them. The writing marker `> Writing: in progress (spec sha256 <12 hex>)`, the last line of a plan `plan-writing` is still writing, is read the same way by `plan-check` (`plan-incomplete`), `parse_plan_tasks` (`incomplete`), the splitter preflight, `ledger-init` and the revision `bootstrap`: an unfinished plan goes nowhere. `plan-writing/tests` holds the contract tests against the other parsers.
- **The chain journal is a contract** (stage names, statuses, transitions, owners, artifact keys) between the six skills and `plan-chain-runner`, which schedules by it and owns its optional `runner` section; `plan-writing/tests/test_journal_contract.py` replays the event sequence against `journal-validate` and `journal-show`.
- **The runner launches skills by name and arguments** returned by `run-next` (`/plan-writing <spec>`, `/plan-executor <plan or roadmap>`, `/plan-resolver <plan> fix|auto`, `/plan-executor <plan> commit`, …) and takes the roadmap from the `split` stage's artifacts. A change of a skill's arguments or stage artifacts must be checked against `chain_tool.py`.
- **The goal roadmap `<goal>-roadmap.md` is a contract** between `plan-brainstorming` (`roadmap-write`, `roadmap-check`, `roadmap-parse`, `GOAL_ROADMAP_RE`) and `plan-chain-runner`, which takes it as its argument (`/plan-chain-runner <goal>-roadmap.md`) and reads it in-process through `brainstorm_tool.parse_goal_roadmap` (`run-init --roadmap`, `subset-check`, `run-status`). A change of its `## Order` table or `> Goal:` line must be checked against `chain_tool.py`.
- **`chain_tool.py` loads `splitter_tool.py` by path** (`../plan-splitter/scripts/splitter_tool.py`) for `gate_verdict`, the numeric gate of `split=auto`: `keep` skips the split stage without an agent; without the splitter, or when the gate fails, the stage runs as before with the warning `gate-unavailable`. `splitter_tool.py` needs `brainstorm_tool.parse_plan_tasks` in turn: `gate`, `split-write` and `validate-all` exit 2 without it. Don't rename `gate_verdict` or `GATE_THRESHOLDS`.
- A format change in one skill must be checked against the parsers in the others.

## Conventions

- Commits: `<type>(<scope>): <subject>`. Type is one of feat/fix/docs/refactor/test/chore/ci/perf/style. Scope is a skill name, `readme`, `docs`, `scripts`, or omitted. The subject is imperative and lowercase, with no period and at most 72 characters. Run the modified skill's tests before committing.
- Never commit user-workspace artifacts generated by the skills: `*-ledger.json`, `*-review-*.md`, `*-report-*.md`, `.exec/`, `*-chain.json`, `*-diffs.md`, `*-followups.json`, `*-roadmap.md`.
- The agent stages specific paths (never `git add .`), shows the staged diff, and waits for user confirmation before committing. It never pushes without explicit approval.
- Keep changes surgical and traceable to the request. Don't refactor adjacent code.
- New skills: follow `skills/writing-skills/SKILL.md` (TDD for skills, behavioural testing with subagents).
- Markdown uses ATX headings and fenced code blocks with language tags. File names are kebab-case.
- `docs/USERGUIDE.md`, `docs/TECHNOLOGIES.md`, `docs/HELPER-CLIS.md` and the README "Technical Design" section describe each skill's techniques and tools. Update them when a technique or a command changes.
