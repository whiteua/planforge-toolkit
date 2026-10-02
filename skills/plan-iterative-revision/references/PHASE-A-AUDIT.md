# Phase A: Audit

Goal: find every problem in `PLAN` and hand the list to `TOOL record` as JSON. Phase A edits no
file; `record` writes the review.

## Inputs

- `PLAN`, the config from `bootstrap` (`lenses`, `rigor`), the audit number `k`.
- For `k > 1`: the digest `D` from `TOOL digest <dir> <basename> --since <run_start>`:
  `active_contracts` (issues of the latest review, with full `required_fix` and `acceptance`) and
  `resolved_contracts` (issues of earlier reviews in this run that are no longer open).

Read `PLAN` once, in full. If the Phase B self-check just read the whole plan and nothing changed
since, reuse that text instead. Lenses and taxonomy classes are checklists over the text you already
have; do not re-read the plan for each of them. Do not read old review files in full. Read a single
issue block only when the digest entry is not enough.

## Step 1: Contract verification (k > 1)

For every entry of `D.active_contracts`, check the current plan against its `required_fix` and
`acceptance`:

- Fully applied: nothing to record.
- Not applied or only partly applied: add a **carry** issue:

  ```json
  {"carry": "<fingerprint>", "severity": "<one step higher, max blocker>",
   "code_cross_check": "not applicable — contract check", "problem": "<what is still missing>",
   "evidence": "<plan quote>"}
  ```

  `record` copies the category, required fix, title, location and acceptance from the earlier
  review, so the fingerprint stays the same. Never re-state an open contract as a new issue with
  different wording: that breaks stuck and regression detection.

If a `resolved_contracts` entry is broken again, record it with `carry` as well; `record` treats
that as a regression.

## Step 2: Lenses

Run `lenses` passes; each one has a focus:

| Lens | Enabled when | Focus | Main classes |
|---|---|---|---|
| L1 | always | engineering + code cross-check | `code`, `db`, `ops`, `perf`, `security`, `math`, `code-plan-mismatch` |
| L2 | lenses ≥ 2 | logic, coherence, contracts | `logic`, `contract` |
| L3 | lenses ≥ 3 | completeness, edge cases, acceptance criteria | `tests`, missing scenarios |
| L4 | lenses = 4 (`deep`) | red team: triggers, failure modes, production consequences, abuse | `security`, `ops`, `logic` |

- With `lenses = 1`, L1 covers all 10 classes of [ERROR-TAXONOMY.md](ERROR-TAXONOMY.md).
  With more lenses, the column is a priority, not an exclusive scope.
- Within a lens, go class by class and ask the questions from the taxonomy. One class at a time
  keeps attention focused.
- An L4 issue is valid only if its `required_fix` names the trigger condition and the production
  consequence.
- Duplicates across lenses are fine: `record` merges issues with the same fingerprint and keeps
  the highest severity.

## Step 3: Code cross-check (mandatory)

