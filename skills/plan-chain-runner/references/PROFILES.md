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
- **Agent definitions.** With the user's consent at the start (START.md, 4), for each role whose effort differs, write `~/.claude/agents/planforge-<role>.md`: YAML frontmatter with `name: planforge-<role>`, `description: plan-chain-runner role <role>: runs one pipeline skill in silent mode as the brief says`, `model: <model>`, `effort: <effort>`; the body is one paragraph: "You are an agent of plan-chain-runner. Do exactly what the brief says: run the named skill without a confirmation channel, record any decision as a journal question, and stop." Then launch that role with `subagent_type: planforge-<role>` and no `model` parameter. Files that already exist are shown and replaced only with consent. Without consent: no files, effort inherited.

## github-copilot

- GitHub Copilot CLI: `task` with `model: <runner.models[role].model>` and the brief as the prompt. Subagents run in parallel; the effort is inherited from the session (GitHub Copilot CLI 1.0.79, 2026-10-02), so the built-in effort is `null` for every role. The session's effort is set when the CLI starts (`--reasoning-effort <level>`); a role's effort that differs from it is said in the start card, it cannot be passed per agent.
- Model names are Copilot's (`claude-opus-5.5`, `claude-sonnet-5.5`, `gpt-5-mini`); every role has the fallback `gpt-5-mini`.

## fallback

- No agents: the runner runs each action's skill itself, in this session, one at a time, in the same silent mode as the brief says (no questions; a decision is a `journal-question` and the stage stops). It still reads the result only from the journal (LOOP.md, After the agents).
- No model choice: every role has `model: null`; `parallel` is `1`.

## Models and effort

- The settings file `~/.planforge/runner.json` (`PLANFORGE_HOME` replaces `~/.planforge`) holds per profile `parallel` and per role `model`, `effort` and an optional `fallback`; `assets/runner.example.json` shows the format. `C settings-load --profile <profile>` fills the roles the file does not name from the built-in defaults.
- The confirmed table (with each role's `fallback`) and `parallel` are written to the journal by `run-init` (`runner.models`, `runner.parallel`); the loop launches with them.
- A refused model or effort: `C model-pick --journal <journal> --profile <profile> --role <role> --unsupported <model>`, which reads the journal's table (LOOP.md, After the agents).

## Built-in defaults

| Role | `claude-code` | `github-copilot` (fallback `gpt-5-mini`) | `fallback` |
|---|---|---|---|
| writing | `fable`, high | `claude-opus-5.5`, inherited | none |
| revision | `fable`, high | `claude-opus-5.5`, inherited | none |
| split | `opus`, medium | `claude-sonnet-5.5`, inherited | none |
| execution | `opus`, medium | `claude-sonnet-5.5`, inherited | none |
| audit | `fable`, high | `claude-opus-5.5`, inherited | none |
| commit | `sonnet`, low | `gpt-5-mini`, inherited | none |
| `parallel` | 3 | 3 | 1 |

This table mirrors the built-in values of `chain_tool.py`; the script is the authority. With an invalid settings file (`settings-load` exit `2`) the runner offers this table for the run.

## Verified

Host behaviour this file relies on, as checked during implementation; one entry per check, newest last.

### Copilot CLI profile probe — 2026-10-03

- Verdict: not verified: copilot exited 126 with 18 events.
- The model call failed with HTTP 402 (monthly quota exceeded). The probe ran with only `--allow-tool=task` and called no tools, but the CLI connected the MCP servers of the user's own Copilot config. A re-run must disable them first, for example `--disable-builtin-mcps` and `--disable-mcp-server <name>` for each configured server; check the flags in `copilot --help`.

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
