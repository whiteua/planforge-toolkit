import argparse
from datetime import datetime, timezone
import functools
import hashlib
import importlib.util
import json
from json import JSONDecodeError
import os
import re
import shlex
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path


VALID_WEIGHTS = {"green", "yellow", "red"}
VALID_STATUSES = {"pending", "running", "done", "failed"}
LEDGER_VERSION = 2
ATTEMPTS_LIMIT = 3
ROADMAP_COLUMNS = 5
ROADMAP_SUFFIX = "-roadmap.md"
_PART_ID_RE = re.compile(r"^[a-z]{1,2}$")  # plan-splitter part ids: a, b, ... aa
_ROADMAP_HEADER_RE = re.compile(r"\|\s*(stage|стадия)\s*\|", re.IGNORECASE)
_CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")
_TASK_RE = re.compile(
    r"^(#{2,4})\s*(Task|Step|Phase|Stage|Задача|Шаг|Фаза|Этап)\s+(\S+?)\s*(?:[:\-]|—|\.\s)\s*(.+?)\s*$",
    re.IGNORECASE,
)
_TASK_KEYWORDS = {"task", "задача"}
_GROUP_KEYWORDS = {"phase", "stage", "фаза", "этап"}
_HEADING_RE = re.compile(r"^(#{1,6})\s+")
_FENCE_RE = re.compile(r"^ {0,3}(```|~~~)")
_TIER_RE = re.compile(r"^\*\*Tier:\*\*\s*(\w+)", re.IGNORECASE | re.MULTILINE)
_TIER_WEIGHTS = {"quick": "green", "standard": "yellow", "deep": "red"}
_SECTION_RE = re.compile(r"^#{1,6}\s*(inputs|outputs|files|входные данные|выходные данные)\s*$", re.IGNORECASE)
_FILES_BLOCK_RE = re.compile(r"^\*\*(files|файлы):\*\*\s*$", re.IGNORECASE)
_FILE_ACTION_RE = re.compile(r"^\s*[-*]\s*(create|modify|test|delete|move|создать|изменить|тест)\s*:", re.IGNORECASE)
_CODE_PATH_RE = re.compile(r"`([^`\s]+?\.[A-Za-z0-9]+)(?::(\d+(?:-\d+)?))?`")
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+\.[A-Za-z0-9]+)\]\(([^)]+)\)")
_HEAVY_KEYWORDS_RE = re.compile(
    r"\b(refactor\w*|architect\w*|security|migrat\w*|concurren\w*|auth|authn|authz|authentication|authoriz\w*|oauth\w*)\b",
    re.IGNORECASE,
)
_STATUS_EMOJI = {"pending": "⏳", "running": "🔄", "done": "✅", "failed": "❌"}
_WEIGHT_ORDER = ["green", "yellow", "red"]
_CHECKPOINT_TITLE_RE = re.compile(r"^checkpoint\b", re.IGNORECASE)
_DOC_PATH_RE = re.compile(r"(^|/)docs?/|\.(md|mdx|rst|txt|adoc)$", re.IGNORECASE)
_EXTERNAL_RE = re.compile(r"^\*\*External:\*\*\s*(.+?)\s*$", re.MULTILINE)
_REF_UNSAFE_RE = re.compile(r"[^A-Za-z0-9._-]")
_SNAPSHOT_ENV = {
    "GIT_AUTHOR_NAME": "plan-executor",
    "GIT_AUTHOR_EMAIL": "plan-executor@localhost",
    "GIT_COMMITTER_NAME": "plan-executor",
    "GIT_COMMITTER_EMAIL": "plan-executor@localhost",
}


COMMANDS = {}


class ToolError(ValueError):
    """Error with a machine-readable exit code: 2 = input/filesystem, 1 = contract violation."""

    def __init__(self, message, code=1, **details):
        super().__init__(message)
        self.code = code
        self.details = details


def _normalize_weight(raw):
    value = str(raw or "").strip().lower()
    if "green" in value or "light" in value or "🟢" in value:
        return "green"
    if "red" in value or "heavy" in value or "🔴" in value:
        return "red"
    if "yellow" in value or "medium" in value or "🟡" in value:
        return "yellow"
    return "yellow"


def _sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_text(path):
    try:
        return Path(path).read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ToolError(f"file not found: {path}", 2) from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise ToolError(f"cannot read {path}: {exc}", 2) from exc


def _error_signature(error):
    return " ".join(str(error or "").lower().split())


def validate_ledger(obj):
    errors = []
    required = ["version", "plan_path", "input_type", "created_at", "units"]
    for field in required:
        if field not in obj:
            errors.append(f"missing field: {field}")
    if errors:
        return errors

    if obj["version"] not in {1, LEDGER_VERSION}:
        errors.append(f"invalid version: {obj['version']}")
    if obj["input_type"] not in {"staged", "whole"}:
        errors.append(f"invalid input_type: {obj['input_type']}")
    if not isinstance(obj["units"], list):
        errors.append("units must be list")
        return errors
    if not obj["units"]:
        errors.append("units must not be empty")

    unit_required = ["id", "title", "weight", "status", "attempts", "depends", "parallel_group", "last_error", "checkpoint_id"]
    seen = set()
    for index, unit in enumerate(obj["units"]):
        if not isinstance(unit, dict):
            errors.append(f"unit {index} must be object")
            continue
        for field in unit_required:
            if field not in unit:
                errors.append(f"unit {index} missing field: {field}")
        if unit.get("id") in seen:
            errors.append(f"duplicate unit id: {unit['id']}")
        seen.add(unit.get("id"))
        if "weight" in unit and unit["weight"] not in VALID_WEIGHTS:
            errors.append(f"invalid weight: {unit['weight']}")
        if "status" in unit and unit["status"] not in VALID_STATUSES:
            errors.append(f"invalid status: {unit['status']}")
        if "attempts" in unit and (not isinstance(unit["attempts"], int) or unit["attempts"] < 0):
            errors.append(f"invalid attempts: {unit['attempts']}")
        if "depends" in unit and not isinstance(unit["depends"], list):
            errors.append("depends must be list")
    return errors


def detect_input(plan_path, force_whole=False):
    plan = Path(plan_path).resolve()
    if force_whole:
        return {"input_type": "whole", "roadmap": None}
    if plan.name.endswith(ROADMAP_SUFFIX):
        return {"input_type": "staged", "roadmap": str(plan)}
    candidate = plan.parent / f"{plan.stem}{ROADMAP_SUFFIX}"
    if candidate.exists():
        return {"input_type": "staged", "roadmap": str(candidate.resolve())}
    return {"input_type": "whole", "roadmap": None}


def _split_markdown_row(line):
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    return cells


def _is_separator_row(line):
    cells = _split_markdown_row(line)
    if not cells:
        return False
    return all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells)


def _parse_depends(raw):
    value = str(raw or "").strip()
    if value in {"", "-", "—", "none", "None", "нет", "Нет"}:
        return []
    # Same tolerance as plan-splitter: comma or whitespace separated, case-insensitive.
    return [part.lower() for part in re.split(r"[,\s]+", value) if part and part not in {"-", "—"}]


def parse_roadmap_table(text):
    rows = []
    in_table = False
    for line in text.splitlines():
        if not in_table:
            if _ROADMAP_HEADER_RE.search(line):
                in_table = True
            else:
                continue

        if not line.strip().startswith("|"):
            if rows:
                break
            continue
        if _is_separator_row(line) or _ROADMAP_HEADER_RE.search(line):
            continue

        cells = _split_markdown_row(line)
        if len(cells) < ROADMAP_COLUMNS:
            continue
        stage, title, depends, group, weight = cells[:ROADMAP_COLUMNS]
        if not stage:
            continue
        rows.append(
            {
                "stage": stage.lower(),
                "title": title,
                "depends": _parse_depends(depends),
                "group": group or None,
                "weight": _normalize_weight(weight),
            }
        )
    return rows


def detect_cycle(graph):
    white = set(graph)
    gray = set()
    black = set()
    path = []

    def visit(node):
        if node in black:
            return
        if node in gray:
            start = path.index(node) if node in path else 0
            cycle = path[start:] + [node]
            raise ToolError("cycle detected: " + " -> ".join(cycle), 2)
        gray.add(node)
        path.append(node)
        for dep in graph.get(node, []):
            if dep in graph:
                visit(dep)
        path.pop()
        gray.remove(node)
        black.add(node)
        white.discard(node)

    while white:
        visit(next(iter(white)))


def parse_roadmap(path):
    rows = parse_roadmap_table(_read_text(path))
    invalid = [row["stage"] for row in rows if not _PART_ID_RE.match(row["stage"])]
    if invalid:
        raise ToolError("invalid-stage-id: " + ", ".join(invalid) + " (expected a, b, ... aa)", 2)
    graph = {row["stage"]: row["depends"] for row in rows}
    unknown = [f"{row['stage']} -> {dep}" for row in rows for dep in row["depends"] if dep not in graph]
    if unknown:
        raise ToolError("unknown-dependency: " + ", ".join(unknown), 2)
    detect_cycle(graph)
    return rows


def _headings(lines):
    """Yield (index, level, line) for Markdown headings outside fenced code blocks."""
    in_fence = False
    for index, line in enumerate(lines):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = _HEADING_RE.match(line)
        if match:
            yield index, len(match.group(1)), line


def _plan_weight(text):
    match = _TIER_RE.search(text)
    return _TIER_WEIGHTS.get(match.group(1).lower(), "yellow") if match else "yellow"


def _task_weight(plan_weight, title, section_text):
    """Plan tier weight, lowered for units that do not need the expensive gate.

    Checkpoint tasks and documentation-only tasks are green (their gate is the command or a
    read-through); tasks that touch only test files go one step down."""
    if _CHECKPOINT_TITLE_RE.match(title or ""):
        return "green"
    files = [entry for entry in extract_files(section_text) if entry["action"] in ("create", "modify", "test", "delete", "move")]
    if not files:
        return plan_weight
    if all(_DOC_PATH_RE.search(entry["path"]) for entry in files):
        return "green"
    if all(entry["action"] == "test" for entry in files):
        return _WEIGHT_ORDER[max(0, _WEIGHT_ORDER.index(plan_weight) - 1)]
    return plan_weight


def _contract_tasks(text):
    """The plan's tasks by plan-brainstorming's shared parser (brainstorm_tool.parse_plan_tasks).

    None when the parser is not installed alongside, when the plan has no contract task heading,
    or when a task-like heading breaks the contract (malformed): those plans keep the local parse."""
    parse = getattr(_load_brainstorm_tool(), "parse_plan_tasks", None)
    if parse is None:
        return None
    parsed = parse(text)
    if not parsed["tasks"] or parsed["malformed"]:
        return None
    return parsed


def _contract_units(plan_path, text, parsed):
    """Units `task-<id>` of a contract plan; parallel_group from the nearest Phase/Stage section."""
    if parsed["duplicates"]:
        first = min(parsed["duplicates"], key=lambda item: item["lines"][1])
        raise ToolError(f"duplicate-unit-id: task-{first['id']}", 2)
    lines = text.splitlines()
    weight = _plan_weight(text)
    path = str(Path(plan_path).resolve())
    units = []
    group = None
    for task in parsed["tasks"]:
        section = _TASK_RE.match(task["section"] or "")
        if section and section.group(2).lower() in _GROUP_KEYWORDS:
            group = f"{section.group(2).lower()}-{section.group(3)}"
        body = "\n".join(lines[task["line_start"] - 1:task["line_end"]])
        units.append(
            {
                "id": f"task-{task['id']}",
                "title": task["title"],
                "weight": _task_weight(weight, task["title"], body),
                "depends": [units[-1]["id"]] if units else [],
                "parallel_group": group,
                "source": {"path": path, "line_start": task["line_start"], "line_end": task["line_end"]},
            }
        )
    return {"units": units}


