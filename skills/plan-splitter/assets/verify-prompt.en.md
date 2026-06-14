Run a deep verification of the micro-plans via plan-iterative-revision?

- Scope: `all` — every stage · `stgNN[,stgNN...]` — selected · `none` — skip.
- Depth: `quick` · `standard` · `deep`.
- Mode: `full-cycle` (edits stages, default) · `audit-only` (report only).

Verification runs silently; you'll get a summary when it's done.

--- Subagent contract ---

Each subagent MUST:
- read `plan-iterative-revision/SKILL.md`;
- run that exact skill with `interaction=autonomous`, the selected `preset`, and mode `full-cycle` or `audit-only`;
- operate only on the supplied `stgNN.md` file and its review artifacts;
- return strict JSON: `{"result":"clean|converged|stagnation|limit|escalated","iterations":N,"remaining_issues":N}`.

Forbidden:
- replacing `plan-iterative-revision` with a manual/ad-hoc audit;
- asking the caller A/B/C or any other interactive question;
- using `audit-only` as a shortcut to bypass the review artifact;
- reporting success without the artifacts required by `plan-iterative-revision` and the machine ledger.