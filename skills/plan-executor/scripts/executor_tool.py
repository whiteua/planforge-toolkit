import argparse
from datetime import datetime, timezone
import json
from json import JSONDecodeError
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


VALID_WEIGHTS = {"green", "yellow", "red"}
VALID_STATUSES = {"pending", "running", "done", "failed"}
ATTEMPTS_LIMIT = 3
ROADMAP_COLUMNS = 5
_ROADMAP_HEADER_RE = re.compile(r"\|\s*(stage|стадия)\s*\|", re.IGNORECASE)
_TASK_RE = re.compile(
    r"^#{2,4}\s*(?:Task|Задача)\s+(\S+?):\s*(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_SECTION_RE = re.compile(r"^#{1,6}\s*(inputs|outputs|files|входные данные|выходные данные)\s*$", re.IGNORECASE)
_ANY_HEADING_RE = re.compile(r"^#{1,6}\s+")
_CODE_PATH_RE = re.compile(r"`([^`]+\.[A-Za-z0-9]+)`")
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+\.[A-Za-z0-9]+)\]\(([^)]+)\)")
_HEAVY_KEYWORDS = ("refactor", "architecture", "security", "migration", "concurren", "auth")
_STATUS_EMOJI = {"pending": "⏳", "running": "🔄", "done": "✅", "failed": "❌"}


COMMANDS = {}


def _normalize_weight(raw):
    value = str(raw or "").strip().lower()
    if "green" in value or "light" in value or "🟢" in value:
        return "green"
    if "red" in value or "heavy" in value or "🔴" in value:
        return "red"
    if "yellow" in value or "medium" in value or "🟡" in value:
        return "yellow"
    return "yellow"


def validate_ledger(obj):
    errors = []
    required = ["version", "plan_path", "input_type", "created_at", "units"]
    for field in required:
        if field not in obj:
            errors.append(f"missing field: {field}")
    if errors:
        return errors

    if obj["version"] != 1:
        errors.append(f"invalid version: {obj['version']}")
    if obj["input_type"] not in {"staged", "whole"}:
        errors.append(f"invalid input_type: {obj['input_type']}")
    if not isinstance(obj["units"], list):
        errors.append("units must be list")
        return errors

    unit_required = ["id", "title", "weight", "status", "attempts", "depends", "parallel_group", "last_error", "checkpoint_id"]
    for index, unit in enumerate(obj["units"]):
        if not isinstance(unit, dict):
            errors.append(f"unit {index} must be object")
            continue
        for field in unit_required:
            if field not in unit:
                errors.append(f"unit {index} missing field: {field}")
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
    if plan.name.endswith("-stg00-roadmap.md"):
        return {"input_type": "staged", "roadmap": str(plan)}
    candidate = plan.parent / f"{plan.stem}-stg00-roadmap.md"
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
    return [part.strip() for part in value.split(",") if part.strip() and part.strip() not in {"-", "—"}]


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
                "stage": stage,
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
            raise ValueError("cycle detected: " + " -> ".join(cycle))
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
    text = Path(path).read_text(encoding="utf-8")
    rows = parse_roadmap_table(text)
    graph = {row["stage"]: row["depends"] for row in rows}
    detect_cycle(graph)
    return rows


def parse_tasks(plan_path):
    text = Path(plan_path).read_text(encoding="utf-8")
    units = []
    for task_id, title in _TASK_RE.findall(text):
        units.append({"id": f"task-{task_id}", "title": title.strip(), "weight": "yellow"})
    return {"units": units}


def ledger_path(exec_dir):
    return Path(exec_dir) / "state.json"


def _full_unit(unit):
    unit_id = unit.get("id") or unit.get("stage")
    if not unit_id:
        raise ValueError("unit missing id/stage")
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
    }


def build_ledger(plan_path, input_type, units):
    raw_units = units.get("units", []) if isinstance(units, dict) else units
    ledger = {
        "version": 1,
        "plan_path": str(Path(plan_path).resolve()),
        "input_type": input_type,
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "units": [_full_unit(unit) for unit in raw_units],
    }
    errors = validate_ledger(ledger)
    if errors:
        raise ValueError("invalid ledger: " + "; ".join(errors))
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


def _load(exec_dir):
    path = ledger_path(exec_dir)
    try:
        led = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"ledger not found: {path}") from exc
    except JSONDecodeError as exc:
        raise ValueError(f"invalid ledger json: {path}") from exc
    errors = validate_ledger(led)
    if errors:
        raise ValueError("invalid ledger: " + "; ".join(errors))
    return led


def ledger_init(exec_dir, plan_path, input_type, units):
    path = ledger_path(exec_dir)
    if path.exists():
        led = _load(exec_dir)
        changed = False
        for unit in led["units"]:
            if unit["status"] == "running":
                unit["status"] = "pending"
                changed = True
        if changed:
            _save(exec_dir, led)
        return led
    return _save(exec_dir, build_ledger(plan_path, input_type, units))