def parse_tasks(plan_path):
    """Extract execution units from a whole plan.

    A plan in the plan format contract (`### Task N: <title>`) takes its units from the shared
    parser of plan-brainstorming (`_contract_tasks`). Otherwise: if the plan has `Task`/`Задача`
    headings, only those are units: `Phase`/`Stage` headings become their parallel_group and
    `Step` headings are ignored; without them every recognised heading is a unit. Units run
    strictly in document order.
    """
    text = _read_text(plan_path)
    parsed = _contract_tasks(text)
    if parsed is not None:
        return _contract_units(plan_path, text, parsed)
    lines = text.splitlines()
    headings = list(_headings(lines))
    matches = []
    for index, level, line in headings:
        match = _TASK_RE.match(line)
        if match:
            matches.append((index, level, match.group(2).lower(), match.group(3), match.group(4).strip()))
    has_tasks = any(keyword in _TASK_KEYWORDS for _, _, keyword, _, _ in matches)
    weight = _plan_weight(text)

    units = []
    group = None
    seen = set()
    for index, level, keyword, raw_id, title in matches:
        if has_tasks and keyword in _GROUP_KEYWORDS:
            group = f"{keyword}-{raw_id}"
            continue
        if has_tasks and keyword not in _TASK_KEYWORDS:
            continue
        unit_id = f"task-{raw_id}"
        if unit_id in seen:
            raise ToolError(f"duplicate-unit-id: {unit_id}", 2)
        seen.add(unit_id)
        end = next((i for i, lvl, _ in headings if i > index and lvl <= level), len(lines))
        units.append(
            {
                "id": unit_id,
                "title": title,
                "weight": _task_weight(weight, title, "\n".join(lines[index:end])) if has_tasks else weight,
                "depends": [units[-1]["id"]] if units else [],
                "parallel_group": group if has_tasks else None,
                "source": {"path": str(Path(plan_path).resolve()), "line_start": index + 1, "line_end": end},
            }
        )
    return {"units": units}


def ledger_path(exec_dir):
    return Path(exec_dir) / "state.json"


def _full_unit(unit):
    unit_id = unit.get("id") or unit.get("stage")
    if not unit_id:
        raise ToolError("unit missing id/stage", 2)
    return {
        "id": unit_id,
        "title": unit.get("title", unit_id),
        "weight": _normalize_weight(unit.get("weight", "yellow")),
        "status": "pending",
        "attempts": 0,
        "depends": list(unit.get("depends") or []),
        "parallel_group": unit.get("parallel_group", unit.get("group")),
        "last_error": None,
        "previous_error": None,
        "checkpoint_id": None,
        "source": unit.get("source"),
        "notes": [],
    }


def build_ledger(plan_path, input_type, units, source_sha256=None):
    raw_units = units.get("units", []) if isinstance(units, dict) else units
    if not raw_units:
        raise ToolError("no-units: the plan has no Task headings; use --whole or plan-splitter", 2)
    created = datetime.now(timezone.utc).replace(microsecond=0)
    ledger = {
        "version": LEDGER_VERSION,
        "plan_path": str(Path(plan_path).resolve()),
        "source_sha256": source_sha256,
        "input_type": input_type,
        "created_at": created.isoformat().replace("+00:00", "Z"),
        "run_id": created.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6],
        "workdir": None,
        "baseline_checkpoint": None,
        "units": [_full_unit(unit) for unit in raw_units],
    }
    errors = validate_ledger(ledger)
    if errors:
        raise ToolError("invalid ledger: " + "; ".join(errors), 2)
    return ledger


def _save(exec_dir, led):
    path = ledger_path(exec_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(led, ensure_ascii=False, indent=2) + "\n"
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, str(path))
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return led


def _migrate(led):
    """Upgrade a v1 ledger in memory; v1 files stay loadable."""
    if led.get("version") == 1:
        led["version"] = LEDGER_VERSION
        led.setdefault("source_sha256", None)
        led.setdefault("run_id", "v1-" + uuid.uuid4().hex[:6])
        led.setdefault("workdir", None)
        led.setdefault("baseline_checkpoint", None)
        for unit in led.get("units", []):
            if isinstance(unit, dict):
                unit.setdefault("source", None)
    return led


def _load(exec_dir):
    path = ledger_path(exec_dir)
    try:
        led = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ToolError(f"ledger not found: {path}", 2) from exc
    except JSONDecodeError as exc:
        raise ToolError(f"invalid ledger json: {path}", 2) from exc
    errors = validate_ledger(led)
    if errors:
        raise ToolError("invalid ledger: " + "; ".join(errors), 2)
    return _migrate(led)


def _drift(led, units):
    old_ids = [unit["id"] for unit in led["units"]]
    new_ids = [unit.get("id") or unit.get("stage") for unit in units]
    return {
        "added": [uid for uid in new_ids if uid not in old_ids],
        "removed": [uid for uid in old_ids if uid not in new_ids],
    }


_SETTINGS_KEYS = ("tier", "chain", "environments", "backlog")


def _apply_settings(led, settings, accept_drift=False):
    """Store resolve_settings output and its source file on the ledger; True when it changed.

    settings None means plan-brainstorming is not installed: the ledger keeps what it has."""
    if settings is None:
        changed = "settings" not in led
        led.setdefault("settings", None)
        led.setdefault("settings_source", None)
        return changed
    source = {"path": settings["source"], "sha256": settings.get("source_sha256")} if settings.get("source") else None
    if not settings.get("ok", True) and not settings.get("source") and led.get("settings_source"):
        # The source cannot be read on resume (e.g. the spec was removed): not a drift. Keep the
        # stored settings; cmd_ledger_init reports settings-unavailable (warning or error).
        return False
    old_sha = (led.get("settings_source") or {}).get("sha256")
    if old_sha and old_sha != (source or {}).get("sha256") and not accept_drift:
        old = led.get("settings") or {}
        changed_keys = [key for key in _SETTINGS_KEYS if old.get(key) != settings.get(key)]
        raise ToolError("settings-drift: the settings source changed since the ledger was created; ask the engineer",
                        1, changed_keys=changed_keys, settings_source=source)
    changed = led.get("settings") != settings or led.get("settings_source") != source
    led["settings"] = settings
    led["settings_source"] = source
    return changed


def ledger_init(exec_dir, plan_path, input_type, units, source_sha256=None, accept_drift=False, settings=None):
    raw_units = units.get("units", []) if isinstance(units, dict) else units
    path = ledger_path(exec_dir)
    if path.exists():
        led = _load(exec_dir)
        changed = False
        if source_sha256 and not led.get("source_sha256"):
            led["source_sha256"] = source_sha256
            changed = True
        drifted = source_sha256 and led["source_sha256"] != source_sha256
        if drifted:
            diff = _drift(led, raw_units)
            if not accept_drift:
                raise ToolError("plan-drift: the plan changed since the ledger was created; ask the engineer", 1, **diff)
            done = {unit["id"]: unit for unit in led["units"] if unit["status"] == "done"}
            rebuilt = build_ledger(plan_path, input_type, raw_units, source_sha256)["units"]
            led["units"] = [done.get(unit["id"], unit) for unit in rebuilt]
            led["source_sha256"] = source_sha256
            changed = True
        interrupted = False
        for unit in led["units"]:
            if unit["status"] == "running":
                unit["status"] = "pending"
                changed = True
                interrupted = True
        if interrupted and led.get("workdir"):
            # The interrupted attempt's files are the run's own state, as after unit-finish fail:
            # the next unit-begin must not report them as foreign.
            try:
                led["expected_tree"] = _worktree_tree(led["workdir"], journal=_run_journal(led))
            except ToolError:
                led["expected_tree"] = None
        if led.get("consents"):
            led["consents"] = {}  # run-scope consents last one session
            changed = True
        changed = _apply_settings(led, settings, accept_drift) or changed
        if changed:
            _save(exec_dir, led)
        return led
    led = build_ledger(plan_path, input_type, raw_units, source_sha256)
    led["consents"] = {}
    _apply_settings(led, settings)
    return _save(exec_dir, led)


def _find_unit(led, unit_id):
    for unit in led["units"]:
        if unit["id"] == unit_id:
            return unit
    raise ToolError(f"unknown unit: {unit_id}", 2)


def ledger_mark(exec_dir, unit_id, status, error=None, checkpoint=None):
    if status not in VALID_STATUSES:
        raise ToolError(f"invalid status: {status}", 2)
    led = _load(exec_dir)
    unit = _find_unit(led, unit_id)
    current = unit["status"]

    if current == "done":
        if status == "done":
            return unit
        raise ToolError("done is terminal")
    if status == "running":
        if current not in {"pending", "failed"}:
            raise ToolError(f"invalid transition: {current} -> running")
        unit["status"] = "running"
        unit["attempts"] += 1
    elif status == "failed":
        if current != "running":
            raise ToolError(f"invalid transition: {current} -> failed")
        old_error = unit.get("last_error")
        unit["previous_error"] = old_error
        unit["status"] = "failed"
        unit["last_error"] = error
        stagnation = old_error is not None and _error_signature(old_error) == _error_signature(error)
        _save(exec_dir, led)
        result = dict(unit)
        result["stagnation"] = stagnation
        return result
    elif status == "pending":
        if current != "failed":
            raise ToolError(f"invalid transition: {current} -> pending")
        unit["status"] = "pending"
        unit["last_error"] = None
    elif status == "done":
        if current != "running":
            raise ToolError(f"invalid transition: {current} -> done")
        unit["status"] = "done"
        unit["last_error"] = None
        unit["checkpoint_id"] = checkpoint

    _save(exec_dir, led)
    return unit


def _stop_reason(unit):
    if unit["attempts"] >= ATTEMPTS_LIMIT:
        return "exhausted"
    prev = unit.get("previous_error")
    if prev is not None and _error_signature(prev) == _error_signature(unit["last_error"]):
        return "stagnated"
    return None


def ledger_next(exec_dir):
    """Pick the next unit. Reasons: ready, retry-available, in-progress, exhausted,
    stagnated, blocked, all-done. A failed unit is retried before any other unit runs."""
    led = _load(exec_dir)
    units_by_id = {unit["id"]: unit for unit in led["units"]}
    if all(unit["status"] == "done" for unit in led["units"]):
        return {"unit": None, "reason": "all-done"}

    for unit in led["units"]:
        if unit["status"] == "running":
            return {"unit": unit, "reason": "in-progress"}

    for unit in led["units"]:
        if unit["status"] != "failed":
            continue
        reason = _stop_reason(unit)
        if reason:
            return {"unit": unit, "reason": reason}
        return {"unit": unit, "reason": "retry-available"}

    blocked_by = set()
    for unit in led["units"]:
        if unit["status"] != "pending":
            continue
        waiting = [dep for dep in unit["depends"] if units_by_id.get(dep, {}).get("status") != "done"]
        if not waiting:
            return {"unit": unit, "reason": "ready"}
        blocked_by.update(waiting)
    return {"unit": None, "reason": "blocked", "blocked_by": sorted(blocked_by)}


def attempts_exhausted(unit):
    return unit.get("attempts", 0) >= ATTEMPTS_LIMIT


def ledger_status(exec_dir):
    led = _load(exec_dir)
    counts = {"pending": 0, "running": 0, "done": 0, "failed": 0}
    running = []
    has_exhausted = False
    for unit in led["units"]:
        counts[unit["status"]] += 1
        if unit["status"] == "running":
            running.append(unit["id"])
        if attempts_exhausted(unit):
            has_exhausted = True
    return {"counts": counts, "running": running, "has_exhausted": has_exhausted}


def _git(workdir, *args, env=None):
    result = subprocess.run(
        ["git", *args],
        cwd=workdir,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env=env,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or f"git {' '.join(args)} failed"
        raise ToolError(message, 1)
    return result.stdout


def checkpoint_detect(workdir, journal=None, plan_dir=None):
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=workdir,
            capture_output=True,
            text=True,
            check=False,
        )
    except (FileNotFoundError, NotADirectoryError):
        return {"vcs": "none", "dirty": None}
    if result.returncode == 0 and result.stdout.strip() == "true":
        # BACKLOG.md at the repository root is the shared backlog the skills append to between
        # runs: it never makes the working tree dirty (same set as the foreign-change check).
        excluded = [f":(top,exclude){path}" for path in sorted(_FOREIGN_IGNORED)]
        excluded += _journal_pathspecs(workdir, journal, "top,exclude")
        # The pipeline's own files (_is_chain_file: followups, diffs, reviews, reports, specs and plans)
        # never make it dirty either; a *-chain.json other than the run's journal still does.
        # --untracked-files=normal (it overrides status.showUntrackedFiles) shows an untracked folder as one
        # "?? dir/" entry: only such folders are listed file by file, each file judged by its name (F6).
        out = _git(workdir, "status", "--porcelain", "-z", "--untracked-files=normal", "--", ":/", *excluded)
        items, paths, folders = out.split("\0"), [], []
        while items:
            item = items.pop(0)
            if len(item) > 3:
                if item.startswith("?? ") and item.endswith("/"):
                    folders.append(item[3:].rstrip("/"))
                    continue
                paths.append(item[3:])
                if "R" in item[:2] or "C" in item[:2]:  # a rename or copy: the source path follows
                    paths.append(items.pop(0) if items else "")

        def foreign(path):  # plan_dir: the run's plan folder when the caller knows it (F3)
            return not _is_chain_file(path, plan_dir) or bool(_JOURNAL_NAME_RE.search(path))

        dirty = any(foreign(path) for path in paths)
        if folders and not dirty:
            try:
                listed = _git(workdir, "ls-files", "--others", "--exclude-standard", "--full-name", "-z", "--",
                              *[f":(top,literal){folder}" for folder in folders], *excluded)
            except ToolError:
                dirty = True  # the folder's files are unknown: dirty is the safe side
            else:
                dirty = any(foreign(path) for path in _z_list(listed))
        return {"vcs": "git", "dirty": dirty}
    return {"vcs": "none", "dirty": None}


