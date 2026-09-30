#!/usr/bin/env python3
"""Deterministic helper for the plan-brainstorming skill.

- spec-check: verifies a written spec against references/spec-contract.md
  (8 headings in order, non-empty sections, empty Open Questions, Tier line).
- findings-parse: validates a JSON list of code-review findings, assigns
  stable ids (F1..Fn in input order), optionally checks file/line locations.
- findings-coverage: verifies that a spec mentions every finding id.

Stdlib only. Python 3.8+.

Commands:
  spec-check        <spec.md>
  findings-parse    <findings.json|-> [--root DIR]
  findings-coverage <findings.json|-> <spec.md>

Exit codes: 0 ok, 1 contract/validation/coverage failure, 2 usage or I/O error.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
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
TIER_RE = re.compile(r"^>\s*Tier:\s*(?P<tier>\S+)\s*$")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
PLACEHOLDER_RE = re.compile(r"\b(TBD|TODO|FIXME)\b")
NONE_TEXT = "(none)"


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
            warnings.append(f"line {number}: extra top-level heading '{line}' (not part of the contract)")
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
            if body not in ("", NONE_TEXT):
                errors.append("## Open Questions must be empty or '(none)' before handoff")
        elif not body:
            errors.append(f"empty section: {heading} (use '(none)' with a one-line rationale)")
        elif body == NONE_TEXT:
            if heading == "## Out of Scope":
                errors.append("## Out of Scope must list excluded work explicitly")
            else:
                warnings.append(f"{heading}: '(none)' without a one-line rationale")

    return {"ok": not errors, "tier": tier, "errors": errors, "warnings": warnings}


def cmd_spec_check(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    result = check_spec(_read_source(args.spec))
    return (0 if result["ok"] else 1), result


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
    ok = not missing and not unknown
    return (0 if ok else 1), {
        "ok": ok,
        "expected": len(expected),
        "covered": [fid for fid in expected if fid in mentioned],
        "missing": missing,
        "unknown": unknown,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command")

    p_spec = sub.add_parser("spec-check", help="check a spec against the spec contract")
    p_spec.add_argument("spec", help="path to the written spec")
    p_spec.set_defaults(func=cmd_spec_check)

    p_parse = sub.add_parser("findings-parse", help="validate findings and assign ids")
    p_parse.add_argument("findings", help="path to findings JSON, or - for stdin")
    p_parse.add_argument("--root", help="workspace root for file/line existence checks")
    p_parse.set_defaults(func=cmd_parse)

    p_cov = sub.add_parser("findings-coverage", help="check that a spec mentions every finding id")
    p_cov.add_argument("findings", help="path to findings JSON, or - for stdin")
    p_cov.add_argument("spec", help="path to the written spec")
    p_cov.set_defaults(func=cmd_coverage)
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
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
