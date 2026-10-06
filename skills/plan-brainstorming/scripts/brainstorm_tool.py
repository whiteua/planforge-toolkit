#!/usr/bin/env python3
"""Deterministic helper for the plan-brainstorming skill.

- spec-check: verifies a written spec against references/spec-contract.md
  (8 headings in order, non-empty sections, empty Open Questions, Tier line).
- findings-parse: validates a JSON list of code-review findings, assigns
  stable ids (F1..Fn in input order), optionally checks file/line locations.
- findings-coverage: verifies that a spec mentions every finding id.
- settings: chain settings, environments and backlog of a spec, plan, roadmap
  or part by the single reading rule (spec; plan header only for old specs).
- plan-tasks: tasks of a plan by the plan format contract (`### Task N: <title>`): id, title,
  line range, Files, Preconditions refs, size and SHA-1 of the body; malformed and duplicate
  headings; `incomplete` and `marker_spec_sha` for a plan plan-writing is still writing (its marker
  `> Writing: in progress`). The one task parser of plan_tool, executor_tool, resolver_tool, splitter_tool and
  chain_tool (parse_plan_tasks, loaded by path).
- detect-lang: dialogue language of a goal file or findings JSON
  (`ru` when more than 5% of the letters are Cyrillic, otherwise `en`).
- inputs: kind, language and size of each input file of a call, the mode of the call and plan_root.
- spec-set-check: paths and symbols that several specs of a goal name, pairs that do not mention
  each other, shared numbered sections.
- roadmap-write / roadmap-check / roadmap-parse: the goal roadmap <goal>-roadmap.md.
- journal-*: the chain journal <goal>-chain.json next to the spec: stages of
  every plan, questions Qn, out-of-plan findings Fn and an append-only event
  log; journal-export-findings writes <goal>-followups.json (findings-parse format);
  journal-show, journal-validate and journal-reconcile read, check and repair it.

Stdlib only. Python 3.8+.

Commands:
  spec-check        <spec.md>
  findings-parse    <findings.json|-> [--root DIR]
  findings-coverage <findings.json|-> <spec.md>
  settings          <spec|plan|roadmap|part.md>
  plan-tasks        <plan|part.md>
  detect-lang       <file|->
  inputs            [<file>…] [--note TEXT]
  spec-set-check    <dir> [--goal G] [--specs <file>…]
  roadmap-write     <dir> --graph <json> [--lang ru|en] [--force]
  roadmap-check     <roadmap.md>
  roadmap-parse     <roadmap.md>
  backlog-append    <root> --section S --source "skill, artifact" --item TEXT [--lang ru|en] [--plain] [--date D]
  backlog-parse     <BACKLOG.md> [--section S] [--state open|done|cancelled|all]
  backlog-mark      <root> --section S --item TEXT
  backlog-unmark    <root> --section S --item TEXT
  backlog-sweep     <root> --section S [--journal J]
  journal-path      <spec|plan|roadmap|part.md> [--create]
  journal-event     <journal> --skill S --plan P --stage ST --status X [--reason R] [--input F]
                    [--artifact k=v|k[]=v]... [--data JSON] [--spec SPEC]
  journal-unit      <journal> --plan P --kind unit-begin|unit-finish --data JSON
  journal-question  <journal> --skill S --plan P --stage ST --text T [--option O]... [--answer A] [--spec SPEC]
  journal-answer    <journal> <Qn> (--answer A | --applied)
  journal-finding   <journal> --skill S --plan P --file F [--line N] --summary T --failure-scenario T [--backlog-root R]
  journal-commit    <journal> --plan P --sha SHA --subject S [--file F]...
  journal-export-findings <journal>
  journal-show      <journal> [--plan P]
  journal-validate  <journal>
  journal-reconcile <journal> [--rebuild]

Exit codes: 0 ok, 1 contract/validation/coverage failure, 2 usage or I/O error.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Tuple


REQUIRED_TEXT_FIELDS = ("file", "summary", "failure_scenario")
OPTIONAL_TEXT_FIELDS = ("category", "short_summary", "verdict", "outcome")
KNOWN_FIELDS = set(REQUIRED_TEXT_FIELDS) | set(OPTIONAL_TEXT_FIELDS) | {"line"}
ID_RE = re.compile(r"\bF(\d+)\b")

SPEC_HEADINGS = (
    "# Goal",
    "## Architecture",
    "## Components",
    "## Data Flow",
    "## Error Handling",
    "## Testing Strategy",
    "## Out of Scope",
    "## Open Questions",
)
TIERS = ("Quick", "Standard", "Deep")
# "> Tier: Quick", "> **Tier:** Quick" and "> **Tier**: Quick" are all accepted.
TIER_RE = re.compile(r"^>\s*(?:\*\*)?Tier:?(?:\*\*)?:?\s*(?P<tier>[A-Za-z]+)\s*$")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
# CommonMark code fence: three or more backticks or tildes after up to three spaces; the info string of a
# backtick fence may not contain a backtick. A fence closes only on a line of the same character with at
# least the opening length and nothing else, so a ```` block may hold ``` lines (F6/F13).
FENCE_OPEN_RE = re.compile(r"^ {0,3}(?P<fence>`{3,}|~{3,})(?P<info>.*)$")
PLACEHOLDER_RE = re.compile(r"\b(TBD|TODO|FIXME)\b")
NONE_TEXT = "(none)"
# Size budget of one plan, shared by spec-check (volume), plan_tool.py plan-check (plan-oversized,
# with equal fallback values) and the splitter gate; a contract test in plan-writing compares them.
SIZE_BUDGET = {"tasks": 40, "bytes": 150000}
# Plan tasks per Components item by tier: estimate_tasks = components × factor + testing items.
TIER_TASK_FACTOR = {"Quick": 1, "Standard": 2, "Deep": 3}
VOLUME_UNKNOWN = "volume-unknown: Components has no list items, table rows or subheadings"
# Same Cyrillic range and threshold as executor_tool.py, splitter_tool.py and resolver_tool.py.
CYRILLIC_RE = re.compile("[Ѐ-ӿ]")
LANG_THRESHOLD = 0.05
CHAIN_VALUES = {
    "split": ("auto", "always", "never"),
    "revision": ("quick", "standard", "deep"),
    "stop": ("pragmatic", "strict"),
    "resolver": ("audit", "auto", "skip"),
}
# Defaults for keys missing in Chain; "revision" defaults to the tier (see _complete_chain).
CHAIN_DEFAULTS = {"split": "auto", "stop": "pragmatic", "resolver": "audit"}
# "> Chain: …", "> **Chain:** …" and "> **Chain**: …", the same forms as the Tier line.
METADATA_RE = re.compile(r"^>\s*(?:\*\*)?(?P<key>Chain|Environment|Backlog)(?::\*\*|\*\*:|:)\s*(?P<body>.*?)\s*$")
# A line above '# Goal' that names a settings key but matches neither METADATA_RE nor TIER_RE
# ("> chain:", "> Chain :"): an error in spec-check, a warning in settings, never ignored.
MALFORMED_METADATA_RE = re.compile(r"^>\s*(?:\*\*)?(?i:chain|environment|backlog|tier)\b")
RIGHT_VALUES = ("run", "task", "deny")
QUOTE_PATTERN = r"\"[^\"]+\"|«[^»]+»|“[^”]+”"
# Interface markers a question UI adds to an option; they are not the user's words.
UI_MARKER_RE = re.compile(r"\((?:recommended|рекомендую)\)", re.IGNORECASE)
# `name` (test|prod) — read=…, write=… — "question — answer" (YYYY-MM-DD). The rights part is
# optional here so that a line without rights gets a precise error, not "does not match".
SPEC_ENV_RE = re.compile(
    r"^`(?P<name>[^`]+)`\s*\((?P<kind>test|prod)\)\s*[—–-]\s*"
    r"(?:(?P<rights>[^\"«“]*?)\s*[—–-]\s*)?"
    r"(?P<quote>" + QUOTE_PATTERN + r")\s*\((?P<date>\d{4}-\d{2}-\d{2})\)$"
)
# New form: - `name` (test; read=run, write=run) — "quote" (date); old form: - `name` (test) — "quote" (date).
# The parenthesised tail after the quote is optional and free: plan-check never required a date in
# old plans, and old entries carry tails such as "(user, 2026-09-30)". `date` keeps only YYYY-MM-DD.
PLAN_ENV_RE = re.compile(
    r"^\s*[-*]\s+`(?P<name>[^`]+)`\s*\((?P<kind>test|prod)(?:\s*;\s*(?P<rights>[^)]*))?\)\s*[—–-]\s*"
    r"(?P<quote>" + QUOTE_PATTERN + r")(?:\s*\((?P<date>[^)]*)\))?\s*$"
)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
LINK_TARGET_RE = re.compile(r"\[[^\]]*\]\((?P<target>[^)\s]+)\)")
# Plan tasks (parse_plan_tasks): the task heading of the plan format contract, "### Task N: <title>";
# a task-like heading without "<id>:" is malformed. Files lines follow executor_tool.extract_files.
PLAN_TASK_HEADING_RE = re.compile(r"^(?P<hashes>#{2,4})\s+(?:Task|Задача)\s+(?P<id>\S+?)\s*:\s*(?P<title>\S.*?)\s*$")
PLAN_TASKISH_RE = re.compile(r"^#{2,4}\s+(?:Task|Задача)\b", re.IGNORECASE)
PLAN_HEADING_RE = re.compile(r"^(?P<hashes>#{1,6})\s+")
PLAN_CHECKPOINT_RE = re.compile(r"^Checkpoint\b", re.IGNORECASE)
PLAN_FILES_BLOCK_RE = re.compile(r"^\*\*(?:files|файлы):\*\*\s*$", re.IGNORECASE)
PLAN_FILE_ACTION_RE = re.compile(r"^\s*[-*]\s*(create|modify|test|delete|move|создать|изменить|тест)\s*:", re.IGNORECASE)
PLAN_CODE_PATH_RE = re.compile(r"`([^`\s]+?\.[A-Za-z0-9]+)(?::(\d+(?:-\d+)?))?`")
PLAN_MD_LINK_RE = re.compile(r"\[([^\]]+\.[A-Za-z0-9]+)\]\(([^)]+)\)")
# A name with < or > (a placeholder such as <base>-diffs.md) is no path of an action line (spec 1 of plan-refactoring-04).
PLAN_PLACEHOLDER_RE = re.compile(r"[<>]")
PLAN_PRECONDITIONS_RE = re.compile(r"^\*\*Preconditions:\*\*")
PLAN_TASK_REF_RE = re.compile(r"\b(?:Task|Задача)\s+(\d+(?:\.\d+)*)\b")
PLAN_NUMERIC_ID_RE = re.compile(r"^[0-9]+(?:\.[0-9]+)*$")
PLAN_FIELD_RE = re.compile(r"^\*\*(?P<name>Spec|Tier|Chain|Backlog):\*\*\s*(?P<value>.*?)\s*$")
PLAN_ENVIRONMENTS_RE = re.compile(r"^\*\*Environments:\*\*\s*$")
PLAN_ENV_ITEM_RE = re.compile(r"^\s*[-*]\s+`")
# Roadmap and part files point to the master plan in one of their first lines. Plain and bold
# forms as for the Tier line; a target with spaces is written in angle brackets: [x](<a b/p.md>).
SOURCE_RE = re.compile(
    r"^>\s*(?:\*\*)?(?:Source|Источник)(?::\*\*|\*\*:|:)\s*\[[^\]]*\]"
    r"\((?P<open><)?(?P<target>(?(open)[^<>\n]+|[^<>)\s]+))(?(open)>)\)"
)
# A goal roadmap (<goal>-roadmap.md, written by roadmap-write) names its goal in one of its first ten
# lines: "> Goal: <goal>", plain and bold forms as for the Tier line. executor_tool._GOAL_ROADMAP_RE is
# a copy of this pattern (contract test in plan-executor/tests).
GOAL_ROADMAP_RE = re.compile(r"^>\s*(?:\*\*)?Goal(?::\*\*|\*\*:|:)\s*(?P<goal>\S.*?)\s*$")


class InputError(Exception):
    """Unreadable input or malformed JSON (exit 2)."""


def _read_source(source: str) -> str:
    if source == "-":
        return sys.stdin.read()
    try:
        with open(source, "r", encoding="utf-8-sig") as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError) as exc:  # a file not in UTF-8 is unreadable input, not a crash
        raise InputError(f"cannot read {source}: {exc}") from exc


def _normalize_path(path: str) -> str:
    path = path.strip().replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return path


def _count_lines(path: str) -> int:
    with open(path, "rb") as fh:
        data = fh.read()
    if not data:
        return 0
    return data.count(b"\n") + (0 if data.endswith(b"\n") else 1)


def cyrillic_ratio(text: str) -> float:
    """Share of Cyrillic letters among all letters; 0.0 when there are no letters."""
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for ch in letters if CYRILLIC_RE.match(ch)) / len(letters)


def detect_lang_text(text: str) -> str:
    """`ru` when more than 5% of the letters are Cyrillic, otherwise `en` (no letters -> `en`)."""
    return "ru" if cyrillic_ratio(text) > LANG_THRESHOLD else "en"


def _text_for_lang(text: str) -> str:
    """Findings JSON may escape Cyrillic as \\uXXXX: detect over its decoded string values."""
    try:
        data = json.loads(text)
    except ValueError:
        return text
    parts: List[str] = []
    stack = [data]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict):
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    return "\n".join(parts)


def load_findings(text: str) -> Tuple[List[Dict[str, Any]], List[str], List[str]]:
    """Validate raw JSON text. Returns (findings, errors, warnings)."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InputError(f"invalid JSON: {exc}") from exc

    # Accept the bare array and the {"findings": [...]} report wrapper.
    if isinstance(data, dict) and isinstance(data.get("findings"), list):
        data = data["findings"]
    if not isinstance(data, list):
        raise InputError("expected a JSON array of findings (or an object with a 'findings' array)")

    findings: List[Dict[str, Any]] = []
    errors: List[str] = []
    warnings: List[str] = []

    if not data:
        errors.append("findings list is empty")

    for index, item in enumerate(data):
        fid = f"F{index + 1}"
        if not isinstance(item, dict):
            errors.append(f"{fid}: item must be an object")
            continue

        entry: Dict[str, Any] = {"id": fid}
        for field in REQUIRED_TEXT_FIELDS:
            value = item.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{fid}: '{field}' must be a non-empty string")
            else:
                entry[field] = value.strip()
        if "file" in entry:
            entry["file"] = _normalize_path(entry["file"])

        line = item.get("line")
        if line is None:
            entry["line"] = None
        elif isinstance(line, bool) or not isinstance(line, int) or line < 1:
            errors.append(f"{fid}: 'line' must be a positive integer when present")
        else:
            entry["line"] = line

        for field in OPTIONAL_TEXT_FIELDS:
            value = item.get(field)
            if value is None:
                continue
            if not isinstance(value, str):
                errors.append(f"{fid}: '{field}' must be a string when present")
            else:
                entry[field] = value.strip()

        unknown = sorted(set(item) - KNOWN_FIELDS)
        if unknown:
            warnings.append(f"{fid}: unknown fields kept as-is: {', '.join(unknown)}")
            entry["extra"] = {key: item[key] for key in unknown}

        findings.append(entry)

    seen: Dict[Tuple[Any, ...], str] = {}
    for entry in findings:
        key = (entry.get("file"), entry.get("line"), entry.get("summary"))
        if None in (key[0], key[2]):
            continue
        if key in seen:
            warnings.append(f"{entry['id']}: duplicate of {seen[key]} (same file, line and summary)")
        else:
            seen[key] = entry["id"]

    return findings, errors, warnings


def check_locations(findings: List[Dict[str, Any]], root: str) -> List[str]:
    """Annotate each finding with a 'location' status. Returns warnings."""
    warnings: List[str] = []
    line_counts: Dict[str, Optional[int]] = {}
    for entry in findings:
        rel = entry.get("file")
        if not rel:
            continue
        full = os.path.join(root, rel)
        if rel not in line_counts:
            line_counts[rel] = _count_lines(full) if os.path.isfile(full) else None
        total = line_counts[rel]
        if total is None:
            entry["location"] = "file_missing"
            warnings.append(f"{entry['id']}: file not found under root: {rel}")
        elif entry.get("line") is not None and entry["line"] > total:
            entry["location"] = "line_out_of_range"
            warnings.append(f"{entry['id']}: line {entry['line']} beyond end of {rel} ({total} lines)")
        else:
            entry["location"] = "ok"
    return warnings


def _fence_scan(text: str) -> List[Tuple[int, str, str]]:
    """(line number, raw line, kind) for every line: kind is `text` outside code fences, `fence` for an
    opening or closing fence line, `code` inside a fence. Fences follow CommonMark: an opening fence of
    N backticks or tildes is closed only by a line of the same character, at least N long, with nothing
    else on it; an unclosed fence runs to the end of the text."""
    result: List[Tuple[int, str, str]] = []
    open_char = ""
    open_len = 0
    for number, raw in enumerate(text.splitlines(), start=1):
        match = FENCE_OPEN_RE.match(raw)
        if open_char:
            closes = (match is not None and match.group("fence")[0] == open_char
                      and len(match.group("fence")) >= open_len and not match.group("info").strip())
            if closes:
                open_char, open_len = "", 0
                result.append((number, raw, "fence"))
            else:
                result.append((number, raw, "code"))
        elif match is not None and not (match.group("fence")[0] == "`" and "`" in match.group("info")):
            open_char, open_len = match.group("fence")[0], len(match.group("fence"))
            result.append((number, raw, "fence"))
        else:
            result.append((number, raw, "text"))
    return result


def _unfenced_lines(text: str) -> List[Tuple[int, str]]:
    """(line number, right-stripped line) for every line outside code fences."""
    return [(number, raw.rstrip()) for number, raw, kind in _fence_scan(text) if kind == "text"]


def _parse_chain(body: str, where: str, errors: List[str]) -> Dict[str, str]:
    """Parse 'key=value; key=value'. Only the keys present are returned."""
    chain: Dict[str, str] = {}
    for item in (part.strip() for part in body.split(";")):
        if not item:
            continue
        key, sep, value = (piece.strip() for piece in item.partition("="))
        if not sep or not key or not value:
            errors.append(f"{where}: chain item '{item}' is not key=value")
        elif key not in CHAIN_VALUES:
            errors.append(f"{where}: unknown chain key '{key}' (allowed: {', '.join(CHAIN_VALUES)})")
        elif value not in CHAIN_VALUES[key]:
            allowed = ", ".join(CHAIN_VALUES[key])
            errors.append(f"{where}: unknown value '{value}' for chain key '{key}' (allowed: {allowed})")
        elif key in chain:
            errors.append(f"{where}: duplicate chain key '{key}'")
        else:
            chain[key] = value
    return chain


def _environment_entry(match: Any, read: Optional[str], write: Optional[str]) -> Dict[str, Any]:
    return {
        "name": match.group("name"),
        "kind": match.group("kind"),
        "read": read,
        "write": write,
        "quote": match.group("quote")[1:-1],
        "date": match.group("date"),
    }


def _parse_spec_environment(body: str, where: str, errors: List[str]) -> Optional[Dict[str, Any]]:
    match = SPEC_ENV_RE.match(body)
    if not match:
        errors.append(
            f"{where}: Environment line does not match "
            "'`name` (test|prod) — read=run|task|deny, write=run|task|deny — \"question — answer\" (YYYY-MM-DD)'"
        )
        return None
    read, write = _parse_rights(match.group("rights"), where, match.group("name"), errors)
    entry = _environment_entry(match, read, write)
    errors.extend(_environment_errors(entry, where))
    return entry


def parse_metadata(text: str) -> Dict[str, Any]:
    """Parse the spec's '> Chain:', '> Environment:' and '> Backlog:' lines above '# Goal'."""
    result: Dict[str, Any] = {"chain": None, "environments": [], "backlog": None, "errors": [], "warnings": []}
    errors = result["errors"]
    for number, line in _unfenced_lines(text):
        if line == "# Goal":
            break
        match = METADATA_RE.match(line)
        if not match:
            if MALFORMED_METADATA_RE.match(line) and not TIER_RE.match(line):
                errors.append(f"line {number}: malformed-metadata: {line}")
            continue
        key, body, where = match.group("key"), match.group("body"), f"line {number}"
        if key == "Chain":
            if result["chain"] is not None:
                errors.append(f"{where}: duplicate Chain line")
            else:
                result["chain"] = _parse_chain(body, where, errors)
        elif key == "Backlog":
            if not body:
                errors.append(f"{where}: empty Backlog line (expected '> Backlog: <section name>')")
            elif result["backlog"] is not None:
                errors.append(f"{where}: duplicate Backlog line")
            else:
                result["backlog"] = body
        elif key == "Environment":
            entry = _parse_spec_environment(body, where, errors)
            if entry is None:
                continue
            if any(known["name"] == entry["name"] for known in result["environments"]):
                errors.append(f"{where}: duplicate Environment `{entry['name']}`")
            else:
                result["environments"].append(entry)
    return result


def _parse_rights(text: Optional[str], where: str, name: str, errors: List[str]) -> Tuple[Optional[str], Optional[str]]:
    """Parse 'read=X, write=Y' (',' or ';' separated). Both keys are required."""
    rights: Dict[str, str] = {}
    named = set()
    for item in (part.strip() for part in re.split(r"[,;]", text or "")):
        if not item:
            continue
        key, _, value = (piece.strip() for piece in item.partition("="))
        named.add(key)
        if key in ("read", "write") and value in RIGHT_VALUES:
            rights[key] = value
        else:
            allowed = ", ".join(RIGHT_VALUES)
            errors.append(f"{where}: environment `{name}`: bad right '{item}' (expected read= or write= with {allowed})")
    missing = [key + "=" for key in ("read", "write") if key not in named]
    if missing:
        errors.append(f"{where}: environment `{name}` misses {' and '.join(missing)} (values: {', '.join(RIGHT_VALUES)})")
    return rights.get("read"), rights.get("write")


def _environment_errors(entry: Dict[str, Any], where: str) -> List[str]:
    """Rules shared by the spec line and the plan header: no prod write=run, no UI markers."""
    issues: List[str] = []
    if entry["kind"] == "prod" and entry["write"] == "run":
        issues.append(f"{where}: environment `{entry['name']}` is prod: write=run is not allowed (prod changes are task or deny only)")
    marker = UI_MARKER_RE.search(entry["quote"])
    if marker:
        issues.append(
            f"{where}: environment `{entry['name']}`: quote contains the interface marker '{marker.group(0)}' "
            "(record the question and the user's answer only)"
        )
    return issues


def _link_target(value: str) -> str:
    """'[x](./x.md)' → './x.md'; '`x.md`' → 'x.md'; a bare path is returned as is."""
    match = LINK_TARGET_RE.search(value)
    return (match.group("target") if match else value).strip().strip("`").strip()


