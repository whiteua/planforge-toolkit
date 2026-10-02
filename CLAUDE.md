# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

PlanForge Toolkit is a collection of **agent skills** (agentskills.io `SKILL.md` convention), not an application. Each directory under `skills/` is an independently installable skill, distributed via `npx skills add whiteua/planforge-toolkit` or by symlinking `skills/<name>` into an agent's skills directory. Rolling release: every push to `main` is a release, so there are no version tags.

The skills form one pipeline:

```
plan-brainstorming → plan-writing → [plan-splitter] → plan-executor → plan-resolver
                                  plan-iterative-revision (usable at any stage)
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

## Skill anatomy and architecture

```
skills/<name>/
  SKILL.md      YAML frontmatter (name MUST equal directory name; description = 2–4 sentence trigger hint, no keyword stuffing) + core instructions
  USAGE.md      human quick reference; update when invocation arguments change
  references/   detailed phase docs loaded on demand from SKILL.md (part of the skill's published contract; don't change them casually)
  scripts/      single-file Python CLI tool
  assets/       output templates (paired *.en.md / *.ru.md; keep both languages in sync), JSON schemas
  tests/        pytest/unittest for the script
```

**External systems.** Every skill treats a database, API or remote service as off limits without the user's explicit permission for a named environment; a permission is never widened, and a project script aimed at another environment is not permission. Plans list environments with the user's quoted words (`**Environments:**`), tasks declare `**External:**`, the executor asks before running them, the revision and the resolver flag violations. Pre-approved reads (`read=run` in the spec's `> Environment:` line, production included) cover the plan's steps and the read-only checks of plan-iterative-revision and plan-resolver; changes on production are never pre-approved. Keep this rule identical across the skills when editing any of them.

**Dialogue language.** Every skill talks to the user in the language of the primary task (the goal or findings for `plan-brainstorming`, the plan for the later skills): questions, option labels and descriptions in question UIs, status lines, confirmations, human gates, final summaries and stop reports. Only parser tokens stay in English; sample phrases quoted in skill instructions are templates said in the dialogue language. The language is detected with one threshold (`ru` when more than 5% of the letters are Cyrillic, otherwise `en`): `brainstorm_tool.py detect-lang` and `spec-check` (`lang`), `plan_tool.py plan-check` (`lang`), `next_review_index.py bootstrap` (`lang`), `splitter_tool.py detect-lang`, `executor_tool.py detect-lang`, `resolver_tool.py bootstrap` (`language`). The rule is an identical `**Dialogue language.**` paragraph in `## Language` of all six pipeline `SKILL.md` files, followed by one skill-specific "In this skill:" line. Keep the paragraph identical across the skills when editing any of them.

**Deterministic/LLM boundary.** This is the main design rule of the repo. Exact, cheap operations (parsing plans, hashing, ledger state, validation, set algebra over issue fingerprints) live in the skill's Python CLI and return JSON plus machine-readable exit codes. Semantic judgment lives in `SKILL.md` and `references/*.md`. When a behaviour changes, decide which side it belongs on. A change often needs both a script update (with tests) and a reference-doc update that describes how the agent calls it.

