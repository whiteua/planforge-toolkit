#!/usr/bin/env python3
"""Utility commands for the plan-resolver skill.

Stdlib only. Python 3.8+.
"""
from __future__ import annotations

import argparse
import fnmatch
import functools
import hashlib
import importlib.util
import json
import os
import random
import re
import string
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence, Tuple


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
# plan-splitter part ids (roadmap table rows): a, b, ... aa. Letters need a separator to count as ids.
PLAN_TABLE_STAGE_ID_RE = re.compile(r"^\s*\|\s*(?P<id>[a-z]{1,2})\s*\|", re.IGNORECASE)
PLAN_LEADING_ID_RE = re.compile(r"^(?:(?P<id>\d+(?:\.\d+)*)[.):]?|(?P<part>[a-z]{1,2})[.):])\s+\S", re.IGNORECASE)
# plan-writing task headings: "### Task 1.2: Title" / "### Задача 3: Название".
# Separators mirror plan-executor `_TASK_RE`: ':', '-', '—', or '.' followed by whitespace.
PLAN_KEYWORD_ID_RE = re.compile(
    r"^(?:Task|Задача)\s+(?P<id>\d+(?:\.\d+)*)\s*(?:[:\-)]|—|\.(?=\s|$))", re.IGNORECASE
)
PLAN_FENCE_RE = re.compile(r"^\s*(```|~~~)")
ANCHOR_RE = re.compile(r"[^\s:#]+#L\d+(?:-L?\d+)?", re.IGNORECASE)
CONFIDENCE_RE = re.compile(r"confidence\s*[:=]\s*(?P<level>high|medium|low)", re.IGNORECASE)
AMBIGUOUS_RE = re.compile(r"\bambiguous\b", re.IGNORECASE)
EVIDENCE_ANCHOR_RE = re.compile(r"evidence_anchor\s*[:=]\s*(?P<anchor>\S+)", re.IGNORECASE)
# Evidence for tasks that leave no code (checkpoints, manual verifications): the command and its result.
EVIDENCE_PROBE_RE = re.compile(r"evidence_probe\s*[:=]\s*\S", re.IGNORECASE)
# A task closed on the executor's word (e.g. it needs an external system the audit may not touch).
EXECUTOR_REPORTED_RE = re.compile(r"verification\s*[:=]\s*executor-reported", re.IGNORECASE)
# Compact closed lines (REPORT-FORMAT.md): a `✅` leaf with more detail lines or anchors gets a warning.
MAX_CLOSED_DETAILS = 1
MAX_CLOSED_ANCHORS = 2
PLAN_CODE_FILE_RE = re.compile(r"^\s*[-*]\s*(?:Create|Modify|Delete|Move|Создать|Изменить)\s*:", re.IGNORECASE)
# Files actions of a code task in the shared parser's `files` (the actions PLAN_CODE_FILE_RE matches).
PLAN_CODE_ACTIONS = {"create", "modify", "delete", "move", "создать", "изменить"}


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
# .git/index: read-only git commands (status, diff) refresh its stat cache. HEAD and refs stay
# in the fingerprint, so commits, resets and checkouts are still detected.
FIXED_EXCLUDED_PREFIXES = {".git/objects", ".git/index"}
# Tool caches that read-only probes (pytest, mypy, ruff, tsc, eslint) create as a side effect.
FIXED_EXCLUDED_CACHE_DIRS = {".pytest_cache", ".mypy_cache", ".ruff_cache", ".hypothesis", ".tox", ".nox", ".cache"}
FIXED_EXCLUDED_FILES = {".eslintcache"}
FIXED_EXCLUDED_SUFFIXES = (".tsbuildinfo",)
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
    "fix_log": ("## Журнал исправлений", "## Fix Log"),
    "evidence": ("## Отпечаток улик", "## Evidence fingerprint"),
}
LEVEL_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}
FIX_STATES = ("applied", "needs-user", "skipped")
FIX_LOG_LINE_RE = re.compile(
    r"^- (?:Ошибка|Error) (?P<id>\d+):\s*(?P<state>applied|needs-user|skipped)\b", re.IGNORECASE | re.MULTILINE
)
# Incremental re-audit: the pass scope in the frontmatter and the report's evidence fingerprint.
AUDIT_SCOPES = ("full", "incremental")
FULL_SCOPE_RATIO = 0.5
REAUDIT_MARKER = "<!-- reaudit -->"
REVERIFY_MARKER = "<!-- re-verify -->"
HTML_COMMENT_RE = re.compile(r"<!--.*?-->")
AUDIT_TASK_ID_RE = re.compile(r"^[0-9A-Za-z]+(?:\.[0-9A-Za-z]+)*$")
EVIDENCE_HEADER_RE = re.compile(r"^\|\s*(?:File|Файл)\s*\|\s*SHA-256\s*\|$", re.IGNORECASE)
EVIDENCE_ROW_RE = re.compile(r"^\|\s*(?P<path>[^|\s][^|]*?)\s*\|\s*(?P<value>[0-9a-f]{64}|excluded|missing)\s*\|$")
ISSUE_HEAD_RE = re.compile(r"^\s*(?P<num>\d+)\)\s*(?:Ошибка|Error)\b")
# bootstrap.report_header fields carry-forward needs to write the draft's frontmatter.
CARRY_HEADER_FIELDS = (
    "master_plan_path",
    "master_plan_sha256",
    "master_plan_size",
    "audited_at",
    "audit_iteration",
    "consecutive_open_invocations_if_open",
    "previous_report_path",
    "previous_report_sha256",
    "language",
)


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
    """(absolute path, root-relative POSIX path) of `raw_path`; ToolError when it is outside the root. Inside is
    decided by path_inside (realpath + normcase, F12 of plan-refactoring-02); a path that reaches the root through
    a link is spelled under the root, so callers compare it with the root's other paths."""
    root_abs = os.path.abspath(root)
    candidate_abs = os.path.abspath(raw_path if os.path.isabs(raw_path) else os.path.join(root_abs, raw_path))
    if not path_inside(root_abs, candidate_abs):
        raise ToolError(f"path is outside workspace: {raw_path}")
    try:
        lexical = os.path.commonpath([os.path.normcase(root_abs), os.path.normcase(candidate_abs)])
    except ValueError:
        lexical = ""
    if lexical != os.path.normcase(root_abs):
        real = os.path.relpath(os.path.realpath(candidate_abs), os.path.realpath(root_abs))
        candidate_abs = os.path.join(root_abs, real)
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
STUCK_OPEN_LIMIT = 5