def _plan_environment(line: str, where: str, result: Dict[str, Any]) -> None:
    match = PLAN_ENV_RE.match(line)
    if not match:
        # An entry with rights is new syntax: an error. An old entry in another shape only warns.
        target = result["errors"] if ("read=" in line or "write=" in line) else result["warnings"]
        target.append(f"{where}: Environments entry does not match '- `name` (test|prod; read=…, write=…) — \"quote\" (date)'")
        return
    name = match.group("name")
    if match.group("rights") is None:
        entry = _environment_entry(match, None, None)
        result["warnings"].append(f"environment `{name}` has no read/write rights")
        result["warnings"].extend(_environment_errors(entry, where))
    else:
        read, write = _parse_rights(match.group("rights"), where, name, result["errors"])
        entry = _environment_entry(match, read, write)
        result["errors"].extend(_environment_errors(entry, where))
    if entry["date"] is not None and not DATE_RE.match(entry["date"].strip()):
        entry["date"] = None  # a free tail such as "(user, 2026-09-30)" is not a date
    if any(known["name"] == name for known in result["environments"]):
        result["errors"].append(f"{where}: duplicate environment `{name}`")
    else:
        result["environments"].append(entry)


def _plan_task_files(lines: List[str]) -> List[Dict[str, Any]]:
    """{path, action, lines} of the **Files:** block of a task, by the rules of executor_tool.extract_files. On an
    action line (Create, Modify, Test, Delete, Move and the Russian ones) the path is the first backticked name or
    markdown link, the first two for Move:, and the rest of the line explains it; a name with < or > is a
    placeholder, not a path. A line without an action gives every name (spec 1 of plan-refactoring-04)."""
    files: List[Dict[str, Any]] = []
    seen = set()
    in_scope = False
    for line in lines:
        stripped = line.strip()
        if PLAN_FILES_BLOCK_RE.match(stripped):
            in_scope = True
            continue
        if in_scope and (PLAN_HEADING_RE.match(stripped)
                         or (stripped.startswith("**") and not PLAN_FILE_ACTION_RE.match(line))):
            in_scope = False
        if not in_scope:
            continue
        action = PLAN_FILE_ACTION_RE.match(line)
        candidates = [(m.start(), m.group(1), None) for m in PLAN_MD_LINK_RE.finditer(line)]
        candidates.extend((m.start(), m.group(1), m.group(2)) for m in PLAN_CODE_PATH_RE.finditer(line))
        candidates.sort(key=lambda item: item[0])
        if action:
            first = candidates[:2 if action.group(1).lower() == "move" else 1]
            candidates = [item for item in first if not PLAN_PLACEHOLDER_RE.search(item[1])]
        for _, candidate, span in candidates:
            path = candidate.strip().strip(".,;:")
            path = (path[2:] if path.startswith("./") else path).replace("\\", "/")
            if path and path not in seen:
                seen.add(path)
                files.append({"path": path, "action": action.group(1).lower() if action else None, "lines": span})
    return files


def normalize_task_id(task_id: str) -> str:
    """A task id for comparison (F7 of plan-refactoring-02): every number of a dotted numeric id without leading
    zeros (`01.02` → `1.2`, `007` → `7`); any other id as written, without surrounding spaces. Copies of this rule:
    next_review_index.normalize_task_id, resolver_tool.normalize_plan_task_id (plan-writing/tests holds them equal)."""
    text = str(task_id).strip()
    if PLAN_NUMERIC_ID_RE.match(text):
        return ".".join(str(int(part)) for part in text.split("."))
    return text


# The writing marker of plan-writing (spec 3 of plan-refactoring-02): the last line of a plan that is still being
# written, `> Writing: in progress (spec sha256 <first 12 hex of the spec's SHA-256>)`. Outside code fences anywhere
# it makes the plan incomplete; a missing or broken fingerprint reads as None, which matches no spec.
# plan_tool.WRITING_MARKER_RE and WRITING_MARKER_SHA_RE copy these two (plan-writing/tests holds them equal).
WRITING_MARKER_RE = re.compile(r"^> Writing: in progress\b(?P<rest>.*)$")
WRITING_MARKER_SHA_RE = re.compile(r"^\s*\(spec sha256 (?P<sha>[0-9a-f]{12})\)\s*$")


def _writing_marker_in(unfenced: List[Tuple[int, str]]) -> Optional[Dict[str, Any]]:
    """The first writing marker among (line number, line) pairs outside code fences."""
    for number, line in unfenced:
        match = WRITING_MARKER_RE.match(line)
        if match:
            sha = WRITING_MARKER_SHA_RE.match(match.group("rest"))
            return {"line": number, "spec_sha": sha.group("sha") if sha else None}
    return None


def writing_marker(text: str) -> Optional[Dict[str, Any]]:
    """{"line", "spec_sha"} of the plan's first writing marker outside code fences, None when it has none."""
    return _writing_marker_in(_unfenced_lines(text))


def _plan_task_refs(lines: List[str]) -> List[str]:
    """Task ids named in the **Preconditions:** block (Task N, Task N.M, Задача N), in order, once each."""
    refs: List[str] = []
    in_block = False
    for line in lines:
        stripped = line.strip()
        if PLAN_PRECONDITIONS_RE.match(stripped):
            in_block = True
        elif in_block and (stripped.startswith("**") or stripped.startswith("- [ ]") or PLAN_HEADING_RE.match(stripped)):
            in_block = False
        if in_block:
            for ref in PLAN_TASK_REF_RE.findall(stripped):
                ref = normalize_task_id(ref)
                if ref not in refs:
                    refs.append(ref)
    return refs


def parse_plan_tasks(text: str) -> Dict[str, Any]:
    """Tasks of a plan by the plan format contract: `### Task N: <title>` headings outside code fences.

    A task ends before the next task heading or the next heading of its level or higher. Lines are
    1-based and inclusive (`lines[line_start-1:line_end]`). `sha1` (8 hex) and `size_bytes` cover the task's
    text joined with newlines, without trailing blank lines. Task-like headings without `<id>:` go to
    `malformed`, repeated ids to `duplicates`; ids and refs are normalised (normalize_task_id), so `Task 1` and
    `Task 01` repeat one id.
    `incomplete` is True when plan-writing's writing marker stands outside code fences (writing_marker): the tasks
    before it are returned as usual, the last one ending on the line before the marker, and `marker_spec_sha` is the
    marker's spec fingerprint (None without a valid one)."""
    lines = text.splitlines()
    scanned = _fence_scan(text)
    unfenced = [(number, raw.rstrip()) for number, raw, kind in scanned if kind == "text"]
    visible = {number for number, _ in unfenced}
    marker = _writing_marker_in(unfenced)
    limit = marker["line"] if marker else len(lines) + 1
    code = {number for number, _, kind in scanned if kind == "code"}
    headings: List[Tuple[int, int, str]] = []
    for number, line in unfenced:
        heading = PLAN_HEADING_RE.match(line)
        if heading:
            headings.append((number, len(heading.group("hashes")), line))
    tasks: List[Dict[str, Any]] = []
    malformed: List[Dict[str, Any]] = []
    for position, (number, level, line) in enumerate(headings):
        if number > limit:
            break  # tasks after the writing marker are not the plan's yet
        match = PLAN_TASK_HEADING_RE.match(line)
        if not match:
            if PLAN_TASKISH_RE.match(line):
                malformed.append({"line": number, "text": line})
            continue
        end = min(next((later - 1 for later, later_level, later_line in headings[position + 1:]
                        if later_level <= level or PLAN_TASK_HEADING_RE.match(later_line)), len(lines)), limit - 1)
        block = lines[number - 1:end]
        while block and not block[-1].strip():
            block.pop()
        body = "\n".join(block) + "\n"
        inner = range(number + 1, end + 1)
        plain = [lines[n - 1] for n in inner if n in visible]
        tasks.append({
            "id": normalize_task_id(match.group("id")),
            "title": match.group("title"),
            "level": level,
            "line_start": number,
            "line_end": end,
            "checkpoint": bool(PLAN_CHECKPOINT_RE.match(match.group("title"))),
            "section": next((h_line for _, h_level, h_line in reversed(headings[:position]) if h_level < level), None),
            "files": _plan_task_files(plain),
            "refs": _plan_task_refs(plain),
            "size_bytes": len(body.encode("utf-8")),
            "code_lines": sum(1 for n in inner if n in code),
            "sha1": hashlib.sha1(body.encode("utf-8")).hexdigest()[:8],
        })
    positions: Dict[str, List[int]] = {}
    for task in tasks:
        positions.setdefault(task["id"], []).append(task["line_start"])
    duplicates = [{"id": task_id, "lines": found} for task_id, found in positions.items() if len(found) > 1]
    return {"tasks": tasks, "malformed": malformed, "duplicates": duplicates,
            "incomplete": marker is not None, "marker_spec_sha": marker["spec_sha"] if marker else None}


def parse_plan_header(text: str) -> Dict[str, Any]:
    """Settings in a plan header (lines before the first task heading): written only for old specs."""
    result: Dict[str, Any] = {"spec": None, "tier": None, "chain": None, "environments": [],
                              "backlog": None, "errors": [], "warnings": []}
    parsed = parse_plan_tasks(text)
    starts = [task["line_start"] for task in parsed["tasks"]] + [item["line"] for item in parsed["malformed"]]
    first_task = min(starts) if starts else None
    in_env_block = False
    for number, line in _unfenced_lines(text):
        if first_task is not None and number >= first_task:
            break
        where = f"line {number}"
        if PLAN_ENVIRONMENTS_RE.match(line):
            in_env_block = True
            continue
        if in_env_block and PLAN_ENV_ITEM_RE.match(line):
            _plan_environment(line, where, result)
            continue
        if line.strip() and not line.startswith(" "):
            in_env_block = False
        field = PLAN_FIELD_RE.match(line)
        if not field:
            continue
        name, value = field.group("name"), field.group("value")
        if name in ("Spec", "Tier"):
            key = name.lower()
            result[key] = result[key] or ((_link_target(value) if name == "Spec" else value) or None)
        elif result[name.lower()] is not None:
            result["errors"].append(f"{where}: duplicate {name} line")
        elif name == "Chain":
            result["chain"] = _parse_chain(value, where, result["errors"])
        else:
            result["backlog"] = value or None
    return result


def _complete_chain(chain: Optional[Dict[str, str]], tier: Optional[str]) -> Dict[str, str]:
    """All four chain keys: explicit values, else CHAIN_DEFAULTS; revision defaults to the tier."""
    full = dict(CHAIN_DEFAULTS, revision=tier.lower() if tier in TIERS else "standard")
    full.update(chain or {})
    return {key: full[key] for key in CHAIN_VALUES}