def _with_temp_index(workdir, callback):
    fd, index_path = tempfile.mkstemp(prefix="plan-executor-index-")
    os.close(fd)
    os.unlink(index_path)
    env = dict(os.environ, GIT_INDEX_FILE=index_path, **_SNAPSHOT_ENV)
    try:
        return callback(env)
    finally:
        if os.path.exists(index_path):
            os.unlink(index_path)


# Never a foreign change: BACKLOG.md at the repository root is the shared workspace backlog
# that the skills themselves append to.
_FOREIGN_IGNORED = {"BACKLOG.md"}
_TREE_STATUS = {"A": "added", "D": "deleted"}


def _worktree_tree(workdir, journal=None):
    """Tree sha of the working tree, built exactly like a snapshot (temp index: HEAD, then
    add -A) but without commit-tree or a ref. None outside git."""
    if not workdir or checkpoint_detect(workdir)["vcs"] != "git":
        return None

    def build(env):
        try:
            _git(workdir, "rev-parse", "--verify", "-q", "HEAD", env=env)
            _git(workdir, "read-tree", "HEAD", env=env)
        except ToolError:
            pass
        _git(workdir, "add", "-A", env=env)
        _drop_journal(workdir, env, journal)
        return _git(workdir, "write-tree", env=env).strip()

    return _with_temp_index(workdir, build)


def _commit_tree(workdir, sha):
    """Tree sha of a snapshot commit; None when there is no snapshot."""
    if not workdir or not sha:
        return None
    return _git(workdir, "rev-parse", f"{sha}^{{tree}}").strip()


def _tree_diff(workdir, old_tree, new_tree):
    """[{path, status: added|modified|deleted}] between two trees, sorted by path."""
    if old_tree == new_tree:
        return []
    out = _git(workdir, "diff-tree", "-r", "--no-renames", "--name-status", "-z", old_tree, new_tree)
    items = [item for item in out.split("\0") if item]
    changes = [{"path": path, "status": _TREE_STATUS.get(status[:1], "modified")}
               for status, path in zip(items[0::2], items[1::2])]
    return sorted(changes, key=lambda change: change["path"])


def checkpoint_create(workdir, label, run_id="manual", journal=None):
    """Snapshot the working tree into refs/plan-executor/<run>/<label>.

    Uses a temporary index and commit-tree: HEAD, the branch and the user's index
    are never touched, so no commit appears in the branch history."""
    if checkpoint_detect(workdir)["vcs"] != "git":
        return {"checkpoint_id": None, "vcs": "none", "ref": None}

    def snapshot(env):
        try:
            _git(workdir, "rev-parse", "--verify", "-q", "HEAD", env=env)
            _git(workdir, "read-tree", "HEAD", env=env)
        except ToolError:
            pass
        _git(workdir, "add", "-A", env=env)
        _drop_journal(workdir, env, journal)
        tree = _git(workdir, "write-tree", env=env).strip()
        return _git(workdir, "commit-tree", tree, "-m", f"[plan-executor] {label}", env=env).strip()

    sha = _with_temp_index(workdir, snapshot)
    ref = f"refs/plan-executor/{_REF_UNSAFE_RE.sub('-', run_id)}/{_REF_UNSAFE_RE.sub('-', label)}"
    _git(workdir, "update-ref", ref, sha)
    return {"checkpoint_id": sha, "vcs": "git", "ref": ref}


def _z_list(output):
    return {item for item in output.split("\0") if item}


