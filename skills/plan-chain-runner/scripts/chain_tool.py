#!/usr/bin/env python3
"""Deterministic helper of the plan-chain-runner skill.

The chain journal is read and written only through ../plan-brainstorming/scripts/brainstorm_tool.py
(loaded by path). Settings and session marks live in PLANFORGE_HOME (default ~/.planforge),
outside any working copy. Stdlib only, Python 3.8+.

Commands:
  settings-load  [--file F] --profile P
  settings-save  --profile P --roles JSON [--file F]
  model-pick     (--profile P [--file F] | --journal J [--profile P]) --role R [--light] [--unsupported MODEL]...
  run-init       <journal> --profile P --spec S... --graph JSON --models JSON [--start-commit SHA|declined|none] [--parallel N]
                 [--roadmap R]
  subset-check   <journal> --roadmap R [--spec S]...
  run-session    <journal> (--begin [--host H] [--takeover] | --heartbeat --id ID | --end stopped|complete|interrupted --id ID)
  run-next       <journal> [--parallel N] [--in-flight PLAN_ID:STAGE]...
  host-wait      <journal> --plan P --stage S --error TEXT
  writing-resume <journal> --plan P
  run-eta        <journal>
  run-status     <journal>
  run-stats      (<journal> | --plan PLAN) [--baseline JSON] [--json-out FILE]
  run-checklist  <journal> [--backlog-root R]

Exit codes: 0 ok, 1 contract (graph-cycle, session-active, session-stale-running, session-taken-over,
runner-missing, no-model, stage-not-open, no-marker) or scheduler-bug (run-next, run-eta, run-status, run-stats, subset-check, run-checklist), 2 usage or
I/O error (journal-corrupt, roadmap-mismatch and not-in-roadmap included).
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import importlib.util
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


ROLES = ("writing", "revision", "split", "execution", "audit", "commit")
PROFILES = ("claude-code", "github-copilot", "fallback")


# run-stats: text metrics of the chain's files (Task 1), their discovery next to a plan (Tasks 1.1, 1.2).
_STATS_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_STATS_TASK_RE = re.compile(r"^#{2,4}\s+(?:Task|Задача)\s+\S+?\s*:")


def _fenced_lines(lines: List[str]) -> List[Tuple[str, bool]]:
    """(line, in_code) per line: in_code is True for the lines of a fenced block, its opening and closing
    lines included. Fences follow CommonMark: the closing line repeats the opening character, is at least
    as long and has no text after it, so a four-backtick block may hold three-backtick blocks."""
    out: List[Tuple[str, bool]] = []
    fence: Optional[Tuple[str, int]] = None
    for line in lines:
        match = _STATS_FENCE_RE.match(line)
        if fence is None:
            if match and not (match.group(1)[0] == "`" and "`" in match.group(2)):
                fence = (match.group(1)[0], len(match.group(1)))
            out.append((line, fence is not None))
        else:
            out.append((line, True))
            if match and match.group(1)[0] == fence[0] and len(match.group(1)) >= fence[1] and not match.group(2).strip():
                fence = None
    return out


def _text_metrics(path: str) -> Dict[str, Any]:
    """bytes, lines and the share of lines inside code fences (fence lines included); a file that is
    not UTF-8 keeps its bytes and gets None for the rest."""
    with open(path, "rb") as fh:
        raw = fh.read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return {"bytes": len(raw), "lines": None, "code_share": None}
    lines = text.splitlines()
    code = sum(1 for _, in_code in _fenced_lines(lines) if in_code)
    return {"bytes": len(raw), "lines": len(lines), "code_share": round(code / len(lines), 4) if lines else 0.0}


def _text_metrics_text(path: str) -> str:
    """File text for the header scans; an unreadable or undecodable file reads as empty."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError):
        return ""


def _count_plan_tasks(text: str) -> int:
    """Tasks of a contract plan by brainstorm_tool.parse_plan_tasks (no malformed task heading); otherwise,
    and without plan-brainstorming, `### Task N:` / `### Задача N:` headings outside code fences."""
    try:
        parse = getattr(_brainstorm(), "parse_plan_tasks", None)
    except InputError:
        parse = None
    if parse is not None:
        parsed = parse(text)
        if parsed["tasks"] and not parsed["malformed"]:
            return len(parsed["tasks"])
    return sum(1 for line, in_code in _fenced_lines(text.splitlines()) if not in_code and _STATS_TASK_RE.match(line))


_SIBLINGS: Dict[str, Any] = {}


def _sibling(skill: str, script: str) -> Any:
    """A sibling skill's script loaded by path once per process, like _brainstorm(); None when that skill
    is not installed alongside (the caller decides what the absence means)."""
    if skill not in _SIBLINGS:
        path = Path(__file__).resolve().parents[2] / skill / "scripts" / script
        module = None
        if path.is_file():
            spec = importlib.util.spec_from_file_location(script[:-len(".py")], str(path))
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        _SIBLINGS[skill] = module
    return _SIBLINGS[skill]


def _executor() -> Any:
    """plan-executor's executor_tool.py, or None without it."""
    return _sibling("plan-executor", "executor_tool.py")


# Copy of executor_tool._CHAIN_FILE_RE for a runner installed without plan-executor. The original wins
# when it is there; the two stay equal by contract (test SiblingLoaderTest). `roadmap\.md` covers the split
# roadmap <X>-impl-roadmap.md and the goal roadmap <goal>-roadmap.md.
_CHAIN_FILE_FALLBACK_RE = re.compile(
    r"(\.)?.+-(?:chain\.json(?:\.lock)?|diffs\.md|followups\.json|spec\.md|impl\.md|impl-[a-z]+\.md"
    r"|roadmap\.md|completion\.md|review-\d+\.md|report-\d+(?:-final)?\.md)(?(1)\.[a-z0-9_]+\.tmp)"
    r"|\.splitter-[a-z0-9_]+\.tmp|\.splitter-probe-[a-z0-9_]+|\..+-review-write-test-\d+(?:-\d+)?\.tmp")


def _chain_file_re(warnings: List[str]) -> Any:
    """The names of the pipeline's files as plan-executor knows them; the fallback constant with one
    `executor-not-installed` warning when executor_tool.py is not alongside."""
    module = _executor()
    if module is None:
        if "executor-not-installed" not in warnings:
            warnings.append("executor-not-installed")
        return _CHAIN_FILE_FALLBACK_RE
    return module._CHAIN_FILE_RE


_STATS_SPEC_RE = re.compile(r"^\*\*Spec:\*\*\s*(\S.*?)\s*$", re.MULTILINE)
_STATS_STAGE_FILES = ("writing", "revision", "split", "execution", "audit", "commit")


def _artifact_files(plan_path: str, warnings: List[str]) -> Dict[str, Any]:
    """The chain's files next to `plan_path` (names by plan-executor's pattern, _chain_file_re), by the
    stage that writes them, relative to the plan's folder and in production order (reviews and reports
    by number): parts `<base>-<id>.md`, `<base>-roadmap.md`, `<base>-review-N.md`, `<base>-completion.md`,
    `<base>-report-N[-final].md`, `<X>-diffs.md` (X = base without -impl)."""
    folder, name = os.path.split(os.path.abspath(plan_path))
    base = name[:-3] if name.lower().endswith(".md") else name
    x_base = base[:-len("-impl")] if base.endswith("-impl") else base
    chain_re = _chain_file_re(warnings)
    names = sorted(n for n in (os.listdir(folder) if os.path.isdir(folder) else [])
                   if chain_re.fullmatch(n) and (n.startswith(base + "-") or n == f"{x_base}-diffs.md"))

    def numbered(pattern: str) -> List[str]:
        found = [(int(m.group(1)), n) for n in names for m in [re.fullmatch(pattern, n)] if m]
        return [n for _, n in sorted(found)]

    parts = [n for n in names if re.fullmatch(re.escape(base) + r"-[a-z]{1,2}\.md", n)]
    roadmap = [n for n in names if n == f"{base}-roadmap.md"]
    completion = [n for n in names if n == f"{base}-completion.md"]
    reports = numbered(re.escape(base) + r"-report-(\d+)(?:-final)?\.md")
    stages = {"writing": [name] if os.path.isfile(plan_path) else [],
              "revision": numbered(re.escape(base) + r"-review-(\d+)\.md") + completion,
              "split": roadmap + parts,
              "execution": [n for n in names if n == f"{x_base}-diffs.md"],
              "audit": reports, "commit": []}
    spec = None
    if os.path.isfile(plan_path):
        match = _STATS_SPEC_RE.search(_text_metrics_text(plan_path))
        spec = match.group(1).strip("`") if match else None
    return {"folder": folder, "base": base, "spec": spec, "stages": stages, "parts": parts, "reports": reports}


def _artifact_stats(plan_path: str, warnings: List[str]) -> Dict[str, Any]:
    """The artifact layer of run-stats: the plan's size, code share and task count, the spec's size,
    and per stage the files it wrote with their metrics; statuses derived from the files alone
    (the journal layer overrides them when there is a journal)."""
    files = _artifact_files(plan_path, warnings)
    folder = files["folder"]
    exists = os.path.isfile(plan_path)
    plan_text = _text_metrics_text(plan_path) if exists else ""
    plan_metrics = _text_metrics(plan_path) if exists else {"bytes": 0, "lines": None, "code_share": None}
    spec_path = os.path.join(folder, files["spec"]) if files["spec"] else None
    spec_bytes = os.path.getsize(spec_path) if spec_path and os.path.isfile(spec_path) else 0
    stages: Dict[str, Any] = {}
    for stage in _STATS_STAGE_FILES:
        entries = [dict(name=n, **_text_metrics(os.path.join(folder, n))) for n in files["stages"][stage]]
        if stage == "split":
            status = "done" if entries else "skipped"
        elif stage == "commit":
            status = "pending"
        else:
            status = "done" if entries else "pending"
        stages[stage] = {"status": status, "files": entries, "bytes_written": sum(e["bytes"] for e in entries)}
    return {"plan": os.path.basename(plan_path), "plan_missing": not exists, "tasks": _count_plan_tasks(plan_text),
            "plan_bytes": plan_metrics["bytes"], "code_share": plan_metrics["code_share"], "spec": files["spec"],
            "spec_bytes": spec_bytes, "parts": files["parts"], "reports": files["reports"], "stages": stages}


class InputError(Exception):
    """Bad arguments, unreadable or invalid input (exit 2)."""


class ChainError(Exception):
    """Contract violation (exit 1); `details` are added to the JSON result."""

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.details = details


def _home() -> str:
    """PLANFORGE_HOME, else ~/.planforge."""
    return os.environ.get("PLANFORGE_HOME") or os.path.join(os.path.expanduser("~"), ".planforge")


def _now() -> float:
    """Current time in seconds; tests monkeypatch it."""
    return time.time()


