#!/usr/bin/env python3
"""Utility commands for the plan-resolver skill.

Stdlib only. Python 3.8+.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import random
import re
import string
import sys
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


ALLOWED_PLAN_EXTENSIONS = {".md", ".markdown", ".txt", ".text"}
REPORT_RE = re.compile(r"^(?P<base>.+)-report-(?P<n>\d+)(?P<final>-final)?\.md$", re.IGNORECASE)
HEX64_RE = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)
ISO_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
ISSUE_RE = re.compile(
    r"(?ms)^\s*(?P<num>\d+)\)\s*(?:Ошибка|Error)\s*(?P<label_num>\d+)?\s*:\s*(?P<head>.*?)\n"
    r"(?P<body>.*?)(?=^\s*\d+\)\s*(?:Ошибка|Error)\s*\d*\s*:|^##\s+|\Z)"
)
FIELD_RE_TEMPLATE = r"^- \*\*{label}\*\*:\s*(?P<body>.*?)(?=\n- \*\*|\n\s*\d+\)\s*(?:Ошибка|Error)|\n##\s+|\Z)"
PLAN_HEADING_RE = re.compile(r"^#{1,6}\s+(?P<rest>.*\S)\s*$")
PLAN_BULLET_RE = re.compile(r"^\s*[-*+]\s+(?:\[[ xX]\]\s+)?(?P<rest>.*\S)\s*$")
PLAN_NUMBERED_RE = re.compile(r"^\s*(?P<id>\d+(?:\.\d+)*)[.)]\s+\S")
PLAN_TABLE_STAGE_ID_RE = re.compile(r"^\s*\|\s*(?P<id>stg\d+)\s*\|", re.IGNORECASE)
PLAN_LEADING_ID_RE = re.compile(r"^(?P<id>\d+(?:\.\d+)*|stg\d+)[.):]?\s+\S", re.IGNORECASE)
PLAN_STAGE_ID_RE = re.compile(r"\bstg\d+\b", re.IGNORECASE)
ANCHOR_RE = re.compile(r"[^\s:#]+#L\d+(?:-L?\d+)?", re.IGNORECASE)
CONFIDENCE_RE = re.compile(r"confidence\s*[:=]\s*(?P<level>high|medium|low)", re.IGNORECASE)
AMBIGUOUS_RE = re.compile(r"\bambiguous\b", re.IGNORECASE)
EVIDENCE_ANCHOR_RE = re.compile(r"evidence_anchor\s*[:=]\s*(?P<anchor>\S+)", re.IGNORECASE)


def confidence_level(text_blob: str) -> str:
    match = CONFIDENCE_RE.search(text_blob or "")
    return match.group("level").lower() if match else ""

FIXED_EXCLUDED_DIRS = {
    "node_modules",
    "__pycache__",
    "dist",
    "build",
    "target",
    "out",
    "bin",
    "obj",
    ".next",
    ".gradle",
    ".venv",
    "venv",
}
FIXED_EXCLUDED_PREFIXES = {".git/objects"}
MAX_FINGERPRINT_FILES = 200_000
VALID_TASK_MARKERS = {"✅", "⭕️", "⭕", "⚠️", "⚠", "‼️", "‼", "not-applicable"}
CLOSED_TASK_MARKERS = {"✅", "not-applicable"}
ALLOWED_ISSUE_EMOJI = {"✅", "⭕️", "⭕", "⚠️", "⚠", "‼️", "‼"}
VALID_LEVELS = {"critical", "high", "medium", "low"}
VALID_ISSUE_STATUSES = {"fixed", "fixed-with-errors", "not-fixed", "regressed"}
VALID_LANGUAGES = {"ru", "en"}
REQUIRED_HEADER_FIELDS = (
    "master_plan_path",
    "master_plan_sha256",
    "master_plan_size",
    "audited_at",
    "audit_iteration",
    "consecutive_open_invocations",
    "previous_report_path",
    "previous_report_sha256",
    "language",
)
SECTION_ALIASES = {
    "title": ("# Отчет о выполнении плана", "# Plan Implementation Report"),
    "stages": ("## Основные стадии плана", "## Plan Stages"),
    "issues": ("## Список ошибок", "## Issues"),
    "task": ("## Задача", "## Task"),
    "context": ("## Дополнительный контекст", "## Additional Context"),
}


class ToolError(Exception):
    def __init__(self, message: str, code: int = 2) -> None:
        super().__init__(message)
        self.code = code


def print_json(data: object) -> None:
    print(json.dumps(data, ensure_ascii=True, sort_keys=True))


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def write_json_file(path: str, data: object) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")


def posix_rel(path: str, root: str) -> str:
    return os.path.relpath(path, root).replace(os.sep, "/")


def ensure_inside(root: str, raw_path: str) -> Tuple[str, str]:
    root_abs = os.path.abspath(root)
    candidate = raw_path if os.path.isabs(raw_path) else os.path.join(root_abs, raw_path)
    candidate_abs = os.path.abspath(candidate)
    try:
        common = os.path.commonpath([root_abs, candidate_abs])
    except ValueError as exc:
        raise ToolError(f"path is outside workspace: {raw_path}") from exc
    if common != root_abs:
        raise ToolError(f"path is outside workspace: {raw_path}")
    return candidate_abs, posix_rel(candidate_abs, root_abs)


def is_posix_relative(value: str) -> bool:
    if not value or value == "null":
        return False
    if "\\" in value or value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        return False
    parts = value.split("/")
    return all(part not in {"", ".", ".."} for part in parts)


def parse_report_filename(filename: str) -> Optional[Dict[str, object]]:
    match = REPORT_RE.match(filename)
    if not match:
        return None
    return {
        "base": match.group("base"),
        "n": int(match.group("n")),
        "final": bool(match.group("final")),
    }


CYRILLIC_RATIO_THRESHOLD = 0.05


def detect_plan_language(plan_path: str) -> str:
    """Ecosystem convention (see plan-iterative-revision invariant #9):
    cyrillic_ratio > 0.05 -> ru, otherwise en. Unreadable/empty -> ru."""
    try:
        with open(plan_path, encoding="utf-8", errors="ignore") as fh:
            text = fh.read()
    except OSError:
        return "ru"
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return "ru"
    cyrillic = sum(1 for ch in letters if "\u0400" <= ch <= "\u04ff")
    return "ru" if cyrillic / len(letters) > CYRILLIC_RATIO_THRESHOLD else "en"


def validate_plan_path(path_abs: str, role: str, errors: List[str]) -> None:
    if not os.path.exists(path_abs):
        errors.append(f"bootstrap-missing-{role}: {path_abs}")
        return
    if not os.path.isfile(path_abs):
        errors.append(f"bootstrap-not-file-{role}: {path_abs}")
        return
    ext = os.path.splitext(path_abs)[1].lower()
    if ext not in ALLOWED_PLAN_EXTENSIONS:
        errors.append(f"bootstrap-bad-extension-{role}: {path_abs}")


def cmd_bootstrap(args: argparse.Namespace) -> int:
    workspace_root = os.path.abspath(args.workspace_root)
    errors: List[str] = []
    warnings: List[str] = []
    if not os.path.isdir(workspace_root):
        print_json({"valid": False, "errors": [f"bootstrap-missing-workspace: {workspace_root}"]})
        return 2

    try:
        master_abs, master_rel = ensure_inside(workspace_root, args.plan)
    except ToolError as exc:
        print_json({"valid": False, "errors": [str(exc)]})
        return exc.code

    validate_plan_path(master_abs, "master", errors)
    master_name = os.path.basename(master_abs)
    master_base, _ = os.path.splitext(master_name)
    if parse_report_filename(master_name):
        errors.append("bootstrap-bad-master: first plans-list item is a report")

    report_items: List[Dict[str, object]] = []
    seen_numbers: Dict[int, str] = {}
    plan_dir_abs = os.path.dirname(master_abs)
    plan_dir_rel = posix_rel(plan_dir_abs, workspace_root)

    for raw_report in args.reports:
        try:
            report_abs, report_rel = ensure_inside(workspace_root, raw_report)
        except ToolError as exc:
            errors.append(str(exc))
            continue
        validate_plan_path(report_abs, "report", errors)
        parsed = parse_report_filename(os.path.basename(report_abs))
        if not parsed:
            errors.append(f"bootstrap-bad-report-name: {report_rel}")
            continue
        if os.path.dirname(report_abs) != plan_dir_abs:
            errors.append(f"bootstrap-report-outside-plan-dir: {report_rel}")
        if str(parsed["base"]).lower() != master_base.lower():
            errors.append(f"bootstrap-base-mismatch: {report_rel}")
        n = int(parsed["n"])
        if n in seen_numbers:
            errors.append(f"bootstrap-duplicate-report: {n} ({seen_numbers[n]}, {report_rel})")
        seen_numbers[n] = report_rel
        report_items.append(
            {
                "n": n,
                "path": report_rel,
                "abs_path": report_abs,
                "final": bool(parsed["final"]),
                "sha256": sha256_file(report_abs) if os.path.isfile(report_abs) else None,
            }
        )

    report_items.sort(key=lambda item: int(item["n"]))
    numbers = [int(item["n"]) for item in report_items]
    missing = [expected for expected in range(1, len(numbers) + 1) if expected not in numbers]
    if missing:
        errors.append("bootstrap-gap-in-reports: missing " + ", ".join(str(n) for n in missing))

    if errors:
        print_json({"valid": False, "errors": errors, "warnings": warnings})
        return 2

    last_report = report_items[-1] if report_items else None
    if last_report and bool(last_report["final"]):
        print_json(
            {
                "valid": True,
                "closed": True,
                "message": "план уже закрыт; новые проходы не требуются",
                "workspace_root": workspace_root,
                "master_plan": master_rel,
                "last_report": {k: v for k, v in last_report.items() if k != "abs_path"},
                "errors": [],
                "warnings": warnings,
            }
        )
        return 64

    next_n = (max(numbers) + 1) if numbers else 1
    next_open_name = f"{master_base}-report-{next_n}.md"
    next_final_name = f"{master_base}-report-{next_n}-final.md"
    result = {
        "valid": True,
        "closed": False,
        "workspace_root": workspace_root,
        "master_plan": master_rel,
        "master_plan_abs": master_abs,
        "master_plan_sha256": sha256_file(master_abs),
        "master_plan_size": os.path.getsize(master_abs),
        "plan_dir": plan_dir_rel if plan_dir_rel != "." else ".",
        "plan_dir_abs": plan_dir_abs,
        "reports": [{k: v for k, v in item.items() if k != "abs_path"} for item in report_items],
        "last_report": None if last_report is None else {k: v for k, v in last_report.items() if k != "abs_path"},
        "next_n": next_n,
        "next_open_name": next_open_name,
        "next_final_name": next_final_name,
        "next_open_path": posix_rel(os.path.join(plan_dir_abs, next_open_name), workspace_root),
        "next_final_path": posix_rel(os.path.join(plan_dir_abs, next_final_name), workspace_root),
        "language": detect_plan_language(master_abs),
        "pass_type": "first" if not report_items else "subsequent",
        "errors": [],
        "warnings": warnings,
    }
    print_json(result)
    return 0


def safe_join_name(directory: str, name: str) -> str:
    if os.path.basename(name) != name or name in {"", ".", ".."}:
        raise ToolError(f"target name must be a basename: {name}", 2)
    return os.path.join(directory, name)


def cmd_preflight(args: argparse.Namespace) -> int:
    plan_dir = os.path.abspath(args.plan_dir)
    errors: List[str] = []
    existing: List[str] = []
    checks = {"directory_exists": False, "probe_create_delete": False, "targets_absent": False}

    if not os.path.isdir(plan_dir):
        errors.append(f"preflight-missing-plan-dir: {plan_dir}")
    else:
        checks["directory_exists"] = True

    try:
        open_path = safe_join_name(plan_dir, args.next_open_name)
        final_path = safe_join_name(plan_dir, args.next_final_name)
    except ToolError as exc:
        errors.append(str(exc))
        open_path = os.path.join(plan_dir, args.next_open_name)
        final_path = os.path.join(plan_dir, args.next_final_name)

    for path in (open_path, final_path):
        if os.path.exists(path):
            existing.append(path)
    if existing:
        errors.append("preflight-target-exists")
    else:
        checks["targets_absent"] = True

    if checks["directory_exists"]:
        suffix = "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(10))
        probe = os.path.join(plan_dir, f".{suffix}.preflight")
        fd: Optional[int] = None
        try:
            fd = os.open(probe, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.write(fd, b"x")
            checks["probe_create_delete"] = True
        except OSError as exc:
            errors.append(f"preflight-probe-failed: {exc}")
        finally:
            if fd is not None:
                os.close(fd)
            if os.path.exists(probe):
                try:
                    os.remove(probe)
                except OSError as exc:
                    checks["probe_create_delete"] = False
                    errors.append(f"preflight-probe-cleanup-failed: {exc}")

    valid = not errors
    print_json(
        {
            "valid": valid,
            "plan_dir": plan_dir,
            "open_path": open_path,
            "final_path": final_path,
            "existing": existing,
            "checks": checks,
            "errors": errors,
        }
    )
    if valid:
        return 0
    return 1 if existing and len(errors) == 1 else 2


def load_gitignore_patterns(root: str) -> List[str]:
    path = os.path.join(root, ".gitignore")
    patterns: List[str] = []
    if not os.path.isfile(path):
        return patterns
    try:
        lines = read_text(path).splitlines()
    except OSError:
        return patterns
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("!"):
            continue
        patterns.append(stripped)
    return patterns


def matches_gitignore(rel_path: str, is_dir: bool, patterns: Sequence[str]) -> bool:
    rel_path = rel_path.replace("\\", "/")
    basename = rel_path.rsplit("/", 1)[-1]
    for raw_pattern in patterns:
        pattern = raw_pattern.replace("\\", "/")
        dir_only = pattern.endswith("/")
        if dir_only:
            pattern = pattern.rstrip("/")
        anchored = pattern.startswith("/")
        if anchored:
            pattern = pattern.lstrip("/")
        if dir_only and not is_dir:
            continue
        if anchored:
            if fnmatch.fnmatch(rel_path, pattern) or rel_path.startswith(pattern + "/"):
                return True
        elif "/" in pattern:
            if fnmatch.fnmatch(rel_path, pattern) or rel_path.startswith(pattern.rstrip("*") + "/"):
                return True
        else:
            if fnmatch.fnmatch(basename, pattern) or any(fnmatch.fnmatch(part, pattern) for part in rel_path.split("/")):
                return True
    return False


def is_fixed_excluded(rel_path: str, is_dir: bool) -> bool:
    rel_path = rel_path.replace("\\", "/")
    parts = rel_path.split("/")
    if any(part in FIXED_EXCLUDED_DIRS for part in parts):
        return True
    return any(rel_path == prefix or rel_path.startswith(prefix + "/") for prefix in FIXED_EXCLUDED_PREFIXES)


def should_ignore(rel_path: str, is_dir: bool, patterns: Sequence[str]) -> bool:
    return is_fixed_excluded(rel_path, is_dir) or matches_gitignore(rel_path, is_dir, patterns)


def fingerprint_tree(root: str) -> Dict[str, str]:
    root_abs = os.path.abspath(root)
    patterns = load_gitignore_patterns(root_abs)
    files: Dict[str, str] = {}
    for current_root, dirs, filenames in os.walk(root_abs, topdown=True):
        kept_dirs = []
        for dirname in dirs:
            full_dir = os.path.join(current_root, dirname)
            if os.path.islink(full_dir):
                continue
            rel_dir = posix_rel(full_dir, root_abs)
            if not should_ignore(rel_dir, True, patterns):
                kept_dirs.append(dirname)
        dirs[:] = kept_dirs
        for filename in filenames:
            full_file = os.path.join(current_root, filename)
            if os.path.islink(full_file):
                continue
            rel_file = posix_rel(full_file, root_abs)
            if should_ignore(rel_file, False, patterns):
                continue
            files[rel_file] = sha256_file(full_file)
            if len(files) > MAX_FINGERPRINT_FILES:
                raise ToolError("fingerprint-scope-too-large: more than 200000 files after exclusions", 2)
    return dict(sorted(files.items()))


def cmd_fingerprint_workspace(args: argparse.Namespace) -> int:
    root = os.path.abspath(args.root)
    out_json = os.path.abspath(args.out_json)
    if not os.path.isdir(root):
        print_json({"valid": False, "errors": [f"fingerprint-missing-root: {root}"]})
        return 2
    try:
        if os.path.commonpath([root, out_json]) == root:
            print_json({"valid": False, "errors": ["fingerprint-out-json-inside-workspace"]})
            return 2
    except ValueError:
        pass
    try:
        files = fingerprint_tree(root)
        payload = {"algorithm": "sha256-tree-v1", "root": root, "file_count": len(files), "files": files}
        write_json_file(out_json, payload)
        print_json({"valid": True, "path": out_json, "file_count": len(files)})
        return 0
    except (OSError, ToolError) as exc:
        print_json({"valid": False, "errors": [str(exc)]})
        return getattr(exc, "code", 2)


def load_snapshot(path: str) -> Dict[str, object]:
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict) or not isinstance(data.get("files"), dict):
        raise ToolError(f"invalid fingerprint snapshot: {path}")
    return data


def normalize_allowed_path(raw_allowed: str, root: str) -> str:
    if os.path.isabs(raw_allowed):
        allowed_abs = os.path.abspath(raw_allowed)
        try:
            if os.path.commonpath([root, allowed_abs]) != root:
                raise ToolError(f"allowed path is outside snapshot root: {raw_allowed}")
        except ValueError as exc:
            raise ToolError(f"allowed path is outside snapshot root: {raw_allowed}") from exc
        return posix_rel(allowed_abs, root)
    candidate = raw_allowed.replace("\\", "/")
    if not is_posix_relative(candidate):
        raise ToolError(f"allowed path must be workspace-relative: {raw_allowed}")
    return candidate


def cmd_assert_readonly(args: argparse.Namespace) -> int:
    try:
        start = load_snapshot(args.start_json)
        current = load_snapshot(args.current_json)
        root = os.path.abspath(str(start.get("root") or current.get("root") or "."))
        allowed = normalize_allowed_path(args.allowed_path, root)
        start_files = dict(start["files"])
        current_files = dict(current["files"])
    except (OSError, json.JSONDecodeError, ToolError) as exc:
        print_json({"valid": False, "errors": [str(exc)]})
        return 2

    added = sorted(path for path in current_files if path not in start_files)
    removed = sorted(path for path in start_files if path not in current_files)
    modified = sorted(path for path in current_files if path in start_files and current_files[path] != start_files[path])
    changed = sorted(set(added + removed + modified))
    violations = [path for path in changed if path != allowed]
    valid = not violations
    print_json(
        {
            "valid": valid,
            "allowed_path": allowed,
            "added": added,
            "removed": removed,
            "modified": modified,
            "violations": violations,
        }
    )
    return 0 if valid else 1


def parse_frontmatter(text: str) -> Dict[str, str]:
    if not text.startswith("---"):
        return {}
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fields: Dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        match = re.match(r"^(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*:\s*(?P<value>.*)$", line)
        if match:
            fields[match.group("key")] = match.group("value").strip().strip('"')
    return fields


def parse_markdown_header_fields(text: str) -> Dict[str, str]:
    fields: Dict[str, str] = {}
    for line in text.splitlines():
        if line.startswith("## "):
            break
        match = re.match(r"^\*\*(?P<key>[A-Za-z_][A-Za-z0-9_]*)\*\*:\s*(?P<value>.*)$", line.strip())
        if match:
            fields[match.group("key")] = match.group("value").strip().strip('"')
    return fields


def parse_header(text: str) -> Dict[str, str]:
    fields = parse_frontmatter(text)
    fields.update({k: v for k, v in parse_markdown_header_fields(text).items() if k not in fields})
    return fields


def section_bounds(text: str, aliases: Sequence[str]) -> Optional[Tuple[int, int]]:
    lines = text.splitlines(keepends=True)
    offset = 0
    start = None
    for line in lines:
        stripped = line.strip()
        if start is None and any(stripped == alias for alias in aliases):
            start = offset + len(line)
        elif start is not None and stripped.startswith("## "):
            return start, offset
        offset += len(line)
    if start is None:
        return None
    return start, len(text)


def get_section(text: str, name: str) -> Optional[str]:
    bounds = section_bounds(text, SECTION_ALIASES[name])
    if not bounds:
        return None
    return text[bounds[0] : bounds[1]].strip()


def has_title(text: str) -> bool:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return any(stripped.startswith(alias) for alias in SECTION_ALIASES["title"])
    return False


def field_value(block: str, label: str) -> Optional[str]:
    pattern = re.compile(FIELD_RE_TEMPLATE.format(label=re.escape(label)), re.IGNORECASE | re.MULTILINE | re.DOTALL)
    match = pattern.search(block)
    if match:
        return " ".join(match.group("body").strip().split())
    return None


def normalize_status(value: str) -> str:
    lowered = value.lower()
    for status in ("fixed-with-errors", "not-fixed", "regressed", "fixed"):
        if status in lowered:
            return status
    return ""


def normalize_level(value: str) -> str:
    lowered = value.lower()
    for level in ("critical", "high", "medium", "low"):
        if re.search(rf"\b{level}\b", lowered):
            return level
    return ""


def issue_emoji(value: str) -> str:
    if "✅" in value:
        return "✅"
    if "⭕" in value:
        return "⭕️"
    if "⚠" in value:
        return "⚠️"
    if "‼" in value:
        return "‼️"
    return ""


def contains_disallowed_emoji(value: str) -> bool:
    cleaned = value
    for marker in ALLOWED_ISSUE_EMOJI:
        cleaned = cleaned.replace(marker, "")
    cleaned = cleaned.replace("\ufe0f", "")
    for char in cleaned:
        codepoint = ord(char)
        if 0x1F000 <= codepoint <= 0x1FAFF:
            return True
        if 0x2600 <= codepoint <= 0x27BF:
            return True
    return False


def issue_emoji_error(head: str) -> str:
    if contains_disallowed_emoji(head):
        return "has invalid emoji marker"
    if not issue_emoji(head):
        return "is missing emoji marker"
    return ""


def parse_issues(text: str) -> List[Dict[str, object]]:
    section = get_section(text, "issues") or ""
    issues: List[Dict[str, object]] = []
    for match in ISSUE_RE.finditer(section):
        block = match.group(0)
        head = " ".join(match.group("head").strip().split())
        level = field_value(block, "level") or normalize_level(head)
        status = field_value(block, "status") or normalize_status(head)
        title = field_value(block, "title") or head
        description = field_value(block, "description") or ""
        recommendations = field_value(block, "recommendations") or ""
        issues.append(
            {
                "id": int(match.group("num")),
                "level": normalize_level(level),
                "status": normalize_status(status),
                "title": title,
                "description": description,
                "recommendations": recommendations,
                "emoji": issue_emoji(head),
                "emoji_error": issue_emoji_error(head),
                "raw": block,
            }
        )
    return issues


def section_lines(text: str, name: str) -> List[Tuple[int, str]]:
    aliases = SECTION_ALIASES[name]
    lines = text.splitlines()
    in_section = False
    collected: List[Tuple[int, str]] = []
    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not in_section and any(stripped == alias for alias in aliases):
            in_section = True
            continue
        if in_section and stripped.startswith("## "):
            break
        if in_section:
            collected.append((line_number, line))
    return collected


def stage_status_marker(line: str) -> str:
    for candidate in ("✅", "⭕️", "⭕", "⚠️", "⚠", "‼️", "‼"):
        if candidate in line:
            if candidate == "✅":
                return "✅"
            if "⭕" in candidate:
                return "⭕️"
            if "⚠" in candidate:
                return "⚠️"
            return "‼️"
    if "not-applicable" in line.lower():
        return "not-applicable"
    return ""


def clean_stage_title(line: str, marker: str) -> str:
    cleaned = line.strip()
    cleaned = re.sub(r"^[-*+]\s+", "", cleaned)
    if cleaned.startswith("|") and cleaned.endswith("|"):
        parts = [part.strip() for part in cleaned.strip("|").split("|") if part.strip()]
        cleaned = " ".join(parts)
    for token in ("✅", "⭕️", "⭕", "⚠️", "⚠", "‼️", "‼", "not-applicable"):
        cleaned = cleaned.replace(token, "")
    cleaned = " ".join(cleaned.split())
    match = re.match(r"^(?P<id>\d+(?:\.\d+)*)(?:[.)])?\s*(?P<title>.*)$", cleaned)
    if match and match.group("title"):
        return match.group("title").strip()
    return cleaned


def extract_stage_id(line: str) -> str:
    cleaned = line.strip()
    cleaned = re.sub(r"^[-*+]\s+", "", cleaned)
    for token in ("✅", "⭕️", "⭕", "⚠️", "⚠", "‼️", "‼", "not-applicable"):
        cleaned = cleaned.replace(token, "")
    cleaned = " ".join(cleaned.replace("|", " ").split())
    match = re.match(r"^(?P<id>\d+(?:\.\d+)*)(?:[.)])?(?:\s|$)", cleaned)
    return match.group("id") if match else ""


def parse_stage_items(text: str) -> Tuple[List[Dict[str, object]], List[Dict[str, object]], List[Dict[str, str]]]:
    phases: List[Dict[str, object]] = []
    tasks: List[Dict[str, object]] = []
    stages: List[Dict[str, str]] = []
    current_phase = 0
    generated_phase = 0
    generated_task_by_phase: Dict[int, int] = {}

    for line_number, raw_line in section_lines(text, "stages"):
        stripped = raw_line.strip()
        if not stripped:
            continue
        if stripped.startswith("|") and set(stripped.replace("|", "").replace("-", "").replace(":", "").strip()) == set():
            continue
        if not (stripped.startswith("-") or stripped.startswith("|") or re.match(r"^\d+[.)]\s+", stripped)):
            continue

        status = stage_status_marker(stripped)
        item_id = extract_stage_id(stripped)
        title = clean_stage_title(stripped, status)
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        is_explicit_task = "." in item_id if item_id else indent > 0

        if item_id:
            try:
                phase = int(item_id.split(".", 1)[0])
            except ValueError:
                phase = current_phase or 1
        elif is_explicit_task:
            phase = current_phase or 1
            generated_task_by_phase[phase] = generated_task_by_phase.get(phase, 0) + 1
            item_id = f"{phase}.{generated_task_by_phase[phase]}"
        else:
            generated_phase += 1
            phase = generated_phase
            item_id = str(phase)

        if not is_explicit_task:
            current_phase = phase
            phases.append(
                {
                    "id": item_id,
                    "phase": phase,
                    "title": title,
                    "status": status,
                    "raw_text": stripped,
                    "line_start": line_number,
                    "line_end": line_number,
                }
            )
        else:
            tasks.append(
                {
                    "id": item_id,
                    "phase": phase,
                    "title": title,
                    "status": status,
                    "raw_text": stripped,
                    "actionable": status != "not-applicable",
                    "line_start": line_number,
                    "line_end": line_number,
                }
            )
        stages.append({"status": status, "line": stripped})
    return phases, tasks, stages


def parse_stage_statuses(text: str) -> List[Dict[str, str]]:
    return parse_stage_items(text)[2]


def parse_report_document(path: str) -> Dict[str, object]:
    text = read_text(path)
    phases, tasks, stages = parse_stage_items(text)
    return {
        "path": path,
        "header": parse_header(text),
        "sections": {key: get_section(text, key) is not None for key in ("stages", "issues", "task", "context")},
        "phases": phases,
        "tasks": tasks,
        "stages": stages,
        "issues": [{k: v for k, v in issue.items() if k != "raw"} for issue in parse_issues(text)],
    }


def parse_int(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def validate_header_value(field: str, value: Optional[str], errors: List[str]) -> None:
    if value is None or value == "":
        errors.append(f"missing header field: {field}")
        return
    if field == "master_plan_path":
        if not is_posix_relative(value):
            errors.append("master_plan_path must be POSIX-relative to PLAN_DIR")
    elif field == "master_plan_sha256":
        if not HEX64_RE.match(value):
            errors.append("master_plan_sha256 must be 64 hex chars")
    elif field == "master_plan_size":
        parsed = parse_int(value)
        if parsed is None or parsed < 0:
            errors.append("master_plan_size must be int bytes")
    elif field == "audited_at":
        if not ISO_UTC_RE.match(value):
            errors.append("audited_at must be ISO-8601 UTC like 2026-05-10T07:54:08Z")
        else:
            try:
                datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
            except ValueError:
                errors.append("audited_at is not a valid UTC timestamp")
    elif field == "audit_iteration":
        parsed = parse_int(value)
        if parsed is None or parsed < 1:
            errors.append("audit_iteration must be int >= 1")
    elif field == "consecutive_open_invocations":
        parsed = parse_int(value)
        if parsed is None or parsed < 0:
            errors.append("consecutive_open_invocations must be int >= 0")
    elif field == "previous_report_path":
        if value != "null" and not is_posix_relative(value):
            errors.append("previous_report_path must be null or POSIX-relative to PLAN_DIR")
    elif field == "previous_report_sha256":
        if value != "null" and not HEX64_RE.match(value):
            errors.append("previous_report_sha256 must be null or 64 hex chars")
    elif field == "language":
        if value not in VALID_LANGUAGES:
            errors.append("language must be ru or en")


def collect_ambiguous_anchors(text: str) -> Dict[str, str]:
    _, tasks, _ = parse_stage_items(text)
    out: Dict[str, str] = {}
    for task in tasks:
        line = str(task["raw_text"])
        if task["status"] == "⚠️" and AMBIGUOUS_RE.search(line):
            explicit = EVIDENCE_ANCHOR_RE.search(line)
            if explicit:
                out[str(task["id"])] = explicit.group("anchor")
            else:
                fallback = ANCHOR_RE.search(line)
                out[str(task["id"])] = fallback.group(0) if fallback else ""
    return out


def validate_report(path: str) -> Tuple[bool, Dict[str, object]]:
    if not os.path.isfile(path):
        return False, {"valid": False, "path": path, "errors": [f"file not found: {path}"], "warnings": []}
    text = read_text(path)
    errors: List[str] = []
    warnings: List[str] = []

    if not has_title(text):
        errors.append("missing report title")
    for section in ("stages", "issues", "task"):
        if get_section(text, section) is None:
            errors.append(f"missing required section: {section}")
    context = get_section(text, "context")
    if context is not None and not context.strip():
        errors.append("additional context section is present but empty")

    header = parse_header(text)
    for field in REQUIRED_HEADER_FIELDS:
        validate_header_value(field, header.get(field), errors)

    stages = parse_stage_statuses(text)
    if not stages:
        errors.append("no plan stages with statuses found")
    for idx, stage in enumerate(stages, start=1):
        if stage["status"] not in VALID_TASK_MARKERS:
            errors.append(f"stage {idx} has invalid or missing status")

    issues = parse_issues(text)
    for expected_id, issue in enumerate(issues, start=1):
        if issue["id"] != expected_id:
            errors.append(f"issue IDs must be monotonic from 1: expected {expected_id}, got {issue['id']}")
        if issue["level"] not in VALID_LEVELS:
            errors.append(f"issue {issue['id']} has invalid level")
        if issue["status"] not in VALID_ISSUE_STATUSES:
            errors.append(f"issue {issue['id']} has invalid status")
        if not str(issue["title"]).strip():
            errors.append(f"issue {issue['id']} has empty title")
        if len(str(issue["description"])) < 200:
            errors.append(f"issue {issue['id']} description must be >= 200 chars")
        if issue["emoji_error"]:
            errors.append(f"issue {issue['id']} {issue['emoji_error']}")

    is_final = os.path.basename(path).lower().endswith("-final.md")
    if is_final:
        open_stages = [stage["line"] for stage in stages if stage["status"] not in CLOSED_TASK_MARKERS]
        open_issues = [issue["id"] for issue in issues if issue["status"] != "fixed"]
        if open_stages:
            errors.append("final report contains non-closed task statuses")
        if open_issues:
            errors.append("final report contains non-fixed issues")
        consecutive = parse_int(header.get("consecutive_open_invocations"))
        if consecutive != 0:
            errors.append("final report must set consecutive_open_invocations to 0")

    _, gate_tasks, _ = parse_stage_items(text)
    for task in gate_tasks:
        if task["status"] != "✅":
            continue
        if not ANCHOR_RE.search(str(task["raw_text"])):
            message = f"task '{task['id']}' with ✅ is missing an evidence anchor (path#Lx-Ly)"
            if is_final:
                errors.append(message)
            else:
                warnings.append(f"[WARNING] {message}")

    for task in gate_tasks:
        if task["status"] == "✅" and confidence_level(str(task["raw_text"])) == "low":
            message = f"task '{task['id']}' closes with confidence: low"
            if is_final:
                errors.append(message)
            else:
                warnings.append(f"[WARNING] {message}")

    for issue in issues:
        if issue["status"] == "fixed" and confidence_level(str(issue.get("raw", ""))) == "low":
            message = f"issue {issue['id']} marked fixed with confidence: low"
            if is_final:
                errors.append(message)
            else:
                warnings.append(f"[WARNING] {message}")

    previous_rel = header.get("previous_report_path")
    if previous_rel and previous_rel != "null":
        previous_abs = os.path.join(os.path.dirname(os.path.abspath(path)), previous_rel)
        if os.path.isfile(previous_abs):
            try:
                previous_ambiguous = collect_ambiguous_anchors(read_text(previous_abs))
            except OSError:
                previous_ambiguous = {}
            for task_id, anchor in collect_ambiguous_anchors(text).items():
                if task_id in previous_ambiguous and previous_ambiguous[task_id] == anchor:
                    warnings.append(
                        f"[WARNING] task '{task_id}' stuck in ambiguous; "
                        "evidence_anchor unchanged from previous report"
                    )

    result = {
        "valid": not errors,
        "path": path,
        "errors": errors,
        "warnings": warnings,
        "summary": {
            "stage_count": len(stages),
            "issue_count": len(issues),
            "is_final": is_final,
        },
    }
    return not errors, result


def cmd_parse_report(args: argparse.Namespace) -> int:
    if not os.path.isfile(args.report):
        print_json({"valid": False, "errors": [f"file not found: {args.report}"]})
        return 1
    try:
        print_json(parse_report_document(args.report))
        return 0
    except OSError as exc:
        print_json({"valid": False, "errors": [str(exc)]})
        return 1


def cmd_validate_report(args: argparse.Namespace) -> int:
    valid, result = validate_report(args.report)
    print_json(result)
    return 0 if valid else 1


def cmd_iteration_check(args: argparse.Namespace) -> int:
    if not os.path.isfile(args.last_report):
        print_json({"valid": False, "errors": [f"file not found: {args.last_report}"]})
        return 2
    header = parse_header(read_text(args.last_report))
    audit_iteration = parse_int(header.get("audit_iteration"))
    previous_consecutive = parse_int(header.get("consecutive_open_invocations"))
    if audit_iteration is None or previous_consecutive is None:
        print_json({"valid": False, "errors": ["iteration-check-missing-header-fields"]})
        return 2
    if os.path.basename(args.last_report).lower().endswith("-final.md"):
        consecutive = 0
        next_audit_iteration = audit_iteration
    else:
        consecutive = previous_consecutive + 1
        next_audit_iteration = audit_iteration + 1
    limit = args.limit
    print_json(
        {
            "valid": True,
            "previous_consecutive": previous_consecutive,
            "consecutive": consecutive,
            "last_audit_iteration": audit_iteration,
            "next_audit_iteration": next_audit_iteration,
            "ask_required": consecutive >= limit and consecutive > 0,
            "limit": limit,
        }
    )
    return 0


def extract_plan_task_id(line: str) -> str:
    heading = PLAN_HEADING_RE.match(line)
    if heading:
        inner = PLAN_LEADING_ID_RE.match(heading.group("rest"))
        return normalize_plan_task_id(inner.group("id")) if inner else ""
    bullet = PLAN_BULLET_RE.match(line)
    if bullet:
        inner = PLAN_LEADING_ID_RE.match(bullet.group("rest"))
        return normalize_plan_task_id(inner.group("id")) if inner else ""
    table_stage = PLAN_TABLE_STAGE_ID_RE.match(line)
    if table_stage:
        return normalize_plan_task_id(table_stage.group("id"))
    numbered = PLAN_NUMBERED_RE.match(line)
    if numbered:
        return numbered.group("id")
    return ""


def normalize_plan_task_id(task_id: str) -> str:
    return task_id.lower() if PLAN_STAGE_ID_RE.fullmatch(task_id) else task_id

def extract_plan_task_ids(text: str) -> List[str]:
    ids: List[str] = []
    seen = set()
    for line in text.splitlines():
        task_id = extract_plan_task_id(line)
        if task_id and task_id not in seen:
            seen.add(task_id)
            ids.append(task_id)
    return ids


def report_covered_ids(text: str) -> set:
    phases, tasks, _ = parse_stage_items(text)
    covered = {str(item["id"]) for item in phases} | {str(item["id"]) for item in tasks}
    for item in phases + tasks:
        raw_text = str(item.get("raw_text", ""))
        covered.update(normalize_plan_task_id(match.group(0)) for match in PLAN_STAGE_ID_RE.finditer(raw_text))
    return covered


def cmd_task_census(args: argparse.Namespace) -> int:
    for role, candidate in (("plan", args.plan), ("report", args.report)):
        if not os.path.isfile(candidate):
            print_json(
                {
                    "valid": False,
                    "units_extracted": 0,
                    "plan_ids": [],
                    "covered": [],
                    "uncovered": [],
                    "errors": [f"file not found: {candidate}"],
                }
            )
            return 2
    plan_ids = extract_plan_task_ids(read_text(args.plan))
    if not plan_ids:
        print_json(
            {
                "valid": False,
                "units_extracted": 0,
                "plan_ids": [],
                "covered": [],
                "uncovered": [],
                "errors": ["task-census-no-units: no syntactic task units extracted from plan"],
            }
        )
        return 2
    covered_set = report_covered_ids(read_text(args.report))
    covered = [pid for pid in plan_ids if pid in covered_set]
    uncovered = [pid for pid in plan_ids if pid not in covered_set]
    result = {
        "valid": not uncovered,
        "units_extracted": len(plan_ids),
        "plan_ids": plan_ids,
        "covered": covered,
        "uncovered": uncovered,
        "errors": [] if not uncovered else [f"task-census-uncovered: {', '.join(uncovered)}"],
    }
    print_json(result)
    return 0 if not uncovered else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="plan-resolver helper utility")
    subparsers = parser.add_subparsers(dest="command", required=True)

    bootstrap = subparsers.add_parser("bootstrap")
    bootstrap.add_argument("workspace_root")
    bootstrap.add_argument("plan")
    bootstrap.add_argument("reports", nargs="*")
    bootstrap.set_defaults(func=cmd_bootstrap)

    preflight = subparsers.add_parser("preflight")
    preflight.add_argument("plan_dir")
    preflight.add_argument("next_open_name")
    preflight.add_argument("next_final_name")
    preflight.set_defaults(func=cmd_preflight)

    fingerprint = subparsers.add_parser("fingerprint-workspace")
    fingerprint.add_argument("root")
    fingerprint.add_argument("out_json")
    fingerprint.set_defaults(func=cmd_fingerprint_workspace)

    parse_report = subparsers.add_parser("parse-report")
    parse_report.add_argument("report")
    parse_report.set_defaults(func=cmd_parse_report)

    validate_report_parser = subparsers.add_parser("validate-report")
    validate_report_parser.add_argument("report")
    validate_report_parser.set_defaults(func=cmd_validate_report)

    readonly = subparsers.add_parser("assert-readonly")
    readonly.add_argument("start_json")
    readonly.add_argument("current_json")
    readonly.add_argument("allowed_path")
    readonly.set_defaults(func=cmd_assert_readonly)

    iteration = subparsers.add_parser("iteration-check")
    iteration.add_argument("last_report")
    iteration.add_argument("limit", nargs="?", type=int, default=5)
    iteration.set_defaults(func=cmd_iteration_check)

    census = subparsers.add_parser("task-census")
    census.add_argument("plan")
    census.add_argument("report")
    census.set_defaults(func=cmd_task_census)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except ToolError as exc:
        print_json({"valid": False, "errors": [str(exc)]})
        return exc.code
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