def checkpoint_restore(workdir, checkpoint_id, plan_dir=None, own=()):
    """Make the working tree match a snapshot: rewrite its files and delete files added
    after it. The branch, HEAD and the user's index are not changed."""
    if checkpoint_detect(workdir)["vcs"] != "git":
        raise ToolError("not a git repository", 1)
    # Like snapshots and --paths, the whole repository is restored from its root, not only workdir.
    root = _git(workdir, "rev-parse", "--show-toplevel").strip()
    snapshot_files = _z_list(_git(root, "ls-tree", "-r", "-z", "--name-only", checkpoint_id))
    current_files = _z_list(_git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard"))
    # The shared backlog and the pipeline's files are not part of a rollback (the skills write them).
    removed = sorted(rel for rel in current_files - snapshot_files if not _is_chain_file(rel, plan_dir, own))
    for rel in removed:
        target = Path(root) / rel
        if target.is_file() or target.is_symlink():
            target.unlink()

    def checkout(env):
        _git(root, "read-tree", checkpoint_id, env=env)
        kept = _FOREIGN_IGNORED | {rel for rel in snapshot_files if _is_chain_file(rel, plan_dir, own)}
        _git(root, "--literal-pathspecs", "rm", "--cached", "-f", "-q", "--ignore-unmatch", "--", *sorted(kept),
             env=env)
        _git(root, "checkout-index", "-a", "-f", env=env)

    _with_temp_index(root, checkout)
    return {"restored_to": checkpoint_id, "removed": removed}


def _safe_rel_path(raw):
    rel = str(raw).replace("\\", "/")
    while rel.startswith("./"):
        rel = rel[2:]
    # `C:x` is relative to the current directory of drive C, a leading `:` is git pathspec magic.
    if (not rel or rel.startswith("/") or os.path.isabs(str(raw)) or ".." in rel.split("/")
            or re.match(r"^[A-Za-z]:", rel) or rel.startswith(":")):
        raise ToolError(f"invalid-path: {raw} (expected a path relative to the repository root)", 2)
    return rel


def _same_as_tree(workdir, tree_ish, rels):
    """The paths of `rels` whose working-tree content equals their blob in `tree_ish`
    (hash-object applies the same filters as git add, so line-ending conversion is not a change)."""
    if not rels:
        return set()
    blobs = _git(workdir, "rev-parse", *[f"{tree_ish}:{rel}" for rel in rels]).split()
    hashes = _git(workdir, "hash-object", "--", *rels).split()
    return {rel for rel, blob, digest in zip(rels, blobs, hashes) if blob == digest}


def checkpoint_restore_paths(workdir, tree_ish, paths, plan_dir=None, own=()):
    """Restore only `paths` from a snapshot or tree: changed and deleted files come back from it,
    files absent from it are deleted. Every path is checked before anything is written."""
    if checkpoint_detect(workdir)["vcs"] != "git":
        raise ToolError("not a git repository", 1)
    wanted = sorted(rel for rel in {_safe_rel_path(raw) for raw in paths} if not _is_chain_file(rel, plan_dir, own))
    if not wanted:
        raise ToolError("paths-empty: nothing to restore after excluding BACKLOG.md and the chain files", 2)
    # Like snapshots and foreign changes, paths are relative to the repository root, not to workdir.
    root = _git(workdir, "rev-parse", "--show-toplevel").strip()
    in_tree = _z_list(_git(root, "ls-tree", "-r", "-z", "--name-only", tree_ish, "--", *wanted))
    present = {rel for rel in wanted if (Path(root) / rel).is_file() or (Path(root) / rel).is_symlink()}
    unknown = [rel for rel in wanted if rel not in in_tree and rel not in present]
    if unknown:
        raise ToolError("unknown-path: " + ", ".join(unknown) + " (neither in the snapshot nor in the working tree)",
                        2, unknown=unknown)
    restored = [rel for rel in wanted if rel in in_tree]
    removed = [rel for rel in wanted if rel not in in_tree]
    same = _same_as_tree(root, tree_ish, [rel for rel in restored if rel in present])
    statuses = [{"path": rel, "status": "added" if rel in removed else "unchanged" if rel in same
                 else "modified" if rel in present else "deleted"} for rel in wanted]
    for rel in removed:
        (Path(root) / rel).unlink()

    def checkout(env):
        _git(root, "read-tree", tree_ish, env=env)
        _git(root, "checkout-index", "-f", "--", *restored, env=env)

    if restored:
        _with_temp_index(root, checkout)
    return {"restored_to": tree_ish, "restored": restored, "removed": removed, "paths": statuses}


def checkpoint_prune(workdir, run_id):
    if checkpoint_detect(workdir)["vcs"] != "git":
        return {"pruned": []}
    prefix = f"refs/plan-executor/{_REF_UNSAFE_RE.sub('-', run_id)}/"
    refs = [line for line in _git(workdir, "for-each-ref", "--format=%(refname)", prefix).splitlines() if line]
    for ref in refs:
        _git(workdir, "update-ref", "-d", ref)
    return {"pruned": refs}


def recommend_gate(weight):
    return {"gate_tier": _normalize_weight(weight), "no_tests": "escalate"}


def recommend_strategy(weight, task_text=""):
    gate_tier = recommend_gate(weight)["gate_tier"]
    base = {
        "green": ("main", "light"),
        "yellow": ("main", "medium"),
        "red": ("subagent", "deep"),
    }
    isolation, model_depth = base[gate_tier]
    if _HEAVY_KEYWORDS_RE.search(task_text or ""):
        isolation = "subagent"
        model_depth = "deep"
    return {"isolation": isolation, "model_depth": model_depth, "gate_tier": gate_tier}


def _clean_path(value):
    cleaned = value.strip().strip(".,;:")
    if cleaned.startswith("./"):
        cleaned = cleaned[2:]
    return cleaned.replace("\\", "/")


def extract_files(text):
    """Paths from `## Inputs/Outputs/Files` sections and `**Files:**` blocks.

    A `path:12-30` suffix inside backticks is split off into `lines`."""
    files = []
    seen = set()
    in_scope = False
    for line in text.splitlines():
        stripped = line.strip()
        if _SECTION_RE.match(stripped) or _FILES_BLOCK_RE.match(stripped):
            in_scope = True
            continue
        if in_scope and (_HEADING_RE.match(stripped) or (stripped.startswith("**") and not _FILE_ACTION_RE.match(line))):
            in_scope = False
        if not in_scope:
            continue
        action_match = _FILE_ACTION_RE.match(line)
        action = action_match.group(1).lower() if action_match else None
        candidates = [(match.group(1), None) for match in _MARKDOWN_LINK_RE.finditer(line)]
        candidates.extend((match.group(1), match.group(2)) for match in _CODE_PATH_RE.finditer(line))
        for candidate, lines in candidates:
            path = _clean_path(candidate)
            if path and path not in seen:
                seen.add(path)
                files.append({"path": path, "action": action, "lines": lines})
    return files


def scope_context(stage_text):
    return {"paths": [entry["path"] for entry in extract_files(stage_text)]}


def render_progress(exec_dir):
    led = _load(exec_dir)
    lines = [
        "# Plan Executor Progress",
        "",
        "| Task | Status | Attempts | Weight | Last Error |",
        "|---|---|---:|---|---|",
    ]
    for unit in led["units"]:
        status = unit["status"]
        status_text = f"{_STATUS_EMOJI.get(status, '')} {status}".strip()
        last_error = " ".join(str(unit.get("last_error") or "").split()).replace("|", "\\|")
        lines.append(f"| {unit['id']} | {status_text} | {unit['attempts']} | {unit['weight']} | {last_error} |")
    noted = [(unit["id"], note) for unit in led["units"] for note in unit.get("notes") or []]
    if noted:
        lines += ["", "## Notes (deviations agreed with the engineer)", ""]
        lines += [f"- {unit_id}: {' '.join(str(note).split())}" for unit_id, note in noted]
    path = Path(exec_dir).resolve() / "progress.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"path": str(path)}


def _stage_source(roadmap_path, stage):
    roadmap = Path(roadmap_path)
    base = roadmap.name[: -len(ROADMAP_SUFFIX)]
    candidate = roadmap.parent / f"{base}-{stage}.md"
    return {"path": str(candidate.resolve()), "line_start": None, "line_end": None} if candidate.exists() else None


def unit_text(unit):
    source = unit.get("source") or {}
    if not source.get("path") or not os.path.isfile(source["path"]):
        return None
    lines = _read_text(source["path"]).splitlines()
    start = (source.get("line_start") or 1) - 1
    end = source.get("line_end") or len(lines)
    return "\n".join(lines[start:end]).strip() + "\n"


def _inside(path, root):
    try:
        return os.path.commonpath([os.path.abspath(path), os.path.abspath(root)]) == os.path.abspath(root)
    except ValueError:
        return False


def _is_temp(path):
    return _inside(os.path.realpath(path), os.path.realpath(tempfile.gettempdir()))


def default_exec_dir(workdir, plan_path):
    """<repo parent>/.exec/<repo>-<plan base>: outside the repository, stable across sessions."""
    repo = Path(workdir).resolve()
    return str(repo.parent / ".exec" / f"{repo.name}-{Path(plan_path).stem}")


def _check_exec_dir(exec_dir, workdir, allow_temp=False):
    # A ledger in the OS temp dir disappears with the session: the run cannot be resumed or
    # audited. A temp workdir (tests, throwaway clones) may keep its ledger in temp.
    if _is_temp(exec_dir) and not _is_temp(workdir) and not allow_temp:
        raise ToolError(
            f"exec-dir-ephemeral: {exec_dir} is inside the OS temp dir; use 'auto' "
            f"({default_exec_dir(workdir, 'plan')[:-5]}-<plan>) or pass --allow-temp", 2)
    if not _inside(exec_dir, workdir):
        return
    probe = os.path.join(os.path.abspath(exec_dir), "state.json")
    try:
        result = subprocess.run(["git", "check-ignore", "-q", probe], cwd=workdir, capture_output=True, check=False)
    except OSError as exc:
        raise ToolError(f"git-unavailable: cannot run git to check the exec dir ({exc})", 2)
    if result.returncode != 0:
        raise ToolError(f"exec-dir-inside-workdir: {exec_dir} is inside {workdir} and not git-ignored", 2)


def _set_expected_tree(exec_dir, tree):
    led = _load(exec_dir)
    led["expected_tree"] = tree
    _save(exec_dir, led)
    return tree


def _foreign_check(led):
    """Compare the working tree with the ledger's expected_tree.

    foreign_changes is None, with a one-line warning, when the check cannot run: no git working
    tree, or a ledger written before expected_tree existed (the next unit-finish sets it)."""
    workdir = led.get("workdir")
    current = _worktree_tree(workdir, journal=_run_journal(led))
    expected = led.get("expected_tree")
    result = {"foreign_changes": None, "expected_tree": expected, "current_tree": current, "warning": None}
    if current is None:
        result["warning"] = "foreign-change check is off: the working tree is not a git repository"
    elif not expected:
        result["warning"] = "foreign-change check starts after the next finished unit (old ledger)"
    else:
        try:
            changes = _tree_diff(workdir, expected, current)
        except ToolError:
            # A tree without a ref can be pruned by git gc during a long pause (Known limitation).
            result["warning"] = (f"expected_tree {expected} is missing from the object store; "
                                 "accept-changes resets it")
        else:
            folder = _plan_dir(led)  # a chain-file name outside the plan folder is a project file (F3)
            result["foreign_changes"] = [change for change in changes
                                         if not _is_chain_file(change["path"], folder)]
    return result


def unit_begin(exec_dir):
    nxt = ledger_next(exec_dir)
    if nxt["reason"] not in {"ready", "retry-available"}:
        return _journal_stop(exec_dir, nxt)
    # Files changed outside the run since the last unit (J11): report them and mark nothing running.
    check = _foreign_check(_load(exec_dir))
    if check["foreign_changes"]:
        return {"reason": "foreign-changes", "unit": nxt["unit"], "foreign_changes": check["foreign_changes"],
                "expected_tree": check["expected_tree"], "current_tree": check["current_tree"]}
    unit = nxt["unit"]
    text = unit_text(unit) or ""
    strategy = recommend_strategy(unit["weight"], unit["title"])
    running = ledger_mark(exec_dir, unit["id"], "running")
    result = {
        "reason": nxt["reason"],
        "foreign_changes": check["foreign_changes"],
        "foreign_warning": check["warning"],
        "unit": running,
        "strategy": strategy,
        "text": text or None,
        "files": extract_files(text),
        # `**External:** `env` (read|write) — ...` lines with the consent that covers each one;
        # recorded on the unit in the ledger. Unconfirmed entries need the engineer (GATE.md).
        "external": _record_external(exec_dir, running, text),
    }
    return _journal_progress(exec_dir, "unit-begin", unit["id"], result)


def _restore_target(led, unit_id):
    target = led.get("baseline_checkpoint")
    for unit in led["units"]:
        if unit["id"] == unit_id:
            break
        if unit["status"] == "done" and unit.get("checkpoint_id"):
            target = unit["checkpoint_id"]
    return target


def _add_note(exec_dir, unit_id, note):
    led = _load(exec_dir)
    unit = _find_unit(led, unit_id)
    unit.setdefault("notes", []).append(" ".join(str(note).split()))
    _save(exec_dir, led)
    return unit


def _environments(led):
    settings = led.get("settings") or {}
    return {env["name"]: env for env in settings.get("environments") or [] if isinstance(env, dict) and env.get("name")}


def _external_items(line):
    """Every `env` (read|write) item before the description dash, whatever separates them
    (comma, semicolon, "and", spaces); backticked commands after the dash are not environments."""
    head, in_code = line, False
    for index, char in enumerate(line):
        if char == "`":
            in_code = not in_code
        elif not in_code and (char in "—–" or line[index:index + 3] == " - "):
            head = line[:index]
            break
    return [(m.group(1), m.group(2).lower() if m.group(2) else None)
            for m in re.finditer(r"`([^`]+)`\s*(?:\((read|write)\))?", head, re.IGNORECASE)]


_FENCE_OPEN_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


def _external_lines(text):
    """Bodies of the `**External:**` lines outside fenced code blocks: a fixture or an example
    inside a fence is not a request for access. As in CommonMark, only a line of the opening
    fence's character, at least as long and with nothing else on it, closes the block: a shorter
    or other fence inside it is content, so a real External line after the block is never lost."""
    bodies, fence = [], None
    for line in (text or "").splitlines():
        opening = _FENCE_OPEN_RE.match(line)
        if fence is None:
            if opening:
                fence = opening.group(1)
                continue
            found = _EXTERNAL_RE.match(line)
            if found:
                bodies.append(found.group(1))
        elif (opening and opening.group(1)[0] == fence[0] and len(opening.group(1)) >= len(fence)
              and not line.strip().strip(fence[0])):
            fence = None
    return bodies


def _external_entries(text, led):
    """One entry per environment of each `**External:**` line: the consent from the stored settings
    (run|task|deny) and whether it may run without a question (run, or a run-scope consent).
    Settings stored with errors grant nothing, and a production write is never confirmed."""
    valid = (led.get("settings") or {}).get("ok", True)
    environments = _environments(led)
    consents = led.get("consents") or {}
    entries = []
    for line in _external_lines(text):
        for env, access in _external_items(line) or [(None, None)]:
            setting = environments.get(env) or {}
            consent = setting.get(access) if access and valid else None
            session = bool(valid and access and consent != "deny" and (consents.get(env) or {}).get(access))
            confirmed = consent == "run" or session
            if setting.get("kind") == "prod" and access == "write":
                confirmed = False
            source = None if not confirmed else ("spec" if consent == "run" else "session")
            entries.append({"env": env, "access": access, "kind": setting.get("kind"), "consent": consent,
                            "confirmed": confirmed, "source": source})
    return entries


def _record_external(exec_dir, unit, text):
    """Compute the unit's external entries and record them on the unit in the ledger."""
    led = _load(exec_dir)
    entries = _external_entries(text, led)
    _find_unit(led, unit["id"])["external"] = entries
    _save(exec_dir, led)
    unit["external"] = entries
    return entries


def record_consent(exec_dir, env, access):
    """Run-scope consent the engineer gave during execution ("the whole run", GATE.md)."""
    led = _load(exec_dir)
    environments = _environments(led)
    setting = environments.get(env)
    if setting is None:
        raise ToolError(f"consent-unknown-environment: `{env}` is not in the run's settings", 1,
                        environments=sorted(environments))
    if setting.get("kind") == "prod" and access == "write":
        raise ToolError(f"consent-prod-write: changes on prod `{env}` are confirmed task by task, never for the run", 1)
    if setting.get(access) == "deny":
        raise ToolError(f"consent-denied: {access}=deny for `{env}` in the settings; the plan must change", 1)
    led.setdefault("consents", {}).setdefault(env, {})[access] = True
    _save(exec_dir, led)
    return {"ok": True, "env": env, "access": access, "consents": led["consents"]}


def _utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def accept_changes(exec_dir, note=None):
    """The engineer keeps the foreign changes: the current tree becomes the expected one."""
    led = _load(exec_dir)
    check = _foreign_check(led)
    if check["current_tree"] is None:
        raise ToolError("accept-changes-unavailable: the run has no git working tree", 1)
    accepted = check["foreign_changes"] or []
    event = None
    if accepted:
        event = {"at": _utc_now(), "paths": accepted, "decision": "accepted",
                 "note": " ".join(str(note).split()) if note else None}
        led.setdefault("foreign_events", []).append(event)
    led["expected_tree"] = check["current_tree"]
    _save(exec_dir, led)
    return {"expected_tree": led["expected_tree"], "accepted": accepted, "event": event}


def run_diff(exec_dir):
    """What this run changed: baseline snapshot vs the last done unit's snapshot."""
    led = _load(exec_dir)
    workdir = led.get("workdir")
    baseline = led.get("baseline_checkpoint")
    last = None
    for unit in led["units"]:
        if unit["status"] == "done" and unit.get("checkpoint_id"):
            last = unit["checkpoint_id"]
    if workdir and checkpoint_detect(workdir)["vcs"] != "git":
        raise ToolError("no-git: the workdir is not a git repository; no diff report", 1)
    if not workdir or not baseline or not last:
        raise ToolError("run-diff-unavailable: the run has no baseline or no finished unit snapshot", 1)

    def git(*args):
        result = subprocess.run(["git", "-c", "core.quotepath=off", *args], cwd=workdir, capture_output=True,
                                text=True, encoding="utf-8", errors="replace", check=False)
        if result.returncode != 0:
            raise ToolError(f"run-diff-failed: {result.stderr.strip()}", 2)
        return result.stdout

    files = [line.split("\t", 1) for line in git("diff", "--name-status", baseline, last).splitlines() if "\t" in line]
    return {
        "baseline": baseline,
        "last": last,
        "files": [{"status": status, "path": path} for status, path in files],
        "stat": git("diff", "--stat", baseline, last).strip(),
        "command": f"git diff {baseline} {last}",
    }


# Files the pipeline writes itself never enter a run's diff report or commit (spec C).
_PIPELINE_ARTIFACT_RE = re.compile(
    r"(?:.*-spec\.md|.*-impl.*\.md|.*-review-.*\.md|.*-report-.*\.md|.*-roadmap\.md"
    r"|.*-chain\.json|.*-diffs\.md|.*-followups\.json)")


def _is_pipeline_artifact(rel, plan_dir_rel):
    """True for the plan directory (unless it is the repository root), the chain's artifacts in
    any directory (matched on the file name) and BACKLOG.md at the root. `rel` and `plan_dir_rel`
    are relative to the repository root."""
    rel = str(rel).replace("\\", "/").strip("/")
    plan_dir = str(plan_dir_rel or "").replace("\\", "/").strip("/")
    if rel in _FOREIGN_IGNORED:
        return True
    if plan_dir not in ("", ".") and (rel == plan_dir or rel.startswith(plan_dir + "/")):
        return True
    return bool(_PIPELINE_ARTIFACT_RE.fullmatch(rel.rsplit("/", 1)[-1]))


# The user's git config must not change the report: no colour, no external diff or textconv driver,
# the a/ and b/ prefixes whatever diff.noprefix or diff.mnemonicPrefix say.
_DIFF_PLAIN = ("--no-color", "--no-ext-diff", "--no-textconv")
_DIFF_PATCH = _DIFF_PLAIN + ("--src-prefix=a/", "--dst-prefix=b/")


def _diff_git(root, *args):
    result = subprocess.run(["git", "-c", "core.quotepath=off", *args], cwd=root, capture_output=True,
                            text=True, encoding="utf-8", errors="replace", check=False)
    if result.returncode != 0:
        raise ToolError(f"run-diff-failed: {result.stderr.strip()}", 2)
    return result.stdout


def _diff_entries(root, base, target, paths=None):
    """Files of `git diff -M base target` (run from the repository root, paths root-relative):
    [{path, old_path, status, added, deleted, binary}] sorted by path. `paths` limits the diff;
    an empty list gives []. Binary files have added/deleted None."""
    if paths is not None and not paths:
        return []
    spec = ["--", *(":(literal)" + rel for rel in paths)] if paths else []
    items = _diff_git(root, "diff", *_DIFF_PLAIN, "-M", "--name-status", "-z", base, target, *spec).split("\0")
    entries, index = {}, 0
    while index < len(items) and items[index]:
        code = items[index]
        if code[:1] in ("R", "C"):
            old, path, index = items[index + 1], items[index + 2], index + 3
        else:
            old, path, index = None, items[index + 1], index + 2
        entries[path] = {"path": path, "old_path": old, "status": code[:1],
                         "added": None, "deleted": None, "binary": False}
    items = _diff_git(root, "diff", *_DIFF_PLAIN, "-M", "--numstat", "-z", base, target, *spec).split("\0")
    index = 0
    while index < len(items) and items[index]:
        added, deleted, path = items[index].split("\t", 2)
        if path:
            index += 1
        else:  # rename: "added\tdeleted\t\0old\0new\0"
            path, index = items[index + 2], index + 3
        if path in entries:
            binary = added == "-"
            entries[path].update(added=None if binary else int(added),
                                 deleted=None if binary else int(deleted), binary=binary)
    return [entries[path] for path in sorted(entries)]


DIFF_TRUNCATE_LINES = 400
# Headings of the diff report in the plan's language (detect_lang).
_DIFF_STRINGS = {
    "ru": {"title": "Diff-отчёт", "plan": "План", "baseline": "Исходный снимок", "last": "Последний снимок",
           "fixes": "Исправления аудита: от исходного снимка до рабочей копии", "date": "Дата",
           "summary": "Сводка", "files": "Изменения по файлам", "file": "Файл", "status": "Статус",
           "note": "Примечание", "binary": "двоичный файл", "fixed": "исправлено аудитом",
           "renamed": "переименован из", "empty": "Прогон не изменил файлов вне артефактов конвейера.",
           "truncated": "Показаны первые {shown} из {total} строк. Полный diff:",
           "excluded": "Не включены (артефакты конвейера)", "ignored": "Не включены (игнорируются git)",
           "posix": "(команда для оболочки POSIX: bash, zsh)"},
    "en": {"title": "Diff report", "plan": "Plan", "baseline": "Baseline snapshot", "last": "Last snapshot",
           "fixes": "Audit fixes: from the baseline snapshot to the working tree", "date": "Date",
           "summary": "Summary", "files": "Changes by file", "file": "File", "status": "Status",
           "note": "Note", "binary": "binary file", "fixed": "fixed by audit",
           "renamed": "renamed from", "empty": "The run changed no files outside the pipeline artifacts.",
           "truncated": "First {shown} of {total} lines shown. Full diff:",
           "excluded": "Not included (pipeline artifacts)", "ignored": "Not included (ignored by git)",
           "posix": "(command for a POSIX shell: bash, zsh)"},
}


# Characters that would end or change a link target (a target is a URL): percent-encoded.
_MD_TARGET_ESCAPES = {"%": "%25", "#": "%23", "`": "%60", "<": "%3C", ">": "%3E", "\\": "%5C"}
# Characters that would end the link text or open a code span, emphasis or a tag in it: backslash-escaped.
_MD_TEXT_RE = re.compile(r"([\\`*\[\]<>])")


def _md_link(report_dir, path, text):
    """[text](target) with the target relative to the report's folder, percent-encoded where a character
    would change the URL; a target with a space or parentheses goes in <...>; a file on another drive
    (Windows) is an absolute file:// URI. | is escaped because the link also sits in a table cell."""
    try:
        target = os.path.relpath(path, report_dir).replace(os.sep, "/")
    except ValueError:  # another drive on Windows: no relative path exists
        target = Path(path).as_uri()  # already percent-encoded
    else:
        target = "".join(_MD_TARGET_ESCAPES.get(ch, ch) for ch in target)
        if any(ch in target for ch in " ()"):
            target = f"<{target}>"
    label = _MD_TEXT_RE.sub(r"\\\1", text)
    return f"[{label}]({target})".replace("|", "\\|")


def _fence(text):
    """A backtick fence longer than any backtick run inside `text`, at least three."""
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)


