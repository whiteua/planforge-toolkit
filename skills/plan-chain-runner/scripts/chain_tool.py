#!/usr/bin/env python3
"""Deterministic helper of the plan-chain-runner skill.

The chain journal is read and written only through ../plan-brainstorming/scripts/brainstorm_tool.py
(loaded by path). Settings and session marks live in PLANFORGE_HOME (default ~/.planforge),
outside any working copy. Stdlib only, Python 3.8+.

Commands:
  settings-load  [--file F] --profile P
  settings-save  --profile P --roles JSON [--file F]
  model-pick     (--profile P [--file F] | --journal J [--profile P]) --role R [--unsupported MODEL]...
  run-init       <journal> --profile P --spec S... --graph JSON --models JSON [--start-commit SHA|declined|none] [--parallel N]
  run-session    <journal> (--begin [--host H] [--takeover] | --heartbeat --id ID | --end stopped|complete|interrupted --id ID)
  run-next       <journal> [--parallel N] [--in-flight PLAN_ID:STAGE]...
  run-eta        <journal>
  run-status     <journal>

Exit codes: 0 ok, 1 contract (graph-cycle, session-active, session-stale-running, session-taken-over,
runner-missing, no-model) or scheduler-bug (run-next, run-eta, run-status), 2 usage or I/O error
(journal-corrupt included).
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
        "split": {"model": "opus", "effort": "medium"}, "execution": {"model": "opus", "effort": "medium"},
        "audit": {"model": "fable", "effort": "high"}, "commit": {"model": "sonnet", "effort": "low"}}},
    "github-copilot": {"parallel": 3, "roles": {
        role: {"model": model, "effort": None, "fallback": _MINI}
        for role, model in (("writing", _OPUS), ("revision", _OPUS), ("split", _SONNET),
                            ("execution", _SONNET), ("audit", _OPUS), ("commit", _MINI))}},
    "fallback": {"parallel": 1, "roles": {role: {"model": None, "effort": None} for role in ROLES}},
}
ROLE_KEYS = ("model", "effort", "fallback")
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
    return {"ok": not errors, "source": "file" if body is not None or errors else "builtin", "profile": profile,
            "parallel": (body or {}).get("parallel", builtin["parallel"]), "roles": roles,
            "pinned": _pinned(roles), "errors": errors}


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


def pick_model(settings: Dict[str, Any], role: str, unsupported: List[str]) -> Dict[str, Any]:
    """The role's model; a refused (`unsupported`) model gives way to its fallback, else no-model.
    A null model (fallback profile, inherited model) is returned as null."""
    if role not in ROLES:
        raise InputError(f"unknown-role: {role}")
    entry = settings["roles"][role]
    model, fallback = entry["model"], entry.get("fallback")
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
        return 0, pick_model({"roles": roles}, args.role, args.unsupported)
    if not args.profile:
        raise InputError("--profile is required without --journal")
    settings = load_settings(_settings_path(args.file), args.profile)
    if not settings["ok"]:
        return 2, {"ok": False, "errors": settings["errors"]}
    return 0, pick_model(settings, args.role, args.unsupported)


START_COMMIT_RE = re.compile(r"^[0-9a-f]{7,64}$")


def _runner_models(models: Any) -> Dict[str, Dict[str, Any]]:
    """`--models` (settings-load roles) as {role: {"model", "effort", "fallback"?}}: the fallback stays
    for model-pick --journal."""
    errors = _roles_errors("--models", models)
    if errors:
        raise InputError("; ".join(errors))
    runner_models: Dict[str, Dict[str, Any]] = {}
    for role, entry in models.items():
        runner_models[role] = {"model": entry.get("model"), "effort": entry.get("effort")}
        if entry.get("fallback"):
            runner_models[role]["fallback"] = entry["fallback"]
    return runner_models


def run_init(journal: str, profile: str, specs: List[str], graph: Any, models: Any,
             start_commit: Optional[str] = None, parallel: Optional[int] = None) -> Dict[str, Any]:
    """Write the journal's `runner` section. Spec paths are taken relative to CWD and stored relative
    to the journal; every one must be registered in journal.specs. Sessions of an earlier run-init stay;
    without --start-commit (--parallel) the earlier value stays, else the key is left out."""
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
        runner = {"version": bt.RUNNER_VERSION, "profile": profile, "specs": rels, "graph": rel_graph,
                  "models": runner_models,
                  "sessions": old.get("sessions") if isinstance(old.get("sessions"), list) else []}
        kept = start_commit or old.get("start_commit")
        if kept:
            runner["start_commit"] = kept
        width = parallel if parallel is not None else old.get("parallel")
        if width is not None:
            runner["parallel"] = width
        errors = bt._runner_errors(runner)
        if errors:
            raise InputError("runner-invalid: " + "; ".join(errors))
        data["runner"] = runner
        return runner

    return {"ok": True, "journal": journal, "runner": bt.journal_update(journal, mutate)}


def cmd_run_init(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    return 0, run_init(args.journal, args.profile, args.spec, _json_arg(args.graph, "--graph"),
                       _json_arg(args.models, "--models"), args.start_commit, args.parallel)


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


def _claim_mark(path: str, mark: Dict[str, Any]) -> bool:
    """Create the session mark with O_CREAT | O_EXCL; False when another process created it first."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return False
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
        try:
            won = _claim_mark(path, {"id": session_id, "host": host or runner.get("profile"), "journal": journal,
                                     "heartbeat_at": now})
        except OSError:  # the file may be left half written: the rollback removes it and puts the displaced mark back
            claimed.append(path)
            raise
        if not won:
            displaced.clear()  # another --begin created its mark first: it stays, there is nothing to put back
            raise ChainError(f"session-active: {journal}", id=None, host=None, age_seconds=None)
        claimed.append(path)
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