Helper CLIs:
- `plan-executor/scripts/executor_tool.py`: argparse subcommands registered through `_register(...)` into `COMMANDS`, with a JSON result printed by `main`. It owns the execution ledger (`state.json`, schema in `assets/ledger.schema.json`). The ledger must be changed only through this tool. The agent loop uses `ledger-init`, `unit-begin` (next unit + strategy + that unit's text and files, marks it running) and `unit-finish` (snapshot + done, or failed + retry/stop decision). Whole plans: only `Task`/`Задача` headings become units when present, headings in code fences are ignored, units are strictly sequential, `**Tier:**` sets the weight. Snapshots are hidden refs `refs/plan-executor/<run>/<unit>` built with a temporary index and `commit-tree` (no branch commits). The ledger (v2) stores the plan SHA-256 for `plan-drift` detection. Errors are JSON with exit 2 (input) or 1 (contract). `ledger-init auto` puts the ledger in `<repo parent>/.exec/<repo>-<plan>/` and refuses temp dirs; `unit-begin` reports `external` lines (units that need confirmation), task weights are lowered for checkpoint/docs/test-only tasks, `unit-finish --note` records agreed deviations, `run-diff` shows what the run changed. `ledger-init` also stores the chain settings (`settings`, and `settings_source` with the SHA-256 of the spec or plan header they came from); on resume it clears `consents` and stops with `settings-drift` (`changed_keys`) when that file changed, unless `--accept-drift`. `unit-begin` returns `external` as `{env, access, kind, consent, confirmed, source}` objects and first compares the working tree with the ledger's `expected_tree`: a difference gives `reason: foreign-changes` with `foreign_changes: [{path, status}]` (skipped for an in-progress unit, `null` outside git, `BACKLOG.md` ignored). `consent <exec_dir> <env> read|write` records a run-scope consent (refused for prod writes, for `deny` and for unknown environments); `accept-changes [--note]` takes the current tree as expected and logs a `foreign_events` entry; `checkpoint-restore --paths P …` restores only the listed files, and `--exec-dir D` moves `expected_tree` (every restore the executor makes itself passes it).
- `plan-splitter/scripts/splitter_tool.py`: hand-rolled `argv` dispatch in `main`. Parts are named `<base>-a.md`, `<base>-b.md`, … (`part_id`, bijective base-26) with the roadmap at `<base>-roadmap.md`. It handles preflight, part and roadmap validation, and the verify baseline/record/status commands; `verify-record` turns plan-iterative-revision's batch JSON into the verify ledger.
- `plan-resolver/scripts/resolver_tool.py`: argparse. It handles bootstrap, preflight, SHA-256 `fingerprint-workspace` plus `assert-readonly <start> <current> <allowed> [<allowed> …]` (the resolver writes only its report and `BACKLOG.md`), report parsing and validation (`validate-report --root` also verifies evidence anchors against the workspace), the stuck-open gate inside `bootstrap`, `snapshot-diff`, the fix-loop commands (`discover`, `open-issues`, `protect`, `mark-fix`, `cycle-check`), and `task-census` (every plan task must be covered in the report). `validate-report --plan` lets only tasks without code files be closed by `evidence_probe`, and lists `verification: executor-reported` tasks as warnings.
- `plan-iterative-revision/scripts/next_review_index.py`: hand-rolled dispatch. `bootstrap` starts a run and returns `settings` (plan header, else the spec at `**Spec:**`; a roadmap goes through its Source link); `record` takes the agent's issues JSON and is the single authority for loop gates (clean/converged/drain/regression/unchanged/churn/stuck/limit over the current run's history). It also computes the fingerprints (SHA-1 of category + required fix, first 8 characters), then renders, writes and strictly validates the review or completion file. `guard-begin`/`guard-check` keep diff-guard snapshots in the OS temp dir. The low-level commands (`validate-review`, `flow-analyze`, `digest`, ...) remain; `plan-splitter` calls `validate-review`. Fixtures are in `.fixtures/`.
- `plan-writing/scripts/plan_tool.py`: argparse. `plan-path` (`<X>-spec.md` → `<X>-impl.md`) and `plan-check` (plan format contract, including the `**Environments:**` header block with quoted user permissions and per-task `**External:**` lines: `**Spec:**`/`**Tier:**` header, task headings and unique ids, task core per tier, backticked file paths, no commit steps, no placeholders; `--root` checks Modify targets). Reference plan in `tests/fixtures/`. `plan-check` reads the chain settings through `brainstorm_tool.resolve_settings` (plan header, else the spec at `**Spec:**`) and returns `settings`, `task_count`, `plan_bytes`, `lang` and `oversized`. It checks `` **External:** `name` (read|write) `` against the environment's `read=`/`write=` rights and the size rule: more than 100 lines of code in a task without `**Size:** <N> lines — <reason>` warns, more than 150 fails.
- `plan-brainstorming/scripts/`: a Node visual-companion server (`server.cjs`, started with `start-server.sh`), plus `brainstorm_tool.py` (argparse). It handles `spec-check` (spec contract: 8 headings in order, empty Open Questions, Tier line), `findings-parse` (validates a JSON findings list, assigns ids `F1..Fn`, checks file/line against `--root`) and `findings-coverage` (every finding id is mentioned in the spec). It also owns the formats other skills load: `detect-lang` (`ru` when Cyrillic letters are over 5% of all letters), `settings` (`resolve_settings`, the single reading rule for chain settings; `spec-check` validates the `> Chain:`, `> Environment:` and `> Backlog:` lines and returns `lang`, `chain`, `environments`, `backlog`), and `backlog-append` / `backlog-parse` for the shared `BACKLOG.md` at the repository root (append to the end of a goal's section only; every other byte must stay unchanged).

**Cross-skill coupling.** `plan-writing` runs `../plan-brainstorming/scripts/brainstorm_tool.py spec-check` by relative path, so both skills must be installed side by side. `plan_tool.py`, `executor_tool.py` and `next_review_index.py` also load `../plan-brainstorming/scripts/brainstorm_tool.py` by path (`importlib`, no subprocess) for `resolve_settings`; the splitter and resolver agents call its `settings` CLI, and the executor and resolver agents call its `backlog-append`. Without it the settings come back empty with the warning `plan-brainstorming not installed alongside`. The settings lines (`> Chain:`, `> Environment:`, `> Backlog:`, `**Chain:**`, `**Environments:**`, `**Backlog:**`) are parsed only there, and the task lines `**External:**` and `**Size:**` are carried into split parts verbatim. Don't rename or move that script or `references/spec-contract.md`. Output formats are also contracts between skills: splitter roadmap/part formats are parsed by `executor_tool.py parse-roadmap` and by `next_review_index.py parts` (batch mode); part ids are letters and the three parsers must agree, and plan task headings (`### Task N: <title>`) are parsed by both the executor and the resolver's `task-census`; `plan_tool.py plan-check` enforces that format, and `plan-writing/tests` holds contract tests against both parsers. A format change in one skill must be checked against the parsers in the others.

Skills refer to their own scripts as `python "<SKILL_DIR>/scripts/<tool>.py"` (absolute path), because they run from the user's project directory rather than from this repo.

## Conventions

- Commits: `<type>(<scope>): <subject>`. Type is one of feat/fix/docs/refactor/test/chore/ci/perf/style. Scope is a skill name, `readme`, `docs`, `scripts`, or omitted. The subject is imperative and lowercase, with no period and at most 72 characters. Run the modified skill's tests before committing.
- Never commit user-workspace artifacts generated by the skills: `*-ledger.json`, `*-review-*.md`, `*-report-*.md`, `.exec/`.
- The agent stages specific paths (never `git add .`), shows the staged diff, and waits for user confirmation before committing. It never pushes without explicit approval.
- Keep changes surgical and traceable to the request. Don't refactor adjacent code.
- New skills: follow `skills/writing-skills/SKILL.md` (TDD for skills, behavioural testing with subagents).
- Markdown uses ATX headings and fenced code blocks with language tags. File names are kebab-case.
- `docs/USERGUIDE.md` and `docs/TECHNOLOGIES.md` and the README "Technical Design" section describe each skill's techniques. Update them when a technique changes.
