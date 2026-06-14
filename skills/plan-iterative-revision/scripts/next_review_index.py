#!/usr/bin/env python3
"""
next_review_index.py — utility for the plan-iterative-revision skill.

Subcommands:
  next <dir> <basename>
      Scan <dir> for files matching '<basename>-review-*.md', extract numeric N,
      print JSON: {"next": N+1, "prev": "<path>"|null, "max": N|0}.

  digest <dir> <basename>
      Print a compact machine digest of REVIEW history as JSON:
      {iteration, active_contracts[], resolved_contracts[]}. No flows (S_i unknown at audit start).

  flow-analyze <dir> <basename> --current <fps.json|->
      Set-algebra over fingerprint history vs current audit S_i. Print JSON:
      {iteration, flows{new,resolved,persisted,reintroduced}, persisted_counts, result, stop_reason}.
      result/stop_reason are a deterministic SUGGESTER; WORKFLOW remains authoritative.

  preflight-review <dir> <basename> <N>
      Fail-fast check that '<basename>-review-<N>.md' can be created in <dir>.
      Verifies that the directory exists, the target file does not exist, and a temporary
      probe file can be created and removed. This does not check agent tool availability.

  hash <file>
      Print SHA-256 hex of <file> raw bytes.

  fingerprint <category> <required-fix...>
      Print the canonical 8-char issue fingerprint.

  fingerprint-file <category> <file>
      Read required-fix text from <file> and print the canonical fingerprint.

  completion-path <dir> <basename>
      Print JSON: {"path": "<dir>/<basename>-completion.md", "exists": bool}.
      Deterministic path for the completion artifact. Does not create anything.

  validate-review [--strict-fingerprint] <review-file>
      Validate review structure and print JSON. Exits 0 when valid, 1 when invalid.
      --strict-fingerprint also verifies Fingerprint values against Required fix text.

  changed <git-root>
      Print a JSON git status snapshot for later diff checks.

  check-allowed <before-json> <after-json> <allowed-path>...
      Compare two snapshots from 'changed' and fail if any newly changed path is not allowed.

Stdlib only. Python 3.8+.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


REVIEW_RE = re.compile(r"^(?P<base>.+)-review-(?P<n>\d+)\.md$", re.IGNORECASE)
ISSUE_HEADING_RE = re.compile(
    r"^###\s+\[(?P<id>\d+\.\d+)\]\s+"
    r"(?P<severity>[A-Za-z]+)\s+·\s+"
    r"(?P<category>[a-z0-9-]+)\s+·\s+"
    r"(?P<title>.+)$",
    re.MULTILINE,
)
FIELD_RE_TEMPLATE = r"- \*\*{label}\*\*:\s*(?P<body>.*?)(?=\n- \*\*|\n### |\n## |\Z)"
HEX64_RE = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)
FINGERPRINT_RE = re.compile(r"^[0-9a-f]{8}$", re.IGNORECASE)
SEVERITIES = ("blocker", "major", "minor", "nit")
CODE_CROSS_CHECK_STATUSES = ("verified", "not found", "ambiguous", "not applicable")
REQUIRED_REVIEW_SECTIONS = ("## Audit state", "## Summary", "## Issues")
VALID_CATEGORIES = {
    "logic",
    "code",
    "math",
    "ops",
    "db",
    "contract",
    "tests",
    "security",
    "perf",
    "code-plan-mismatch",
    "unfulfilled-contract",
}

PRESETS = {
    "quick": {"lenses": 1, "rigor": "grep", "max": 3},
    "standard": {"lenses": 2, "rigor": "read", "max": 5},
    "deep": {"lenses": 3, "rigor": "explore", "max": 7},
}
RIGOR_LEVELS = ("grep", "read", "explore")
STOP_POLICIES = ("pragmatic", "strict")
CHURN_WINDOW = 2
K_STUCK = 3


def print_json(data: object) -> None:
    print(json.dumps(data, ensure_ascii=False, sort_keys=True))


def normalize_required_fix(text: str) -> str:
    return " ".join(text.strip().split())


def make_fingerprint(category: str, required_fix: str) -> str:
    normalized = normalize_required_fix(required_fix)
    payload = f"{category.lower()}\n{normalized[:200]}".encode("utf-8")
    return hashlib.sha1(payload).hexdigest()[:8]


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def cmd_next(directory: str, basename: str) -> int:
    if not os.path.isdir(directory):
        print_json({"error": f"directory not found: {directory}"})
        return 2

    matches: List[Tuple[int, str]] = []
    target_base = basename.lower()
    for entry in os.listdir(directory):
        m = REVIEW_RE.match(entry)
        if not m:
            continue
        if m.group("base").lower() != target_base:
            continue
        try:
            n = int(m.group("n"))
        except ValueError:
            continue
        matches.append((n, os.path.join(directory, entry)))

    if not matches:
        print_json({"next": 1, "prev": None, "max": 0})
        return 0

    matches.sort(key=lambda t: t[0])
    max_n, prev_path = matches[-1]
    print_json({"next": max_n + 1, "prev": prev_path, "max": max_n})
    return 0


def cmd_preflight_review(directory: str, basename: str, n_text: str) -> int:
    errors: List[str] = []
    checks = {
        "directory_exists": False,
        "target_absent": False,
        "probe_create_delete": False,
    }

    try:
        n = int(n_text)
        if n < 1:
            errors.append("N must be >= 1")
    except ValueError:
        n = 0
        errors.append(f"N must be an integer: {n_text}")

    target = os.path.join(directory, f"{basename}-review-{n}.md") if n >= 1 else ""

    if not os.path.isdir(directory):
        errors.append(f"directory not found: {directory}")
    else:
        checks["directory_exists"] = True

    if target and os.path.exists(target):
        errors.append(f"review file already exists: {target}")
    elif target:
        checks["target_absent"] = True

    if not errors and target:
        probe = os.path.join(directory, f".{basename}-review-write-test-{os.getpid()}.tmp")
        suffix = 0
        while os.path.exists(probe):
            suffix += 1
            probe = os.path.join(directory, f".{basename}-review-write-test-{os.getpid()}-{suffix}.tmp")
        fd: Optional[int] = None
        try:
            fd = os.open(probe, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.write(fd, b"preflight\n")
            checks["probe_create_delete"] = True
        except OSError as exc:
            errors.append(f"cannot create probe file in review directory: {exc}")
        finally:
            if fd is not None:
                os.close(fd)
            if os.path.exists(probe):
                try:
                    os.remove(probe)
                except OSError as exc:
                    errors.append(f"cannot remove probe file {probe}: {exc}")
                    checks["probe_create_delete"] = False

    valid = not errors
    print_json({"valid": valid, "path": target, "errors": errors, "checks": checks})
    return 0 if valid else 1


def cmd_hash(path: str) -> int:
    if not os.path.isfile(path):
        print_json({"error": f"file not found: {path}"})
        return 2
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    print(h.hexdigest())
    return 0


def cmd_fingerprint(category: str, required_fix: str) -> int:
    if category.lower() not in VALID_CATEGORIES:
        print_json({"error": f"unknown category: {category}", "valid_categories": sorted(VALID_CATEGORIES)})
        return 2
    print(make_fingerprint(category, required_fix))
    return 0


def header_value(text: str, field: str) -> Optional[str]:
    pattern = re.compile(rf"^\*\*{re.escape(field)}\*\*:\s*(?P<value>.*)$", re.MULTILINE)
    m = pattern.search(text)
    return m.group("value").strip() if m else None


def parse_expected_counts(value: str) -> Optional[Dict[str, int]]:
    m = re.search(
        r"(?P<total>\d+)\s*\(\s*blocker:\s*(?P<blocker>\d+)\s*,\s*"
        r"major:\s*(?P<major>\d+)\s*,\s*minor:\s*(?P<minor>\d+)\s*,\s*nit:\s*(?P<nit>\d+)\s*\)",
        value,
        re.IGNORECASE,
    )
    if not m:
        return None
    return {k: int(m.group(k)) for k in ("total", "blocker", "major", "minor", "nit")}


def issue_blocks(text: str) -> Iterable[Tuple[re.Match[str], str]]:
    matches = list(ISSUE_HEADING_RE.finditer(text))
    for idx, match in enumerate(matches):
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        yield match, text[start:end]


def extract_issue_field(block: str, label: str) -> Optional[str]:
    pattern = re.compile(FIELD_RE_TEMPLATE.format(label=re.escape(label)), re.DOTALL)
    m = pattern.search(block)
    if not m:
        return None
    return m.group("body").strip()


def parse_review_issues(text: str) -> List[Dict[str, str]]:
    issues: List[Dict[str, str]] = []
    for heading, block in issue_blocks(text):
        required_fix = extract_issue_field(block, "Required fix (contract)") or ""
        fp_field = extract_issue_field(block, "Fingerprint") or ""
        fingerprint = fp_field.split()[0].lower() if fp_field.split() else ""
        lowered = block.lower()
        status = "Deferred" if ("deferred-conflict" in lowered or "status: escalated" in lowered) else "Open"
        first_line = required_fix.strip().splitlines()[0].strip() if required_fix.strip() else ""
        issues.append(
            {
                "fingerprint": fingerprint,
                "severity": heading.group("severity").lower(),
                "category": heading.group("category").lower(),
                "required_fix": required_fix.strip(),
                "fix": first_line,
                "status": status,
            }
        )
    return issues


def collect_review_files(directory: str, basename: str) -> List[Tuple[int, str]]:
    if not os.path.isdir(directory):
        return []
    target_base = basename.lower()
    matches: List[Tuple[int, str]] = []
    for entry in os.listdir(directory):
        m = REVIEW_RE.match(entry)
        if not m or m.group("base").lower() != target_base:
            continue
        try:
            matches.append((int(m.group("n")), os.path.join(directory, entry)))
        except ValueError:
            continue
    matches.sort(key=lambda t: t[0])
    return matches


def ordered_fingerprint_sets(directory: str, basename: str) -> List[set]:
    sets: List[set] = []
    for _n, path in collect_review_files(directory, basename):
        fps = {iss["fingerprint"] for iss in parse_review_issues(read_text(path)) if iss["fingerprint"]}
        sets.append(fps)
    return sets


def compute_flows(history: List[set], current: set) -> Dict[str, int]:
    prev = history[-1] if history else set()
    cumulative: set = set()
    for s in history:
        cumulative |= s
    new = current - cumulative
    resolved = prev - current
    persisted = prev & current
    reintroduced = (cumulative - prev) & current
    return {
        "new": len(new),
        "resolved": len(resolved),
        "persisted": len(persisted),
        "reintroduced": len(reintroduced),
    }


def persisted_counts(history: List[set], current: set) -> Dict[str, int]:
    prev = history[-1] if history else set()
    persisted = prev & current
    counts: Dict[str, int] = {}
    for fp in persisted:
        k = 0
        for s in reversed(history):
            if fp in s:
                k += 1
            else:
                break
        counts[fp] = k
    return counts


def classify_flow(history: List[set], current: set) -> Tuple[str, Optional[str]]:
    i = len(history) + 1
    if not current:
        return "clean", None

    flows = compute_flows(history, current)
    if i >= 3 and flows["reintroduced"] > 0:
        return "escalated", "regression"

    if i >= 3 and flows["new"] > 0:
        window_empty = True
        chain = history + [current]
        for t in range(len(chain) - 1, len(chain) - 1 - CHURN_WINDOW, -1):
            if t < 1:
                break
            if chain[t - 1] - chain[t]:
                window_empty = False
                break
        if window_empty:
            return "stagnation", "churn"

    return "continue", None


def code_cross_check_status(value: str) -> str:
    normalized = " ".join(value.strip().lower().split())
    for status in CODE_CROSS_CHECK_STATUSES:
        if normalized == status or normalized.startswith(status + " "):
            return status
    return ""


def validate_review(path: str, strict_fingerprint: bool) -> Tuple[bool, Dict[str, object]]:
    if not os.path.isfile(path):
        return False, {"valid": False, "errors": [f"file not found: {path}"], "path": path}

    text = read_text(path)
    errors: List[str] = []
    warnings: List[str] = []
    required_headers = [
        "Iteration",
        "Audited plan",
        "Plan SHA-256",
        "Plan size",
        "Audited at",
        "Previous review",
        "Issues found",
    ]
    headers = {field: header_value(text, field) for field in required_headers + ["Plan git blob", "Status"]}
    for field in required_headers:
        if not headers.get(field):
            errors.append(f"missing header: {field}")

    for section in REQUIRED_REVIEW_SECTIONS:
        if section not in text:
            errors.append(f"missing section: {section}")

    if headers.get("Plan SHA-256") and not HEX64_RE.match(headers["Plan SHA-256"] or ""):
        errors.append("Plan SHA-256 must be 64 hex chars")

    expected_counts: Optional[Dict[str, int]] = None
    if headers.get("Issues found"):
        expected_counts = parse_expected_counts(headers["Issues found"] or "")
        if expected_counts is None:
            errors.append("Issues found header must include total and severity counts")

    actual_counts = {severity: 0 for severity in SEVERITIES}
    issues_summary: List[Dict[str, object]] = []
    headings = list(issue_blocks(text))
    if expected_counts and expected_counts["total"] > 0 and not headings:
        errors.append("Issues found is non-zero, but no issue headings were found")

    seen_ids = set()
    for heading, block in headings:
        issue_id = heading.group("id")
        severity = heading.group("severity").lower()
        category = heading.group("category").lower()
        title = heading.group("title").strip()

        if issue_id in seen_ids:
            errors.append(f"duplicate issue id: {issue_id}")
        seen_ids.add(issue_id)

        if severity not in SEVERITIES:
            errors.append(f"{issue_id}: invalid severity: {severity}")
        else:
            actual_counts[severity] += 1

        if category not in VALID_CATEGORIES:
            errors.append(f"{issue_id}: invalid category: {category}")

        required_fix = extract_issue_field(block, "Required fix (contract)")
        acceptance = extract_issue_field(block, "Acceptance")
        fingerprint = extract_issue_field(block, "Fingerprint")
        cross_check = extract_issue_field(block, "Code cross-check")

        if not required_fix:
            errors.append(f"{issue_id}: missing Required fix (contract)")
        if not acceptance:
            errors.append(f"{issue_id}: missing Acceptance")
        if not fingerprint:
            errors.append(f"{issue_id}: missing Fingerprint")
        elif not FINGERPRINT_RE.match(fingerprint.split()[0]):
            errors.append(f"{issue_id}: Fingerprint must be 8 hex chars")
        elif strict_fingerprint and required_fix:
            expected = make_fingerprint(category, required_fix)
            actual = fingerprint.split()[0].lower()
            if expected != actual:
                errors.append(f"{issue_id}: fingerprint mismatch: expected {expected}, got {actual}")

        if not cross_check:
            errors.append(f"{issue_id}: missing Code cross-check status")
        elif not code_cross_check_status(cross_check):
            errors.append(
                f"{issue_id}: invalid Code cross-check status: {cross_check.splitlines()[0]} "
                f"(expected one of: {', '.join(CODE_CROSS_CHECK_STATUSES)})"
            )

        issues_summary.append(
            {
                "id": issue_id,
                "severity": severity,
                "category": category,
                "title": title,
                "has_required_fix": bool(required_fix),
                "has_acceptance": bool(acceptance),
                "has_fingerprint": bool(fingerprint),
                "has_code_cross_check": bool(cross_check),
            }
        )

    if expected_counts:
        actual_total = sum(actual_counts.values())
        if expected_counts["total"] != actual_total:
            errors.append(f"Issues found total mismatch: expected {expected_counts['total']}, actual {actual_total}")
        for severity in SEVERITIES:
            if expected_counts[severity] != actual_counts[severity]:
                errors.append(
                    f"Issues found {severity} mismatch: expected {expected_counts[severity]}, "
                    f"actual {actual_counts[severity]}"
                )

    valid = not errors
    return valid, {
        "valid": valid,
        "path": path,
        "errors": errors,
        "warnings": warnings,
        "summary": {
            "issue_count": len(issues_summary),
            "severity_counts": actual_counts,
            "strict_fingerprint": strict_fingerprint,
        },
        "issues": issues_summary,
    }


def parse_git_status_line(line: str) -> Optional[Dict[str, str]]:
    if not line:
        return None
    status = line[:2]
    path = line[3:] if len(line) > 3 else ""
    if " -> " in path:
        path = path.split(" -> ", 1)[1]
    return {"status": status, "path": path.replace("\\", "/")}


def file_sha256_or_none(path: str) -> Optional[str]:
    if not os.path.isfile(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def git_changed(root: str) -> Tuple[int, Dict[str, object]]:
    proc = subprocess.run(
        ["git", "-C", root, "status", "--porcelain=v1", "--untracked-files=all"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if proc.returncode != 0:
        return proc.returncode, {"error": proc.stderr.strip() or "git status failed", "root": root}
    root_abs = os.path.abspath(root)
    changed = []
    for item in (parse_git_status_line(line) for line in proc.stdout.splitlines()):
        if not item:
            continue
        item["sha256"] = file_sha256_or_none(os.path.join(root_abs, item["path"])) or ""
        changed.append(item)
    return 0, {"root": root_abs, "changed": changed}


def normalize_path(path: str) -> str:
    return path.replace("\\", "/").strip("/")


def load_changed_map(snapshot_path: str) -> Dict[str, Dict[str, str]]:
    with open(snapshot_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        changed = data.get("changed", [])
    else:
        changed = data
    result: Dict[str, Dict[str, str]] = {}
    for item in changed:
        if isinstance(item, dict) and "path" in item:
            path = normalize_path(str(item["path"]))
            result[path] = {
                "status": str(item.get("status", "")),
                "sha256": str(item.get("sha256", "")),
            }
        elif isinstance(item, str):
            result[normalize_path(item)] = {"status": "", "sha256": ""}
    return result


def path_is_allowed(path: str, allowed: Sequence[str]) -> bool:
    normalized = normalize_path(path)
    for candidate in allowed:
        allowed_path = normalize_path(candidate)
        if normalized == allowed_path:
            return True
        if allowed_path.endswith("/") and normalized.startswith(allowed_path):
            return True
    return False


def cmd_check_allowed(before_json: str, after_json: str, allowed: Sequence[str]) -> int:
    before = load_changed_map(before_json)
    after = load_changed_map(after_json)
    all_paths = set(before) | set(after)
    changed_between_snapshots = sorted(path for path in all_paths if before.get(path) != after.get(path))
    violations = [path for path in changed_between_snapshots if not path_is_allowed(path, allowed)]
    result = {
        "valid": not violations,
        "changed_between_snapshots": changed_between_snapshots,
        "newly_changed": changed_between_snapshots,
        "allowed": [normalize_path(path) for path in allowed],
        "violations": violations,
    }
    print_json(result)
    return 0 if not violations else 1


def cmd_resolve_config(args: List[str]) -> int:
    preset = "standard"
    stop_policy = "pragmatic"
    overrides: Dict[str, str] = {}
    errors: List[str] = []

    flag_map = {
        "--preset": "preset",
        "--lenses": "lenses",
        "--rigor": "rigor",
        "--max": "max",
        "--stop-policy": "stop_policy",
    }
    i = 0
    while i < len(args):
        key = flag_map.get(args[i])
        if key is None or i + 1 >= len(args):
            errors.append(f"unknown or incomplete argument: {args[i]}")
            i += 1
            continue
        value = args[i + 1]
        if key == "preset":
            preset = value
        elif key == "stop_policy":
            stop_policy = value
        else:
            overrides[key] = value
        i += 2

    if preset in PRESETS:
        config: Dict[str, object] = dict(PRESETS[preset])
    else:
        errors.append(f"unknown preset: {preset} (valid: {', '.join(sorted(PRESETS))})")
        config = {"lenses": None, "rigor": None, "max": None}

    if "lenses" in overrides:
        try:
            lenses = int(overrides["lenses"])
            if 1 <= lenses <= 3:
                config["lenses"] = lenses
            else:
                errors.append("lenses must be in [1,3]")
        except ValueError:
            errors.append(f"lenses must be an integer: {overrides['lenses']}")
    if "rigor" in overrides:
        if overrides["rigor"] in RIGOR_LEVELS:
            config["rigor"] = overrides["rigor"]
        else:
            errors.append(f"unknown rigor: {overrides['rigor']} (valid: {', '.join(RIGOR_LEVELS)})")
    if "max" in overrides:
        try:
            max_iter = int(overrides["max"])
            if max_iter >= 1:
                config["max"] = max_iter
            else:
                errors.append("max must be >= 1")
        except ValueError:
            errors.append(f"max must be an integer: {overrides['max']}")
    if stop_policy not in STOP_POLICIES:
        errors.append(f"unknown stop_policy: {stop_policy} (valid: {', '.join(STOP_POLICIES)})")

    result: Dict[str, object] = {
        "preset": preset,
        "lenses": config["lenses"],
        "rigor": config["rigor"],
        "max": config["max"],
        "stop_policy": stop_policy,
    }
    if errors:
        result["error"] = "; ".join(errors)
    print_json(result)
    return 0 if not errors else 2


def cmd_digest(directory: str, basename: str) -> int:
    files = collect_review_files(directory, basename)
    if not files:
        print_json({"iteration": 1, "active_contracts": [], "resolved_contracts": []})
        return 0

    latest_n, latest_path = files[-1]
    latest_issues = parse_review_issues(read_text(latest_path))
    active: List[Dict[str, str]] = []
    seen: set = set()
    for issue in latest_issues:
        fingerprint = issue["fingerprint"]
        if not fingerprint or fingerprint in seen:
            continue
        seen.add(fingerprint)
        active.append(
            {
                "fingerprint": fingerprint,
                "severity": issue["severity"],
                "status": issue["status"],
                "fix": issue["fix"],
            }
        )

    latest_fingerprints = {issue["fingerprint"] for issue in latest_issues if issue["fingerprint"]}
    earlier: Dict[str, Dict[str, str]] = {}
    for _n, path in files[:-1]:
        for issue in parse_review_issues(read_text(path)):
            fingerprint = issue["fingerprint"]
            if fingerprint:
                earlier[fingerprint] = issue

    resolved = [
        {
            "fingerprint": fingerprint,
            "severity": issue["severity"],
            "status": "Fixed",
            "fix": issue["fix"],
        }
        for fingerprint, issue in earlier.items()
        if fingerprint not in latest_fingerprints
    ]
    print_json({"iteration": latest_n + 1, "active_contracts": active, "resolved_contracts": resolved})
    return 0


def load_current_fingerprints(arg: str) -> set:
    raw = sys.stdin.read() if arg == "-" else read_text(arg)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        source = "stdin" if arg == "-" else arg
        raise ValueError(f"invalid JSON in {source}: {exc.msg}") from exc

    if isinstance(data, dict):
        data = data.get("fingerprints", [])
        if not isinstance(data, list):
            raise ValueError("current fingerprints must be a list")
    elif not isinstance(data, list):
        raise ValueError("current JSON must be a list or an object with a fingerprints list")

    return {str(x).strip().lower() for x in data if str(x).strip()}


def cmd_flow_analyze(directory: str, basename: str, current_arg: str) -> int:
    history = ordered_fingerprint_sets(directory, basename)
    try:
        current = load_current_fingerprints(current_arg)
    except (OSError, ValueError) as exc:
        print_json({"error": str(exc)})
        return 2

    flows = compute_flows(history, current)
    result, stop_reason = classify_flow(history, current)
    print_json(
        {
            "iteration": len(history) + 1,
            "flows": flows,
            "persisted_counts": persisted_counts(history, current),
            "result": result,
            "stop_reason": stop_reason,
        }
    )
    return 0


def cmd_completion_path(directory: str, basename: str) -> int:
    """Print the deterministic completion-file path as JSON."""
    path = os.path.join(directory, f"{basename}-completion.md")
    print_json({"path": path, "exists": os.path.isfile(path)})
    return 0


def main(argv: List[str]) -> int:
    if len(argv) < 2:
        print(__doc__ or "", file=sys.stderr)
        return 64

    cmd = argv[1]
    if cmd == "next":
        if len(argv) != 4:
            print("usage: next_review_index.py next <dir> <basename>", file=sys.stderr)
            return 64
        return cmd_next(argv[2], argv[3])

    if cmd == "digest":
        if len(argv) != 4:
            print("usage: next_review_index.py digest <dir> <basename>", file=sys.stderr)
            return 64
        return cmd_digest(argv[2], argv[3])

    if cmd == "flow-analyze":
        if len(argv) != 6 or argv[4] != "--current":
            print("usage: next_review_index.py flow-analyze <dir> <basename> --current <fps.json|->", file=sys.stderr)
            return 64
        return cmd_flow_analyze(argv[2], argv[3], argv[5])

    if cmd == "preflight-review":
        if len(argv) != 5:
            print("usage: next_review_index.py preflight-review <dir> <basename> <N>", file=sys.stderr)
            return 64
        return cmd_preflight_review(argv[2], argv[3], argv[4])

    if cmd == "hash":
        if len(argv) != 3:
            print("usage: next_review_index.py hash <file>", file=sys.stderr)
            return 64
        return cmd_hash(argv[2])

    if cmd == "fingerprint":
        if len(argv) < 4:
            print("usage: next_review_index.py fingerprint <category> <required-fix...>", file=sys.stderr)
            return 64
        return cmd_fingerprint(argv[2], " ".join(argv[3:]))

    if cmd == "fingerprint-file":
        if len(argv) != 4:
            print("usage: next_review_index.py fingerprint-file <category> <file>", file=sys.stderr)
            return 64
        if not os.path.isfile(argv[3]):
            print_json({"error": f"file not found: {argv[3]}"})
            return 2
        return cmd_fingerprint(argv[2], read_text(argv[3]))

    if cmd == "validate-review":
        strict = False
        args = argv[2:]
        if args and args[0] == "--strict-fingerprint":
            strict = True
            args = args[1:]
        if len(args) != 1:
            print("usage: next_review_index.py validate-review [--strict-fingerprint] <review-file>", file=sys.stderr)
            return 64
        valid, result = validate_review(args[0], strict)
        print_json(result)
        return 0 if valid else 1

    if cmd == "changed":
        if len(argv) != 3:
            print("usage: next_review_index.py changed <git-root>", file=sys.stderr)
            return 64
        code, result = git_changed(argv[2])
        print_json(result)
        return code

    if cmd == "check-allowed":
        if len(argv) < 5:
            print("usage: next_review_index.py check-allowed <before-json> <after-json> <allowed-path>...", file=sys.stderr)
            return 64
        return cmd_check_allowed(argv[2], argv[3], argv[4:])

    if cmd == "resolve-config":
        return cmd_resolve_config(argv[2:])

    if cmd == "completion-path":
        if len(argv) != 4:
            print("usage: next_review_index.py completion-path <dir> <basename>", file=sys.stderr)
            return 64
        return cmd_completion_path(argv[2], argv[3])

    print(f"unknown subcommand: {cmd}", file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv))
