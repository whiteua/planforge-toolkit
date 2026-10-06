# PROFILES

The core (start dialogue, graph, loop, `run-next`, `continue`, `discuss`, progress lines) is the same in every host. The profile decides only how an action is launched and how model and effort reach it. `C` as in SKILL.md, Tool.

## Detection

At the start and again on every `continue`, by the tools of this session:

| Profile | The session has | Launch |
|---|---|---|
| `claude-code` | the `Agent` tool with a `model` parameter | one `Agent` call per action, the actions of one `run-next` answer in one message |
| `github-copilot` | the `task` tool with a `model` parameter | one `task` call per action, started together |
| `fallback` | neither | the `Skill` tool (or the skill's instructions) in this session, one action after another |

When the profile's capability fails at run time (the tool refuses to start agents), switch to the next profile down for the rest of this session and say so in one line. Only `run-init` records the profile; on `continue` a different profile is announced in one line (LOOP.md, Continue).

## claude-code

- `Agent` with `model: <runner.models[role].model>` and the brief (LOOP.md, Brief) as the prompt. Where the host offers it, launch in the background and wait for the completion notices, heartbeating meanwhile (LOOP.md, Session mark).
- The `Agent` tool has no effort parameter: the agent inherits the session's effort unless agent definitions exist.
- **Pinned models.** An alias (`sonnet`, `opus`, `haiku`, `fable`) does not pin the version: it points at the current model of its family, and Claude Code has no way to fix it. A full model id (`claude-sonnet-5-5`) pins the version. `C settings-load` returns `pinned` per role (`true` for a full id). The `model` parameter of the `Agent` tool lists only the aliases (Verified, Claude Code Agent tool model names), so a pinned role runs through its agent definition: `~/.claude/agents/planforge-<role>.md` with `model: <id>`, launched with `subagent_type: planforge-<role>` and no `model` parameter. When that file cannot be written (no consent, the folder is not writable), launch `Agent` with `model: <id>`; a refusal of the host is the `model: <role>` question (LOOP.md, After the agents, 4), as for any refused model. Other profiles ignore `pinned`: their model names are not Claude Code aliases.
- **Agent definitions.** With the user's consent at the start (START.md, 4), for each role whose effort differs or whose model is pinned, write `~/.claude/agents/planforge-<role>.md`: YAML frontmatter with `name: planforge-<role>`, `description: plan-chain-runner role <role>: runs one pipeline skill in silent mode as the brief says`, `model: <model>`, `effort: <effort>`; the body is one paragraph: "You are an agent of plan-chain-runner. Do exactly what the brief says: run the named skill without a confirmation channel, record any decision as a journal question, and stop." Then launch that role with `subagent_type: planforge-<role>` and no `model` parameter. Files that already exist are shown and replaced only with consent. Without consent: no files, effort inherited.
- **Actual cost.** **Unverified:** that the result of the `Agent` tool ends with the subagent's token usage, and that the field is called `subagent_tokens`, is an assumption until a probe records it under Verified (below); the runner takes the number from the usage block of the result when the host shows one. The runner adds that number to the stage's running total `cost_tokens` after every return (LOOP.md, After the agents, 6), so a stage with several agents carries the sum of all of them; a result without it is reported as `cost-missing: <plan> <stage>` and the stage is estimated from its artifacts. The number is what the host shows, not a provider bill: `docs/COST.md`, Model.

## github-copilot

**Unverified.** No probe of this profile has passed yet (Verified, Copilot CLI profile probe). The `task` tool with a `model` parameter, the model names, the inherited effort and the `--reasoning-effort` flag below are what the profile assumes, not observed behaviour.

- GitHub Copilot CLI: `task` with `model: <runner.models[role].model>` and the brief as the prompt. Subagents run in parallel; the effort is inherited from the session (GitHub Copilot CLI 1.0.79, 2026-10-02), so the built-in effort is `null` for every role. The session's effort is set when the CLI starts (`--reasoning-effort <level>`); a role's effort that differs from it is said in the start card, it cannot be passed per agent.
- Model names are Copilot's (`claude-opus-5.5`, `claude-sonnet-5.5`, `gpt-5-mini`); every role has the fallback `gpt-5-mini`.

## fallback

- No agents: the runner runs each action's skill itself, in this session, one at a time, in the same silent mode as the brief says (no questions; a decision is a `journal-question` and the stage stops). It still reads the result only from the journal (LOOP.md, After the agents).
- No model choice: every role has `model: null`; `parallel` is `1`.

## Notifications and questions

Two host tools let a stop of the runner reach the user away from the terminal. A session without them works as before, in text; a missing tool or a failed call is skipped without an error.

| Profile | Push notification | Question with options |
|---|---|---|
| `claude-code` | the `PushNotification` tool | the host's question tool (`AskUserQuestion`); with "Push when actions required" on, its questions notify too |
| `github-copilot` | none known (Unverified) | text |
| `fallback` | `PushNotification` when this session has it, else none | the question tool when this session has it, else text |

- **Push:** one line, in the dialogue language, when the loop stops on questions and when the summary of a finished run is ready (LOOP.md, 7. End), e.g. "plan-refactoring-02: stopped, 2 questions — discuss" or "plan-refactoring-02: run complete". A stop on a `plan-oversized:` question is named in it: "<goal>: stopped, plan over the budget — discuss". Nothing else is pushed: no progress lines, no push per question. The push is a host call, not a write; the runner sends it only at the End, when no audit agent runs.
- **Questions with options:** the choices of the start (START.md: the card's confirm / edit, the start commit's yes / no, continue here / stop) and the question of `discuss` (DISCUSS.md: the options of one journal question) go through the question tool, the options in the dialogue language with one line of explanation each and the recommended one first; the user's own words stay possible. The tokens recorded in the journal stay as DISCUSS.md says.

## Host errors

A host error is an error of the tool that launched the agent, not the agent's answer: an API error (529 overloaded, 429 rate limit, a 5xx), a dropped connection, the tool's own time-out. Its text goes to `C host-wait` (LOOP.md, After the agents, 3); the agent's final text never does, even when it names an error.

| Profile | A host error is | How the runner waits `wait_seconds` |
|---|---|---|
| `claude-code` | the `Agent` tool's result marked as an error (`API Error: …`, a dropped stream, the tool's time-out), not the subagent's final text | a background `sleep <wait_seconds>` (Bash with `run_in_background`), heartbeating meanwhile (LOOP.md, Session mark); on its completion notice, `run-next` |
| `github-copilot` | the `task` tool's error result (Unverified) | `sleep` in pieces of at most 600 s, `C run-session <journal> --heartbeat --id <id>` between them |
| `fallback` | the failure of the `Skill` call itself (Unverified) | as `github-copilot` |

