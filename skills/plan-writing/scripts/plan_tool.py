#!/usr/bin/env python3
"""Deterministic helper for the plan-writing skill.

- plan-path: derives the implementation plan path from a spec path.
- plan-check: verifies a written plan against the plan format contract
  that plan-executor and plan-resolver parse (header fields, task headings,
  unique ids, Files / steps / done-state per tier, no commit steps, no
  placeholders), optionally checking Modify paths against the workspace.
  Also returns `journal`: the chain journal path when that file exists, else null.

Stdlib only. Python 3.8+.

Commands:
  plan-path  <spec.md>
  plan-check <plan.md> [--root DIR]

Exit codes: 0 ok, 1 contract violation, 2 usage or I/O error.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
from pathlib import Path
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
# External systems a plan may touch. Header block:
#   **Environments:**
#   - `dev_db` (test) — "user's permission, quoted verbatim" (2026-09-30)
# Task line:  **External:** `dev_db` — what the task does there
ENVIRONMENTS_RE = re.compile(r"^\*\*Environments:\*\*\s*$")
ENV_ENTRY_RE = re.compile(r"^\s*[-*]\s+`(?P<name>[^`]+)`(?P<rest>.*)$")
ENV_QUOTE_RE = re.compile(r"\"[^\"]+\"|«[^»]+»|“[^”]+”")
EXTERNAL_RE = re.compile(r"^\*\*External:\*\*\s*(?P<rest>.*)$")
# Access after the name: **External:** `dev_db` (write) — what the task does there
EXTERNAL_ACCESS_RE = re.compile(r"^`[^`]+`\s*\((?P<access>read|write)\)")
BACKTICKED_RE = re.compile(r"`([^`]+)`")
MAX_CODE_LINES = 100
MAX_CODE_LINES_ERROR = 150
# Task line:  **Size:** 140 lines — why the task cannot be split
SIZE_PREFIX_RE = re.compile(r"^\*\*Size:\*\*")
SIZE_RE = re.compile(r"^\*\*Size:\*\*\s*(\d+)\s+lines\s*[—-]\s*\S")
# Same Cyrillic range and threshold as brainstorm_tool.py, executor_tool.py, splitter_tool.py
# and resolver_tool.py.
CYRILLIC_RE = re.compile("[Ѐ-ӿ]")
LANG_THRESHOLD = 0.05


class InputError(Exception):
    """Unreadable input (exit 2)."""


SETTINGS_MISSING = "settings-source-missing"


def _load_brainstorm_tool():
    path = Path(__file__).resolve().parents[2] / "plan-brainstorming" / "scripts" / "brainstorm_tool.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("brainstorm_tool", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _plan_settings(plan_path: Optional[str]) -> Tuple[Optional[Dict[str, Any]], List[str], List[str]]:
    """Chain settings by the shared reading rule: the plan header if it has settings, else
    the spec at **Spec:** (brainstorm_tool.resolve_settings). Returns (settings, errors,
    warnings). Text-only calls (no path) resolve nothing. A missing settings source is a
    warning here; check_plan makes it an error when the plan has External lines."""
    if plan_path is None:
        return None, [], []
    tool = _load_brainstorm_tool()
    if tool is None:
        return None, [], ["plan-brainstorming not installed alongside"]
    try:
        settings = tool.resolve_settings(plan_path)
    except tool.InputError as exc:  # the spec at **Spec:** cannot be read (not UTF-8): a JSON error, exit 2
        raise InputError(str(exc)) from exc
    errors = [f"settings: {e}" for e in settings["errors"] if not e.startswith(SETTINGS_MISSING)]
    warnings = [f"settings: {e}" for e in settings["errors"] if e.startswith(SETTINGS_MISSING)]
    warnings.extend(f"settings: {w}" for w in settings["warnings"])
    return settings, errors, warnings


def _journal_for(plan_path: str) -> Optional[str]:
    """The chain journal of the plan (brainstorm_tool.journal_path_for) when that file exists.
    None when it does not exist yet, when plan-brainstorming is not installed alongside or
    predates the journal, and when the path cannot be resolved (e.g. the spec at **Spec:** is
    missing): the journal is optional and never fails plan-check."""
    finder = getattr(_load_brainstorm_tool(), "journal_path_for", None)
    if finder is None:
        return None
    try:
        found = finder(plan_path)
    except Exception:  # the module's InputError or a read error: no journal, not a failure
        return None
    return found["journal"] if found.get("exists") else None


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


def detect_lang_text(text: str) -> str:
    """`ru` when more than 5% of the letters are Cyrillic, otherwise `en` (no letters -> `en`)."""
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return "en"
    cyrillic = sum(1 for ch in letters if CYRILLIC_RE.match(ch))
    return "ru" if cyrillic / len(letters) > LANG_THRESHOLD else "en"


def check_plan(text: str, root: Optional[str] = None, plan_path: Optional[str] = None) -> Dict[str, Any]:
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
    # Environments block of the header: every entry names an environment and quotes the
    # user's permission. An environment without a quote is not permitted.
    environments: List[str] = []
    in_env_block = False
    for number, line, fenced in lines:
        if first_task_line is not None and number >= first_task_line:
            break
        if fenced:
            continue
        if ENVIRONMENTS_RE.match(line):
            in_env_block = True
            continue
        if not in_env_block:
            continue
        entry = ENV_ENTRY_RE.match(line)
        if entry:
            environments.append(entry.group("name"))
            if not ENV_QUOTE_RE.search(entry.group("rest")):
                errors.append(
                    f"line {number}: environment `{entry.group('name')}` has no quoted user permission "
                    "(quote the user's words verbatim)"
                )
        elif line.strip() and not line.startswith(" "):
            in_env_block = False
    # Chain settings by the shared reading rule (plan header, else the spec at **Spec:**).
    # Their environments join the header's list; `rights` maps a name to its read/write.
    settings, settings_errors, settings_warnings = _plan_settings(plan_path)
    errors.extend(settings_errors)
    warnings.extend(settings_warnings)
    rights: Dict[str, Dict[str, Any]] = {}
    for env in (settings or {}).get("environments", []):
        rights[env["name"]] = env
        if env["name"] not in environments:
            environments.append(env["name"])

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
    oversized: List[str] = []
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

        # External systems: a task that names a permitted environment anywhere in its body
        # (commands included) must declare it, and may declare only permitted environments.
        declared: List[str] = []
        for n, line, fenced in body:
            external = None if fenced else EXTERNAL_RE.match(line)
            if external:
                names = BACKTICKED_RE.findall(external.group("rest"))
                if not names:
                    errors.append(f"line {n}: '**External:**' must name the environment in backticks")
                for name in names[:1]:
                    declared.append(name)
                    if name not in environments:
                        errors.append(
                            f"line {n}: environment `{name}` is not listed in the settings "
                            "(plan header '**Environments:**' or the spec's '> Environment:' lines)"
                        )
                    env = rights.get(name)
                    if env is None:
                        continue
                    access_match = EXTERNAL_ACCESS_RE.match(external.group("rest").strip())
                    access = access_match.group("access") if access_match else None
                    if access is None:
                        if env.get("read") or env.get("write"):
                            errors.append(
                                f"line {n}: '**External:** `{name}`' needs the access type (read) or (write): "
                                "the environment has read/write rights"
                            )
                        else:
                            warnings.append(f"line {n}: '**External:** `{name}`' has no access type (read) or (write)")
                    elif env.get(access) == "deny":
                        errors.append(f"line {n}: `{name}` ({access}) is not allowed: {access}=deny in the settings")
        task["external"] = declared
        body_text = "\n".join(line for _, line, _ in body)
        for name in environments:
            if name not in declared and re.search(r"(?<![\w-])" + re.escape(name) + r"(?![\w-])", body_text):
                errors.append(f"{label}: uses environment `{name}` without a '**External:** `{name}` — …' line")

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

        # Size: a task over the limit is split or justified with '**Size:** <N> lines — <reason>'.
        sized = False
        for n, line, fenced in body:
            if fenced or not SIZE_PREFIX_RE.match(line):
                continue
            if SIZE_RE.match(line):
                sized = True
            else:
                errors.append(f"line {n}: malformed size line, expected '**Size:** <N> lines — <reason>': {line.strip()}")
        if sized:
            oversized.append(task["id"])
        code_lines = sum(1 for _, line, fenced in body if fenced and not FENCE_RE.match(line))
        if code_lines > MAX_CODE_LINES_ERROR and not sized:
            errors.append(
                f"{label}: {code_lines} lines of code (limit {MAX_CODE_LINES}, error above {MAX_CODE_LINES_ERROR}) "
                "without a '**Size:** <N> lines — <reason>' line"
            )
        elif code_lines > MAX_CODE_LINES and not sized:
            warnings.append(f"{label}: {code_lines} lines of code in steps; check the 100-lines-of-new-code limit")

    # Dialogue language: the plan text outside code fences.
    lang = detect_lang_text("\n".join(line for _, line, fenced in lines if not fenced))
    # External lines need settings: without the spec and without header settings nothing
    # says which environments the user permitted. Same source as the executor (Task 43):
    # resolve_settings could not read its source and found no environments.
    settings_missing = settings is not None and not settings["environments"] and any(
        e.startswith(SETTINGS_MISSING) for e in settings["errors"]
    )
    if settings_missing and any(task["external"] for task in tasks):
        errors.append(
            "plan has '**External:**' lines but settings are unavailable: the spec at '**Spec:**' "
            "cannot be read and the plan header has no settings"
        )
    return {
        "ok": not errors,
        "spec": spec,
        "tier": tier,
        "lang": lang,
        "environments": environments,
        "tasks": [{k: task.get(k, []) for k in ("id", "title", "checkpoint", "external")} for task in tasks],
        "settings": settings,
        "task_count": len(tasks),
        "plan_bytes": len(text.encode("utf-8")),
        "errors": errors,
        "warnings": warnings,
        "oversized": oversized,
    }


def cmd_plan_path(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    return 0, dict(plan_path(args.spec), ok=True)


def cmd_plan_check(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    if args.root is not None and not os.path.isdir(args.root):
        raise InputError(f"root is not a directory: {args.root}")
    result = check_plan(_read(args.plan), args.root, args.plan)
    result["journal"] = _journal_for(args.plan)
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
