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

Stdlib only. Python 3.8+.

Commands:
  spec-check        <spec.md>
  findings-parse    <findings.json|-> [--root DIR]
  findings-coverage <findings.json|-> <spec.md>
  settings          <spec|plan|roadmap|part.md>
  detect-lang       <file|->
  backlog-append    <root> --section S --source "skill, artifact" --item TEXT [--lang ru|en] [--plain] [--date D]
  backlog-parse     <BACKLOG.md> [--section S]

Exit codes: 0 ok, 1 contract/validation/coverage failure, 2 usage or I/O error.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import sys
import tempfile
from typing import Any, Dict, List, Optional, Tuple


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
# Roadmap and part files point to the master plan in one of their first lines.
SOURCE_RE = re.compile(r"^>\s*(?:Source|Источник):\s*\[[^\]]*\]\((?P<target>[^)\s]+)\)")


class InputError(Exception):
    """Unreadable input or malformed JSON (exit 2)."""


def _read_source(source: str) -> str:
    if source == "-":
        return sys.stdin.read()
    try:
        with open(source, "r", encoding="utf-8-sig") as fh:
            return fh.read()
    except OSError as exc:
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
    result["errors"].extend(settings["errors"])
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
    except OSError as exc:
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


def backlog_append(root: str, section: str, source: str, item: str, lang: str = "en",
                   plain: bool = False, date: Optional[str] = None) -> Dict[str, Any]:
    """Append one line at the end of `## <section>` in `<root>/BACKLOG.md`."""
    if not os.path.isdir(root):
        raise InputError(f"root is not a directory: {root}")
    section = _backlog_field("section", section)
    source = _backlog_field("source", source)
    item = _backlog_field("item", item)
    if section in BACKLOG_USER_SECTION.values():
        raise InputError(f"section '{section}' belongs to the user; skills never write there")
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
    # Write a sibling temp file and swap it in: a crash never leaves a half-written BACKLOG.md.
    fd, temp = tempfile.mkstemp(prefix=".BACKLOG.", suffix=".tmp", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(new)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temp, path)
    except OSError as exc:
        if os.path.exists(temp):
            os.remove(temp)
        raise BacklogError(f"{path}: write failed, file left unchanged: {exc}") from exc
    with open(path, "rb") as fh:
        if fh.read() != new:
            raise BacklogError(f"{path}: content after write differs from the expected bytes")
    return {**result, "action": "created" if created else "appended"}


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
        text, source, day = match.group("body"), None, None
        if " — " in text:
            head, tail = text.rsplit(" — ", 1)
            found = BACKLOG_TAIL_RE.match(tail)
            if found:
                text, source, day = head, found.group("source"), found.group("date")
        items.append({"section": current, "text": text, "source": source, "date": day, "line": number})
    return {"ok": True, "items": items}


def cmd_backlog_append(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    result = backlog_append(args.root, args.section, args.source, args.item,
                            lang=args.lang, plain=args.plain, date=args.date)
    return 0, result


def cmd_backlog_parse(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    return 0, backlog_parse(args.file, args.section)


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
    p_settings = sub.add_parser("settings", help="chain settings, environments and backlog by the single reading rule")
    p_settings.add_argument("file", help="spec, plan, roadmap or part file")
    p_settings.set_defaults(func=cmd_settings)
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
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