A host with no way to wait (no shell, no `sleep`) treats the first host error as exhausted: no `host-wait`, at once `J journal-question <journal> --skill plan-chain-runner --plan <plan> --spec <spec> --stage <stage> --text "stage-failed: <stage> host error, this host cannot wait: <error text>" --option retry --option stop`.

## Models and effort

- The settings file `~/.planforge/runner.json` (`PLANFORGE_HOME` replaces `~/.planforge`) holds per profile `parallel` and per role `model`, `effort` and an optional `fallback`, and for `execution` an optional `light`; `assets/runner.example.json` shows the format, with full model ids for `claude-code` (they pin the version; Pinned models). `C settings-load --profile <profile>` fills the roles the file does not name from the built-in defaults.
- The confirmed table (with each role's `fallback`) and `parallel` are written to the journal by `run-init` (`runner.models`, `runner.parallel`); the loop launches with them.
- A refused model or effort: `C model-pick --journal <journal> --profile <profile> --role <role> --unsupported <model>`, which reads the journal's table (LOOP.md, After the agents).
- **`light`** (role `execution` only): the model plan-executor gives the units `unit-begin` marks `delegable` (green, in the main agent, not a checkpoint, no `**External:**`; plan-executor EXECUTION-STRATEGY.md, Delegation). `null`, the default of every profile, means no delegation: the executor works as before. In `claude-code` it is an alias (`haiku`): the executor passes it as the `model` of its `Agent` call, which takes only aliases (Verified). `settings-load` returns it in the `execution` entry; on another role it is accepted, has no effect and gives the warning `light-ignored: <role>`. `run-init` copies it into `runner.models.execution.light`, and every executor brief names it (LOOP.md, Brief, 9). A host that refuses it: `C model-pick --journal <journal> --role execution --light --unsupported <light>` (LOOP.md, After the agents, 4), no question. Making `light: haiku` the default of `claude-code` is a separate decision after the measurement in `docs/COST.md` (Delegation).

## Built-in defaults

| Role | `claude-code` | `github-copilot` (fallback `gpt-5-mini`) | `fallback` |
|---|---|---|---|
| writing | `fable`, high | `claude-opus-5.5`, inherited | none |
| revision | `fable`, high | `claude-opus-5.5`, inherited | none |
| split | `sonnet`, low | `claude-sonnet-5.5`, inherited | none |
| execution | `opus`, medium | `claude-sonnet-5.5`, inherited | none |
| execution `light` | none | none | none |
| audit | `fable`, high | `claude-opus-5.5`, inherited | none |
| commit | `sonnet`, low | `gpt-5-mini`, inherited | none |
| `parallel` | 3 | 3 | 1 |

This table mirrors the built-in values of `chain_tool.py`; the script is the authority. With an invalid settings file (`settings-load` exit `2`) the runner offers this table for the run.

`split` runs on `sonnet` with low effort: the role reads the plan's task list (`plan-tasks`) and writes the boundaries JSON, and when the splitter's gate keeps the plan whole no agent starts at all.

**Unverified:** the `github-copilot` column (model names, inherited effort, fallback) is an assumption until the Copilot CLI profile probe passes (Verified).

## Verified

Host behaviour this file relies on, as checked during implementation; one entry per check, newest last.

### Copilot CLI profile probe — 2026-10-03

- Verdict: not verified: copilot exited 126 with 18 events.
- The model call failed with HTTP 402 (monthly quota exceeded). The probe ran with only `--allow-tool=task` and called no tools, but the CLI connected the MCP servers of the user's own Copilot config, a production database among them.
- **Do not start the probe before step 1 is done:** a probe with the user's MCP servers connected can reach the systems behind them.
- Manual re-run, on the user's machine, on an environment the user allows:
  1. Disable every MCP server for the run: `--disable-builtin-mcps` for the built-in GitHub server and `--disable-mcp-server <name>` for each server of the user's Copilot config (`~/.copilot`), one flag per server; the user names the servers. Check both flags in `copilot --help`; a flag that is missing → stop, the probe is not run.
  2. In an empty temporary folder run `copilot -p "<prompt>" --model gpt-5-mini --reasoning-effort low --no-ask-user --no-custom-instructions --disable-builtin-mcps --disable-mcp-server <name> --allow-tool=task --deny-tool=write --deny-tool=shell --output-format json > events.jsonl`, with one `--disable-mcp-server` per server from step 1 and this prompt: `Call your task tool twice in one response so that two sub-agents run in parallel. First sub-agent: model gpt-5-mini, task: reply with only the word alpha. Second sub-agent: model claude-sonnet-5.5, task: reply with only the word beta. Use no other tool. When both finish, reply with the two words.`
  3. In `events.jsonl` check that two `task` calls ran in parallel with the models asked for, and that no MCP tool was called.
  4. Delete the temporary folder and record the outcome as a new entry in this section. Until a probe passes, the `github-copilot` profile stays Unverified.

### Claude Code agent-definition effort key — 2026-10-03

- Verdict: not verified automatically. The check needs a live Claude Code session, and the plan that added this skill had no permission to call one.
- Manual check, about two minutes:
  1. In an empty temporary folder create `.claude/agents/planforge-probe.md` with YAML frontmatter `name: planforge-probe`, `description: Probe for plan-chain-runner; replies with one word.`, `model: haiku`, `effort: low` and the body `Reply with only the word probe.`
  2. Start `claude` in that folder and run `/agents`: `planforge-probe` is listed, and no warning names the `effort` key.
  3. Ask: "Use the planforge-probe agent." The transcript (Ctrl+O) shows that the agent ran on Haiku, and the effort it used if the host reports one.
  4. Delete the temporary folder.
- Record the outcome as a new entry in this section. Until then `effort` in agent definitions is unconfirmed.

### Claude Code Agent tool model names — 2026-10-03

- Source: the `model` parameter of the `Agent` tool in the Claude Code session that executed the plan; its schema lists `sonnet`, `opus`, `haiku`, `fable`. The session that drafted the plan saw the same list on 2026-10-02.
- The `claude-code` builtin defaults of `chain_tool.py settings-load` use only `fable`, `opus` and `sonnet`, so every default name is accepted. `model-pick --unsupported` stays the guard when a host refuses a name at run time.