def _find_unit(led, unit_id):
    for unit in led["units"]:
        if unit["id"] == unit_id:
            return unit
    raise ValueError(f"unknown unit: {unit_id}")


def ledger_mark(exec_dir, unit_id, status, error=None, checkpoint=None):
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid status: {status}")
    led = _load(exec_dir)
    unit = _find_unit(led, unit_id)
    current = unit["status"]

    if current == "done":
        if status == "done":
            return unit
        raise ValueError("done is terminal")
    if status == "running":
        if current == "running":
            raise ValueError("invalid transition: running -> running")
        if current not in {"pending", "failed"}:
            raise ValueError(f"invalid transition: {current} -> running")
        unit["status"] = "running"
        unit["attempts"] += 1
    elif status == "failed":
        if current != "running":
            raise ValueError(f"invalid transition: {current} -> failed")
        old_error = unit.get("last_error")
        unit["previous_error"] = old_error
        unit["status"] = "failed"
        unit["last_error"] = error
        stagnation = old_error is not None and old_error == error
        _save(exec_dir, led)
        result = dict(unit)
        result["stagnation"] = stagnation
        return result
    elif status == "pending":
        if current != "failed":
            raise ValueError(f"invalid transition: {current} -> pending")
        unit["status"] = "pending"
        unit["last_error"] = None
    elif status == "done":
        if current != "running":
            raise ValueError(f"invalid transition: {current} -> done")
        unit["status"] = "done"
        unit["last_error"] = None
        unit["checkpoint_id"] = checkpoint

    _save(exec_dir, led)
    return unit


def ledger_next(exec_dir):
    led = _load(exec_dir)
    units_by_id = {unit["id"]: unit for unit in led["units"]}
    if all(unit["status"] == "done" for unit in led["units"]):
        return {"unit": None, "reason": "all-done"}

    # Priority 1: pending units with satisfied dependencies.
    blocked = False
    for unit in led["units"]:
        if unit["status"] != "pending":
            continue
        if all(units_by_id.get(dep, {}).get("status") == "done" for dep in unit["depends"]):
            return {"unit": unit, "reason": "ready"}
        blocked = True

    # Priority 2: failed units eligible for retry.
    for unit in led["units"]:
        if unit["status"] != "failed":
            continue
        if unit["attempts"] >= ATTEMPTS_LIMIT:
            continue
        prev = unit.get("previous_error")
        if prev is not None and prev == unit["last_error"]:
            continue
        return {"unit": unit, "reason": "retry-available"}

    return {"unit": None, "reason": "blocked" if blocked else "no-pending"}


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