def _code_span(text):
    """Inline code for `text`: a backtick run longer than any inside it, padded when it holds backticks."""
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    tick, pad = "`" * (longest + 1), " " if longest else ""
    return f"{tick}{pad}{text}{pad}{tick}"


def _file_section(heading, diff_text, command, strings, posix=False):
    """Lines of one file's section: heading and a diff block; a diff longer than
    DIFF_TRUNCATE_LINES keeps its first lines and names the command that shows it in full
    (with a note when the command is for a POSIX shell only, see _top_literal)."""
    lines = diff_text.split("\n")  # not splitlines:  , \x0c and the like are inside a diff line
    if lines and lines[-1] == "":
        lines.pop()
    body = "\n".join(lines[:DIFF_TRUNCATE_LINES])
    fence = _fence(body)
    section = [heading, "", fence + "diff", body, fence]
    if len(lines) > DIFF_TRUNCATE_LINES:
        note = strings["truncated"].format(shown=DIFF_TRUNCATE_LINES, total=len(lines))
        section += ["", f"{note} {_code_span(command)}" + (f" {strings['posix']}" if posix else "")]
    return section


def _render_diff_report(lang, plan_link, title, baseline, last, entries, fixes, excluded=(), ignored=()):
    """Markdown of the diff report. `entries`: dicts with path, old_path, status, added, deleted,
    binary, fixed, link, diff (text; unused for binary files) and command (full diff). `excluded`:
    the run's files dropped as pipeline artifacts, listed last so that none is dropped silently;
    `ignored`: audit fix files git ignores (no tree holds them), listed after them."""
    s = _DIFF_STRINGS.get(lang, _DIFF_STRINGS["en"])
    lines = [f"# {s['title']}: {title}", "", f"- {s['plan']}: {plan_link}",
             f"- {s['baseline']}: `{baseline}`", f"- {s['last']}: `{last}`"]
    if fixes:
        lines.append(f"- {s['fixes']}")
    lines += [f"- {s['date']}: {_utc_now()}", "", f"## {s['summary']}", ""]
    tail = (["", f"## {s['excluded']}", ""] + [f"- `{rel}`" for rel in excluded]) if excluded else []
    tail += (["", f"## {s['ignored']}", ""] + [f"- `{rel}`" for rel in ignored]) if ignored else []
    if not entries:
        return "\n".join(lines + [s["empty"]] + tail) + "\n"
    lines += [f"| {s['file']} | {s['status']} | + | − | {s['note']} |", "|---|---|---|---|---|"]
    for entry in entries:
        notes = [f"{s['renamed']} `{entry['old_path']}`"] if entry.get("old_path") else []
        notes += [s["binary"]] if entry["binary"] else []
        notes += [s["fixed"]] if entry["fixed"] else []
        added = "-" if entry["added"] is None else entry["added"]
        deleted = "-" if entry["deleted"] is None else entry["deleted"]
        lines.append(f"| {entry['link']} | {entry['status']} | {added} | {deleted} | {', '.join(notes)} |")
    lines += ["", f"## {s['files']}"]
    for entry in entries:
        if entry["binary"]:
            continue  # a binary file is a table row only
        heading = f"### {entry['link']}" + (f" — {s['fixed']}" if entry["fixed"] else "")
        lines += [""] + _file_section(heading, entry["diff"], entry["command"], s, posix=entry.get("posix", False))
    return "\n".join(lines + tail) + "\n"


def _plan_id(plan_path):
    """Journal plan id of a ledger's plan: the file name without .md (a roadmap: without
    -roadmap.md, i.e. the master plan's id)."""
    name = Path(plan_path).name
    if name.endswith(ROADMAP_SUFFIX):
        return name[: -len(ROADMAP_SUFFIX)]
    return name[:-3] if name.endswith(".md") else name


def _audit_fix_files(led, journal):
    """Repository-root-relative files the audit's fix loop changed: the journal's
    plans[<id>].stages.audit.artifacts.fix_files. The journal is `journal`, else the ledger's
    journal.path; the plan id is the ledger's journal.plan, else _plan_id(plan_path).
    [] without a journal or without an audit stage."""
    ref = led.get("journal") or {}
    path = journal or ref.get("path")
    if not path:
        return []
    module = _load_brainstorm_tool()
    if module is None or not hasattr(module, "journal_load"):
        raise ToolError("journal-unavailable: plan-brainstorming not installed alongside; "
                        "the audit's fix files cannot be read", 2)
    try:
        data = module.journal_load(str(path))
    except getattr(module, "InputError", ValueError) as exc:
        raise ToolError(str(exc), 2) from exc
    plan_id = ref.get("plan") or _plan_id(led["plan_path"])

    def shaped(value, kind, where):
        if value is not None and not isinstance(value, kind):
            raise ToolError(f"journal-corrupt: {path}: {where} must be {kind.__name__}", 2)
        return value or kind()

    entry = next((plan for plan in shaped(data.get("plans"), list, "plans")
                  if isinstance(plan, dict) and plan.get("id") == plan_id), None)
    if entry is None:
        raise ToolError(f"journal-plan-unknown: {plan_id} is not in {path}", 2)
    audit = shaped(shaped(entry.get("stages"), dict, f"{plan_id}.stages").get("audit"), dict,
                   f"{plan_id}.stages.audit")
    raw = shaped(audit.get("artifacts"), dict, f"{plan_id}.stages.audit.artifacts").get("fix_files") or []
    raw = [raw] if isinstance(raw, str) else raw
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise ToolError(f"journal-corrupt: {path}: {plan_id}.stages.audit.artifacts.fix_files "
                        "must be a list of strings", 2)
    return sorted({_safe_rel_path(item) for item in raw})


def run_diff_markdown(exec_dir, out_path, journal=None):
    """The run's diff as a Markdown report (spec C): header, summary table, one diff block per
    file; pipeline artifacts are excluded. The report file is overwritten (derived artifact).
    With `journal`, the audit's fix files are diffed from the baseline to the working tree
    and marked."""
    info = run_diff(exec_dir)  # no-git and run-diff-unavailable come from here
    led = _load(exec_dir)
    baseline, last = info["baseline"], info["last"]
    root = os.path.realpath(_diff_git(led["workdir"], "rev-parse", "--show-toplevel").strip())
    plan = os.path.realpath(led["plan_path"])
    plan_dir_rel = os.path.relpath(os.path.dirname(plan), root) if _inside(plan, root) else ""
    entries = {entry["path"]: dict(entry, fixed=False, target=last, posix=_posix_only(entry["path"]),
                                   command=f"git diff {baseline} {last} -- {_top_literal(entry['path'])}")
               for entry in _diff_entries(root, baseline, last)}
    fix_files = _audit_fix_files(led, journal) if journal else []
    ignored = []
    if fix_files:
        tree = _worktree_tree(led["workdir"], journal=_run_journal(led))  # untracked fix files count too
        paths = list(fix_files)
        for rel in fix_files:  # the audit's state replaces the run's: a file it reverted drops out
            popped = entries.pop(rel, None)
            if popped and popped["old_path"] and popped["old_path"] not in paths:
                paths.append(popped["old_path"])  # the run's rename: its deletion stays in the report
        for entry in _diff_entries(root, baseline, tree, paths):
            # The old path of a run's rename is diffed with the fixes so its deletion stays in the report,
            # but only the audit's own files are "fixed by audit" (F5).
            entries[entry["path"]] = dict(entry, fixed=entry["path"] in fix_files, target=tree,
                                          posix=_posix_only(entry["path"]),
                                          command=f"git diff {baseline} -- {_top_literal(entry['path'])}")
        # add -A skips ignored files, so no tree holds them: named, never dropped silently.
        ignored = sorted(rel for rel in _git_ignored(root, fix_files) if rel not in entries)
    excluded = sorted(path for path in entries if _is_pipeline_artifact(path, plan_dir_rel))
    kept = [entries[path] for path in sorted(entries) if path not in excluded]
    report_dir = os.path.dirname(os.path.realpath(out_path))
    for entry in kept:
        entry["link"] = _md_link(report_dir, os.path.join(root, entry["path"]), entry["path"])
        if not entry["binary"]:
            paths = [":(literal)" + rel for rel in (entry["old_path"], entry["path"]) if rel]
            entry["diff"] = _diff_git(root, "diff", *_DIFF_PATCH, "-M", baseline, entry["target"], "--", *paths)
    lang = detect_lang(_read_text(plan))["lang"] if os.path.isfile(plan) else "en"
    text = _render_diff_report(lang, _md_link(report_dir, plan, os.path.basename(plan)), _plan_id(plan),
                               baseline, last, kept, fixes=bool(fix_files), excluded=excluded, ignored=ignored)
    Path(out_path).write_bytes(text.encode("utf-8"))
    files = [{key: entry[key] for key in ("path", "old_path", "status", "added", "deleted", "binary", "fixed")}
             for entry in kept]
    return {"ok": True, "path": str(Path(out_path).resolve()), "lang": lang, "baseline": baseline,
            "last": last, "files": files, "excluded": excluded, "fix_files": fix_files, "ignored": ignored}


# In double quotes bash, zsh, PowerShell and cmd read a path alike unless it holds one of these.
_POSIX_ONLY_CHARS = frozenset('"$`!\\')


def _posix_only(rel):
    """True when the full-diff command for `rel` needs POSIX single quotes (the report then says so)."""
    return any(ch in _POSIX_ONLY_CHARS for ch in rel)