def detect_plan_language(plan_path: str) -> str:
    """Ecosystem convention (see plan-iterative-revision `detect_lang` in scripts/next_review_index.py):
    cyrillic_ratio > 0.05 -> ru, otherwise en. Unreadable/empty -> en."""
    try:
        with open(plan_path, encoding="utf-8", errors="ignore") as fh:
            text = fh.read()
    except OSError:
        return "en"
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return "en"
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
    master_sha = sha256_file(master_abs)
    language = detect_plan_language(master_abs)
    previous_consecutive = 0
    if last_report:
        previous_consecutive = parse_int(parse_header(read_text(str(last_report["abs_path"]))).get("consecutive_open_invocations")) or 0
    report_header = {
        "master_plan_path": posix_rel(master_abs, plan_dir_abs),
        "master_plan_sha256": master_sha,
        "master_plan_size": os.path.getsize(master_abs),
        "audit_iteration": next_n,
        "audited_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "consecutive_open_invocations_if_open": previous_consecutive + 1,
        "consecutive_open_invocations_if_final": 0,
        "previous_report_path": os.path.basename(str(last_report["abs_path"])) if last_report else None,
        "previous_report_sha256": last_report["sha256"] if last_report else None,
        "language": language,
        "audit_scope": "full",
        "audit_tasks": "all",
    }
    if args.full and not report_items:
        warnings.append("--full ignored on the first pass")
    pass_type = "first" if not report_items else ("subsequent-full" if args.full else "subsequent")
    # Stuck-open gate: this many audits in a row ended with an open report (counting this
    # one if it stays open). At the limit the agent asks the user instead of auditing again.
    stuck_open = {
        "consecutive_if_open": previous_consecutive + 1,
        "limit": STUCK_OPEN_LIMIT,
        "ask_required": previous_consecutive + 1 >= STUCK_OPEN_LIMIT,
    }
    result = {
        "valid": True,
        "closed": False,
        "stuck_open": stuck_open,
        "workspace_root": workspace_root,
        "master_plan": master_rel,
        "master_plan_abs": master_abs,
        "master_plan_sha256": master_sha,
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
        "language": language,
        "pass_type": pass_type,
        "report_header": report_header,
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
    if any(part in FIXED_EXCLUDED_DIRS or part in FIXED_EXCLUDED_CACHE_DIRS for part in parts):
        return True
    if not is_dir and (parts[-1] in FIXED_EXCLUDED_FILES or parts[-1].endswith(FIXED_EXCLUDED_SUFFIXES)):
        return True
    return any(rel_path == prefix or rel_path.startswith(prefix + "/") for prefix in FIXED_EXCLUDED_PREFIXES)


def should_ignore(rel_path: str, is_dir: bool, patterns: Sequence[str]) -> bool:
    return is_fixed_excluded(rel_path, is_dir) or matches_gitignore(rel_path, is_dir, patterns)


def fingerprint_tree(root: str, base: Optional[Dict[str, object]] = None) -> Tuple[Dict[str, str], Dict[str, List[int]], int]:
    """Hash the tree; reuse base hashes for files whose size and mtime_ns are unchanged."""
    root_abs = os.path.abspath(root)
    patterns = load_gitignore_patterns(root_abs)
    base_files = dict(base.get("files") or {}) if base else {}
    base_stats = dict(base.get("stats") or {}) if base else {}
    files: Dict[str, str] = {}
    stats: Dict[str, List[int]] = {}
    hashed = 0
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
            info = os.stat(full_file)
            stat = [info.st_size, info.st_mtime_ns]
            if rel_file in base_files and base_stats.get(rel_file) == stat:
                files[rel_file] = str(base_files[rel_file])
            else:
                files[rel_file] = sha256_file(full_file)
                hashed += 1
            stats[rel_file] = stat
            if len(files) > MAX_FINGERPRINT_FILES:
                raise ToolError("fingerprint-scope-too-large: more than 200000 files after exclusions", 2)
    return dict(sorted(files.items())), dict(sorted(stats.items())), hashed


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
        base = None
        if args.base:
            base = load_snapshot(args.base)
            if os.path.abspath(str(base.get("root") or "")) != root or not isinstance(base.get("stats"), dict):
                base = None
        files, stats, hashed = fingerprint_tree(root, base)
        payload = {"algorithm": "sha256-tree-v2", "root": root, "file_count": len(files), "files": files, "stats": stats}
        write_json_file(out_json, payload)
        print_json({"valid": True, "path": out_json, "file_count": len(files), "hashed": hashed, "base_used": base is not None})
        return 0
    except (OSError, json.JSONDecodeError, ToolError) as exc:
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


def snapshot_diff(before: Dict[str, object], after: Dict[str, object]) -> Dict[str, List[str]]:
    before_files = dict(before.get("files") or {})
    after_files = dict(after.get("files") or {})
    return {
        "added": sorted(path for path in after_files if path not in before_files),
        "removed": sorted(path for path in before_files if path not in after_files),
        "modified": sorted(path for path in after_files if path in before_files and after_files[path] != before_files[path]),
    }


def cmd_snapshot_diff(args: argparse.Namespace) -> int:
    try:
        before = load_snapshot(args.before_json)
        after = load_snapshot(args.after_json)
    except (OSError, json.JSONDecodeError, ToolError) as exc:
        print_json({"valid": False, "errors": [str(exc)]})
        return 2
    diff = snapshot_diff(before, after)
    changed = diff["added"] + diff["removed"] + diff["modified"]
    print_json({"valid": True, "changed": sorted(changed), **diff, "errors": []})
    return 0


def cmd_assert_readonly(args: argparse.Namespace) -> int:
    try:
        start = load_snapshot(args.start_json)
        current = load_snapshot(args.current_json)
        root = os.path.abspath(str(start.get("root") or current.get("root") or "."))
        allowed = [normalize_allowed_path(raw, root) for raw in args.allowed_paths]
        start_files = dict(start["files"])
        current_files = dict(current["files"])
    except (OSError, json.JSONDecodeError, ToolError) as exc:
        print_json({"valid": False, "errors": [str(exc)]})
        return 2

    added = sorted(path for path in current_files if path not in start_files)
    removed = sorted(path for path in start_files if path not in current_files)
    modified = sorted(path for path in current_files if path in start_files and current_files[path] != start_files[path])
    changed = sorted(set(added + removed + modified))
    violations = [path for path in changed if path not in allowed]
    valid = not violations
    print_json(
        {
            "valid": valid,
            "allowed_path": allowed[0],
            "allowed_paths": allowed,
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
            normalized = stripped.replace("ё", "е").replace("Ё", "Е")
            return any(normalized.startswith(alias) for alias in SECTION_ALIASES["title"])
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
                "origin": (field_value(block, "origin") or "").lower(),
                "linked_items": field_value(block, "linked_items") or "",
                "evidence": field_value(block, "evidence") or "",
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
    cleaned = HTML_COMMENT_RE.sub(" ", line).strip()
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
    cleaned = HTML_COMMENT_RE.sub(" ", line).strip()
    cleaned = re.sub(r"^[-*+]\s+", "", cleaned)
    for token in ("✅", "⭕️", "⭕", "⚠️", "⚠", "‼️", "‼", "not-applicable"):
        cleaned = cleaned.replace(token, "")
    cleaned = " ".join(cleaned.replace("|", " ").split())
    match = re.match(r"^(?P<id>\d+(?:\.\d+)*)(?:[.)])?(?:\s|$)", cleaned)
    if match:
        return match.group("id")
    # Part ids (a, b, ... aa) count only with a separator: "- ✅ a: Scaffold".
    part = re.match(r"^(?P<id>[a-z]{1,2})[.):](?:\s|$)", cleaned, re.IGNORECASE)
    return part.group("id").lower() if part else ""


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
        if indent > 0 and not status and not item_id and (tasks or phases):
            # Detail sub-bullet (e.g. "- evidence_anchor: path#L1-L9") belongs to the item above.
            owner = tasks[-1] if tasks and tasks[-1]["line_end"] > phases[-1]["line_end"] else phases[-1]
            owner["raw_text"] = f"{owner['raw_text']} {stripped.lstrip('-*+ ').strip()}"
            owner["line_end"] = line_number
            owner["details"] = int(owner["details"]) + 1
            continue
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
                    "details": 0,
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
                    "details": 0,
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
    elif field == "audit_scope":
        if value not in AUDIT_SCOPES:
            errors.append("audit_scope must be full or incremental")
    elif field == "audit_tasks":
        if parse_audit_tasks(value) is None:
            errors.append("audit_tasks must be all or a list of task ids like [7, 8, 12.1]")


def parse_audit_tasks(value: str) -> Optional[List[str]]:
    """Ids of `audit_tasks: [7, 8, 12.1]` as written; [] for `all` and for an empty list; None when malformed."""
    value = value.strip()
    if value == "all":
        return []
    if not (value.startswith("[") and value.endswith("]")):
        return None
    ids = [item.strip().strip("'\"") for item in value[1:-1].split(",") if item.strip()]
    return ids if all(AUDIT_TASK_ID_RE.match(item) for item in ids) else None


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


ANCHOR_PARTS_RE = re.compile(r"^(?P<path>[^\s:#]+)#L(?P<start>\d+)(?:-L?(?P<end>\d+))?$", re.IGNORECASE)


def check_anchor(anchor: str, root: str) -> Optional[str]:
    """Return an error text when `path#Lx[-Ly]` does not point at real lines under root."""
    match = ANCHOR_PARTS_RE.match(anchor)
    if not match:
        return f"malformed anchor: {anchor}"
    target = os.path.normpath(os.path.join(root, match.group("path").replace("\\", "/")))
    if not os.path.isfile(target):
        return f"anchor file not found: {anchor}"
    try:
        with open(target, "rb") as handle:
            line_count = sum(1 for _ in handle)
    except OSError as exc:
        return f"anchor unreadable: {anchor} ({exc})"
    start = int(match.group("start"))
    end = int(match.group("end") or start)
    if start < 1 or end < start:
        return f"anchor has an invalid line range: {anchor}"
    if end > line_count:
        return f"anchor beyond end of file ({line_count} lines): {anchor}"
    return None


def evidence_lines(section: str) -> List[str]:
    """Rows of an evidence section without blank lines, the header row and the separator."""
    rows: List[str] = []
    for line in section.splitlines():
        stripped = line.strip()
        if stripped and not set(stripped) <= set("|-: ") and not EVIDENCE_HEADER_RE.match(stripped):
            rows.append(stripped)
    return rows


def anchor_path(anchor: str) -> str:
    """The file of `path#Lx-Ly`, POSIX, without quoting characters around it."""
    return anchor.split("#", 1)[0].replace("\\", "/").strip("`'\"()[]<>")


def stage_anchor_paths(text: str) -> Dict[str, List[str]]:
    """Anchor files per stage item id (phases and tasks of the stages section), in order, once each."""
    phases, tasks, _ = parse_stage_items(text)
    out: Dict[str, List[str]] = {}
    for item in phases + tasks:
        paths = out.setdefault(str(item["id"]), [])
        for match in ANCHOR_RE.finditer(str(item["raw_text"])):
            path = anchor_path(match.group(0))
            if path and path not in paths:
                paths.append(path)
    return out


def plan_task_files(plan_text: str) -> Optional[Dict[str, List[str]]]:
    """Paths of each plan task's Files block by brainstorm_tool.parse_plan_tasks, keyed by the normalized
    task id; None without the parser or for a plan outside the task heading contract."""
    tasks = _contract_tasks(plan_text)
    if tasks is None:
        return None
    out: Dict[str, List[str]] = {}
    for task in tasks:
        paths = out.setdefault(normalize_plan_task_id(task["id"]), [])
        for entry in task["files"]:
            path = str(entry["path"]).replace("\\", "/")
            if path not in paths:
                paths.append(path)
    return out


def evidence_value(path: str, files: Dict[str, str], root: str) -> str:
    """SHA-256 of `path` in the snapshot; `excluded` for a file the snapshot skips; `missing` when there is none."""
    if path in files:
        return str(files[path])
    return "excluded" if os.path.isfile(os.path.join(root, path)) else "missing"


def evidence_table(report_text: str, plan_text: str, snapshot: Dict[str, object],
                   plan_path: Optional[str] = None) -> Tuple[Dict[str, str], List[str]]:
    """{path: SHA-256 | excluded | missing} for the evidence files of a report: the anchors of its stage items
    and issue evidence, and the files of the plan tasks' Files blocks; plus warnings. The pipeline's own files
    (is_pipeline_file; the plan's folder from `plan_path`) are left out."""
    root = os.path.abspath(str(snapshot.get("root") or ""))
    plan_dir = plan_dir_of(plan_path, root) if plan_path else None
    files = dict(snapshot["files"])
    table: Dict[str, str] = {}
    for paths in stage_anchor_paths(report_text).values():
        for path in paths:
            if not is_pipeline_file(path, plan_dir):
                table[path] = evidence_value(path, files, root)
    for issue in parse_issues(report_text):
        for match in ANCHOR_RE.finditer(str(issue["evidence"])):
            path = anchor_path(match.group(0))
            if path and not is_pipeline_file(path, plan_dir):
                table[path] = evidence_value(path, files, root)
    warnings: List[str] = []
    plan_files = plan_task_files(plan_text)
    if plan_files is None:
        warnings.append(
            "plan-files-unavailable: evidence from anchors only "
            "(plan-brainstorming not installed alongside, or the plan has no task headings)"
        )
    else:
        for paths in plan_files.values():
            for path in paths:
                if is_pipeline_file(path, plan_dir):
                    continue
                value = table.get(path) or evidence_value(path, files, root)
                # A Files token that names no file (`B.lang`, a bare `SKILL.md`) is not evidence.
                if value != "missing":
                    table[path] = value
    excluded = sorted(path for path, value in table.items() if value == "excluded")
    if excluded:
        warnings.append("evidence-excluded (outside the snapshot): " + ", ".join(excluded))
    return dict(sorted(table.items())), warnings


def render_evidence_section(table: Dict[str, str], ru: bool) -> str:
    heading = SECTION_ALIASES["evidence"][0 if ru else 1]
    rows = "".join(f"| {path} | {value} |\n" for path, value in table.items())
    return f"{heading}\n\n| File | SHA-256 |\n|---|---|\n{rows}"


def put_evidence_section(text: str, section: str) -> str:
    """Replace the report's evidence section whole; else insert it before the Fix Log; else append it."""
    lines = text.splitlines(keepends=True)

    def heading_at(aliases: Sequence[str]) -> Optional[int]:
        return next((index for index, line in enumerate(lines) if line.strip() in aliases), None)

    start = heading_at(SECTION_ALIASES["evidence"])
    if start is not None:
        end = next((index for index in range(start + 1, len(lines)) if lines[index].startswith("## ")), len(lines))
        tail = "".join(lines[end:])
        return "".join(lines[:start]) + section + ("\n" + tail if tail else "")
    fix_log = heading_at(SECTION_ALIASES["fix_log"])
    if fix_log is not None:
        return "".join(lines[:fix_log]) + section + "\n" + "".join(lines[fix_log:])
    return text.rstrip("\n") + "\n\n" + section


def path_inside(root: str, path: str) -> bool:
    """`path` lies under `root` after realpath and normcase (F12 of plan-refactoring-02): a link to the root is
    inside, a link out of it is not."""
    base = os.path.normcase(os.path.realpath(root))
    try:
        return os.path.commonpath([base, os.path.normcase(os.path.realpath(path))]) == base
    except ValueError:  # another drive on Windows
        return False


# The pipeline's own files are never evidence (F10 of plan-refactoring-02): BACKLOG.md at the root, a free file the
# user and the skills write at any moment, and the chain files by exact name in the plan's folder, by plan-executor's
# rule (executor_tool._CHAIN_FILE_RE, _is_run_artifact). A file with such a name elsewhere is ordinary evidence.
# CHAIN_FILE_RE is a copy for a resolver installed without plan-executor; a contract test keeps the two equal.
CHAIN_FILE_RE = re.compile(
    r".+-(?:chain\.json(?:\.lock)?|diffs\.md|followups\.json|spec\.md|impl\.md|impl-[a-z]+\.md"
    r"|roadmap\.md|completion\.md|review-\d+\.md|report-\d+(?:-final)?\.md)")
FREE_FILES = ("BACKLOG.md",)


def plan_dir_of(plan: str, root: str) -> Optional[str]:
    """Root-relative folder of the plan ("" for the root); None for a plan outside the root."""
    if not path_inside(root, plan):
        return None
    folder = os.path.relpath(os.path.dirname(os.path.realpath(plan)), os.path.realpath(root)).replace(os.sep, "/")
    return "" if folder == "." else folder


def is_pipeline_file(path: str, plan_dir: Optional[str]) -> bool:
    """BACKLOG.md at the root, or a CHAIN_FILE_RE name in `plan_dir` (root-relative; None: no folder matches)."""
    path = path.replace("\\", "/")
    if path in FREE_FILES:
        return True
    folder, _, name = path.rpartition("/")
    return plan_dir is not None and folder == plan_dir and bool(CHAIN_FILE_RE.fullmatch(name))


def validate_report(
    path: str, root: Optional[str] = None, plan: Optional[str] = None
) -> Tuple[bool, Dict[str, object]]:
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
    scope = header.get("audit_scope")
    if scope is None:
        warnings.append("[WARNING] audit_scope is missing: the report is read as a full pass")
    else:
        validate_header_value("audit_scope", scope, errors)
    audit_tasks = header.get("audit_tasks")
    if audit_tasks is None:
        if scope == "incremental":
            warnings.append("[WARNING] audit_scope: incremental without audit_tasks: run-stats counts this pass as full")
    else:
        validate_header_value("audit_tasks", audit_tasks, errors)
        listed = parse_audit_tasks(audit_tasks) or []
        if listed and plan:
            known = set(extract_plan_task_ids(read_text(plan)))
            unknown = [item for item in listed if normalize_plan_task_id(item) not in known]
            if unknown:
                errors.append("audit_tasks names tasks the plan does not have: " + ", ".join(unknown))
    for marker in (REAUDIT_MARKER, REVERIFY_MARKER):
        if marker in text:
            errors.append(f"unfilled placeholder {marker}: {text.count(marker)} left")
    evidence = get_section(text, "evidence")
    if evidence is not None:
        for line in evidence_lines(evidence):
            if not EVIDENCE_ROW_RE.match(line):
                errors.append(
                    "evidence fingerprint row is malformed (expected | path | 64 hex, excluded or missing |; "
                    f"run evidence-fingerprint): {line}"
                )

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
        if scope == "incremental":
            errors.append("final report requires a full pass (audit_scope: full)")

    phases, tasks, _ = parse_stage_items(text)
    # Every closed leaf needs evidence: tasks, and phases that have no tasks of their own
    # (a phase line only aggregates when child tasks carry the anchors).
    phases_with_tasks = {task["phase"] for task in tasks}
    gate_tasks = tasks + [phase for phase in phases if phase["phase"] not in phases_with_tasks]
    code_tasks = set(plan_code_task_ids(read_text(plan))) if plan else set()
    probe_closed: List[str] = []
    for task in gate_tasks:
        if task["status"] != "✅":
            continue
        raw = str(task["raw_text"])
        if ANCHOR_RE.search(raw):
            continue
        if EVIDENCE_PROBE_RE.search(raw):
            # A command result proves a checkpoint or a manual verification, but not a task
            # that was supposed to change code: that one must point at the code.
            if str(task["id"]) in code_tasks:
                errors.append(
                    f"task '{task['id']}' changes code in the plan (Create/Modify): "
                    "evidence_probe is not enough, add an evidence anchor (path#Lx-Ly)"
                )
            else:
                probe_closed.append(str(task["id"]))
            continue
        message = f"task '{task['id']}' with ✅ is missing an evidence anchor (path#Lx-Ly) or evidence_probe"
        if is_final:
            errors.append(message)
        else:
            warnings.append(f"[WARNING] {message}")

    # A closed leaf is one line with one anchor (a second only on the task's test file, which the
    # validator does not tell apart): warnings, not errors, so older verbose reports stay valid.
    for task in gate_tasks:
        if task["status"] != "✅":
            continue
        details = int(task["details"])
        if details > MAX_CLOSED_DETAILS:
            warnings.append(f"[WARNING] verbose-closed-task: {task['id']} has {details} detail lines")
        anchors = len(ANCHOR_RE.findall(str(task["raw_text"])))
        if anchors > MAX_CLOSED_ANCHORS:
            warnings.append(f"[WARNING] too-many-anchors: {task['id']} has {anchors} anchors")

    executor_reported = [
        str(task["id"]) for task in gate_tasks if EXECUTOR_REPORTED_RE.search(str(task["raw_text"]))
    ]
    if executor_reported:
        warnings.append(
            "[WARNING] closed on the executor's report, not re-verified by this audit: "
            + ", ".join(executor_reported)
        )

    if root:
        # Anchors are claims about the code: a closed item or an issue must point at real lines.
        checked: List[Tuple[str, str]] = []
        for task in gate_tasks:
            if task["status"] in ("✅", "⚠️"):
                checked.extend((f"task '{task['id']}'", m.group(0)) for m in ANCHOR_RE.finditer(str(task["raw_text"])))
        for issue in issues:
            checked.extend((f"issue {issue['id']}", m.group(0)) for m in ANCHOR_RE.finditer(str(issue.get("evidence") or "")))
        for owner, anchor in checked:
            problem = check_anchor(anchor, root)
            if problem:
                errors.append(f"{owner}: {problem}")

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
            "probe_closed": probe_closed,
            "executor_reported": executor_reported,
        },
    }
    return not errors, result


def cmd_parse_report(args: argparse.Namespace) -> int:
    if not os.path.isfile(args.report):
        print_json({"valid": False, "errors": [f"file not found: {args.report}"]})
        return 2
    try:
        print_json(parse_report_document(args.report))
        return 0
    except (OSError, UnicodeDecodeError) as exc:
        print_json({"valid": False, "errors": [str(exc)]})
        return 2


def cmd_validate_report(args: argparse.Namespace) -> int:
    if not os.path.isfile(args.report):
        print_json({"valid": False, "path": args.report, "errors": [f"file not found: {args.report}"], "warnings": []})
        return 2
    root = os.path.abspath(args.root) if args.root else None
    if root and not os.path.isdir(root):
        print_json({"valid": False, "path": args.report, "errors": [f"root not found: {args.root}"], "warnings": []})
        return 2
    if args.plan and not os.path.isfile(args.plan):
        print_json({"valid": False, "path": args.report, "errors": [f"plan not found: {args.plan}"], "warnings": []})
        return 2
    valid, result = validate_report(args.report, root, args.plan)
    print_json(result)
    return 0 if valid else 1


def extract_plan_task_id(line: str) -> str:
    return extract_plan_task_id_kind(line)[0]


def extract_plan_task_id_kind(line: str) -> Tuple[str, str]:
    """Return (id, kind); kind is 'heading', 'table' or 'list' (bullets and numbered lines)."""
    heading = PLAN_HEADING_RE.match(line)
    if heading:
        rest = heading.group("rest")
        keyword = PLAN_KEYWORD_ID_RE.match(rest)
        inner = PLAN_LEADING_ID_RE.match(rest) or keyword
        kind = "task-heading" if keyword else "heading"
        return (normalize_plan_task_id(_leading_id(inner)) if inner else ""), kind
    bullet = PLAN_BULLET_RE.match(line)
    if bullet:
        inner = PLAN_LEADING_ID_RE.match(bullet.group("rest"))
        return (normalize_plan_task_id(_leading_id(inner)) if inner else ""), "list"
    table_stage = PLAN_TABLE_STAGE_ID_RE.match(line)
    if table_stage:
        return normalize_plan_task_id(table_stage.group("id")), "table"
    numbered = PLAN_NUMBERED_RE.match(line)
    if numbered:
        return numbered.group("id"), "list"
    return "", ""


def _leading_id(match: "re.Match[str]") -> str:
    groups = match.groupdict()
    return groups.get("id") or groups.get("part") or ""


NUMERIC_TASK_ID_RE = re.compile(r"^[0-9]+(?:\.[0-9]+)*$")


def normalize_plan_task_id(task_id: str) -> str:
    """Lower case; a dotted numeric id without leading zeros (`01.02` → `1.2`): the rule of
    brainstorm_tool.normalize_task_id (F7 of plan-refactoring-02), so `Task 01` of a plan and `1` of a report meet."""
    text = task_id.lower()
    if NUMERIC_TASK_ID_RE.match(text):
        return ".".join(str(int(part)) for part in text.split("."))
    return text

@functools.lru_cache(maxsize=None)
def _load_brainstorm_tool():
    """plan-brainstorming's brainstorm_tool.py, loaded by path once per process (None when it is not
    installed alongside). Tests swap it by replacing this function, which the cache does not affect."""
    skills = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    path = os.path.join(skills, "plan-brainstorming", "scripts", "brainstorm_tool.py")
    if not os.path.isfile(path):
        return None
    spec = importlib.util.spec_from_file_location("brainstorm_tool", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _contract_tasks(text: str) -> Optional[List[Dict[str, object]]]:
    """Tasks of a plan in the plan format contract by brainstorm_tool.parse_plan_tasks; None (the local
    parse) without the parser, without contract task headings, or with a malformed task heading."""
    parse = getattr(_load_brainstorm_tool(), "parse_plan_tasks", None)
    if parse is None:
        return None
    parsed = parse(text)
    if not parsed["tasks"] or parsed["malformed"]:
        return None
    return parsed["tasks"]


def plan_code_task_ids(text: str) -> List[str]:
    """Ids of plan tasks whose Files block creates or modifies code (not test-only, not checkpoints)."""
    tasks = _contract_tasks(text)
    if tasks is not None:
        result: List[str] = []
        for task in tasks:
            task_id = normalize_plan_task_id(task["id"])
            if task_id not in result and any(entry["action"] in PLAN_CODE_ACTIONS for entry in task["files"]):
                result.append(task_id)
        return result
    current = ""
    result: List[str] = []
    in_fence = False
    for line in text.splitlines():
        if PLAN_FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        task_id, kind = extract_plan_task_id_kind(line)
        if task_id and kind in ("task-heading", "heading"):
            current = task_id
            continue
        if current and PLAN_CODE_FILE_RE.match(line) and current not in result:
            result.append(current)
    return result


def extract_plan_task_ids(text: str) -> List[str]:
    tasks = _contract_tasks(text)
    if tasks is not None:
        ids: List[str] = []
        for task in tasks:
            task_id = normalize_plan_task_id(task["id"])
            if task_id not in ids:
                ids.append(task_id)
        return ids
    found: List[Tuple[str, str]] = []
    in_fence = False
    for line in text.splitlines():
        # Code blocks hold file contents or commands, never plan task units.
        if PLAN_FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        task_id, kind = extract_plan_task_id_kind(line)
        if task_id:
            found.append((task_id, kind))
    # A plan with Task/Задача headings or a roadmap table is structured: numbered prose lists
    # inside it are steps, not units (same rule as plan-executor `parse_tasks`). Plans with
    # plain numeric headings ("## 1. Phase" + "- 1.1 ...") keep their list items.
    structured = any(kind in ("task-heading", "table") for _id, kind in found)
    ids: List[str] = []
    seen = set()
    for task_id, kind in found:
        if structured and kind == "list":
            continue
        if task_id not in seen:
            seen.add(task_id)
            ids.append(task_id)
    return ids


def report_covered_ids(text: str) -> set:
    phases, tasks, _ = parse_stage_items(text)
    return {str(item["id"]) for item in phases} | {str(item["id"]) for item in tasks}


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
        # tasks whose Files block creates or modifies code: they need an evidence anchor,
        # an evidence_probe alone does not close them
        "code_tasks": plan_code_task_ids(read_text(args.plan)),
        "errors": [] if not uncovered else [f"task-census-uncovered: {', '.join(uncovered)}"],
    }
    print_json(result)
    return 0 if not uncovered else 1


def list_plan_reports(plan_dir_abs: str, base: str) -> List[Dict[str, object]]:
    items: List[Dict[str, object]] = []
    for name in os.listdir(plan_dir_abs):
        parsed = parse_report_filename(name)
        path = os.path.join(plan_dir_abs, name)
        if parsed and str(parsed["base"]).lower() == base.lower() and os.path.isfile(path):
            items.append({"n": int(parsed["n"]), "final": bool(parsed["final"]), "abs_path": path})
    items.sort(key=lambda item: (int(item["n"]), bool(item["final"])))
    return items


def discover_open_plans(root: str) -> Tuple[List[Dict[str, str]], List[str]]:
    groups: Dict[Tuple[str, str], List[Dict[str, object]]] = {}
    for current_root, dirs, filenames in os.walk(root, topdown=True):
        dirs[:] = [
            d for d in dirs
            if d != ".git" and not is_fixed_excluded(posix_rel(os.path.join(current_root, d), root), True)
        ]
        for name in filenames:
            parsed = parse_report_filename(name)
            if parsed:
                key = (current_root, str(parsed["base"]).lower())
                groups.setdefault(key, []).append({"n": int(parsed["n"]), "final": bool(parsed["final"]), "name": name})
    candidates: List[Dict[str, str]] = []
    skipped: List[str] = []
    for (directory, base), reports in sorted(groups.items()):
        last = max(reports, key=lambda item: (int(item["n"]), bool(item["final"])))
        if last["final"]:
            continue
        masters = [
            name for name in sorted(os.listdir(directory))
            if os.path.splitext(name)[0].lower() == base
            and os.path.splitext(name)[1].lower() in ALLOWED_PLAN_EXTENSIONS
            and os.path.isfile(os.path.join(directory, name))
        ]
        if len(masters) == 1:
            candidates.append(
                {
                    "master_plan": posix_rel(os.path.join(directory, masters[0]), root),
                    "last_report": posix_rel(os.path.join(directory, str(last["name"])), root),
                }
            )
        else:
            found = ", ".join(masters) if masters else "no plan file"
            skipped.append(f"{posix_rel(directory, root) or '.'}: open report '{last['name']}' but {found} for base '{base}'")
    return candidates, skipped


def cmd_discover(args: argparse.Namespace) -> int:
    root = os.path.abspath(args.workspace_root)
    if not os.path.isdir(root):
        print_json({"valid": False, "errors": [f"discover-missing-workspace: {root}"]})
        return 2
    if not args.plan:
        candidates, skipped = discover_open_plans(root)
        print_json({"valid": True, "mode": "workspace", "candidates": candidates, "skipped": skipped, "errors": []})
        return 0 if len(candidates) == 1 else 1
    try:
        master_abs, master_rel = ensure_inside(root, args.plan)
    except ToolError as exc:
        print_json({"valid": False, "errors": [str(exc)]})
        return exc.code
    if not os.path.isfile(master_abs):
        print_json({"valid": False, "errors": [f"discover-missing-plan: {master_rel}"]})
        return 2
    base = os.path.splitext(os.path.basename(master_abs))[0]
    reports = [posix_rel(str(item["abs_path"]), root) for item in list_plan_reports(os.path.dirname(master_abs), base)]
    last = reports[-1] if reports else None
    state = "none" if last is None else ("closed" if last.lower().endswith("-final.md") else "open")
    print_json(
        {
            "valid": True,
            "mode": "plan",
            "master_plan": master_rel,
            "reports": reports,
            "plans_list": [master_rel] + reports,
            "last_report": last,
            "state": state,
            "errors": [],
        }
    )
    return 0


def report_language(text: str, header: Dict[str, str]) -> str:
    language = header.get("language", "")
    if language in VALID_LANGUAGES:
        return language
    return "ru" if SECTION_ALIASES["issues"][0] in text else "en"


def cmd_open_issues(args: argparse.Namespace) -> int:
    if not os.path.isfile(args.report):
        print_json({"valid": False, "errors": [f"file not found: {args.report}"]})
        return 2
    text = read_text(args.report)
    open_issues = [issue for issue in parse_issues(text) if issue["status"] != "fixed"]
    fields = ("id", "level", "status", "title", "linked_items", "evidence", "description", "recommendations")
    blocked_by_drift = any("probe-mutated-workspace" in str(issue["title"]).lower() for issue in open_issues)
    print_json(
        {
            "valid": True,
            "report": args.report,
            "blocked_by_drift": blocked_by_drift,
            "language": report_language(text, parse_header(text)),
            "is_final": os.path.basename(args.report).lower().endswith("-final.md"),
            "open_count": len(open_issues),
            "fix_order": [
                issue["id"]
                for issue in sorted(open_issues, key=lambda item: (LEVEL_RANK.get(str(item["level"]), 9), int(item["id"])))
            ],
            "issues": [{key: issue[key] for key in fields} for issue in open_issues],
            "task": get_section(text, "task") or "",
            "errors": [],
        }
    )
    return 0


def cmd_protect(args: argparse.Namespace) -> int:
    files: Dict[str, str] = {}
    missing = [path for path in args.paths if not os.path.isfile(path)]
    if missing:
        print_json({"valid": False, "errors": [f"file not found: {path}" for path in missing]})
        return 2
    for path in args.paths:
        files[os.path.abspath(path)] = sha256_file(path)
    write_json_file(os.path.abspath(args.out_json), {"algorithm": "sha256-files-v1", "files": files})
    print_json({"valid": True, "path": os.path.abspath(args.out_json), "file_count": len(files), "errors": []})
    return 0


def cmd_assert_protected(args: argparse.Namespace) -> int:
    try:
        snapshot = load_snapshot(args.snapshot_json)
    except (OSError, json.JSONDecodeError, ToolError) as exc:
        print_json({"valid": False, "errors": [str(exc)]})
        return 2
    removed: List[str] = []
    modified: List[str] = []
    for path, digest in sorted(dict(snapshot["files"]).items()):
        if not os.path.isfile(path):
            removed.append(path)
        elif sha256_file(path) != digest:
            modified.append(path)
    valid = not removed and not modified
    print_json({"valid": valid, "removed": removed, "modified": modified, "violations": removed + modified})
    return 0 if valid else 1


def parse_fix_log(text: str) -> Dict[int, str]:
    section = get_section(text, "fix_log") or ""
    return {int(match.group("id")): match.group("state").lower() for match in FIX_LOG_LINE_RE.finditer(section)}


def cmd_mark_fix(args: argparse.Namespace) -> int:
    if not os.path.isfile(args.report):
        print_json({"valid": False, "errors": [f"file not found: {args.report}"]})
        return 2
    if os.path.basename(args.report).lower().endswith("-final.md"):
        print_json({"valid": False, "errors": ["mark-fix-final-report: final reports are closed"]})
        return 1
    with open(args.report, "rb") as handle:
        raw_bytes = handle.read()
    crlf = b"\r\n" in raw_bytes
    text = raw_bytes.decode("utf-8").replace("\r\n", "\n")
    issue = next((item for item in parse_issues(text) if item["id"] == args.issue_id), None)
    if issue is None:
        print_json({"valid": False, "errors": [f"mark-fix-unknown-issue: {args.issue_id}"]})
        return 1
    if issue["status"] == "fixed":
        print_json({"valid": False, "errors": [f"mark-fix-issue-already-fixed: {args.issue_id}"]})
        return 1

    ru = report_language(text, parse_header(text)) == "ru"
    heading = SECTION_ALIASES["fix_log"][0 if ru else 1]
    entry = f"- {'Ошибка' if ru else 'Error'} {args.issue_id}: {args.state}"
    if args.files:
        entry += " | files: " + ", ".join(args.files)
    if args.note:
        entry += " | note: " + " ".join(args.note.split())
    entry_re = re.compile(rf"^- (?:Ошибка|Error) {args.issue_id}:")

    bounds = section_bounds(text, SECTION_ALIASES["fix_log"])
    if bounds is None:
        updated = text.rstrip("\n") + f"\n\n{heading}\n\n{entry}\n"
        action = "added"
    else:
        start, end = bounds
        lines = [line for line in text[start:end].strip("\n").splitlines() if line.strip()]
        replaced = [entry if entry_re.match(line) else line for line in lines]
        action = "updated" if replaced != lines else "added"
        if action == "added":
            replaced.append(entry)
        tail = text[end:]
        body = "\n" + "\n".join(replaced) + ("\n\n" if tail else "\n")
        updated = text[:start] + body + tail
    # Only the Fix Log changes: keep the file's own line endings.
    with open(args.report, "w", encoding="utf-8", newline="\r\n" if crlf else "\n") as handle:
        handle.write(updated)
    print_json({"valid": True, "report": args.report, "issue_id": args.issue_id, "state": args.state, "action": action, "errors": []})
    return 0


def normalize_title(title: object) -> str:
    return " ".join(str(title).lower().split())


def full_audit_required(path: str, text: str) -> bool:
    """An open incremental report with every stage closed and no open issue: only a full pass may close the plan."""
    if os.path.basename(path).lower().endswith("-final.md"):
        return False
    if parse_header(text).get("audit_scope") != "incremental":
        return False
    stages = parse_stage_statuses(text)
    return (
        bool(stages)
        and all(stage["status"] in CLOSED_TASK_MARKERS for stage in stages)
        and all(issue["status"] == "fixed" for issue in parse_issues(text))
    )


def cmd_cycle_check(args: argparse.Namespace) -> int:
    for candidate in (args.prev_report, args.new_report):
        if not os.path.isfile(candidate):
            print_json({"valid": False, "errors": [f"file not found: {candidate}"]})
            return 2
    prev_text = read_text(args.prev_report)
    prev_open = [issue for issue in parse_issues(prev_text) if issue["status"] != "fixed"]
    prev_open_ids = {int(issue["id"]) for issue in prev_open}
    prev_open_titles = {normalize_title(issue["title"]) for issue in prev_open}
    fix_log = parse_fix_log(prev_text)
    needs_user_titles = {normalize_title(i["title"]) for i in prev_open if fix_log.get(int(i["id"])) == "needs-user"}
    applied_titles = {normalize_title(i["title"]) for i in prev_open if fix_log.get(int(i["id"])) == "applied"}

    new_text = read_text(args.new_report)
    new_issues = parse_issues(new_text)
    new_open = [issue for issue in new_issues if issue["status"] != "fixed"]
    fixed_now = [
        issue["id"]
        for issue in new_issues
        if issue["status"] == "fixed"
        and (normalize_title(issue["title"]) in prev_open_titles or int(issue["id"]) in prev_open_ids)
    ]
    needs_user = [issue["id"] for issue in new_open if normalize_title(issue["title"]) in needs_user_titles]
    claimed_not_fixed = [issue["id"] for issue in new_open if normalize_title(issue["title"]) in applied_titles]
    fixable = [issue["id"] for issue in new_open if issue["id"] not in needs_user]

    # The pass after full-audit-required had no open issue to close, so it cannot stall.
    after_full_audit_required = full_audit_required(args.prev_report, prev_text)
    if os.path.basename(args.new_report).lower().endswith("-final.md"):
        action = "complete"
    elif full_audit_required(args.new_report, new_text):
        action = "full-audit-required"
    elif not fixable:
        # Everything left needs a human decision; nothing more to fix automatically.
        action = "ask-user"
    elif not fixed_now and not after_full_audit_required:
        action = "stop-stalled"
    elif args.cycle >= args.limit:
        action = "stop-limit"
    else:
        action = "continue"
    print_json(
        {
            "valid": True,
            "action": action,
            "cycle": args.cycle,
            "limit": args.limit,
            "fixed_now": fixed_now,
            "open_ids": [issue["id"] for issue in new_open],
            "needs_user_ids": needs_user,
            "claimed_not_fixed_ids": claimed_not_fixed,
            "errors": [],
        }
    )
    return 0


def load_audit_snapshot(path: str, plan: str) -> Dict[str, object]:
    """The start snapshot of this audit; ToolError (exit 2) when it is no snapshot or when the plan is not
    under its root (a snapshot of another workspace)."""
    try:
        snapshot = load_snapshot(path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ToolError(f"invalid fingerprint snapshot: {path} ({exc})") from exc
    root = os.path.abspath(str(snapshot.get("root") or ""))
    if not snapshot.get("root") or not path_inside(root, plan):
        raise ToolError(f"snapshot-root-mismatch: the plan is not under the snapshot root {root}")
    return snapshot


def cmd_evidence_fingerprint(args: argparse.Namespace) -> int:
    for candidate in (args.report, args.plan):
        if not os.path.isfile(candidate):
            print_json({"valid": False, "errors": [f"file not found: {candidate}"]})
            return 2
    snapshot = load_audit_snapshot(args.snapshot, args.plan)
    with open(args.report, "rb") as handle:
        raw_bytes = handle.read()
    crlf = b"\r\n" in raw_bytes
    try:
        text = raw_bytes.decode("utf-8").replace("\r\n", "\n")
    except UnicodeDecodeError as exc:
        raise ToolError(f"not-utf8: {args.report}: {exc}") from exc
    try:
        plan_text = read_text(args.plan)
    except UnicodeDecodeError as exc:
        raise ToolError(f"not-utf8: {args.plan}: {exc}") from exc
    table, warnings = evidence_table(text, plan_text, snapshot, args.plan)
    ru = report_language(text, parse_header(text)) == "ru"
    updated = put_evidence_section(text, render_evidence_section(table, ru))
    with open(args.report, "w", encoding="utf-8", newline="\r\n" if crlf else "\n") as handle:
        handle.write(updated)
    print_json(
        {
            "valid": True,
            "report": args.report,
            "file_count": len(table),
            "excluded": [path for path, value in table.items() if value == "excluded"],
            "missing": [path for path, value in table.items() if value == "missing"],
            "warnings": warnings,
            "errors": [],
        }
    )
    return 0


def parse_evidence_table(text: str) -> Optional[Dict[str, str]]:
    """{path: value} of the report's evidence section; None for a report without one."""
    section = get_section(text, "evidence")
    if section is None:
        return None
    table: Dict[str, str] = {}
    for line in evidence_lines(section):
        match = EVIDENCE_ROW_RE.match(line)
        if match:
            table[match.group("path")] = match.group("value")
    return table


def parent_ids(task_id: str) -> List[str]:
    """`12.1.3` → [`12.1`, `12`]."""
    parts = task_id.split(".")
    return [".".join(parts[:count]) for count in range(len(parts) - 1, 0, -1)]


def linked_ids(value: str, known: Sequence[str]) -> List[str]:
    """Task ids named in an issue's linked_items that the report or the plan has, in order, once each."""
    found: List[str] = []
    for token in re.split(r"[,;\s]+", value or ""):
        task_id = normalize_plan_task_id(token.strip("`'\".()[]"))
        if task_id in known and task_id not in found:
            found.append(task_id)
    return found


def stub_title(item: Dict[str, object]) -> str:
    """Title of a report stage item without its evidence: the stub line's fallback when the plan has no title."""
    title = re.split(r"\s(?:evidence_anchor|evidence_probe|evidence|confidence|verification)\s*[:=]", str(item["title"]), maxsplit=1)[0]
    return " ".join(ANCHOR_RE.sub("", title).split()).strip(" —-:")


def rescan_scope(plan: str, last_report: str, snapshot: Dict[str, object], ratio: float) -> Dict[str, object]:
    """Tasks of the last report to audit again, by its evidence fingerprint against the start snapshot."""
    report_text = read_text(last_report)
    plan_text = read_text(plan)
    files = dict(snapshot["files"])
    table = parse_evidence_table(report_text)
    plan_sha_changed = parse_header(report_text).get("master_plan_sha256", "").lower() != sha256_file(plan)
    phases, tasks, _ = parse_stage_items(report_text)
    items = sorted(phases + tasks, key=lambda item: int(item["line_start"]))
    report_ids: List[str] = []
    for item in items:
        if str(item["id"]) not in report_ids:
            report_ids.append(str(item["id"]))
    plan_ids = extract_plan_task_ids(plan_text)
    all_ids = report_ids + [task_id for task_id in plan_ids if task_id not in report_ids]

    # Rows of the pipeline's own files (an older report wrote BACKLOG.md as `excluded`) send no task to re-audit.
    plan_dir = plan_dir_of(plan, str(snapshot["root"]))
    rows = {path: value for path, value in (table or {}).items() if not is_pipeline_file(path, plan_dir)}
    changed = sorted(path for path, value in rows.items() if path in files and value not in ("excluded", "missing") and files[path] != value)
    gone = sorted(path for path, value in rows.items() if path not in files and value not in ("excluded", "missing"))
    unverified = sorted(path for path, value in rows.items() if value in ("excluded", "missing"))
    suspect = set(changed) | set(gone) | set(unverified)

    reaudit = set()
    for item_id, paths in stage_anchor_paths(report_text).items():
        if suspect.intersection(paths):
            reaudit.add(item_id)
    for task_id, paths in (plan_task_files(plan_text) or {}).items():
        if suspect.intersection(paths):
            reaudit.add(task_id)
    for item in items:
        raw = str(item["raw_text"])
        if item["status"] != "✅":
            reaudit.add(str(item["id"]))
        elif EVIDENCE_PROBE_RE.search(raw) and not ANCHOR_RE.search(raw):
            reaudit.add(str(item["id"]))  # a probe is cheap to repeat and is the only evidence
    issues: List[Dict[str, object]] = []
    for issue in parse_issues(report_text):
        linked = linked_ids(str(issue["linked_items"]), all_ids)
        issues.append({"id": issue["id"], "status": issue["status"], "linked_items": linked})
        if issue["status"] != "fixed":
            reaudit.update(linked)
    reaudit.update(task_id for task_id in plan_ids if task_id not in report_ids)
    for task_id in list(reaudit):
        # A parent's marker is the worst of its children (REPORT-FORMAT, propagation).
        reaudit.update(parent for parent in parent_ids(task_id) if parent in all_ids)
    ordered = [task_id for task_id in all_ids if task_id in reaudit]

    if plan_sha_changed:
        scope, reason = "full", "plan-changed"
    elif table is None:
        scope, reason = "full", "no-evidence-fingerprint"
    elif len(ordered) > ratio * len(all_ids):
        scope, reason = "full", "ratio"
    else:
        scope, reason = "incremental", f"{len(ordered)} of {len(all_ids)} tasks touched"
    contract = _contract_tasks(plan_text) or []
    plan_titles = {normalize_plan_task_id(task["id"]): str(task["title"]) for task in contract}
    ranges = {normalize_plan_task_id(task["id"]): [int(task["line_start"]), int(task["line_end"])] for task in contract}
    report_titles = {str(item["id"]): stub_title(item) for item in items}
    return {
        "valid": True,
        "scope": scope,
        "reason": reason,
        "plan_sha_changed": plan_sha_changed,
        "changed_files": changed,
        "missing_files": gone,
        "unverified_files": unverified,
        "reaudit": ordered,
        "carry": [task_id for task_id in report_ids if task_id not in reaudit],
        # audit_tasks of the draft: run-stats and validate-report --plan know only the plan's task ids
        "audit_tasks": [task_id for task_id in ordered if task_id in plan_ids],
        "titles": {task_id: plan_titles.get(task_id) or report_titles.get(task_id, "") for task_id in ordered},
        # the plan lines of each re-audited task: the incremental pass reads these, never the whole plan
        "line_ranges": {task_id: ranges[task_id] for task_id in ordered if task_id in ranges},
        "issues": issues,
        "task_count": len(all_ids),
        "ratio": ratio,
        "plan": os.path.abspath(plan),
        "last_report": os.path.abspath(last_report),
        "root": os.path.abspath(str(snapshot["root"])),
        "errors": [],
    }


def cmd_rescan_scope(args: argparse.Namespace) -> int:
    for candidate in (args.plan, args.last_report):
        if not os.path.isfile(candidate):
            print_json({"valid": False, "errors": [f"file not found: {candidate}"]})
            return 2
    if not 0 < args.ratio <= 1:
        print_json({"valid": False, "errors": [f"--ratio must be in (0, 1]: {args.ratio}"]})
        return 2
    snapshot = load_audit_snapshot(args.snapshot, args.plan)
    try:
        result = rescan_scope(args.plan, args.last_report, snapshot, args.ratio)
    except UnicodeDecodeError as exc:
        raise ToolError(f"not-utf8: the plan or the last report is not UTF-8 ({exc})") from exc
    print_json(result)
    return 0


def load_json_input(path: str) -> object:
    """JSON the agent saved: UTF-8 (a BOM allowed) or UTF-16 with a BOM (PowerShell `>` redirection)."""
    with open(path, "rb") as handle:
        raw = handle.read()
    return json.loads(raw.decode("utf-16" if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig"))


def carry_stage_lines(text: str, reaudit: Sequence[str], titles: Dict[str, str]) -> Tuple[str, int]:
    """The stages section of the last report: carried items with their detail lines byte for byte, one stub
    line per re-audited item at its old indent, stubs for items the report did not have at the end."""
    lines = text.splitlines(keepends=True)
    phases, tasks, _ = parse_stage_items(text)
    starts = {int(item["line_start"]): str(item["id"]) for item in phases + tasks}
    wanted = set(reaudit)

    def stub(indent: str, task_id: str) -> str:
        label = task_id if "." in task_id else task_id + "."
        return indent + "- " + " ".join(part for part in (label, titles.get(task_id, ""), REAUDIT_MARKER) if part) + "\n"

    out: List[str] = []
    current: Optional[str] = None
    seen = set()
    for number, _line in section_lines(text, "stages"):
        raw = lines[number - 1]
        if number in starts:
            current = starts[number]
            seen.add(current)
            out.append(stub(raw[: len(raw) - len(raw.lstrip(" "))], current) if current in wanted else raw)
        elif current in wanted and raw.strip():
            continue  # the re-audit writes the evidence of this item again
        else:
            out.append(raw)
    body = "".join(out).strip("\n")
    extra = "".join(stub("  " * task_id.count("."), task_id) for task_id in reaudit if task_id not in seen)
    if extra:
        body = (body + "\n" + extra).strip("\n")
    return body, len(seen - wanted)


def carry_issue_blocks(text: str) -> Tuple[str, List[int]]:
    """Every issue block of the last report with its number; the head line of an open one marked re-verify."""
    bounds = section_bounds(text, SECTION_ALIASES["issues"])
    body = text[bounds[0] : bounds[1]].strip("\n") if bounds else ""
    open_ids = sorted(int(issue["id"]) for issue in parse_issues(text) if issue["status"] != "fixed")
    out: List[str] = []
    for line in body.split("\n"):
        head = ISSUE_HEAD_RE.match(line)
        if head and int(head.group("num")) in open_ids and REVERIFY_MARKER not in line:
            line = line.rstrip() + " " + REVERIFY_MARKER
        out.append(line)
    return "\n".join(out), open_ids


def carry_forward_draft(text: str, scope: Dict[str, object], header: Dict[str, object]) -> Tuple[str, Dict[str, object]]:
    """The incremental report's draft: frontmatter from bootstrap.report_header, carried stage lines and stubs,
    the last report's issue blocks, stub bodies for Additional Context and Task."""

    def value(item: object) -> str:
        return "null" if item is None else str(item)

    index = 0 if value(header["language"]) == "ru" else 1
    reaudit = [str(task_id) for task_id in scope.get("reaudit") or []]
    audit_tasks = [str(task_id) for task_id in scope.get("audit_tasks") or []]
    titles = {str(key): str(title) for key, title in dict(scope.get("titles") or {}).items()}
    stages, carried = carry_stage_lines(text, reaudit, titles)
    issues, reverify = carry_issue_blocks(text)
    frontmatter = [
        "---",
        f"master_plan_path: {value(header['master_plan_path'])}",
        f"master_plan_sha256: {value(header['master_plan_sha256'])}",
        f"master_plan_size: {value(header['master_plan_size'])}",
        f"audited_at: {value(header['audited_at'])}",
        f"audit_iteration: {value(header['audit_iteration'])}",
        f"consecutive_open_invocations: {value(header['consecutive_open_invocations_if_open'])}",
        f"previous_report_path: {value(header['previous_report_path'])}",
        f"previous_report_sha256: {value(header['previous_report_sha256'])}",
        f"language: {value(header['language'])}",
        "audit_scope: incremental",
        f"audit_tasks: [{', '.join(audit_tasks)}]",
        "---",
    ]
    parts = [
        "\n".join(frontmatter),
        f"{SECTION_ALIASES['title'][index]} {value(header['audit_iteration'])}",
        SECTION_ALIASES["stages"][index],
        stages,
        SECTION_ALIASES["issues"][index],
        issues,
        SECTION_ALIASES["context"][index],
        REAUDIT_MARKER,
        SECTION_ALIASES["task"][index],
        REAUDIT_MARKER,
    ]
    draft = "\n\n".join(part for part in parts if part) + "\n"
    return draft, {"carried": carried, "stubs": len(reaudit), "reverify_issues": reverify, "audit_tasks": audit_tasks}


def cmd_carry_forward(args: argparse.Namespace) -> int:
    if not os.path.isfile(args.last_report):
        print_json({"valid": False, "errors": [f"file not found: {args.last_report}"]})
        return 2
    if os.path.exists(args.out):
        print_json({"valid": False, "errors": [f"report-exists: reports are immutable: {args.out}"]})
        return 2
    try:
        scope = load_json_input(args.scope)
        header = load_json_input(args.header)
    except (OSError, ValueError) as exc:
        print_json({"valid": False, "errors": [f"bad-input-json: {exc}"]})
        return 2
    if not isinstance(scope, dict) or not isinstance(header, dict):
        print_json({"valid": False, "errors": ["bad-input-json: --scope and --header must hold JSON objects"]})
        return 2
    if isinstance(header.get("report_header"), dict):
        header = header["report_header"]  # the whole bootstrap result is accepted too
    root = os.path.abspath(str(scope.get("root") or ""))
    inside = [path for path in (args.scope, args.header) if scope.get("root") and path_inside(root, path)]
    if inside:
        # inside the workspace they would be assert-readonly violations and foreign changes for the executor
        print_json({"valid": False, "errors": ["inputs-inside-workspace: keep them in the OS temp dir: " + ", ".join(inside)]})
        return 2
    if os.path.normcase(os.path.abspath(str(scope.get("last_report") or ""))) != os.path.normcase(os.path.abspath(args.last_report)):
        print_json({"valid": False, "errors": [f"scope-mismatch: --scope was computed for {scope.get('last_report')}"]})
        return 2
    missing = [field for field in CARRY_HEADER_FIELDS if field not in header]
    if missing:
        print_json({"valid": False, "errors": ["header-missing-fields: " + ", ".join(missing)]})
        return 2
    if scope.get("scope") != "incremental":
        print_json({"valid": False, "errors": [f"use-full-pass: rescan-scope chose a full pass ({scope.get('reason')})"]})
        return 1
    with open(args.last_report, "rb") as handle:
        raw_bytes = handle.read()
    crlf = b"\r\n" in raw_bytes
    draft, summary = carry_forward_draft(raw_bytes.decode("utf-8").replace("\r\n", "\n"), scope, header)
    with open(args.out, "x", encoding="utf-8", newline="\r\n" if crlf else "\n") as handle:
        handle.write(draft)
    print_json({"valid": True, "path": args.out, **summary, "errors": []})
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="plan-resolver helper utility")
    subparsers = parser.add_subparsers(dest="command", required=True)

    bootstrap = subparsers.add_parser("bootstrap")
    bootstrap.add_argument("workspace_root")
    bootstrap.add_argument("plan")
    bootstrap.add_argument("reports", nargs="*")
    bootstrap.add_argument("--full", action="store_true", help="a full subsequent pass (the user's `full` argument)")
    bootstrap.set_defaults(func=cmd_bootstrap)

    preflight = subparsers.add_parser("preflight")
    preflight.add_argument("plan_dir")
    preflight.add_argument("next_open_name")
    preflight.add_argument("next_final_name")
    preflight.set_defaults(func=cmd_preflight)

    fingerprint = subparsers.add_parser("fingerprint-workspace")
    fingerprint.add_argument("root")
    fingerprint.add_argument("out_json")
    fingerprint.add_argument("--base", help="previous snapshot; unchanged size+mtime files reuse its hashes")
    fingerprint.set_defaults(func=cmd_fingerprint_workspace)

    parse_report = subparsers.add_parser("parse-report")
    parse_report.add_argument("report")
    parse_report.set_defaults(func=cmd_parse_report)

    validate_report_parser = subparsers.add_parser("validate-report")
    validate_report_parser.add_argument("report")
    validate_report_parser.add_argument("--root", help="workspace root; verifies that evidence anchors point at real lines")
    validate_report_parser.add_argument("--plan", help="master plan; tasks with Create/Modify files cannot be closed by evidence_probe alone")
    validate_report_parser.set_defaults(func=cmd_validate_report)

    diff_parser = subparsers.add_parser("snapshot-diff")
    diff_parser.add_argument("before_json")
    diff_parser.add_argument("after_json")
    diff_parser.set_defaults(func=cmd_snapshot_diff)

    readonly = subparsers.add_parser("assert-readonly")
    readonly.add_argument("start_json")
    readonly.add_argument("current_json")
    readonly.add_argument("allowed_paths", nargs="+")
    readonly.set_defaults(func=cmd_assert_readonly)

    census = subparsers.add_parser("task-census")
    census.add_argument("plan")
    census.add_argument("report")
    census.set_defaults(func=cmd_task_census)

    discover = subparsers.add_parser("discover")
    discover.add_argument("workspace_root")
    discover.add_argument("plan", nargs="?")
    discover.set_defaults(func=cmd_discover)

    open_issues = subparsers.add_parser("open-issues")
    open_issues.add_argument("report")
    open_issues.set_defaults(func=cmd_open_issues)

    protect = subparsers.add_parser("protect")
    protect.add_argument("out_json")
    protect.add_argument("paths", nargs="+")
    protect.set_defaults(func=cmd_protect)

    protected = subparsers.add_parser("assert-protected")
    protected.add_argument("snapshot_json")
    protected.set_defaults(func=cmd_assert_protected)

    mark_fix = subparsers.add_parser("mark-fix")
    mark_fix.add_argument("report")
    mark_fix.add_argument("issue_id", type=int)
    mark_fix.add_argument("state", choices=FIX_STATES)
    mark_fix.add_argument("--files", nargs="*", default=[])
    mark_fix.add_argument("--note", default="")
    mark_fix.set_defaults(func=cmd_mark_fix)

    cycle = subparsers.add_parser("cycle-check")
    cycle.add_argument("prev_report")
    cycle.add_argument("new_report")
    cycle.add_argument("cycle", type=int)
    cycle.add_argument("limit", nargs="?", type=int, default=2)
    cycle.set_defaults(func=cmd_cycle_check)

    evidence = subparsers.add_parser("evidence-fingerprint")
    evidence.add_argument("report")
    evidence.add_argument("--snapshot", required=True, help="the start snapshot of this audit (fingerprint-workspace)")
    evidence.add_argument("--plan", required=True, help="master plan; the files of its tasks' Files blocks are evidence too")
    evidence.set_defaults(func=cmd_evidence_fingerprint)

    rescan = subparsers.add_parser("rescan-scope")
    rescan.add_argument("plan")
    rescan.add_argument("last_report")
    rescan.add_argument("--snapshot", required=True, help="the start snapshot of this audit")
    rescan.add_argument("--ratio", type=float, default=FULL_SCOPE_RATIO, help="share of tasks above which the pass is full")
    rescan.set_defaults(func=cmd_rescan_scope)

    carry = subparsers.add_parser("carry-forward")
    carry.add_argument("last_report")
    carry.add_argument("--scope", required=True, help="rescan-scope output saved in the OS temp dir")
    carry.add_argument("--header", required=True, help="bootstrap.report_header (or the whole bootstrap output) in the OS temp dir")
    carry.add_argument("--out", required=True, help="the new report (bootstrap.next_open_path); must not exist")
    carry.set_defaults(func=cmd_carry_forward)

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