def _git(workdir, *args):
    result = subprocess.run(
        ["git", *args],
        cwd=workdir,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or f"git {' '.join(args)} failed"
        raise RuntimeError(message)
    return result.stdout.strip()


def checkpoint_detect(workdir):
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=workdir,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return {"vcs": "none"}
    if result.returncode == 0 and result.stdout.strip() == "true":
        return {"vcs": "git"}
    return {"vcs": "none"}


def checkpoint_create(workdir, label):
    if checkpoint_detect(workdir)["vcs"] != "git":
        return {"checkpoint_id": None, "vcs": "none"}
    _git(workdir, "add", "-A")
    _git(workdir, "commit", "-m", f"[plan-executor] {label}", "--allow-empty")
    sha = _git(workdir, "rev-parse", "HEAD")
    return {"checkpoint_id": sha, "vcs": "git"}


def checkpoint_restore(workdir, checkpoint_id):
    if checkpoint_detect(workdir)["vcs"] != "git":
        raise RuntimeError("not a git repository")
    _git(workdir, "reset", "--hard", checkpoint_id)
    return {"restored_to": checkpoint_id}


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
    lowered = (task_text or "").lower()
    if any(keyword in lowered for keyword in _HEAVY_KEYWORDS):
        isolation = "subagent"
        model_depth = "deep"
    return {"isolation": isolation, "model_depth": model_depth, "gate_tier": gate_tier}


def _clean_path(value):
    cleaned = value.strip().strip(".,;:")
    if cleaned.startswith("./"):
        cleaned = cleaned[2:]
    return cleaned.replace("\\", "/")


def scope_context(stage_text):
    paths = []
    seen = set()
    in_scope = False
    for line in stage_text.splitlines():
        if _SECTION_RE.match(line.strip()):
            in_scope = True
            continue
        if in_scope and _ANY_HEADING_RE.match(line.strip()):
            in_scope = False
        if not in_scope:
            continue

        candidates = []
        candidates.extend(match.group(1) for match in _MARKDOWN_LINK_RE.finditer(line))
        candidates.extend(match.group(1) for match in _CODE_PATH_RE.finditer(line))
        for candidate in candidates:
            path = _clean_path(candidate)
            if path and path not in seen:
                seen.add(path)
                paths.append(path)
    return {"paths": paths}


def recommend_parallel(units):
    grouped = {}
    for unit in units:
        group = unit.get("parallel_group")
        if not group:
            continue
        grouped.setdefault(group, []).append(unit["id"])
    groups = {group: ids for group, ids in grouped.items() if len(ids) > 1}
    if not groups:
        return {"groups": {}, "recommendation": None}
    names = ", ".join(sorted(groups))
    return {"groups": groups, "recommendation": f"Run parallel groups manually where useful: {names}"}


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
        last_error = unit.get("last_error") or ""
        lines.append(f"| {unit['id']} | {status_text} | {unit['attempts']} | {unit['weight']} | {last_error} |")
    path = Path(exec_dir).resolve() / "progress.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"path": str(path)}


def cmd_detect_input(args):
    return detect_input(args.plan_path, force_whole=args.whole)


def cmd_parse_roadmap(args):
    return parse_roadmap(args.roadmap_path)


def cmd_parse_tasks(args):
    return parse_tasks(args.plan_path)


def cmd_ledger_init(args):
    detected = detect_input(args.plan_path, force_whole=args.whole)
    if detected["input_type"] == "staged":
        units = parse_roadmap(detected["roadmap"])
    else:
        units = parse_tasks(args.plan_path)
    return ledger_init(args.exec_dir, args.plan_path, detected["input_type"], units)


def cmd_ledger_next(args):
    return ledger_next(args.exec_dir)


def cmd_ledger_mark(args):
    return ledger_mark(args.exec_dir, args.unit_id, args.status, error=args.error, checkpoint=args.checkpoint)


def cmd_ledger_status(args):
    return ledger_status(args.exec_dir)


def cmd_checkpoint_detect(args):
    return checkpoint_detect(args.workdir)


def cmd_checkpoint_create(args):
    return checkpoint_create(args.workdir, args.label)


def cmd_checkpoint_restore(args):
    return checkpoint_restore(args.workdir, args.checkpoint_id)


def cmd_recommend_gate(args):
    return recommend_gate(args.weight)


def cmd_recommend_strategy(args):
    return recommend_strategy(args.weight, args.task_text)


def cmd_scope_context(args):
    text = Path(args.stage_path).read_text(encoding="utf-8")
    return scope_context(text)


def cmd_recommend_parallel(args):
    return recommend_parallel(_load(args.exec_dir)["units"])


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


def _configure_checkpoint_detect(parser):
    parser.add_argument("workdir")


def _configure_checkpoint_create(parser):
    parser.add_argument("workdir")
    parser.add_argument("label")


def _configure_checkpoint_restore(parser):
    parser.add_argument("workdir")
    parser.add_argument("checkpoint_id")


def _configure_recommend_gate(parser):
    parser.add_argument("weight")


def _configure_recommend_strategy(parser):
    parser.add_argument("weight")
    parser.add_argument("--task-text", default="")


def _configure_scope_context(parser):
    parser.add_argument("stage_path")


def _configure_recommend_parallel(parser):
    parser.add_argument("exec_dir")


def _configure_render_progress(parser):
    parser.add_argument("exec_dir")


_register("checkpoint-create", cmd_checkpoint_create, _configure_checkpoint_create)
_register("checkpoint-detect", cmd_checkpoint_detect, _configure_checkpoint_detect)
_register("checkpoint-restore", cmd_checkpoint_restore, _configure_checkpoint_restore)
_register("detect-input", cmd_detect_input, _configure_detect_input)
_register("ledger-init", cmd_ledger_init, _configure_ledger_init)
_register("ledger-mark", cmd_ledger_mark, _configure_ledger_mark)
_register("ledger-next", cmd_ledger_next, _configure_ledger_next)
_register("ledger-status", cmd_ledger_status, _configure_ledger_status)
_register("parse-roadmap", cmd_parse_roadmap, _configure_parse_roadmap)
_register("parse-tasks", cmd_parse_tasks, _configure_parse_tasks)
_register("recommend-gate", cmd_recommend_gate, _configure_recommend_gate)
_register("recommend-parallel", cmd_recommend_parallel, _configure_recommend_parallel)
_register("recommend-strategy", cmd_recommend_strategy, _configure_recommend_strategy)
_register("render-progress", cmd_render_progress, _configure_render_progress)
_register("scope-context", cmd_scope_context, _configure_scope_context)


def build_parser():
    parser = argparse.ArgumentParser(prog="executor_tool.py")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in sorted(COMMANDS):
        handler, configure = COMMANDS[name]
        subparser = subparsers.add_parser(name)
        configure(subparser)
        subparser.set_defaults(handler=handler)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = args.handler(args)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