def _top_literal(rel):
    """A root-relative path as a literal pathspec for the full-diff command: in double quotes, or
    shell-quoted for a POSIX shell when the path holds ", $, `, ! or \\ (_posix_only)."""
    spec = f":(top,literal){rel}"
    return shlex.quote(spec) if _posix_only(rel) else f'"{spec}"'


def _git_ignored(root, rels):
    """The paths of `rels` that git ignores (untracked and matched by an ignore rule)."""
    if not rels:
        return []
    result = subprocess.run(["git", "-c", "core.quotepath=off", "check-ignore", "-z", "--stdin"], cwd=root,
                            input="\0".join(rels) + "\0", capture_output=True, text=True, encoding="utf-8",
                            errors="replace", check=False)
    if result.returncode not in (0, 1):  # 1: none of them is ignored
        raise ToolError(f"run-diff-failed: {result.stderr.strip()}", 2)
    return sorted(_z_list(result.stdout))


def unit_finish(exec_dir, unit_id, outcome, error=None, note=None):
    led = _load(exec_dir)
    workdir = led.get("workdir")
    if outcome == "pass":
        checkpoint = None
        if workdir:
            try:
                checkpoint = checkpoint_create(workdir, unit_id, led["run_id"],
                                               journal=_run_journal(led))["checkpoint_id"]
            except ToolError as exc:
                outcome, error = "fail", f"checkpoint-failed: {exc}"
        if outcome == "pass":
            unit = ledger_mark(exec_dir, unit_id, "done", checkpoint=checkpoint)
            if workdir:
                _set_expected_tree(exec_dir, _commit_tree(workdir, checkpoint))
            for text in ([note] if isinstance(note, str) else note or []):
                unit = _add_note(exec_dir, unit_id, text)
            progress = render_progress(exec_dir)
            result = {"status": "done", "unit": unit, "checkpoint_id": checkpoint, "progress": progress["path"]}
            return _journal_progress(exec_dir, "unit-finish", unit_id, result, outcome="pass")
    unit = ledger_mark(exec_dir, unit_id, "failed", error=error or "gate failed")
    if workdir:
        # The failed attempt's files are the run's own state: a retry must not see them as foreign.
        try:
            _set_expected_tree(exec_dir, _worktree_tree(workdir, journal=_run_journal(led)))
        except ToolError:
            _set_expected_tree(exec_dir, None)
    stop = _stop_reason(unit)
    progress = render_progress(exec_dir)
    result = {
        "status": "failed",
        "unit": {k: v for k, v in unit.items() if k != "stagnation"},
        "decision": "stop" if stop else "retry",
        "stop_reason": stop,
        "restore_to": _restore_target(led, unit_id),
        "progress": progress["path"],
    }
    return _journal_progress(exec_dir, "unit-finish", unit_id, result, outcome="fail")


def cmd_detect_input(args):
    return detect_input(args.plan_path, force_whole=args.whole)


def cmd_parse_roadmap(args):
    return parse_roadmap(args.roadmap_path)


def cmd_parse_tasks(args):
    return parse_tasks(args.plan_path)


def _extract_h1(plan_path):
    """Return the first H1 heading text, or the file stem as fallback."""
    text = _read_text(plan_path)
    match = re.search(r"^#\s+(.+?)\s*$", text, re.MULTILINE)
    if match:
        return match.group(1).strip()
    return Path(plan_path).stem


def _staged_sha256(roadmap_path, units):
    """Drift fingerprint for staged input: the roadmap plus every stage file it points to."""
    digest = hashlib.sha256(_sha256_file(roadmap_path).encode("utf-8"))
    for unit in units:
        source = (unit.get("source") or {}).get("path")
        file_sha = _sha256_file(source) if source and os.path.isfile(source) else "missing"
        digest.update(f"{unit['stage']}:{file_sha}".encode("utf-8"))
    return digest.hexdigest()


def detect_lang(text):
    """Ecosystem convention (same formula in plan-splitter and plan-iterative-revision)."""
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return {"lang": "en", "cyrillic_ratio": 0.0}
    ratio = sum(1 for ch in letters if _CYRILLIC_RE.match(ch)) / len(letters)
    return {"lang": "ru" if ratio > 0.05 else "en", "cyrillic_ratio": round(ratio, 4)}


def cmd_detect_lang(args):
    return detect_lang(_read_text(args.path))


BRAINSTORM_MISSING = ("plan-brainstorming not installed alongside: settings are not read; "
                      "every External unit needs the engineer's confirmation")


def _head_sha(workdir):
    """HEAD commit of the repository; "" while HEAD is unborn (no commit yet)."""
    try:
        return _git(workdir, "rev-parse", "--verify", "-q", "HEAD").strip()
    except ToolError:
        return ""


def locate_ledger(plan_path, workdir):
    """Where `ledger-init auto` keeps the ledger of this plan. A split plan runs by its roadmap, so
    <X>.md is also looked up as <X>-roadmap.md and a roadmap also as its master plan <X>.md; both
    found is ledger-ambiguous. Reads nothing else and writes nothing: consents and settings-drift
    stay as they are (the commit mode uses it after the run)."""
    path = Path(plan_path)
    if path.name.endswith(ROADMAP_SUFFIX):
        names = {"roadmap": path, "plan": path.with_name(path.name[: -len(ROADMAP_SUFFIX)] + ".md")}
    else:
        names = {"plan": path, "roadmap": path.with_name(path.stem + ROADMAP_SUFFIX)}
    found = {kind: default_exec_dir(workdir, name) for kind, name in names.items()}
    existing = [kind for kind, exec_dir in found.items() if ledger_path(exec_dir).is_file()]
    if len(existing) > 1:
        dirs = [found[kind] for kind in existing]
        raise ToolError("ledger-ambiguous: both the plan and its roadmap have a ledger: " + ", ".join(dirs)
                        + "; pass the exec_dir of the run to commit to commit-run", 2, exec_dirs=dirs)
    matched = existing[0] if existing else None
    return {"ok": True, "exec_dir": found[matched or next(iter(found))], "exists": matched is not None,
            "matched": matched}


def cmd_ledger_path(args):
    return locate_ledger(args.plan_path, args.workdir)


# Files of the pipeline itself: an exact name in the run's plan folder (any folder when no ledger tells
# the folder), plus BACKLOG.md at the root. The skills write them between units, so they are never a foreign
# change and a rollback never deletes or rewrites them. Any other file stays watched, in the plan's folder
# too (diffs and commits use _is_pipeline_artifact), and so does a name like api/openapi-spec.md elsewhere.
_CHAIN_FILE_RE = re.compile(
    r".+-(?:chain\.json(?:\.lock)?|diffs\.md|followups\.json|spec\.md|impl\.md|impl-[a-z]+\.md"
    r"|impl-roadmap\.md|completion\.md|review-\d+\.md|report-\d+(?:-final)?\.md)")


def _is_chain_file(rel, plan_dir=None, own=()):
    """True for BACKLOG.md at the root, for a path in `own` (the run's journal and its lock, _own_journal_rels)
    and for a _CHAIN_FILE_RE name in `plan_dir` (repository-root-relative, "" for the root; _plan_dir).
    Without plan_dir (no ledger) the name alone decides, in any folder."""
    rel = str(rel).replace("\\", "/")
    if rel in _FOREIGN_IGNORED or rel in own:
        return True
    folder, _, name = rel.rpartition("/")
    return bool(_CHAIN_FILE_RE.fullmatch(name)) and (plan_dir is None or folder == plan_dir)


def _plan_dir(led, top=None):
    """Repository-root-relative folder of the ledger's plan ("" for the root) for _is_chain_file. None when
    it cannot be known: no ledger, no plan_path, no workdir and no `top`, no git, a plan outside the
    repository; the chain files are then recognised by name only."""
    if not led or not led.get("plan_path"):
        return None
    if top is None:
        if not led.get("workdir"):
            return None
        try:
            top = _git(led["workdir"], "rev-parse", "--show-toplevel").strip()
        except (ToolError, OSError):
            return None
    top = os.path.realpath(top)
    plan = os.path.realpath(led["plan_path"])
    if not _inside(plan, top):
        return None
    folder = os.path.relpath(os.path.dirname(plan), top).replace(os.sep, "/")
    return "" if folder == "." else folder


def _own_journal_rels(led, workdir):
    """Repository-root-relative paths of the run's journal and its lock, for _is_chain_file: the journal lies
    next to the spec, which may be outside the plan's folder. () when the journal is unknown or outside the
    repository."""
    journal = _run_journal(led)
    if not journal:
        return ()
    top = os.path.realpath(_git(workdir, "rev-parse", "--show-toplevel").strip())
    path = os.path.realpath(journal)
    if not _inside(path, top):
        return ()
    rel = os.path.relpath(path, top).replace(os.sep, "/")
    return (rel, f"{rel}.lock")


# A chain file named like a journal: the dirty check leaves out only the run's own journal (by path).
_JOURNAL_NAME_RE = re.compile(r"-chain\.json(?:\.lock)?$")


# The chain journal is the run's own record, like the ledger: it changes after every unit, so snapshots
# and the working-tree tree leave it out, and it never makes the working tree dirty. Only the run's own
# journal is left out; every *-chain.json is the fallback for a journal whose path is unknown.
_JOURNAL_GLOBS = ("**/*-chain.json", "**/*-chain.json.lock")


def _journal_file(plan_path):
    """Absolute path of the plan's chain journal (brainstorm_tool.journal_path_for; nothing is created).
    None when it cannot be known: plan-brainstorming not alongside, or the plan's sources are missing."""
    try:
        module = _load_brainstorm_tool()
        if module is None or not hasattr(module, "journal_path_for"):
            return None
        return module.journal_path_for(str(Path(plan_path).resolve()))["journal"]
    except Exception:  # an unknown journal falls back to every *-chain.json
        return None


def _run_journal(led):
    """The run's journal: the ledger's journal.path, else the journal of the ledger's plan."""
    return (led.get("journal") or {}).get("path") or _journal_file(led["plan_path"])


def _journal_pathspecs(workdir, journal, magic):
    """Pathspecs of the journal and its lock with `magic` ("top" or "top,exclude"): the exact paths
    from the repository root, none for a journal outside it, every *-chain.json when it is unknown."""
    if not journal:
        return [f":({magic},glob){pattern}" for pattern in _JOURNAL_GLOBS]
    root = os.path.realpath(_git(workdir, "rev-parse", "--show-toplevel").strip())
    path = os.path.realpath(journal)
    if not _inside(path, root):
        return []
    rel = os.path.relpath(path, root).replace(os.sep, "/")
    return [f":({magic},literal){rel}", f":({magic},literal){rel}.lock"]


def _drop_journal(workdir, env, journal=None):
    """Remove the chain journal from the temporary index a snapshot or a tree is written from."""
    specs = _journal_pathspecs(workdir, journal, "top")
    if specs:
        _git(workdir, "rm", "--cached", "-q", "--ignore-unmatch", "--", *specs, env=env)


def _journal_call(led, name, *args, **kwargs):
    """brainstorm_tool.<name>(<the run's journal>, *args, **kwargs). Returns None on success, or when
    there is no journal or no journal code alongside, else the error text: the journal is a record
    of the run, never a gate, so this never raises."""
    journal = led.get("journal")
    if not journal:
        return None
    try:
        module = _load_brainstorm_tool()
        function = getattr(module, name, None) if module is not None else None
        if function is not None:
            function(journal["path"], *args, **kwargs)
    except Exception as exc:  # any failure of the journal is reported, not raised
        return str(exc) or exc.__class__.__name__
    return None


def _journal_open(plan_path):
    """(journal, master plan path, error) for a plan, roadmap or part: the chain journal found by
    brainstorm_tool.journal_path_for, created when missing. journal is {path, plan id}; it is None,
    without an error, when plan-brainstorming or its journal code is not installed alongside."""
    try:
        module = _load_brainstorm_tool()
        if module is None or not hasattr(module, "journal_path_for"):
            return None, None, None
        info = module.journal_path_for(str(Path(plan_path).resolve()))
        if not info.get("plan"):
            return None, None, None
        if not info["exists"]:
            lang = module.detect_lang_text(_read_text(info.get("spec") or info["plan"]))
            module.journal_create(info["journal"], info["goal"], lang, info.get("spec"))
        return {"path": info["journal"], "plan": Path(info["plan"]).stem}, info["plan"], None
    except Exception as exc:  # the journal never stops ledger-init
        return None, None, str(exc) or exc.__class__.__name__


def _journal_stage(led, stage):
    """Status of a stage of the run's plan in its journal: "pending" while the journal does not list
    the plan yet, None when the journal cannot be read (the next journal call reports why)."""
    try:
        data = _load_brainstorm_tool().journal_load(led["journal"]["path"])
    except Exception:  # unreadable journal: the caller's journal call returns the error
        return None
    for entry in data.get("plans") or []:
        if entry.get("id") == led["journal"]["plan"]:
            return ((entry.get("stages") or {}).get(stage) or {}).get("status", "pending")
    return "pending"