A plan that is not checked against the code is fiction. The cross-check means reading the repository and running local commands without side effects (build, offline tests, grep). Anything that reaches an external system — a database, an API, a remote service, a cloud account — even a constant query, runs only after the user explicitly allows it and names the environment. A permission covers the named environment only: never extend it to another one, and never treat an existing project script that targets another environment as permission. Production needs a separate confirmation for every action. Pre-approved reads (`read=run` in the spec's `> Environment:` line, production included) cover the plan's steps and the read-only checks of plan-iterative-revision and plan-resolver; changes on production are never pre-approved.

The rights come from `B.settings.environments`. On an environment with `read=run` the cross-check
may run read-only queries (no writes, no migrations, no project script that changes state) and
cites the query and its result in `code_cross_check`. With `read=task`, `read=deny` or no rights,
the claim stays `ambiguous` unless the user allows the check.

Depth depends on `rigor`:

- `grep`: `Grep`/`Glob` for the symbols and paths the plan mentions.
- `read` (standard): additionally `Read` the definitions you found.
- `explore` (deep): additionally delegate large modules or subsystems to an `Explore` subagent.

| Plan mentions | Check in code |
|---|---|
| File path | the file exists and is live |
| Class, function, type | `Grep` for its definition |
| Signature | `Read` the definition, compare parameters and return type |
| Table or column | models, entities, `schema.sql`, migrations |
| HTTP endpoint | routing: method, path, payload |
| Env variable or config key | `.env*`, `appsettings*.json`, `config/` |
| Package or dependency | `package.json`, `*.csproj`, `requirements.txt`, `Cargo.toml` |
| Migration | the migration file itself |
| Command in a step (`npm run x`, `make y`) | the project script it runs: which environment it really targets |

Explore prompt for a large module:

> Quick exploration: how is X implemented today? What public API does it expose? Return: public
> methods with signatures, related DB tables, current behavior in 3-5 bullets. Do not edit anything.

Environments: a step that runs on an environment not listed under `**Environments:**` in the plan
header or in the spec's `> Environment:` lines (`B.settings.environments`), or on production when
only a test environment is permitted, is a `blocker` of category `ops`, even when the command
itself is harmless. Pre-approved reads (`read=run` in the spec's `> Environment:` line, production included) cover the plan's steps and the read-only checks of plan-iterative-revision and plan-resolver; changes on production are never pre-approved.
A "user decision" stated in the plan without the user's quoted words is `major`. Differences from
the spec listed under `**Deviations from spec:**` are agreed; unlisted ones are issues.

Every checked claim gets one status: `verified`, `not found`, `ambiguous`, `not applicable`.
`not found` and `ambiguous` usually become issues when the plan depends on the object.
Objects the plan itself creates (new tables, endpoints, files) are `not applicable`; still check
that nothing with the same name already exists, since a collision is an issue.

Reuse inside a run: the skill never changes code, so a claim you verified in an earlier audit
stays verified while its text in the plan is unchanged. Always re-check claims that were
`not found` or `ambiguous`, and raise the depth to at least `read` for them.

## Severity

- **blocker**: the plan cannot be implemented as written (contradiction, reference to missing
  code, schema change that breaks production, migration without rollback).
- **major**: implementing the plan leads to a serious bug or rework (wrong signature, missing
  index, no acceptance criteria for a key feature).
- **minor**: lowers quality without blocking (missing edge case, stale file name, trivial test).
- **nit**: style, numbering, formatting. Report only when there are many and they get in the way.

## Output: the issues JSON

Write all text in the plan's language. Pass the JSON to `record` as a file in the OS temp
directory (never inside the repository) or on stdin.

```json
{
  "summary": "1-3 sentences: overall state of the plan and nature of the problems.",
  "audit_state": {
    "previous_contracts": "yes | no | n-a",
    "previous_contracts_notes": "3 contracts checked, 1 carried",
    "taxonomy": "yes | partial",
    "code_cross_check": "yes | partial",
    "code_cross_check_notes": "12 claims: 10 verified, 1 not found, 1 ambiguous",
    "lenses_used": 2
  },
  "issues": [
    {
      "severity": "major",
      "category": "code-plan-mismatch",
      "title": "Short title",
      "location_in_plan": "## 3. Data model / 3.2",
      "location_in_code": "src/models/user.ts:42",
      "code_cross_check": "not found — no column `role_id` in migrations",
      "problem": "What is wrong and why it matters.",
      "evidence": "> Plan: ...\n\n```ts\n// code quote\n```",
      "required_fix": "Unambiguous contract: what the plan must say after the fix.",
      "acceptance": "How to check the fix in the plan text."
    }
  ],
  "notes": "Optional hints for Phase B."
}
```

- `category`: `logic`, `code`, `math`, `ops`, `db`, `contract`, `tests`, `security`, `perf`,
  `code-plan-mismatch`. (`unfulfilled-contract` exists only in old reviews; use `carry` instead.)
- `code_cross_check` must start with one of the four statuses.
- `location_in_code` and `evidence` are optional; every other field is required.
- The fingerprint is `category` + the first 200 characters of `required_fix` (whitespace
  normalized). `record` computes it; you never do.
- An empty `issues` list means the plan is clean.
- Code quoted inside a JSON string needs its backslashes doubled: a literal `\n` in code is
  `\\n` in JSON, otherwise it becomes a line break and the contract text is corrupted. Safest:
  build the JSON with a script (`json.dump`) instead of typing it. `record` returns `warnings`
  when a contract line has an unbalanced quote; fix the input and record again only if the
  review file was not written (exit code 2), otherwise note it for the next audit.

`record` rejects invalid input with exit code 2 and writes nothing; fix the JSON and call it again.