def _sha256(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _settings_missing(result: Dict[str, Any], missing: str) -> Dict[str, Any]:
    result["ok"] = False
    result["errors"].append(f"settings-source-missing: {missing}")
    result["chain"] = _complete_chain(None, result["tier"])
    return result


def resolve_settings(path: str) -> Dict[str, Any]:
    """The single reading rule: roadmap/part → master plan (Source link); plan → its header
    settings when present, else the spec at **Spec:**; spec → its metadata lines."""
    current = os.path.abspath(path)
    text = _read_source(current)
    result: Dict[str, Any] = {"ok": True, "from": "none", "source": None, "source_sha256": None,
                              "tier": None, "chain": None, "chain_explicit": False,
                              "environments": [], "backlog": None, "errors": [], "warnings": []}
    source = next((m.group("target") for m in map(SOURCE_RE.match, text.splitlines()[:10]) if m), None)
    if source is not None:
        current = os.path.normpath(os.path.join(os.path.dirname(current), source))
        if not os.path.isfile(current):
            return _settings_missing(result, current)
        text = _read_source(current)
    header = parse_plan_header(text)
    settings: Optional[Dict[str, Any]] = None
    if header["spec"] is not None:
        result["tier"] = header["tier"]
        if header["chain"] is not None or header["environments"] or header["backlog"] is not None:
            result["from"], settings = "plan-header", header
        else:
            current = os.path.normpath(os.path.join(os.path.dirname(current), header["spec"]))
            if not os.path.isfile(current):
                return _settings_missing(result, current)
            text = _read_source(current)
    elif not any(line == "# Goal" for _, line in _unfenced_lines(text)):
        # Not a spec, a plan or a roadmap/part (e.g. a plan without **Spec:**): defaults, no error.
        result["chain"] = _complete_chain(None, None)
        return result
    if settings is None:
        result["from"], settings = "spec", parse_metadata(text)
        result["tier"] = check_spec(text)["tier"] or result["tier"]
    result["source"], result["source_sha256"] = current, _sha256(current)
    result["chain_explicit"] = settings["chain"] is not None
    result["chain"] = _complete_chain(settings["chain"], result["tier"])
    result["environments"], result["backlog"] = settings["environments"], settings["backlog"]
    # A malformed metadata line fails spec-check but keeps the settings readable: a warning here.
    for error in settings["errors"]:
        _, malformed, line = error.partition(": malformed-metadata: ")
        if malformed:
            result["warnings"].append(f"malformed-metadata: {line}")
        else:
            result["errors"].append(error)
    result["warnings"].extend(settings["warnings"])
    result["ok"] = not result["errors"]
    return result


def _spec_volume(text: str, bodies: Dict[str, str], tier: Optional[str]) -> Dict[str, Any]:
    """Volume estimate of a spec: the items of Components, Testing Strategy and Out of Scope
    (_spec_item_heads), the size in bytes and estimate_tasks = components × TIER_TASK_FACTOR[tier]
    + testing_items; a missing or unknown tier counts as Standard. An estimate, not a measurement:
    nothing is written into the spec."""
    def count(heading: str) -> int:
        return len(_spec_item_heads(bodies.get(heading, "").splitlines()))

    components = count("## Components")
    testing_items = count("## Testing Strategy")
    estimate = components * TIER_TASK_FACTOR.get(tier or "", TIER_TASK_FACTOR["Standard"]) + testing_items
    return {
        "components": components,
        "testing_items": testing_items,
        "out_of_scope_items": count("## Out of Scope"),
        "spec_bytes": len(text.encode("utf-8")),
        "estimate_tasks": estimate,
        "budget_tasks": SIZE_BUDGET["tasks"],
        "over_budget": estimate > SIZE_BUDGET["tasks"],
    }


# CLAUDE.md changes only on a structural event (its "Stability of this file" rule): a spec that names it in Components
# gets a warning, never an error (spec 1 of plan-refactoring-02).
CLAUDE_MD_RE = re.compile(r"(?<![\w.-])CLAUDE\.md\b")
CLAUDE_MD_IN_COMPONENTS = ("claude-md-in-components: Components names CLAUDE.md; it changes only on a structural event "
                           "(skill, script, contract, convention, artifact): name the event, and put commands, flags "
                           "and fields into the skill's USAGE.md and docs/HELPER-CLIS.md")


def check_spec(text: str) -> Dict[str, Any]:
    """Check spec text against the spec contract. Code fences are ignored."""
    errors: List[str] = []
    warnings: List[str] = []
    tier: Optional[str] = None
    positions: Dict[str, List[int]] = {}
    lines: List[Tuple[int, str]] = []

    for number, raw, kind in _fence_scan(text):
        if kind != "text":
            continue
        line = raw.rstrip()
        lines.append((number, line))
        if line in SPEC_HEADINGS:
            positions.setdefault(line, []).append(number)
        elif re.match(r"^#{1,2}\s", line):
            warnings.append(f"line {number}: extra top-level heading '{line}' (not part of the contract; '# Goal' is the only H1)")
        if PLACEHOLDER_RE.search(line):
            warnings.append(f"line {number}: placeholder marker: {line.strip()}")

    goal_line = positions.get("# Goal", [None])[0]
    for number, line in lines:
        if goal_line is not None and number >= goal_line:
            break
        match = TIER_RE.match(line)
        if match:
            tier = match.group("tier")
            break
    if tier is None:
        warnings.append("missing '> Tier: <Quick|Standard|Deep>' line above '# Goal'")
    elif tier not in TIERS:
        warnings.append(f"unknown tier '{tier}' (allowed: {', '.join(TIERS)})")

    for heading in SPEC_HEADINGS:
        found = positions.get(heading, [])
        if not found:
            errors.append(f"missing heading: {heading}")
        elif len(found) > 1:
            errors.append(f"duplicate heading: {heading} (lines {', '.join(map(str, found))})")
    present = sorted((found[0], heading) for heading, found in positions.items())
    order = [heading for _, heading in present]
    if order != [heading for heading in SPEC_HEADINGS if heading in positions]:
        errors.append("headings out of order: " + " > ".join(order))

    bodies: Dict[str, str] = {}
    for index, (start, heading) in enumerate(present):
        end = present[index + 1][0] if index + 1 < len(present) else None
        body = [line for number, line in lines if number > start and (end is None or number < end)]
        bodies[heading] = "\n".join(body).strip()

    for heading, body in bodies.items():
        if heading == "## Open Questions":
            # Empty, "(none)", or "(none)" plus a one-line rationale.
            if body and not (body.startswith(NONE_TEXT) and len(body.splitlines()) == 1):
                errors.append("## Open Questions must be empty or '(none)' before handoff")
        elif not body:
            errors.append(f"empty section: {heading} (use '(none)' with a one-line rationale)")
        elif body == NONE_TEXT:
            if heading == "## Out of Scope":
                errors.append("## Out of Scope must list excluded work explicitly")
            else:
                warnings.append(f"{heading}: '(none)' without a one-line rationale")

    # Dialogue and plan language: the spec text outside code fences.
    lang = detect_lang_text("\n".join(line for _, line in lines))
    metadata = parse_metadata(text)
    errors.extend(metadata["errors"])
    if metadata["backlog"] is not None:
        try:
            _check_goal(metadata["backlog"])  # the goal names the chain journal <goal>-chain.json
        except InputError:
            number = next(n for n, line in lines if re.match(r"^>\s*(?:\*\*)?Backlog\b", line))
            errors.append(f"line {number}: backlog-not-a-file-name: {metadata['backlog']}")
    warnings.extend(metadata["warnings"])
    volume = _spec_volume(text, bodies, tier)
    components_body = bodies.get("## Components", "")
    if components_body and not components_body.startswith(NONE_TEXT) and volume["components"] == 0:
        warnings.append(VOLUME_UNKNOWN)
    if CLAUDE_MD_RE.search(components_body):
        warnings.append(CLAUDE_MD_IN_COMPONENTS)
    return {
        "ok": not errors,
        "tier": tier,
        "lang": lang,
        "chain": metadata["chain"],
        "environments": metadata["environments"],
        "backlog": metadata["backlog"],
        "volume": volume,
        "errors": errors,
        "warnings": warnings,
    }


def cmd_spec_check(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    result = check_spec(_read_source(args.spec))
    return (0 if result["ok"] else 1), result


def cmd_detect_lang(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    text = _text_for_lang(_read_source(args.path))
    return 0, {"ok": True, "lang": detect_lang_text(text), "cyrillic_ratio": round(cyrillic_ratio(text), 4)}


def _group_by_file(findings: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    groups: Dict[str, List[str]] = {}
    for entry in findings:
        if entry.get("file"):
            groups.setdefault(entry["file"], []).append(entry["id"])
    return groups


def cmd_parse(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    findings, errors, warnings = load_findings(_read_source(args.findings))
    if args.root is not None:
        if not os.path.isdir(args.root):
            raise InputError(f"root is not a directory: {args.root}")
        warnings.extend(check_locations(findings, args.root))
    result = {
        "ok": not errors,
        "count": len(findings),
        "findings": findings,
        "by_file": _group_by_file(findings),
        "errors": errors,
        "warnings": warnings,
    }
    return (0 if not errors else 1), result


def cmd_coverage(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    findings, errors, _ = load_findings(_read_source(args.findings))
    if errors:
        return 1, {"ok": False, "errors": errors}
    try:
        with open(args.spec, "r", encoding="utf-8-sig") as fh:
            spec_text = fh.read()
    except (OSError, UnicodeDecodeError) as exc:  # same rule as _read_source
        raise InputError(f"cannot read {args.spec}: {exc}") from exc

    expected = [entry["id"] for entry in findings]
    mentioned = {f"F{m.group(1)}" for m in ID_RE.finditer(spec_text)}
    missing = [fid for fid in expected if fid not in mentioned]
    unknown = sorted(mentioned - set(expected), key=lambda fid: int(fid[1:]))
    # Unknown F-ids are a warning: "F401" in a spec may be a lint code, not a finding.
    ok = not missing
    return (0 if ok else 1), {
        "ok": ok,
        "expected": len(expected),
        "covered": [fid for fid in expected if fid in mentioned],
        "missing": missing,
        "unknown": unknown,
        "warnings": [f"unknown finding ids mentioned: {', '.join(unknown)}"] if unknown else [],
    }


def cmd_plan_tasks(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    try:
        text = _read_source(args.plan)
    except InputError:
        raise InputError(f"plan-unreadable: {args.plan}") from None
    return 0, dict(ok=True, **parse_plan_tasks(text))


def cmd_settings(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    result = resolve_settings(args.file)
    if any(error.startswith("settings-source-missing: ") for error in result["errors"]):
        return 2, result
    return (0 if result["ok"] else 1), result


BACKLOG_FILE = "BACKLOG.md"
BACKLOG_USER_SECTION = {"en": "My notes", "ru": "Свои заметки"}
BACKLOG_HEADING_RE = re.compile(r"^#{1,2} ")
BACKLOG_ITEM_RE = re.compile(r"^- \[(?P<mark>[ xX-])\] (?P<body>.+?)\s*$")
# `[ ]` open, `[x]` taken into an approved spec (not "done"), `[-]` cancelled by the user.
BACKLOG_STATES = {" ": "open", "x": "done", "X": "done", "-": "cancelled"}
BACKLOG_STATE_FILTERS = ("open", "done", "cancelled", "all")
BACKLOG_TAIL_RE = re.compile(r"^(?P<source>.+), (?P<date>\d{4}-\d{2}-\d{2})$")
BACKLOG_DATE_SUFFIX_RE = re.compile(r", \d{4}-\d{2}-\d{2}$")


def _is_user_section(name: str) -> bool:
    """`My notes` / `Свои заметки` in any letter case: the user's section, never written by skills."""
    return name.strip().casefold() in {value.casefold() for value in BACKLOG_USER_SECTION.values()}


def _backlog_lines(text: str) -> List[str]:
    """Split on "\\n" only, keeping the endings: offsets stay exact for any content."""
    return re.findall(r"[^\n]*\n|[^\n]+$", text)


BACKLOG_CANCELLED_PREFIXES = ("Отменено. ", "Cancelled. ")


def _backlog_uncancelled(text: str) -> str:
    """Item text without the `Отменено. ` / `Cancelled. ` prefix the user writes on a cancelled item."""
    for prefix in BACKLOG_CANCELLED_PREFIXES:
        if text.startswith(prefix):
            return text[len(prefix):]
    return text


def _backlog_key(line: str) -> Optional[str]:
    """Identity of a backlog line: checkbox, date and the cancelled prefix are ignored, item and source count."""
    line = line.rstrip()
    match = BACKLOG_ITEM_RE.match(line)
    if match:
        return "[] " + BACKLOG_DATE_SUFFIX_RE.sub("", _backlog_uncancelled(match.group("body")))
    if line.startswith("- "):
        return "- " + line[2:]
    return None


def _backlog_scan(lines: List[str]) -> Tuple[List[Optional[str]], List[bool]]:
    """Per line: (heading text without the BOM when it is a `#`/`##` heading outside a code
    fence, else None) and (True when the line is a fence marker or inside a fence).
    Headings inside fences (pasted examples) never start or end a section."""
    marks: List[Optional[str]] = []
    fenced: List[bool] = []
    fence: Optional[str] = None
    for line in lines:
        bare = line.lstrip("﻿").rstrip()
        match = re.match(r"^ {0,3}(`{3,}|~{3,})", bare)
        if match:
            mark = match.group(1)
            if fence is None:
                fence = mark
            elif mark[0] == fence[0] and len(mark) >= len(fence) and bare.strip() == mark:
                fence = None
            marks.append(None)
            fenced.append(True)
            continue
        marks.append(bare if fence is None and BACKLOG_HEADING_RE.match(bare) else None)
        fenced.append(fence is not None)
    return marks, fenced


def _backlog_insertion(text: str, section: str, entry: str) -> Optional[Tuple[int, str]]:
    """Offset and text that append `entry` at the end of `## <section>`.

    None means the section already holds the same entry (same item and source).
    A missing section is created at the end of the file. Nothing outside the
    returned text changes.
    """
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = _backlog_lines(text)
    headings, _ = _backlog_scan(lines)
    heading = f"## {section}"
    start = next((i for i, mark in enumerate(headings) if mark == heading), None)
    if start is None:
        prefix = "" if not text or text.endswith("\n") else nl
        if lines and lines[-1].strip():
            prefix += nl
        return len(text), f"{prefix}{heading}{nl}{nl}{entry}{nl}"
    end = next((i for i in range(start + 1, len(lines)) if headings[i] is not None), len(lines))
    key = _backlog_key(entry)
    if any(_backlog_key(line) == key for line in lines[start + 1:end]):
        return None
    last = end
    while last > start + 1 and not lines[last - 1].strip():
        last -= 1
    prefix = "" if lines[last - 1].endswith("\n") else nl
    if last == start + 1:
        prefix += nl  # empty section: keep one blank line after the heading
    return sum(len(line) for line in lines[:last]), f"{prefix}{entry}{nl}"


class BacklogError(Exception):
    """BACKLOG.md cannot be appended to without changing other bytes (exit 1)."""


def _backlog_field(name: str, value: Optional[str]) -> str:
    value = (value or "").strip()
    if not value or "\n" in value or "\r" in value:
        raise InputError(f"{name} must be a non-empty single line")
    return value


def _replace_retrying(source: str, target: str, retry_seconds: float = 1.0) -> None:
    """os.replace; on Windows a reader holding `target` open fails it with PermissionError for a
    moment, so there that error is retried for `retry_seconds`."""
    deadline = time.monotonic() + retry_seconds
    while True:
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if os.name != "nt" or time.monotonic() >= deadline:
                raise
            time.sleep(0.05)


def _atomic_write_text(path: str, text: str) -> None:
    """Write `text` as UTF-8 bytes through a sibling temp file and os.replace.

    A crash never leaves a half-written file. A symlink stays a symlink: the write goes to
    its target. An existing file keeps its permission bits, a new file gets 0o666 & ~umask
    (mkstemp alone would give 0600). On any error the temp file is removed and re-raised.
    """
    target = os.path.realpath(path) if os.path.islink(path) else os.path.abspath(path)
    fd, temp = tempfile.mkstemp(prefix="." + os.path.basename(target) + ".", suffix=".tmp",
                                dir=os.path.dirname(target))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(text.encode("utf-8"))
            fh.flush()
            os.fsync(fh.fileno())
        if os.path.exists(target):
            mode = stat.S_IMODE(os.stat(target).st_mode)
        else:
            mask = os.umask(0)
            os.umask(mask)
            mode = 0o666 & ~mask
        os.chmod(temp, mode)
        _replace_retrying(temp, target)
    except BaseException:
        try:
            if os.path.exists(temp):
                os.chmod(temp, stat.S_IREAD | stat.S_IWRITE)  # Windows: a read-only file cannot be removed
                os.remove(temp)
        except OSError:
            pass  # the original error is the one to report
        raise


def backlog_append(root: str, section: str, source: str, item: str, lang: str = "en",
                   plain: bool = False, date: Optional[str] = None) -> Dict[str, Any]:
    """Append one line at the end of `## <section>` in `<root>/BACKLOG.md`."""
    if not os.path.isdir(root):
        raise InputError(f"root is not a directory: {root}")
    section = _backlog_field("section", section)
    source = _backlog_field("source", source)
    item = _backlog_field("item", item)
    if _is_user_section(section):
        raise BacklogError(f"user-section: section '{section}' belongs to the user; skills never write there")
    if lang not in BACKLOG_USER_SECTION:
        raise InputError(f"lang must be one of: {', '.join(sorted(BACKLOG_USER_SECTION))}")
    day = date or datetime.date.today().isoformat()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", day):
        raise InputError(f"date must be YYYY-MM-DD: {day}")
    entry = f"- {item}" if plain else f"- [ ] {item} — {source}, {day}"

    path = os.path.abspath(os.path.join(root, BACKLOG_FILE))
    created = not os.path.exists(path)
    if created:
        old = f"# Backlog\n\n## {BACKLOG_USER_SECTION[lang]}\n\n".encode("utf-8")
    else:
        try:
            with open(path, "rb") as fh:
                old = fh.read()
        except OSError as exc:
            raise InputError(f"cannot read {path}: {exc}") from exc
    try:
        text = old.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BacklogError(f"{path} is not UTF-8, file not written: {exc}") from exc

    result: Dict[str, Any] = {"ok": True, "path": path, "section": section}
    insertion = _backlog_insertion(text, section, entry)
    if insertion is None:
        return {**result, "action": "exists"}
    offset, inserted = insertion
    head, tail = text[:offset].encode("utf-8"), text[offset:].encode("utf-8")
    if not created and head + tail != old:
        raise BacklogError(f"{path}: bytes outside the insertion would change, file not written")
    new = head + inserted.encode("utf-8") + tail
    # A sibling temp file swapped in: a crash never leaves a half-written BACKLOG.md, the file
    # keeps its mode and a symlinked BACKLOG.md stays a symlink (_atomic_write_text).
    try:
        _atomic_write_text(path, new.decode("utf-8"))
    except OSError as exc:
        raise BacklogError(f"{path}: write failed, file left unchanged: {exc}") from exc
    with open(path, "rb") as fh:
        if fh.read() != new:
            raise BacklogError(f"{path}: content after write differs from the expected bytes")
    return {**result, "action": "created" if created else "appended"}


def _backlog_target(root: str, section: str, item: str) -> Tuple[str, str, str, Optional[bytes], Optional[str]]:
    """Checked arguments of backlog-mark / backlog-unmark: (section, item, BACKLOG.md path, bytes, text);
    bytes and text are None when the file is missing. User section or a file not in UTF-8: BacklogError."""
    if not os.path.isdir(root):
        raise InputError(f"root is not a directory: {root}")
    section = _backlog_field("section", section)
    item = _backlog_field("item", item)
    if _is_user_section(section):
        raise BacklogError(f"user-section: section '{section}' belongs to the user; skills never write there")
    path = os.path.abspath(os.path.join(root, BACKLOG_FILE))
    try:
        with open(path, "rb") as fh:
            old = fh.read()
    except FileNotFoundError:
        return section, item, path, None, None
    except OSError as exc:
        raise InputError(f"cannot read {path}: {exc}") from exc
    try:
        return section, item, path, old, old.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BacklogError(f"{path} is not UTF-8, file not written: {exc}") from exc


def _backlog_flip(path: str, text: str, old: bytes, lines: List[str], index: int, before: str, after: str) -> None:
    """Set the checkbox of line `index` (now one of `before`) to `after`: exactly one byte changes, checked
    before and after the atomic write; otherwise BacklogError and the file is left as it was."""
    offset = sum(len(line) for line in lines[:index]) + len(lines[index]) - len(lines[index].lstrip("﻿")) + 3
    new_text = text[:offset] + after + text[offset + 1:]
    new = new_text.encode("utf-8")
    if text[offset] not in before or len(new) != len(old) or sum(a != b for a, b in zip(old, new)) != 1:
        raise BacklogError(f"{path}: more than the checkbox would change, file not written")
    try:
        _atomic_write_text(path, new_text)
    except OSError as exc:
        raise BacklogError(f"{path}: write failed, file left unchanged: {exc}") from exc
    with open(path, "rb") as fh:
        if fh.read() != new:
            raise BacklogError(f"{path}: content after write differs from the expected bytes")


def backlog_mark(root: str, section: str, item: str) -> Dict[str, Any]:
    """Check off `- [ ] <item>` of `## <section>` in `<root>/BACKLOG.md`: the item entered an approved
    spec. Only the checkbox byte changes. marked / already; cancelled, not-found and ambiguous write nothing."""
    section, item, path, old, text = _backlog_target(root, section, item)
    result: Dict[str, Any] = {"ok": True, "path": path, "section": section, "item": item}
    missing = dict(result, ok=False, action="not-found", errors=[f"not-found: '{item}' in '## {section}'"])
    if old is None or text is None:
        return missing
    lines = _backlog_lines(text)
    found = _backlog_item_lines(lines, section, item)
    unchecked, checked, cancelled = found["open"], found["done"], found["cancelled"]
    if len(unchecked) > 1:
        return dict(result, ok=False, action="ambiguous", lines=[index + 1 for index in unchecked],
                    errors=[f"ambiguous: {len(unchecked)} unchecked lines of '## {section}' read '{item}'"])
    if not unchecked:
        if checked:
            return dict(result, action="already", line=checked[0] + 1)
        if cancelled:
            return dict(result, ok=False, action="cancelled", line=cancelled[0] + 1,
                        errors=[f"cancelled: '{item}' in '## {section}' is cancelled [-] by the user"])
        return missing
    _backlog_flip(path, text, old, lines, unchecked[0], " ", "x")
    return dict(result, action="marked", line=unchecked[0] + 1)


def backlog_unmark(root: str, section: str, item: str) -> Dict[str, Any]:
    """Uncheck `- [x] <item>` of `## <section>` in `<root>/BACKLOG.md`: an amended or withdrawn spec no
    longer covers it. Only the checkbox byte changes. unmarked / already; cancelled, not-found and
    ambiguous write nothing."""
    section, item, path, old, text = _backlog_target(root, section, item)
    result: Dict[str, Any] = {"ok": True, "path": path, "section": section, "item": item}
    missing = dict(result, ok=False, action="not-found", errors=[f"not-found: '{item}' in '## {section}'"])
    if old is None or text is None:
        return missing
    lines = _backlog_lines(text)
    found = _backlog_item_lines(lines, section, item)
    checked = found["done"]
    if len(checked) > 1:
        return dict(result, ok=False, action="ambiguous", lines=[index + 1 for index in checked],
                    errors=[f"ambiguous: {len(checked)} checked lines of '## {section}' read '{item}'"])
    if not checked:
        if found["open"]:
            return dict(result, action="already", line=found["open"][0] + 1)
        if found["cancelled"]:
            return dict(result, ok=False, action="cancelled", line=found["cancelled"][0] + 1,
                        errors=[f"cancelled: '{item}' in '## {section}' is cancelled [-] by the user"])
        return missing
    _backlog_flip(path, text, old, lines, checked[0], "xX", " ")
    return dict(result, action="unmarked", line=checked[0] + 1)


def _backlog_item_text(body: str) -> Tuple[str, Optional[str], Optional[str]]:
    """(text, source, date) of an item body: " — <source>, <YYYY-MM-DD>" at the end is split off."""
    if " — " in body:
        head, tail = body.rsplit(" — ", 1)
        found = BACKLOG_TAIL_RE.match(tail)
        if found:
            return head, found.group("source"), found.group("date")
    return body, None, None


def _backlog_item_lines(lines: List[str], section: str, item: str) -> Dict[str, List[int]]:
    """Indexes of the item lines of `## <section>`, outside code fences, whose text (as backlog-parse gives
    it) is `item`, by state: open, done, cancelled. A cancelled line also matches without its prefix."""
    headings, fenced = _backlog_scan(lines)
    found: Dict[str, List[int]] = {"open": [], "done": [], "cancelled": []}
    current: Optional[str] = None
    for index, (line, heading, in_fence) in enumerate(zip(lines, headings, fenced)):
        if heading is not None:
            current = heading
            continue
        if in_fence or current != f"## {section}":
            continue
        match = BACKLOG_ITEM_RE.match(line.lstrip("﻿").rstrip())
        if not match:
            continue
        state = BACKLOG_STATES[match.group("mark")]
        text = _backlog_item_text(match.group("body"))[0]
        if text == item or (state == "cancelled" and _backlog_uncancelled(text) == item):
            found[state].append(index)
    return found


def _backlog_mark_lines(lines: List[str], section: str, item: str) -> Tuple[List[int], List[int]]:
    """(unchecked, checked) lines of `item` in `## <section>`; cancelled `[-]` lines are in neither."""
    found = _backlog_item_lines(lines, section, item)
    return found["open"], found["done"]


def backlog_parse(path: str, section: Optional[str] = None, state: str = "open") -> Dict[str, Any]:
    """Items of BACKLOG.md with their state (open `[ ]`, done `[x]`, cancelled `[-]`), optionally of one
    section; `state` keeps one state (default open) or `all`."""
    if state not in BACKLOG_STATE_FILTERS:
        raise InputError(f"state must be one of: {', '.join(BACKLOG_STATE_FILTERS)}")
    items: List[Dict[str, Any]] = []
    current: Optional[str] = None
    raw_lines = _read_source(path).split("\n")
    headings, fenced = _backlog_scan(raw_lines)
    for number, (raw, heading, in_fence) in enumerate(zip(raw_lines, headings, fenced), start=1):
        if heading is not None:
            current = heading[3:].strip() if heading.startswith("## ") else None
            continue
        if in_fence:
            continue
        match = BACKLOG_ITEM_RE.match(raw.lstrip("﻿").rstrip())
        if not match:
            continue
        item_state = BACKLOG_STATES[match.group("mark")]
        if (state != "all" and item_state != state) or (section is not None and current != section):
            continue
        text, source, day = _backlog_item_text(match.group("body"))
        items.append({"section": current, "text": text, "source": source, "date": day, "line": number,
                      "state": item_state})
    return {"ok": True, "items": items}


# backlog-sweep walks the whole root for the section's journal: a dot in a directory name, `.plans`
# and .gitignore do not matter, only these directories are skipped.
BACKLOG_SWEEP_SKIP_DIRS = (".git", "node_modules", "__pycache__", ".venv", "venv")


def _section_journals(root: str, section: str) -> List[str]:
    """Absolute paths of every `<section>-chain.json` under `root` (exact name), sorted."""
    name = _check_goal(section) + JOURNAL_SUFFIX
    found: List[str] = []
    for directory, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in BACKLOG_SWEEP_SKIP_DIRS)
        if name in files:
            found.append(os.path.abspath(os.path.join(directory, name)))
    return sorted(found)


# Tree snapshot (spec 2 of plan-refactoring-04): every file under a root, for executor_tool.py delegate-check and the
# diff guard of next_review_index.py (both load this file by path). Directories with these names are not walked, .git
# never is; a write into them is seen only through the subagent's `Written files:` block.
TREE_SKIP_DIRS = ("node_modules", ".venv", "venv", "__pycache__", ".pytest_cache", "dist", "build")
TREE_LARGE_BYTES = 8 * 1024 * 1024  # a larger file keeps its size and mtime, without a hash


def _tree_file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_entry(path: str) -> List[Any]:
    """[size, sha256, mtime_ns, label] of one file (a link to a file counts by its target): label None with the hash;
    `large` (size > TREE_LARGE_BYTES) with the mtime and no hash; `unreadable` when the file cannot be read (size None
    when it cannot be stat-ed either, e.g. a broken link)."""
    try:
        info = os.stat(path)
    except OSError:
        return [None, None, None, "unreadable"]
    if info.st_size > TREE_LARGE_BYTES:
        return [info.st_size, None, info.st_mtime_ns, "large"]
    try:
        return [info.st_size, _tree_file_sha256(path), None, None]
    except OSError:
        return [info.st_size, None, None, "unreadable"]


def tree_snapshot(root: str, skip: Iterable[str] = ()) -> Dict[str, List[Any]]:
    """{root-relative path with forward slashes: [size, sha256 or None, mtime_ns or None, label]} of every file under
    `root`, the files git ignores included. `.git` and the TREE_SKIP_DIRS names are skipped at any depth, links to
    directories are not walked, and `skip` names root-relative paths to leave out (the caller's own snapshot file)."""
    left_out = {str(path).replace("\\", "/") for path in skip}
    skipped = set(TREE_SKIP_DIRS) | {".git"}
    entries: Dict[str, List[Any]] = {}
    for directory, dirs, files in os.walk(root):
        dirs[:] = sorted(name for name in dirs if name not in skipped)
        for name in sorted(files):
            if name == ".git":  # a worktree's or submodule's .git file
                continue
            path = os.path.join(directory, name)
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            if rel not in left_out:
                entries[rel] = _tree_entry(path)
    return entries


def tree_diff(before: Dict[str, Any], after: Dict[str, Any]) -> List[str]:
    """Paths of two tree_snapshot results that appeared, disappeared or changed (size, hash, the mtime of a `large`
    file, the label), sorted."""
    return sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))


SPEC_ITEM_RE = re.compile(r"^(?:[-*]|\d+\.)\s+(?P<text>.+)$")
FINDINGS_HEADING = "### Findings Traceability"


def _is_table_separator(line: str) -> bool:
    return line.startswith("|") and "-" in line and re.fullmatch(r"[\s|:\-]+", line) is not None


def _spec_item_heads(lines: List[str]) -> List[str]:
    """Heads of a spec section's items: a top-level list item up to its first ': ', a ###/#### subheading,
    a table row other than the header and the separator (cells joined by ' | ')."""
    heads: List[str] = []
    for index, line in enumerate(lines):
        if line.startswith("|"):
            following = lines[index + 1] if index + 1 < len(lines) else ""
            if not (_is_table_separator(line) or _is_table_separator(following)):
                heads.append(" | ".join(cell.strip() for cell in line.strip().strip("|").split("|")))
        elif re.match(r"^#{3,4}\s", line):
            heads.append(line.lstrip("#").strip())
        else:
            match = SPEC_ITEM_RE.match(line)
            if match:
                heads.append(match.group("text").split(": ", 1)[0].strip())
    return heads


def _spec_excerpt(journal_dir: str, rel: str) -> Dict[str, Any]:
    """What backlog-sweep shows of one spec of the journal: Goal, item heads of Components and Findings
    Traceability, Out of Scope items. A missing file: missing; an unreadable one: error."""
    path = os.path.normpath(os.path.join(os.path.abspath(journal_dir), rel))
    entry: Dict[str, Any] = {"path": rel, "file": path}
    if not os.path.isfile(path):
        return dict(entry, missing=True)
    try:
        text = _read_source(path)
    except InputError as exc:
        return dict(entry, error=str(exc))
    sections: Dict[str, List[str]] = {}
    current: Optional[str] = None
    for _, line in _unfenced_lines(text):
        if line in SPEC_HEADINGS:
            current = line
            sections[current] = []
            continue
        if line == FINDINGS_HEADING and current in ("## Components", FINDINGS_HEADING):
            current = FINDINGS_HEADING
            sections.setdefault(current, [])
            continue
        if current == FINDINGS_HEADING and re.match(r"^###\s", line):
            current = "## Components"
        if current is not None:
            sections[current].append(line)
    out_of_scope = [m.group("text") for m in map(SPEC_ITEM_RE.match, sections.get("## Out of Scope", [])) if m]
    return dict(entry, goal="\n".join(sections.get("# Goal", [])).strip(),
                components=_spec_item_heads(sections.get("## Components", [])),
                findings=_spec_item_heads(sections.get(FINDINGS_HEADING, [])), out_of_scope=out_of_scope)


def backlog_sweep(root: str, section: str, journal: Optional[str] = None) -> Dict[str, Any]:
    """Read-only input of the backlog sweep: the open items of `## <section>` in <root>/BACKLOG.md and the
    specs of the section's chain journal with their excerpts. Writes nothing."""
    if not os.path.isdir(root):
        raise InputError(f"root is not a directory: {root}")
    section = _backlog_field("section", section)
    backlog = os.path.abspath(os.path.join(root, BACKLOG_FILE))
    items = backlog_parse(backlog, section)["items"] if os.path.isfile(backlog) else []
    result: Dict[str, Any] = {"ok": True, "root": os.path.abspath(root), "section": section,
                              "backlog": backlog, "items": items}
    if journal is None:
        journals = _section_journals(root, section)
        if len(journals) > 1:
            return dict(result, ok=False, journal=None, specs=[], journals=journals,
                        errors=[f"ambiguous-journal: {len(journals)} files {section}{JOURNAL_SUFFIX} under {root}"])
        if not journals:
            return dict(result, journal=None, specs=[])
        journal = journals[0]
    journal = os.path.abspath(journal)
    specs = journal_load(journal).get("specs")
    if not (isinstance(specs, list) and all(isinstance(s, dict) and isinstance(s.get("path"), str) for s in specs)):
        raise InputError(f"journal-corrupt: {journal}: 'specs' must be a list of {{path, sha256}} objects")
    directory = os.path.dirname(journal)
    return dict(result, journal=journal, specs=[_spec_excerpt(directory, spec["path"]) for spec in specs])


def cmd_backlog_append(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    result = backlog_append(args.root, args.section, args.source, args.item,
                            lang=args.lang, plain=args.plain, date=args.date)
    return 0, result


def cmd_backlog_parse(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    return 0, backlog_parse(args.file, args.section, args.state)


def cmd_backlog_mark(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    result = backlog_mark(args.root, args.section, args.item)
    return (0 if result["ok"] else 1), result


def cmd_backlog_unmark(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    result = backlog_unmark(args.root, args.section, args.item)
    return (0 if result["ok"] else 1), result


def cmd_backlog_sweep(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    result = backlog_sweep(args.root, args.section, args.journal)
    return (0 if result["ok"] else 1), result


# Chain journal <goal>-chain.json (spec plan-chain-runner-1, section A): stages of every plan of a
# goal, questions, out-of-plan findings and an append-only event log.
JOURNAL_VERSION = 1
JOURNAL_SUFFIX = "-chain.json"
FOLLOWUPS_SUFFIX = "-followups.json"
STAGES = ("writing", "revision", "split", "execution", "diffs", "audit", "commit")
STAGE_STATUSES = ("pending", "running", "done", "stopped", "failed", "skipped")
STAGE_OWNERS = {"writing": "plan-writing", "revision": "plan-iterative-revision", "split": "plan-splitter",
                "execution": "plan-executor", "diffs": "plan-executor", "audit": "plan-resolver", "commit": "plan-executor"}
REENTRY_REASONS = ("drift", "audit-open", "recommit", "user-request")
EVENT_KINDS = ("stage-start", "stage-end", "stage-update", "unit-begin", "unit-finish", "question", "answer",
               "applied", "finding", "commit", "reconcile", "lock-takeover", "diffs-rebuilt")
LOCK_WAIT_SECONDS = 10.0
LOCK_STALE_SECONDS = 60.0

# Optional `runner` section of the journal (spec plan-chain-runner-2, section C): written by
# plan-chain-runner's chain_tool.py (run-init, run-session), checked by journal-validate.
RUNNER_VERSION = 1
RUNNER_PROFILES = ("claude-code", "github-copilot", "fallback")
ROLES = ("writing", "revision", "split", "execution", "audit", "commit")
RUNNER_SESSION_ENDS = ("stopped", "complete", "interrupted")
RUNNER_START_COMMIT_RE = re.compile(r"^(?:[0-9a-f]{7,64}|declined|none)$")
# runner.roadmap_sha256 (spec 10 of plan-refactoring-01): sha256 of the goal roadmap run-init read.
RUNNER_ROADMAP_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
# runner.host_errors and runner.writing_resumes (spec plan-refactoring-03): optional lists of chain_tool.py host-wait
# and writing-resume; at_event = len(events) when written (the scheduler orders records by events, not by the clock).
RUNNER_HOST_ERROR_KEYS = ("plan", "stage", "at", "error", "attempt", "wait_seconds", "wait_until", "waited_total",
                          "at_event")
RUNNER_EXHAUSTED_KEYS = ("plan", "stage", "attempt", "event")
RUNNER_WRITING_RESUME_KEYS = ("plan", "tasks", "bytes", "sha256", "at_event")


class JournalError(Exception):
    """Journal contract violation: illegal transition, held lock, open questions (exit 1)."""


def _now() -> float:
    """Current time in seconds; tests monkeypatch it."""
    return time.time()


def _iso_now() -> str:
    """_now() in UTC as YYYY-MM-DDTHH:MM:SSZ."""
    return datetime.datetime.fromtimestamp(_now(), datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _check_goal(goal: str) -> str:
    """The goal names files next to the spec: no path separators or reserved characters."""
    if not goal or goal in (".", "..") or re.search(r'[\\/:*?"<>|\x00-\x1f]', goal):
        raise InputError(f"journal-goal-invalid: {goal!r}")
    return goal


def _strip_suffix(name: str, suffix: str) -> str:
    return name[:-len(suffix)] if name.endswith(suffix) and name != suffix else os.path.splitext(name)[0]


def _goal_roadmap_goal(text: str) -> Optional[str]:
    """The goal named by a '> Goal:' line among the first ten lines (a goal roadmap), else None."""
    return next((m.group("goal") for m in map(GOAL_ROADMAP_RE.match, text.splitlines()[:10]) if m), None)


def journal_path_for(path: str) -> Dict[str, Any]:
    """Journal of a spec, plan, roadmap or part: roadmap/part → master plan → spec at **Spec:**. A goal
    roadmap ('> Goal:' in its first ten lines) → the goal's journal next to it, `kind: goal-roadmap`."""
    current = os.path.abspath(path)
    text = _read_source(current)
    warnings: List[str] = []
    source = next((m.group("target") for m in map(SOURCE_RE.match, text.splitlines()[:10]) if m), None)
    roadmap_goal = _goal_roadmap_goal(text)
    if roadmap_goal is not None:
        if source is not None:
            warnings.append(f"roadmap-both-markers: {os.path.basename(current)}: '> Goal:' wins over Source")
        journal = os.path.join(os.path.dirname(current), _check_goal(roadmap_goal) + JOURNAL_SUFFIX)
        return {"ok": True, "journal": journal, "goal": roadmap_goal, "spec": None, "plan": None,
                "kind": "goal-roadmap", "exists": os.path.isfile(journal), "warnings": warnings}
    if source is None and os.path.basename(current).endswith("-roadmap.md"):
        warnings.append(f"roadmap-without-markers: {os.path.basename(current)}")
    if source is not None:
        current = os.path.normpath(os.path.join(os.path.dirname(current), source))
        if not os.path.isfile(current):
            raise InputError(f"journal-source-missing: {current}")
        text = _read_source(current)
    spec: Optional[str] = None
    plan: Optional[str] = None
    header = parse_plan_header(text)
    if header["spec"] is not None:
        plan = current
        spec = os.path.normpath(os.path.join(os.path.dirname(current), header["spec"]))
        if not os.path.isfile(spec):
            raise InputError(f"journal-source-missing: {spec}")
    elif any(line == "# Goal" for _, line in _unfenced_lines(text)):
        spec = current
    else:
        plan = current
    if spec is not None:
        goal = parse_metadata(_read_source(spec))["backlog"] or _strip_suffix(os.path.basename(spec), "-spec.md")
    else:
        goal = _strip_suffix(os.path.basename(plan or ""), "-impl.md")
    journal = os.path.join(os.path.dirname(spec or plan or ""), _check_goal(goal) + JOURNAL_SUFFIX)
    return {"ok": True, "journal": journal, "goal": goal, "spec": spec, "plan": plan,
            "exists": os.path.isfile(journal), "warnings": warnings}


def journal_load(journal: str) -> Dict[str, Any]:
    """The journal as a dict: missing → journal-missing, unreadable or not version 1 → journal-corrupt (exit 2).
    A PermissionError is retried for about a second: on Windows a reader takes no lock and can meet
    the moment a writer's os.replace swaps the file."""
    deadline = time.monotonic() + 1.0
    while True:
        try:
            with open(journal, "rb") as fh:
                raw = fh.read()
            break
        except FileNotFoundError as exc:
            raise InputError(f"journal-missing: {journal}") from exc
        except PermissionError as exc:
            if time.monotonic() >= deadline:
                raise InputError(f"cannot read {journal}: {exc}") from exc
            time.sleep(0.05)
        except OSError as exc:
            raise InputError(f"cannot read {journal}: {exc}") from exc
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except ValueError as exc:
        raise InputError(f"journal-corrupt: {journal}: {exc}") from exc
    if not isinstance(data, dict) or data.get("version") != JOURNAL_VERSION:
        raise InputError(f"journal-corrupt: {journal}: not a version {JOURNAL_VERSION} journal object")
    return data


def _lock_stamp(lock: str) -> Optional[int]:
    """mtime of the lock file in ns, or None when it is gone. Only stat: an open handle of a
    waiter would make the owner's os.remove fail on Windows."""
    try:
        return os.stat(lock).st_mtime_ns
    except OSError:
        return None


def _lock_age(lock: str) -> float:
    """Seconds since the lock file was written (its mtime); 0 when it is gone."""
    stamp = _lock_stamp(lock)
    return 0.0 if stamp is None else _now() - stamp / 1e9


def _remove_quiet(path: str, retry_seconds: float = 0.0) -> bool:
    """Remove a file; True when it is gone (also when someone else removed it first). A
    PermissionError (Windows: another process has the file open) is retried for `retry_seconds`."""
    deadline = time.monotonic() + retry_seconds
    while True:
        try:
            os.remove(path)
        except FileNotFoundError:
            return True
        except PermissionError:
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.05)
            continue
        except OSError:
            return False
        return True


def _take_over(lock: str, seen: int) -> bool:
    """Move an abandoned lock aside in one step and keep it aside only when it is the file judged
    abandoned (mtime `seen`). A fresh lock taken in between goes back while its path is free."""
    aside = f"{lock}.stale-{os.getpid()}-{int(_now() * 1000)}"
    try:
        os.replace(lock, aside)
    except OSError:
        return False
    if _lock_stamp(aside) == seen:
        _remove_quiet(aside)
        return True
    try:
        os.link(aside, lock)  # not os.replace: a lock created meanwhile must not be overwritten
    except OSError:
        pass
    _remove_quiet(aside)
    return False


@contextlib.contextmanager
def _journal_lock(journal: str) -> Iterator[bool]:
    """Exclusive `<journal>.lock`; yields True when an abandoned lock was taken over."""
    lock = os.path.abspath(journal) + ".lock"
    deadline = _now() + LOCK_WAIT_SECONDS
    took_over = False
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            seen = _lock_stamp(lock)
            if seen is not None and _lock_age(lock) > LOCK_STALE_SECONDS and _take_over(lock, seen):
                took_over = True
                continue
            if _now() >= deadline:
                raise JournalError(f"journal-locked: {lock}")
            time.sleep(0.05)
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"pid": os.getpid(), "at": _now()}, fh)
        break
    try:
        yield took_over
    finally:
        _remove_quiet(lock, retry_seconds=1.0)


def _new_journal(goal: str, lang: str) -> Dict[str, Any]:
    return {"version": JOURNAL_VERSION, "goal": goal, "lang": lang, "created_at": _iso_now(),
            "specs": [], "plans": [], "questions": [], "findings": [], "events": [],
            "limits": {"enabled": False, "time_minutes": None, "cost": None}}


def _journal_append_event(data: Dict[str, Any], skill: Optional[str], plan: Optional[str],
                          stage: Optional[str], kind: str, payload: Dict[str, Any]) -> None:
    data["events"].append({"at": _iso_now(), "skill": skill, "plan": plan, "stage": stage, "kind": kind, "data": payload})


def journal_update(journal: str, mutate: Callable[[Dict[str, Any]], Any],
                   create: Optional[Dict[str, Any]] = None) -> Any:
    """Lock → load (`create` when the file is missing) → mutate → atomic save when anything changed."""
    journal = os.path.abspath(journal)
    if create is None and not os.path.isfile(journal):
        raise InputError(f"journal-missing: {journal}")
    try:
        with _journal_lock(journal) as took_over:
            exists = os.path.isfile(journal)
            data = journal_load(journal) if exists or create is None else create
            before = json.dumps(data, sort_keys=True) if exists else None
            result = mutate(data)
            if took_over:
                _journal_append_event(data, None, None, None, "lock-takeover", {"lock": journal + ".lock"})
            if json.dumps(data, sort_keys=True) != before:
                _atomic_write_text(journal, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    except OSError as exc:  # read-only file or folder, full disk: a JSON error (exit 1), not a traceback
        raise JournalError(f"journal-write-failed: {journal}: {exc}") from exc
    return result


def _journal_rel(journal: str, path: str) -> str:
    """`path` relative to the journal's directory with forward slashes (absolute on another drive)."""
    try:
        rel = os.path.relpath(os.path.abspath(path), os.path.dirname(os.path.abspath(journal)))
    except ValueError:
        rel = os.path.abspath(path)
    return rel.replace("\\", "/")


def journal_create(journal: str, goal: str, lang: str, spec: Optional[str] = None,
                   plan: Optional[str] = None) -> Dict[str, Any]:
    """Create the journal when missing, register the spec once and, with `plan`, the plan's entry."""
    journal = os.path.abspath(journal)
    fresh = _new_journal(_check_goal(goal), lang)

    def mutate(data: Dict[str, Any]) -> bool:
        if spec is not None:
            rel = _journal_rel(journal, spec)
            if all(entry.get("path") != rel for entry in data["specs"]):
                data["specs"].append({"path": rel, "sha256": _sha256(spec)})
        if plan is not None:
            _plan_entry(data, journal, plan, spec=spec)  # every stage pending; an existing entry stays
        return data is fresh

    created = journal_update(journal, mutate, create=fresh)
    return {"ok": True, "journal": journal, "created": created}


def cmd_journal_path(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    result = journal_path_for(args.file)
    if args.create:
        lang = detect_lang_text(_read_source(result["spec"] or result["plan"] or args.file))
        result["created"] = journal_create(result["journal"], result["goal"], lang, result["spec"],
                                           result["plan"])["created"]
        result["exists"] = True
    return 0, result


# Allowed stage transitions (spec A «Переходы»); done → running also needs a re-entry reason.
STAGE_TRANSITIONS = {"pending": ("running", "skipped"), "running": ("done", "stopped", "failed", "skipped"),
                     "stopped": ("running",), "failed": ("running",), "done": ("running",), "skipped": ()}
REENTRY_STAGES = {"drift": STAGES, "audit-open": ("audit",), "recommit": ("commit",),
                  "user-request": ("revision", "audit")}


def _plan_entry(data: Dict[str, Any], journal: str, plan_path: str, spec: Optional[str] = None,
                create: bool = True) -> Dict[str, Any]:
    """Plan record by plan file or id; the first event of an unknown plan file creates it."""
    name = os.path.basename(plan_path.replace("\\", "/"))
    is_file = name.lower().endswith(".md")  # the same rule as _journal_plan_id: .MD is a plan file too
    plan_id = name[:-3] if is_file else name
    for entry in data["plans"]:
        if entry.get("id") == plan_id:
            if spec is not None:  # a question asked before plan-writing binds the entry to its spec
                rel = _journal_rel(journal, spec)
                if entry.get("spec") is None:
                    entry["spec"] = rel
                elif entry["spec"] != rel:
                    raise InputError(f"journal-plan-unknown: plan {plan_id} belongs to spec {entry['spec']}, not {rel}")
            return entry
    if not create or not is_file:
        raise InputError(f"unknown-plan: {plan_path}")
    if spec is not None:
        spec_rel: Optional[str] = _journal_rel(journal, spec)
    else:
        spec_rel = data["specs"][0]["path"] if len(data["specs"]) == 1 else None
    entry = {"id": plan_id, "spec": spec_rel, "plan": _journal_rel(journal, plan_path),
             "stages": {stage: {"status": "pending"} for stage in STAGES}}
    data["plans"].append(entry)
    return entry


def _drift_confirmed(data: Dict[str, Any], entry: Dict[str, Any], stage: str, journal: str) -> bool:
    """drift re-entry: a question 'drift: <stage> …' of this plan and stage was answered (or applied),
    or the stage's stored input no longer has its input_sha256."""
    if any(q.get("plan") == entry["id"] and q.get("stage") == stage and q.get("status") in ("answered", "applied")
           and str(q.get("text", "")).startswith(f"drift: {stage} ") for q in data["questions"]):
        return True
    record = entry["stages"][stage]
    if not record.get("input") or not record.get("input_sha256"):
        return False
    path = os.path.join(os.path.dirname(os.path.abspath(journal)), record["input"])
    try:
        return _sha256(path) != record["input_sha256"]
    except OSError:
        return False


def _check_transition(data: Dict[str, Any], entry: Dict[str, Any], stage: str, old: str, new: str,
                      reason: Optional[str], journal: str) -> None:
    """JournalError unless `old → new` is allowed for this stage of this plan; X → X is an update.
    The conditions of done → running read the stored journal, before this call's artifacts."""
    if old == new:
        return
    if new not in STAGE_TRANSITIONS[old]:
        raise JournalError(f"illegal-transition: {stage} {old} → {new}")
    if old == "stopped":
        open_ids = [q["id"] for q in data["questions"]
                    if q.get("plan") == entry["id"] and q.get("stage") == stage and q.get("status") == "open"]
        if open_ids:
            raise JournalError("open-questions: " + ", ".join(open_ids))
    if old == "done":
        allowed = reason in REENTRY_STAGES and stage in REENTRY_STAGES[reason]
        if allowed and reason == "audit-open":
            allowed = entry["stages"]["audit"].get("artifacts", {}).get("status") == "open"
        if allowed and reason == "drift":
            allowed = _drift_confirmed(data, entry, stage, journal)
        if not allowed:
            raise JournalError(f"illegal-transition: {stage} {old} → {new} (re-entry reason: {reason or 'none'})")


def _apply_artifacts(record: Dict[str, Any], artifacts: Optional[List[str]]) -> None:
    """`key=value` sets a string, `key[]=value` appends to a list once."""
    store = record.setdefault("artifacts", {})
    for item in artifacts or []:
        key, sep, value = item.partition("=")
        name = key[:-2] if key.endswith("[]") else key
        if not sep or not name.strip():
            raise InputError(f"bad artifact '{item}' (expected key=value or key[]=value)")
        if not key.endswith("[]"):
            store[name] = value
            continue
        values = store.setdefault(name, [])
        if not isinstance(values, list):
            raise InputError(f"artifact '{name}' is not a list")
        if value not in values:
            values.append(value)


def journal_event(journal: str, skill: str, plan: str, stage: str, status: str, reason: Optional[str] = None,
                  input_path: Optional[str] = None, artifacts: Optional[List[str]] = None,
                  data: Optional[Dict[str, Any]] = None, spec: Optional[str] = None) -> Dict[str, Any]:
    """Checked stage transition of a plan plus its event; X → X merges artifacts (stage-update)."""
    if stage not in STAGES or status not in STAGE_STATUSES:
        raise InputError(f"unknown stage or status: {stage} {status} "
                         f"(stages: {', '.join(STAGES)}; statuses: {', '.join(STAGE_STATUSES)})")
    if data is not None and not isinstance(data, dict):
        raise InputError("event data must be a JSON object")
    digest = None
    if input_path is not None and status == "done":
        try:
            digest = _sha256(input_path)
        except OSError as exc:
            raise InputError(f"cannot read {input_path}: {exc}") from exc
    journal = os.path.abspath(journal)

    def mutate(doc: Dict[str, Any]) -> Dict[str, Any]:
        entry = _plan_entry(doc, journal, plan, spec=spec)
        record = entry["stages"][stage]
        old = record["status"]
        _check_transition(doc, entry, stage, old, status, reason, journal)  # the stored state decides
        _apply_artifacts(record, artifacts)
        record["status"] = status
        if old != status and status == "running":
            record["started_at"] = _iso_now()
            record.pop("finished_at", None)
        elif old != status:
            record["finished_at"] = _iso_now()
        if digest is not None:
            record["input"], record["input_sha256"] = _journal_rel(journal, input_path or ""), digest
        if old == status:
            kind = "diffs-rebuilt" if stage == "diffs" else "stage-update"
        else:
            kind = "stage-start" if status == "running" else "stage-end"
        payload = dict(data or {}, **{"from": old, "to": status})
        if reason:
            payload["reason"] = reason
        _journal_append_event(doc, skill, entry["id"], stage, kind, payload)
        return {"ok": True, "plan": entry["id"], "stage": stage, "from": old, "to": status, "changed": old != status}

    return journal_update(journal, mutate)


def _json_object(text: Optional[str], name: str) -> Optional[Dict[str, Any]]:
    if text is None:
        return None
    try:
        value = json.loads(text)
    except ValueError as exc:
        raise InputError(f"{name} is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise InputError(f"{name} must be a JSON object")
    return value


def cmd_journal_event(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    return 0, journal_event(args.journal, args.skill, args.plan, args.stage, args.status, reason=args.reason,
                            input_path=args.input, artifacts=args.artifact,
                            data=_json_object(args.data, "--data"), spec=args.spec)


def journal_unit(journal: str, plan: str, kind: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Unit event of plan-executor (stage execution); no stage transition."""
    if kind not in ("unit-begin", "unit-finish"):
        raise InputError(f"unknown unit event kind: {kind} (unit-begin, unit-finish)")
    if not isinstance(data, dict):
        raise InputError("unit event data must be a JSON object")
    journal = os.path.abspath(journal)

    def mutate(doc: Dict[str, Any]) -> Dict[str, Any]:
        entry = _plan_entry(doc, journal, plan)
        _journal_append_event(doc, "plan-executor", entry["id"], "execution", kind, data)
        return {"ok": True, "plan": entry["id"], "kind": kind}

    return journal_update(journal, mutate)


def journal_question(journal: str, skill: str, plan: str, stage: str, text: str,
                     options: Optional[List[str]] = None, answer: Optional[str] = None,
                     spec: Optional[str] = None) -> Dict[str, Any]:
    """New Qn. Without an answer it stays open and a running stage stops; with one it is answered at once."""
    if stage not in STAGES:
        raise InputError(f"unknown stage: {stage} (stages: {', '.join(STAGES)})")
    if not (text or "").strip() or (answer is not None and not answer.strip()):
        raise InputError("question text and answer must be non-empty")
    journal = os.path.abspath(journal)
    return journal_update(journal, lambda doc: _add_question(doc, journal, skill, plan, stage, text, options, answer,
                                                             spec=spec))


def _add_question(doc: Dict[str, Any], journal: str, skill: str, plan: str, stage: str, text: str,
                  options: Optional[List[str]] = None, answer: Optional[str] = None,
                  spec: Optional[str] = None) -> Dict[str, Any]:
    """journal_question inside a mutate that already holds the lock; `spec` as in journal_event."""
    entry = _plan_entry(doc, journal, plan, spec=spec)
    record = entry["stages"][stage]
    qid = f"Q{len(doc['questions']) + 1}"
    question = {"id": qid, "plan": entry["id"], "stage": stage, "skill": skill, "text": text,
                "options": list(options or []), "status": "open", "answer": None,
                "asked_at": _iso_now(), "answered_at": None}
    doc["questions"].append(question)
    if answer is None and record["status"] == "running":
        record["status"], record["finished_at"] = "stopped", _iso_now()
        _journal_append_event(doc, skill, entry["id"], stage, "stage-end",
                              {"from": "running", "to": "stopped", "question": qid})
    _journal_append_event(doc, skill, entry["id"], stage, "question", {"id": qid, "text": text})
    if answer is not None:
        question.update(status="answered", answer=answer, answered_at=_iso_now())
        _journal_append_event(doc, skill, entry["id"], stage, "answer", {"id": qid, "answer": answer})
    return {"ok": True, "id": qid, "status": question["status"], "stage_status": record["status"]}


def cmd_journal_unit(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    return 0, journal_unit(args.journal, args.plan, args.kind, _json_object(args.data, "--data") or {})


def cmd_journal_question(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    return 0, journal_question(args.journal, args.skill, args.plan, args.stage, args.text,
                               options=args.option, answer=args.answer, spec=args.spec)


def journal_answer(journal: str, qid: str, answer: Optional[str] = None, applied: bool = False) -> Dict[str, Any]:
    """open → answered (needs an answer); answered → applied (the owner skill applied it)."""
    journal = os.path.abspath(journal)

    def mutate(doc: Dict[str, Any]) -> Dict[str, Any]:
        question = next((q for q in doc["questions"] if q.get("id") == qid), None)
        if question is None:
            raise InputError(f"unknown-question: {qid}")
        old = question["status"]
        if applied:
            if old != "answered":
                raise JournalError(f"illegal-transition: {qid} {old} → applied")
            question.update(status="applied", applied_at=_iso_now())
            kind, payload = "applied", {"id": qid}
        else:
            if not (answer or "").strip():
                raise JournalError(f"answer-required: {qid}")
            if old != "open":
                raise JournalError(f"illegal-transition: {qid} {old} → answered")
            question.update(status="answered", answer=answer, answered_at=_iso_now())
            kind, payload = "answer", {"id": qid, "answer": answer}
        _journal_append_event(doc, question.get("skill"), question.get("plan"), question.get("stage"), kind, payload)
        return {"ok": True, "id": qid, "status": question["status"]}

    return journal_update(journal, mutate)


def cmd_journal_answer(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    return 0, journal_answer(args.journal, args.qid, answer=args.answer, applied=args.applied)


def journal_finding(journal: str, skill: str, plan: str, file: str, summary: str, failure_scenario: str,
                    line: Optional[int] = None, backlog_root: Optional[str] = None) -> Dict[str, Any]:
    """New out-of-plan finding Fn (findings-parse fields); the same file + summary is not recorded twice."""
    file = _normalize_path(file or "")
    summary, failure_scenario = (summary or "").strip(), (failure_scenario or "").strip()
    if not file or not summary or not failure_scenario:
        raise InputError("file, summary and failure_scenario must be non-empty")
    if line is not None and (isinstance(line, bool) or not isinstance(line, int) or line < 1):
        raise InputError("line must be a positive integer")
    journal = os.path.abspath(journal)

    def mutate(doc: Dict[str, Any]) -> Dict[str, Any]:
        entry = _plan_entry(doc, journal, plan)
        known = next((f for f in doc["findings"] if f.get("file") == file and f.get("summary") == summary), None)
        if known is not None:
            return {"ok": True, "id": known["id"], "action": "exists", "backlog": None}
        fid = f"F{len(doc['findings']) + 1}"
        result: Dict[str, Any] = {"ok": True, "id": fid, "action": "recorded", "backlog": None}
        if backlog_root is not None:
            item = f"{summary} ({file}:{line})" if line is not None else f"{summary} ({file})"
            source = f"{skill}, {os.path.basename(entry['plan'])}"
            try:
                outcome = backlog_append(backlog_root, doc["goal"], source, item, lang=doc.get("lang", "en"))
                result["backlog"] = "exists" if outcome["action"] == "exists" else "appended"
            except (BacklogError, InputError) as exc:  # the backlog is not a gate
                result["backlog"], result["backlog_error"] = "failed", str(exc)
        doc["findings"].append({"id": fid, "plan": entry["id"], "skill": skill, "file": file, "line": line,
                                "summary": summary, "failure_scenario": failure_scenario,
                                "recorded_at": _iso_now(), "backlog": result["backlog"]})
        _journal_append_event(doc, skill, entry["id"], None, "finding", {"id": fid, "file": file, "line": line})
        return result

    return journal_update(journal, mutate)


def cmd_journal_finding(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    return 0, journal_finding(args.journal, args.skill, args.plan, args.file, args.summary, args.failure_scenario,
                              line=args.line, backlog_root=args.backlog_root)


def journal_add_commit(journal: str, plan: str, sha: str, subject: str, files: List[str]) -> Dict[str, Any]:
    """A commit made by commit-run goes to stages.commit.artifacts.commits (once per sha); no transition."""
    if not re.match(r"^[0-9a-f]{7,64}$", sha or ""):
        raise InputError(f"bad commit sha: {sha}")
    journal = os.path.abspath(journal)

    def mutate(doc: Dict[str, Any]) -> Dict[str, Any]:
        entry = _plan_entry(doc, journal, plan)
        commits = entry["stages"]["commit"].setdefault("artifacts", {}).setdefault("commits", [])
        if all(commit.get("sha") != sha for commit in commits):
            commits.append({"sha": sha, "subject": subject, "files": list(files or []), "at": _iso_now()})
            _journal_append_event(doc, "plan-executor", entry["id"], "commit", "commit", {"sha": sha, "subject": subject})
        return {"ok": True, "plan": entry["id"], "sha": sha, "commits": len(commits)}

    return journal_update(journal, mutate)


def _followups_items(path: str) -> List[Any]:
    """Items of an existing <goal>-followups.json, [] when there is none. Not readable or not a JSON
    list: followups-unreadable (exit 2), and the export leaves the file as it is."""
    if not os.path.exists(path):
        return []
    try:
        items = json.loads(_read_source(path))
    except (InputError, ValueError) as exc:
        raise InputError(f"followups-unreadable: {path}: {exc}") from exc
    if not isinstance(items, list):
        raise InputError(f"followups-unreadable: {path}: not a JSON list")
    return items


def _finding_key(file: Any, summary: Any) -> Optional[Tuple[str, str]]:
    """file + summary as journal-finding compares them (path normalized, summary stripped); None for
    an item without both strings."""
    if not isinstance(file, str) or not isinstance(summary, str):
        return None
    return _normalize_path(file), summary.strip()


def journal_export_findings(journal: str) -> Dict[str, Any]:
    """Write <goal>-followups.json next to the journal in the findings-parse input format: the items
    already in the file first, as they are and in their order, then the journal's findings the file
    lacks (by file + summary), by id. A finding removed from the file by hand comes back from the journal."""
    data = journal_load(journal)
    goal = _check_goal(str(data.get("goal") or ""))
    path = os.path.join(os.path.dirname(os.path.abspath(journal)), goal + FOLLOWUPS_SUFFIX)
    items = _followups_items(path)
    known = {_finding_key(item.get("file"), item.get("summary")) for item in items if isinstance(item, dict)}
    for f in sorted(data.get("findings") or [], key=lambda f: int(f["id"][1:])):
        key = _finding_key(f["file"], f["summary"])
        if key is not None and key in known:
            continue
        known.add(key)
        items.append({"file": f["file"], "line": f.get("line"), "summary": f["summary"],
                      "failure_scenario": f["failure_scenario"]})
    try:
        _atomic_write_text(path, json.dumps(items, ensure_ascii=False, indent=2) + "\n")
    except OSError as exc:
        raise JournalError(f"journal-write-failed: {path}: {exc}") from exc
    return {"ok": True, "path": path, "count": len(items)}


def cmd_journal_commit(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    return 0, journal_add_commit(args.journal, args.plan, args.sha, args.subject, args.file)


def cmd_journal_export_findings(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    return 0, journal_export_findings(args.journal)


def _journal_plan_id(plan: str) -> str:
    """Plan id of a plan path ('docs/x-impl.md' -> 'x-impl'); an id is returned as is."""
    name = os.path.basename(plan.replace("\\", "/"))
    return name[:-3] if name.lower().endswith(".md") else name


def _journal_next_action(status: Optional[str], open_ids: List[str]) -> str:
    """What the owner of the current stage does next (status None: every stage is done or skipped)."""
    if status is None:
        return "complete"
    if status == "stopped":
        return "answer" if open_ids else "resume"
    return "retry" if status == "failed" else "run"


def _journal_progress(data: Dict[str, Any], plan_id: str) -> Optional[Dict[str, Any]]:
    """`done`/`total` of the plan's last unit-begin/unit-finish event, else None."""
    for event in reversed(data["events"]):
        if event.get("plan") == plan_id and event.get("kind") in ("unit-begin", "unit-finish"):
            info = event.get("data") or {}
            return {"done": info.get("done"), "total": info.get("total")}
    return None


def journal_show(journal: str, plan: Optional[str] = None) -> Dict[str, Any]:
    """Stage statuses of each plan, its current stage, the next action and the open questions."""
    data = journal_load(journal)
    wanted = _journal_plan_id(plan) if plan is not None else None
    entries = [entry for entry in data["plans"] if wanted is None or entry["id"] == wanted]
    if wanted is not None and not entries:
        raise InputError(f"unknown-plan: {plan}")
    asked = [q for q in data["questions"]
             if q.get("status") == "open" and (wanted is None or q.get("plan") == wanted)]
    plans: List[Dict[str, Any]] = []
    for entry in entries:
        stages = {name: entry["stages"].get(name, {}).get("status", "pending") for name in STAGES}
        current = next((name for name in STAGES if stages[name] not in ("done", "skipped")), None)
        mine = [q for q in asked if q.get("plan") == entry["id"]]
        # An open question waits for its answer whatever the status of its stage (a done audit too).
        plans.append({
            "id": entry["id"],
            "plan": entry["plan"],
            "stages": stages,
            "current": current,
            "next_action": "answer" if mine else _journal_next_action(stages[current] if current else None, []),
            "owner": (STAGE_OWNERS.get(mine[0].get("stage")) if mine
                      else STAGE_OWNERS[current] if current else None),
            "progress": _journal_progress(data, entry["id"]),
            "open_questions": [q["id"] for q in mine],
        })
    return {
        "ok": True,
        "goal": data["goal"],
        "lang": data["lang"],
        "plans": plans,
        "open_questions": [{key: q.get(key) for key in ("id", "plan", "stage", "text", "options")} for q in asked],
        "findings": len(data["findings"]),
        "limits": data["limits"],
    }


def cmd_journal_show(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    return 0, journal_show(args.journal, args.plan)


_VALIDATE_TOP_KEYS = (("version", int), ("goal", str), ("lang", str), ("created_at", str),
                      ("specs", list), ("plans", list), ("questions", list), ("findings", list),
                      ("events", list), ("limits", dict))
_VALIDATE_QUESTION_STATUSES = ("open", "answered", "applied")


# Fields of the list items and of limits (assets/chain-journal.schema.json). Ids, question statuses
# and event kinds are checked in _journal_structure_errors itself.
_VALIDATE_ITEM_STRINGS = {"specs": ("path", "sha256"),
                          "questions": ("plan", "stage", "skill", "text", "asked_at"),
                          "findings": ("plan", "skill", "file", "summary", "failure_scenario", "recorded_at"),
                          "events": ("at",)}
_VALIDATE_ITEM_NULLABLE = {"specs": (), "questions": ("answer", "answered_at"), "findings": ("backlog",),
                           "events": ("skill", "plan", "stage")}


def _journal_item_errors(data: Dict[str, Any]) -> List[str]:
    """Required keys and types of specs, questions, findings, events and limits; export and show
    read these fields, so a journal without them must not validate."""
    errors: List[str] = []
    for section, names in _VALIDATE_ITEM_STRINGS.items():
        for index, item in enumerate(data[section]):
            where = f"{section}[{index}]"
            if not isinstance(item, dict):
                errors.append(f"{where}: must be an object")
                continue
            errors.extend(f"{where}: '{name}' must be a non-empty string" for name in names
                          if not isinstance(item.get(name), str) or not item[name].strip())
            errors.extend(f"{where}: '{name}' must be a string or null" for name in _VALIDATE_ITEM_NULLABLE[section]
                          if name not in item or not (item[name] is None or isinstance(item[name], str)))
            if section == "questions" and not (isinstance(item.get("options"), list)
                                               and all(isinstance(option, str) for option in item["options"])):
                errors.append(f"{where}: 'options' must be a list of strings")
            if section == "findings":
                line = item.get("line", 0)  # the key is required too
                if line is not None and (isinstance(line, bool) or not isinstance(line, int) or line < 1):
                    errors.append(f"{where}: 'line' must be an integer ≥ 1 or null")
            if section == "events" and not isinstance(item.get("data"), dict):
                errors.append(f"{where}: 'data' must be dict")
    limits = data["limits"]
    if not isinstance(limits.get("enabled"), bool):
        errors.append("limits: 'enabled' must be a boolean")
    for name in ("time_minutes", "cost"):
        value = limits.get(name, "missing")
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))):
            errors.append(f"limits: '{name}' must be a number or null")
    return errors


def _journal_id_errors(items: List[Any], prefix: str, what: str) -> List[str]:
    ids = [item.get("id") if isinstance(item, dict) else None for item in items]
    if ids == [f"{prefix}{n}" for n in range(1, len(items) + 1)]:
        return []
    return [f"{what} ids must be {prefix}1..{prefix}{len(items)} in order, found: {ids}"]


def _runner_cycle(graph: Dict[str, List[str]]) -> Optional[List[str]]:
    """The first dependency cycle of `graph` (spec -> the specs it depends on) as a path whose last
    node repeats the first, e.g. ['a', 'b', 'a']; None without cycles. Keys and dependencies are
    visited in their stored order, so the answer is stable for one journal."""
    state: Dict[str, int] = {}  # 1 = on the current path, 2 = finished
    path: List[str] = []

    def visit(node: str) -> Optional[List[str]]:
        state[node] = 1
        path.append(node)
        for dep in graph.get(node, ()):
            if state.get(dep) == 1:
                return path[path.index(dep):] + [dep]
            if dep not in state:
                found = visit(dep)
                if found:
                    return found
        path.pop()
        state[node] = 2
        return None

    for node in graph:
        if node not in state:
            found = visit(node)
            if found:
                return found
    return None


def _runner_graph_errors(graph: Any, specs: Optional[List[str]]) -> List[str]:
    """runner.graph maps a spec to the specs it depends on: string lists; every key and dependency
    is one of `specs` (skipped when `specs` itself is invalid, None); no cycle."""
    if not (isinstance(graph, dict) and all(isinstance(deps, list) and all(isinstance(dep, str) for dep in deps)
                                             for deps in graph.values())):
        return ["runner: 'graph' must be an object of string lists"]
    errors: List[str] = []
    if specs is not None:
        known = set(specs)
        for key, deps in graph.items():
            if key not in known:
                errors.append(f"runner: graph key '{key}' is not in specs")
            errors.extend(f"runner: graph dependency '{dep}' of '{key}' is not in specs"
                          for dep in deps if dep not in known)
    cycle = _runner_cycle(graph)
    if cycle:
        errors.append("runner-graph-cycle: " + " -> ".join(cycle))
    return errors


def _runner_models_errors(models: Any) -> List[str]:
    """runner.models maps a role of ROLES to {"model", "effort"}, each a non-empty string or null
    (null model: profile fallback; null effort: inherited); other keys such as "fallback" are kept."""
    if not isinstance(models, dict):
        return ["runner: 'models' must be an object"]
    errors: List[str] = []
    for role, entry in models.items():
        if role not in ROLES:
            errors.append(f"runner: unknown role '{role}' in models (roles: {', '.join(ROLES)})")
        elif not (isinstance(entry, dict) and all(
                name in entry and (entry[name] is None or (isinstance(entry[name], str) and entry[name].strip()))
                for name in ("model", "effort"))):
            errors.append(f"runner: models.{role} needs 'model' and 'effort', each a non-empty string or null")
    return errors


def _runner_sessions_errors(sessions: Any) -> List[str]:
    """runner.sessions lists {"id", "started_at", "ended_at": str|null, "end": RUNNER_SESSION_ENDS|null};
    run-session --begin appends an open one, --end closes it."""
    if not isinstance(sessions, list):
        return ["runner: 'sessions' must be a list"]
    errors: List[str] = []
    for index, item in enumerate(sessions):
        where = f"runner: sessions[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{where}: must be an object")
            continue
        errors.extend(f"{where}: '{name}' must be a non-empty string" for name in ("id", "started_at")
                      if not isinstance(item.get(name), str) or not item[name].strip())
        if "ended_at" not in item or not (item["ended_at"] is None or isinstance(item["ended_at"], str)):
            errors.append(f"{where}: 'ended_at' must be a string or null")
        if "end" not in item or not (item["end"] is None or item["end"] in RUNNER_SESSION_ENDS):
            errors.append(f"{where}: 'end' must be one of {', '.join(RUNNER_SESSION_ENDS)} or null")
    return errors


def _runner_mark_ok(name: str, value: Any) -> bool:
    """One field of a host_errors / writing_resumes record or of exhausted_for: plan and error non-empty strings,
    stage in STAGES, at and wait_until journal times, sha256 64 hex, attempt an int >= 1, the rest an int >= 0."""
    if name in ("plan", "error"):
        return isinstance(value, str) and bool(value.strip())
    if name == "stage":
        return value in STAGES
    if name in ("at", "wait_until"):
        return isinstance(value, str) and bool(JOURNAL_TIME_RE.fullmatch(value))
    if name == "sha256":
        return isinstance(value, str) and bool(RUNNER_ROADMAP_SHA_RE.match(value))
    return isinstance(value, int) and not isinstance(value, bool) and value >= (1 if name == "attempt" else 0)


def _runner_marks_errors(runner: Dict[str, Any]) -> List[str]:
    """The optional runner.host_errors and runner.writing_resumes: every key of RUNNER_HOST_ERROR_KEYS /
    RUNNER_WRITING_RESUME_KEYS (_runner_mark_ok), exhausted_for with RUNNER_EXHAUSTED_KEYS."""
    errors: List[str] = []
    for key, names in (("host_errors", RUNNER_HOST_ERROR_KEYS), ("writing_resumes", RUNNER_WRITING_RESUME_KEYS)):
        items = runner.get(key, [])
        if not isinstance(items, list):
            errors.append(f"runner: '{key}' must be a list")
            continue
        for index, item in enumerate(items):
            where = f"runner: {key}[{index}]"
            if not isinstance(item, dict):
                errors.append(f"{where}: must be an object")
                continue
            errors.extend(f"{where}: '{name}' missing or invalid" for name in names
                          if not _runner_mark_ok(name, item.get(name)))
            mark = item.get("exhausted_for")
            if "exhausted_for" in item and not (key == "host_errors" and isinstance(mark, dict) and all(
                    _runner_mark_ok(name, mark.get(name)) for name in RUNNER_EXHAUSTED_KEYS)):
                errors.append(f"{where}: 'exhausted_for' invalid")
    return errors


def _runner_errors(runner: Any) -> List[str]:
    """Checks of the optional `runner` section (spec plan-chain-runner-2, section C): version,
    profile, specs, graph (membership, runner-graph-cycle), roles of models, start_commit, parallel,
    roadmap and roadmap_sha256 (optional keys), sessions. The optional host_errors and writing_resumes:
    _runner_marks_errors. Required keys: version, profile, specs, graph, models, sessions."""
    if not isinstance(runner, dict):
        return ["runner: must be an object"]
    errors: List[str] = []
    version = runner.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version != RUNNER_VERSION:
        errors.append(f"runner: 'version' must be {RUNNER_VERSION}")
    if runner.get("profile") not in RUNNER_PROFILES:
        errors.append(f"runner: 'profile' must be one of {', '.join(RUNNER_PROFILES)}")
    specs = runner.get("specs")
    if not (isinstance(specs, list) and all(isinstance(spec, str) and spec.strip() for spec in specs)):
        errors.append("runner: 'specs' must be a list of non-empty strings")
        specs = None
    errors.extend(_runner_graph_errors(runner.get("graph"), specs))
    errors.extend(_runner_models_errors(runner.get("models")))
    start = runner.get("start_commit", "none")
    if not (isinstance(start, str) and RUNNER_START_COMMIT_RE.match(start)):
        errors.append("runner: 'start_commit' must be a commit sha, 'declined' or 'none'")
    parallel = runner.get("parallel", 1)
    if isinstance(parallel, bool) or not isinstance(parallel, int) or parallel < 1:
        errors.append("runner: 'parallel' must be an integer >= 1")
    roadmap = runner.get("roadmap", "-")
    if not (isinstance(roadmap, str) and roadmap.strip()):
        errors.append("runner: 'roadmap' must be a non-empty string")
    digest = runner.get("roadmap_sha256", "0" * 64)
    if not (isinstance(digest, str) and RUNNER_ROADMAP_SHA_RE.match(digest)):
        errors.append("runner: 'roadmap_sha256' must be 64 lowercase hex digits")
    errors.extend(_runner_sessions_errors(runner.get("sessions")))
    errors.extend(_runner_marks_errors(runner))
    return errors


JOURNAL_TIME_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")


def _journal_time_errors(data: Dict[str, Any]) -> List[str]:
    """Time fields in the format of _iso_now, each error with its path. Null is allowed for stage
    started_at/finished_at, question answered_at and session ended_at; stage times and applied_at
    may be absent. Called on a journal whose top-level keys have their types."""
    fields: List[Tuple[str, Any, bool]] = [("created_at", data["created_at"], False)]
    for index, entry in enumerate(data["plans"]):
        stages = entry.get("stages") if isinstance(entry, dict) else None
        for stage, record in (stages.items() if isinstance(stages, dict) else ()):
            fields += [(f"plans[{index}].stages.{stage}.{name}", record[name], True)
                       for name in ("started_at", "finished_at") if isinstance(record, dict) and name in record]
    for index, question in enumerate(data["questions"]):
        if isinstance(question, dict):
            fields += [(f"questions[{index}].asked_at", question.get("asked_at"), False),
                       (f"questions[{index}].answered_at", question.get("answered_at"), True)]
            if "applied_at" in question:
                fields.append((f"questions[{index}].applied_at", question["applied_at"], False))
    fields += [(f"findings[{index}].recorded_at", item.get("recorded_at"), False)
               for index, item in enumerate(data["findings"]) if isinstance(item, dict)]
    fields += [(f"events[{index}].at", item.get("at"), False)
               for index, item in enumerate(data["events"]) if isinstance(item, dict)]
    runner = data.get("runner")
    sessions = runner.get("sessions") if isinstance(runner, dict) else None
    for index, item in enumerate(sessions if isinstance(sessions, list) else ()):
        if isinstance(item, dict):
            fields += [(f"runner.sessions[{index}].started_at", item.get("started_at"), False),
                       (f"runner.sessions[{index}].ended_at", item.get("ended_at"), True)]
    return [f"{where}: not a journal time (YYYY-MM-DDTHH:MM:SSZ)" for where, value, nullable in fields
            if not (value is None and nullable)
            and not (isinstance(value, str) and JOURNAL_TIME_RE.fullmatch(value))]


def _journal_structure_errors(data: Dict[str, Any], times: bool = True) -> List[str]:
    """Keys and types, plan ids, stage names and statuses, Qn/Fn ids, question states, event kinds,
    the optional runner section and, with `times`, the time fields (_journal_time_errors)."""
    errors = [f"'{key}' must be {kind.__name__}" for key, kind in _VALIDATE_TOP_KEYS
              if not isinstance(data.get(key), kind) or isinstance(data.get(key), bool)]
    if errors:
        return errors
    seen = set()
    for index, entry in enumerate(data["plans"]):
        where = f"plans[{index}]"
        if not (isinstance(entry, dict) and isinstance(entry.get("id"), str)
                and isinstance(entry.get("plan"), str) and isinstance(entry.get("stages"), dict)):
            errors.append(f"{where}: needs string 'id', string 'plan' and object 'stages'")
            continue
        if entry["id"] in seen:
            errors.append(f"{where}: duplicate plan id {entry['id']}")
        seen.add(entry["id"])
        errors.extend(f"{where}: unknown stage '{name}'" for name in entry["stages"] if name not in STAGES)
        for name in STAGES:
            record = entry["stages"].get(name)
            if not isinstance(record, dict) or record.get("status") not in STAGE_STATUSES:
                errors.append(f"{where}: stage '{name}' needs a status in {', '.join(STAGE_STATUSES)}")
                continue
            # the scheduler and the journal commands read these three; the schema types them
            for key, kind, article in (("artifacts", dict, "an object"), ("input", str, "a string"),
                                       ("input_sha256", str, "a string")):
                if key in record and not isinstance(record[key], kind):
                    errors.append(f"{where}: stage '{name}' '{key}' must be {article}")
    errors.extend(_journal_id_errors(data["questions"], "Q", "question"))
    for question in data["questions"]:
        if not isinstance(question, dict):
            continue
        status = question.get("status")
        if status not in _VALIDATE_QUESTION_STATUSES:
            errors.append(f"{question.get('id')}: status must be one of {', '.join(_VALIDATE_QUESTION_STATUSES)}")
        elif status != "open" and question.get("answer") is None:
            errors.append(f"{question.get('id')}: status {status} needs an answer")
    errors.extend(_journal_id_errors(data["findings"], "F", "finding"))
    for index, event in enumerate(data["events"]):
        if not isinstance(event, dict) or event.get("kind") not in EVENT_KINDS:
            errors.append(f"events[{index}]: kind must be one of {', '.join(EVENT_KINDS)}")
    errors.extend(_journal_item_errors(data))
    if times:  # before the runner errors: test_runner_errors_come_after_the_other_structure_errors_and_stop_the_replay
        errors.extend(_journal_time_errors(data))
    if "runner" in data:  # optional section of plan-chain-runner
        errors.extend(_runner_errors(data["runner"]))
    return errors


def _journal_replay_errors(data: Dict[str, Any]) -> List[str]:
    """stage-start/stage-end events follow the allowed moves from 'pending' (STAGE_TRANSITIONS, the
    table journal-event writes by; the reasons of done → running are checked when the event is
    written, the replay only checks the shape of the history); reconcile events repair without the
    rules; same-status events (stage-update, diffs-rebuilt) move nothing; the last status of every
    plan stage equals the stored one."""
    errors: List[str] = []
    replayed: Dict[Tuple[Any, Any], Any] = {}
    for index, event in enumerate(data["events"]):
        if event["kind"] not in ("stage-start", "stage-end", "reconcile"):
            continue
        info = event.get("data") if isinstance(event.get("data"), dict) else {}
        key = (event.get("plan"), event.get("stage"))
        before, after = info.get("from"), info.get("to")
        where = f"events[{index}] {key[0]} {key[1]}"
        current = replayed.get(key, "pending")
        if before != current:
            errors.append(f"{where}: from '{before}' but the replayed status is '{current}'")
        elif event["kind"] != "reconcile" and after not in STAGE_TRANSITIONS.get(before, ()):
            errors.append(f"{where}: illegal transition {before} → {after}")
        replayed[key] = after
    for entry in data["plans"]:
        for name in STAGES:
            stored, last = entry["stages"][name]["status"], replayed.get((entry["id"], name), "pending")
            if stored != last:
                errors.append(f"{entry['id']} {name}: stored status '{stored}' but the events end at '{last}'")
    return errors


def journal_validate(journal: str) -> Dict[str, Any]:
    """Executable check of assets/chain-journal.schema.json plus the replay of stage events."""
    data = journal_load(journal)
    errors = _journal_structure_errors(data)
    if not errors:
        errors = _journal_replay_errors(data)
    return {"ok": not errors, "errors": errors}


def cmd_journal_validate(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    result = journal_validate(args.journal)
    return (0 if result["ok"] else 1), result


def _latest_report(plan_dir: str, stem: str) -> Optional[Tuple[str, bool]]:
    """(name, final) of the highest '<stem>-report-N.md' / '<stem>-report-N-final.md' (resolver naming)."""
    pattern = re.compile(re.escape(stem) + r"-report-(?P<n>\d+)(?P<final>-final)?\.md$", re.IGNORECASE)
    found = [(int(m.group("n")), bool(m.group("final")), name)
             for name, m in ((name, pattern.match(name)) for name in os.listdir(plan_dir)) if m]
    if not found:
        return None
    _, final, name = max(found)
    return name, final


_EXEC_ATTEMPTS_LIMIT = 3  # executor_tool.ATTEMPTS_LIMIT: a failed unit with this many attempts gets no retry
_COMMIT_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")


def _ledger_evidence(journal: str, entry: Dict[str, Any],
                     warnings: List[str]) -> Optional[Tuple[Dict[str, str], str]]:
    """Execution is done when every unit of the ledger at artifacts.exec_dir is done."""
    exec_dir = (entry["stages"]["execution"].get("artifacts") or {}).get("exec_dir")
    if not exec_dir:
        return None
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(journal)), exec_dir, "state.json"),
                  "r", encoding="utf-8") as fh:
            units = json.load(fh).get("units")
    except (OSError, ValueError, AttributeError):
        return None
    if not isinstance(units, list) or not units or not all(isinstance(unit, dict) for unit in units):
        return None
    stuck = [str(unit.get("id")) for unit in units
             if unit.get("status") == "failed" and (unit.get("attempts") or 0) >= _EXEC_ATTEMPTS_LIMIT]
    if stuck:
        warnings.append(f"{entry['id']} execution: units without retries left: {', '.join(stuck)}")
    if all(unit.get("status") == "done" for unit in units):
        return {}, f"ledger: {len(units)} of {len(units)} units done"
    return None


def _commit_evidence(entry: Dict[str, Any], plan_dir: str) -> Optional[Tuple[Dict[str, str], str]]:
    """Commit is done when every recorded sha is a commit of the plan's repository."""
    commits = (entry["stages"]["commit"].get("artifacts") or {}).get("commits") or []
    shas = [item.get("sha") if isinstance(item, dict) else None for item in commits]
    if not shas or not all(isinstance(sha, str) and _COMMIT_SHA_RE.match(sha) for sha in shas):
        return None
    for sha in shas:
        try:
            probe = subprocess.run(["git", "cat-file", "-e", sha + "^{commit}"], cwd=plan_dir,
                                   capture_output=True, check=False)
        except OSError:
            return None
        if probe.returncode != 0:
            return None
    return {}, f"commits found in git: {len(shas)}"


def _plan_incomplete(plan_path: str) -> bool:
    """The plan file carries plan-writing's writing marker (spec 3 of plan-refactoring-02): it is still being
    written. An unreadable file counts as written, as before."""
    try:
        return writing_marker(_read_source(plan_path)) is not None
    except InputError:
        return False


def _stage_evidence(journal: str, entry: Dict[str, Any], stage: str,
                    warnings: List[str]) -> Optional[Tuple[Dict[str, str], str]]:
    """(artifacts, why) when the stage's own artifacts show it finished, else None."""
    plan_path = os.path.join(os.path.dirname(os.path.abspath(journal)), entry["plan"])
    plan_dir, stem = os.path.dirname(plan_path), os.path.splitext(os.path.basename(plan_path))[0]
    if not os.path.isdir(plan_dir):
        return None
    if stage == "writing":
        if not os.path.isfile(plan_path) or _plan_incomplete(plan_path):
            return None
        return {"plan": entry["plan"]}, f"plan exists: {entry['plan']}"
    base = stem[:-len("-impl")] if stem.endswith("-impl") else stem
    files = {"revision": ("completion", f"{stem}-completion.md"), "split": ("roadmap", f"{stem}-roadmap.md"),
             "diffs": ("diffs", f"{base}-diffs.md")}
    if stage in files:
        key, name = files[stage]
        rel = _journal_rel(journal, os.path.join(plan_dir, name))
        return ({key: rel}, f"{key} exists: {rel}") if os.path.isfile(os.path.join(plan_dir, name)) else None
    if stage == "audit":
        latest = _latest_report(plan_dir, stem)
        if latest is None:
            return None
        rel, status = _journal_rel(journal, os.path.join(plan_dir, latest[0])), "final" if latest[1] else "open"
        return {"report": rel, "status": status}, f"last report ({status}): {rel}"
    if stage == "execution":
        return _ledger_evidence(journal, entry, warnings)
    if stage == "commit":
        return _commit_evidence(entry, plan_dir)
    return None


def _evidence_is_fresh(journal: str, entry: Dict[str, Any], stage: str, artifacts: Dict[str, Any]) -> bool:
    """A running stage counts its evidence file only when it was written at or after the stage's
    started_at: the report, completion or roadmap of an earlier pass proves nothing."""
    started = entry["stages"][stage].get("started_at")
    if not started:
        return True  # no start time (a hand-written record): nothing to compare with
    directory = os.path.dirname(os.path.abspath(journal))
    if stage == "execution":
        exec_dir = (entry["stages"]["execution"].get("artifacts") or {}).get("exec_dir")
        path = os.path.join(directory, exec_dir, "state.json") if exec_dir else None
    else:
        key = {"revision": "completion", "split": "roadmap", "diffs": "diffs", "audit": "report"}.get(stage)
        path = os.path.join(directory, artifacts[key]) if key in artifacts else None
    if path is None:
        return True  # commit: the evidence is the commits in git, not a file
    try:
        start = datetime.datetime.strptime(started, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
        return os.path.getmtime(path) >= start.timestamp()
    except (OSError, ValueError):
        return False


def _stage_drift(journal: str, data: Dict[str, Any], entry: Dict[str, Any],
                 stage: str) -> Optional[Tuple[str, str, str]]:
    """(plan path, stage, question text) when the input of a done stage changed since input_sha256."""
    stored = entry["stages"][stage].get("input_sha256")
    if not stored or stage in ("diffs", "commit"):
        return None
    directory = os.path.dirname(os.path.abspath(journal))
    plan_path = os.path.join(directory, entry["plan"])
    if stage == "writing":
        inputs = [os.path.join(directory, entry["spec"])] if entry.get("spec") else []
    else:
        inputs = [plan_path]
        if stage == "execution":  # the executor ran either the plan or its roadmap
            inputs.append(os.path.splitext(plan_path)[0] + "-roadmap.md")
    existing = [path for path in inputs if os.path.isfile(path)]
    if not existing or any(_sha256(path) == stored for path in existing):
        return None
    prefix = f"drift: {stage} input changed: "
    text = prefix + ", ".join(f"{_journal_rel(journal, path)} (sha256 {_sha256(path)[:12]})" for path in existing)
    # One question per change: none while one is open, none again for the same input once answered.
    if any(q.get("plan") == entry["id"] and q.get("stage") == stage
           and (q.get("text") == text or (q.get("status") == "open" and str(q.get("text", "")).startswith(prefix)))
           for q in data["questions"]):
        return None
    return plan_path, stage, text


def _reconcile_stage(journal: str, data: Dict[str, Any], entry: Dict[str, Any], stage: str,
                     report: Dict[str, List[Any]]) -> None:
    """pending/running → done when the artifacts show it; done is checked for drift; stopped,
    failed and skipped stay."""
    record = entry["stages"][stage]
    before = record["status"]
    if before == "done":
        drift = _stage_drift(journal, data, entry, stage)
        if drift is not None:
            report["drift"].append(drift)
        return
    if before not in ("pending", "running"):
        return
    if before == "running" and stage == "writing":  # the plan file exists long before it is finished
        report["running"].append({"plan": entry["id"], "stage": stage})
        return
    evidence = _stage_evidence(journal, entry, stage, report["warnings"])
    if evidence is not None and before == "running" and not _evidence_is_fresh(journal, entry, stage, evidence[0]):
        evidence = None
    if evidence is None:
        if before == "running":
            report["running"].append({"plan": entry["id"], "stage": stage})
        return
    artifacts, why = evidence
    record["status"], record["finished_at"] = "done", _iso_now()
    record.setdefault("artifacts", {}).update(artifacts)
    data["events"].append({"at": _iso_now(), "skill": "plan-brainstorming", "plan": entry["id"], "stage": stage,
                           "kind": "reconcile", "data": {"from": before, "to": "done", "why": why}})
    report["changes"].append({"plan": entry["id"], "stage": stage, "from": before, "to": "done", "why": why})


def _rebuild_sources(directory: str, goal: str) -> Tuple[List[str], List[Tuple[str, Optional[str]]]]:
    """Specs of the goal in the journal's directory and the plans whose **Spec:** names one of them
    (no spec of the goal: the plan '<goal>-impl.md' without **Spec:**)."""
    try:
        names = sorted(os.listdir(directory))
    except OSError as exc:
        raise InputError(f"cannot list {directory}: {exc}") from exc
    specs = [os.path.join(directory, name) for name in names if name.endswith("-spec.md")
             and (parse_metadata(_read_source(os.path.join(directory, name)))["backlog"]
                  or name[:-len("-spec.md")]) == goal]
    known = {os.path.normcase(path): path for path in specs}
    plans: List[Tuple[str, Optional[str]]] = []
    for name in (name for name in names if name.endswith("-impl.md")):
        path = os.path.join(directory, name)
        target = parse_plan_header(_read_source(path))["spec"]
        if target is None:
            if not specs and name == f"{goal}-impl.md":
                plans.append((path, None))
        else:
            spec = known.get(os.path.normcase(os.path.normpath(os.path.join(directory, target))))
            if spec is not None:
                plans.append((path, spec))
    return specs, plans


def _rebuild_findings(directory: str, goal: str, plan_id: Optional[str],
                      warnings: List[str]) -> List[Dict[str, Any]]:
    """Findings F1..Fn back from '<goal>-followups.json' (the last export), so that the next export
    does not shrink it; they belong to the first plan of the goal."""
    path = os.path.join(directory, goal + FOLLOWUPS_SUFFIX)
    if not os.path.isfile(path):
        return []
    try:
        found, errors, _ = load_findings(_read_source(path))
    except InputError as exc:
        found, errors = [], [str(exc)]
    errors = [error for error in errors if error != "findings list is empty"]
    if errors or plan_id is None:
        warnings.append(f"findings not restored from {goal}{FOLLOWUPS_SUFFIX}: "
                        + "; ".join(errors or ["no plan of the goal"]))
        return []
    return [{"id": f["id"], "plan": plan_id, "skill": "journal-rebuild", "file": f["file"], "line": f["line"],
             "summary": f["summary"], "failure_scenario": f["failure_scenario"], "recorded_at": _iso_now(),
             "backlog": None} for f in found]


def _journal_rebuild(journal: str) -> Tuple[bool, Optional[str], List[str]]:
    """(rebuilt, backup, warnings): a corrupt journal is renamed to '<journal>.corrupt-<UTC time>'
    and a fresh one is built from the files next to it; a readable journal is left as it is. Valid
    version-1 JSON with structural errors (journal-validate) counts as corrupt too."""
    try:
        # A bad time alone is fixed by hand (plan-chain-runner LOOP.md, Journal errors), not rebuilt.
        if not _journal_structure_errors(journal_load(journal), times=False):
            return False, None, []
    except InputError as exc:
        if not str(exc).startswith(("journal-corrupt", "journal-missing")):
            raise
    # Everything that reads the files comes before the rename: a failure leaves the journal in place.
    directory, name = os.path.dirname(os.path.abspath(journal)), os.path.basename(journal)
    goal = name[:-len(JOURNAL_SUFFIX)] if name.endswith(JOURNAL_SUFFIX) else os.path.splitext(name)[0]
    specs, plans = _rebuild_sources(directory, goal)
    first = specs[0] if specs else (plans[0][0] if plans else None)
    lang = detect_lang_text(_read_source(first)) if first else "en"
    backup = None
    if os.path.exists(journal):
        stamp = datetime.datetime.fromtimestamp(_now(), datetime.timezone.utc).strftime("%Y%m%d%H%M%S")
        backup, number = f"{journal}.corrupt-{stamp}", 1
        while os.path.exists(backup):  # a second rebuild within the same second keeps the first backup
            backup, number = f"{journal}.corrupt-{stamp}-{number}", number + 1
        try:
            os.replace(journal, backup)
        except OSError as exc:
            raise JournalError(f"journal-write-failed: {journal}: {exc}") from exc
    journal_create(journal, goal, lang, specs[0] if specs else None)
    warnings = ["rebuilt journal: questions, events, commits, exec_dir and input_sha256 "
                "cannot be restored from the files"]

    def mutate(data: Dict[str, Any]) -> None:
        for spec in specs[1:]:
            data["specs"].append({"path": _journal_rel(journal, spec), "sha256": _sha256(spec)})
        for plan, spec in plans:
            _plan_entry(data, journal, plan, spec=spec)
        owner = data["plans"][0]["id"] if data["plans"] else None
        data["findings"].extend(_rebuild_findings(directory, goal, owner, warnings))

    journal_update(journal, mutate)
    return True, backup, warnings


def journal_reconcile(journal: str, rebuild: bool = False) -> Dict[str, Any]:
    """Statuses from the artifacts after a crash: never lowers a stage, lists running stages;
    `rebuild` first replaces a corrupt journal with a fresh one."""
    rebuilt, backup, lost = _journal_rebuild(journal) if rebuild else (False, None, [])
    report: Dict[str, List[Any]] = {"changes": [], "running": [], "warnings": list(lost), "drift": []}
    questions: List[str] = []

    def mutate(data: Dict[str, Any]) -> None:
        for entry in data["plans"]:
            for stage in STAGES:
                _reconcile_stage(journal, data, entry, stage, report)
        # Under the same lock as the drift check, so a concurrent reconcile cannot ask it again.
        # A done stage stays done.
        questions.extend(_add_question(data, os.path.abspath(journal), STAGE_OWNERS[stage], plan_path, stage,
                                       text)["id"] for plan_path, stage, text in report["drift"])

    journal_update(journal, mutate)
    return {"ok": True, "changes": report["changes"], "questions": questions, "running": report["running"],
            "warnings": report["warnings"], "rebuilt": rebuilt, "backup": backup}


def cmd_journal_reconcile(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    return 0, journal_reconcile(args.journal, rebuild=args.rebuild)


# Inputs of a brainstorming call (spec plan-refactoring-01-9): every file given is classified, the free
# text is the instruction (`note`). Nothing is written.
MARKDOWN_EXTENSIONS = (".md", ".markdown")
GOAL_NAME_RE = re.compile(r"(?:^|[-_])goal$", re.IGNORECASE)
SINGLE_FILE_MODES = {"spec": "amend", "findings": "findings", "backlog": "backlog",
                     "goal": "idea", "markdown": "idea", "text": "idea"}


def _plan_root(path: str) -> str:
    """<plan-root> of a goal file (spec-contract.md): the name without extension and without a descriptive
    suffix after the last numeric segment: plan02-goal.md → plan02, plan01.md → plan01, goal.md → goal."""
    stem = os.path.splitext(os.path.basename(path))[0]
    match = re.match(r"^(?P<root>.*\d)[-_][^\d]*$", stem)
    return match.group("root") if match else stem


def _findings_count(text: str) -> Optional[int]:
    """Number of findings when `text` is a findings JSON (a list of objects with `file` and `summary`, or
    {"findings": [...]}); None for other JSON; ValueError when it is not JSON."""
    data = json.loads(text)
    items = data.get("findings") if isinstance(data, dict) else data
    if isinstance(items, list) and items and all(isinstance(i, dict) and "file" in i and "summary" in i
                                                  for i in items):
        return len(items)
    return None


def _classify_input(path: str) -> Tuple[Dict[str, Any], bool]:
    """(entry, goal candidate) of one input file; a goal candidate is markdown without spec headings."""
    entry: Dict[str, Any] = {"path": path, "exists": os.path.isfile(path)}
    if not entry["exists"]:
        return dict(entry, kind="missing"), False
    with open(path, "rb") as fh:
        raw = fh.read()
    entry.update(bytes=len(raw), lines=0 if not raw else raw.count(b"\n") + (0 if raw.endswith(b"\n") else 1))
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return dict(entry, kind="binary"), False
    entry["lang"] = detect_lang_text(_text_for_lang(text))
    name = os.path.basename(path)
    lines = [line for _, line in _unfenced_lines(text)]
    markdown = name.lower().endswith(MARKDOWN_EXTENSIONS)
    if name == BACKLOG_FILE:
        return dict(entry, kind="backlog"), False
    if _goal_roadmap_goal(text) is not None:
        return dict(entry, kind="goal-roadmap"), False
    if name.endswith("-spec.md") and "# Goal" in lines:
        return dict(entry, kind="spec"), False
    if name.endswith("-impl.md") and any(PLAN_TASK_HEADING_RE.match(line) for line in lines):
        return dict(entry, kind="plan"), False
    if not markdown and text.lstrip()[:1] in ("[", "{"):
        try:
            count = _findings_count(text)
        except ValueError:
            pass  # not JSON: a text file
        else:
            return (dict(entry, kind="json") if count is None else dict(entry, kind="findings", count=count)), False
    if markdown:
        return dict(entry, kind="markdown"), not any(line in SPEC_HEADINGS for line in lines)
    return dict(entry, kind="text"), False


def inputs_report(paths: List[str], note: Optional[str]) -> Tuple[int, Dict[str, Any]]:
    """`inputs`: kind, language and size of each file, the mode of the call, plan_root and the note.
    The goal is a markdown file without spec headings whose name ends in 'goal', else the first such
    file; the other markdown files are reference material (`markdown`)."""
    if not paths and not (note or "").strip():
        raise InputError("nothing-to-classify: give input files or --note")
    files: List[Dict[str, Any]] = []
    candidates: List[int] = []
    for index, path in enumerate(paths):
        entry, candidate = _classify_input(path)
        files.append(entry)
        if candidate:
            candidates.append(index)
    goals = [i for i in candidates if GOAL_NAME_RE.search(os.path.splitext(os.path.basename(paths[i]))[0])]
    goals = goals or candidates[:1]
    for index in goals:
        files[index]["kind"] = "goal"
    warnings = [f"binary: {entry['path']}" for entry in files if entry["kind"] == "binary"]
    if len(goals) > 1:
        warnings.append(f"several-goals: plan_root from {files[goals[0]]['path']}")
    errors = [f"missing: {entry['path']}" for entry in files if entry["kind"] == "missing"]
    if not files:
        mode = "idea"
    elif len(files) == 1:
        mode = SINGLE_FILE_MODES.get(files[0]["kind"], "multi")
    else:
        mode = "multi"
    langs = [files[i]["lang"] for i in goals] + ([detect_lang_text(note)] if (note or "").strip() else [])
    langs += [entry["lang"] for entry in files if "lang" in entry]
    return (1 if errors else 0), {
        "ok": not errors, "mode": mode, "plan_root": _plan_root(files[goals[0]]["path"]) if goals else None,
        "lang": langs[0] if langs else "en", "note": note, "files": files, "warnings": warnings, "errors": errors}


def cmd_inputs(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    return inputs_report(args.files, args.note)


# Specs of one goal (spec-set-check, roadmap-write): the journal in their directory names them.
SPEC_NUMBER_RE = re.compile(r"-(?P<n>\d+)-spec\.md$")
SPEC_MENTION_RE = re.compile(r"(?<![\w-])(?:спек[аиуеой]{0,2}|specs?)\s+(?P<n>\d+)\b", re.IGNORECASE)
NUMBERED_REF_RE = re.compile(r"`?(?P<path>[\w./-]+\.[A-Za-z0-9]+)`?\s*(?:\(\s*)?"
                             r"(?:§\s*\d+|(?:пункт|шаг|item|step)\s+\d+)", re.IGNORECASE)
CODE_SPAN_RE = re.compile(r"`([^`\n]+)`")
IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _spec_number(name: str) -> Optional[int]:
    """N of '<root>-N-spec.md', else None."""
    match = SPEC_NUMBER_RE.search(name)
    return int(match.group("n")) if match else None


def _dir_rel(directory: str, path: str) -> str:
    """`path` relative to `directory` with forward slashes (absolute on another drive)."""
    try:
        rel = os.path.relpath(os.path.abspath(path), os.path.abspath(directory))
    except ValueError:
        rel = os.path.abspath(path)
    return rel.replace("\\", "/")


def _goal_journal(directory: str, goal: Optional[str] = None) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """(path, data) of the goal's chain journal in `directory`: the only `*-chain.json` there, or
    `<goal>-chain.json` among several; (None, None) without one; several and no goal among them is
    ambiguous-journal (exit 2)."""
    names = sorted(name for name in os.listdir(directory) if name.endswith(JOURNAL_SUFFIX))
    if goal is not None and len(names) > 1 and goal + JOURNAL_SUFFIX in names:
        names = [goal + JOURNAL_SUFFIX]
    if not names:
        return None, None
    if len(names) > 1:
        raise InputError(f"ambiguous-journal: {', '.join(names)} in {directory}")
    path = os.path.join(directory, names[0])
    data = journal_load(path)
    specs = data.get("specs")
    if not (isinstance(specs, list) and all(isinstance(s, dict) and isinstance(s.get("path"), str) for s in specs)):
        raise InputError(f"journal-corrupt: {path}: 'specs' must be a list of {{path, sha256}} objects")
    return path, data


def _set_specs(directory: str, given: Optional[List[str]], warnings: List[str],
               goal: Optional[str] = None) -> Tuple[Optional[str], List[str]]:
    """(journal, spec names relative to `directory`): the journal's specs (`goal` picks `<goal>-chain.json`
    among the journals of several goals); without a journal the `given` files, else every '*-spec.md' in
    `directory` by file number, only '<goal>-*-spec.md' when `goal` is given (warning no-journal)."""
    journal, data = _goal_journal(directory, goal)
    if data is not None:
        if given:
            warnings.append("specs-ignored: the journal lists the goal's specs")
        return journal, [_normalize_path(spec["path"]) for spec in data["specs"]]
    warnings.append("no-journal")
    if given:
        return None, [_dir_rel(directory, path) for path in given]
    names = [name for name in os.listdir(directory)
             if name.endswith("-spec.md") and (goal is None or name.startswith(goal + "-"))]
    return None, sorted(names, key=lambda name: (_spec_number(name) is None, _spec_number(name) or 0, name))


def _components_cells(lines: List[str]) -> Optional[List[str]]:
    """First cells of the rows of the '## Components' table (header and separator left out); None when
    the section has no table. The section ends at the next '#' or '##' heading, whatever its text, and a heading
    is compared without trailing spaces (F16 of plan-refactoring-02): a table under another section is not
    Components; '###' subheadings stay inside it."""
    rows: List[str] = []
    inside = False
    for line in lines:
        stripped = line.rstrip()
        if re.match(r"^#{1,2}\s", stripped):
            inside = stripped == "## Components"
        elif inside and stripped.startswith("|"):
            rows.append(stripped)
    if not rows:
        return None
    cells: List[str] = []
    for index, line in enumerate(rows):
        following = rows[index + 1] if index + 1 < len(rows) else ""
        if not (_is_table_separator(line) or _is_table_separator(following)):
            cells.append(re.split(r"(?<!\\)\|", line.strip().strip("|"))[0])
    return cells


# Names every spec may give without sharing work (F15 of plan-refactoring-02): the shared documents and the
# Components rows of tests and documentation are not touchpoints.
SHARED_DOC_NAMES = ("CLAUDE.md", "README.md", "USAGE.md")
SHARED_DOC_PATH_RE = re.compile(r"^docs/[^/]+\.md$")
SHARED_ROW_RE = re.compile(r"^\s*(?:Тесты|Документация|Tests|Docs)\b", re.IGNORECASE)


def _shared_doc(name: str, kind: str) -> bool:
    """True for a path to CLAUDE.md, README.md or USAGE.md in any folder, or to a .md file right in docs/."""
    return kind == "path" and (name.rsplit("/", 1)[-1] in SHARED_DOC_NAMES or bool(SHARED_DOC_PATH_RE.match(name)))


def _touch_names(cell: str) -> List[Tuple[str, str]]:
    """(name, kind) of the code spans of one Components cell: a path (has '/' or an extension; a ':line'
    suffix is dropped) or a symbol (an identifier). A span with spaces counts by its first word."""
    names: List[Tuple[str, str]] = []
    for span in CODE_SPAN_RE.findall(cell):
        words = span.split()
        token = re.sub(r":\d+(?:-\d+)?$", "", words[0].replace("\\", "/")) if words else ""
        if not token or token.startswith(":"):
            continue
        if "/" in token or re.search(r"\.[A-Za-z0-9]+$", token):
            names.append((_normalize_path(token), "path"))
        elif IDENTIFIER_RE.match(token):
            names.append((token, "symbol"))
    return names


def _spec_mentions(text: str, own: str, names: List[str]) -> List[str]:
    """Other specs of the set that `text` names: 'спека N' / 'spec N' (N = file number) or the file name."""
    numbers: Dict[int, List[str]] = {}
    for name in names:
        if _spec_number(name) is not None:
            numbers.setdefault(_spec_number(name), []).append(name)
    found = {numbers[n][0] for n in (int(m.group("n")) for m in SPEC_MENTION_RE.finditer(text))
             if len(numbers.get(n, ())) == 1}
    found |= {name for name in names
              if re.search(r"(?<![\w.-])" + re.escape(os.path.basename(name)), text)}
    return [name for name in names if name in found and name != own]


def spec_set_check(directory: str, given: Optional[List[str]] = None, goal: Optional[str] = None) -> Dict[str, Any]:
    """`spec-set-check`: paths and symbols that two or more specs of the goal name in their Components
    table, the pairs among them that do not mention each other, files with numbered references from
    two or more specs, and each spec's mentions of the others. `goal` names the goal when the directory
    holds the journals of several goals. Warnings only; nothing is written."""
    if not os.path.isdir(directory):
        raise InputError(f"not a directory: {directory}")
    warnings: List[str] = []
    journal, names = _set_specs(directory, given, warnings, goal)
    result: Dict[str, Any] = {"ok": True, "journal": journal, "specs": names, "touchpoints": [],
                              "undeclared": [], "numbered_items": [], "self_edges": [], "warnings": warnings}
    if len(names) < 2:
        warnings.append("single-spec")
        return result
    touch: Dict[Tuple[str, str], List[str]] = {}
    numbered: Dict[str, List[str]] = {}
    mentions: Dict[str, List[str]] = {}
    for name in names:
        lines = [line for _, line in _unfenced_lines(_read_source(os.path.join(directory, name)))]
        cells = _components_cells(lines)
        if cells is None:
            warnings.append(f"no-components-table: {name}")
        points = (key for cell in cells or [] if not SHARED_ROW_RE.match(cell)
                  for key in _touch_names(cell) if not _shared_doc(*key))
        for key in dict.fromkeys(points):
            touch.setdefault(key, []).append(name)
        text = "\n".join(lines)
        for path in dict.fromkeys(m.group("path") for m in NUMBERED_REF_RE.finditer(text)):
            numbered.setdefault(path, []).append(name)
        mentions[name] = _spec_mentions(text, name, names)

    def declared(a: str, b: str) -> bool:
        return b in mentions[a] or a in mentions[b]

    for (point, kind), specs in touch.items():
        if len(specs) > 1:
            result["touchpoints"].append({"name": point, "kind": kind, "specs": specs})
            if any(not declared(a, b) for i, a in enumerate(specs) for b in specs[i + 1:]):
                result["undeclared"].append({"name": point, "specs": specs})
    result["numbered_items"] = [{"file": path, "specs": specs} for path, specs in numbered.items() if len(specs) > 1]
    result["self_edges"] = [{"spec": name, "mentions": mentions[name]} for name in names if mentions[name]]
    return result


def cmd_spec_set_check(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    return 0, spec_set_check(args.dir, args.specs, args.goal)


# Goal roadmap <goal>-roadmap.md (spec-contract.md, "Goal roadmap"): written by roadmap-write, checked by
# roadmap-check, read by roadmap-parse (plan-chain-runner's input).
ROADMAP_SUFFIX = "-roadmap.md"
ROADMAP_HEADINGS = ("## Overview", "## Order", "## Graph", "## Parallelism", "## Shared touchpoints",
                    "## Specs", "## Sources", "## Notes")
ROADMAP_ORDER_HEADER = ("#", "Spec", "Title", "Depends on", "Group", "Tier", "Estimate")
ROADMAP_SHARED_HEADER = ("File or symbol", "Specs", "Delivery order", "Note")
ROADMAP_LABELS = {
    "ru": {"goal": "Цель", "depends": "Зависит от", "notes": "Примечания", "handoff": "Передаёт",
           "instruction": "Инструкция", "none": "нет", "together": "можно вести одновременно", "alone": "одна спека"},
    "en": {"goal": "Goal", "depends": "Depends on", "notes": "Notes", "handoff": "Hands off",
           "instruction": "Instruction", "none": "none", "together": "may run at the same time", "alone": "one spec"},
}
ROADMAP_GROUP_RE = re.compile(r"^[A-Za-z0-9_]+$")
DASH = "—"


def _graph_text(value: Any, where: str, required: bool = False) -> Optional[str]:
    """A text field of the roadmap JSON, stripped; None when empty; graph-invalid (exit 2) otherwise."""
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise InputError(f"graph-invalid: {where} is required")
        return None
    if not isinstance(value, str):
        raise InputError(f"graph-invalid: {where} must be a string")
    return value.strip()


def _graph_files(value: Any, where: str) -> List[str]:
    """A list of spec files of the roadmap JSON (missing → [])."""
    if value is None:
        return []
    if not (isinstance(value, list) and all(isinstance(item, str) and item.strip() for item in value)):
        raise InputError(f"graph-invalid: {where} must be a list of spec files")
    return [_normalize_path(item) for item in value]


def _graph_items(graph: Dict[str, Any], key: str) -> List[Dict[str, Any]]:
    value = graph.get(key) or []
    if not (isinstance(value, list) and all(isinstance(item, dict) for item in value)):
        raise InputError(f"graph-invalid: {key} must be a list of objects")
    return value


def _roadmap_graph(graph: Any) -> Dict[str, Any]:
    """The roadmap JSON of roadmap-write with its shape checked (graph-invalid, exit 2)."""
    if not isinstance(graph, dict):
        raise InputError("graph-invalid: not a JSON object")
    specs = []
    for index, item in enumerate(_graph_items(graph, "specs")):
        where = f"specs[{index}]"
        group = _graph_text(item.get("group"), where + ".group", True)
        if not ROADMAP_GROUP_RE.match(group):
            raise InputError(f"graph-invalid: {where}.group must be letters, digits or _")
        specs.append({"file": _normalize_path(_graph_text(item.get("file"), where + ".file", True)),
                      "title": _graph_text(item.get("title"), where + ".title", True),
                      "depends": _graph_files(item.get("depends"), where + ".depends"), "group": group,
                      "notes": _graph_text(item.get("notes"), where + ".notes"),
                      "handoff": _graph_text(item.get("handoff"), where + ".handoff")})
    files = [spec["file"] for spec in specs]
    if not files or len(set(files)) != len(files):
        raise InputError("graph-invalid: specs must list each spec once")
    sources = [{"path": _graph_text(item.get("path"), f"sources[{i}].path", True),
                "role": _graph_text(item.get("role"), f"sources[{i}].role", True)}
               for i, item in enumerate(_graph_items(graph, "sources"))]
    shared = [{"name": _graph_text(item.get("name"), f"shared[{i}].name", True),
               "kind": _graph_text(item.get("kind"), f"shared[{i}].kind"),
               "specs": _graph_files(item.get("specs"), f"shared[{i}].specs"),
               "order": _graph_files(item.get("order"), f"shared[{i}].order"),
               "note": _graph_text(item.get("note"), f"shared[{i}].note")}
              for i, item in enumerate(_graph_items(graph, "shared"))]
    lang = graph.get("lang")
    if lang not in (None, "ru", "en"):
        raise InputError("graph-invalid: lang must be ru or en")
    return {"goal": _graph_text(graph.get("goal"), "goal"), "title": _graph_text(graph.get("title"), "title", True),
            "overview": _graph_text(graph.get("overview"), "overview"), "lang": lang,
            "instruction": _graph_text(graph.get("instruction"), "instruction"),
            "notes": _graph_text(graph.get("notes"), "notes"), "specs": specs, "sources": sources, "shared": shared}


def _roadmap_order(specs: List[Dict[str, Any]]) -> Tuple[List[str], List[str]]:
    """(execution order, errors). The order is topological by `depends`: level = 1 + the deepest
    dependency's level, the JSON order inside a level. Errors: unknown-dependency, dependency-cycle,
    group-conflict (a spec in the group of one of its dependencies)."""
    files = [spec["file"] for spec in specs]
    graph = {spec["file"]: spec["depends"] for spec in specs}
    errors = [f"unknown-dependency: {name} -> {dep}" for name, deps in graph.items() for dep in deps if dep not in graph]
    if errors:
        return [], errors
    cycle = _runner_cycle(graph)
    if cycle:
        return [], ["dependency-cycle: " + " -> ".join(cycle)]
    group = {spec["file"]: spec["group"] for spec in specs}
    errors = [f"group-conflict: {name} and its dependency {dep} are both in group {group[name]}"
              for name in files for dep in graph[name] if group[dep] == group[name]]
    level: Dict[str, int] = {}

    def depth(name: str) -> int:
        if name not in level:
            level[name] = 1 + max((depth(dep) for dep in graph[name]), default=-1)
        return level[name]

    return sorted(files, key=lambda name: (depth(name), files.index(name))), errors


def _shared_errors(shared: List[Dict[str, Any]], position: Dict[str, int]) -> List[str]:
    """unknown-shared-spec (a spec outside the roadmap, or an `order` entry outside the point's `specs`)
    and shared-order-conflict (a delivery order against the execution order `#`)."""
    errors: List[str] = []
    for item in shared:
        unknown = [name for name in item["specs"] + item["order"]
                   if name not in position or name not in item["specs"]]
        if unknown:
            errors.append(f"unknown-shared-spec: {item['name']}: {', '.join(dict.fromkeys(unknown))}")
            continue
        ranks = [position[name] for name in item["order"]]
        if ranks != sorted(ranks):
            errors.append(f"shared-order-conflict: {item['name']}: {' → '.join(item['order'])} "
                          f"goes against the execution order")
    return errors


ROADMAP_TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets",
                                "goal-roadmap-template.{lang}.md")


def _spec_refs(files: List[str]) -> Dict[str, str]:
    """How the roadmap names a spec in Depends on, Specs and Delivery order: its file number when no
    other spec of the roadmap has that number, else its file name."""
    numbers = [_spec_number(name) for name in files]
    return {name: str(number) if number is not None and numbers.count(number) == 1 else name
            for name, number in zip(files, numbers)}


def _node_id(ref: str, position: int) -> str:
    """Mermaid node of a spec: s<file number>, or n<#> for a spec named by its file name."""
    return f"s{ref}" if ref.isdigit() else f"n{position}"


def _one_line(text: Optional[str]) -> str:
    return " ".join(text.split()) if text and text.strip() else DASH


def _cell(text: Optional[str]) -> str:
    """A table cell: one line, '|' escaped, '—' when empty."""
    return _one_line(text).replace("|", "\\|")


def _code_span(text: str) -> str:
    """Inline code for `text`: a backtick run longer than any inside it, padded with spaces when it holds one
    (F17 of plan-refactoring-02)."""
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    tick, pad = "`" * (longest + 1), " " if longest else ""
    return f"{tick}{pad}{text}{pad}{tick}"


def _code_span_text(cell: str) -> str:
    """The text of a cell that is one code span (`x`, `` a`b ``); one space is stripped from each side when both
    are there. Any other cell loses only its outer backticks, as before."""
    match = re.fullmatch(r"(`+)(.*?)\1", cell)
    if not match:
        return cell.strip("`")
    text = match.group(2)
    return text[1:-1] if len(text) > 2 and text.startswith(" ") and text.endswith(" ") and text.strip() else text


def _fence(text: str, info: str) -> str:
    """`text` in a code fence one backtick longer than any backtick run inside it (at least three)."""
    ticks = "`" * max(3, max((len(run) for run in re.findall(r"`+", text)), default=0) + 1)
    return f"{ticks}{info}\n{text}\n{ticks}"


def _spec_goal_phrase(text: str) -> str:
    """The first sentence of a spec's '# Goal' section on one line; '?' when the section is empty."""
    body: List[str] = []
    inside = False
    for _, line in _unfenced_lines(text):
        if line in SPEC_HEADINGS:
            if inside:
                break
            inside = line == "# Goal"
        elif inside and line.strip():
            body.append(line.strip())
        elif inside and body:
            break
    paragraph = " ".join(" ".join(body).split())
    return re.split(r"(?<=[.!?])\s", paragraph, maxsplit=1)[0] if paragraph else "?"


def _render_roadmap(lang: str, goal: str, graph: Dict[str, Any], order: List[str],
                    facts: Dict[str, Dict[str, str]]) -> str:
    """The text of <goal>-roadmap.md from assets/goal-roadmap-template.<lang>.md."""
    labels = ROADMAP_LABELS[lang]
    spec = {item["file"]: item for item in graph["specs"]}
    position = {name: index + 1 for index, name in enumerate(order)}
    refs = _spec_refs(order)
    nodes = {name: _node_id(refs[name], position[name]) for name in order}

    def named(files: List[str], joiner: str = ", ") -> str:
        return joiner.join(refs[name] for name in files) or DASH

    rows = ["| " + " | ".join(ROADMAP_ORDER_HEADER) + " |", "|" + "---|" * len(ROADMAP_ORDER_HEADER)]
    rows += ["| " + " | ".join((str(position[name]), _cell(name), _cell(spec[name]["title"]),
                                named(spec[name]["depends"]), spec[name]["group"], _cell(facts[name]["tier"]),
                                _cell(facts[name]["estimate"]))) + " |" for name in order]
    groups: Dict[str, List[str]] = {}
    for name in order:
        groups.setdefault(spec[name]["group"], []).append(name)
    mermaid = ["graph LR"]
    for group, members in groups.items():
        # A group id of its own: `end` is a Mermaid word and `s2` may be a node id (F18 of plan-refactoring-02).
        mermaid += [f'    subgraph g_{group}["{group}"]'] + [
            f'        {nodes[name]}["{position[name]}. {_one_line(spec[name]["title"]).replace(chr(34), "#quot;")}"]'
            for name in members] + ["    end"]
    mermaid += [f"    {nodes[dep]} --> {nodes[name]}" for name in order for dep in spec[name]["depends"]]
    shared = ["| " + " | ".join(ROADMAP_SHARED_HEADER) + " |", "|" + "---|" * len(ROADMAP_SHARED_HEADER)]
    shared += [f"| {_code_span(_cell(item['name']))} | {named(item['specs'])} | {named(item['order'], ' → ')} | "
               f"{_cell(item['note'])} |" for item in graph["shared"]]
    sections = [f"### {position[name]}. {name}\n\n- {labels['goal']}: {facts[name]['goal']}\n"
                f"- {labels['depends']}: {named(spec[name]['depends'])}\n"
                f"- {labels['notes']}: {_one_line(spec[name]['notes'])}\n"
                f"- {labels['handoff']}: {_one_line(spec[name]['handoff'])}" for name in order]
    sources = [f"- `{item['path']}` — {_one_line(item['role'])}" for item in graph["sources"]] or [DASH]
    instruction = graph["instruction"]
    sources += ["", f"{labels['instruction']}:" + (f"\n\n{_fence(instruction, 'text')}" if instruction else f" {DASH}")]
    values = {
        "goal": goal, "count": str(len(order)), "generated": _iso_now(), "title": _one_line(graph["title"]),
        "overview": graph["overview"] or DASH, "order": "\n".join(rows),
        "graph": _fence("\n".join(mermaid), "mermaid"),
        "parallelism": "\n".join(f"- {group}: {named(members)} — "
                                 f"{labels['together'] if len(members) > 1 else labels['alone']}"
                                 for group, members in groups.items()),
        "shared": "\n".join(shared) if graph["shared"] else labels["none"],
        "specs": "\n\n".join(sections), "sources": "\n".join(sources), "notes": graph["notes"] or DASH,
    }
    template = _read_source(ROADMAP_TEMPLATE.format(lang=lang))
    return re.sub(r"\$\{(\w+)\}", lambda match: values[match.group(1)], template)


def _spec_facts(path: str, name: str, warnings: List[str]) -> Dict[str, str]:
    """Tier, estimate (`~N` from spec-check's volume) and the Goal sentence of one spec, with the text.
    A failing spec-check gives '?' (warning spec-check-failed); a result without volume '—' (no-volume)."""
    text = _read_source(path)
    result = check_spec(text)
    facts = {"text": text, "goal": _spec_goal_phrase(text), "tier": result.get("tier") or "?"}
    if not result["ok"]:
        warnings.append(f"spec-check-failed: {name}")
        return dict(facts, tier="?", estimate="?")
    if result.get("volume") is None:
        warnings.append(f"no-volume: {name}")
        return dict(facts, estimate=DASH)
    return dict(facts, estimate=f"~{result['volume']['estimate_tasks']}")


def _is_own_roadmap(path: str) -> bool:
    """True when the existing file is a goal roadmap ('> Goal:' in its first lines)."""
    try:
        return _goal_roadmap_goal(_read_source(path)) is not None
    except InputError:
        return False


def roadmap_write(directory: str, graph_file: str, lang: Optional[str] = None,
                  force: bool = False) -> Tuple[int, Dict[str, Any]]:
    """`roadmap-write`: check the roadmap JSON against the goal's journal and the disk, then write
    <goal>-roadmap.md atomically. Every error comes before the write (exit 1, the file is not touched)."""
    if not os.path.isdir(directory):
        raise InputError(f"not a directory: {directory}")
    try:
        graph = _roadmap_graph(json.loads(_read_source(graph_file)))
    except ValueError as exc:  # InputError is not a ValueError
        raise InputError(f"graph-invalid: {exc}") from exc
    warnings: List[str] = []
    errors: List[str] = []
    journal, data = _goal_journal(directory, graph["goal"])
    listed = [item["file"] for item in graph["specs"]]
    if data is None:
        warnings.append("no-journal")
        if graph["goal"] is None:
            raise InputError("graph-invalid: goal is required when the directory has no journal")
        goal, first = _check_goal(graph["goal"]), listed[0]
    else:
        goal = data["goal"]
        registered = [_normalize_path(item["path"]) for item in data["specs"]]
        first = registered[0] if registered else listed[0]
        if graph["goal"] not in (None, goal):
            errors.append(f"goal-mismatch: the journal's goal is {goal}, the JSON says {graph['goal']}")
        missing = [name for name in registered if name not in listed]
        if missing:
            errors.append("specs-missing: " + ", ".join(missing))
    absent = [name for name in listed if not os.path.isfile(os.path.join(directory, name))]
    if absent:
        errors.append("spec-not-found: " + ", ".join(absent))
    order, order_errors = _roadmap_order(graph["specs"])
    errors += order_errors
    if order:
        errors += _shared_errors(graph["shared"], {name: index + 1 for index, name in enumerate(order)})
    target = os.path.join(directory, goal + ROADMAP_SUFFIX)
    if os.path.exists(target) and not force and not _is_own_roadmap(target):
        errors.append(f"exists-foreign: {target} has no '> Goal:' line; --force overwrites it")
    if errors:
        return 1, {"ok": False, "path": target, "errors": errors, "warnings": warnings}
    facts = {name: _spec_facts(os.path.join(directory, name), name, warnings) for name in order}
    lang = lang or graph["lang"] or detect_lang_text(
        facts[first]["text"] if first in facts else _read_source(os.path.join(directory, first)))
    _atomic_write_text(target, _render_roadmap(lang, goal, graph, order, facts))
    return 0, {"ok": True, "path": target, "goal": goal, "journal": journal, "lang": lang, "order": order,
               "warnings": warnings}


def cmd_roadmap_write(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    return roadmap_write(args.dir, args.graph, args.lang, args.force)


ROADMAP_FENCE_RE = re.compile(r"^(?P<ticks>`{3,}|~{3,})(?P<info>.*)$")
Block = Tuple[Optional[str], List[str]]


def _md_blocks(lines: List[str]) -> List[Block]:
    """(None, [line]) for every line outside code fences and (info, body lines) for every fenced block.
    A fence closes on a line of its character at least as long as the opening run."""
    blocks: List[Block] = []
    fence: Optional[str] = None
    info = ""
    body: List[str] = []
    for line in lines:
        if fence is None:
            match = ROADMAP_FENCE_RE.match(line)
            if match:
                fence, info, body = match.group("ticks"), match.group("info").strip(), []
            else:
                blocks.append((None, [line.rstrip()]))
        elif set(line.strip()) == {fence[0]} and len(line.strip()) >= len(fence):
            blocks.append((info, body))
            fence = None
        else:
            body.append(line)
    if fence is not None:
        blocks.append((info, body))
    return blocks


def _roadmap_sections(text: str) -> Tuple[List[str], List[str], Dict[str, List[Block]]]:
    """(lines before the first '## ' heading, the '## ' headings in order, blocks of each heading)."""
    head: List[str] = []
    names: List[str] = []
    sections: Dict[str, List[Block]] = {}
    current: Optional[str] = None
    for info, body in _md_blocks(text.splitlines()):
        if info is None and body[0].startswith("## "):
            current = body[0]
            names.append(current)
            sections.setdefault(current, [])
        elif current is None:
            head.extend(body if info is None else [])
        else:
            sections[current].append((info, body))
    return head, names, sections


def _section_lines(blocks: List[Block]) -> List[str]:
    return [body[0] for info, body in blocks if info is None]


def _table_rows(blocks: List[Block]) -> List[List[str]]:
    """Cells of the table rows outside fences (separator rows left out, '\\|' unescaped)."""
    rows: List[List[str]] = []
    for line in (line.strip() for line in _section_lines(blocks)):
        if line.startswith("|") and not _is_table_separator(line):
            rows.append([cell.strip().replace("\\|", "|") for cell in re.split(r"(?<!\\)\|", line[1:].rstrip("|"))])
    return rows


def _section_text(blocks: List[Block]) -> Optional[str]:
    text = "\n".join(_section_lines(blocks)).strip()
    return None if text in ("", DASH) else text


def _parse_order(blocks: List[Block], errors: List[str], warnings: List[str]) -> List[Dict[str, Any]]:
    """Rows of the '## Order' table; `depends` stays the raw cell (resolved by _order_graph_errors)."""
    rows = _table_rows(blocks)
    if not rows or tuple(rows[0]) != ROADMAP_ORDER_HEADER:
        errors.append("order-table: the header must be | " + " | ".join(ROADMAP_ORDER_HEADER) + " |")
        return []
    specs: List[Dict[str, Any]] = []
    for cells in rows[1:]:
        if len(cells) != len(ROADMAP_ORDER_HEADER):
            errors.append("order-row: " + " | ".join(cells))
            continue
        number, name, title, depends, group, tier, estimate = cells
        match = re.fullmatch(r"~(\d+)", estimate)
        if not match and estimate not in (DASH, "?"):
            warnings.append(f"no-estimate: {name}")
        specs.append({"n": int(number) if re.fullmatch(r"[0-9]+", number) else None, "file": name, "title": title,
                      "depends": depends, "group": group, "tier": None if tier in ("", DASH, "?") else tier,
                      "estimate": int(match.group(1)) if match else None, "notes": None, "handoff": None})
    if not specs:
        errors.append("order-table: no specs")
    elif [spec["n"] for spec in specs] != list(range(1, len(specs) + 1)):
        errors.append("order-numbering: # must run 1, 2, … in table order")
    return specs


def _order_graph_errors(specs: List[Dict[str, Any]], blocks: List[Block]) -> List[str]:
    """Resolves `depends` to files and checks the table's graph (unknown-dependency, dependency-cycle,
    order-violation, group-conflict) and the Mermaid block of '## Graph' against it."""
    files = [spec["file"] for spec in specs]
    position = {name: index + 1 for index, name in enumerate(files)}
    refs = _spec_refs(files)
    by_ref = {ref: name for name, ref in refs.items()}
    errors: List[str] = []
    for spec in specs:
        tokens = [] if spec["depends"] in ("", DASH) else [token.strip() for token in spec["depends"].split(",")]
        errors += [f"unknown-dependency: {spec['file']} -> {token}" for token in tokens if token not in by_ref]
        spec["depends"] = [by_ref[token] for token in tokens if token in by_ref]
    graph = {spec["file"]: spec["depends"] for spec in specs}
    group = {spec["file"]: spec["group"] for spec in specs}
    cycle = _runner_cycle(graph)
    if cycle:
        errors.append("dependency-cycle: " + " -> ".join(cycle))
    else:
        errors += [f"order-violation: {name} (#{position[name]}) depends on {dep} (#{position[dep]})"
                   for name in files for dep in graph[name] if position[dep] > position[name]]
    errors += [f"group-conflict: {name} and its dependency {dep} are both in group {group[name]}"
               for name in files for dep in graph[name] if group[dep] == group[name]]
    mermaid = next((body for info, body in blocks if info == "mermaid"), None)
    if mermaid is None:
        return errors + ["graph-missing: no mermaid block in ## Graph"]
    if not mermaid or mermaid[0].strip() != "graph LR":
        errors.append("graph-not-lr: the mermaid block must start with 'graph LR'")
    nodes = {name: _node_id(refs[name], position[name]) for name in files}
    defined = {m.group(1) for m in (re.match(r'^\s*([A-Za-z]\w*)\["', line) for line in mermaid) if m}
    edges = {(m.group(1), m.group(2)) for m in
             (re.match(r"^\s*([A-Za-z]\w*)\s*-->\s*([A-Za-z]\w*)\s*$", line) for line in mermaid) if m}
    expected = {(nodes[dep], nodes[name]) for name in files for dep in graph[name]}
    errors += [f"graph-node-missing: {nodes[name]} ({name})" for name in files if nodes[name] not in defined]
    errors += [f"graph-node-unknown: {node}" for node in sorted(defined - set(nodes.values()))]
    errors += [f"graph-edge-without-row: {a} --> {b}" for a, b in sorted(edges - expected)]
    errors += [f"row-edge-missing-in-graph: {a} --> {b}" for a, b in sorted(expected - edges)]
    return errors


def _parse_shared(blocks: List[Block], files: List[str], errors: List[str]) -> List[Dict[str, Any]]:
    """Rows of the '## Shared touchpoints' table ([] for the one-line 'none'), checked by _shared_errors."""
    rows = _table_rows(blocks)
    if not rows:
        return []
    if tuple(rows[0]) != ROADMAP_SHARED_HEADER:
        errors.append("shared-table: the header must be | " + " | ".join(ROADMAP_SHARED_HEADER) + " |")
        return []
    by_ref = {ref: name for name, ref in _spec_refs(files).items()}
    shared: List[Dict[str, Any]] = []
    for cells in rows[1:]:
        if len(cells) != len(ROADMAP_SHARED_HEADER):
            errors.append("shared-row: " + " | ".join(cells))
            continue
        name = _code_span_text(cells[0])
        specs = [] if cells[1] == DASH else [by_ref.get(token.strip(), token.strip()) for token in cells[1].split(",")]
        order = [] if cells[2] == DASH else [by_ref.get(token.strip(), token.strip()) for token in cells[2].split("→")]
        kind = "path" if "/" in name or re.search(r"\.[A-Za-z0-9]+$", name) else "symbol"
        shared.append({"name": name, "kind": kind, "specs": specs, "order": order,
                       "note": None if cells[3] == DASH else cells[3]})
    errors += _shared_errors(shared, {name: index + 1 for index, name in enumerate(files)})
    return shared


def _parse_spec_sections(blocks: List[Block], specs: List[Dict[str, Any]], errors: List[str]) -> None:
    """Notes and handoff of each spec from its '### <#>. <file>' section (labels of either language)."""
    keys = {labels[key]: key for labels in ROADMAP_LABELS.values() for key in ("goal", "depends", "notes", "handoff")}
    found: Dict[str, Dict[str, str]] = {}
    current: Optional[str] = None
    for line in _section_lines(blocks):
        heading = re.match(r"^###\s+\d+\.\s+(\S.*?)\s*$", line)
        item = re.match(r"^-\s+([^:]+):\s*(.*?)\s*$", line)
        if heading:
            current = heading.group(1)
            found[current] = {}
        elif current is not None and item and item.group(1) in keys:
            found[current][keys[item.group(1)]] = item.group(2)
    for spec in specs:
        if spec["file"] not in found:
            errors.append(f"spec-section-missing: {spec['file']}")
            continue
        for key in ("notes", "handoff"):
            value = found[spec["file"]].get(key, DASH)
            spec[key] = None if value in ("", DASH) else value


def _parse_sources(blocks: List[Block]) -> Tuple[List[Dict[str, str]], Optional[str]]:
    """Input files with their roles and the verbatim instruction (the fenced block after its label)."""
    labels = {labels["instruction"] for labels in ROADMAP_LABELS.values()}
    sources: List[Dict[str, str]] = []
    instruction: Optional[str] = None
    waiting = False
    for info, body in blocks:
        if info is not None:
            if waiting:
                instruction, waiting = "\n".join(body), False
            continue
        line = body[0].strip()
        source = re.match(r"^-\s+`([^`]+)`\s+—\s+(.*)$", line)
        label, _, rest = line.partition(":")
        if source:
            sources.append({"path": source.group(1), "role": source.group(2)})
        elif label in labels:
            waiting = rest.strip() != DASH
    return sources, instruction


def parse_goal_roadmap(text: str) -> Tuple[Dict[str, Any], List[str], List[str]]:
    """(parsed roadmap, errors, warnings) of a goal roadmap's text: header, sections, the Order table and
    its graph, the Mermaid block, shared touchpoints, spec sections and sources. No file is read."""
    errors: List[str] = []
    warnings: List[str] = []
    head, names, sections = _roadmap_sections(text)
    goal = _goal_roadmap_goal(text)
    if goal is None:
        errors.append("no-goal-line: '> Goal: <goal>' is not among the first ten lines")
    count = next((int(m.group(1)) for m in (re.match(r"^>\s*Specs:\s*(\d+)\s*$", line) for line in head) if m), None)
    if not any(re.match(r"^>\s*Generated:\s*\S", line) for line in head):
        errors.append("no-generated-line: '> Generated: <ISO-8601 UTC>' is missing")
    title = next((line[len("# Roadmap:"):].strip() for line in head if line.startswith("# Roadmap:")), "")
    if not title:
        errors.append("no-title: '# Roadmap: <title>' is missing")
    missing = [heading for heading in ROADMAP_HEADINGS if heading not in names]
    if missing:
        errors.append("missing-section: " + ", ".join(missing))
    known = [name for name in names if name in ROADMAP_HEADINGS]
    if known != sorted(set(known), key=ROADMAP_HEADINGS.index):
        errors.append("sections-out-of-order: " + " > ".join(known))
    warnings += [f"extra-section: {name}" for name in names if name not in ROADMAP_HEADINGS]
    specs = _parse_order(sections.get("## Order", []), errors, warnings)
    if count != len(specs):
        errors.append(f"specs-count: '> Specs:' says {count}, the Order table has {len(specs)} rows")
    if specs:
        errors += _order_graph_errors(specs, sections.get("## Graph", []))
        _parse_spec_sections(sections.get("## Specs", []), specs, errors)
    files = [spec["file"] for spec in specs]
    groups: Dict[str, List[str]] = {}
    for spec in specs:
        groups.setdefault(spec["group"], []).append(spec["file"])
    sources, instruction = _parse_sources(sections.get("## Sources", []))
    parsed = {"goal": goal, "title": title, "specs": specs, "groups": groups,
              "shared": _parse_shared(sections.get("## Shared touchpoints", []), files, errors),
              "sources": sources, "instruction": instruction,
              "overview": _section_text(sections.get("## Overview", [])),
              "notes": _section_text(sections.get("## Notes", []))}
    return parsed, errors, warnings


def roadmap_check(path: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """(check result, parsed roadmap): parse_goal_roadmap plus spec-not-found for a spec file missing
    next to the roadmap."""
    parsed, errors, warnings = parse_goal_roadmap(_read_source(path))
    directory = os.path.dirname(os.path.abspath(path))
    errors += [f"spec-not-found: {spec['file']}" for spec in parsed["specs"]
               if not os.path.isfile(os.path.join(directory, spec["file"]))]
    return {"ok": not errors, "valid": not errors, "path": path, "errors": errors, "warnings": warnings}, parsed


def cmd_roadmap_check(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    result, _ = roadmap_check(args.file)
    return (0 if result["valid"] else 1), result


def cmd_roadmap_parse(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    result, parsed = roadmap_check(args.file)
    if not result["valid"]:
        return 1, {"ok": False, "errors": result["errors"], "warnings": result["warnings"]}
    return 0, dict(ok=True, **parsed, warnings=result["warnings"])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command")

    p_spec = sub.add_parser("spec-check", help="check a spec against the spec contract")
    p_spec.add_argument("spec", help="path to the written spec")
    p_spec.set_defaults(func=cmd_spec_check)

    p_lang = sub.add_parser("detect-lang", help="dialogue language of a goal file or findings JSON")
    p_lang.add_argument("path", help="goal file or findings JSON, or - for stdin")
    p_lang.set_defaults(func=cmd_detect_lang)

    p_parse = sub.add_parser("findings-parse", help="validate findings and assign ids")
    p_parse.add_argument("findings", help="path to findings JSON, or - for stdin")
    p_parse.add_argument("--root", help="workspace root for file/line existence checks")
    p_parse.set_defaults(func=cmd_parse)

    p_cov = sub.add_parser("findings-coverage", help="check that a spec mentions every finding id")
    p_cov.add_argument("findings", help="path to findings JSON, or - for stdin")
    p_cov.add_argument("spec", help="path to the written spec")
    p_cov.set_defaults(func=cmd_coverage)

    p_bl_add = sub.add_parser("backlog-append", help="append one line to <root>/BACKLOG.md")
    p_bl_add.add_argument("root", help="git top-level of the plan's directory, else the working directory")
    p_bl_add.add_argument("--section", required=True, help="goal section: settings backlog, else plan name without -impl")
    p_bl_add.add_argument("--source", required=True, help='"<skill>, <artifact>"')
    p_bl_add.add_argument("--item", required=True, help="one line: what to do")
    p_bl_add.add_argument("--lang", choices=("ru", "en"), default="en", help="user-section heading language for a new file")
    p_bl_add.add_argument("--plain", action="store_true", help="line without a checkbox (spec map)")
    p_bl_add.add_argument("--date", help="YYYY-MM-DD, default today")
    p_bl_add.set_defaults(func=cmd_backlog_append)

    p_bl_parse = sub.add_parser("backlog-parse", help="list BACKLOG.md items (unchecked by default)")
    p_bl_parse.add_argument("file", help="path to BACKLOG.md")
    p_bl_parse.add_argument("--section", help="only this section")
    p_bl_parse.add_argument("--state", default="open", help="open (default), done, cancelled or all")
    p_bl_parse.set_defaults(func=cmd_backlog_parse)
    p_bl_mark = sub.add_parser("backlog-mark", help="check off one item of an approved spec in <root>/BACKLOG.md")
    p_bl_mark.add_argument("root", help="git top-level of the spec's directory, else the working directory")
    p_bl_mark.add_argument("--section", required=True, help="goal section that holds the item")
    p_bl_mark.add_argument("--item", required=True, help="item text as backlog-parse gives it (without ' — source, date')")
    p_bl_mark.set_defaults(func=cmd_backlog_mark)
    p_bl_unmark = sub.add_parser("backlog-unmark", help="uncheck one item an amended or withdrawn spec no longer covers")
    p_bl_unmark.add_argument("root", help="git top-level of the spec's directory, else the working directory")
    p_bl_unmark.add_argument("--section", required=True, help="goal section that holds the item")
    p_bl_unmark.add_argument("--item", required=True, help="item text as backlog-parse gives it (without ' — source, date')")
    p_bl_unmark.set_defaults(func=cmd_backlog_unmark)
    p_bl_sweep = sub.add_parser("backlog-sweep", help="read-only: open items of a section and the specs of its chain journal")
    p_bl_sweep.add_argument("root", help="git top-level of the spec's directory, else the working directory")
    p_bl_sweep.add_argument("--section", required=True, help="goal section of BACKLOG.md")
    p_bl_sweep.add_argument("--journal", help="the section's chain journal, when the search finds several")
    p_bl_sweep.set_defaults(func=cmd_backlog_sweep)
    p_plan_tasks = sub.add_parser("plan-tasks", help="tasks of a plan by the plan format contract (shared task parser)")
    p_plan_tasks.add_argument("plan", help="plan or part file")
    p_plan_tasks.set_defaults(func=cmd_plan_tasks)
    p_settings = sub.add_parser("settings", help="chain settings, environments and backlog by the single reading rule")
    p_settings.add_argument("file", help="spec, plan, roadmap or part file")
    p_settings.set_defaults(func=cmd_settings)
    p_inputs = sub.add_parser("inputs", help="classify the input files of a brainstorming call")
    p_inputs.add_argument("files", nargs="*", help="input files (goal, research, findings JSON, BACKLOG.md, spec, …)")
    p_inputs.add_argument("--note", help="the free text of the call: how to use the files")
    p_inputs.set_defaults(func=cmd_inputs)
    p_set = sub.add_parser("spec-set-check", help="shared files and symbols of a goal's specs, undeclared pairs")
    p_set.add_argument("dir", help="directory of the goal's specs and journal")
    p_set.add_argument("--goal", help="the goal, when the directory holds the journals of several goals")
    p_set.add_argument("--specs", nargs="+", help="spec files, used only when the directory has no journal")
    p_set.set_defaults(func=cmd_spec_set_check)
    p_rw = sub.add_parser("roadmap-write", help="write <goal>-roadmap.md from the roadmap JSON")
    p_rw.add_argument("dir", help="directory of the goal's specs and journal")
    p_rw.add_argument("--graph", required=True, help="roadmap JSON file (in the OS temp folder)")
    p_rw.add_argument("--lang", choices=("ru", "en"), help="template language, default: the first spec's")
    p_rw.add_argument("--force", action="store_true", help="overwrite a file of that name without '> Goal:'")
    p_rw.set_defaults(func=cmd_roadmap_write)
    p_rc = sub.add_parser("roadmap-check", help="validate a goal roadmap <goal>-roadmap.md")
    p_rc.add_argument("file", help="the goal roadmap")
    p_rc.set_defaults(func=cmd_roadmap_check)
    p_rp = sub.add_parser("roadmap-parse", help="a valid goal roadmap as JSON (plan-chain-runner's input)")
    p_rp.add_argument("file", help="the goal roadmap")
    p_rp.set_defaults(func=cmd_roadmap_parse)

    p_j_path = sub.add_parser("journal-path", help="chain journal of a spec, plan, roadmap or part")
    p_j_path.add_argument("file", help="spec, plan, roadmap or part file")
    p_j_path.add_argument("--create", action="store_true",
                          help="create the journal and register the spec and the plan when missing")
    p_j_path.set_defaults(func=cmd_journal_path)

    p_j_event = sub.add_parser("journal-event", help="checked stage transition of a plan in the chain journal")
    p_j_event.add_argument("journal", help="path to <goal>-chain.json")
    p_j_event.add_argument("--skill", required=True, help="skill that owns the stage")
    p_j_event.add_argument("--plan", required=True, help="plan file (relative to CWD) or an existing plan id")
    p_j_event.add_argument("--stage", required=True, help=", ".join(STAGES))
    p_j_event.add_argument("--status", required=True, help=", ".join(STAGE_STATUSES))
    p_j_event.add_argument("--reason", help="re-entry reason for done → running: " + ", ".join(REENTRY_REASONS))
    p_j_event.add_argument("--input", help="stage input file: its sha256 is stored on done")
    p_j_event.add_argument("--artifact", action="append", default=[], help="key=value or key[]=value (repeatable)")
    p_j_event.add_argument("--data", help="JSON object added to the event")
    p_j_event.add_argument("--spec", help="spec of the plan: binds a new entry, or one without a spec, to it; a different spec is journal-plan-unknown")
    p_j_event.set_defaults(func=cmd_journal_event)

    p_j_unit = sub.add_parser("journal-unit", help="unit event of plan-executor in the chain journal")
    p_j_unit.add_argument("journal", help="path to <goal>-chain.json")
    p_j_unit.add_argument("--plan", required=True, help="plan file (relative to CWD) or an existing plan id")
    p_j_unit.add_argument("--kind", required=True, help="unit-begin or unit-finish")
    p_j_unit.add_argument("--data", required=True, help='JSON object, e.g. {"unit": "a-3", "done": 12, "total": 40}')
    p_j_unit.set_defaults(func=cmd_journal_unit)

    p_j_question = sub.add_parser("journal-question", help="record a question Qn in the chain journal")
    p_j_question.add_argument("journal", help="path to <goal>-chain.json")
    p_j_question.add_argument("--skill", required=True, help="skill that asks")
    p_j_question.add_argument("--plan", required=True, help="plan file (relative to CWD) or an existing plan id")
    p_j_question.add_argument("--stage", required=True, help=", ".join(STAGES))
    p_j_question.add_argument("--text", required=True, help="the question in the dialogue language")
    p_j_question.add_argument("--option", action="append", default=[], help="answer option (repeatable)")
    p_j_question.add_argument("--answer", help="the user's answer (interactive mode): the stage keeps its status")
    p_j_question.add_argument("--spec", help="spec of the plan: binds a new entry, or one without a spec, to it")
    p_j_question.set_defaults(func=cmd_journal_question)

    p_j_answer = sub.add_parser("journal-answer", help="answer a journal question or mark it applied")
    p_j_answer.add_argument("journal", help="path to <goal>-chain.json")
    p_j_answer.add_argument("qid", help="question id Qn")
    j_answer_mode = p_j_answer.add_mutually_exclusive_group(required=True)
    j_answer_mode.add_argument("--answer", help="the user's answer")
    j_answer_mode.add_argument("--applied", action="store_true", help="the owner skill applied the answer")
    p_j_answer.set_defaults(func=cmd_journal_answer)

    p_j_finding = sub.add_parser("journal-finding", help="record an out-of-plan finding Fn in the chain journal")
    p_j_finding.add_argument("journal", help="path to <goal>-chain.json")
    p_j_finding.add_argument("--skill", required=True, help="skill that found it")
    p_j_finding.add_argument("--plan", required=True, help="plan file (relative to CWD) or an existing plan id")
    p_j_finding.add_argument("--file", required=True, help="file of the defect")
    p_j_finding.add_argument("--line", type=int, help="line of the defect")
    p_j_finding.add_argument("--summary", required=True, help="what is wrong")
    p_j_finding.add_argument("--failure-scenario", required=True, help="how it fails")
    p_j_finding.add_argument("--backlog-root", help="also append it to <root>/BACKLOG.md (goal section)")
    p_j_finding.set_defaults(func=cmd_journal_finding)

    p_j_commit = sub.add_parser("journal-commit", help="record a commit-run commit in the chain journal")
    p_j_commit.add_argument("journal", help="path to <goal>-chain.json")
    p_j_commit.add_argument("--plan", required=True, help="plan file (relative to CWD) or an existing plan id")
    p_j_commit.add_argument("--sha", required=True, help="commit sha")
    p_j_commit.add_argument("--subject", required=True, help="commit subject")
    p_j_commit.add_argument("--file", action="append", default=[], help="committed file (repeatable)")
    p_j_commit.set_defaults(func=cmd_journal_commit)

    p_j_export = sub.add_parser("journal-export-findings", help="write <goal>-followups.json from the chain journal")
    p_j_export.add_argument("journal", help="path to <goal>-chain.json")
    p_j_export.set_defaults(func=cmd_journal_export_findings)
    p_j_show = sub.add_parser("journal-show", help="stage of each plan, open questions and the next action")
    p_j_show.add_argument("journal", help="path to <goal>-chain.json")
    p_j_show.add_argument("--plan", help="plan file or plan id: show only this plan")
    p_j_show.set_defaults(func=cmd_journal_show)
    p_j_validate = sub.add_parser("journal-validate", help="journal structure, ids and the replay of stage events")
    p_j_validate.add_argument("journal", help="path to <goal>-chain.json")
    p_j_validate.set_defaults(func=cmd_journal_validate)
    p_j_reconcile = sub.add_parser("journal-reconcile", help="stage statuses from the artifacts, drift questions")
    p_j_reconcile.add_argument("journal", help="path to <goal>-chain.json")
    p_j_reconcile.add_argument("--rebuild", action="store_true",
                               help="a corrupt journal is renamed to <journal>.corrupt-<time> and built anew")
    p_j_reconcile.set_defaults(func=cmd_journal_reconcile)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    # Findings are often non-ASCII; don't depend on the console code page.
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
    except BacklogError as exc:
        code, result = 1, {"ok": False, "errors": [str(exc)]}
    except JournalError as exc:
        code, result = 1, {"ok": False, "errors": [str(exc)]}
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        # A journal that is valid JSON of version 1 but misses keys or has wrong types.
        if getattr(args, "journal", None) is None:
            raise
        code, result = 2, {"ok": False, "errors": [f"journal-corrupt: {args.journal}: "
                                                    f"{exc.__class__.__name__}: {exc}"]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
