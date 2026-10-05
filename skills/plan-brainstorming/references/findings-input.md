# Findings Input

How to brainstorm when the input is a JSON list of code-review findings
instead of a free-form idea. The goal is the same: an approved spec that
satisfies `spec-contract.md`. The findings are the problem statement, not
the design.


## Input Format

A JSON array of objects. It may also be wrapped as `{"findings": [...]}`.
The input can be a path to a `.json` file or JSON pasted inline.

| Field | Required | Meaning |
|---|---|---|
| `file` | yes | Repo-relative path of the defect. |
| `line` | no | 1-indexed anchor line (positive integer). |
| `summary` | yes | One-sentence statement of the defect. |
| `failure_scenario` | yes | Concrete input/state → wrong output/crash. May suggest a fix. |
| `category`, `short_summary`, `verdict`, `outcome` | no | Passed through unchanged. |

Unknown fields are kept and reported as warnings. They are never errors.

## Step A: Parse (deterministic)

Run the helper before reading any code:

```bash
python "<SKILL_DIR>/scripts/brainstorm_tool.py" findings-parse <findings.json> --root <project-root>
# inline JSON: pipe it on stdin and pass "-" instead of a path
```

- Exit `0`: use the returned `findings`. Each one has an `id` (`F1`..`Fn`,
  in input order). Use these ids everywhere from now on.
- Exit `1`: show the `errors` list to the user and stop. Do not guess the
  missing fields.
- Exit `2`: unreadable input or invalid JSON. Show the error and stop.
- `warnings` do not block. `location: file_missing` or `line_out_of_range`
  means the finding may be stale. Check it in Step B.

## Step B: Triage (semantic)

A finding is a claim to check, not a fact. For each one, read the code at
`file:line`, trace the `failure_scenario`, and give it a verdict:

| Verdict | Meaning |
|---|---|
| confirmed | The code behaves as the scenario says. |
| partial | The defect is real, but the scenario or root cause is not quite right. Say what differs. |
| disputed | The code contradicts the claim. Cite the lines. |
| stale | The file or line no longer matches (moved, fixed, or deleted). |

Investigate, don't ask: the code answers these questions. Group findings
that share a root cause, because one fix should cover them all.

More than 10 findings: if the host supports subagents, give each file
group (`by_file` from Step A) to one subagent. Each subagent returns only
`id`, verdict, cited lines, and root cause. You merge the results and build
the table; subagents never edit code.

Show a compact triage table (id, `file:line`, one-line summary, verdict,
root-cause group) in the message where you state the depth tier (checklist step 2).

## Step C: Scope (checklist step 4, first question)

Ask one question: which findings go into this spec? Use a multi-select
option when the interactive channel supports it. Recommend all `confirmed`
and `partial` findings. If there is only one finding and it is confirmed,
state the scope instead of asking.

- Apply the normal decomposition rule. If the selected findings fall into
  independent subsystems, recommend one spec per subsystem and brainstorm
  the first one.
- Excluded findings go to `## Out of Scope` with their id and the reason
  (disputed, stale, deferred).

## Tier

Apply the `depth-tiers.md` heuristic to the selected findings together.
Do not rate them one at a time. A failure scenario that involves
concurrency, security, data loss, resource exhaustion, or a hang is the
"concurrency/security/perf is a stated concern" signal, so the tier is Deep.
A single confirmed defect in one file with no such signal is Quick.

## Clarifying Questions and Approaches

- Ask about the intended behavior after the fix, not the defect itself.
  Examples: reject the input or clamp it; fail fast or retry; which error
  the caller sees.
- A fix suggested inside `failure_scenario` is one candidate approach, not
  a decision. Put it next to 1-2 alternatives and compare the trade-offs.
- Give approaches per root-cause group, not per finding.

## Spec Mapping

The 8 contract headings stay unchanged. Findings map into them as follows:

| Section | Content from findings |
|---|---|
| `# Goal` | One sentence: which defect class is removed. Not a list of ids. |
| `## Components` | Normal content, plus a `### Findings Traceability` table: `ID \| Location \| Root cause \| Fix (component) \| Regression test`. One row per selected finding. |
| `## Error Handling` | The new, intended behavior for each failure scenario. |
| `## Testing Strategy` | One regression test per selected finding. It reproduces the `failure_scenario` and fails before the fix. |
| `## Out of Scope` | Every excluded finding, as `F<n>: <reason>`. |

Each finding id appears either in the traceability table (selected) or in
`Out of Scope` (excluded). Other sections may also cite ids.

## Coverage Gate (deterministic)

Right after `spec-check` passes, run:

```bash
python "<SKILL_DIR>/scripts/brainstorm_tool.py" findings-coverage <findings.json|-> <spec-path>
```

Exit `1` lists `missing` ids (not mentioned anywhere). `unknown` ids (an
`F<n>` token that is not a finding, e.g. a lint code) are only a warning.
Fix the spec and re-run until it exits `0`. The coverage check proves each id is mentioned. Whether it sits in the
right section is checked in the self-review.

## Spec Path

- Findings from a file `<dir>/<name>.json`: `<plan-root>` is derived from
  `<name>` with the usual rule. The spec is `<dir>/<plan-root>-spec.md`.
  Example: `review01.json` → `review01-spec.md`.
- Inline JSON: there is no file to derive the path from. Ask for the spec
  path and recommend a default.
- Several specs from one findings list (after decomposition): numeric
  suffixes by default, `review01-1-spec.md`, `review01-2-spec.md`, …
  (`spec-contract.md`, "Artifacts and naming"); a descriptive suffix
  (`review01-conn-spec.md`) only when the user asks for it.
  `plan-writing` maps each to its own plan (`review01-2-impl.md`).
  Each spec lists the other specs' finding ids in `Out of Scope` with a
  pointer to the spec that covers them, so `findings-coverage` passes for
  every spec.

## Findings among several inputs

With several inputs (`inputs` → `mode: multi`) a findings JSON is one of them. Steps A-C run for
the part of the goal that takes the findings (the instruction says which; otherwise ask), and
`findings-coverage` runs on the spec that takes them. A findings JSON alone is findings mode as
above.
