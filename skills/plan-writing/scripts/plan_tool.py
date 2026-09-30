#!/usr/bin/env python3
"""Deterministic helper for the plan-writing skill.

- plan-path: derives the implementation plan path from a spec path.
- plan-check: verifies a written plan against the plan format contract
  that plan-executor and plan-resolver parse (header fields, task headings,
  unique ids, Files / steps / done-state per tier, no commit steps, no
  placeholders), optionally checking Modify paths against the workspace.

Stdlib only. Python 3.8+.

Commands:
  plan-path  <spec.md>
  plan-check <plan.md> [--root DIR]

Exit codes: 0 ok, 1 contract violation, 2 usage or I/O error.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple


TIERS = ("Quick", "Standard", "Deep")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
TASK_HEADING_RE = re.compile(r"^#{2,4}\s+(?:Task|Задача)\s+(?P<id>\S+?)\s*:\s*(?P<title>\S.*?)\s*$")
TASKISH_HEADING_RE = re.compile(r"^#{2,4}\s+(?:Task|Задача)\b", re.IGNORECASE)
OLD_CHECKPOINT_RE = re.compile(r"^#{2,4}\s+Phase Checkpoint\b", re.IGNORECASE)
TASK_ID_RE = re.compile(r"^\d+(?:\.\d+)*$")
TOP_HEADING_RE = re.compile(r"^#{1,2}\s")
HEADER_FIELD_RE = re.compile(r"^\*\*(?P<name>Spec|Tier):\*\*\s*(?P<value>.*?)\s*$")
STEP_RE = re.compile(r"^\s*- \[ \] \*\*Step \d+")
FILES_RE = re.compile(r"^\*\*Files:\*\*")
FILE_LINE_RE = re.compile(r"^\s*- (?P<kind>Create|Modify|Test):\s*(?P<rest>.*)$")
FILE_PATH_RE = re.compile(r"^`(?P<path>[^`:]+)(?::(?P<start>\d+)(?:-(?P<end>\d+))?)?`")
DONE_WHEN_RE = re.compile(r"^(?:\*\*)?Done when:(?:\*\*)?\s*\S")
PRE_RE = re.compile(r"^\*\*Preconditions:\*\*")
POST_RE = re.compile(r"^\*\*Postconditions:\*\*")
COMMIT_RE = re.compile(r"\bgit\s+commit\b")
# A backticked path with a directory separator, outside Files lines: `src/app/x.py`.
REF_PATH_RE = re.compile(r"`(?P<path>[^`\s:]+/[^`\s:]+\.[A-Za-z0-9]+)(?::\d+(?:-\d+)?)?`")
PLACEHOLDER_RE = re.compile(
    r"\b(TBD|TODO|FIXME)\b|implement later|fill in details|similar to task \d+"
    r"|add appropriate error handling|handle edge cases",
    re.IGNORECASE,
)
CHECKPOINT_TITLE_RE = re.compile(r"^Checkpoint\b", re.IGNORECASE)
MAX_CODE_LINES = 100


class InputError(Exception):
    """Unreadable input (exit 2)."""


def _read(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            return fh.read()
    except OSError as exc:
        raise InputError(f"cannot read {path}: {exc}") from exc


def plan_path(spec_path: str) -> Dict[str, str]:
    """`<X>-spec.md` -> `<X>-impl.md`; `spec.md` -> `impl.md`; other -> `<name>-impl.md`."""
    directory, name = os.path.split(spec_path)
    stem = os.path.splitext(name)[0]
    if stem.lower() == "spec":
        root = ""
    elif stem.lower().endswith("-spec"):
        root = stem[: -len("-spec")]
    else:
        root = stem
    impl_name = f"{root}-impl.md" if root else "impl.md"
    return {"plan_root": root, "impl_path": os.path.join(directory, impl_name).replace("\\", "/")}


def _count_lines(path: str) -> int:
    with open(path, "rb") as fh:
        data = fh.read()
    if not data:
        return 0
    return data.count(b"\n") + (0 if data.endswith(b"\n") else 1)


def _split_lines(text: str) -> List[Tuple[int, str, bool]]:
    """(line number, line, inside code fence). Fence lines themselves count as inside."""
    result = []
    in_fence = False
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip()
        if FENCE_RE.match(line):
            result.append((number, line, True))
            in_fence = not in_fence
            continue
        result.append((number, line, in_fence))
    return result


def check_plan(text: str, root: Optional[str] = None) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []
    lines = _split_lines(text)

    # Header: everything before the first task heading.
    first_task_line = next(
        (n for n, line, fenced in lines if not fenced and TASK_HEADING_RE.match(line)), None
    )
    header = {}
    for number, line, fenced in lines:
        if first_task_line is not None and number >= first_task_line:
            break
        match = None if fenced else HEADER_FIELD_RE.match(line)
        if match:
            header.setdefault(match.group("name"), match.group("value"))
    if not any(not fenced and line.startswith("# ") for _, line, fenced in lines):
        errors.append("missing plan title ('# <Feature> Implementation Plan')")
    spec = header.get("Spec") or None
    tier = header.get("Tier") or None
    if not spec:
        errors.append("missing header field '**Spec:** <path>'")
    if not tier:
        errors.append("missing header field '**Tier:** Quick|Standard|Deep'")
    elif tier not in TIERS:
        errors.append(f"unknown tier '{tier}' (allowed: {', '.join(TIERS)})")

    # Task boundaries.
    tasks: List[Dict[str, Any]] = []
    for number, line, fenced in lines:
        if fenced:
            continue
        match = TASK_HEADING_RE.match(line)
        if match:
            task_id = match.group("id")
            title = match.group("title")
            if not TASK_ID_RE.match(task_id):
                errors.append(f"line {number}: task id '{task_id}' must be N or N.M")
            tasks.append({
                "id": task_id,
                "title": title,
                "line": number,
                "checkpoint": bool(CHECKPOINT_TITLE_RE.match(title)),
            })
        elif OLD_CHECKPOINT_RE.match(line):
            errors.append(f"line {number}: use '### Task N: Checkpoint — <what it proves>' instead of 'Phase Checkpoint'")
        elif TASKISH_HEADING_RE.match(line):
            errors.append(f"line {number}: malformed task heading, expected '### Task N: <title>': {line}")
    if not tasks:
        errors.append("no task headings found ('### Task N: <title>')")

    seen: Dict[str, int] = {}
    for task in tasks:
        if task["id"] in seen:
            errors.append(f"line {task['line']}: duplicate task id {task['id']} (first at line {seen[task['id']]})")
        else:
            seen[task["id"]] = task["line"]

    if tier == "Quick" and any(task["checkpoint"] for task in tasks):
        errors.append("checkpoint tasks are not used on the Quick tier")

    # Placeholders anywhere outside code fences; commit commands in code fences or step lines
    # (prose such as "do not run git commit" is fine).
    for number, line, fenced in lines:
        if not fenced and PLACEHOLDER_RE.search(line):
            errors.append(f"line {number}: placeholder: {line.strip()}")
        if COMMIT_RE.search(line) and (fenced or STEP_RE.match(line)):
            errors.append(f"line {number}: commit step; no skill commits, the plan must not commit")

    # Per-task body checks. `created` grows task by task: a later task may Modify or Test
    # a file an earlier task creates.
    line_counts: Dict[str, Optional[int]] = {}
    created: set = set()
    for index, task in enumerate(tasks):
        start = task["line"]
        end = tasks[index + 1]["line"] if index + 1 < len(tasks) else None
        body = [
            (n, line, fenced) for n, line, fenced in lines
            if n > start and (end is None or n < end)
        ]
        # A top-level heading ends the task (e.g. a closing section).
        for position, (n, line, fenced) in enumerate(body):
            if not fenced and TOP_HEADING_RE.match(line):
                body = body[:position]
                break
        plain = [line for _, line, fenced in body if not fenced]
        label = f"Task {task['id']}"

        has_files = any(FILES_RE.match(line) for line in plain)
        if not has_files and not task["checkpoint"]:
            errors.append(f"{label}: missing '**Files:**' block")
        if not any(STEP_RE.match(line) for line in plain):
            errors.append(f"{label}: no steps ('- [ ] **Step N: ...**')")

        has_done = any(DONE_WHEN_RE.match(line) for line in plain)
        has_pre = any(PRE_RE.match(line) for line in plain)
        has_post = any(POST_RE.match(line) for line in plain)
        if tier == "Quick" or task["checkpoint"]:
            if not (has_done or has_post):
                errors.append(f"{label}: missing done-state ('Done when: <observable result>')")
        elif tier in ("Standard", "Deep"):
            if not has_pre:
                errors.append(f"{label}: missing '**Preconditions:**' ({tier} tier)")
            if not has_post:
                errors.append(f"{label}: missing '**Postconditions:**' ({tier} tier)")

        for n, line, fenced in body:
            if fenced:
                continue
            file_match = FILE_LINE_RE.match(line)
            if not file_match:
                continue
            path_match = FILE_PATH_RE.match(file_match.group("rest").strip())
            if not path_match:
                errors.append(f"line {n}: {file_match.group('kind')} path must be in backticks: {line.strip()}")
                continue
            kind = file_match.group("kind")
            rel = path_match.group("path").strip()
            if kind == "Create":
                created.add(rel)
            if root is None:
                continue
            full = os.path.join(root, rel)
            exists = os.path.isfile(full)
            if kind == "Create":
                if exists:
                    warnings.append(f"line {n}: Create target already exists under root: {rel} (use Modify:)")
                continue
            if kind == "Test":
                if not exists and rel not in created:
                    warnings.append(f"line {n}: Test target not found under root and not created by an earlier task: {rel}")
                continue
            if rel not in line_counts:
                line_counts[rel] = _count_lines(full) if exists else None
            total = line_counts[rel]
            if total is None:
                if rel not in created:
                    warnings.append(f"line {n}: Modify target not found under root: {rel}")
                continue
            last = path_match.group("end") or path_match.group("start")
            if last and int(last) > total:
                warnings.append(f"line {n}: line range beyond end of {rel} ({total} lines)")

        if root is not None:
            # Paths cited in prose must exist or be created by the plan: a plan that names
            # files that are not there is guessing about the codebase.
            for n, line, fenced in body:
                if fenced or FILE_LINE_RE.match(line):
                    continue
                for ref in REF_PATH_RE.finditer(line):
                    rel = ref.group("path")
                    if rel in created or os.path.exists(os.path.join(root, rel)):
                        continue
                    warnings.append(f"line {n}: referenced path not found under root: {rel}")

        code_lines = sum(1 for _, line, fenced in body if fenced and not FENCE_RE.match(line))
        if code_lines > MAX_CODE_LINES:
            warnings.append(f"{label}: {code_lines} lines of code in steps; check the 100-lines-of-new-code limit")

    return {
        "ok": not errors,
        "spec": spec,
        "tier": tier,
        "tasks": [{k: task[k] for k in ("id", "title", "checkpoint")} for task in tasks],
        "errors": errors,
        "warnings": warnings,
    }


def cmd_plan_path(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    return 0, dict(plan_path(args.spec), ok=True)


def cmd_plan_check(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    if args.root is not None and not os.path.isdir(args.root):
        raise InputError(f"root is not a directory: {args.root}")
    result = check_plan(_read(args.plan), args.root)
    return (0 if result["ok"] else 1), result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command")

    p_path = sub.add_parser("plan-path", help="derive the implementation plan path from a spec path")
    p_path.add_argument("spec")
    p_path.set_defaults(func=cmd_plan_path)

    p_check = sub.add_parser("plan-check", help="check a plan against the plan format contract")
    p_check.add_argument("plan")
    p_check.add_argument("--root", help="workspace root for Modify path checks")
    p_check.set_defaults(func=cmd_plan_check)
    return parser


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
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
