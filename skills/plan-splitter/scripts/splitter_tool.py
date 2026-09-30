#!/usr/bin/env python3
"""
splitter_tool.py — utility for the plan-splitter skill.

Subcommands:
  preflight <dir> <base_name>
      Check write access to <dir> and list existing split artifacts for this base
      (roadmap, part files, review/completion files, verify JSONs). Returns JSON:
      {"writable": bool, "existing": ["<file>", ...], "warning": "<text>"|null}.
      Existing files are a WARNING, not an error: the agent decides what to do.

  part-id <N>
      Print the part id for ordinal N (1 -> a, 26 -> z, 27 -> aa).

  stage-name <base> <N|id>
      Print '<base>-<id>.md' for ordinal N or part id (e.g. 1 -> "<base>-a.md").

  detect-lang <file>
      Detect language by cyrillic_ratio. Print JSON:
      {"lang": "ru"|"en", "cyrillic_ratio": <float>}.
      Threshold: cyrillic_ratio > 0.05 -> "ru", else "en".

  validate-stage <file>
      Validate that the stg-file has all required sections. Print JSON:
      {"valid": bool, "missing": [...], "extra": [...]}.

  validate-roadmap <file>
      Validate roadmap structure: required sections, dependency table, stage links.
      Print JSON: {"valid": bool, "missing": [...], "errors": [...], "stages": [...]}.

  validate-all <dir> <base_name>
      Cross-validation of the whole set: '<base>-roadmap.md' + all '<base>-<id>.md' parts.
      Checks: file existence, DAG (no cycles), depends->exist, parallel-group consistency,
      task-coverage (sum of part tasks >= original-plan tasks), original-plan hash.
      Print JSON with detailed results. Exit 0 on success, 1 on failure.

  verify-baseline <dir> <base_name> [--stages all|a[,b...]] [--out <file>]
      Snapshot selected part SHA-256 values and pre-existing review files.
      'all' takes the parts from the roadmap table, in table order. --out writes the JSON
      file itself (UTF-8) in addition to printing it.

  verify-record <dir> <base_name> --results <file|-> --ledger <file> [--mode full-cycle|audit-only]
      Upsert the ledger from plan-iterative-revision's batch JSON ({"parts": {"a": {...}}}).

  verify-status <dir> <base_name> --baseline <file> --ledger <file> --validator <file>
      Verify ledger entries against current part/review artifacts.

  hash <file>
      Print SHA-256 hex of <file> raw bytes.

Stdlib only. Python 3.8+.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from typing import Dict, List, Optional, Set, Tuple


# Part ids are lowercase letters: a..z, then aa, ab, ... (bijective base-26).
PART_ID_RE = re.compile(r"^[a-z]{1,2}$")
ROADMAP_SUFFIX = "-roadmap.md"
STAGE_FILE_RE = re.compile(r"^(?P<base>.+)-(?P<part>[a-z]{1,2})\.md$")
ROADMAP_FILE_RE = re.compile(r"^(?P<base>.+)-roadmap\.md$")
REVIEW_FILE_RE = re.compile(r"^(?P<base>.+)-(?P<part>[a-z]{1,2})-review-(?P<n>\d+)\.md$")
PART_ARTIFACT_RE = re.compile(r"^(?P<base>.+)-(?P<part>[a-z]{1,2})-(?:review-\d+|completion)\.md$")
VERIFY_JSON_RE = re.compile(r"^(?P<base>.+)-verify-(?:baseline|ledger)\.json$")
CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")
FENCE_RE = re.compile(r"^\s*(```|~~~)")

REQUIRED_STAGE_SECTIONS = (
    "## Цель",
    "## Входные данные",
    "## Задачи",
    "## Критерии завершения",
    "## Выходные данные",
    "## Примечания",
)
REQUIRED_STAGE_SECTIONS_EN = (
    "## Goal",
    "## Inputs",
    "## Tasks",
    "## Completion criteria",
    "## Outputs",
    "## Notes",
)

REQUIRED_ROADMAP_SECTIONS = (
    "## Обзор",
    "## Граф зависимостей",
    "## Стадии",
)
REQUIRED_ROADMAP_SECTIONS_EN = (
    "## Overview",
    "## Dependency graph",
    "## Stages",
)

GRANULARITY_TASK_THRESHOLD = 15  # tasks per stage; above this is a soft warning


def print_json(data: object, exit_code: int = 0) -> None:
    # ASCII-only output survives any console code page; json.loads restores the text.
    print(json.dumps(data, ensure_ascii=True, sort_keys=True, indent=2))
    sys.exit(exit_code)


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _load_json(path: str) -> Dict[str, object]:
    if not os.path.isfile(path):
        raise ValueError(f"JSON file not found: {path}")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return data


def cyrillic_ratio(text: str) -> float:
    """Ecosystem convention (same formula in plan-iterative-revision and plan-resolver)."""
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return 0.0
    cyr = sum(1 for ch in letters if CYRILLIC_RE.match(ch))
    return cyr / len(letters)


def detect_lang_for_text(text: str) -> Tuple[str, float]:
    ratio = cyrillic_ratio(text)
    lang = "ru" if ratio > 0.05 else "en"
    return lang, ratio


def part_id(n: int) -> str:
    """1 -> a, 26 -> z, 27 -> aa (bijective base-26)."""
    if n < 1:
        raise ValueError("Part ordinal must be >= 1")
    letters = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        letters = chr(ord("a") + rem) + letters
    return letters


def normalize_part_id(raw: str) -> str:
    """Accept an ordinal ('3') or a part id in any case ('C'); return the canonical id."""
    value = str(raw).strip()
    if value.isdigit():
        return part_id(int(value))
    value = value.lower()
    if not PART_ID_RE.match(value):
        raise ValueError(f"Invalid part id: {raw}")
    return value


def stage_filename(base: str, part: object) -> str:
    return f"{base}-{normalize_part_id(str(part))}.md"


def roadmap_filename(base: str) -> str:
    return f"{base}{ROADMAP_SUFFIX}"


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _get_flag(args: List[str], flag: str, default: Optional[str] = None) -> Optional[str]:
    if flag not in args:
        return default
    index = args.index(flag)
    if index + 1 >= len(args):
        raise ValueError(f"Missing value for {flag}")
    return args[index + 1]


def roadmap_part_ids(directory: str, base: str) -> List[str]:
    """Part ids in roadmap-table order; the roadmap is the source of truth for 'all'."""
    roadmap_path = os.path.join(directory, roadmap_filename(base))
    if not os.path.isfile(roadmap_path):
        raise ValueError(f"Roadmap not found: {roadmap_path}")
    rows = parse_roadmap_table(read_text(roadmap_path))
    return [row["id"] for row in rows if not row.get("error")]


def _stage_ids(stages_arg: str, directory: str, base: str) -> List[str]:
    if stages_arg == "all":
        stage_ids = roadmap_part_ids(directory, base)
    else:
        stage_ids = [normalize_part_id(raw) for raw in re.split(r"[,\s]+", stages_arg) if raw.strip()]
    for stage in stage_ids:
        path = os.path.join(directory, stage_filename(base, stage))
        if not os.path.isfile(path):
            raise ValueError(f"Stage file not found: {path}")
    return stage_ids


def _reviews_for_stage(directory: str, base: str, stage: str) -> List[str]:
    reviews: List[Tuple[int, str]] = []
    for name in os.listdir(directory):
        match = REVIEW_FILE_RE.match(name)
        if not match:
            continue
        if match.group("base") == base and match.group("part") == stage:
            reviews.append((int(match.group("n")), name))
    reviews.sort(key=lambda item: item[0])
    return [name for _n, name in reviews]


def _current_reviews(directory: str, base: str, stage: str) -> List[str]:
    return _reviews_for_stage(directory, base, stage)


def _validate_review(validator_path: str, review_path: str) -> bool:
    if not os.path.isfile(validator_path):
        raise ValueError(f"Validator not found: {validator_path}")
    process = subprocess.run(
        [sys.executable, validator_path, "validate-review", "--strict-fingerprint", review_path],
        capture_output=True,
        text=True,
    )
    return process.returncode == 0


def _status_stage_ids(stages_arg: str, directory: str, base: str, baseline_stages: Dict[str, object]) -> List[str]:
    resolved = _stage_ids(stages_arg, directory, base)
    if stages_arg == "all":
        return [stage for stage in resolved if stage in baseline_stages]
    missing = [stage for stage in resolved if stage not in baseline_stages]
    if missing:
        raise ValueError(f"Stage not present in baseline: {', '.join(missing)}")
    return resolved


# ---------- preflight ----------

def cmd_preflight(directory: str, base_name: str) -> None:
    result: Dict[str, object] = {"writable": False, "existing": [], "warning": None}
    if not os.path.isdir(directory):
        result["error"] = f"Directory does not exist: {directory}"
        print_json(result, 1)

    # Probe write access.
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", dir=directory, delete=True, prefix=".splitter-probe-"
        ) as _:
            pass
        result["writable"] = True
    except OSError as e:
        result["error"] = f"Cannot write to {directory}: {e}"
        print_json(result, 1)

    # Scan for existing split artifacts of this base.
    existing: List[str] = []
    for name in os.listdir(directory):
        for pattern in (STAGE_FILE_RE, ROADMAP_FILE_RE, PART_ARTIFACT_RE, VERIFY_JSON_RE):
            m = pattern.match(name)
            if m and m.group("base") == base_name:
                existing.append(name)
                break
    existing.sort()
    result["existing"] = existing
    if existing:
        result["warning"] = (
            f"Found {len(existing)} existing split artifact(s) for base '{base_name}'. "
            "Ask the user before overwriting."
        )
    print_json(result, 0)


# ---------- stage-name ----------

def cmd_stage_name(base: str, n_str: str) -> None:
    print(stage_filename(base, n_str))


def cmd_part_id(n_str: str) -> None:
    print(part_id(int(n_str)))


# ---------- detect-lang ----------

def cmd_detect_lang(path: str) -> None:
    text = read_text(path)
    lang, ratio = detect_lang_for_text(text)
    print_json({"lang": lang, "cyrillic_ratio": round(ratio, 4)})


# ---------- validate-stage ----------

def _check_sections(text: str, required_ru: Tuple[str, ...], required_en: Tuple[str, ...]) -> Tuple[List[str], str]:
    lang, _ = detect_lang_for_text(text)
    required = required_ru if lang == "ru" else required_en
    missing = [s for s in required if s not in text]
    return missing, lang


def cmd_validate_stage(path: str) -> None:
    if not os.path.isfile(path):
        print_json({"valid": False, "error": f"File not found: {path}"}, 1)
    text = read_text(path)
    missing, lang = _check_sections(text, REQUIRED_STAGE_SECTIONS, REQUIRED_STAGE_SECTIONS_EN)

    # Self-sufficiency heuristic: forbidden back-references.
    forbidden_patterns = [
        r"\bкак описано выше\b",
        r"\bсм\.\s*выше\b",
        r"\bпредыдущий пункт\b",
        r"\bпредыдущей секции\b",
        r"\bsee above\b",
        r"\bas described above\b",
        r"\bprevious section\b",
    ]
    warnings: List[str] = []
    for pat in forbidden_patterns:
        if re.search(pat, text, re.IGNORECASE):
            warnings.append(f"Back-reference found: '{pat}'")

    n_tasks = count_tasks_in_stage(text)
    granularity_warning = None
    if n_tasks > GRANULARITY_TASK_THRESHOLD:
        granularity_warning = (
            f"Stage has {n_tasks} tasks (> {GRANULARITY_TASK_THRESHOLD}); "
            "may be too large for a single agent pass - consider re-splitting."
        )

    result = {
        "valid": not missing,
        "lang": lang,
        "missing": missing,
        "warnings": warnings,
        "granularity_warning": granularity_warning,
    }
    print_json(result, 0 if not missing else 1)


# ---------- validate-roadmap ----------

ROADMAP_TABLE_HEADER_RE = re.compile(
    r"\|\s*(?:Стадия|Stage)\s*\|\s*(?:Название|Title|Name)\s*\|\s*(?:Зависит\s*от|Depends\s*on)\s*\|"
    r"\s*(?:Параллельная\s*группа|Parallel\s*group)\s*\|\s*(?:Вес|Weight)\s*\|",
    re.IGNORECASE,
)
MERMAID_BLOCK_RE = re.compile(
    r"```mermaid\s*\n(.+?)\n```",
    re.DOTALL,
)


def validate_mermaid_block(text: str) -> List[str]:
    mermaid_match = MERMAID_BLOCK_RE.search(text)
    if not mermaid_match:
        return ["Mermaid visualization block not found"]

    mermaid_body = mermaid_match.group(1).strip()
    if "-->" not in mermaid_body:
        return ["Mermaid block is empty (no edges found)"]

    return []


def parse_roadmap_table(text: str) -> List[Dict[str, str]]:
    """Parse the dependency table from roadmap. Returns list of stage dicts."""
    lines = text.splitlines()
    rows: List[Dict[str, str]] = []
    in_table = False
    header_idx: Optional[int] = None
    for i, line in enumerate(lines):
        if ROADMAP_TABLE_HEADER_RE.search(line):
            header_idx = i
            in_table = True
            continue
        if in_table:
            if not line.strip().startswith("|"):
                break
            # Skip separator row like |---|---|
            if re.match(r"^\|[\s\-:]+\|", line):
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) < 5:
                continue
            stage_id = cells[0].strip().lower()
            depends_raw = cells[2].strip()
            depends: List[str] = []
            if depends_raw and depends_raw not in ("—", "-", ""):
                depends = [d.strip().lower() for d in re.split(r"[,\s]+", depends_raw) if d.strip()]
            row = {
                "id": stage_id,
                "title": cells[1].strip(),
                "depends": ",".join(depends),
                "group": cells[3].strip(),
                "weight": cells[4].strip(),
            }
            if not PART_ID_RE.match(stage_id):
                row["error"] = f"invalid stage id: {cells[0].strip()} (expected a, b, ... aa)"
            rows.append(row)
    return rows


def cmd_validate_roadmap(path: str) -> None:
    if not os.path.isfile(path):
        print_json({"valid": False, "error": f"File not found: {path}"}, 1)
    text = read_text(path)
    missing, lang = _check_sections(text, REQUIRED_ROADMAP_SECTIONS, REQUIRED_ROADMAP_SECTIONS_EN)
    stages = parse_roadmap_table(text)
    errors: List[str] = []
    if not stages:
        errors.append("Dependency table not found or empty")
    errors.extend(str(s["error"]) for s in stages if s.get("error"))
    stages = [s for s in stages if not s.get("error")]
    stage_ids = {s["id"] for s in stages}
    for s in stages:
        deps = [d for d in s["depends"].split(",") if d]
        for d in deps:
            if d not in stage_ids:
                errors.append(f"Stage {s['id']} depends on unknown stage '{d}'")

    errors.extend(validate_mermaid_block(text))

    valid = not missing and not errors
    result = {
        "valid": valid,
        "lang": lang,
        "missing": missing,
        "errors": errors,
        "stages": stages,
    }
    print_json(result, 0 if valid else 1)


# ---------- validate-all ----------

def has_cycle(graph: Dict[str, List[str]]) -> Optional[List[str]]:
    """Return a cycle (list of node ids) or None if DAG."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color: Dict[str, int] = {n: WHITE for n in graph}
    parent: Dict[str, Optional[str]] = {n: None for n in graph}

    def dfs(u: str) -> Optional[List[str]]:
        color[u] = GRAY
        for v in graph.get(u, []):
            if v not in color:
                continue
            if color[v] == GRAY:
                # cycle: walk back via parent until v
                cyc = [v, u]
                p = parent[u]
                while p is not None and p != v:
                    cyc.append(p)
                    p = parent[p]
                cyc.reverse()
                return cyc
            if color[v] == WHITE:
                parent[v] = u
                res = dfs(v)
                if res:
                    return res
        color[u] = BLACK
        return None

    for n in graph:
        if color[n] == WHITE:
            res = dfs(n)
            if res:
                return res
    return None


