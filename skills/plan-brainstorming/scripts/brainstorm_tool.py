#!/usr/bin/env python3
"""Deterministic helper for the plan-brainstorming skill.

- spec-check: verifies a written spec against references/spec-contract.md
  (8 headings in order, non-empty sections, empty Open Questions, Tier line).
- findings-parse: validates a JSON list of code-review findings, assigns
  stable ids (F1..Fn in input order), optionally checks file/line locations.
- findings-coverage: verifies that a spec mentions every finding id.
- settings: chain settings, environments and backlog of a spec, plan, roadmap
  or part by the single reading rule (spec; plan header only for old specs).
- detect-lang: dialogue language of a goal file or findings JSON
  (`ru` when more than 5% of the letters are Cyrillic, otherwise `en`).
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
  detect-lang       <file|->
  backlog-append    <root> --section S --source "skill, artifact" --item TEXT [--lang ru|en] [--plain] [--date D]
  backlog-parse     <BACKLOG.md> [--section S]
  backlog-mark      <root> --section S --item TEXT
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
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple


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
PLACEHOLDER_RE = re.compile(r"\b(TBD|TODO|FIXME)\b")
NONE_TEXT = "(none)"
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
PLAN_TASK_RE = re.compile(r"^#{2,4}\s+(?:Task|Задача)\b")
PLAN_FIELD_RE = re.compile(r"^\*\*(?P<name>Spec|Tier|Chain|Backlog):\*\*\s*(?P<value>.*?)\s*$")
PLAN_ENVIRONMENTS_RE = re.compile(r"^\*\*Environments:\*\*\s*$")
PLAN_ENV_ITEM_RE = re.compile(r"^\s*[-*]\s+`")
# Roadmap and part files point to the master plan in one of their first lines. Plain and bold
# forms as for the Tier line; a target with spaces is written in angle brackets: [x](<a b/p.md>).
SOURCE_RE = re.compile(
    r"^>\s*(?:\*\*)?(?:Source|Источник)(?::\*\*|\*\*:|:)\s*\[[^\]]*\]"
    r"\((?P<open><)?(?P<target>(?(open)[^<>\n]+|[^<>)\s]+))(?(open)>)\)"
)


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


def _unfenced_lines(text: str) -> List[Tuple[int, str]]:
    """(line number, right-stripped line) for every line outside code fences."""
    lines: List[Tuple[int, str]] = []
    in_fence = False
    for number, raw in enumerate(text.splitlines(), start=1):
        if FENCE_RE.match(raw):
            in_fence = not in_fence
        elif not in_fence:
            lines.append((number, raw.rstrip()))
    return lines


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


def parse_plan_header(text: str) -> Dict[str, Any]:
    """Settings in a plan header (lines before the first task heading): written only for old specs."""
    result: Dict[str, Any] = {"spec": None, "tier": None, "chain": None, "environments": [],
                              "backlog": None, "errors": [], "warnings": []}
    in_env_block = False
    for number, line in _unfenced_lines(text):
        if PLAN_TASK_RE.match(line):
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


def check_spec(text: str) -> Dict[str, Any]:
    """Check spec text against the spec contract. Code fences are ignored."""
    errors: List[str] = []
    warnings: List[str] = []
    tier: Optional[str] = None
    positions: Dict[str, List[int]] = {}
    lines: List[Tuple[int, str]] = []
    in_fence = False

    for number, raw in enumerate(text.splitlines(), start=1):
        if FENCE_RE.match(raw):
            in_fence = not in_fence
            continue
        if in_fence:
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
    return {
        "ok": not errors,
        "tier": tier,
        "lang": lang,
        "chain": metadata["chain"],
        "environments": metadata["environments"],
        "backlog": metadata["backlog"],
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


def cmd_settings(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    result = resolve_settings(args.file)
    if any(error.startswith("settings-source-missing: ") for error in result["errors"]):
        return 2, result
    return (0 if result["ok"] else 1), result


BACKLOG_FILE = "BACKLOG.md"
BACKLOG_USER_SECTION = {"en": "My notes", "ru": "Свои заметки"}
BACKLOG_HEADING_RE = re.compile(r"^#{1,2} ")
BACKLOG_ITEM_RE = re.compile(r"^- \[(?P<mark>[ xX])\] (?P<body>.+?)\s*$")
BACKLOG_TAIL_RE = re.compile(r"^(?P<source>.+), (?P<date>\d{4}-\d{2}-\d{2})$")
BACKLOG_DATE_SUFFIX_RE = re.compile(r", \d{4}-\d{2}-\d{2}$")


def _is_user_section(name: str) -> bool:
    """`My notes` / `Свои заметки` in any letter case: the user's section, never written by skills."""
    return name.strip().casefold() in {value.casefold() for value in BACKLOG_USER_SECTION.values()}