def _iso_now() -> str:
    """_now() in UTC as YYYY-MM-DDTHH:MM:SSZ, the journal's time format."""
    return datetime.datetime.fromtimestamp(_now(), datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


_BRAINSTORM: Any = None


def _brainstorm() -> Any:
    """plan-brainstorming's brainstorm_tool.py, loaded by path once per process."""
    global _BRAINSTORM
    if _BRAINSTORM is None:
        path = Path(__file__).resolve().parents[2] / "plan-brainstorming" / "scripts" / "brainstorm_tool.py"
        if not path.is_file():
            raise InputError("plan-brainstorming not installed alongside: " + str(path))
        spec = importlib.util.spec_from_file_location("brainstorm_tool", str(path))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _BRAINSTORM = module
    return _BRAINSTORM


_SPLITTER: Any = None


def _splitter() -> Any:
    """plan-splitter's splitter_tool.py, loaded by path once per process; None when it is not installed
    alongside (the split stage then runs as before)."""
    global _SPLITTER
    if _SPLITTER is None:
        path = Path(__file__).resolve().parents[2] / "plan-splitter" / "scripts" / "splitter_tool.py"
        if not path.is_file():
            return None
        spec = importlib.util.spec_from_file_location("splitter_tool", str(path))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _SPLITTER = module
    return _SPLITTER


def _split_gate(state: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """The splitter's numeric gate on the plan (split=auto): (verdict, None), or (None, "gate-unavailable:
    <error>") when the splitter is missing or the gate fails; a failing gate never stops the chain."""
    plan = os.path.join(state["root"], state["entry"]["plan"])
    try:
        splitter = _splitter()
        if splitter is None:
            raise RuntimeError("plan-splitter not installed alongside")
        return splitter.gate_verdict(plan), None
    except Exception as exc:  # any failure of the gate: the splitter agent decides as before
        return None, f"gate-unavailable: {exc}"


def _gate_why(gate: Dict[str, Any]) -> str:
    """The skip reason of a plan the gate keeps whole: its numbers, and for a borderline plan the budget that
    decided it (silent_verdict, spec plan-refactoring-03)."""
    factors = gate["factors"]
    numbers = (f"{factors['task_count']} tasks, {round(factors['plan_bytes'] / 1000)} KB, "
               f"{factors['modules']} modules, {factors['dependency_shape']}")
    if gate["verdict"] == "keep":
        return f"gate: keep ({numbers})"
    limits = gate["thresholds"]
    return (f"gate: borderline → keep ({numbers}; budget {limits['split_tasks']} tasks / "
            f"{round(limits['split_bytes'] / 1000)} KB)")


def _brainstorm_exit(exc: BaseException) -> Optional[int]:
    """Exit code of an error raised inside brainstorm_tool: JournalError → 1, its InputError → 2."""
    module = _BRAINSTORM
    if module is not None and isinstance(exc, module.JournalError):
        return 1
    if module is not None and isinstance(exc, module.InputError):
        return 2
    return None


# Built-in models per profile and role (spec plan-chain-runner-2, B). effort None: inherited from the session.
_OPUS, _SONNET, _MINI = "claude-opus-5.5", "claude-sonnet-5.5", "gpt-5-mini"
BUILTIN_SETTINGS: Dict[str, Dict[str, Any]] = {
    "claude-code": {"parallel": 3, "roles": {
        "writing": {"model": "fable", "effort": "high"}, "revision": {"model": "fable", "effort": "high"},
        "split": {"model": "sonnet", "effort": "low"}, "execution": {"model": "opus", "effort": "medium"},
        "audit": {"model": "fable", "effort": "high"}, "commit": {"model": "sonnet", "effort": "low"}}},
    "github-copilot": {"parallel": 3, "roles": {
        role: {"model": model, "effort": None, "fallback": _MINI}
        for role, model in (("writing", _OPUS), ("revision", _OPUS), ("split", _SONNET),
                            ("execution", _SONNET), ("audit", _OPUS), ("commit", _MINI))}},
    "fallback": {"parallel": 1, "roles": {role: {"model": None, "effort": None} for role in ROLES}},
}
# `light` (spec 8 of plan-refactoring-01): the model of the green units plan-executor may delegate to a
# subagent. Meaningful only for the execution role; null, the default of every profile, = no delegation.
for _builtin in BUILTIN_SETTINGS.values():
    _builtin["roles"]["execution"]["light"] = None
ROLE_KEYS = ("model", "effort", "fallback", "light")
# Claude Code model aliases: each points at the current model of its family and cannot be pinned;
# a full model id (claude-sonnet-5-5) pins the version (PROFILES.md, Pinned models).
MODEL_ALIASES = ("sonnet", "opus", "haiku", "fable")


def _pinned(roles: Dict[str, Any]) -> Dict[str, bool]:
    """{role: True} when the role's model is a full model id: not an alias, not null (inherited)."""
    return {role: isinstance(entry.get("model"), str) and entry["model"] not in MODEL_ALIASES
            for role, entry in roles.items()}


def _roles_errors(where: str, roles: Any) -> List[str]:
    """Errors of {role: {"model"?, "effort"?, "fallback"?}}: known roles, each value a non-empty string or null."""
    if not isinstance(roles, dict):
        return [f"{where}: must be an object"]
    errors: List[str] = []
    for role, entry in roles.items():
        if role not in ROLES:
            errors.append(f"unknown-role: {role}")
        elif not isinstance(entry, dict):
            errors.append(f"{where}.{role}: must be an object")
        else:
            errors.extend(f"{where}.{role}: unknown key '{key}'" for key in entry if key not in ROLE_KEYS)
            errors.extend(f"{where}.{role}.{key}: must be a non-empty string or null" for key in ROLE_KEYS
                          if key in entry and entry[key] is not None
                          and not (isinstance(entry[key], str) and entry[key].strip()))
    return errors


def _settings_errors(data: Any) -> List[str]:
    """Errors of a runner.json document: {"profiles": {<profile>: {"parallel": int >= 1, "roles": {...}}}}."""
    if not isinstance(data, dict):
        return ["settings: must be an object"]
    errors = [f"settings: unknown key '{key}'" for key in data if key != "profiles"]
    profiles = data.get("profiles", {})
    if not isinstance(profiles, dict):
        return errors + ["profiles: must be an object"]
    for name, body in profiles.items():
        if name not in PROFILES:
            errors.append(f"unknown-profile: {name}")
        elif not isinstance(body, dict):
            errors.append(f"profiles.{name}: must be an object")
        else:
            errors.extend(f"profiles.{name}: unknown key '{key}'" for key in body if key not in ("parallel", "roles"))
            parallel = body.get("parallel", 1)
            if isinstance(parallel, bool) or not isinstance(parallel, int) or parallel < 1:
                errors.append(f"profiles.{name}.parallel: must be an integer >= 1")
            errors.extend(_roles_errors(f"profiles.{name}.roles", body.get("roles", {})))
    return errors


def _settings_path(path: Optional[str]) -> str:
    return os.path.abspath(path) if path else os.path.join(_home(), "runner.json")


def _check_profile(profile: str) -> str:
    if profile not in PROFILES:
        raise InputError(f"unknown-profile: {profile}")
    return profile


def _read_settings(path: str) -> Any:
    """The settings document; None when the file is missing; InputError when unreadable or not JSON."""
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise InputError(f"cannot read {path}: {exc}") from exc
    try:
        return json.loads(raw.decode("utf-8-sig"))
    except ValueError as exc:
        raise InputError(f"settings-invalid-json: {path}: {exc}") from exc


def load_settings(path: str, profile: str) -> Dict[str, Any]:
    """Settings of one profile: the file's values over the built-in ones, role by role and key by key."""
    builtin = BUILTIN_SETTINGS[_check_profile(profile)]
    data = _read_settings(path)
    errors = [] if data is None else _settings_errors(data)
    body = None if data is None or errors else data.get("profiles", {}).get(profile)
    roles = {role: dict(entry) for role, entry in builtin["roles"].items()}
    for role, entry in ((body or {}).get("roles") or {}).items():
        roles[role].update(entry)
    # `light` is accepted on any role but means something only for execution (spec 8 of plan-refactoring-01).
    warnings = [f"light-ignored: {role}" for role, entry in roles.items()
                if role != "execution" and entry.get("light") is not None]
    return {"ok": not errors, "source": "file" if body is not None or errors else "builtin", "profile": profile,
            "parallel": (body or {}).get("parallel", builtin["parallel"]), "roles": roles,
            "pinned": _pinned(roles), "errors": errors, "warnings": warnings}


def cmd_settings_load(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    result = load_settings(_settings_path(args.file), args.profile)
    return (0 if result["ok"] else 2), result


def _json_arg(text: str, name: str) -> Any:
    try:
        return json.loads(text)
    except ValueError as exc:
        raise InputError(f"{name}: invalid JSON: {exc}") from exc


def save_settings(path: str, profile: str, roles: Dict[str, Any]) -> Dict[str, Any]:
    """Replace the given roles of one profile in the settings file; other roles and profiles stay.
    An invalid existing file is not overwritten. Atomic write (brainstorm_tool._atomic_write_text)."""
    _check_profile(profile)
    data = _read_settings(path)
    data = {"profiles": {}} if data is None else data
    errors = _settings_errors(data)
    if errors:
        raise InputError(f"settings-invalid: {path}: " + "; ".join(errors))
    body = data.setdefault("profiles", {}).setdefault(profile, {})
    body.setdefault("roles", {}).update(roles)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        _brainstorm()._atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    except OSError as exc:
        raise InputError(f"cannot write {path}: {exc}") from exc
    return {"ok": True, "path": path}


def cmd_settings_save(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    roles = _json_arg(args.roles, "--roles")
    errors = _roles_errors("roles", roles)
    if errors:
        return 2, {"ok": False, "errors": errors}
    return 0, save_settings(_settings_path(args.file), args.profile, roles)


def pick_model(settings: Dict[str, Any], role: str, unsupported: List[str], light: bool = False) -> Dict[str, Any]:
    """The role's model; with `light` (execution only) its `light` model, the model of delegated green units
    (spec 8 of plan-refactoring-01). A refused (`unsupported`) model gives way to the role's fallback, else
    no-model. A null model (fallback profile, inherited model, no `light`) is returned as null."""
    if role not in ROLES:
        raise InputError(f"unknown-role: {role}")
    if light and role != "execution":
        raise InputError(f"light-role: --light goes with --role execution, not {role}")
    entry = settings["roles"][role]
    model, fallback = (entry.get("light") if light else entry["model"]), entry.get("fallback")
    if model is None or model not in unsupported:
        return {"ok": True, "model": model, "effort": entry["effort"], "fallback_used": False}
    if fallback and fallback not in unsupported:
        return {"ok": True, "model": fallback, "effort": entry["effort"], "fallback_used": True}
    raise ChainError(f"no-model: {role}", role=role, unsupported=list(unsupported))


def cmd_model_pick(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    if args.journal:  # the source the runner launches from: runner.models (with fallback), not the file
        if args.file:
            raise InputError("--file goes without --journal")
        if args.profile:
            _check_profile(args.profile)
        journal = os.path.abspath(args.journal)
        models = _runner_journal(journal)[1].get("models") or {}  # runner.models validated there
        roles = {role: dict({"model": None, "effort": None}, **(models.get(role) or {})) for role in ROLES}
        return 0, pick_model({"roles": roles}, args.role, args.unsupported, args.light)
    if not args.profile:
        raise InputError("--profile is required without --journal")
    settings = load_settings(_settings_path(args.file), args.profile)
    if not settings["ok"]:
        return 2, {"ok": False, "errors": settings["errors"]}
    return 0, pick_model(settings, args.role, args.unsupported, args.light)


START_COMMIT_RE = re.compile(r"^[0-9a-f]{7,64}$")


def _runner_models(models: Any) -> Dict[str, Dict[str, Any]]:
    """`--models` (settings-load roles) as {role: {"model", "effort", "fallback"?, "light"?}}: the fallback
    stays for model-pick --journal; `light` only for execution (the executor's brief names it)."""
    errors = _roles_errors("--models", models)
    if errors:
        raise InputError("; ".join(errors))
    runner_models: Dict[str, Dict[str, Any]] = {}
    for role, entry in models.items():
        runner_models[role] = {"model": entry.get("model"), "effort": entry.get("effort")}
        if entry.get("fallback"):
            runner_models[role]["fallback"] = entry["fallback"]
        if role == "execution" and entry.get("light"):
            runner_models[role]["light"] = entry["light"]
    return runner_models


def _goal_roadmap(journal: str, roadmap: str, goal: Any) -> Tuple[str, str, Dict[str, Any]]:
    """(name relative to the journal, absolute path, brainstorm_tool.parse_goal_roadmap result) of the goal
    roadmap `roadmap`, a path relative to CWD like --spec (spec 10 of plan-refactoring-01). roadmap-mismatch
    (exit 2) when it is not a file name in the journal's directory or its '> Goal:' is not `goal`."""
    bt = _brainstorm()
    rel = bt._journal_rel(journal, roadmap)
    if "/" in rel or rel in ("", ".", ".."):
        raise InputError(f"roadmap-mismatch: {rel} is not a file in the journal's directory")
    path = os.path.join(os.path.dirname(os.path.abspath(journal)), rel)
    try:
        text = bt._read_source(path)
    except bt.InputError as exc:
        raise InputError(str(exc)) from exc
    parsed = bt.parse_goal_roadmap(text)[0]
    if parsed["goal"] != goal:
        raise InputError(f"roadmap-mismatch: {rel} names the goal {parsed['goal']!r}, the journal's goal is {goal!r}")
    return rel, path, parsed


def run_init(journal: str, profile: str, specs: List[str], graph: Any, models: Any,
             start_commit: Optional[str] = None, parallel: Optional[int] = None,
             roadmap: Optional[str] = None) -> Dict[str, Any]:
    """Write the journal's `runner` section. Spec paths are taken relative to CWD and stored relative
    to the journal; every one must be registered in journal.specs. Sessions, host_errors and writing_resumes of an earlier run-init stay;
    without --start-commit (--parallel, --roadmap) the earlier value stays, else the key is left out.
    With --roadmap the specs are stored in the roadmap's # order (not-in-roadmap for a spec it does not
    name), with runner.roadmap and runner.roadmap_sha256."""
    _check_profile(profile)
    if parallel is not None and parallel < 1:
        raise InputError(f"--parallel must be at least 1, got {parallel}")
    if start_commit is not None and start_commit not in ("declined", "none") and not START_COMMIT_RE.match(start_commit):
        raise InputError(f"start-commit-invalid: {start_commit}")
    if not isinstance(graph, dict) or not all(isinstance(deps, list) and all(isinstance(d, str) for d in deps)
                                              for deps in graph.values()):
        raise InputError("--graph: must be an object {spec: [spec it depends on, ...]}")
    runner_models = _runner_models(models)
    bt = _brainstorm()
    journal = os.path.abspath(journal)
    rels = list(dict.fromkeys(bt._journal_rel(journal, spec) for spec in specs))
    rel_graph = {bt._journal_rel(journal, key): [bt._journal_rel(journal, dep) for dep in deps]
                 for key, deps in graph.items()}
    unknown = [name for name in [*rel_graph, *(d for deps in rel_graph.values() for d in deps)] if name not in rels]
    if unknown:
        raise InputError("unknown-spec: " + ", ".join(dict.fromkeys(unknown)))
    cycle = bt._runner_cycle(rel_graph)
    if cycle:
        raise ChainError("graph-cycle: " + " -> ".join(cycle), cycle=cycle)

    def mutate(data: Dict[str, Any]) -> Dict[str, Any]:
        registered = [entry.get("path") for entry in data.get("specs") or [] if isinstance(entry, dict)]
        missing = [rel for rel in rels if rel not in registered]
        if missing:
            raise InputError("unknown-spec: " + ", ".join(missing) + " (not registered in the journal)")
        old = data.get("runner") if isinstance(data.get("runner"), dict) else {}
        ordered, source = rels, None
        if roadmap is not None:
            name, path, parsed = _goal_roadmap(journal, roadmap, data.get("goal"))
            position = {row["file"]: index for index, row in enumerate(parsed["specs"])}
            outside = [rel for rel in rels if rel not in position]
            if outside:
                raise InputError("not-in-roadmap: " + ", ".join(outside))
            ordered, source = sorted(rels, key=position.__getitem__), (name, bt._sha256(path))
        runner = {"version": bt.RUNNER_VERSION, "profile": profile, "specs": ordered, "graph": rel_graph,
                  "models": runner_models,
                  "sessions": old.get("sessions") if isinstance(old.get("sessions"), list) else []}
        for key in ("host_errors", "writing_resumes"):  # the scheduler's marks outlive a new run-init
            if isinstance(old.get(key), list):
                runner[key] = old[key]
        kept = start_commit or old.get("start_commit")
        if kept:
            runner["start_commit"] = kept
        width = parallel if parallel is not None else old.get("parallel")
        if width is not None:
            runner["parallel"] = width
        if source is None and old.get("roadmap") and old.get("roadmap_sha256"):
            source = (old["roadmap"], old["roadmap_sha256"])
        if source is not None:
            runner["roadmap"], runner["roadmap_sha256"] = source
        errors = bt._runner_errors(runner)
        if errors:
            raise InputError("runner-invalid: " + "; ".join(errors))
        data["runner"] = runner
        return runner

    return {"ok": True, "journal": journal, "runner": bt.journal_update(journal, mutate)}


def cmd_run_init(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    return 0, run_init(args.journal, args.profile, args.spec, _json_arg(args.graph, "--graph"),
                       _json_arg(args.models, "--models"), args.start_commit, args.parallel, args.roadmap)


SESSION_STALE_SECONDS = 1800
SESSION_ENDS = ("stopped", "complete", "interrupted")


def _session_file(journal: str) -> str:
    """$PLANFORGE_HOME/sessions/<sha1 of the real journal path>.json: outside the working copy, so a
    heartbeat during an audit does not change the resolver's workspace fingerprint. realpath: a journal
    reached through a symlink, a junction or a subst drive has the same mark as by its own path."""
    key = hashlib.sha1(os.path.normcase(os.path.realpath(journal)).encode("utf-8")).hexdigest()
    return os.path.join(_home(), "sessions", key + ".json")


def _read_mark_bytes(path: str) -> Optional[bytes]:
    """Raw bytes of the session mark; None when it is missing. A PermissionError is retried for about a
    second, as journal_load does: on Windows a reader can meet the moment a writer's os.replace swaps the
    file; a missing file is looked for once more for the same reason. Still unreadable: InputError."""
    deadline, missing = time.monotonic() + 1.0, 0
    while True:
        try:
            with open(path, "rb") as fh:
                return fh.read()
        except FileNotFoundError:
            missing += 1
            if missing > 1:
                return None
        except PermissionError as exc:
            if time.monotonic() >= deadline:
                raise InputError(f"cannot read {path}: {exc}") from exc
        except OSError as exc:
            raise InputError(f"cannot read {path}: {exc}") from exc
        time.sleep(0.05)


def _read_session(path: str) -> Optional[Dict[str, Any]]:
    """The session mark; None when it is missing or not a JSON object (such a mark counts as abandoned).
    Read by _read_mark_bytes: still unreadable is an InputError, never None, so a live mark is not taken
    for an absent one."""
    raw = _read_mark_bytes(path)
    if raw is None:
        return None
    try:
        data = json.loads(raw.decode("utf-8"))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _session_age(mark: Dict[str, Any]) -> Optional[int]:
    """Seconds since the mark's heartbeat_at; None when it has no valid time."""
    try:
        at = datetime.datetime.strptime(mark["heartbeat_at"], "%Y-%m-%dT%H:%M:%SZ")
    except (KeyError, TypeError, ValueError):
        return None
    return max(0, int(_now() - at.replace(tzinfo=datetime.timezone.utc).timestamp()))


def _write_session(path: str, mark: Dict[str, Any]) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        _brainstorm()._atomic_write_text(path, json.dumps(mark, ensure_ascii=False, indent=2) + "\n")
    except OSError as exc:
        raise InputError(f"cannot write {path}: {exc}") from exc


def _runner_of(data: Dict[str, Any], journal: str) -> Dict[str, Any]:
    runner = data.get("runner")
    if not isinstance(runner, dict) or not isinstance(runner.get("sessions"), list):
        raise ChainError(f"runner-missing: {journal}")
    return runner


def _running_stage(data: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    """(plan id, stage) of the first stage of the journal in status running, else None."""
    for entry in data.get("plans") or []:
        for stage, record in (entry.get("stages") or {}).items():
            if isinstance(record, dict) and record.get("status") == "running":
                return entry.get("id"), stage
    return None


def _claim_mark(path: str, mark: Dict[str, Any], created: Optional[List[str]] = None) -> bool:
    """Create the session mark with O_CREAT | O_EXCL; False when another process created it first.
    `created` gets the path as soon as the file is ours, so a refused open (a mark held by another process)
    never makes the caller remove that process's file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return False
    if created is not None:
        created.append(path)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(mark, ensure_ascii=False, indent=2) + "\n")
    return True


def _restore_mark(path: str, raw: bytes) -> bool:
    """Put a mark displaced by --begin back byte for byte. Exclusive create: a mark another --begin
    created meanwhile is kept. False when the mark could not be put back."""
    try:
        with open(path, "xb") as fh:
            fh.write(raw)
    except OSError:
        return False
    return True


def session_begin(journal: str, host: Optional[str] = None, takeover: bool = False) -> Dict[str, Any]:
    """New session: the mark file and an entry in runner.sessions, both under the journal lock; the mark
    is created with O_EXCL. A fresh mark (younger than SESSION_STALE_SECONDS) is session-active, a stale
    one while a stage is running is session-stale-running, unless `takeover`; nothing is written then.
    Journal sessions left open become interrupted. When the journal write or the creation of the mark fails,
    the mark claimed here is removed and a mark it displaced (takeover, abandoned) is put back byte for byte."""
    bt = _brainstorm()
    journal = os.path.abspath(journal)
    path = _session_file(journal)
    session_id, now = uuid.uuid4().hex[:12], _iso_now()

    def mutate(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        runner = _runner_of(data, journal)
        mark = _read_session(path)
        age = None if mark is None else _session_age(mark)
        if mark is not None and not takeover:
            if age is not None and age < SESSION_STALE_SECONDS:
                raise ChainError(f"session-active: {journal}", id=mark.get("id"), host=mark.get("host"),
                                 age_seconds=age)
            running = _running_stage(data)
            if running is not None:  # a foreground agent may run longer than 30 minutes without heartbeat
                raise ChainError(f"session-stale-running: {journal}", plan=running[0], stage=running[1],
                                 age_seconds=age)
        if os.path.exists(path):  # abandoned, unreadable or taken over: put back if the journal write fails
            displaced[:] = [_read_mark_bytes(path)]
            bt._remove_quiet(path, retry_seconds=1.0)
        # An OSError leaves in `claimed` only a file we created (maybe half written): the rollback removes it
        # and puts the displaced mark back.
        won = _claim_mark(path, {"id": session_id, "host": host or runner.get("profile"), "journal": journal,
                                 "heartbeat_at": now}, claimed)
        if not won:
            displaced.clear()  # another --begin created its mark first: it stays, there is nothing to put back
            raise ChainError(f"session-active: {journal}", id=None, host=None, age_seconds=None)
        for item in runner["sessions"]:
            if isinstance(item, dict) and item.get("end") is None:
                item["ended_at"], item["end"] = now, "interrupted"
        runner["sessions"].append({"id": session_id, "started_at": now, "ended_at": None, "end": None})
        return None if mark is None else {"id": mark.get("id"), "host": mark.get("host"), "age_seconds": age}

    claimed: List[str] = []
    displaced: List[Optional[bytes]] = []
    try:
        previous = bt.journal_update(journal, mutate)
    except BaseException as exc:  # the journal has no such session: its mark goes, the displaced one comes back
        notes: List[str] = []
        removed = True
        if claimed:
            removed = bt._remove_quiet(path, retry_seconds=1.0)
            if not removed:
                notes.append(f"session mark not removed: {path}")
        if displaced and displaced[0] is not None and not (removed and _restore_mark(path, displaced[0])):
            notes.append(f"previous session mark not restored: {path}")
        if notes and isinstance(exc, Exception) and exc.args:
            exc.args = (f"{exc.args[0]}; " + "; ".join(notes),) + exc.args[1:]
        raise
    return {"ok": True, "id": session_id, "session_file": path, "previous": previous}


def _own_mark(journal: str, session_id: str) -> Tuple[str, Dict[str, Any]]:
    """The mark of session `session_id`; session-taken-over (nothing written) when the mark is missing
    or holds another id: another window took the run over or closed it."""
    path = _session_file(journal)
    mark = _read_session(path)
    if mark is None or mark.get("id") != session_id:
        raise ChainError(f"session-taken-over: {os.path.abspath(journal)}", id=session_id,
                         mark_id=None if mark is None else mark.get("id"))
    return path, mark


def session_heartbeat(journal: str, session_id: str) -> Dict[str, Any]:
    """Refresh heartbeat_at of this session's mark; the journal is never read or written (safe during an audit)."""
    path, mark = _own_mark(journal, session_id)
    mark["heartbeat_at"] = _iso_now()
    _own_mark(journal, session_id)  # again right before the write: a takeover may have come meanwhile
    _write_session(path, mark)
    _own_mark(journal, session_id)  # and after it: a takeover that came with the write is reported, not overwritten
    return {"ok": True, "id": mark.get("id"), "heartbeat_at": mark["heartbeat_at"]}


def session_end(journal: str, end: str, session_id: str) -> Dict[str, Any]:
    """Close this session in runner.sessions (ended_at, end) and remove its mark. The mark is checked
    again under the journal lock (where --begin takes a mark over) and removed there only while it is
    still this session's; otherwise session-taken-over and nothing is written."""
    bt = _brainstorm()
    journal = os.path.abspath(journal)
    path, mark = _own_mark(journal, session_id)
    now = _iso_now()

    removed: List[bool] = []

    def mutate(data: Dict[str, Any]) -> bool:
        sessions = _runner_of(data, journal)["sessions"]
        _own_mark(journal, session_id)
        removed[:] = [bt._remove_quiet(path, retry_seconds=1.0)]
        for item in sessions:
            if isinstance(item, dict) and item.get("id") == mark.get("id"):
                item["ended_at"], item["end"] = now, end
                return True
        return False

    recorded = bt.journal_update(journal, mutate)
    return {"ok": True, "id": mark.get("id"), "end": end, "recorded": recorded, "mark_removed": all(removed)}


def cmd_run_session(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    if not args.begin and (args.host or args.takeover):
        raise InputError("--host and --takeover go with --begin")
    if args.begin:
        if args.id:
            raise InputError("--id goes with --heartbeat and --end")
        return 0, session_begin(args.journal, args.host, args.takeover)
    if not args.id:
        raise InputError("--heartbeat and --end need --id <id returned by --begin>")
    if args.heartbeat:
        return 0, session_heartbeat(args.journal, args.id)
    return 0, session_end(args.journal, args.end, args.id)


# run-next, run-eta, run-status (spec plan-chain-runner-2, section B): what the runner launches now,
# read from the journal alone. Agents the runner launched and that have not returned come in as
# --in-flight; any other `running` stage is a resume of its owner. None of these commands writes the
# journal (an audit may be running).


JOURNAL_TIME_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")


def _time_errors(data: Dict[str, Any]) -> List[str]:
    """Time fields the scheduler compares as strings (stage starts and ends, question times): each is
    absent, null or a journal time YYYY-MM-DDTHH:MM:SSZ. Called on a journal without structure errors."""
    fields = [(f"plans[{index}].stages.{stage}.{name}", record.get(name))
              for index, entry in enumerate(data["plans"]) for stage, record in entry["stages"].items()
              for name in ("started_at", "finished_at")]
    fields += [(f"questions[{index}].{name}", question.get(name))
               for index, question in enumerate(data["questions"]) for name in ("asked_at", "answered_at")]
    return [f"{where}: not a journal time (YYYY-MM-DDTHH:MM:SSZ)" for where, value in fields
            if value is not None and not (isinstance(value, str) and JOURNAL_TIME_RE.fullmatch(value))]


def _runner_journal(journal: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """(journal, its runner section); a journal error of brainstorm_tool is an InputError (exit 2), and
    so is a journal that fails journal-validate's structure checks or has a time field the scheduler
    cannot compare (journal-corrupt with its errors). The event replay is not checked: it decides
    nothing the scheduler reads."""
    bt = _brainstorm()
    try:
        data = bt.journal_load(journal)
    except bt.InputError as exc:
        raise InputError(str(exc)) from exc
    errors = bt._journal_structure_errors(data) or _time_errors(data)
    if errors:
        raise InputError(f"journal-corrupt: {journal}: " + "; ".join(errors))
    return data, _runner_of(data, journal)


def _derived_plan(spec: str) -> str:
    """Plan of a spec before plan-writing ran, by the rule of plan_tool.py plan-path:
    `<X>-spec.md` -> `<X>-impl.md`, `spec.md` -> `impl.md`, other -> `<name>-impl.md`."""
    directory, _, name = spec.replace("\\", "/").rpartition("/")
    stem = os.path.splitext(name)[0]
    root = "" if stem.lower() == "spec" else stem[:-len("-spec")] if stem.lower().endswith("-spec") else stem
    impl = f"{root}-impl.md" if root else "impl.md"
    return f"{directory}/{impl}" if directory else impl


def _journal_entry(data: Dict[str, Any], spec: str) -> Optional[Dict[str, Any]]:
    """The journal's plan entry of `spec`: by its spec, else an entry created without --spec
    (journal-question before plan-writing) by the plan id derived from the spec; None when there is none."""
    entry = next((item for item in data["plans"] if item.get("spec") == spec), None)
    if entry is None:
        plan_id = _brainstorm()._journal_plan_id(_derived_plan(spec))
        entry = next((item for item in data["plans"] if not item.get("spec") and item.get("id") == plan_id), None)
    return entry


def _plan_states(journal: str, data: Dict[str, Any], runner: Dict[str, Any]) -> List[Dict[str, Any]]:
    """One record per runner spec, in runner order: its plan entry (a pending one before plan-writing),
    the chain settings (of the plan when it exists, else of the spec), the plan's questions and the
    ids of the open ones."""
    bt = _brainstorm()
    directory = os.path.dirname(os.path.abspath(journal))
    states: List[Dict[str, Any]] = []
    for spec in runner.get("specs") or []:
        plan = _derived_plan(spec)
        entry = _journal_entry(data, spec)
        if entry is None:
            entry = {"id": bt._journal_plan_id(plan), "spec": spec, "plan": plan,
                     "stages": {stage: {"status": "pending"} for stage in bt.STAGES}}
        plan_path = os.path.join(directory, entry.get("plan") or plan)
        source = plan_path if os.path.isfile(plan_path) else os.path.join(directory, spec)
        try:  # the plan header wins over the spec (answers of the start card for an old spec)
            chain = bt.resolve_settings(source)["chain"]
        except bt.InputError as exc:
            raise InputError(str(exc)) from exc
        questions = [q for q in data["questions"] if q.get("plan") == entry["id"]]
        states.append({"spec": spec, "entry": entry, "chain": chain, "questions": questions,
                       "open": [q["id"] for q in questions if q.get("status") == "open"], "root": directory})
    return states


def _record(state: Dict[str, Any], stage: str) -> Dict[str, Any]:
    return state["entry"]["stages"].get(stage) or {"status": "pending"}


def _latest_question(state: Dict[str, Any], stage: str, prefix: str) -> Optional[Dict[str, Any]]:
    """The plan's last question of `stage` whose text starts with `prefix` (machine questions)."""
    found = [q for q in state["questions"] if q.get("stage") == stage and str(q.get("text", "")).startswith(prefix)]
    return found[-1] if found else None


def _answered_after(question: Optional[Dict[str, Any]], answer: str, stamp: str) -> bool:
    """`question` was answered `answer` after `stamp` (the stage has not acted on it yet). A stage event in
    the same second as the answer counts as after it, so one answer moves the stage once."""
    return (question is not None and question.get("status") != "open" and question.get("answer") == answer
            and stamp < (question.get("answered_at") or ""))


def _input_changed(state: Dict[str, Any], record: Dict[str, Any]) -> bool:
    """The done stage's stored input (relative to the journal) now hashes differently from
    input_sha256. No stored input or an unreadable file: unchanged, as journal-event decides drift."""
    if not record.get("input") or not record.get("input_sha256"):
        return False
    try:
        digest = _brainstorm()._sha256(os.path.join(state.get("root") or "", record["input"]))
    except OSError:
        return False
    return digest != record["input_sha256"]


def _reentry_reason(state: Dict[str, Any], stage: str) -> Optional[str]:
    """Rule 9 for a done stage: 'drift' after a drift question answered rewrite, 'audit-open' after an
    open-audit question answered fix, while the stage has not finished again since the answer."""
    finished = _record(state, stage).get("finished_at") or ""
    if _answered_after(_latest_question(state, stage, f"drift: {stage} "), "rewrite", finished):
        return "drift"
    if stage == "audit" and _answered_after(_latest_question(state, stage, "open-audit: "), "fix", finished):
        return "audit-open"
    return None


def _next_stage(state: Dict[str, Any]) -> Optional[Tuple[str, Optional[str]]]:
    """Rules 7 and 9: (stage, re-entry reason) of the plan's next step, None when every stage is done
    or skipped and up to date. A done stage that finished before the previous non-skipped stage is
    stale only when its input changed and no `keep` answered its drift question since it finished:
    drift. commit finished before execution or audit (the stages that change files), e.g. an execution
    run again under a kept audit: recommit. A current stage becomes `previous`.
    diffs is never stale: FINALIZE and COMMIT rebuild it in place."""
    previous = newest = ""
    for stage in _brainstorm().STAGES:
        record = _record(state, stage)
        status = record.get("status", "pending")
        if status == "skipped":
            continue
        if status != "done":
            return stage, None
        finished = record.get("finished_at") or ""
        reason = _reentry_reason(state, stage)
        if reason is None and stage == "commit" and finished and finished < newest:
            reason = "recommit"
        elif reason is None and stage != "diffs" and previous and finished and finished < previous:
            kept = _answered_after(_latest_question(state, stage, f"drift: {stage} "), "keep", finished)
            if _input_changed(state, record) and not kept:
                reason = "drift"
        if reason is not None:
            return stage, reason
        if stage != "diffs":
            previous = finished
        if stage in ("execution", "audit"):
            newest = max(newest, finished)
    return None


STAGE_ROLES = {"writing": "writing", "revision": "revision", "split": "split", "execution": "execution",
               "diffs": "execution", "audit": "audit", "commit": "commit"}


def _run_action(state: Dict[str, Any], stage: str, reason: Optional[str]) -> Dict[str, Any]:
    """Stage → skill and args (spec B table). execution and diffs run the roadmap once split is done;
    audit adds `auto` for resolver=auto and is `fix` after an open-audit answered fix."""
    plan = state["entry"]["plan"]
    split = _record(state, "split")
    if stage == "writing":
        args = [state["spec"]]
    elif stage in ("execution", "diffs"):
        roadmap = (split.get("artifacts") or {}).get("roadmap")
        args = [roadmap if split.get("status") == "done" and roadmap else plan]
    elif stage == "audit" and reason == "audit-open":
        args = [plan, "fix"]
    elif stage == "audit":
        args = [plan, "auto"] if state["chain"].get("resolver") == "auto" else [plan]
    elif stage == "commit":
        args = [plan, "commit"]
    else:
        args = [plan]
    return {"kind": "run", "spec": state["spec"], "plan": plan, "stage": stage,
            "skill": _brainstorm().STAGE_OWNERS[stage], "args": args, "role": STAGE_ROLES[stage], "reason": reason}


QUESTION_OPTIONS = {"open-audit": ["accept", "fix"], "stage-failed": ["retry", "stop"],
                    "plan-oversized": ["continue", "split", "stop"]}


def _failures(data: Dict[str, Any], plan_id: str, stage: str) -> int:
    """How many times the stage ended failed since it last ended done (stage-end and reconcile events)."""
    count = 0
    for event in data["events"]:
        if event.get("plan") != plan_id or event.get("stage") != stage:
            continue
        if event.get("kind") in ("stage-end", "reconcile"):
            target = (event.get("data") or {}).get("to")
            count = 0 if target == "done" else count + (target == "failed")
    return count


# host-wait (spec plan-refactoring-03): a transient error of the host's agent call repeats the stage after a growing
# pause. HOST_ERROR_RE classifies the error text of the launch tool, never an agent's ordinary reply.
HOST_ERROR_RE = re.compile(
    r"\b(?:529|429)\b|overloaded|rate[\s_-]?limit|too many requests"
    r"|\b(?:api|http)[\s_-]*(?:error|status)?[\s:=]*5\d\d\b"
    r"|internal server error|bad gateway|service unavailable|gateway time-?out"
    r"|connection (?:reset|refused|aborted|closed|error|lost|dropped)|econnreset|socket hang up|network error"
    r"|time[sd]?[\s_-]?out", re.IGNORECASE)
HOST_WAITS = (60, 120, 300, 600)  # seconds; the last one repeats until the series has waited HOST_WAIT_TOTAL
HOST_WAIT_TOTAL = 3600


def _iso_at(seconds: float) -> str:
    """A moment in seconds as a journal time YYYY-MM-DDTHH:MM:SSZ (UTC), like _iso_now."""
    return datetime.datetime.fromtimestamp(seconds, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _plan_entry_of(data: Dict[str, Any], plan: str) -> Dict[str, Any]:
    """The journal's plan entry named by `plan`, a plan id or a plan path; unknown-plan (exit 2) without one."""
    plan_id = _brainstorm()._journal_plan_id(plan)
    entry = next((item for item in data["plans"] if item.get("id") == plan_id), None)
    if entry is None:
        raise InputError(f"unknown-plan: {plan}")
    return entry


def _last_stage_move(data: Dict[str, Any], plan_id: str, stage: str) -> int:
    """Index in `events` of the plan stage's last stage-start or stage-end, -1 without one."""
    for index in range(len(data["events"]) - 1, -1, -1):
        event = data["events"][index]
        if (event.get("plan"), event.get("stage")) == (plan_id, stage) and event.get("kind") in ("stage-start", "stage-end"):
            return index
    return -1


def _host_series_start(data: Dict[str, Any], plan_id: str, stage: str) -> int:
    """Index in `events` after which the stage's current host-error series begins: its last stage-start or stage-end,
    or the answer `retry` to a `stage-failed: <stage>` question (a launch that failed leaves no stage-start)."""
    retried = {q.get("id") for q in data.get("questions") or []
               if (q.get("plan"), q.get("stage")) == (plan_id, stage) and q.get("answer") == "retry"
               and str(q.get("text", "")).startswith(f"stage-failed: {stage}")}
    answers = [index for index, event in enumerate(data["events"])
               if event.get("kind") == "answer" and (event.get("plan"), event.get("stage")) == (plan_id, stage)
               and (event.get("data") or {}).get("id") in retried]
    return max([_last_stage_move(data, plan_id, stage), *answers])


def _host_series(data: Dict[str, Any], plan_id: str, stage: str) -> List[Dict[str, Any]]:
    """The stage's runner.host_errors written after _host_series_start: the current series."""
    last = _host_series_start(data, plan_id, stage)
    runner = data.get("runner") if isinstance(data.get("runner"), dict) else {}
    return [item for item in runner.get("host_errors") or []
            if (item.get("plan"), item.get("stage")) == (plan_id, stage) and item.get("at_event", -1) > last]


def _host_item(doc: Dict[str, Any], journal: str, plan_id: str, stage: str, error: str, now: float, wait: int,
               attempt: int, total: int, exhausted: bool = False) -> Dict[str, Any]:
    """Append one record to runner.host_errors inside a journal_update; an exhausted one carries exhausted_for, its
    event the stage's last stage-start or stage-end (the failed stage-end)."""
    item = {"plan": plan_id, "stage": stage, "at": _iso_at(now), "error": error.strip(), "attempt": attempt,
            "wait_seconds": wait, "wait_until": _iso_at(now + wait), "waited_total": total,
            "at_event": len(doc["events"])}
    if exhausted:
        item["exhausted_for"] = {"plan": plan_id, "stage": stage, "attempt": attempt,
                                 "event": _last_stage_move(doc, plan_id, stage)}
    _runner_of(doc, journal).setdefault("host_errors", []).append(item)
    return item


def _host_exhaust(journal: str, plan_id: str, stage: str, status: str, error: str, now: float, attempt: int,
                  total: int) -> Dict[str, Any]:
    """The series has waited HOST_WAIT_TOTAL: the stage goes to failed through journal_event under plan-chain-runner
    (data why: host-error; pending, stopped and failed through running), then the record with exhausted_for. A
    stopped stage with open questions is the journal's open-questions error: nothing is written."""
    bt = _brainstorm()
    if status in ("pending", "stopped", "failed"):
        bt.journal_event(journal, "plan-chain-runner", plan_id, stage, "running", data={"why": "host-error"})
    bt.journal_event(journal, "plan-chain-runner", plan_id, stage, "failed", data={"why": "host-error"})
    return bt.journal_update(journal, lambda doc: _host_item(doc, journal, plan_id, stage, error, now, 0, attempt,
                                                             total, exhausted=True))


def host_wait(journal: str, plan: str, stage: str, error: str) -> Dict[str, Any]:
    """A failed agent call of the plan's stage: text HOST_ERROR_RE does not match → host_error false, nothing
    written; else the next pause of HOST_WAITS, then _host_exhaust after HOST_WAIT_TOTAL. An exhausted series answers
    so and writes nothing until the stage moves or a `retry` answers its question (_host_series_start).
    stage-not-open (exit 1) for a done or skipped stage; unknown plan or stage: exit 2."""
    bt = _brainstorm()
    journal = os.path.abspath(journal)
    if stage not in bt.STAGES:
        raise InputError(f"unknown-stage: {stage}")
    data, _ = _runner_journal(journal)
    entry = _plan_entry_of(data, plan)
    plan_id, status = entry["id"], (entry["stages"].get(stage) or {}).get("status", "pending")
    if status in ("done", "skipped"):
        raise ChainError(f"stage-not-open: {plan_id} {stage} is {status}", plan=plan_id, stage=stage, status=status)
    if not HOST_ERROR_RE.search(error or ""):
        return {"ok": True, "host_error": False}
    now = _now()

    def pause(doc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        series = _host_series(doc, plan_id, stage)
        exhausted = [item for item in series if "exhausted_for" in item]
        if exhausted:
            return exhausted[-1]
        waited = sum(item["wait_seconds"] for item in series)
        wait = min(HOST_WAITS[min(len(series), len(HOST_WAITS) - 1)], HOST_WAIT_TOTAL - waited)
        if wait <= 0:
            return None
        return _host_item(doc, journal, plan_id, stage, error, now, wait, len(series) + 1, waited + wait)

    item = bt.journal_update(journal, pause)
    if item is None:
        series = _host_series(bt.journal_load(journal), plan_id, stage)
        item = _host_exhaust(journal, plan_id, stage, status, error, now, len(series) + 1,
                             sum(record["wait_seconds"] for record in series))
    return {"ok": True, "host_error": True, "attempt": item["attempt"], "wait_seconds": item["wait_seconds"],
            "waited_total": item["waited_total"], "wait_until": item["wait_until"],
            "exhausted": "exhausted_for" in item}


def _host_wait_left(data: Dict[str, Any], plan_id: str, stage: str) -> Optional[int]:
    """Seconds left (rounded up) until wait_until of the stage's current host-error series; None for no series, an
    exhausted one or a moment passed. The one comparison with the clock."""
    series = _host_series(data, plan_id, stage)
    if not series or "exhausted_for" in series[-1]:
        return None
    until = _parse_iso(series[-1].get("wait_until"))
    left = None if until is None else int(-(-(until - _now()) // 1))
    return left if left is not None and left > 0 else None


def _host_exhausted(data: Dict[str, Any], plan_id: str, stage: str) -> Optional[Dict[str, Any]]:
    """The stage's last record with exhausted_for while its event is still the stage's last stage-start or
    stage-end, else None: the next stage-start lifts the mark."""
    runner = data.get("runner") if isinstance(data.get("runner"), dict) else {}
    for item in reversed(runner.get("host_errors") or []):
        mark = item.get("exhausted_for")
        if (item.get("plan"), item.get("stage")) == (plan_id, stage) and isinstance(mark, dict):
            return item if mark.get("event") == _last_stage_move(data, plan_id, stage) else None
    return None


# plan-oversized (spec 1 of plan-refactoring-04): with split=never a plan over brainstorm_tool.SIZE_BUDGET stops on one
# question before its split is skipped; the plan's sha256 in the text ties an answer to the plan it was given for.
PLAN_OVERSIZED_RE = re.compile(r"^plan-oversized: (?P<tasks>\d+) tasks, (?P<bytes>\d+) bytes "
                               r"\(budget \d+ / \d+; plan sha256 (?P<sha>[0-9a-f]{12})\)")


def _plan_size(state: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """({tasks, bytes, sha, max_tasks, max_bytes}, None) of the plan file: tasks by parse_plan_tasks, its bytes, the
    first 12 hex of its sha256 and SIZE_BUDGET; (None, "size-unavailable: <error>") when it cannot be measured."""
    path = os.path.join(state.get("root") or "", state["entry"]["plan"])
    try:
        bt = _brainstorm()
        budget = bt.SIZE_BUDGET
        with open(path, "rb") as fh:
            raw = fh.read()
        tasks = len(bt.parse_plan_tasks(raw.decode("utf-8", errors="replace"))["tasks"])
    except (InputError, OSError, AttributeError) as exc:
        return None, f"size-unavailable: {exc}"
    return {"tasks": tasks, "bytes": len(raw), "sha": hashlib.sha256(raw).hexdigest()[:12],
            "max_tasks": int(budget["tasks"]), "max_bytes": int(budget["bytes"])}, None


def _oversized_reason(text: Any) -> Optional[str]:
    """`plan-oversized: N tasks, M bytes` of a plan-oversized: question text, None for another text."""
    match = PLAN_OVERSIZED_RE.match(str(text or ""))
    return f"plan-oversized: {match.group('tasks')} tasks, {match.group('bytes')} bytes" if match else None


def _oversized_step(state: Dict[str, Any], where: Dict[str, Any]) -> Dict[str, Any]:
    """The pending split of a split=never plan: a skip within the budget (or with size-unavailable), else the
    plan-oversized: question with the plan's sha256 and the options continue / split / stop. Its question of this sha256: open → wait,
    continue → skip, split → run the splitter, stop or another answer → wait."""
    size, warning = _plan_size(state)
    if size is None:
        return dict(where, kind="skip", why="split=never", warnings=[warning])
    if size["tasks"] <= size["max_tasks"] and size["bytes"] <= size["max_bytes"]:
        return dict(where, kind="skip", why="split=never")
    reason = f"plan-oversized: {size['tasks']} tasks, {size['bytes']} bytes"
    same = [q for q in state["questions"] if q.get("stage") == "split" and _oversized_reason(q.get("text"))
            and PLAN_OVERSIZED_RE.match(str(q["text"])).group("sha") == size["sha"]]
    if same:  # a question of another sha256 was given for another plan: asked again
        question = same[-1]
        if question.get("status") == "open":
            return dict(where, kind="wait", why=reason)
        if question.get("answer") == "continue":
            return dict(where, kind="skip", why="plan-oversized: continue")
        if question.get("answer") == "split":
            return _run_action(state, "split", None)  # the splitter splits as with always (--reason user-request)
        return dict(where, kind="wait", why="plan-oversized: stop")  # like stage-failed: stop, without a question
    return dict(where, kind="ask", options=list(QUESTION_OPTIONS["plan-oversized"]),
                prefix=f"{reason} (budget {size['max_tasks']} / {size['max_bytes']}; plan sha256 {size['sha']})")


def _stage_step(data: Dict[str, Any], state: Dict[str, Any], stage: str, reason: Optional[str]) -> Dict[str, Any]:
    """The step for the plan's next stage (open questions are checked before): a run, a skip
    (split=never within the budget, resolver=skip; plan-oversized: over it, _oversized_step), an ask (rule 10: stage-failed; at once after an exhausted host wait) or {"kind": "wait", "why"}.
    A running audit started by an open-audit `fix` resumes as `fix`."""
    record = _record(state, stage)
    status = record.get("status", "pending")
    where = {"spec": state["spec"], "plan": state["entry"]["plan"], "stage": stage}
    if status == "pending" and stage == "split" and state["chain"].get("split") == "never":
        return _oversized_step(state, where)  # plan-oversized: before the skip (spec 1 of plan-refactoring-04)
    if status == "pending" and stage == "audit" and state["chain"].get("resolver") == "skip":
        return dict(where, kind="skip", why="resolver=skip")
    gate_warning = None
    if status == "pending" and stage == "split" and state["chain"].get("split") == "auto":
        verdict, gate_warning = _split_gate(state)
        if verdict is not None and verdict.get("silent_verdict", verdict["verdict"]) == "keep":
            return dict(where, kind="skip", why=_gate_why(verdict))
    touched = max(record.get("started_at") or "", record.get("finished_at") or "")
    for prefix, name in (("not-confirmed", stage), ("stage-failed", stage), ("model", STAGE_ROLES[stage])):
        # stop: the plan waits until the stage moves again (the user ran or fixed it by hand).
        question = _latest_question(state, stage, f"{prefix}: {name}")
        if status != "done" and _answered_after(question, "stop", touched):
            return dict(where, kind="wait", why=f"{prefix}: stop")
    model = _latest_question(state, stage, f"model: {STAGE_ROLES[stage]}")
    if (status != "done" and model is not None and model.get("status") == "answered"
            and str(model.get("answer") or "").startswith("retry ") and touched <= (model.get("answered_at") or "")):
        # retry <model>: wait until the runner's run-init sets that model and marks the answer applied.
        return dict(where, kind="wait", why="model: retry")
    if status == "failed":
        asked = _latest_question(state, stage, f"stage-failed: {stage}")
        current = asked is not None and (asked.get("asked_at") or "") >= (record.get("finished_at") or "")
        exhausted = _host_exhausted(data, state["entry"]["id"], stage)
        if not current and (exhausted is not None or _failures(data, state["entry"]["id"], stage) >= 2):
            ask = dict(where, kind="ask", prefix=f"stage-failed: {stage}",
                       options=list(QUESTION_OPTIONS["stage-failed"]))
            if exhausted is not None:  # an hour of host errors: no automatic repeat
                ask["host_error"] = {key: exhausted[key] for key in ("attempt", "waited_total", "error")}
            return ask
    if stage == "audit" and status == "running" and reason is None:  # an interrupted fix resumes as a fix
        starts = [event for event in data["events"] if event.get("plan") == state["entry"]["id"]
                  and event.get("stage") == "audit" and event.get("kind") == "stage-start"]
        decided = _latest_question(state, "audit", "open-audit: ")
        if (starts and (starts[-1].get("data") or {}).get("reason") == "audit-open" and decided is not None
                and decided.get("status") != "open" and decided.get("answer") == "fix"):
            reason = "audit-open"
    action = _run_action(state, stage, reason)
    if gate_warning:
        action["warnings"] = [gate_warning]
    return action


def _dependency_wait(runner: Dict[str, Any], by_spec: Dict[str, Dict[str, Any]], state: Dict[str, Any],
                     asks: Dict[str, Dict[str, Any]]) -> Optional[str]:
    """Rules 1 and 4 for the writing stage of `state`: why it waits for a spec it depends on, or None.
    An open audit of a finished dependency without an `accept` puts an open-audit ask into `asks`."""
    for dep in (runner.get("graph") or {}).get(state["spec"]) or []:
        other = by_spec.get(dep)
        if other is None:  # run-init and journal-validate keep the graph inside runner.specs
            continue
        if other["open"]:
            return f"held-by: {other['entry']['id']}"
        if _record(other, "commit").get("status") not in ("done", "skipped") or other["next"] is not None:
            return f"depends-on: {dep}"
        if (_record(other, "audit").get("artifacts") or {}).get("status") != "open":
            continue
        decided = _latest_question(other, "audit", "open-audit: ")
        if decided is not None and decided.get("status") != "open" and decided.get("answer") == "accept":
            continue
        # No question yet, or a fix after which the audit is still open: a new decision is needed.
        asks[dep] = {"kind": "ask", "spec": dep, "plan": other["entry"]["plan"], "stage": "audit",
                     "prefix": f"open-audit: {other['entry']['id']}", "options": list(QUESTION_OPTIONS["open-audit"])}
        return f"open-audit: {other['entry']['id']}"
    return None


CODE_STAGES = ("execution", "diffs", "audit", "commit")
# Stages that read the code the holder of CODE_STAGES changes in the shared working copy (F2 of plan-refactoring-02):
# the revision's diff guard compares a snapshot of the whole tree, so they wait for the holder; writing does not wait.
CODE_READING_STAGES = ("revision", "split")


def _uncommitted(state: Dict[str, Any]) -> bool:
    """Execution has started and no commit done (or skipped) after that start took its changes in."""
    started = _record(state, "execution").get("started_at") or ""
    commit = _record(state, "commit")
    return bool(started) and not (commit.get("status") in ("done", "skipped")
                                  and (commit.get("finished_at") or "") >= started)


def _in_code_phase(state: Dict[str, Any]) -> bool:
    """The plan has started its code stages and not finished them: it holds the working copy (rule 2).
    A plan sent back to an earlier stage (drift) after its execution started keeps holding it while
    its changes are uncommitted."""
    step = state["next"]
    if step is None:
        return False
    if step[0] in CODE_STAGES and (step[0] != "execution" or _record(state, "execution").get("status") != "pending"):
        return True
    return _uncommitted(state)


def _cascade(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Rule 9 cascade: open `drift: <stage>` questions (journal-reconcile) of a plan that has a drift
    question of an earlier stage answered rewrite strictly after this stage finished. An answer in the
    same second as the stage end does not count (_answered_after compares strictly, so one answer moves
    a stage once): that drift question stays open and is asked like any other. The runner answers the
    cascade rewrite itself: the cascade asks the user nothing."""
    stages = list(_brainstorm().STAGES)
    found = []
    for question in state["questions"]:
        stage = question.get("stage")
        if (question.get("status") != "open" or stage not in stages
                or not str(question.get("text", "")).startswith(f"drift: {stage} ")):
            continue
        finished = _record(state, stage).get("finished_at") or ""
        if any(_answered_after(_latest_question(state, earlier, f"drift: {earlier} "), "rewrite", finished)
               for earlier in stages[:stages.index(stage)]):
            found.append(question)
    return found


def _writing_resumes(state: Dict[str, Any]) -> bool:
    """The plan file of the plan carries plan-writing's writing marker (brainstorm_tool.writing_marker; spec 3 of
    plan-refactoring-02): its writer was cut off, and a new one continues after the last task written (LOOP.md, 4)."""
    marker = getattr(_brainstorm(), "writing_marker", None)
    text = _text_metrics_text(os.path.join(state.get("root") or "", state["entry"]["plan"]))
    return marker is not None and bool(text) and marker(text) is not None


def writing_resume(journal: str, plan: str) -> Dict[str, Any]:
    """Before a writer is relaunched with resume: true: the plan file's task count (parse_plan_tasks), bytes and
    sha256 appended to runner.writing_resumes. No plan file: exit 2 plan-missing; no writing marker: exit 1
    no-marker; nothing is written then."""
    bt = _brainstorm()
    journal = os.path.abspath(journal)
    data, _ = _runner_journal(journal)
    entry = _plan_entry_of(data, plan)
    path = os.path.join(os.path.dirname(journal), entry["plan"])
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError as exc:
        raise InputError(f"plan-missing: {path}: {exc}") from exc
    parsed = bt.parse_plan_tasks(raw.decode("utf-8", errors="replace"))
    if not parsed["incomplete"]:
        raise ChainError(f"no-marker: {entry['plan']}", plan=entry["id"])

    def mutate(doc: Dict[str, Any]) -> Dict[str, Any]:
        item = {"plan": entry["id"], "tasks": len(parsed["tasks"]), "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(), "at_event": len(doc["events"])}
        _runner_of(doc, journal).setdefault("writing_resumes", []).append(item)
        return item

    return dict({"ok": True}, **bt.journal_update(journal, mutate))


def _writing_stalled(data: Dict[str, Any], state: Dict[str, Any]) -> bool:
    """No progress: the plan's last three runner.writing_resumes records after the last `retry` answer of a
    `stage-failed: writing` question have the same task count and sha256."""
    plan_id = state["entry"]["id"]
    retried = {q.get("id") for q in state["questions"] if q.get("stage") == "writing" and q.get("answer") == "retry"
               and str(q.get("text", "")).startswith("stage-failed: writing")}
    start = max((index for index, event in enumerate(data["events"])
                 if event.get("kind") == "answer" and (event.get("data") or {}).get("id") in retried), default=-1)
    runner = data.get("runner") if isinstance(data.get("runner"), dict) else {}
    marks = [(item.get("tasks"), item.get("sha256")) for item in runner.get("writing_resumes") or []
             if item.get("plan") == plan_id and item.get("at_event", -1) > start]
    return len(marks) >= 3 and len(set(marks[-3:])) == 1


def _reads_code(state: Dict[str, Any], flying: Dict[str, str]) -> bool:
    """The plan reads the code now: its revision or split is running or has an agent in flight (CODE_READING_STAGES)."""
    return (flying.get(state["entry"]["id"]) in CODE_READING_STAGES
            or any(_record(state, stage).get("status") == "running" for stage in CODE_READING_STAGES))


def _candidates(data: Dict[str, Any], runner: Dict[str, Any], states: List[Dict[str, Any]],
                waiting: List[Dict[str, Any]], asks: Dict[str, Dict[str, Any]],
                flying: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """Rules 1, 2, 4, 7-10: one step per plan that can move; every other unfinished plan goes to
    `waiting` with its reason. One plan at a time holds the code stages: the one already in them
    (even while it waits for an answer), the one with uncommitted changes first (a committed plan
    sent back by drift must not execute over them), else the first plan in runner order that reaches them
    (taken before the loop, so a revision earlier in runner order does not start next to it). The revision
    and split of the other plans wait for the holder too (CODE_READING_STAGES). The first plan to reach them waits
    with reading-busy while another plan's revision or split runs or is in flight, and new readers wait for it
    (code-busy).
    Rule 9 cascade questions do not hold their plan: they become `answer` steps. A plan whose agent
    is in flight (`flying`: plan id -> stage) gets no step; an agent in a code stage holds them.
    A writing running, failed or stopped whose plan file carries the writing marker gets resume: true (spec 3 of
    plan-refactoring-02), or the stage-failed: writing ask when it stalled (_writing_stalled)."""
    flying = flying or {}
    by_spec = {state["spec"]: state for state in states}
    holder = next((state for state in states if flying.get(state["entry"]["id"]) in CODE_STAGES), None)
    holder = holder or next((state for state in states if _in_code_phase(state) and _uncommitted(state)), None)
    holder = holder or next((state for state in states if _in_code_phase(state)), None)
    steps: List[Dict[str, Any]] = []
    for state in states:
        cascade = _cascade(state)
        state["open"] = [qid for qid in state["open"] if qid not in {q["id"] for q in cascade}]
        steps.extend({"kind": "answer", "spec": state["spec"], "plan": state["entry"]["plan"], "stage": q["stage"],
                      "qid": q["id"], "answer": "rewrite", "running": False} for q in cascade)
    pending_holder = None if holder else next((state for state in states if state["entry"]["id"] not in flying
                                               and not state["open"] and state["next"] is not None
                                               and state["next"][0] in CODE_STAGES), None)
    # Mirror rule: the first plan to reach the code stages takes them only when no other plan's revision or split runs
    # or is in flight; meanwhile new readers wait for it (code-busy), so they cannot starve it.
    reader = None if pending_holder is None else next(
        (state for state in states if state is not pending_holder and _reads_code(state, flying)), None)
    if pending_holder is not None and reader is None:
        holder = pending_holder
    for state in states:
        if state["entry"]["id"] in flying:
            stage = flying[state["entry"]["id"]]
            left = _host_wait_left(data, state["entry"]["id"], stage)
            waiting.append({"spec": state["spec"], "plan": state["entry"]["plan"], "stage": stage,
                            "reason": f"host-wait: {left}s" if left else f"in-flight: {stage}"})
            continue
        if state["next"] is None:
            continue
        stage, reason = state["next"]
        where = {"spec": state["spec"], "plan": state["entry"]["plan"], "stage": stage}
        why: Optional[str] = None
        left = _host_wait_left(data, state["entry"]["id"], stage)
        if left:  # a host error of its agent call: the pair waits until wait_until (spec plan-refactoring-03)
            why = f"host-wait: {left}s"
        elif state["open"]:  # an open plan-oversized: question names the plan's size (spec 1 of plan-refactoring-04)
            sized = [reason for q in state["questions"] if q.get("id") in state["open"] and q.get("stage") == "split"
                     for reason in [_oversized_reason(q.get("text"))] if reason]
            why = sized[-1] if sized else "open-question: " + ", ".join(state["open"])
        elif stage == "writing" and _record(state, "writing").get("status") == "pending":
            why = _dependency_wait(runner, by_spec, state, asks)
        if why is None and stage in CODE_STAGES + CODE_READING_STAGES and holder is not None and holder is not state:
            why = f"code-busy: {holder['entry']['id']}"
        elif why is None and reader is not None:
            if state is pending_holder:
                why = f"reading-busy: {reader['entry']['id']}"
            elif stage in CODE_STAGES or (stage in CODE_READING_STAGES
                                          and _record(state, stage).get("status") != "running"):
                why = f"code-busy: {pending_holder['entry']['id']}"
        step = _stage_step(data, state, stage, reason) if why is None else {"kind": "wait", "why": why}
        if step["kind"] == "wait":
            waiting.append(dict(where, reason=step["why"]))
        else:
            step["running"] = _record(state, stage).get("status") == "running"
            if (stage == "writing" and step["kind"] == "run" and _writing_resumes(state)
                    and _record(state, stage).get("status") in ("running", "failed", "stopped")):
                if _writing_stalled(data, state):  # three relaunches without progress: a question, not a fourth
                    step = dict(where, kind="ask", prefix="stage-failed: writing",
                                options=list(QUESTION_OPTIONS["stage-failed"]), running=step["running"])
                else:
                    step["resume"] = True  # relaunched with the same brief, writing-resume first (LOOP.md, 4)
            steps.append(step)
    return steps


def _default_parallel(runner: Dict[str, Any]) -> int:
    """runner.parallel (run-init --parallel: the start card's value), else `parallel` of the profile in
    the settings file, else the built-in one; 1 for an unknown profile."""
    pinned = runner.get("parallel")
    if isinstance(pinned, int) and not isinstance(pinned, bool) and pinned > 0:
        return pinned
    profile = runner.get("profile")
    if profile not in BUILTIN_SETTINGS:
        return 1
    try:
        settings = load_settings(_settings_path(None), profile)
    except InputError:  # an unreadable settings file: the built-in value for this call
        settings = {"ok": False}
    value = settings.get("parallel") if settings["ok"] else None
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return BUILTIN_SETTINGS[profile]["parallel"]


def _in_flight(pairs: Any) -> Dict[str, str]:
    """--in-flight `<plan id>:<stage>` pairs (agents launched and not yet returned) as {plan id: stage}."""
    flying: Dict[str, str] = {}
    for pair in pairs or ():
        plan_id, _, stage = str(pair).rpartition(":")
        if not plan_id or stage not in _brainstorm().STAGES:
            raise InputError(f"--in-flight: expected <plan id>:<stage>, got {pair}")
        flying[plan_id] = stage
    return flying


def run_next(journal: str, parallel: Optional[int] = None, in_flight: Any = ()) -> Dict[str, Any]:
    """Rules 1-11 of spec B: the actions to launch now, the plans that wait and why, done and blocked.
    Agents in flight are not returned again; they count toward rules 2, 3 and 5."""
    data, runner = _runner_journal(journal)
    flying = _in_flight(in_flight)
    if parallel is None:
        parallel = _default_parallel(runner)
    if parallel < 1:
        raise InputError(f"--parallel must be at least 1, got {parallel}")
    states = _plan_states(journal, data, runner)
    for state in states:
        state["next"] = _next_stage(state)
    waiting: List[Dict[str, Any]] = []
    asks: Dict[str, Dict[str, Any]] = {}
    steps = _candidates(data, runner, states, waiting, asks, flying) + list(asks.values())
    # Rule 3: an audit runs alone: while an audit agent is in flight nothing else starts; a running
    # audit is resumed alone; a new one starts alone unless another stage still runs or an agent is
    # in flight (then it waits for the next call). Skips, asks and answers wait as well.
    audit = next((step for step in steps if step["kind"] == "run" and step["stage"] == "audit"), None)
    if "audit" in flying.values():
        held, steps, why = steps, [], "audit-alone"
    elif audit is not None and not flying and (audit["running"] or not any(step.get("running") for step in steps)):
        held, steps, why = [step for step in steps if step is not audit], [audit], "audit-alone"
    else:
        held, why = [audit] if audit is not None else [], "audit-waits"
        steps = [step for step in steps if step is not audit]
    for step in held:
        waiting.append({"spec": step["spec"], "plan": step["plan"], "stage": step["stage"], "reason": why})
    # Rule 5: at most `parallel` runs including the agents in flight, resumes of running stages first;
    # skips, asks and answers are journal writes.
    runs = sorted((step for step in steps if step["kind"] == "run"), key=lambda step: not step["running"])
    width = max(parallel - len(flying), 0)
    chosen = runs[:width]
    for step in runs[width:]:
        waiting.append({"spec": step["spec"], "plan": step["plan"], "stage": step["stage"],
                        "reason": "parallel-limit"})
    actions = chosen + [step for step in steps if step["kind"] != "run"]
    for step in actions:
        step.pop("running", None)
    # Rule 11 (rule 6: limits.enabled is false, nothing is checked).
    done = not flying and all(state["next"] is None and not state["open"] for state in states)
    hosting = any(item["reason"].startswith("host-wait: ") for item in waiting)  # a host wait is not a stop
    return {"ok": True, "journal_dir": os.path.dirname(os.path.abspath(journal)), "actions": actions,
            "waiting": waiting, "done": done, "blocked": not done and not actions and not flying and not hosting}


def cmd_host_wait(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    return 0, host_wait(args.journal, args.plan, args.stage, args.error)


def cmd_writing_resume(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    return 0, writing_resume(args.journal, args.plan)


def cmd_run_next(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    return 0, run_next(args.journal, args.parallel, args.in_flight)


def _parse_iso(value: Any) -> Optional[float]:
    """Seconds of a journal time YYYY-MM-DDTHH:MM:SSZ, None when it is not one."""
    try:
        moment = datetime.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError):
        return None
    return moment.replace(tzinfo=datetime.timezone.utc).timestamp()


def _int_or_none(value: Any) -> Optional[int]:
    """units_done / units_total are stored as strings (journal-event --artifact k=v)."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _spans(data: Dict[str, Any], start: str, end: str, key: Any) -> List[Tuple[Any, float]]:
    """(key, seconds) from each `start` event to the next `end` event of the same plan and key(event)."""
    begun: Dict[Tuple[Any, Any], float] = {}
    spans: List[Tuple[Any, float]] = []
    for event in data["events"]:
        at, mark = _parse_iso(event.get("at")), (event.get("plan"), key(event))
        if at is None:
            continue
        if event.get("kind") == start:
            begun[mark] = at
        elif event.get("kind") == end and mark in begun:
            spans.append((mark[1], at - begun.pop(mark)))
    return spans


def _journal_stats(data: Dict[str, Any], runner: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
    """The journal layer of run-stats for one plan state: per stage its status, the summed minutes of its
    stage-start/stage-end spans, the role's model and effort (runner.models), its artifacts and the actual
    cost the runner recorded (artifacts cost_tokens/cost_source), the host waits of runner.host_errors (host_waits,
    host_waited_seconds); the plan's unit events, audit result and failed stages."""
    plan_id = state["entry"]["id"]
    own = {"events": [event for event in data["events"] if event.get("plan") == plan_id]}
    minutes: Dict[str, float] = {}
    for stage, seconds in _spans(own, "stage-start", "stage-end", lambda event: event.get("stage")):
        minutes[stage] = minutes.get(stage, 0.0) + seconds / 60
    models = runner.get("models") or {}
    marks = [item for item in runner.get("host_errors") or [] if item.get("plan") == plan_id]
    stages: Dict[str, Any] = {}
    for stage in _brainstorm().STAGES:
        record, role = _record(state, stage), models.get(STAGE_ROLES[stage]) or {}
        artifacts = record.get("artifacts") or {}
        stages[stage] = {"status": record.get("status", "pending"),
                         "minutes": round(minutes[stage], 1) if stage in minutes else None,
                         "model": role.get("model"), "effort": role.get("effort"), "artifacts": dict(artifacts),
                         "actual_tokens": _int_or_none(artifacts.get("cost_tokens")),
                         "actual_source": artifacts.get("cost_source"),
                         "host_waits": sum(1 for item in marks if item.get("stage") == stage and item.get("wait_seconds")),
                         "host_waited_seconds": sum(item.get("wait_seconds") or 0 for item in marks
                                                    if item.get("stage") == stage)}
    begun = [(event.get("data") or {}).get("unit") for event in own["events"] if event.get("kind") == "unit-begin"]
    # unit-finish --delegated (spec 8 of plan-refactoring-01): attempts a subagent on the light model made;
    # a failed one is always retried in the main agent, so its fails are the delegated retries.
    delegated = [event.get("data") or {} for event in own["events"]
                 if event.get("kind") == "unit-finish" and (event.get("data") or {}).get("delegated")]
    audit = (_record(state, "audit").get("artifacts") or {})
    return {"stages": stages,
            "units": {"begun": len(begun), "distinct": len(set(begun)), "retries": len(begun) - len(set(begun))},
            "delegated": {"units": len({item.get("unit") for item in delegated}),
                          "retries": sum(1 for item in delegated if item.get("outcome") == "fail")},
            "audit": {"status": audit.get("status"), "issues": _int_or_none(audit.get("issues"))},
            "failed_stages": [stage for stage, item in stages.items() if item["status"] in ("failed", "stopped")]}


# Scope of an incremental pass: review headers (plan-iterative-revision, spec 5 of plan-refactoring-01)
# and report frontmatter (plan-resolver, spec 6). A file without them was a full pass.
_STATS_SCOPE_RE = re.compile(r"^\*\*Audit scope\*\*:\s*(\w+)", re.MULTILINE)
_STATS_TASKS_RE = re.compile(r"^\*\*Audit tasks\*\*:\s*(.+?)\s*$", re.MULTILINE)
_STATS_FM_SCOPE_RE = re.compile(r"^audit_scope:\s*(\w+)\s*$", re.MULTILINE)
_STATS_FM_TASKS_RE = re.compile(r"^audit_tasks:\s*(.+?)\s*$", re.MULTILINE)


def _frontmatter(text: str) -> str:
    """The YAML frontmatter between the leading `---` lines, or an empty string."""
    if not text.startswith("---"):
        return ""
    end = text.find("\n---", 3)
    return text[3:end] if end >= 0 else ""


def _task_key(task_id: str) -> str:
    """brainstorm_tool.normalize_task_id (`01.02` → `1.2`, F7 of plan-refactoring-02) when plan-brainstorming
    provides it, else the id as written: the ids then meet the parser's ids in _scoped_bytes."""
    try:
        normalize = getattr(_brainstorm(), "normalize_task_id", None)
    except InputError:
        normalize = None
    return normalize(task_id) if normalize else task_id


def _audit_scope(text: str, frontmatter: bool) -> Tuple[str, Optional[List[str]]]:
    """(scope, task ids) of a review (markdown headers) or a report (frontmatter): ("full", None) when
    the file has no scope or names `all`, else ("incremental", ids normalized by _task_key)."""
    source = _frontmatter(text) if frontmatter else text
    scope_re, tasks_re = (_STATS_FM_SCOPE_RE, _STATS_FM_TASKS_RE) if frontmatter else (_STATS_SCOPE_RE, _STATS_TASKS_RE)
    scope, tasks = scope_re.search(source), tasks_re.search(source)
    if not scope or scope.group(1).lower() != "incremental":
        return "full", None
    raw = tasks.group(1).strip().strip("[]") if tasks else ""
    if raw.lower() == "all":
        return "full", None
    return "incremental", [_task_key(item.strip().strip("'\"")) for item in raw.split(",") if item.strip()]


def _task_parser() -> Any:
    """brainstorm_tool.parse_plan_tasks when plan-brainstorming provides it (spec 2 of plan-refactoring-01),
    else None: the plan is then read whole."""
    try:
        return getattr(_brainstorm(), "parse_plan_tasks", None)
    except InputError:
        return None


def _task_ranges(plan_text: str) -> Optional[Dict[str, Any]]:
    """{"header": bytes before the first task, "tasks": {id: bytes}} by parse_plan_tasks, which returns
    {"tasks": [...], "malformed": [...], "duplicates": [...]} (spec 2); a task carries `id`, `line_start`,
    `line_end`, 1-based inclusive. None without the parser, without tasks, or when anything in the parser's
    answer is not as expected: the plan is then read whole and run-stats never fails on it."""
    parser = _task_parser()
    if parser is None:
        return None
    try:
        tasks = list(parser(plan_text)["tasks"])
        if not tasks:
            return None
        sizes = [len(line.encode("utf-8")) for line in plan_text.splitlines(keepends=True)]
        first = min(int(task["line_start"]) for task in tasks)
        return {"header": sum(sizes[:first - 1]),
                "tasks": {str(task["id"]): sum(sizes[int(task["line_start"]) - 1:int(task["line_end"])]) for task in tasks}}
    except Exception:  # the parser's own errors or another answer shape: the plan is read whole
        return None


def _scoped_bytes(plan_text: str, plan_bytes: int, ids: Optional[List[str]], name: str,
                  warnings: List[str]) -> Tuple[int, str]:
    """Bytes an incremental pass reads: the plan's header plus the named tasks. Without the task parser the
    whole plan, silently; with an empty list or an id the plan does not have, the whole plan and
    `scope-unresolved: <name>`."""
    if _task_parser() is None:
        return plan_bytes, "full"
    ranges = _task_ranges(plan_text)
    if not ids or ranges is None or any(task_id not in ranges["tasks"] for task_id in ids):
        warnings.append(f"scope-unresolved: {name}")
        return plan_bytes, "full"
    return ranges["header"] + sum(ranges["tasks"][task_id] for task_id in ids), "incremental"


COST_FORMULA: Dict[str, Any] = {
    "bytes_per_token": 3, "output_weight": 4, "cache": "not modelled",
    "effective": "input_est + output_weight * output_est; actual (host) replaces the estimate when recorded",
    "reads": {"writing": "spec",
              "revision": "plan per review; incremental review (**Audit scope**/**Audit tasks**): plan header + the named tasks",
              "split": "plan + parts; split_method=script: ~300 bytes per task (plan-tasks); skipped: nothing",
              "execution": "parts with a roadmap, else plan",
              "audit": "(plan + earlier reports) per report; a full pass with plan-writing's skeleton: plan × (1 − code_share); "
                       "incremental report (audit_scope/audit_tasks): plan header + the named tasks + the evidence "
                       "files changed since the previous report + the evidence files of the named tasks",
              "diffs": "none", "commit": "none"}}
_STATS_TASK_LIST_BYTES = 300  # one line of `plan-tasks` per task (id, title, files, refs)
_STATS_EVIDENCE_HEAD_RE = re.compile(r"^## (?:Evidence fingerprint|Отпечаток улик)\s*$", re.MULTILINE)


def _evidence_rows(report_text: str) -> Dict[str, str]:
    """{file: value} of the report's evidence-fingerprint table (`## Evidence fingerprint`); empty without one."""
    match = _STATS_EVIDENCE_HEAD_RE.search(report_text)
    rows: Dict[str, str] = {}
    if not match:
        return rows
    for line in report_text[match.end():].splitlines():
        if line.startswith("## "):
            break
        cells = [cell.strip().strip("`") for cell in line.strip().strip("|").split("|")]
        if len(cells) >= 2 and cells[0] and cells[0] not in ("File", "Файл") and not set(cells[0]) <= set("-: "):
            rows[cells[0].replace("\\", "/")] = cells[1]
    return rows


def _task_files(plan_text: str, ids: Optional[List[str]]) -> set:
    """Files of the `**Files:**` blocks of the tasks `ids` by parse_plan_tasks, with forward slashes; empty without
    the parser, without ids or on any parser error."""
    parser = _task_parser()
    if parser is None or not ids:
        return set()
    try:
        return {str(item["path"]).replace("\\", "/") for task in parser(plan_text)["tasks"]
                if str(task["id"]) in ids for item in task.get("files") or []}
    except Exception:  # the parser's own errors or another answer shape: no task evidence
        return set()


def _evidence_bytes(report_text: str, folder: str, previous_text: str = "", task_files: Any = ()) -> int:
    """Size of the evidence files an incremental pass reads (F11 of plan-refactoring-02): the rows of the report's
    evidence-fingerprint table whose value differs from the previous report's (a row it lacks counts), plus the rows
    of the files of the re-audited tasks (`task_files`). Paths resolve against the nearest ancestor of `folder` that
    holds `.git` (else `folder`); files that are gone count 0."""
    rows = _evidence_rows(report_text)
    if not rows:
        return 0
    before = _evidence_rows(previous_text)
    root = folder
    while not os.path.exists(os.path.join(root, ".git")) and os.path.dirname(root) != root:
        root = os.path.dirname(root)
    root = root if os.path.exists(os.path.join(root, ".git")) else folder
    total = 0
    for name, value in rows.items():
        if before.get(name) == value and name not in task_files:
            continue
        path = os.path.join(root, name)
        total += os.path.getsize(path) if os.path.isfile(path) else 0
    return total


def _skeleton_available() -> bool:
    """plan-writing's plan_tool.py alongside and with `skeleton` (spec 7 of plan-refactoring-01): the
    resolver's full passes then read the skeleton, not the plan."""
    module = _sibling("plan-writing", "plan_tool.py")
    return module is not None and hasattr(module, "_render_skeleton")


def _mode_name(modes: set) -> str:
    return "none" if not modes else modes.pop() if len(modes) == 1 else "mixed"


def _reads_model(stage: str, stats: Dict[str, Any], folder: str, plan_text: str,
                 warnings: List[str]) -> Tuple[int, str]:
    """(bytes the stage put through the model, the reads mode that applied) by COST_FORMULA["reads"]."""
    files, plan = stats["stages"][stage]["files"], stats["plan_bytes"]
    if stage == "writing":
        return (stats["spec_bytes"] if files else 0), "spec"
    if stage == "revision":
        total, modes = 0, set()
        for item in (f for f in files if "-review-" in f["name"]):
            scope, ids = _audit_scope(_text_metrics_text(os.path.join(folder, item["name"])), frontmatter=False)
            size, mode = (plan, "full") if scope == "full" else _scoped_bytes(plan_text, plan, ids, item["name"], warnings)
            total, modes = total + size, modes | {mode}
        return total, _mode_name(modes)
    if stage == "split":
        if not files:
            return 0, "skipped"
        if (stats["stages"]["split"].get("artifacts") or {}).get("split_method") == "script":
            return stats["tasks"] * _STATS_TASK_LIST_BYTES, "script"
        return plan + sum(f["bytes"] for f in files if f["name"] in stats["parts"]), "full"
    if stage == "execution":
        if not files:
            return 0, "none"
        parts = sum(f["bytes"] for f in stats["stages"]["split"]["files"] if f["name"] in stats["parts"])
        return (parts, "parts") if stats["parts"] else (plan, "plan")
    if stage == "audit":
        total, earlier, modes, skeleton, previous = 0, 0, set(), _skeleton_available(), ""
        for item in files:
            text = _text_metrics_text(os.path.join(folder, item["name"]))
            scope, ids = _audit_scope(text, frontmatter=True)
            if scope == "full":
                size, mode = (round(plan * (1 - (stats["code_share"] or 0))), "skeleton") if skeleton else (plan, "full")
            else:
                size, mode = _scoped_bytes(plan_text, plan, ids, item["name"], warnings)
                size += _evidence_bytes(text, folder, previous, _task_files(plan_text, ids)) if mode == "incremental" else 0
            total, earlier, modes, previous = total + size + earlier, earlier + item["bytes"], modes | {mode}, text
        return total, _mode_name(modes)
    return 0, "none"


def _cost_estimate(stats: Dict[str, Any], folder: str, warnings: List[str]) -> Dict[str, Any]:
    """bytes_read_est (by _reads_model) and tokens per stage by COST_FORMULA; totals over the plan.
    `actual_tokens` set by the journal layer wins and makes the stage's basis `host`."""
    plan_text = "" if stats["plan_missing"] else _text_metrics_text(os.path.join(folder, stats["plan"]))
    out: Dict[str, Any] = {"stages": {}}
    for stage, item in stats["stages"].items():
        read, mode = _reads_model(stage, stats, folder, plan_text, warnings)
        input_est = round(read / COST_FORMULA["bytes_per_token"])
        output_est = round(item["bytes_written"] / COST_FORMULA["bytes_per_token"])
        actual = item.get("actual_tokens")
        out["stages"][stage] = dict(item, bytes_read_est=read, reads_mode=mode,
                                    basis="host" if actual is not None else "estimate",
                                    tokens={"input_est": input_est, "output_est": output_est,
                                            "effective_est": input_est + COST_FORMULA["output_weight"] * output_est,
                                            "actual": actual})
    values = list(out["stages"].values())
    basis = "host" if any(s["basis"] == "host" for s in values) else "estimate"
    out["totals"] = {"bytes_read_est": sum(s["bytes_read_est"] for s in values),
                     "bytes_written": sum(s["bytes_written"] for s in values),
                     "effective_tokens_est": sum(s["tokens"]["effective_est"] for s in values),
                     "actual_tokens": sum(s["tokens"]["actual"] or 0 for s in values) if basis == "host" else None,
                     "minutes": (round(sum(s.get("minutes") or 0 for s in values), 1)
                                 if any(s.get("minutes") is not None for s in values) else None),
                     "basis": basis}
    return out


_STATS_ISSUE_RE = re.compile(r"^\d+\)\s", re.MULTILINE)
_STATS_FOUND_RE = re.compile(r"^\*\*Issues found\*\*:\s*(\d+)", re.MULTILINE)


def _quality(stats: Dict[str, Any], folder: str) -> Dict[str, Any]:
    """Quality of the run from the files (the journal layer overrides what it knows better): the last
    report's status and issue count, the reviews and the last review's open issues, unit retries and
    failed stages."""
    reports = stats["reports"]
    reviews = [f["name"] for f in stats["stages"]["revision"]["files"] if "-review-" in f["name"]]
    completion = any(f["name"].endswith("-completion.md") for f in stats["stages"]["revision"]["files"])
    last_report = _text_metrics_text(os.path.join(folder, reports[-1])) if reports else ""
    last_review = _text_metrics_text(os.path.join(folder, reviews[-1])) if reviews else ""
    found = _STATS_FOUND_RE.search(last_review)
    return {"audit_status": ("final" if reports[-1].endswith("-final.md") else "open") if reports else None,
            "audit_issues": len(_STATS_ISSUE_RE.findall(last_report)) if reports else None,
            "reviews": len(reviews),
            "review_remaining": 0 if completion else (int(found.group(1)) if found else None),
            "unit_retries": (stats.get("units") or {}).get("retries"),
            "failed_stages": list(stats.get("failed_stages") or []),
            "delegated": stats.get("delegated")}  # null without a journal (--plan), like unit_retries


_STATS_DELTA_KEYS = ("bytes_read_est", "bytes_written", "effective_tokens_est", "minutes")


def _baseline_delta(current: Dict[str, Any], baseline: Dict[str, Any], warnings: List[str]) -> Dict[str, Any]:
    """Deltas current − baseline on the totals and per stage: absolute, per task and per KB of plan.
    `minutes` only when both sides have it (a --plan baseline has none). A stage whose basis differs
    between the two (host vs estimate) gets `basis-mixed: <stage>`: the numbers are not directly comparable."""
    if not isinstance(baseline, dict) or "formula" not in baseline or "totals" not in baseline:
        raise InputError("baseline-mismatch: not a run-stats result (formula and totals expected)")
    if current.get("goal") and baseline.get("goal") and current["goal"] != baseline["goal"]:
        raise InputError(f"baseline-mismatch: goal {baseline['goal']!r} differs from {current['goal']!r}")

    def one(now: Dict[str, Any], then: Dict[str, Any]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for key in _STATS_DELTA_KEYS:
            a, b = now.get(key), then.get(key)
            if a is None or b is None:
                out[key] = None
                continue
            per_task = a / max(current["totals"]["tasks"], 1) - b / max(baseline["totals"]["tasks"], 1)
            per_kb = a / max(current["totals"]["plan_bytes"] / 1024, 1e-9) - b / max(baseline["totals"]["plan_bytes"] / 1024, 1e-9)
            out[key] = {"abs": round(a - b, 2), "per_task": round(per_task, 2), "per_kb": round(per_kb, 2)}
        return out

    then_stages = baseline["totals"].get("stages", {})
    stages: Dict[str, Any] = {}
    for stage, now in current["totals"].get("stages", {}).items():
        then = then_stages.get(stage, {})
        if now.get("basis") and then.get("basis") and now["basis"] != then["basis"]:
            warnings.append(f"basis-mixed: {stage}")
        stages[stage] = one(now, then)
    return {"stages": stages, "totals": one(current["totals"], baseline["totals"])}


def _eta(data: Dict[str, Any], states: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Remaining stages of every plan and their estimate: the stage's average duration in this journal
    (basis history); execution with a known unit count: seconds per unit × units left (basis units)."""
    durations: Dict[str, List[float]] = {}
    for stage, span in _spans(data, "stage-start", "stage-end", lambda event: event.get("stage")):
        durations.setdefault(stage, []).append(span)
    per_stage = {stage: sum(values) / len(values) for stage, values in durations.items()}
    units = [span for _, span in _spans(data, "unit-begin", "unit-finish",
                                        lambda event: (event.get("data") or {}).get("unit"))]
    per_unit = sum(units) / len(units) if units else None
    seconds, bases, remaining = 0.0, set(), []
    for state in states:
        for stage in _brainstorm().STAGES:
            record = _record(state, stage)
            if record.get("status", "pending") in ("done", "skipped"):
                continue
            remaining.append({"plan": state["entry"]["plan"], "stage": stage})
            artifacts = record.get("artifacts") or {}
            total, done = _int_or_none(artifacts.get("units_total")), _int_or_none(artifacts.get("units_done"))
            if stage == "execution" and per_unit is not None and total is not None and done is not None:
                seconds += per_unit * max(total - done, 0)
                bases.add("units")
            elif stage in per_stage:
                seconds += per_stage[stage]
                bases.add("history")
    if not bases:
        return {"ok": True, "eta_minutes": None, "basis": "none", "remaining": remaining}
    return {"ok": True, "eta_minutes": int(-(-seconds // 60)),
            "basis": "history" if "history" in bases else "units", "remaining": remaining}


def run_eta(journal: str) -> Dict[str, Any]:
    data, runner = _runner_journal(journal)
    return _eta(data, _plan_states(journal, data, runner))


def _session_state(journal: str) -> Optional[Dict[str, Any]]:
    """Active-session mark of the journal (run-session, outside the working copy): its age and whether
    it is younger than SESSION_STALE_SECONDS; None without a readable mark."""
    mark = _read_session(_session_file(journal))
    age = _session_age(mark) if mark is not None else None
    if age is None:
        return None
    return {"active": age < SESSION_STALE_SECONDS, "age_seconds": age}


def _roadmap_state(journal: str, data: Dict[str, Any], runner: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The run's goal roadmap (runner.roadmap) as it is on disk now: `path`, `sha_matches` (its sha256 is
    runner.roadmap_sha256), `missing` (no readable file), `not_in_roadmap` (journal specs it does not name)
    and `rows` {spec: (#, group)}; None without runner.roadmap. Reads only (spec 10 of plan-refactoring-01)."""
    name = runner.get("roadmap")
    if not name:
        return None
    bt = _brainstorm()
    path = os.path.join(os.path.dirname(os.path.abspath(journal)), name)
    try:
        text, digest = bt._read_source(path), bt._sha256(path)
    except (bt.InputError, OSError):
        return {"path": name, "sha_matches": False, "missing": True, "not_in_roadmap": [], "rows": {}}
    rows = {row["file"]: (row["n"], row["group"]) for row in bt.parse_goal_roadmap(text)[0]["specs"]}
    registered = [entry.get("path") for entry in data["specs"] if isinstance(entry, dict)]
    return {"path": name, "sha_matches": digest == runner.get("roadmap_sha256"), "missing": False,
            "not_in_roadmap": [spec for spec in registered if spec not in rows], "rows": rows}


def run_status(journal: str) -> Dict[str, Any]:
    """Per plan: stage statuses, the next stage (rules 7 and 9), unit progress; open questions, waits
    without a question of their own (stage-failed: stop, not-confirmed: stop, model: stop, code-busy, reading-busy, host-wait, plan-oversized),
    ETA, the session mark, the cost totals, the goal roadmap's state and the plans' # order. Reads only."""
    bt = _brainstorm()
    data, runner = _runner_journal(journal)
    states = _plan_states(journal, data, runner)
    plans: List[Dict[str, Any]] = []
    for state in states:
        entry, step = state["entry"], _next_stage(state)
        artifacts = _record(state, "execution").get("artifacts") or {}
        total, done = _int_or_none(artifacts.get("units_total")), _int_or_none(artifacts.get("units_done"))
        progress = ({"done": done, "total": total} if total is not None and done is not None
                    else bt._journal_progress(data, entry["id"]))
        plans.append({"spec": state["spec"], "plan": entry["plan"],
                      "stages": {stage: _record(state, stage).get("status", "pending") for stage in bt.STAGES},
                      "current": step[0] if step else None, "progress": progress})
    questions = [{key: q.get(key) for key in ("id", "plan", "stage", "text", "options")}
                 for q in data["questions"] if q.get("status") == "open"]
    for state in states:
        state["next"] = _next_stage(state)
    waiting: List[Dict[str, Any]] = []
    _candidates(data, runner, states, waiting, {})
    waits = [item for item in waiting
             if item["reason"] in ("stage-failed: stop", "not-confirmed: stop", "model: stop")
             or item["reason"].startswith(("code-busy: ", "reading-busy: ", "host-wait: ", "plan-oversized: "))]
    totals = run_stats(journal, None)["totals"]
    roadmap = _roadmap_state(journal, data, runner)
    rows = roadmap.pop("rows") if roadmap is not None else {}
    if roadmap is None or not roadmap["sha_matches"]:  # # and groups only of the file run-init read
        rows = {}
    order = []
    for index, state in enumerate(states):
        n, group = rows.get(state["spec"], (index + 1, None))
        order.append({"plan": state["entry"]["plan"], "n": n, "group": group})
    return {"ok": True, "goal": data.get("goal"), "profile": runner.get("profile"), "plans": plans,
            "open_questions": questions, "waits": waits, "eta_minutes": _eta(data, states)["eta_minutes"],
            "session": _session_state(journal),
            "cost": {"effective_tokens_est": totals["effective_tokens_est"], "bytes_total": totals["bytes_written"],
                     "basis": totals["basis"]},
            "roadmap": roadmap, "order": order}


def subset_check(journal: str, roadmap: str, specs: Optional[List[str]] = None) -> Dict[str, Any]:
    """The run the goal roadmap allows for `specs` (relative to CWD; none = every spec of the roadmap), for
    the start card and roadmap-changed (spec 10 of plan-refactoring-01): `specs` in the roadmap's # order;
    `not_in_roadmap`, the specs of the call or the journal it does not name; `missing_dependencies`, the
    roadmap dependencies outside the set whose commit is not done or skipped; `graph`, the roadmap edges
    inside the set (run-init accepts no other); `dropped_uncommitted`, the journal's specs outside the set
    whose execution started and is not committed. Reads only; the journal needs no runner section."""
    bt = _brainstorm()
    journal = os.path.abspath(journal)
    try:
        data = bt.journal_load(journal)
    except bt.InputError as exc:
        raise InputError(str(exc)) from exc
    errors = bt._journal_structure_errors(data) or _time_errors(data)
    if errors:
        raise InputError(f"journal-corrupt: {journal}: " + "; ".join(errors))
    name, _, parsed = _goal_roadmap(journal, roadmap, data.get("goal"))
    rows = [row["file"] for row in parsed["specs"]]
    depends = {row["file"]: row["depends"] for row in parsed["specs"]}
    given = list(dict.fromkeys(bt._journal_rel(journal, spec) for spec in specs)) if specs else rows
    chosen = [spec for spec in rows if spec in given]
    registered = [entry.get("path") for entry in data["specs"] if isinstance(entry, dict)]

    def state(spec: str) -> Dict[str, Any]:  # what _record and _uncommitted read
        return {"entry": {"stages": (_journal_entry(data, spec) or {}).get("stages") or {}}}

    committed = {spec for spec in rows if _record(state(spec), "commit").get("status") in ("done", "skipped")}
    return {"ok": True, "journal": journal, "roadmap": name, "specs": chosen,
            "not_in_roadmap": [spec for spec in dict.fromkeys(given + registered) if spec not in rows],
            "missing_dependencies": list(dict.fromkeys(dep for spec in chosen for dep in depends[spec]
                                                       if dep not in chosen and dep not in committed)),
            "graph": {spec: [dep for dep in depends[spec] if dep in chosen] for spec in chosen},
            "dropped_uncommitted": [spec for spec in registered if spec not in chosen and _uncommitted(state(spec))]}


def cmd_subset_check(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    return 0, subset_check(args.journal, args.roadmap, args.spec)


def _plan_stats(plan_path: str, journal_layer: Optional[Dict[str, Any]], warnings: List[str]) -> Dict[str, Any]:
    """One plan of run-stats: the artifact layer, the journal layer on top (status, minutes, model,
    artifacts, actual cost; its units/audit/failed stages), then the cost estimate and the quality block."""
    stats = _artifact_stats(plan_path, warnings)
    folder = os.path.dirname(os.path.abspath(plan_path))
    if stats["plan_missing"]:
        warnings.append(f"plan-missing: {plan_path}")
    warnings.extend(f"not-utf8: {f['name']}" for item in stats["stages"].values() for f in item["files"] if f["lines"] is None)
    if journal_layer:
        for stage, item in journal_layer["stages"].items():
            stats["stages"].setdefault(stage, {"status": "pending", "files": [], "bytes_written": 0}).update(item)
        stats.update(units=journal_layer["units"], failed_stages=journal_layer["failed_stages"],
                     delegated=journal_layer["delegated"])
    else:  # --plan: no journal, so no durations; every stage still carries the key
        for item in stats["stages"].values():
            item.setdefault("minutes", None)
            item.setdefault("host_waits", None)
            item.setdefault("host_waited_seconds", None)
    estimate = _cost_estimate(stats, folder, warnings)
    quality = _quality(stats, folder)
    if journal_layer and journal_layer["audit"]["status"]:
        quality.update(audit_status=journal_layer["audit"]["status"], audit_issues=journal_layer["audit"]["issues"])
    totals = dict(estimate["totals"], tasks=stats["tasks"], plan_bytes=stats["plan_bytes"])
    return {"plan": stats["plan"], "plan_missing": stats["plan_missing"], "tasks": stats["tasks"],
            "plan_bytes": stats["plan_bytes"], "code_share": stats["code_share"], "spec": stats["spec"],
            "stages": estimate["stages"], "quality": quality, "totals": totals, "delta": None}


def _stats_totals(plans: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Totals of run-stats over `plans`: per stage the summed bytes, effective tokens, host tokens and minutes with
    their basis (`mixed` when the plans differ), then the sums over the stages. `actual_tokens` (spec 1 of
    plan-refactoring-04) sums the host's counts that exist: a stage's `tokens.actual`, a plan's `totals.actual_tokens`;
    null when none of them has one."""
    stages: Dict[str, Dict[str, Any]] = {}
    for item in plans:
        for stage, record in item["stages"].items():
            agg = stages.setdefault(stage, {"bytes_read_est": 0, "bytes_written": 0, "effective_tokens_est": 0,
                                            "actual_tokens": None, "minutes": None, "bases": set()})
            agg["bytes_read_est"] += record["bytes_read_est"]
            agg["bytes_written"] += record["bytes_written"]
            agg["effective_tokens_est"] += record["tokens"]["effective_est"]
            agg["bases"].add(record["basis"])
            if record["tokens"].get("actual") is not None:
                agg["actual_tokens"] = (agg["actual_tokens"] or 0) + record["tokens"]["actual"]
            if record.get("minutes") is not None:
                agg["minutes"] = round((agg["minutes"] or 0) + record["minutes"], 1)
    for agg in stages.values():
        bases = agg.pop("bases")
        agg["basis"] = bases.pop() if len(bases) == 1 else "mixed" if bases else "estimate"
    actual = [p["totals"]["actual_tokens"] for p in plans if p["totals"].get("actual_tokens") is not None]
    return {"tasks": sum(p["tasks"] for p in plans), "plan_bytes": sum(p["plan_bytes"] for p in plans),
            "bytes_read_est": sum(s["bytes_read_est"] for s in stages.values()),
            "bytes_written": sum(s["bytes_written"] for s in stages.values()),
            "effective_tokens_est": sum(s["effective_tokens_est"] for s in stages.values()),
            "actual_tokens": sum(actual) if actual else None,
            "minutes": (round(sum(s["minutes"] for s in stages.values() if s["minutes"] is not None), 1)
                        if any(s["minutes"] is not None for s in stages.values()) else None),
            "basis": "host" if any(p["totals"]["basis"] == "host" for p in plans) else "estimate",
            "stages": stages}


def run_stats(journal: Optional[str], plan: Optional[str], baseline: Optional[str] = None) -> Dict[str, Any]:
    """Sizes, durations, token estimate or recorded cost, and quality per stage of a run: from the journal or from
    one plan's folder (--plan); --baseline adds deltas. With a journal every plan of the journal is a row (F1 of
    plan-refactoring-02): the run's plans (runner.specs) first, then the plans of earlier runs with `outside_run:
    true`; `totals` sums the run's plans, `journal_totals` all of them (null with --plan). Reads only."""
    if bool(journal) == bool(plan):
        raise InputError("bad-arguments: give a journal or --plan <plan.md>, not both")
    warnings: List[str] = []
    out: Dict[str, Any] = {"ok": True, "mode": "journal" if journal else "plan", "formula": COST_FORMULA}
    if journal:
        data, runner = _runner_journal(journal)
        out["goal"] = data.get("goal")
        folder = os.path.dirname(os.path.abspath(journal))
        states = _plan_states(journal, data, runner)
        run_ids = {state["entry"]["id"] for state in states}
        # _plan_states stays the run's own (run-next, run-checklist); the journal's other plans are added here.
        outside = [{"spec": entry.get("spec"), "entry": entry} for entry in data["plans"] if entry.get("id") not in run_ids]
        plans = [dict(_plan_stats(os.path.join(folder, state["entry"].get("plan") or _derived_plan(state["spec"])),
                                  _journal_stats(data, runner, state), warnings), outside_run=outside_run)
                 for state, outside_run in [(state, False) for state in states] + [(state, True) for state in outside]]
    else:
        if not os.path.isfile(plan):
            raise InputError(f"plan-not-found: {plan}")
        plans = [dict(_plan_stats(plan, None, warnings), outside_run=False)]
    out["plans"], out["warnings"] = plans, warnings
    out["totals"] = _stats_totals([item for item in plans if not item["outside_run"]])
    out["journal_totals"] = _stats_totals(plans) if journal else None
    if baseline:
        try:
            with open(baseline, "r", encoding="utf-8") as fh:
                previous = json.load(fh)
        except (OSError, ValueError) as exc:
            raise InputError(f"baseline-mismatch: cannot read {baseline}: {exc}") from exc
        out["delta"] = _baseline_delta(out, previous, warnings)
    else:
        out["delta"] = None
    return out


# run-checklist (spec 2 of plan-refactoring-02): what is left to do by hand after a run, as lines of the goal's
# BACKLOG.md section, written only through brainstorm_tool.backlog_append; a line already open is not repeated.
CHECKLIST_TEXT = {
    "ru": {"skills": "обновить установленные копии скиллов после коммитов прогона: {skills}",
           "prune": "удалить снимки закоммиченного плана {plan}: executor_tool.py checkpoint-prune {exec_dir}",
           "unverified": "повторить контрольную проверку плана {plan} там, где есть инструмент субагента: юниты "
                         "{units} шли в основном агенте (subagent-unavailable)",
           "amend": "amend спеки {spec}: {count} отклонений плана {plan}, строки «поправить спеку» этого раздела"},
    "en": {"skills": "update the installed copies of the skills after the run's commits: {skills}",
           "prune": "remove the snapshots of the committed plan {plan}: executor_tool.py checkpoint-prune {exec_dir}",
           "unverified": "repeat the control check of plan {plan} where a subagent tool exists: units {units} ran "
                         "in the main agent (subagent-unavailable)",
           "amend": "amend the spec {spec}: {count} deviation(s) of plan {plan}, the amend spec lines of this section"},
}
SUBAGENT_UNAVAILABLE = "subagent-unavailable"  # executor_tool.SUBAGENT_UNAVAILABLE


def _ledger_units(exec_dir: str) -> List[Dict[str, Any]]:
    """The units of <exec_dir>/state.json; [] when the ledger cannot be read."""
    try:
        with open(os.path.join(exec_dir, "state.json"), "r", encoding="utf-8") as fh:
            units = json.load(fh).get("units")
    except (OSError, ValueError, AttributeError):
        return []
    return [unit for unit in units if isinstance(unit, dict)] if isinstance(units, list) else []


def _checklist_items(journal: str, data: Dict[str, Any], runner: Dict[str, Any], lang: str,
                     warnings: List[str]) -> List[str]:
    """The checklist of the plans of runner.specs: installed skills after commits under skills/, checkpoint-prune
    of each committed plan, units with the note subagent-unavailable, specs whose plans deviate
    (executor_tool.plan_deviations; left out with `executor-not-installed` without plan-executor)."""
    text = CHECKLIST_TEXT[lang]
    folder = os.path.dirname(os.path.abspath(journal))
    executor = _executor()
    if executor is None:
        warnings.append("executor-not-installed")
    skills, items = set(), []
    for state in _plan_states(journal, data, runner):
        plan_id = state["entry"]["id"]
        commit = _record(state, "commit")
        for record in (commit.get("artifacts") or {}).get("commits") or []:
            for path in (record.get("files") or []) if isinstance(record, dict) else []:
                parts = str(path).replace("\\", "/").split("/")
                if len(parts) > 2 and parts[0] == "skills":
                    skills.add(parts[1])
        exec_dir = (_record(state, "execution").get("artifacts") or {}).get("exec_dir")
        units = _ledger_units(os.path.join(folder, exec_dir)) if isinstance(exec_dir, str) and exec_dir else []
        if commit.get("status") == "done" and units:
            items.append(text["prune"].format(plan=plan_id, exec_dir=os.path.normpath(os.path.join(folder, exec_dir))))
        unverified = [str(unit.get("id")) for unit in units if SUBAGENT_UNAVAILABLE in (unit.get("notes") or [])]
        if unverified:
            items.append(text["unverified"].format(plan=plan_id, units=", ".join(unverified)))
        if executor is not None:
            plan = os.path.join(folder, state["entry"].get("plan") or _derived_plan(state["spec"]))
            count = len(executor.plan_deviations(_text_metrics_text(plan), units))
            if count:
                items.append(text["amend"].format(spec=state["spec"], plan=plan_id, count=count))
    if skills:
        items.insert(0, text["skills"].format(skills=", ".join(sorted(skills))))
    return items


def _repo_root(start: str) -> str:
    """backlog-append's root: the nearest folder from `start` up that holds `.git` (a folder, or the file of a
    worktree); the working directory outside git."""
    current = os.path.abspath(start)
    while not os.path.exists(os.path.join(current, ".git")):
        parent = os.path.dirname(current)
        if parent == current:
            return os.getcwd()
        current = parent
    return current


def run_checklist(journal: str, backlog_root: Optional[str] = None) -> Dict[str, Any]:
    """The checklist after a run (_checklist_items) appended to the goal's section of <root>/BACKLOG.md; `exists`
    for a line already there, open or not. Without plan-brainstorming nothing is written (`backlog-unavailable`);
    the backlog is never a gate, so a failed write is a warning."""
    journal = os.path.abspath(journal)
    result: Dict[str, Any] = {"ok": True, "journal": journal, "section": None, "backlog": None, "items": [],
                              "appended": [], "exists": [], "warnings": []}
    try:
        bt = _brainstorm()
    except InputError as exc:
        result["warnings"].append(f"backlog-unavailable: {exc}")
        return result
    data, runner = _runner_journal(journal)
    lang = data.get("lang") if data.get("lang") in CHECKLIST_TEXT else "en"
    root = backlog_root or _repo_root(os.path.dirname(journal))
    section = data["goal"]
    items = _checklist_items(journal, data, runner, lang, result["warnings"])
    path = os.path.join(root, bt.BACKLOG_FILE)
    result.update(section=section, backlog=path, items=items)
    try:
        known = {item["text"] for item in bt.backlog_parse(path, section)["items"]} if os.path.isfile(path) else set()
    except Exception as exc:  # e.g. BACKLOG.md not in UTF-8: backlog_append reports it per item
        known = set()
        result["warnings"].append(f"backlog-write-failed: {exc}")
    for item in items:
        if item in known:
            result["exists"].append(item)
            continue
        try:
            outcome = bt.backlog_append(root, section, "plan-chain-runner, " + os.path.basename(journal), item, lang=lang)
        except (bt.BacklogError, bt.InputError) as exc:
            result["warnings"].append(f"backlog-write-failed: {exc}")
            continue
        result["exists" if outcome["action"] == "exists" else "appended"].append(item)
    result["warnings"] = list(dict.fromkeys(result["warnings"]))
    return result


def cmd_run_checklist(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    return 0, run_checklist(args.journal, args.backlog_root)


def cmd_run_stats(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    result = run_stats(args.journal, args.plan, args.baseline)
    if args.json_out:
        try:
            with open(args.json_out, "w", encoding="utf-8") as fh:
                json.dump(result, fh, ensure_ascii=False, indent=2)
        except OSError as exc:  # the computed result is still printed, next to the error (exit 2)
            return 2, dict(result, ok=False, errors=[f"write-failed: {args.json_out}: {exc}"])
    return 0, result


def cmd_run_eta(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    return 0, run_eta(args.journal)


def cmd_run_status(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    return 0, run_status(args.journal)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command")

    p_load = sub.add_parser("settings-load", help="models and effort per role of a host profile")
    p_load.add_argument("--file", help="settings file, default $PLANFORGE_HOME/runner.json or ~/.planforge/runner.json")
    p_load.add_argument("--profile", required=True, help=", ".join(PROFILES))
    p_load.set_defaults(func=cmd_settings_load)

    p_save = sub.add_parser("settings-save", help="write the confirmed roles of a profile into the settings file")
    p_save.add_argument("--profile", required=True, help=", ".join(PROFILES))
    p_save.add_argument("--roles", required=True, help='JSON {role: {"model", "effort", "fallback"?}}')
    p_save.add_argument("--file", help="settings file, default $PLANFORGE_HOME/runner.json or ~/.planforge/runner.json")
    p_save.set_defaults(func=cmd_settings_save)

    p_pick = sub.add_parser("model-pick", help="model and effort of one role; --unsupported falls back")
    p_pick.add_argument("--profile", help=", ".join(PROFILES) + " (required without --journal)")
    p_pick.add_argument("--journal", help="chain journal: the role's model, effort and fallback from runner.models")
    p_pick.add_argument("--role", required=True, help=", ".join(ROLES))
    p_pick.add_argument("--file", help="settings file, default $PLANFORGE_HOME/runner.json or ~/.planforge/runner.json")
    p_pick.add_argument("--unsupported", action="append", default=[], help="a model the host refused (repeatable)")
    p_pick.add_argument("--light", action="store_true",
                        help="the light model of the execution role (delegated green units) instead of its model")
    p_pick.set_defaults(func=cmd_model_pick)

    p_init = sub.add_parser("run-init", help="write the runner section of the chain journal")
    p_init.add_argument("journal", help="path to <goal>-chain.json")
    p_init.add_argument("--profile", required=True, help=", ".join(PROFILES))
    p_init.add_argument("--spec", action="append", required=True, help="spec of the run, relative to CWD (repeatable)")
    p_init.add_argument("--graph", required=True, help='JSON {spec: [spec it depends on, ...]}, paths as in --spec')
    p_init.add_argument("--models", required=True, help='JSON {role: {"model", "effort"}} (settings-load roles)')
    p_init.add_argument("--start-commit", help="sha of the start commit, declined or none")
    p_init.add_argument("--parallel", type=int, help="most agents at once for this run (read by run-next first)")
    p_init.add_argument("--roadmap", help="the goal roadmap <goal>-roadmap.md, relative to CWD: the specs in its # order, "
                                          "runner.roadmap and runner.roadmap_sha256")
    p_init.set_defaults(func=cmd_run_init)

    p_subset = sub.add_parser("subset-check", help="the run a goal roadmap allows for some of its specs: order, "
                                                   "missing dependencies, graph, dropped uncommitted plans")
    p_subset.add_argument("journal", help="path to <goal>-chain.json")
    p_subset.add_argument("--roadmap", required=True, help="the goal roadmap <goal>-roadmap.md, relative to CWD")
    p_subset.add_argument("--spec", action="append", default=[],
                          help="a spec of the run, relative to CWD (repeatable; none = every spec of the roadmap)")
    p_subset.set_defaults(func=cmd_subset_check)

    p_session = sub.add_parser("run-session", help="session mark outside the working copy and the journal's session history")
    p_session.add_argument("journal", help="path to <goal>-chain.json")
    mode = p_session.add_mutually_exclusive_group(required=True)
    mode.add_argument("--begin", action="store_true", help="start a session; a mark younger than 30 minutes is session-active")
    mode.add_argument("--heartbeat", action="store_true", help="refresh the mark only; the journal is not touched")
    mode.add_argument("--end", choices=SESSION_ENDS, help="close the session in the journal and remove the mark")
    p_session.add_argument("--host", help="host of the session, default the runner profile")
    p_session.add_argument("--takeover", action="store_true", help="begin even when a fresh mark exists")
    p_session.add_argument("--id", help="this session's id from --begin (required by --heartbeat and --end)")
    p_session.set_defaults(func=cmd_run_session)
    p_run_next = sub.add_parser("run-next", help="what to launch now: actions, waiting plans, done, blocked")
    p_run_next.add_argument("journal", help="path to <goal>-chain.json with a runner section")
    p_run_next.add_argument("--parallel", type=int,
                            help="most runs at once (default: runner.parallel, else parallel of the profile)")
    p_run_next.add_argument("--in-flight", action="append", default=[], metavar="PLAN_ID:STAGE",
                            help="an agent launched and not yet returned (repeatable): not returned again, counted")
    p_run_next.set_defaults(func=cmd_run_next)
    p_host = sub.add_parser("host-wait", help="a host error of an agent call: the next pause, or the stage failed "
                                              "after an hour of pauses")
    p_host.add_argument("journal", help="path to <goal>-chain.json with a runner section")
    p_host.add_argument("--plan", required=True, help="plan id or plan path")
    p_host.add_argument("--stage", required=True, help="the stage of the agent call")
    p_host.add_argument("--error", required=True, help="the error text of the launch tool, never the agent's reply")
    p_host.set_defaults(func=cmd_host_wait)
    p_resume = sub.add_parser("writing-resume", help="record the plan file before a cut-off writer is relaunched")
    p_resume.add_argument("journal", help="path to <goal>-chain.json with a runner section")
    p_resume.add_argument("--plan", required=True, help="plan id or plan path")
    p_resume.set_defaults(func=cmd_writing_resume)
    p_run_eta = sub.add_parser("run-eta", help="minutes left from the stage and unit history of the journal")
    p_run_eta.add_argument("journal", help="path to <goal>-chain.json with a runner section")
    p_run_eta.set_defaults(func=cmd_run_eta)
    p_run_status = sub.add_parser("run-status", help="stages, progress, open questions, ETA and session of a run")
    p_run_status.add_argument("journal", help="path to <goal>-chain.json with a runner section")
    p_run_status.set_defaults(func=cmd_run_status)
    p_run_stats = sub.add_parser("run-stats", help="sizes, durations, token cost (host fact or estimate) and quality per stage; --baseline adds deltas")
    p_run_stats.add_argument("journal", nargs="?", help="path to <goal>-chain.json with a runner section")
    p_run_stats.add_argument("--plan", help="a plan file instead of a journal: artifacts next to it, no durations")
    p_run_stats.add_argument("--baseline", help="an earlier run-stats JSON to compare with")
    p_run_stats.add_argument("--json-out", help="also write the JSON to this file (the only write of the command)")
    p_run_stats.set_defaults(func=cmd_run_stats)
    p_checklist = sub.add_parser("run-checklist", help="the checklist after a run as lines of the goal's BACKLOG.md section")
    p_checklist.add_argument("journal", help="path to <goal>-chain.json with a runner section")
    p_checklist.add_argument("--backlog-root", help="folder of BACKLOG.md (default: the git top-level of the journal's "
                                                    "folder, else the working directory)")
    p_checklist.set_defaults(func=cmd_run_checklist)
    return parser


JOURNAL_READERS = ("run-next", "run-eta", "run-status", "run-stats", "subset-check", "run-checklist")


def main(argv: Optional[List[str]] = None) -> int:
    for stream in (sys.stdin, sys.stdout):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help(sys.stderr)
        return 2
    try:
        code, result = args.func(args)
    except InputError as exc:
        code, result = 2, {"ok": False, "errors": [str(exc)]}
    except ChainError as exc:
        code, result = 1, {"ok": False, "errors": [str(exc)], **exc.details}
    except (KeyError, TypeError, AttributeError) as exc:
        # The journal readers check the structure and the time fields first (journal-corrupt, exit 2):
        # what still fails in them is a bug of the scheduler, not a journal to rebuild. Elsewhere: raised.
        if getattr(args, "command", None) not in JOURNAL_READERS:
            raise
        code, result = 1, {"ok": False, "errors": [f"scheduler-bug: {type(exc).__name__}: {exc}"]}
    except Exception as exc:  # journal-locked, journal-missing, journal-corrupt keep their exit codes
        code = _brainstorm_exit(exc)
        if code is None:
            raise
        result = {"ok": False, "errors": [str(exc)]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