_JOURNAL_STOP = {"all-done": "done", "exhausted": "failed", "stagnated": "failed", "blocked": "failed"}


def _journal_progress(exec_dir, kind, unit_id, result, **data):
    """unit-begin / unit-finish event with the run's progress (done of total units); a journal error
    is added to the command's result as journal_error."""
    led = _load(exec_dir)
    if led.get("journal"):
        done = sum(1 for unit in led["units"] if unit["status"] == "done")
        payload = dict({"unit": unit_id}, **data, done=done, total=len(led["units"]))
        error = _journal_call(led, "journal_unit", led["journal"]["plan"], kind, payload)
        if not error and kind == "unit-finish" and _journal_stage(led, "execution") == "running":
            # Same status, new artifacts (stage-update): the stage carries the run's progress (spec A).
            error = _journal_call(led, "journal_event", "plan-executor", led["journal"]["plan"], "execution",
                                  "running", artifacts=[f"units_done={done}", f"units_total={len(led['units'])}"])
        if error:
            result["journal_error"] = error
    return result


def _journal_stop(exec_dir, nxt):
    """No unit to begin: stage execution becomes done (all-done, with the plan or roadmap hash) or
    failed (exhausted, stagnated, blocked), once; in-progress changes nothing."""
    status = _JOURNAL_STOP.get(nxt["reason"])
    led = _load(exec_dir)
    if status and led.get("journal") and _journal_stage(led, "execution") != status:
        extra = {"input_path": led["plan_path"]} if status == "done" else {}
        error = _journal_call(led, "journal_event", "plan-executor", led["journal"]["plan"], "execution",
                              status, **extra)
        if error:
            return dict(nxt, journal_error=error)
    return nxt


_SUBJECT_RE = re.compile(r"^(feat|fix|docs|refactor|test|chore|ci|perf|style)\([^()\s]+\): \S")


def _empty_tree(top):
    """Tree sha of the empty tree: what an unborn HEAD holds."""
    return _with_temp_index(top, lambda env: _git(top, "write-tree", env=env).strip())


def _changed_paths(top, old, new):
    """Repository-root-relative paths that differ between two tree-ish; an empty old is the empty tree.
    A rename is a deletion plus an addition, so both of its paths are listed."""
    return {change["path"] for change in _tree_diff(top, old or _empty_tree(top), new)}


def _commit_conflicts(led, top, files, fix_files, current):
    """Checks 3 and 4 of commit-run. mixed-files: the start snapshot differs from HEAD at the start, so the
    file held the user's uncommitted work when the run changed it. foreign-changes: the file differs from
    the run's expected tree and is not an audit fix."""
    dirty_at_start = _changed_paths(top, led["baseline_head"], led["baseline_checkpoint"])
    mixed = [rel for rel in files if rel in dirty_at_start]
    if mixed:
        raise ToolError("mixed-files: these files held the user's uncommitted work before the run and the run "
                        "changed them too: " + ", ".join(mixed), 1, files=mixed)
    expected = led.get("expected_tree")
    changed = _changed_paths(top, expected, current) if expected else set()
    foreign = [rel for rel in files if rel in changed and rel not in fix_files]
    if foreign:
        raise ToolError("foreign-changes: changed outside the run after its last unit: " + ", ".join(foreign),
                        1, files=foreign)


def commit_run(exec_dir, message_file, journal=None):
    """Commit the run's files and the audit's fixes on the user's branch (spec D): every refusal comes
    before the index is touched, and the commit runs the hooks. Never --no-verify, --amend, push or --force."""
    led = _load(exec_dir)
    workdir = led.get("workdir")
    if not workdir or checkpoint_detect(workdir)["vcs"] != "git":
        raise ToolError("no-git: the workdir is not a git repository; nothing to commit", 1)
    if "baseline_head" not in led:
        raise ToolError("baseline-head-unknown: the ledger has no baseline_head (it was created before "
                        "commit-run existed); commit this run by hand", 1)
    top = os.path.realpath(_git(workdir, "rev-parse", "--show-toplevel").strip())
    staged = sorted(_z_list(_git(top, "diff", "--cached", "--name-only", "-z")))
    if staged:
        raise ToolError("index-not-empty: the index already holds staged changes: " + ", ".join(staged)
                        + "; commit or unstage them first", 1, staged=staged)
    journal = journal or (led.get("journal") or {}).get("path")
    journal_error = None
    try:
        fix_files = set(_audit_fix_files(led, journal))
    except Exception as exc:  # unreadable journal: no audit fix is known, so a fixed file reads as foreign
        fix_files, journal_error = set(), str(exc) or exc.__class__.__name__
    last = None
    for unit in led["units"]:
        if unit["status"] == "done" and unit.get("checkpoint_id"):
            last = unit["checkpoint_id"]
    baseline = led.get("baseline_checkpoint")
    for sha in (baseline, last, led.get("expected_tree")):
        try:
            if sha:
                _git(top, "cat-file", "-e", sha)
        except ToolError:
            if sha == led.get("expected_tree") and sha not in (baseline, last):
                raise ToolError(f"snapshots-missing: the expected tree {sha} is not in the object store; run "
                                "accept-changes to take the current working tree as expected, then commit-run "
                                "again", 1) from None
            raise ToolError(f"snapshots-missing: {sha} is not in the object store (snapshot refs pruned and "
                            "garbage-collected); commit-run needs the run's snapshots, commit by hand", 1) from None
    running = [{"id": unit["id"], "status": "running"} for unit in led["units"] if unit["status"] == "running"]
    if running:
        raise ToolError("run-incomplete: a unit is still running: " + ", ".join(unit["id"] for unit in running)
                        + "; finish it (unit-finish) or roll it back before the commit", 1, units=running)
    run_files = _changed_paths(top, baseline, last) if baseline and last else set()
    plan = os.path.realpath(led["plan_path"])
    plan_dir = os.path.relpath(os.path.dirname(plan), top) if _inside(plan, top) else ""
    current = _worktree_tree(top, journal=_run_journal(led))
    pool = run_files | fix_files
    candidates = {rel for rel in pool if not _is_pipeline_artifact(rel, plan_dir)}
    # A file whose working copy equals HEAD is committed already (by an earlier call or by the user).
    files = sorted(candidates & _changed_paths(top, _head_sha(top), current))
    failed = [unit["id"] for unit in led["units"] if unit["status"] == "failed"]
    if failed and last:
        # A failed attempt that was not rolled back: its edits sit on top of the done units' files, and
        # expected_tree is that attempt's tree, so foreign-changes cannot see them. Audit fixes are wanted.
        after = _changed_paths(top, last, current)
        attempt = [rel for rel in files if rel in after and rel not in fix_files]
        if attempt:
            raise ToolError("failed-attempt: " + ", ".join(failed) + " failed and was not rolled back; these files "
                            "differ from the last done snapshot (the failed attempt's edits, or were changed outside "
                            "the run): " + ", ".join(attempt) + "; restore them (checkpoint-restore --paths) or "
                            "commit by hand", 1, files=attempt)
    # Units that failed or never ran are a warning, not a refusal: the user decides (COMMIT shows them).
    incomplete = [{"id": unit["id"], "status": unit["status"]} for unit in led["units"]
                  if unit["status"] in {"failed", "pending"}]
    if led["baseline_head"]:
        head = _head_sha(top)
        try:
            _git(top, "merge-base", "--is-ancestor", led["baseline_head"], "HEAD")
        except ToolError:  # another branch, rewritten history or an unborn HEAD: not the run's line
            raise ToolError(f"head-moved: HEAD {head or '(unborn)'} does not descend from {led['baseline_head']}, "
                            "the HEAD the run started from; switch back or commit by hand", 1,
                            baseline_head=led["baseline_head"], head=head) from None
    excluded = sorted(pool - candidates)  # run files that are the pipeline's artifacts: never committed
    # Dropped by the broad rules only (plan folder, name patterns), not as the pipeline's own files:
    # they may be real project files, so the agent names them to the user. A *-chain.json other than
    # the run's journal and its lock is a project file too (Task 53), e.g. config/supply-chain.json.
    own = _run_journal(led)
    own = os.path.realpath(own) if own else None
    own = os.path.relpath(own, top).replace(os.sep, "/") if own and _inside(own, top) else None
    chain_dir = _plan_dir(led, top)  # e.g. api/openapi-spec.md is a project file, not the pipeline's (F3)
    info = {"excluded": excluded, "excluded_outside_chain": [
        rel for rel in excluded if not _is_chain_file(rel, chain_dir)
        or (rel.endswith(("-chain.json", "-chain.json.lock")) and rel not in (own, f"{own}.lock"))]}
    if incomplete:
        info["incomplete"] = incomplete
    _commit_conflicts(led, top, files, fix_files, current)
    if not files:
        return {"ok": True, "empty": True, "files": [], **info}
    message = _read_text(message_file)
    subject = (message.splitlines() or [""])[0].strip()
    if not _SUBJECT_RE.match(subject) or len(subject) > 72:
        raise ToolError(f"bad-subject: {subject!r}: expected <type>(<scope>): <subject>, at most 72 characters, "
                        "type feat|fix|docs|refactor|test|chore|ci|perf|style", 2)
    _git(top, "--literal-pathspecs", "add", "-A", "--", *files)
    try:
        _git(top, "commit", "-q", "-F", str(Path(message_file).resolve()))
    except ToolError as exc:  # a hook refused the commit: the index goes back to how it was
        _git(top, "--literal-pathspecs", "reset", "-q", "--", *files)
        raise ToolError(f"commit-failed: {exc}", 1, files=files) from exc
    result = {"ok": True, "sha": _head_sha(top), "subject": subject, "files": files, "empty": False, **info}
    if journal:
        plan_id = (led.get("journal") or {}).get("plan") or _plan_id(led["plan_path"])
        target = {"journal": {"path": str(Path(journal).resolve()), "plan": plan_id}}
        journal_error = journal_error or _journal_call(target, "journal_add_commit", plan_id, result["sha"],
                                                       subject, files)
    if journal_error:
        result["journal_error"] = journal_error
    return result


def cmd_commit_run(args):
    return commit_run(args.exec_dir, args.message_file, journal=args.journal)


@functools.lru_cache(maxsize=None)
def _load_brainstorm_tool():
    """plan-brainstorming's brainstorm_tool.py, loaded by path once per process (None when it is not
    installed alongside). Tests swap it by replacing this function, which the cache does not affect."""
    path = Path(__file__).resolve().parents[2] / "plan-brainstorming" / "scripts" / "brainstorm_tool.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("brainstorm_tool", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _resolve_settings(plan_path):
    """Chain settings by the shared reading rule of plan-brainstorming (plan header, else the
    spec named by **Spec:**; a roadmap goes through its Source link). Returns (settings, warning);
    settings is None when plan-brainstorming is not installed alongside."""
    module = _load_brainstorm_tool()
    if module is None or not hasattr(module, "resolve_settings"):
        return None, BRAINSTORM_MISSING
    try:
        return module.resolve_settings(str(Path(plan_path).resolve())), None
    except getattr(module, "InputError", ValueError) as exc:  # e.g. a spec not in UTF-8: input error, exit 2
        raise ToolError(str(exc), 2) from exc