def _backlog_lines(text: str) -> List[str]:
    """Split on "\\n" only, keeping the endings: offsets stay exact for any content."""
    return re.findall(r"[^\n]*\n|[^\n]+$", text)


def _backlog_key(line: str) -> Optional[str]:
    """Identity of a backlog line: checkbox and date are ignored, item and source count."""
    line = line.rstrip()
    match = BACKLOG_ITEM_RE.match(line)
    if match:
        return "[] " + BACKLOG_DATE_SUFFIX_RE.sub("", match.group("body"))
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


def backlog_mark(root: str, section: str, item: str) -> Dict[str, Any]:
    """Check off `- [ ] <item>` of `## <section>` in `<root>/BACKLOG.md`: the item entered an approved
    spec. Only the checkbox byte changes. marked / already; not-found and ambiguous write nothing."""
    if not os.path.isdir(root):
        raise InputError(f"root is not a directory: {root}")
    section = _backlog_field("section", section)
    item = _backlog_field("item", item)
    if _is_user_section(section):
        raise BacklogError(f"user-section: section '{section}' belongs to the user; skills never write there")
    path = os.path.abspath(os.path.join(root, BACKLOG_FILE))
    result: Dict[str, Any] = {"ok": True, "path": path, "section": section, "item": item}
    missing = dict(result, ok=False, action="not-found", errors=[f"not-found: '{item}' in '## {section}'"])
    try:
        with open(path, "rb") as fh:
            old = fh.read()
    except FileNotFoundError:
        return missing
    except OSError as exc:
        raise InputError(f"cannot read {path}: {exc}") from exc
    try:
        text = old.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BacklogError(f"{path} is not UTF-8, file not written: {exc}") from exc
    lines = _backlog_lines(text)
    unchecked, checked = _backlog_mark_lines(lines, section, item)
    if len(unchecked) > 1:
        return dict(result, ok=False, action="ambiguous", lines=[index + 1 for index in unchecked],
                    errors=[f"ambiguous: {len(unchecked)} unchecked lines of '## {section}' read '{item}'"])
    if not unchecked:
        return dict(result, action="already", line=checked[0] + 1) if checked else missing
    index = unchecked[0]
    offset = sum(len(line) for line in lines[:index]) + len(lines[index]) - len(lines[index].lstrip("﻿")) + 3
    new_text = text[:offset] + "x" + text[offset + 1:]
    new = new_text.encode("utf-8")
    if text[offset] != " " or len(new) != len(old) or sum(a != b for a, b in zip(old, new)) != 1:
        raise BacklogError(f"{path}: more than the checkbox would change, file not written")
    try:
        _atomic_write_text(path, new_text)
    except OSError as exc:
        raise BacklogError(f"{path}: write failed, file left unchanged: {exc}") from exc
    with open(path, "rb") as fh:
        if fh.read() != new:
            raise BacklogError(f"{path}: content after write differs from the expected bytes")
    return dict(result, action="marked", line=index + 1)


def _backlog_item_text(body: str) -> Tuple[str, Optional[str], Optional[str]]:
    """(text, source, date) of an item body: " — <source>, <YYYY-MM-DD>" at the end is split off."""
    if " — " in body:
        head, tail = body.rsplit(" — ", 1)
        found = BACKLOG_TAIL_RE.match(tail)
        if found:
            return head, found.group("source"), found.group("date")
    return body, None, None