def _plan_states(journal: str, data: Dict[str, Any], runner: Dict[str, Any]) -> List[Dict[str, Any]]:
    """One record per runner spec, in runner order: its plan entry (a pending one before plan-writing),
    the chain settings (of the plan when it exists, else of the spec), the plan's questions and the
    ids of the open ones."""
    bt = _brainstorm()
    directory = os.path.dirname(os.path.abspath(journal))
    states: List[Dict[str, Any]] = []
    for spec in runner.get("specs") or []:
        plan = _derived_plan(spec)
        entry = next((item for item in data["plans"] if item.get("spec") == spec), None)
        if entry is None:  # an entry created without --spec (journal-question before plan-writing)
            entry = next((item for item in data["plans"]
                          if not item.get("spec") and item.get("id") == bt._journal_plan_id(plan)), None)
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


QUESTION_OPTIONS = {"open-audit": ["accept", "fix"], "stage-failed": ["retry", "stop"]}


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


def _stage_step(data: Dict[str, Any], state: Dict[str, Any], stage: str, reason: Optional[str]) -> Dict[str, Any]:
    """The step for the plan's next stage (open questions are checked before): a run, a skip
    (split=never, resolver=skip), an ask (rule 10: stage-failed) or {"kind": "wait", "why"}.
    A running audit started by an open-audit `fix` resumes as `fix`."""
    record = _record(state, stage)
    status = record.get("status", "pending")
    where = {"spec": state["spec"], "plan": state["entry"]["plan"], "stage": stage}
    if status == "pending" and stage == "split" and state["chain"].get("split") == "never":
        return dict(where, kind="skip", why="split=never")
    if status == "pending" and stage == "audit" and state["chain"].get("resolver") == "skip":
        return dict(where, kind="skip", why="resolver=skip")
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
        if not current and _failures(data, state["entry"]["id"], stage) >= 2:
            return dict(where, kind="ask", prefix=f"stage-failed: {stage}",
                        options=list(QUESTION_OPTIONS["stage-failed"]))
    if stage == "audit" and status == "running" and reason is None:  # an interrupted fix resumes as a fix
        starts = [event for event in data["events"] if event.get("plan") == state["entry"]["id"]
                  and event.get("stage") == "audit" and event.get("kind") == "stage-start"]
        decided = _latest_question(state, "audit", "open-audit: ")
        if (starts and (starts[-1].get("data") or {}).get("reason") == "audit-open" and decided is not None
                and decided.get("status") != "open" and decided.get("answer") == "fix"):
            reason = "audit-open"
    return _run_action(state, stage, reason)


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