def _lines_outside_fences(text: str) -> List[str]:
    kept: List[str] = []
    in_fence = False
    for line in text.splitlines():
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            kept.append(line)
    return kept


def count_tasks_in_stage(text: str) -> int:
    """Count top-level numbered items in the '## Задачи' / '## Tasks' section (code fences ignored)."""
    m = re.search(r"^##\s+(?:Задачи|Tasks)\s*$", text, re.MULTILINE)
    if not m:
        return 0
    start = m.end()
    next_sec = re.search(r"^##\s+", text[start:], re.MULTILINE)
    section = text[start: start + next_sec.start()] if next_sec else text[start:]
    return sum(1 for line in _lines_outside_fences(section) if re.match(r"^\d+\.\s+\S", line))


def count_tasks_in_original(text: str) -> int:
    """Task/Задача headings when the plan has them; otherwise top-level numbered items outside fences."""
    lines = _lines_outside_fences(text)
    headings = sum(1 for line in lines if re.match(r"^#{2,4}\s*(?:Task|Задача)\s+\S+?\s*(?:[:\-]|—|\.\s)", line))
    if headings:
        return headings
    return sum(1 for line in lines if re.match(r"^\d+\.\s+\S", line))


def cmd_validate_all(directory: str, base_name: str) -> None:
    if not os.path.isdir(directory):
        print_json({"valid": False, "error": f"Directory not found: {directory}"}, 1)

    roadmap_path = os.path.join(directory, roadmap_filename(base_name))
    original_path = os.path.join(directory, f"{base_name}.md")

    errors: List[str] = []
    if not os.path.isfile(roadmap_path):
        errors.append(f"Roadmap not found: {roadmap_path}")
        print_json({"valid": False, "errors": errors}, 1)

    roadmap_text = read_text(roadmap_path)
    missing_roadmap, _ = _check_sections(roadmap_text, REQUIRED_ROADMAP_SECTIONS, REQUIRED_ROADMAP_SECTIONS_EN)
    if missing_roadmap:
        errors.append(f"Roadmap missing sections: {missing_roadmap}")
    errors.extend(validate_mermaid_block(roadmap_text))

    stages = parse_roadmap_table(roadmap_text)
    errors.extend(str(s["error"]) for s in stages if s.get("error"))
    stages = [s for s in stages if not s.get("error")]
    if not stages:
        errors.append("Roadmap dependency table is empty")
        print_json({"valid": False, "errors": errors}, 1)

    # 1. Files on disk + validate-stage per file
    stage_ids = {s["id"] for s in stages}
    stage_files: Dict[str, str] = {}
    for s in stages:
        fname = stage_filename(base_name, s["id"])
        fpath = os.path.join(directory, fname)
        if not os.path.isfile(fpath):
            errors.append(f"Stage file missing: {fname}")
            continue
        stage_files[s["id"]] = fpath
        stext = read_text(fpath)
        miss, _ = _check_sections(stext, REQUIRED_STAGE_SECTIONS, REQUIRED_STAGE_SECTIONS_EN)
        if miss:
            errors.append(f"{fname}: missing sections {miss}")

    # 2. DAG check
    graph: Dict[str, List[str]] = {s["id"]: [d for d in s["depends"].split(",") if d] for s in stages}
    cycle = has_cycle(graph)
    if cycle:
        errors.append(f"Dependency cycle: {' -> '.join(cycle)}")

    # 3. depends -> existing stages
    for sid, deps in graph.items():
        for d in deps:
            if d not in stage_ids:
                errors.append(f"{sid} depends on unknown stage '{d}'")

    # 4. Parallel-group consistency
    groups: Dict[str, List[str]] = {}
    for s in stages:
        g = s["group"]
        if g:
            groups.setdefault(g, []).append(s["id"])
    for g, members in groups.items():
        member_set = set(members)
        for m_id in members:
            for d in graph.get(m_id, []):
                if d in member_set and d != m_id:
                    errors.append(
                        f"Group {g}: {m_id} depends on {d} but both are in the same parallel group"
                    )

    # 5. Task coverage
    coverage: Dict[str, object] = {}
    if os.path.isfile(original_path):
        original_tasks = count_tasks_in_original(read_text(original_path))
        stage_tasks_total = 0
        per_stage: Dict[str, int] = {}
        for sid, fpath in stage_files.items():
            c = count_tasks_in_stage(read_text(fpath))
            per_stage[sid] = c
            stage_tasks_total += c
        coverage = {
            "original_tasks": original_tasks,
            "stage_tasks_total": stage_tasks_total,
            "per_stage": per_stage,
            "ok": stage_tasks_total >= original_tasks if original_tasks > 0 else True,
        }
        if original_tasks > 0 and stage_tasks_total < original_tasks:
            errors.append(
                f"Task coverage below original: stages have {stage_tasks_total} "
                f"vs original {original_tasks}"
            )
        coverage["original_hash"] = sha256_file(original_path)
    else:
        coverage["note"] = f"Original plan not found at {original_path}; skipping coverage check"

    valid = not errors
    print_json(
        {
            "valid": valid,
            "errors": errors,
            "stages": stages,
            "coverage": coverage,
        },
        0 if valid else 1,
    )


