# DISCUSS

`/plan-chain-runner discuss [<goal>]` (`обсудить`): the open questions of the journal, one at a time, inside the runner. `C` and `J` as in SKILL.md, Tool. Nothing is launched here; the answers are applied by `continue`.

## Order

1. Find the journal (SKILL.md, Commands); `C run-status <journal>`. A session is active and a stage `audit` is `running` → record nothing: say that an audit is running (any write to the journal or the working copy would invalidate it) and offer to come back when it has ended. Then `J journal-show <journal>`.
2. No open questions → say so, list the `waits` of `run-status` if any (below), and offer `continue`.
3. Group `open_questions` by plan, in the run's order (`run-status`); inside a plan by question id. One question per message.
4. After the questions, the `waits` of `run-status`: plans that wait without an open question (`stage-failed: stop`, `not-confirmed: stop`, a `model:` answered `stop`, and the plans held by them with `code-busy: <plan id>`). For each say which stage stopped and how to lift the wait: run that stage by hand (`/<skill> <args>`, then `continue`), or fix the cause and run the stage by hand; the runner does not ask about it again.

## One question

Give, in the dialogue language:

- **What stopped:** the plan, the stage, the skill that asked, and a link to the artifact the question is about (the review, the report, the ledger, the diff report; from the journal file's `plans[].stages.<stage>.artifacts`). Read that artifact before you recommend.
- **The options:** the question's `options`, explained in one line each.
- **A recommendation and its reason**, from the artifact and the specs, not from habit.

Then record the user's choice: `J journal-answer <journal> <Qn> --answer "<answer>"`.

- **Machine questions** (text starts with `open-audit: `, `not-confirmed: `, `stage-failed: `, `drift: `, `model: `): show the options in the dialogue language, record exactly one token (the one exception is `model: <role>`, below): `accept` or `fix` (open audit of a plan others depend on: accept it as it is, or fix it first); `retry` or `stop` (a stage not confirmed or failed twice); `rewrite` or `keep` (the spec or plan changed after the stage: `rewrite` enters this stage and every later stage of the plan again, `keep` keeps this stage as it is). For `model: <role>` (the host refused the role's model and its fallback) record `retry <model>` with the model the user names for that role, `retry` alone to try the same model again, or `stop`; `retry <model>` is the only answer of two tokens.
- **Drift of several stages:** a rewritten spec or plan stops the plan once. Take the plan's earliest `drift:` question first; after `rewrite` there, skip that plan's later `drift:` questions: the runner answers them `rewrite` itself on `continue` (LOOP.md, Drift cascade). After `keep` the next one is asked.
- **Other questions** (written by a skill): record the chosen option as it is, or the user's own words when none fits.

## Two kinds of answer

- **The course of the chain** — commit, raise a limit, accept foreign changes, accept the open audit, retry, keep the plan: recorded now; the stage's owner applies it on `continue` and marks it `--applied`.
- **A change of the spec** — the answer changes the Goal, Components or Out of Scope of a spec: do not record it now. The question stays open, so that plan and the plans depending on it keep waiting while the others go on. Say: amend the spec with `/plan-brainstorming <spec>` (amend mode: the skill changes only that, checks it with `spec-check` and asks for approval), then run `discuss` again. Then this question comes back; record that the spec was amended. On `continue`, a plan already written meets the changed spec as `drift: writing` from `journal-reconcile` (rewrite the plan / keep it); a plan not yet written is written from the amended spec.

Never edit the spec, the plan or the journal yourself in this mode.

## End

After the last question: "Answers recorded. Continue now?" Yes → `continue` (LOOP.md, Continue). No → say the command for later: `/plan-chain-runner continue`.