def _candidates(data: Dict[str, Any], runner: Dict[str, Any], states: List[Dict[str, Any]],
                waiting: List[Dict[str, Any]], asks: Dict[str, Dict[str, Any]],
                flying: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """Rules 1, 2, 4, 7-10: one step per plan that can move; every other unfinished plan goes to
    `waiting` with its reason. One plan at a time holds the code stages: the one already in them
    (even while it waits for an answer), the one with uncommitted changes first (a committed plan
    sent back by drift must not execute over them), else the first plan in runner order that reaches them.
    Rule 9 cascade questions do not hold their plan: they become `answer` steps. A plan whose agent
    is in flight (`flying`: plan id -> stage) gets no step; an agent in a code stage holds them."""
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
    for state in states:
        if state["entry"]["id"] in flying:
            stage = flying[state["entry"]["id"]]
            waiting.append({"spec": state["spec"], "plan": state["entry"]["plan"], "stage": stage,
                            "reason": f"in-flight: {stage}"})
            continue
        if state["next"] is None:
            continue
        stage, reason = state["next"]
        where = {"spec": state["spec"], "plan": state["entry"]["plan"], "stage": stage}
        why: Optional[str] = None
        if state["open"]:
            why = "open-question: " + ", ".join(state["open"])
        elif stage == "writing" and _record(state, "writing").get("status") == "pending":
            why = _dependency_wait(runner, by_spec, state, asks)
        if why is None and stage in CODE_STAGES:
            holder = holder or state
            if holder is not state:
                why = f"code-busy: {holder['entry']['id']}"
        step = _stage_step(data, state, stage, reason) if why is None else {"kind": "wait", "why": why}
        if step["kind"] == "wait":
            waiting.append(dict(where, reason=step["why"]))
        else:
            step["running"] = _record(state, stage).get("status") == "running"
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
    return {"ok": True, "journal_dir": os.path.dirname(os.path.abspath(journal)), "actions": actions,
            "waiting": waiting, "done": done, "blocked": not done and not actions and not flying}


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


def run_status(journal: str) -> Dict[str, Any]:
    """Per plan: stage statuses, the next stage (rules 7 and 9), unit progress; open questions, waits
    without a question of their own (stage-failed: stop, not-confirmed: stop, model: stop, code-busy),
    ETA and the session mark. Reads only."""
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
             if item["reason"] in ("stage-failed: stop", "not-confirmed: stop", "model: stop") or item["reason"].startswith("code-busy: ")]
    return {"ok": True, "goal": data.get("goal"), "profile": runner.get("profile"), "plans": plans,
            "open_questions": questions, "waits": waits, "eta_minutes": _eta(data, states)["eta_minutes"],
            "session": _session_state(journal)}


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
    p_pick.set_defaults(func=cmd_model_pick)

    p_init = sub.add_parser("run-init", help="write the runner section of the chain journal")
    p_init.add_argument("journal", help="path to <goal>-chain.json")
    p_init.add_argument("--profile", required=True, help=", ".join(PROFILES))
    p_init.add_argument("--spec", action="append", required=True, help="spec of the run, relative to CWD (repeatable)")
    p_init.add_argument("--graph", required=True, help='JSON {spec: [spec it depends on, ...]}, paths as in --spec')
    p_init.add_argument("--models", required=True, help='JSON {role: {"model", "effort"}} (settings-load roles)')
    p_init.add_argument("--start-commit", help="sha of the start commit, declined or none")
    p_init.add_argument("--parallel", type=int, help="most agents at once for this run (read by run-next first)")
    p_init.set_defaults(func=cmd_run_init)

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
    p_run_eta = sub.add_parser("run-eta", help="minutes left from the stage and unit history of the journal")
    p_run_eta.add_argument("journal", help="path to <goal>-chain.json with a runner section")
    p_run_eta.set_defaults(func=cmd_run_eta)
    p_run_status = sub.add_parser("run-status", help="stages, progress, open questions, ETA and session of a run")
    p_run_status.add_argument("journal", help="path to <goal>-chain.json with a runner section")
    p_run_status.set_defaults(func=cmd_run_status)
    return parser


JOURNAL_READERS = ("run-next", "run-eta", "run-status")


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
