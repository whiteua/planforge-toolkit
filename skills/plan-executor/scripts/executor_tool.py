import argparse
from datetime import datetime, timezone
import hashlib
import json
from json import JSONDecodeError
import os
import re
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


def parse_tasks(plan_path):
    """Extract execution units from a whole plan.

    If the plan has `Task`/`Задача` headings, only those are units: `Phase`/`Stage`
    headings become their parallel_group and `Step` headings are ignored. Otherwise
    every recognised heading is a unit. Units run strictly in document order.
    """
    text = _read_text(plan_path)
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
                "weight": weight,
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


def ledger_init(exec_dir, plan_path, input_type, units, source_sha256=None, accept_drift=False):
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
        for unit in led["units"]:
            if unit["status"] == "running":
                unit["status"] = "pending"
                changed = True
        if changed:
            _save(exec_dir, led)
        return led
    return _save(exec_dir, build_ledger(plan_path, input_type, raw_units, source_sha256))


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


def checkpoint_detect(workdir):
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
        dirty = bool(_git(workdir, "status", "--porcelain").strip())
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


def checkpoint_create(workdir, label, run_id="manual"):
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
        tree = _git(workdir, "write-tree", env=env).strip()
        return _git(workdir, "commit-tree", tree, "-m", f"[plan-executor] {label}", env=env).strip()

    sha = _with_temp_index(workdir, snapshot)
    ref = f"refs/plan-executor/{_REF_UNSAFE_RE.sub('-', run_id)}/{_REF_UNSAFE_RE.sub('-', label)}"
    _git(workdir, "update-ref", ref, sha)
    return {"checkpoint_id": sha, "vcs": "git", "ref": ref}


def _z_list(output):
    return {item for item in output.split("\0") if item}


def checkpoint_restore(workdir, checkpoint_id):
    """Make the working tree match a snapshot: rewrite its files and delete files added
    after it. The branch, HEAD and the user's index are not changed."""
    if checkpoint_detect(workdir)["vcs"] != "git":
        raise ToolError("not a git repository", 1)
    snapshot_files = _z_list(_git(workdir, "ls-tree", "-r", "-z", "--name-only", checkpoint_id))
    current_files = _z_list(_git(workdir, "ls-files", "-z", "--cached", "--others", "--exclude-standard"))
    removed = sorted(current_files - snapshot_files)
    for rel in removed:
        target = Path(workdir) / rel
        if target.is_file() or target.is_symlink():
            target.unlink()

    def checkout(env):
        _git(workdir, "read-tree", checkpoint_id, env=env)
        _git(workdir, "checkout-index", "-a", "-f", env=env)

    _with_temp_index(workdir, checkout)
    return {"restored_to": checkpoint_id, "removed": removed}


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


def _check_exec_dir(exec_dir, workdir):
    if not _inside(exec_dir, workdir):
        return
    probe = os.path.join(os.path.abspath(exec_dir), "state.json")
    try:
        result = subprocess.run(["git", "check-ignore", "-q", probe], cwd=workdir, capture_output=True, check=False)
    except OSError as exc:
        raise ToolError(f"git-unavailable: cannot run git to check the exec dir ({exc})", 2)
    if result.returncode != 0:
        raise ToolError(f"exec-dir-inside-workdir: {exec_dir} is inside {workdir} and not git-ignored", 2)


def unit_begin(exec_dir):
    nxt = ledger_next(exec_dir)
    if nxt["reason"] not in {"ready", "retry-available"}:
        return nxt
    unit = nxt["unit"]
    text = unit_text(unit) or ""
    strategy = recommend_strategy(unit["weight"], unit["title"])
    running = ledger_mark(exec_dir, unit["id"], "running")
    return {
        "reason": nxt["reason"],
        "unit": running,
        "strategy": strategy,
        "text": text or None,
        "files": extract_files(text),
    }