def _backlog_mark_lines(lines: List[str], section: str, item: str) -> Tuple[List[int], List[int]]:
    """Indexes of the item lines of `## <section>`, outside code fences, whose text (as backlog-parse
    gives it) is `item`: (unchecked, checked)."""
    headings, fenced = _backlog_scan(lines)
    unchecked: List[int] = []
    checked: List[int] = []
    current: Optional[str] = None
    for index, (line, heading, in_fence) in enumerate(zip(lines, headings, fenced)):
        if heading is not None:
            current = heading
            continue
        if in_fence or current != f"## {section}":
            continue
        match = BACKLOG_ITEM_RE.match(line.lstrip("﻿").rstrip())
        if match and _backlog_item_text(match.group("body"))[0] == item:
            (unchecked if match.group("mark") == " " else checked).append(index)
    return unchecked, checked


def backlog_parse(path: str, section: Optional[str] = None) -> Dict[str, Any]:
    """Unchecked `- [ ]` items of BACKLOG.md, optionally of one section."""
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
        line = raw.lstrip("﻿").rstrip()
        match = BACKLOG_ITEM_RE.match(line)
        if not match or match.group("mark") != " ":
            continue
        if section is not None and current != section:
            continue
        text, source, day = _backlog_item_text(match.group("body"))
        items.append({"section": current, "text": text, "source": source, "date": day, "line": number})
    return {"ok": True, "items": items}


def cmd_backlog_append(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    result = backlog_append(args.root, args.section, args.source, args.item,
                            lang=args.lang, plain=args.plain, date=args.date)
    return 0, result


def cmd_backlog_parse(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    return 0, backlog_parse(args.file, args.section)


def cmd_backlog_mark(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    result = backlog_mark(args.root, args.section, args.item)
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


def journal_path_for(path: str) -> Dict[str, Any]:
    """Journal of a spec, plan, roadmap or part: roadmap/part → master plan → spec at **Spec:**."""
    current = os.path.abspath(path)
    text = _read_source(current)
    source = next((m.group("target") for m in map(SOURCE_RE.match, text.splitlines()[:10]) if m), None)
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
            "exists": os.path.isfile(journal)}


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
        lang = detect_lang_text(_read_source(result["spec"] or result["plan"]))
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


def _runner_errors(runner: Any) -> List[str]:
    """Checks of the optional `runner` section (spec plan-chain-runner-2, section C): version,
    profile, specs, graph (membership, runner-graph-cycle), roles of models, start_commit and parallel
    (optional keys), sessions. Required keys: version, profile, specs, graph, models, sessions."""
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
    errors.extend(_runner_sessions_errors(runner.get("sessions")))
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


def _stage_evidence(journal: str, entry: Dict[str, Any], stage: str,
                    warnings: List[str]) -> Optional[Tuple[Dict[str, str], str]]:
    """(artifacts, why) when the stage's own artifacts show it finished, else None."""
    plan_path = os.path.join(os.path.dirname(os.path.abspath(journal)), entry["plan"])
    plan_dir, stem = os.path.dirname(plan_path), os.path.splitext(os.path.basename(plan_path))[0]
    if not os.path.isdir(plan_dir):
        return None
    if stage == "writing":
        return ({"plan": entry["plan"]}, f"plan exists: {entry['plan']}") if os.path.isfile(plan_path) else None
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

    p_bl_parse = sub.add_parser("backlog-parse", help="list unchecked BACKLOG.md items")
    p_bl_parse.add_argument("file", help="path to BACKLOG.md")
    p_bl_parse.add_argument("--section", help="only this section")
    p_bl_parse.set_defaults(func=cmd_backlog_parse)
    p_bl_mark = sub.add_parser("backlog-mark", help="check off one item of an approved spec in <root>/BACKLOG.md")
    p_bl_mark.add_argument("root", help="git top-level of the spec's directory, else the working directory")
    p_bl_mark.add_argument("--section", required=True, help="goal section that holds the item")
    p_bl_mark.add_argument("--item", required=True, help="item text as backlog-parse gives it (without ' — source, date')")
    p_bl_mark.set_defaults(func=cmd_backlog_mark)
    p_settings = sub.add_parser("settings", help="chain settings, environments and backlog by the single reading rule")
    p_settings.add_argument("file", help="spec, plan, roadmap or part file")
    p_settings.set_defaults(func=cmd_settings)

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