# ---------- verify-baseline ----------

def cmd_verify_baseline(directory: str, base_name: str, stages_arg: str, out_path: Optional[str] = None) -> None:
    if not os.path.isdir(directory):
        print_json({"error": f"Directory not found: {directory}"}, 1)

    stages: Dict[str, object] = {}
    for stage in _stage_ids(stages_arg, directory, base_name):
        stage_path = os.path.join(directory, stage_filename(base_name, stage))
        stages[stage] = {
            "stg_sha": sha256_file(stage_path),
            "review_files": _reviews_for_stage(directory, base_name, stage),
        }

    snapshot = {"base_name": base_name, "stages": stages}
    if out_path:
        # Written by the tool so the encoding never depends on the shell's redirect.
        with open(out_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(snapshot, f, ensure_ascii=False, sort_keys=True, indent=2)
            f.write("\n")
    print_json(snapshot, 0)


# ---------- verify-record ----------

RESULT_VALUES = ("clean", "converged", "stagnation", "limit", "escalated")


def cmd_verify_record(directory: str, base_name: str, results_arg: str, ledger_path: str, mode: str) -> None:
    """Upsert the verify ledger from plan-iterative-revision's batch JSON."""
    if mode not in ("full-cycle", "audit-only"):
        raise ValueError("--mode must be full-cycle or audit-only")
    raw = sys.stdin.read() if results_arg == "-" else read_text(results_arg)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid results JSON: {exc}") from exc
    parts = payload.get("parts") if isinstance(payload, dict) else None
    if not isinstance(parts, dict):
        raise ValueError("Results JSON must be an object with a 'parts' object")

    ledger: Dict[str, object] = {"base_name": base_name, "verify_mode": mode, "stages": {}}
    if os.path.isfile(ledger_path):
        ledger = _load_json(ledger_path)
        if not isinstance(ledger.get("stages"), dict):
            ledger["stages"] = {}
    stages = ledger["stages"]  # type: ignore[index]
    errors: List[str] = []
    for raw_id, entry in parts.items():
        try:
            stage = normalize_part_id(raw_id)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if not isinstance(entry, dict):
            errors.append(f"{stage}: part entry must be an object")
            continue
        previous = stages.get(stage) if isinstance(stages.get(stage), dict) else {}  # type: ignore[union-attr]
        attempts = int(previous.get("attempts") or 0) + 1  # type: ignore[union-attr]
        result = entry.get("result")
        error = entry.get("error")
        if result not in RESULT_VALUES:
            error = error or f"invalid result: {result!r}"
            result = None
        stages[stage] = {  # type: ignore[index]
            "verify_mode": mode,
            "result": result,
            "iterations": entry.get("iterations"),
            "remaining_issues": entry.get("remaining_issues"),
            "stop_reason": entry.get("stop_reason"),
            "escalated": entry.get("escalated", []),
            "attempts": attempts,
            "error": error,
        }
    with open(ledger_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(ledger, f, ensure_ascii=False, sort_keys=True, indent=2)
        f.write("\n")
    print_json({"ledger": ledger_path, "recorded": sorted(parts.keys()), "errors": errors}, 0 if not errors else 1)


# ---------- verify-status ----------

def cmd_verify_status(
    directory: str,
    base_name: str,
    baseline_path: str,
    ledger_path: str,
    validator_path: str,
    stages_arg: str,
) -> None:
    if not os.path.isdir(directory):
        print_json({"ok": False, "error": f"Directory not found: {directory}"}, 1)
    if not validator_path:
        raise ValueError("Missing --validator")

    baseline = _load_json(baseline_path)
    ledger = _load_json(ledger_path)
    baseline_stages = baseline.get("stages", {})
    ledger_stages = ledger.get("stages", {})
    if not isinstance(baseline_stages, dict):
        raise ValueError("Baseline field 'stages' must be an object")
    if not isinstance(ledger_stages, dict):
        raise ValueError("Ledger field 'stages' must be an object")

    stages: Dict[str, object] = {}
    for stage in _status_stage_ids(stages_arg, directory, base_name, baseline_stages):
        baseline_entry = baseline_stages[stage]
        if not isinstance(baseline_entry, dict):
            raise ValueError(f"Baseline entry must be an object: {stage}")
        baseline_reviews = set(baseline_entry.get("review_files", []))
        current_reviews = _current_reviews(directory, base_name, stage)
        new_reviews = [name for name in current_reviews if name not in baseline_reviews]
        stage_path = os.path.join(directory, stage_filename(base_name, stage))
        stg_sha_changed = sha256_file(stage_path) != baseline_entry.get("stg_sha")

        ledger_entry = ledger_stages.get(stage)
        result = None
        verify_mode = None
        iterations = None
        remaining_issues = None
        if isinstance(ledger_entry, dict):
            result = ledger_entry.get("result")
            verify_mode = ledger_entry.get("verify_mode", ledger.get("verify_mode"))
            iterations = ledger_entry.get("iterations")
            remaining_issues = ledger_entry.get("remaining_issues")

        reviews_validated = False
        if not isinstance(ledger_entry, dict) or result is None:
            # No entry, or a recorded failure without a result: the part was not verified.
            verdict = "missing"
        elif result == "clean":
            verdict = "satisfied" if not new_reviews and not stg_sha_changed else "inconsistent"
        elif result == "converged":
            reviews_validated = bool(new_reviews) and all(
                _validate_review(validator_path, os.path.join(directory, name))
                for name in new_reviews
            )
            if (
                reviews_validated
                and stg_sha_changed
                and verify_mode == "full-cycle"
                and remaining_issues == 0
            ):
                verdict = "satisfied"
            elif reviews_validated and (
                verify_mode == "audit-only"
                or isinstance(remaining_issues, int) and remaining_issues > 0
            ):
                verdict = "satisfied_with_warning"
            else:
                verdict = "inconsistent"
        elif result in ("stagnation", "limit", "escalated"):
            reviews_validated = bool(new_reviews) and all(
                _validate_review(validator_path, os.path.join(directory, name))
                for name in new_reviews
            )
            verdict = "satisfied_with_warning" if reviews_validated else "inconsistent"
        else:
            verdict = "inconsistent"

        stages[stage] = {
            "verdict": verdict,
            "result": result,
            "stop_reason": ledger_entry.get("stop_reason") if isinstance(ledger_entry, dict) else None,
            "verify_mode": verify_mode,
            "new_reviews": new_reviews,
            "reviews_validated": reviews_validated,
            "stg_sha_changed": stg_sha_changed,
            "iterations": iterations,
            "remaining_issues": remaining_issues,
        }

    ok = all(
        isinstance(item, dict) and item.get("verdict") in ("satisfied", "satisfied_with_warning")
        for item in stages.values()
    )
    print_json({"ok": ok, "stages": stages}, 0 if ok else 1)


# ---------- hash ----------

def cmd_hash(path: str) -> None:
    print(sha256_file(path))


# ---------- main ----------

USAGE = """Usage:
  splitter_tool.py preflight <dir> <base_name>
  splitter_tool.py part-id <N>
  splitter_tool.py stage-name <base> <N|id>
  splitter_tool.py detect-lang <file>
  splitter_tool.py validate-stage <file>
  splitter_tool.py validate-roadmap <file>
  splitter_tool.py validate-all <dir> <base_name>
  splitter_tool.py verify-baseline <dir> <base_name> [--stages all|a[,b...]] [--out <file>]
  splitter_tool.py verify-record <dir> <base_name> --results <file|-> --ledger <file> [--mode full-cycle|audit-only]
  splitter_tool.py verify-status <dir> <base_name> --baseline <file> --ledger <file> --validator <file> [--stages all|a[,b...]]
  splitter_tool.py hash <file>
"""


def main(argv: List[str]) -> None:
    if len(argv) < 2:
        sys.stderr.write(USAGE)
        sys.exit(2)
    cmd = argv[1]
    args = argv[2:]
    try:
        if cmd == "preflight" and len(args) == 2:
            cmd_preflight(args[0], args[1])
        elif cmd == "stage-name" and len(args) == 2:
            cmd_stage_name(args[0], args[1])
        elif cmd == "part-id" and len(args) == 1:
            cmd_part_id(args[0])
        elif cmd == "detect-lang" and len(args) == 1:
            cmd_detect_lang(args[0])
        elif cmd == "validate-stage" and len(args) == 1:
            cmd_validate_stage(args[0])
        elif cmd == "validate-roadmap" and len(args) == 1:
            cmd_validate_roadmap(args[0])
        elif cmd == "validate-all" and len(args) == 2:
            cmd_validate_all(args[0], args[1])
        elif cmd == "verify-baseline" and len(args) >= 2:
            stages_arg = _get_flag(args[2:], "--stages", "all") or "all"
            cmd_verify_baseline(args[0], args[1], stages_arg, _get_flag(args[2:], "--out"))
        elif cmd == "verify-record" and len(args) >= 2:
            results_arg = _get_flag(args[2:], "--results")
            ledger_path = _get_flag(args[2:], "--ledger")
            mode = _get_flag(args[2:], "--mode", "full-cycle") or "full-cycle"
            if not results_arg or not ledger_path:
                raise ValueError("verify-record requires --results and --ledger")
            cmd_verify_record(args[0], args[1], results_arg, ledger_path, mode)
        elif cmd == "verify-status" and len(args) >= 2:
            baseline_path = _get_flag(args[2:], "--baseline")
            ledger_path = _get_flag(args[2:], "--ledger")
            validator_path = _get_flag(args[2:], "--validator")
            stages_arg = _get_flag(args[2:], "--stages", "all") or "all"
            if not baseline_path or not ledger_path or not validator_path:
                raise ValueError("verify-status requires --baseline, --ledger, and --validator")
            cmd_verify_status(args[0], args[1], baseline_path, ledger_path, validator_path, stages_arg)
        elif cmd == "hash" and len(args) == 1:
            cmd_hash(args[0])
        else:
            sys.stderr.write(USAGE)
            sys.exit(2)
    except Exception as e:
        sys.stderr.write(f"Error: {e}\n")
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv)