def _restore_target(led, unit_id):
    target = led.get("baseline_checkpoint")
    for unit in led["units"]:
        if unit["id"] == unit_id:
            break
        if unit["status"] == "done" and unit.get("checkpoint_id"):
            target = unit["checkpoint_id"]
    return target


def unit_finish(exec_dir, unit_id, outcome, error=None):
    led = _load(exec_dir)
    workdir = led.get("workdir")
    if outcome == "pass":
        checkpoint = None
        if workdir:
            try:
                checkpoint = checkpoint_create(workdir, unit_id, led["run_id"])["checkpoint_id"]
            except ToolError as exc:
                outcome, error = "fail", f"checkpoint-failed: {exc}"
        if outcome == "pass":
            unit = ledger_mark(exec_dir, unit_id, "done", checkpoint=checkpoint)
            progress = render_progress(exec_dir)
            return {"status": "done", "unit": unit, "checkpoint_id": checkpoint, "progress": progress["path"]}
    unit = ledger_mark(exec_dir, unit_id, "failed", error=error or "gate failed")
    stop = _stop_reason(unit)
    progress = render_progress(exec_dir)
    return {
        "status": "failed",
        "unit": {k: v for k, v in unit.items() if k != "stagnation"},
        "decision": "stop" if stop else "retry",
        "stop_reason": stop,
        "restore_to": _restore_target(led, unit_id),
        "progress": progress["path"],
    }


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
    fresh = not ledger_path(args.exec_dir).exists()
    if workdir and fresh:
        _check_exec_dir(args.exec_dir, workdir)
        detected_vcs = checkpoint_detect(workdir)
        if detected_vcs["dirty"] and not getattr(args, "allow_dirty", False):
            raise ToolError("dirty-worktree: uncommitted changes in workdir; ask the engineer (commit/stash or --allow-dirty)", 1)
    led = ledger_init(args.exec_dir, args.plan_path, detected["input_type"], units,
                      source_sha256=source_sha256, accept_drift=getattr(args, "accept_drift", False))
    if workdir and fresh:
        led["workdir"] = os.path.abspath(workdir)
        led["baseline_checkpoint"] = checkpoint_create(workdir, "baseline", led["run_id"])["checkpoint_id"]
        _save(args.exec_dir, led)
    return led


def cmd_ledger_next(args):
    return ledger_next(args.exec_dir)


def cmd_ledger_mark(args):
    return ledger_mark(args.exec_dir, args.unit_id, args.status, error=args.error, checkpoint=args.checkpoint)


def cmd_ledger_status(args):
    return ledger_status(args.exec_dir)


def cmd_unit_begin(args):
    return unit_begin(args.exec_dir)


def cmd_unit_finish(args):
    return unit_finish(args.exec_dir, args.unit_id, args.outcome, error=args.error)


def cmd_checkpoint_detect(args):
    return checkpoint_detect(args.workdir)


def cmd_checkpoint_create(args):
    return checkpoint_create(args.workdir, args.label, args.run_id)


def cmd_checkpoint_restore(args):
    return checkpoint_restore(args.workdir, args.checkpoint_id)


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


def _configure_checkpoint_detect(parser):
    parser.add_argument("workdir")


def _configure_checkpoint_create(parser):
    parser.add_argument("workdir")
    parser.add_argument("label")
    parser.add_argument("--run-id", default="manual")


def _configure_checkpoint_restore(parser):
    parser.add_argument("workdir")
    parser.add_argument("checkpoint_id")


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


_register("checkpoint-create", cmd_checkpoint_create, _configure_checkpoint_create)
_register("checkpoint-detect", cmd_checkpoint_detect, _configure_checkpoint_detect)
_register("checkpoint-prune", cmd_checkpoint_prune, _configure_checkpoint_prune)
_register("checkpoint-restore", cmd_checkpoint_restore, _configure_checkpoint_restore)
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
_register("scope-context", cmd_scope_context, _configure_scope_context)
_register("unit-begin", cmd_unit_begin, _configure_unit_begin)
_register("unit-finish", cmd_unit_finish, _configure_unit_finish)


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