def cmd_ledger_init(args):
    detected = detect_input(args.plan_path, force_whole=args.whole)
    if detected["input_type"] == "staged":
        source_file = detected["roadmap"]
        units = parse_roadmap(source_file)
        for unit in units:
            unit["source"] = _stage_source(source_file, unit["stage"])
        source_sha256 = _staged_sha256(source_file, units)
    else:
        source_file = args.plan_path
        source_sha256 = _sha256_file(source_file)
        units = parse_tasks(args.plan_path)
        if not units.get("units") and args.whole:
            title = _extract_h1(args.plan_path)
            units = {"units": [{"id": "whole", "title": title, "weight": "yellow",
                                "source": {"path": str(Path(args.plan_path).resolve()), "line_start": None, "line_end": None}}]}
    workdir = getattr(args, "workdir", None)
    if args.exec_dir == "auto":
        if not workdir:
            raise ToolError("exec-dir-auto-needs-workdir: pass --workdir <repo> with exec_dir 'auto'", 2)
        args.exec_dir = default_exec_dir(workdir, args.plan_path)
    fresh = not ledger_path(args.exec_dir).exists()
    if workdir and fresh:
        _check_exec_dir(args.exec_dir, workdir, allow_temp=getattr(args, "allow_temp", False))
        # A fresh run has no ledger yet, so no plan_dir: chain files are recognised by name in any folder.
        detected_vcs = checkpoint_detect(workdir, journal=_journal_file(args.plan_path))
        if detected_vcs["dirty"] and not getattr(args, "allow_dirty", False):
            raise ToolError("dirty-worktree: uncommitted changes in workdir; ask the engineer (commit/stash or --allow-dirty)", 1)
    settings, warning = _resolve_settings(args.plan_path)
    warnings = [warning] if warning else list((settings or {}).get("warnings") or [])
    if settings is not None and not settings.get("ok", True):
        raw_units = units.get("units", []) if isinstance(units, dict) else units
        problems = "; ".join(settings.get("errors") or [])
        if any(_external_lines(unit_text(unit)) for unit in raw_units):
            raise ToolError("settings-unavailable: the plan has External units but its settings cannot be read ("
                            + problems + "); ask the engineer", 1, settings_errors=settings.get("errors") or [])
        warnings.append(f"settings-unavailable: {problems}; Chain defaults apply")
    led = ledger_init(args.exec_dir, args.plan_path, detected["input_type"], units,
                      source_sha256=source_sha256, accept_drift=getattr(args, "accept_drift", False),
                      settings=settings)
    if workdir and fresh:
        led["workdir"] = os.path.abspath(workdir)
        led["baseline_checkpoint"] = checkpoint_create(workdir, "baseline", led["run_id"],
                                                       journal=_journal_file(args.plan_path))["checkpoint_id"]
        led["expected_tree"] = _commit_tree(workdir, led["baseline_checkpoint"])
        led["foreign_events"] = []
        if led["baseline_checkpoint"]:
            # HEAD at the start of the run: commit-run tells the user's uncommitted work from the run's.
            led["baseline_head"] = _head_sha(workdir)
        _save(args.exec_dir, led)
    journal, master_plan, journal_error = _journal_open(args.plan_path)
    if journal is not None or "journal" not in led:
        led["journal"] = journal
        _save(args.exec_dir, led)
    if journal is not None and _journal_stage(led, "execution") in {"pending", "stopped", "failed", None}:
        # A running stage is a resume and a done stage stays done: neither gets a new event.
        # artifacts.exec_dir lets journal-reconcile find this ledger (_ledger_evidence); like every path
        # in the journal it is relative to the journal's folder. unit-finish keeps units_done current.
        exec_rel = _load_brainstorm_tool()._journal_rel(journal["path"], str(Path(args.exec_dir).resolve()))
        done = sum(1 for unit in led["units"] if unit["status"] == "done")
        journal_error = _journal_call(led, "journal_event", "plan-executor", master_plan, "execution", "running",
                                      artifacts=["exec_dir=" + exec_rel, f"units_done={done}",
                                                 f"units_total={len(led['units'])}"])
    # exec_dir is reported, not stored: tell the engineer where the ledger lives.
    result = dict(led, exec_dir=str(Path(args.exec_dir).resolve()), warnings=warnings)
    if journal_error:
        result["journal_error"] = journal_error
    return result


def cmd_ledger_next(args):
    return ledger_next(args.exec_dir)


def cmd_ledger_mark(args):
    return ledger_mark(args.exec_dir, args.unit_id, args.status, error=args.error, checkpoint=args.checkpoint)


def cmd_ledger_status(args):
    return ledger_status(args.exec_dir)


def cmd_unit_begin(args):
    return unit_begin(args.exec_dir)


def cmd_unit_finish(args):
    return unit_finish(args.exec_dir, args.unit_id, args.outcome, error=args.error, note=args.note)


def cmd_consent(args):
    return record_consent(args.exec_dir, args.env, args.access)


def cmd_run_diff(args):
    if args.include_fixes and not args.markdown:
        raise ToolError("include-fixes-needs-markdown: --include-fixes works with --markdown FILE", 2)
    if args.markdown:
        return run_diff_markdown(args.exec_dir, args.markdown, journal=args.include_fixes)
    return run_diff(args.exec_dir)


def _configure_run_diff(parser):
    parser.add_argument("exec_dir")
    parser.add_argument("--markdown", metavar="FILE",
                        help="write the diff report to FILE (overwritten); the output lists its files")
    parser.add_argument("--include-fixes", metavar="JOURNAL",
                        help="chain journal: add the audit's fix files, diffed up to the working tree")


def cmd_checkpoint_detect(args):
    return checkpoint_detect(args.workdir)


def cmd_checkpoint_create(args):
    return checkpoint_create(args.workdir, args.label, args.run_id)


def _after_restore(exec_dir, workdir, restored_paths=None):
    """Record a restore the executor made: expected_tree becomes the restored tree, so the next
    unit-begin does not report the restore itself as a foreign change. Foreign changes left in
    place by a --paths restore are recorded as accepted, never taken over silently."""
    led = _load(exec_dir)
    old = led.get("expected_tree")
    current = _worktree_tree(workdir, journal=_run_journal(led))
    if restored_paths:
        events = led.setdefault("foreign_events", [])
        events.append({"at": _utc_now(), "paths": restored_paths, "decision": "restored", "note": None})
        names = {entry["path"] for entry in restored_paths}
        folder = _plan_dir(led)
        kept = [change for change in (_tree_diff(workdir, old, current) if old and current else [])
                if change["path"] not in names and not _is_chain_file(change["path"], folder)]
        if kept:
            events.append({"at": _utc_now(), "paths": kept, "decision": "accepted",
                           "note": "kept while restoring other paths"})
    led["expected_tree"] = current
    _save(exec_dir, led)
    return current


def cmd_checkpoint_restore(args):
    exec_dir = getattr(args, "exec_dir", None)
    plan_dir, own = None, ()
    if exec_dir:
        # A missing or broken ledger fails before any file is touched; its plan folder tells the pipeline's
        # files from project files with the same names (F3), and its journal is never rolled back wherever it lies.
        # Without --exec-dir the name alone decides.
        led = _load(exec_dir)
        plan_dir, own = _plan_dir(led), _own_journal_rels(led, args.workdir)
    if getattr(args, "paths", None):
        result = checkpoint_restore_paths(args.workdir, args.checkpoint_id, args.paths, plan_dir=plan_dir, own=own)
    else:
        result = checkpoint_restore(args.workdir, args.checkpoint_id, plan_dir=plan_dir, own=own)
    if exec_dir:
        result["expected_tree"] = _after_restore(exec_dir, args.workdir, result.get("paths"))
    return result


def cmd_accept_changes(args):
    return accept_changes(args.exec_dir, note=args.note)


def cmd_checkpoint_prune(args):
    led = _load(args.exec_dir)
    return checkpoint_prune(led.get("workdir") or args.workdir or ".", led["run_id"])


def cmd_recommend_gate(args):
    return recommend_gate(args.weight)


def cmd_recommend_strategy(args):
    return recommend_strategy(args.weight, args.task_text)


def cmd_scope_context(args):
    return scope_context(_read_text(args.stage_path))


def cmd_render_progress(args):
    return render_progress(args.exec_dir)


def _register(command, handler, configure):
    COMMANDS[command] = (handler, configure)


def _configure_detect_input(parser):
    parser.add_argument("plan_path")
    parser.add_argument("--whole", action="store_true", default=False)


def _configure_parse_roadmap(parser):
    parser.add_argument("roadmap_path")


def _configure_parse_tasks(parser):
    parser.add_argument("plan_path")


def _configure_ledger_init(parser):
    parser.add_argument("exec_dir")
    parser.add_argument("plan_path")
    parser.add_argument("--whole", action="store_true", default=False)
    parser.add_argument("--workdir", help="project working tree; enables baseline and per-unit snapshots")
    parser.add_argument("--allow-dirty", action="store_true", default=False)
    parser.add_argument("--accept-drift", action="store_true", default=False)
    parser.add_argument("--allow-temp", action="store_true", default=False,
                        help="accept an exec_dir inside the OS temp dir (the ledger will not survive the session)")


def _configure_ledger_next(parser):
    parser.add_argument("exec_dir")


def _configure_ledger_mark(parser):
    parser.add_argument("exec_dir")
    parser.add_argument("unit_id")
    parser.add_argument("status", choices=sorted(VALID_STATUSES))
    parser.add_argument("--error")
    parser.add_argument("--checkpoint")


def _configure_ledger_status(parser):
    parser.add_argument("exec_dir")


def _configure_unit_begin(parser):
    parser.add_argument("exec_dir")


def _configure_unit_finish(parser):
    parser.add_argument("exec_dir")
    parser.add_argument("unit_id")
    parser.add_argument("outcome", choices=["pass", "fail"])
    parser.add_argument("--error")
    parser.add_argument("--note", action="append",
                        help="deviation agreed with the engineer, or a per-task External confirmation (pass only; repeatable)")


def _configure_consent(parser):
    parser.add_argument("exec_dir")
    parser.add_argument("env")
    parser.add_argument("access", choices=["read", "write"])


def _configure_checkpoint_detect(parser):
    parser.add_argument("workdir")


def _configure_checkpoint_create(parser):
    parser.add_argument("workdir")
    parser.add_argument("label")
    parser.add_argument("--run-id", default="manual")


def _configure_checkpoint_restore(parser):
    parser.add_argument("workdir")
    parser.add_argument("checkpoint_id", help="snapshot sha or tree sha (expected_tree)")
    parser.add_argument("--paths", nargs="+", help="restore only these repository-relative files")
    parser.add_argument("--exec-dir", help="ledger to update: expected_tree becomes the restored tree")


def _configure_accept_changes(parser):
    parser.add_argument("exec_dir")
    parser.add_argument("--note", help="why the engineer keeps the changes")


def _configure_checkpoint_prune(parser):
    parser.add_argument("exec_dir")
    parser.add_argument("--workdir")


def _configure_recommend_gate(parser):
    parser.add_argument("weight")


def _configure_recommend_strategy(parser):
    parser.add_argument("weight")
    parser.add_argument("--task-text", default="")


def _configure_scope_context(parser):
    parser.add_argument("stage_path")


def _configure_render_progress(parser):
    parser.add_argument("exec_dir")


def _configure_ledger_path(parser):
    parser.add_argument("plan_path")
    parser.add_argument("--workdir", required=True, help="the repository the run works in")


def _configure_commit_run(parser):
    parser.add_argument("exec_dir")
    parser.add_argument("--message-file", required=True, help="commit message; the first line is the subject")
    parser.add_argument("--journal", help="chain journal (default: the ledger's journal)")


_register("accept-changes", cmd_accept_changes, _configure_accept_changes)
_register("checkpoint-create", cmd_checkpoint_create, _configure_checkpoint_create)
_register("checkpoint-detect", cmd_checkpoint_detect, _configure_checkpoint_detect)
_register("checkpoint-prune", cmd_checkpoint_prune, _configure_checkpoint_prune)
_register("checkpoint-restore", cmd_checkpoint_restore, _configure_checkpoint_restore)
_register("consent", cmd_consent, _configure_consent)
_register("detect-input", cmd_detect_input, _configure_detect_input)
_register("detect-lang", cmd_detect_lang, lambda parser: parser.add_argument("path"))
_register("ledger-init", cmd_ledger_init, _configure_ledger_init)
_register("ledger-mark", cmd_ledger_mark, _configure_ledger_mark)
_register("ledger-next", cmd_ledger_next, _configure_ledger_next)
_register("ledger-status", cmd_ledger_status, _configure_ledger_status)
_register("parse-roadmap", cmd_parse_roadmap, _configure_parse_roadmap)
_register("parse-tasks", cmd_parse_tasks, _configure_parse_tasks)
_register("recommend-gate", cmd_recommend_gate, _configure_recommend_gate)
_register("recommend-strategy", cmd_recommend_strategy, _configure_recommend_strategy)
_register("render-progress", cmd_render_progress, _configure_render_progress)
_register("run-diff", cmd_run_diff, _configure_run_diff)
_register("scope-context", cmd_scope_context, _configure_scope_context)
_register("unit-begin", cmd_unit_begin, _configure_unit_begin)
_register("unit-finish", cmd_unit_finish, _configure_unit_finish)
_register("ledger-path", cmd_ledger_path, _configure_ledger_path)
_register("commit-run", cmd_commit_run, _configure_commit_run)


def build_parser():
    parser = argparse.ArgumentParser(prog="executor_tool.py")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in sorted(COMMANDS):
        handler, configure = COMMANDS[name]
        subparser = subparsers.add_parser(name)
        configure(subparser)
        subparser.set_defaults(handler=handler)
    return parser


def _print(data):
    print(json.dumps(data, ensure_ascii=False))


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = args.handler(args)
    except ToolError as exc:
        _print({"ok": False, "errors": [str(exc)], **exc.details})
        return exc.code
    except (OSError, UnicodeDecodeError) as exc:
        _print({"ok": False, "errors": [str(exc)]})
        return 2
    except (ValueError, RuntimeError) as exc:
        _print({"ok": False, "errors": [str(exc)]})
        return 1
    _print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
