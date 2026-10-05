#!/usr/bin/env python3
"""
next_review_index.py - utility for the plan-iterative-revision skill.

Run orchestration (used by SKILL.md):
  bootstrap <plan> [--preset P] [--lenses L] [--rigor R] [--max M] [--stop-policy S]
      One-shot start: paths, lang, run_start (first review number of this run), prev review,
      resolved config, write probe, git root. Exit 0 ok, 1 not writable, 2 bad input.
      settings: chain settings by the shared reading rule (plan header, else the spec at
      **Spec:**; a part or roadmap via Source); null without plan-brainstorming alongside.
      An explicit Chain supplies --preset/--stop-policy the caller did not pass
      (config_from_settings lists them). journal: the chain journal path when that file
      exists, else null.

  record <plan> --run-start N0 --max M --issues <file|-> [--stop-policy S]
         [--mode full-cycle|audit-only] [--interaction interactive|autonomous] [--user-stop] [--lang ru|en]
         [--scope full|incremental] [--tasks <ids>]
      Takes the Phase A issues JSON, resolves 'carry' fingerprints, computes fingerprints, merges
      duplicates, applies ALL loop gates (single authority), renders + writes + strictly validates
      REVIEW(N) or the completion file, and prints {action, result, stop_reason, ..., final?,
      journal_event}. journal_event = {stage: revision, status: done|stopped, artifacts: [k=v],
      input?} when the run stops (done: clean/converged), null while the loop continues.
      --scope incremental (a re-audit of the tasks in --tasks, comma-separated ids) without issues gives
      action full-audit-required: nothing is written and the same audit runs again in full.

  guard-begin <git-root> <label> / guard-check <git-root> <label> <allowed-path>...
      Diff guard with snapshots stored in the OS temp dir (never inside the repository).
      Use a label unique per plan and phase (e.g. "<basename>-phase-a"): concurrent runs
      in the same repository must not share a label.

  parts <roadmap>
      Batch mode input: parse a plan-splitter '<base>-roadmap.md' and list its parts in table
      order: {"dir", "base", "parts": [{"id", "path", "exists", "title"}]}.

  batch-summary --results <file|->
      Fold per-part final JSONs ({"parts": {"a": {...}}}) into one batch result:
      {"result": <worst>, "parts": {...}, "counts": {...}}.

Low-level subcommands:
  next <dir> <basename>
      Scan <dir> for files matching '<basename>-review-*.md', extract numeric N,
      print JSON: {"next": N+1, "prev": "<path>"|null, "max": N|0}.

  digest <dir> <basename> [--since N]
      Print a compact machine digest of REVIEW history as JSON:
      {iteration, active_contracts[], resolved_contracts[], task_digest}. No flows (S_i unknown at audit
      start). task_digest: the scope of the next audit by the tasks' hashes (scope none-changed |
      incremental | full, the tasks to read and their line ranges); absent without reviews.

  flow-analyze <dir> <basename> --current <fps.json|-> [--since N]
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
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path
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
    "deep": {"lenses": 4, "rigor": "explore", "max": 7},
}
RIGOR_LEVELS = ("grep", "read", "explore")
STOP_POLICIES = ("pragmatic", "strict")
MAX_LENSES = 4
CHURN_WINDOW = 2
K_STUCK = 3
SEVERITY_RANK = {severity: rank for rank, severity in enumerate(SEVERITIES)}
# Incremental re-audit (spec 5 of plan-refactoring-01): task hashes in the review, scope of the next audit.
AUDIT_SCOPES = ("full", "incremental")
FULL_SCOPE_RATIO = 0.5
TASK_DIGEST_HEADING = "## Task digest"
TASK_DIGEST_ROW_RE = re.compile(r"^\|\s*(?P<id>[^|\s]+)\s*\|\s*(?P<hash>[0-9a-f]{8})\s*\|$", re.IGNORECASE)
TASK_REF_RE = re.compile(r"\b(?:Task|Задача)\s+(\d+(?:\.\d+)*)", re.IGNORECASE)
CARRIED_BY_RECORD = "not applicable — carried by record"


def print_json(data: object) -> None:
    print(json.dumps(data, ensure_ascii=True, sort_keys=True))


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
                "id": heading.group("id"),
                "title": heading.group("title").strip(),
                "fingerprint": fingerprint,
                "severity": heading.group("severity").lower(),
                "category": heading.group("category").lower(),
                "required_fix": required_fix.strip(),
                "acceptance": (extract_issue_field(block, "Acceptance") or "").strip(),
                "location_in_plan": (extract_issue_field(block, "Location in plan") or "").strip(),
                "location_in_code": (extract_issue_field(block, "Location in code") or "").strip(),
                "code_cross_check": (extract_issue_field(block, "Code cross-check") or "").strip(),
                "problem": (extract_issue_field(block, "Problem") or "").strip(),
                "fix": first_line,
                "status": status,
            }
        )
    return issues


def collect_review_files(directory: str, basename: str, since: int = 0) -> List[Tuple[int, str]]:
    if not os.path.isdir(directory):
        return []
    target_base = basename.lower()
    matches: List[Tuple[int, str]] = []
    for entry in os.listdir(directory):
        m = REVIEW_RE.match(entry)
        if not m or m.group("base").lower() != target_base:
            continue
        try:
            n = int(m.group("n"))
        except ValueError:
            continue
        if n >= since:
            matches.append((n, os.path.join(directory, entry)))
    matches.sort(key=lambda t: t[0])
    return matches


def ordered_fingerprint_sets(directory: str, basename: str, since: int = 0) -> List[set]:
    sets: List[set] = []
    for _n, path in collect_review_files(directory, basename, since):
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

    digest = parse_task_digest(text)
    if digest is not None and digest["malformed"]:
        warnings.append(f"task-digest-malformed: {len(digest['malformed'])} row(s) are not `| <task id> | <8 hex> |`")

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
    if len(path) >= 2 and path[0] == path[-1] == '"':
        path = path[1:-1]
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
        ["git", "-c", "core.quotepath=off", "-C", root, "status", "--porcelain=v1", "--untracked-files=all"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
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


def resolve_config(args: List[str]) -> Dict[str, object]:
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
            if 1 <= lenses <= MAX_LENSES:
                config["lenses"] = lenses
            else:
                errors.append(f"lenses must be in [1,{MAX_LENSES}]")
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
    return result


def cmd_resolve_config(args: List[str]) -> int:
    result = resolve_config(args)
    print_json(result)
    return 2 if "error" in result else 0


def contract_tasks(location: str) -> List[str]:
    """Task ids named in a contract's `Location in plan` (`Task N`, `Task N.M`, `Задача N`, `### Task N:`,
    at the start or inside the line, several per line), in order, once each."""
    found: List[str] = []
    for task_id in TASK_REF_RE.findall(location or ""):
        if task_id not in found:
            found.append(task_id)
    return found


def parse_task_digest(review_text: str) -> Optional[Dict[str, object]]:
    """The `## Task digest` table of a review: {"tasks": {id: 8-hex hash} in table order, "malformed": [rows]}.
    None when the review has no such section (written before it existed or without plan-brainstorming).
    The last unindented heading counts: issue fields are indented and cannot fake it."""
    lines = review_text.splitlines()
    starts = [index for index, line in enumerate(lines) if line.rstrip() == TASK_DIGEST_HEADING]
    if not starts:
        return None
    tasks: Dict[str, str] = {}
    malformed: List[str] = []
    for line in lines[starts[-1] + 1:]:
        stripped = line.strip()
        if stripped.startswith("## "):
            break
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if cells == ["Task", "Hash"] or all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            continue
        match = TASK_DIGEST_ROW_RE.match(stripped)
        if not match or match.group("id") in tasks:
            malformed.append(stripped)
            continue
        tasks[match.group("id")] = match.group("hash").lower()
    if not tasks and not malformed:
        malformed.append("(no rows)")
    return {"tasks": tasks, "malformed": malformed}


def dependents_closure(changed: Iterable[str], tasks: List[Dict[str, object]]) -> List[str]:
    """Tasks whose `refs` (Preconditions) name a changed task, then the tasks that name those, up to a
    fixed point. The seeds may include ids that are no longer in TASKS (removed tasks): their referrers
    are returned too. Plan order, without the seeds themselves; a cycle in `refs` ends at the fixed point."""
    seeds = set(changed)
    reached = set(seeds)
    grown = True
    while grown:
        grown = False
        for task in tasks:
            task_id = str(task["id"])
            if task_id not in reached and any(str(ref) in reached for ref in task.get("refs") or []):
                reached.add(task_id)
                grown = True
    return [str(task["id"]) for task in tasks if str(task["id"]) in reached - seeds]


def plan_task_index(plan_text: str) -> Tuple[Optional[List[Dict[str, object]]], Optional[str]]:
    """(tasks, None) by brainstorm_tool.parse_plan_tasks (spec 2 of plan-refactoring-01), or (None, reason):
    `task-parser-unavailable` without plan-brainstorming alongside, `no-tasks` for a plan or part without
    `### Task N:` headings, `duplicate-task-ids` when an id repeats (hashes by id would be ambiguous)."""
    parser = getattr(_load_brainstorm_tool(), "parse_plan_tasks", None)
    if parser is None:
        return None, "task-parser-unavailable"
    parsed = parser(plan_text)
    if not parsed["tasks"]:
        return None, "no-tasks"
    if parsed["duplicates"]:
        return None, "duplicate-task-ids"
    return parsed["tasks"], None


def task_scope_base(plan_sha_changed: bool, reason: Optional[str]) -> Dict[str, object]:
    """The `task_digest` block when nothing can be compared: scope `full`, `available: false`."""
    return {
        "available": False, "plan_sha_changed": plan_sha_changed, "changed": [], "new": [], "removed": [],
        "unchanged": [], "focus": [], "dependents": [], "tasks": [], "line_ranges": {},
        "changed_ratio": None, "scope": "full", "reason": reason, "warnings": [],
    }


def task_scope(plan_text: str, plan_sha: str, latest_review: str,
               active_contracts: List[Dict[str, str]]) -> Dict[str, object]:
    """Scope of the next audit: the plan's tasks against the `## Task digest` table of the latest review.
    First match wins: no task index → `full`; plan SHA-256 equal to the review's → `none-changed`; no table
    or a malformed one → `full`; changed_ratio > FULL_SCOPE_RATIO or an active contract whose
    `Location in plan` names no known task → `full`; otherwise `incremental`. `tasks` = changed ∪ new ∪
    focus ∪ dependents in plan order (the `--tasks` of `record`); `line_ranges` = those tasks + `header`."""
    sha_changed = plan_sha.lower() != (header_value(latest_review, "Plan SHA-256") or "").lower()
    tasks, reason = plan_task_index(plan_text)
    if tasks is None:
        return task_scope_base(sha_changed, reason)
    order = [str(task["id"]) for task in tasks]
    current = {str(task["id"]): str(task["sha1"]) for task in tasks}
    table = parse_task_digest(latest_review)
    previous: Dict[str, str] = dict(table["tasks"]) if table and not table["malformed"] else {}  # type: ignore[arg-type]
    known = set(current) | set(previous)
    named: List[str] = []
    irreducible = False
    for contract in active_contracts:
        ids = contract_tasks(contract.get("location_in_plan", ""))
        irreducible = irreducible or not ids or any(task_id not in known for task_id in ids)
        named += ids
    focus = [task_id for task_id in order if task_id in named]
    changed: List[str] = []
    new: List[str] = []
    removed: List[str] = []
    dependents: List[str] = []
    unchanged = list(order)
    ratio: Optional[float] = 0.0
    warnings: List[str] = []
    if not sha_changed:
        scope, reason = "none-changed", None
    elif table is None or table["malformed"]:
        scope, reason, ratio, unchanged = "full", "no-task-digest" if table is None else "task-digest-malformed", None, []
        warnings += [] if table is None else ["task-digest-malformed"]
    else:
        changed = [task_id for task_id in order if task_id in previous and previous[task_id] != current[task_id]]
        new = [task_id for task_id in order if task_id not in previous]
        removed = [task_id for task_id in previous if task_id not in current]
        dependents = dependents_closure(changed + new + removed, tasks)  # removed: their referrers now dangle
        unchanged = [task_id for task_id in order if previous.get(task_id) == current[task_id]]
        ratio = len(set(changed) | set(new) | set(removed) | set(dependents)) / max(len(previous), 1)
        scope, reason = (("full", "changed-ratio") if ratio > FULL_SCOPE_RATIO
                         else ("full", "contract-without-task") if irreducible else ("incremental", None))
    in_scope = set(changed) | set(new) | set(focus) | set(dependents)
    first = min(int(task["line_start"]) for task in tasks)  # type: ignore[arg-type]
    line_ranges: Dict[str, List[int]] = {"header": [1, first - 1]} if first > 1 else {}
    line_ranges.update({str(task["id"]): [int(task["line_start"]), int(task["line_end"])]  # type: ignore[arg-type]
                        for task in tasks if str(task["id"]) in in_scope})
    return {
        "available": True, "plan_sha_changed": sha_changed, "changed": changed, "new": new, "removed": removed,
        "unchanged": unchanged, "focus": focus, "dependents": dependents,
        "tasks": [task_id for task_id in order if task_id in in_scope], "line_ranges": line_ranges,
        "changed_ratio": None if ratio is None else round(ratio, 4), "scope": scope, "reason": reason,
        "warnings": warnings,
    }


def review_task_scope(directory: str, latest_review: str, active_contracts: List[Dict[str, str]]) -> Dict[str, object]:
    """task_scope for the plan the latest review audited: its `**Audited plan**`, a file in DIRECTORY
    (`render_review` writes a basename; the header is cut to one, so it cannot point out of DIRECTORY)."""
    name = os.path.basename(header_value(latest_review, "Audited plan") or "")
    path = os.path.join(directory, name)
    if not name or not os.path.isfile(path):
        return task_scope_base(True, "plan-not-found")
    with open(path, "rb") as f:
        plan_sha = hashlib.sha256(f.read()).hexdigest()
    return task_scope(read_text(path), plan_sha, latest_review, active_contracts)


def cmd_digest(directory: str, basename: str, since: int = 0) -> int:
    files = collect_review_files(directory, basename, since)
    if not files:
        print_json({"iteration": 1, "active_contracts": [], "resolved_contracts": []})
        return 0

    latest_n, latest_path = files[-1]
    latest_text = read_text(latest_path)
    latest_issues = parse_review_issues(latest_text)
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
                "id": issue["id"],
                "severity": issue["severity"],
                "category": issue["category"],
                "status": issue["status"],
                "fix": issue["fix"],
                "required_fix": issue["required_fix"],
                "acceptance": issue["acceptance"],
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
            "id": issue["id"],
            "category": issue["category"],
            "severity": issue["severity"],
            "status": "Fixed",
            "fix": issue["fix"],
        }
        for fingerprint, issue in earlier.items()
        if fingerprint not in latest_fingerprints
    ]
    print_json(
        {
            "iteration": latest_n + 1,
            "latest_review": os.path.basename(latest_path),
            "active_contracts": active,
            "resolved_contracts": resolved,
            "task_digest": review_task_scope(directory, latest_text, latest_issues),
        }
    )
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


def cmd_flow_analyze(directory: str, basename: str, current_arg: str, since: int = 0) -> int:
    history = ordered_fingerprint_sets(directory, basename, since)
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



# ---------- batch mode over plan-splitter parts ----------

ROADMAP_SUFFIX = "-roadmap.md"
PART_ID_RE = re.compile(r"^[a-z]{1,2}$")
ROADMAP_HEADER_RE = re.compile(r"\|\s*(stage|стадия)\s*\|", re.IGNORECASE)
# Worst result first: the batch result is the worst part result.
RESULT_SEVERITY = ("escalated", "stagnation", "limit", "converged", "clean")


def parse_roadmap_parts(text: str) -> List[Dict[str, str]]:
    """Minimal reader of the plan-splitter roadmap table: id + title, in table order."""
    rows: List[Dict[str, str]] = []
    in_table = False
    for line in text.splitlines():
        if not in_table:
            in_table = bool(ROADMAP_HEADER_RE.search(line))
            continue
        stripped = line.strip()
        if not stripped.startswith("|"):
            if rows:
                break
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) < 2 or all(re.fullmatch(r":?-{3,}:?", c) for c in cells if c):
            continue
        if ROADMAP_HEADER_RE.search(line):
            continue
        rows.append({"id": cells[0].lower(), "title": cells[1]})
    return rows


def cmd_parts(roadmap: str) -> int:
    if not os.path.isfile(roadmap):
        print_json({"error": f"roadmap not found: {roadmap}"})
        return 2
    name = os.path.basename(roadmap)
    if not name.endswith(ROADMAP_SUFFIX):
        print_json({"error": f"not a roadmap file (expected *{ROADMAP_SUFFIX}): {name}"})
        return 2
    directory = os.path.dirname(os.path.abspath(roadmap))
    base = name[: -len(ROADMAP_SUFFIX)]
    rows = parse_roadmap_parts(read_text(roadmap))
    invalid = [row["id"] for row in rows if not PART_ID_RE.match(row["id"])]
    if invalid:
        print_json({"error": "invalid part ids in roadmap table: " + ", ".join(invalid)})
        return 2
    if not rows:
        print_json({"error": "roadmap table is empty"})
        return 2
    parts = []
    for row in rows:
        path = os.path.join(directory, f"{base}-{row['id']}.md")
        parts.append({"id": row["id"], "title": row["title"], "path": path, "exists": os.path.isfile(path)})
    print_json({"roadmap": os.path.abspath(roadmap), "dir": directory, "base": base, "parts": parts})
    return 0 if all(p["exists"] for p in parts) else 1


def cmd_batch_summary(results_arg: str) -> int:
    try:
        raw = sys.stdin.read() if results_arg == "-" else read_text(results_arg)
        payload = json.loads(raw)
    except OSError as exc:
        print_json({"error": f"cannot read results file (pass a path or '-' for stdin): {exc}"})
        return 2
    except json.JSONDecodeError as exc:
        print_json({"error": f"invalid results JSON: {exc.msg}"})
        return 2
    parts = payload.get("parts") if isinstance(payload, dict) else None
    if not isinstance(parts, dict) or not parts:
        print_json({"error": "results JSON must be an object with a non-empty 'parts' object"})
        return 2
    counts = {name: 0 for name in RESULT_SEVERITY}
    counts["error"] = 0
    invalid: List[str] = []
    for part_id, final in parts.items():
        result = final.get("result") if isinstance(final, dict) else None
        if result in RESULT_SEVERITY:
            counts[result] += 1
        elif isinstance(final, dict) and final.get("error"):
            # A part that could not be verified (bootstrap failure, guard violation, missing file).
            counts["error"] += 1
        else:
            invalid.append(str(part_id))
    if invalid:
        print_json({"error": "parts without a valid result or error: " + ", ".join(sorted(invalid))})
        return 2
    # An unverified part needs a human decision, like an escalated one.
    worst = "escalated" if counts["error"] else next(name for name in RESULT_SEVERITY if counts[name])
    remaining = sum(int(final.get("remaining_issues") or 0) for final in parts.values() if isinstance(final, dict))
    print_json({"result": worst, "remaining_issues": remaining, "counts": counts, "parts": parts})
    return 0


# ---------- run orchestration: bootstrap / record / guard ----------

CYRILLIC_EXTRA = set("ЁёІіЇїЄєҐґ")
STATUS_LINES = {
    "user-stop": "FINAL — implementation skipped by user",
    "limit": "FINAL — iteration limit reached",
    "drain": "FINAL — only nit issues remain (pragmatic stop)",
    "audit-only": "FINAL — audit-only mode, Phase B not run",
    "escalated": "ESCALATED — stuck issue needs manual decision",
    "stagnation": "FINAL — no progress between iterations",
}
REVIEW_TITLE = {"ru": "Ревизия", "en": "Revision"}
REQUIRED_INPUT_FIELDS = ("title", "location_in_plan", "code_cross_check", "problem", "required_fix", "acceptance")
# An issue's `evidence` quotes only the lines that prove it (PHASE-A-AUDIT.md); longer: a warning, never a cut.
MAX_EVIDENCE_CHARS = 600


def pop_since(args: List[str]) -> Tuple[List[str], Optional[int]]:
    """Strip an optional '--since N' pair; return (rest, since) or (rest, None) on a bad value."""
    rest: List[str] = []
    since = 0
    i = 0
    while i < len(args):
        if args[i] == "--since":
            if i + 1 >= len(args):
                return rest, None
            try:
                since = int(args[i + 1])
            except ValueError:
                return rest, None
            i += 2
            continue
        rest.append(args[i])
        i += 1
    return rest, since


def detect_lang(text: str) -> str:
    alpha = [ch for ch in text if ch.isalpha()]
    if not alpha:
        return "en"
    cyrillic = sum(1 for ch in alpha if "А" <= ch <= "я" or ch in CYRILLIC_EXTRA)
    return "ru" if cyrillic / len(alpha) > 0.05 else "en"


def git_root_of(directory: str) -> Optional[str]:
    try:
        proc = subprocess.run(
            ["git", "-C", directory, "rev-parse", "--show-toplevel"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except OSError:
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    return os.path.abspath(proc.stdout.strip())


def git_blob_of(path: str) -> Optional[str]:
    try:
        proc = subprocess.run(["git", "hash-object", path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except OSError:
        return None
    value = proc.stdout.strip()
    return value if proc.returncode == 0 and re.match(r"^[0-9a-f]{40,64}$", value) else None


def utc_now() -> str:
    import datetime

    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def plan_parts(plan: str) -> Tuple[str, str]:
    plan_abs = os.path.abspath(plan)
    base = os.path.basename(plan_abs)
    if base.lower().endswith(".md"):
        base = base[:-3]
    return os.path.dirname(plan_abs), base


def next_review_number(directory: str, basename: str) -> Tuple[int, Optional[str]]:
    files = collect_review_files(directory, basename)
    if not files:
        return 1, None
    return files[-1][0] + 1, files[-1][1]


def probe_writable(directory: str, basename: str) -> Optional[str]:
    probe = os.path.join(directory, f".{basename}-review-write-test-{os.getpid()}.tmp")
    try:
        fd = os.open(probe, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
        os.remove(probe)
    except OSError as exc:
        return f"cannot create files in {directory}: {exc}"
    return None


def _load_brainstorm_tool():
    path = Path(__file__).resolve().parents[2] / "plan-brainstorming" / "scripts" / "brainstorm_tool.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("brainstorm_tool", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def plan_settings(plan: str) -> Tuple[Optional[Dict[str, object]], List[str]]:
    """Chain settings by the shared reading rule: the plan header, else the spec at **Spec:**;
    a part or roadmap goes through its Source line (brainstorm_tool.resolve_settings)."""
    tool = _load_brainstorm_tool()
    if tool is None:
        return None, ["plan-brainstorming not installed alongside; settings unavailable"]
    try:
        settings = tool.resolve_settings(os.path.abspath(plan))
    except tool.InputError as exc:  # unreadable source of the settings: ValueError for the caller, not a traceback
        raise ValueError(str(exc)) from exc
    warnings = [f"settings: {item}" for item in settings.get("errors", [])]
    warnings += [f"settings: {item}" for item in settings.get("warnings", [])]
    return settings, warnings


def settings_config_args(settings: Optional[Dict[str, object]], config_args: List[str]) -> List[str]:
    """resolve-config flags from an explicit Chain (spec `> Chain:` or plan `**Chain:**`).
    A flag the caller passed wins; without an explicit Chain nothing is added."""
    if not settings or not settings.get("chain_explicit"):
        return []
    chain = settings.get("chain") or {}
    extra: List[str] = []
    if "--preset" not in config_args and chain.get("revision"):
        extra += ["--preset", str(chain["revision"])]
    if "--stop-policy" not in config_args and chain.get("stop"):
        extra += ["--stop-policy", str(chain["stop"])]
    return extra


def journal_for(plan: str) -> Optional[str]:
    """The chain journal of PLAN (a plan, roadmap or part; brainstorm_tool.journal_path_for)
    when that file exists. None when it does not exist yet, when plan-brainstorming is not
    installed alongside or predates the journal, and when the path cannot be resolved (e.g. a
    missing spec): the revision then runs without a journal."""
    finder = getattr(_load_brainstorm_tool(), "journal_path_for", None)
    if finder is None:
        return None
    try:
        found = finder(os.path.abspath(plan))
    except Exception:  # the module's InputError or a read error: no journal, not a failure
        return None
    return found["journal"] if found.get("exists") else None


def cmd_bootstrap(plan: str, config_args: List[str]) -> int:
    if not os.path.isfile(plan):
        print_json({"valid": False, "error": f"plan not found: {plan}"})
        return 2
    try:
        settings, settings_warnings = plan_settings(plan)
    except ValueError as exc:  # the spec at **Spec:** cannot be read (not UTF-8)
        print_json({"valid": False, "error": str(exc)})
        return 2
    from_settings = settings_config_args(settings, config_args)
    config = resolve_config(list(config_args) + from_settings)
    if "error" in config:
        print_json({"valid": False, "error": config["error"], "config": config})
        return 2
    directory, basename = plan_parts(plan)
    n, prev = next_review_number(directory, basename)
    errors: List[str] = []
    probe_error = probe_writable(directory, basename)
    if probe_error:
        errors.append(probe_error)
    warnings: List[str] = []
    warnings.extend(settings_warnings)
    if not plan.lower().endswith(".md"):
        warnings.append("plan file does not have .md extension")
    git_root = git_root_of(directory)
    if git_root is None:
        warnings.append("plan is not inside a git repository; diff guard is unavailable")
    print_json(
        {
            "valid": not errors,
            "errors": errors,
            "warnings": warnings,
            "plan": os.path.abspath(plan),
            "dir": directory,
            "basename": basename,
            "lang": detect_lang(read_text(plan)),
            "run_start": n,
            "next_review": os.path.join(directory, f"{basename}-review-{n}.md"),
            "prev_review": prev,
            "completion_path": os.path.join(directory, f"{basename}-completion.md"),
            "git_root": git_root,
            "config": config,
            "settings": settings,
            "config_from_settings": [flag[2:].replace("-", "_") for flag in from_settings[0::2]],
            "journal": journal_for(plan),
        }
    )
    return 0 if not errors else 1


# --- guard: snapshots live in the OS temp dir, never in the user's repo ---

def guard_snapshot_path(root: str, label: str) -> str:
    import tempfile

    key = hashlib.sha1(os.path.realpath(root).encode("utf-8")).hexdigest()[:12]
    safe_label = re.sub(r"[^A-Za-z0-9_.-]", "_", label)
    folder = os.path.join(tempfile.gettempdir(), "plan-iterative-revision", key)
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, f"{safe_label}.json")


def cmd_guard_begin(root: str, label: str) -> int:
    code, snapshot = git_changed(root)
    if code != 0:
        print_json({"valid": False, "git": False, "warning": "git status unavailable; check changed files manually", **snapshot})
        return 3
    with open(guard_snapshot_path(root, label), "w", encoding="utf-8") as f:
        json.dump(snapshot, f)
    print_json({"valid": True, "git": True, "label": label, "changed_count": len(snapshot["changed"])})
    return 0


def relative_to_root(root: str, path: str) -> str:
    if os.path.isabs(path):
        try:
            return normalize_path(os.path.relpath(os.path.realpath(path), os.path.realpath(root)))
        except ValueError:
            return normalize_path(path)
    return normalize_path(path)


def cmd_guard_check(root: str, label: str, allowed: Sequence[str]) -> int:
    snapshot_path = guard_snapshot_path(root, label)
    if not os.path.isfile(snapshot_path):
        print_json({"valid": False, "error": f"no guard snapshot for label '{label}'; run guard-begin first"})
        return 2
    code, after = git_changed(root)
    if code != 0:
        print_json({"valid": False, "git": False, "warning": "git status unavailable; check changed files manually", **after})
        return 3
    before = load_changed_map(snapshot_path)
    after_map = {
        normalize_path(item["path"]): {"status": item["status"], "sha256": item["sha256"]} for item in after["changed"]
    }
    allowed_rel = [relative_to_root(root, path) for path in allowed]
    changed = sorted(path for path in set(before) | set(after_map) if before.get(path) != after_map.get(path))
    violations = [path for path in changed if not path_is_allowed(path, allowed_rel)]
    os.remove(snapshot_path)
    print_json({"valid": not violations, "changed": changed, "allowed": allowed_rel, "violations": violations})
    return 0 if not violations else 1


# --- record: gate + render + validate + write, one call per audit ---

class RecordError(Exception):
    pass


def indent_block(text: str) -> str:
    lines = str(text).strip("\n").splitlines() or [""]
    return "\n".join("  " + line if line.strip() else "" for line in lines)


def one_line(text: str) -> str:
    return " ".join(str(text).split())


def find_issue_by_fingerprint(directory: str, basename: str, fingerprint: str) -> Optional[Dict[str, str]]:
    for _n, path in reversed(collect_review_files(directory, basename)):
        for issue in parse_review_issues(read_text(path)):
            if issue["fingerprint"] == fingerprint:
                found = dict(issue)
                found["review"] = os.path.basename(path)
                return found
    return None


def unbalanced_quote_lines(text: str) -> int:
    """Lines with an odd number of double quotes or backticks: the usual trace of a code quote
    whose `\\n` was written as `\n` in the JSON and became a real line break."""
    count = 0
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            continue
        if line.count('"') % 2 == 1 or line.count("`") % 2 == 1:
            count += 1
    return count


def normalize_input_issues(
    directory: str, basename: str, raw: object, warnings: Optional[List[str]] = None
) -> List[Dict[str, str]]:
    if not isinstance(raw, list):
        raise RecordError("'issues' must be a list")
    issues: List[Dict[str, str]] = []
    errors: List[str] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            errors.append(f"issue #{index}: must be an object")
            continue
        issue = {key: ("" if value is None else str(value)) for key, value in item.items()}
        carry = issue.get("carry", "").strip().lower()
        if carry:
            source = find_issue_by_fingerprint(directory, basename, carry)
            if source is None:
                errors.append(f"issue #{index}: carry fingerprint {carry} not found in review history")
                continue
            # Carried issues keep category + required fix verbatim so the fingerprint stays stable.
            issue["category"] = source["category"]
            issue["required_fix"] = source["required_fix"]
            for key in ("title", "location_in_plan", "acceptance"):
                if not issue.get(key, "").strip():
                    issue[key] = source[key]
            issue["carried_from"] = f"{source['review']}#{source['id']}"
        severity = issue.get("severity", "").strip().lower()
        category = issue.get("category", "").strip().lower()
        if severity not in SEVERITIES:
            errors.append(f"issue #{index}: invalid severity: {severity!r}")
        if category not in VALID_CATEGORIES:
            errors.append(f"issue #{index}: invalid category: {category!r}")
        for key in REQUIRED_INPUT_FIELDS:
            if not issue.get(key, "").strip():
                errors.append(f"issue #{index}: missing {key}")
        if issue.get("code_cross_check") and not code_cross_check_status(issue["code_cross_check"]):
            errors.append(
                f"issue #{index}: code_cross_check must start with one of: {', '.join(CODE_CROSS_CHECK_STATUSES)}"
            )
        if warnings is not None:
            for key in ("required_fix", "acceptance"):
                if unbalanced_quote_lines(issue.get(key, "")):
                    warnings.append(
                        f"issue #{index}: {key} has a line with an unbalanced quote or backtick; "
                        "a code quote with an unescaped \\n? In JSON write \\\\n for a literal backslash-n"
                    )
        issue["severity"] = severity
        issue["category"] = category
        issue["_order"] = str(index)
        if severity in SEVERITIES and category in VALID_CATEGORIES and issue.get("required_fix", "").strip():
            issue["fingerprint"] = make_fingerprint(category, issue["required_fix"])
        issues.append(issue)
    if errors:
        raise RecordError("; ".join(errors))

    # Merge duplicates by fingerprint: keep the highest severity, union locations/evidence.
    merged: Dict[str, Dict[str, str]] = {}
    for issue in issues:
        fp = issue["fingerprint"]
        kept = merged.get(fp)
        if kept is None:
            merged[fp] = issue
            continue
        if SEVERITY_RANK[issue["severity"]] < SEVERITY_RANK[kept["severity"]]:
            issue["_order"] = kept["_order"]
            merged[fp], issue, kept = issue, kept, issue
        for key, sep in (("location_in_plan", "; "), ("evidence", "\n")):
            extra = issue.get(key, "").strip()
            if extra and extra not in kept.get(key, ""):
                kept[key] = (kept.get(key, "").strip() + sep + extra).strip()
    result = sorted(merged.values(), key=lambda it: (SEVERITY_RANK[it["severity"]], int(it["_order"])))
    if warnings is not None:  # after the merge: merged evidence counts as one text
        for issue in result:
            length = len(issue.get("evidence", ""))
            if length > MAX_EVIDENCE_CHARS:
                warnings.append(
                    f"issue #{issue['_order']}: evidence-too-long: {length} characters (limit {MAX_EVIDENCE_CHARS}); "
                    "quote only the lines that prove the problem"
                )
    return result


def consecutive_presence(history: List[set], current: set) -> Dict[str, int]:
    """How many consecutive audits (ending with the current one) contain each fingerprint."""
    counts: Dict[str, int] = {}
    for fp in current:
        k = 1
        for s in reversed(history):
            if fp not in s:
                break
            k += 1
        counts[fp] = k
    return counts


def decide(
    history: List[set],
    issues: List[Dict[str, str]],
    max_iter: int,
    stop_policy: str,
    mode: str,
    interaction: str,
    user_stop: bool,
    scope: str = "full",
) -> Dict[str, object]:
    """Single authority for loop gates. First match wins. An incremental audit without issues proves
    nothing about the tasks it did not read: `full-audit-required`, nothing written, the same k again."""
    current = {issue["fingerprint"] for issue in issues}
    k = len(history) + 1
    flows = compute_flows(history, current)
    decision: Dict[str, object] = {"iteration": k, "flows": flows, "escalated": [], "status": None}
    if scope == "incremental" and not current:
        decision.update({"action": "full-audit-required", "result": None, "stop_reason": None, "write_review": False})
        return decision

    def stop(result: str, reason: Optional[str], status: Optional[str], write: bool = True) -> Dict[str, object]:
        decision.update(
            {"action": "stop", "result": result, "stop_reason": reason, "status": status, "write_review": write}
        )
        return decision

    if not current:
        return stop("clean" if k == 1 else "converged", None, None, write=False)
    if user_stop:
        return stop("limit", None, "user-stop")
    if mode == "audit-only":
        return stop("converged", None, "audit-only")
    if stop_policy == "pragmatic" and all(issue["severity"] == "nit" for issue in issues):
        return stop("converged", "drain", "drain")
    prev = history[-1] if history else set()
    cumulative: set = set().union(*history) if history else set()
    reintroduced = sorted((cumulative - prev) & current)
    if k >= 3 and reintroduced:
        decision["escalated"] = reintroduced
        return stop("escalated", "regression", "escalated")
    if k >= 2 and current == prev:
        return stop("stagnation", "unchanged", "stagnation")
    # churn before stuck: a window with nothing resolved always implies a K_STUCK streak.
    if classify_flow(history, current) == ("stagnation", "churn"):
        return stop("stagnation", "churn", "stagnation")
    stuck = sorted(fp for fp, n in consecutive_presence(history, current).items() if n >= K_STUCK)
    if stuck:
        decision["escalated"] = stuck
        return stop("escalated", "stuck", "escalated")
    if k > max_iter:
        if interaction == "interactive":
            decision.update({"action": "ask_limit", "result": None, "stop_reason": None, "write_review": False})
            return decision
        return stop("limit", None, "limit")
    decision.update({"action": "implement", "result": None, "stop_reason": None, "write_review": True})
    return decision


def render_review(
    n: int,
    basename: str,
    plan: str,
    lang: str,
    prev_review: Optional[str],
    issues: List[Dict[str, str]],
    payload: Dict[str, object],
    flows: Dict[str, int],
    status: Optional[str],
    audit_tasks: Optional[List[str]] = None,
    task_hashes: Optional[List[Tuple[str, str]]] = None,
) -> str:
    """AUDIT_TASKS: the task ids of an incremental audit (None = a full audit, `all`); TASK_HASHES:
    (id, 8-hex sha1) of every plan task for the `## Task digest` table (None = no table)."""
    counts = {severity: sum(1 for it in issues if it["severity"] == severity) for severity in SEVERITIES}
    with open(plan, "rb") as f:
        data = f.read()
    blob = git_blob_of(plan)
    lines = [
        f"# {REVIEW_TITLE.get(lang, 'Revision')} {n}: {basename}",
        "",
        f"**Iteration**: {n}",
        f"**Audited plan**: {os.path.basename(plan)}",
        f"**Plan SHA-256**: {hashlib.sha256(data).hexdigest()}",
        f"**Plan size**: {len(data)} bytes",
    ]
    if blob:
        lines.append(f"**Plan git blob**: {blob}")
    lines += [
        f"**Audited at**: {utc_now()}",
        f"**Previous review**: {os.path.basename(prev_review) if prev_review else 'none'}",
        f"**Audit scope**: {'full' if audit_tasks is None else 'incremental'}",
        f"**Audit tasks**: {'all' if audit_tasks is None else ', '.join(audit_tasks) or 'none'}",
        f"**Issues found**: {len(issues)} (blocker: {counts['blocker']}, major: {counts['major']}, "
        f"minor: {counts['minor']}, nit: {counts['nit']})",
        f"**Flow**: +{flows['new']} / -{flows['resolved']} / {flows['persisted']} persisted / "
        f"{flows['reintroduced']} reintro | Profile: "
        f"({counts['blocker']},{counts['major']},{counts['minor']},{counts['nit']})",
    ]
    if status:
        lines.append(f"**Status**: {STATUS_LINES[status]}")

    audit = payload.get("audit_state") if isinstance(payload.get("audit_state"), dict) else {}
    carried = [it for it in issues if it.get("carried_from")]
    rows = [
        (
            "Previous review contracts checked",
            audit.get("previous_contracts", "yes" if prev_review else "n-a"),
            audit.get("previous_contracts_notes", ""),
        ),
        ("Taxonomy sweep completed", audit.get("taxonomy", "yes"), "10 classes"),
        ("Code cross-check completed", audit.get("code_cross_check", "yes"), audit.get("code_cross_check_notes", "")),
        ("Review validated", "yes", "validate-review --strict-fingerprint"),
        ("Deferred conflicts carried", str(len(carried)), ", ".join(it["carried_from"] for it in carried)),
        ("Lenses used", str(audit.get("lenses_used", "")), ""),
    ]
    lines += ["", "## Audit state", "", "| Check | Status | Notes |", "|---|---|---|"]
    lines += [f"| {name} | {one_line(value)} | {one_line(notes)} |" for name, value, notes in rows]
    lines += ["", "## Summary", "", str(payload.get("summary") or "").strip() or "-", "", "## Issues", ""]
    for k, it in enumerate(issues, start=1):
        it["id"] = f"{n}.{k}"
        lines += [
            f"### [{n}.{k}] {it['severity']} · {it['category']} · {one_line(it['title'])}",
            "",
            f"- **Location in plan**: {one_line(it['location_in_plan'])}",
            f"- **Location in code**: {one_line(it.get('location_in_code') or 'n/a')}",
            f"- **Code cross-check**: {one_line(it['code_cross_check'])}",
        ]
        if it.get("carried_from"):
            lines.append(f"- **Carried from**: {it['carried_from']}")
        lines += ["- **Problem**:", indent_block(it["problem"])]
        if it.get("evidence", "").strip():
            lines += ["- **Evidence**:", indent_block(it["evidence"])]
        lines += [
            "- **Required fix (contract)**:",
            indent_block(it["required_fix"]),
            "- **Acceptance**:",
            indent_block(it["acceptance"]),
            f"- **Fingerprint**: {it['fingerprint']}",
            "",
        ]
    lines += ["## Deferred from previous review", ""]
    lines += [f"- [{it['id']}] carried from {it['carried_from']}" for it in carried] or ["none"]
    lines += ["", "## Notes for implementation", "", str(payload.get("notes") or "").strip() or "none", ""]
    if task_hashes:
        lines += [TASK_DIGEST_HEADING, "", "| Task | Hash |", "|---|---|"]
        lines += [f"| {task_id} | {sha} |" for task_id, sha in task_hashes] + [""]
    return "\n".join(lines)


COMPLETION_VERDICT = {
    "en": "Cycle converged: the last audit found no issues. All review contracts have been applied to the plan.",
    "ru": "Цикл сошёлся: последний аудит не нашёл проблем. Все контракты ревизий применены к плану.",
}


def render_completion(lang: str, basename: str, plan: str, reviews: List[str]) -> str:
    skill_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    template = read_text(os.path.join(skill_dir, "assets", f"completion-report.{lang}.md"))
    with open(plan, "rb") as f:
        sha = hashlib.sha256(f.read()).hexdigest()
    values = {
        "basename": basename,
        "iterations": str(len(reviews)),
        # one audit per review written, plus the final clean audit
        "audits": str(len(reviews) + 1),
        "final_plan_sha256": sha,
        "finished_at_utc": utc_now(),
        "verdict": COMPLETION_VERDICT.get(lang, COMPLETION_VERDICT["en"]),
        "list_of_review_files": "\n".join(f"- {name}" for name in reviews),
    }
    for key, value in values.items():
        template = template.replace("{{" + key + "}}", value)
    return template


# Chain journal status of the revision stage for each way a run ends (the verdict is
# stop_reason, else the gate status, else the result; see decide). A gate that is not
# listed needs a human as well.
REVISION_JOURNAL_STATUS = {
    "clean": "done", "converged": "done", "drain": "done", "audit-only": "done",
    "limit": "stopped", "user-stop": "stopped", "regression": "stopped",
    "unchanged": "stopped", "churn": "stopped", "stuck": "stopped",
}


def journal_ref(path: str, journal: Optional[str]) -> str:
    """PATH as the journal stores it: relative to the journal's directory with forward
    slashes; absolute without a journal or without a relative path (another drive)."""
    path = os.path.abspath(path)
    if journal:
        try:
            return os.path.relpath(path, os.path.dirname(os.path.abspath(journal))).replace(os.sep, "/")
        except ValueError:
            pass
    return path


def revision_journal_event(
    decision: Dict[str, object],
    plan: str,
    review: Optional[str],
    completion: Optional[str],
    journal: Optional[str],
) -> Optional[Dict[str, object]]:
    """The revision stage update for `journal-event`, or None while the loop continues
    (implement, ask_limit). Artifacts are `key=value` strings: the last review of this run,
    the completion file, the verdict. `input` (the plan, for input_sha256) only on done."""
    if decision["action"] != "stop":
        return None
    verdict = str(decision["stop_reason"] or decision["status"] or decision["result"])
    status = REVISION_JOURNAL_STATUS.get(verdict, "stopped")
    artifacts: List[str] = []
    if review:
        artifacts.append(f"review={journal_ref(review, journal)}")
    if completion:
        artifacts.append(f"completion={journal_ref(completion, journal)}")
    artifacts.append(f"verdict={verdict}")
    event: Dict[str, object] = {"stage": "revision", "status": status, "artifacts": artifacts}
    if status == "done":
        event["input"] = os.path.abspath(plan)
    return event


def dropped_contracts(
    directory: str, basename: str, run_start: int, plan_index: List[Dict[str, object]], issues: List[Dict[str, str]]
) -> List[Dict[str, str]]:
    """Contracts of the latest review in the run that an incremental audit left out although every task
    they name is unchanged (its sha1 equals the review's `## Task digest` row): the fix cannot have
    landed. Contracts of changed tasks and contracts without a task id are not returned."""
    latest = read_text(collect_review_files(directory, basename, run_start)[-1][1])
    table = parse_task_digest(latest)
    if table is None or table["malformed"]:
        return []
    hashes: Dict[str, str] = dict(table["tasks"])  # type: ignore[arg-type]
    unchanged = {str(task["id"]) for task in plan_index if hashes.get(str(task["id"])) == task["sha1"]}
    present = {issue["fingerprint"] for issue in issues}
    dropped: Dict[str, Dict[str, str]] = {}
    for contract in parse_review_issues(latest):
        fingerprint, ids = contract["fingerprint"], contract_tasks(contract["location_in_plan"])
        if fingerprint and fingerprint not in present and ids and all(task_id in unchanged for task_id in ids):
            dropped.setdefault(fingerprint, contract)
    return list(dropped.values())


def carry_of(contract: Dict[str, str]) -> Dict[str, str]:
    """The carry item `record` adds for a dropped contract: its earlier severity, problem, cross-check
    and location in code; an old review without them gives the required fix and CARRIED_BY_RECORD."""
    cross_check = contract.get("code_cross_check", "")
    return {
        "carry": contract["fingerprint"],
        "severity": contract["severity"],
        "problem": contract.get("problem") or contract["required_fix"],
        "code_cross_check": cross_check if code_cross_check_status(cross_check) else CARRIED_BY_RECORD,
        "location_in_code": contract.get("location_in_code", ""),
    }


RECORD_OPTIONS = {
    "--run-start": "run_start",
    "--max": "max",
    "--stop-policy": "stop_policy",
    "--mode": "mode",
    "--interaction": "interaction",
    "--issues": "issues",
    "--lang": "lang",
    "--scope": "scope",
    "--tasks": "tasks",
}


def parse_record_args(args: List[str]) -> Dict[str, object]:
    opts: Dict[str, object] = {
        "mode": "full-cycle",
        "interaction": "autonomous",
        "user_stop": False,
        "stop_policy": "pragmatic",
        "scope": "full",
    }
    positional: List[str] = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--user-stop":
            opts["user_stop"] = True
            i += 1
        elif arg in RECORD_OPTIONS:
            if i + 1 >= len(args):
                raise RecordError(f"missing value for {arg}")
            opts[RECORD_OPTIONS[arg]] = args[i + 1]
            i += 2
        elif arg.startswith("--"):
            raise RecordError(f"unknown option: {arg}")
        else:
            positional.append(arg)
            i += 1
    if len(positional) != 1:
        raise RecordError("expected exactly one <plan> argument")
    opts["plan"] = positional[0]
    for key in ("run_start", "max"):
        flag = "--" + key.replace("_", "-")
        if key not in opts:
            raise RecordError(f"{flag} is required")
        try:
            opts[key] = int(str(opts[key]))
        except ValueError:
            raise RecordError(f"{flag} must be an integer")
    if "issues" not in opts:
        raise RecordError("--issues <file|-> is required")
    if opts["mode"] not in ("full-cycle", "audit-only"):
        raise RecordError("--mode must be full-cycle or audit-only")
    if opts["interaction"] not in ("interactive", "autonomous"):
        raise RecordError("--interaction must be interactive or autonomous")
    if opts.get("lang") not in (None, "ru", "en"):
        raise RecordError("--lang must be ru or en")
    if opts["stop_policy"] not in STOP_POLICIES:
        raise RecordError(f"--stop-policy must be one of: {', '.join(STOP_POLICIES)}")
    if opts["scope"] not in AUDIT_SCOPES:
        raise RecordError("--scope must be full or incremental")
    if opts["scope"] == "incremental":
        if "tasks" not in opts:
            raise RecordError("--tasks <ids> is required with --scope incremental")
        if opts["mode"] == "audit-only":
            raise RecordError("--mode audit-only is always a full audit; drop --scope incremental")
        ids = [item.strip() for item in str(opts["tasks"]).split(",") if item.strip()]
        opts["tasks"] = list(dict.fromkeys(ids))
    else:
        opts["tasks"] = None  # a full audit names no tasks: --tasks is ignored
    return opts


def cmd_record(args: List[str]) -> int:
    try:
        opts = parse_record_args(args)
    except RecordError as exc:
        print_json({"error": str(exc)})
        return 64
    plan = str(opts["plan"])
    if not os.path.isfile(plan):
        print_json({"error": f"plan not found: {plan}"})
        return 2
    directory, basename = plan_parts(plan)
    source = str(opts["issues"])
    try:
        payload = json.loads(sys.stdin.read() if source == "-" else read_text(source))
        if isinstance(payload, list):
            payload = {"issues": payload}
        if not isinstance(payload, dict):
            raise RecordError("issues JSON must be an object or a list")
        input_warnings: List[str] = []
        issues = normalize_input_issues(directory, basename, payload.get("issues", []), input_warnings)
    except (OSError, ValueError, RecordError) as exc:
        print_json({"error": str(exc)})
        return 2

    run_start = int(opts["run_start"])  # type: ignore[arg-type]
    history = ordered_fingerprint_sets(directory, basename, run_start)
    plan_index, _reason = plan_task_index(read_text(plan))
    # The ids of an incremental audit, None for a full one; without the task index the review records a full audit.
    audit_tasks = opts["tasks"] if plan_index is not None else None
    if opts["tasks"] is not None:
        if not history:
            print_json({"error": "--scope incremental: the first audit of a run must be full"})
            return 64
        known = {str(task["id"]) for task in plan_index or []}
        unknown = [task_id for task_id in opts["tasks"] if plan_index is not None and task_id not in known]  # type: ignore[union-attr]
        if unknown:
            print_json({"error": f"--tasks names tasks the plan does not have: {', '.join(unknown)}"})
            return 64
        dropped = dropped_contracts(directory, basename, run_start, plan_index, issues) if plan_index else []
        if dropped:
            raw = list(payload.get("issues", [])) + [carry_of(contract) for contract in dropped]
            issues = normalize_input_issues(directory, basename, raw)
            input_warnings.append("contracts-dropped: [" + ", ".join(c["fingerprint"] for c in dropped) + "]")
    decision = decide(
        history,
        issues,
        int(opts["max"]),  # type: ignore[arg-type]
        str(opts["stop_policy"]),
        str(opts["mode"]),
        str(opts["interaction"]),
        bool(opts["user_stop"]),
        str(opts["scope"]),
    )
    lang = str(opts.get("lang") or detect_lang(read_text(plan)))
    run_reviews = [os.path.basename(path) for _n, path in collect_review_files(directory, basename, run_start)]
    out: Dict[str, object] = {
        "action": decision["action"],
        "result": decision["result"],
        "stop_reason": decision["stop_reason"],
        "iteration": decision["iteration"],
        "flows": decision["flows"],
        "escalated": decision["escalated"],
        "review_path": None,
        "completion_path": None,
        "issues": [],
        "warnings": input_warnings,
    }

    if decision.get("write_review"):
        n, prev = next_review_number(directory, basename)
        path = os.path.join(directory, f"{basename}-review-{n}.md")
        text = render_review(
            n, basename, plan, lang, prev, issues, payload, decision["flows"], decision["status"],  # type: ignore[arg-type]
            audit_tasks=audit_tasks,  # type: ignore[arg-type]
            task_hashes=[(str(task["id"]), str(task["sha1"])) for task in plan_index] if plan_index else None,
        )
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:
            print_json({"error": f"review file already exists: {path}"})
            return 2
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        valid, report = validate_review(path, strict_fingerprint=True)
        if not valid:
            os.remove(path)
            print_json({"error": "rendered review failed validation", "validation": report})
            return 1
        out["review_path"] = path
        run_reviews.append(os.path.basename(path))
        out["issues"] = [
            {"id": it["id"], "severity": it["severity"], "fingerprint": it["fingerprint"], "title": one_line(it["title"])}
            for it in issues
        ]
    elif decision["result"] == "converged":
        path = os.path.join(directory, f"{basename}-completion.md")
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(render_completion(lang, basename, plan, run_reviews))
        out["completion_path"] = path

    if decision["action"] == "stop":
        final: Dict[str, object] = {
            "result": decision["result"],
            "iterations": len(run_reviews),
            "remaining_issues": len(issues) if decision.get("write_review") else 0,
            "escalated": decision["escalated"],
            "stop_reason": decision["stop_reason"],
            "flows": decision["flows"],
        }
        audit = payload.get("audit_state")
        lenses = audit.get("lenses_used") if isinstance(audit, dict) else None
        if isinstance(lenses, int) and 1 <= lenses <= MAX_LENSES:
            final["lenses_used"] = lenses
        out["final"] = final
    journal_event = None
    if decision["action"] == "stop":
        last_review = os.path.join(directory, run_reviews[-1]) if run_reviews else None
        journal_event = revision_journal_event(decision, plan, last_review, out["completion_path"], journal_for(plan))
    out["journal_event"] = journal_event
    print_json(out)
    return 0


def main(argv: List[str]) -> int:
    if len(argv) < 2:
        print(__doc__ or "", file=sys.stderr)
        return 64

    cmd = argv[1]
    if cmd in ("-h", "--help", "help"):
        print(__doc__ or "")
        return 0
    if cmd == "next":
        if len(argv) != 4:
            print("usage: next_review_index.py next <dir> <basename>", file=sys.stderr)
            return 64
        return cmd_next(argv[2], argv[3])

    if cmd == "digest":
        rest, since = pop_since(argv[2:])
        if len(rest) != 2 or since is None:
            print("usage: next_review_index.py digest <dir> <basename> [--since N]", file=sys.stderr)
            return 64
        return cmd_digest(rest[0], rest[1], since)

    if cmd == "flow-analyze":
        rest, since = pop_since(argv[2:])
        if len(rest) != 4 or rest[2] != "--current" or since is None:
            print(
                "usage: next_review_index.py flow-analyze <dir> <basename> --current <fps.json|-> [--since N]",
                file=sys.stderr,
            )
            return 64
        return cmd_flow_analyze(rest[0], rest[1], rest[3], since)

    if cmd == "parts":
        if len(argv) != 3:
            print("usage: next_review_index.py parts <roadmap>", file=sys.stderr)
            return 64
        return cmd_parts(argv[2])

    if cmd == "batch-summary":
        if len(argv) != 4 or argv[2] != "--results":
            print("usage: next_review_index.py batch-summary --results <file|->", file=sys.stderr)
            return 64
        return cmd_batch_summary(argv[3])

    if cmd == "bootstrap":
        if len(argv) < 3:
            print("usage: next_review_index.py bootstrap <plan> [resolve-config flags...]", file=sys.stderr)
            return 64
        return cmd_bootstrap(argv[2], argv[3:])

    if cmd == "record":
        return cmd_record(argv[2:])

    if cmd == "guard-begin":
        if len(argv) != 4:
            print("usage: next_review_index.py guard-begin <git-root> <label>", file=sys.stderr)
            return 64
        return cmd_guard_begin(argv[2], argv[3])

    if cmd == "guard-check":
        if len(argv) < 5:
            print("usage: next_review_index.py guard-check <git-root> <label> <allowed-path>...", file=sys.stderr)
            return 64
        return cmd_guard_check(argv[2], argv[3], argv[4:])

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
