#!/usr/bin/env python3
"""
splitter_tool.py — utility for the plan-splitter skill.

Subcommands:
  preflight <dir> <base_name>
      Check write access to <dir> and list any existing stg-files. Returns JSON:
      {"writable": bool, "existing": ["<file>", ...], "warning": "<text>"|null}.
      Existing files are a WARNING, not an error — the agent decides what to do.

  stage-name <base> <N>
      Print '<base>-stg<NN>.md' (NN = zero-padded N, e.g. 1 -> "stg01").

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
      Cross-validation of the whole set: roadmap + all stages.
      Checks: file existence, DAG (no cycles), depends->exist, parallel-group consistency,
      task-coverage (sum of stage tasks >= original-plan tasks), original-plan hash.
      Print JSON with detailed results. Exit 0 on success, 1 on failure.

  verify-baseline <dir> <base_name> [--stages all|stgNN[,stgNN...]]
      Snapshot selected stage SHA-256 values and pre-existing review files.

  verify-status <dir> <base_name> --baseline <file> --ledger <file> --validator <file>
      Verify ledger entries against current stage/review artifacts.

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


STAGE_FILE_RE = re.compile(r"^(?P<base>.+)-stg(?P<n>\d{2,})(?P<suffix>-roadmap)?\.md$", re.IGNORECASE)
REVIEW_FILE_RE = re.compile(r"^(?P<base>.+)-stg(?P<stg>\d{2})-review-(?P<n>\d+)\.md$", re.IGNORECASE)
CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")
LETTER_RE = re.compile(r"[A-Za-z\u0400-\u04FF]")

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
    print(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2))
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
    letters = LETTER_RE.findall(text)
    if not letters:
        return 0.0
    cyr = sum(1 for ch in letters if CYRILLIC_RE.match(ch))
    return cyr / len(letters)


def detect_lang_for_text(text: str) -> Tuple[str, float]:
    ratio = cyrillic_ratio(text)
    lang = "ru" if ratio > 0.05 else "en"
    return lang, ratio


def stage_filename(base: str, n: int) -> str:
    if n < 0:
        raise ValueError("Stage number must be non-negative")
    return f"{base}-stg{n:02d}.md"


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


def _stage_ids(stages_arg: str, directory: str, base: str) -> List[str]:
    if stages_arg == "all":
        stage_ids: List[str] = []
        for n in range(1, 100):
            if os.path.isfile(os.path.join(directory, stage_filename(base, n))):
                stage_ids.append(f"stg{n:02d}")
        return stage_ids

    stage_ids = []
    for raw_stage in stages_arg.split(","):
        stage = raw_stage.strip().lower()
        if not re.match(r"^stg\d{2}$", stage):
            raise ValueError(f"Invalid stage id: {raw_stage}")
        path = os.path.join(directory, f"{base}-{stage}.md")
        if not os.path.isfile(path):
            raise ValueError(f"Stage file not found: {path}")
        stage_ids.append(stage)
    return sorted(stage_ids)


def _reviews_for_stage(directory: str, base: str, stage: str) -> List[str]:
    reviews: List[Tuple[int, str]] = []
    stage_number = stage[3:]
    for name in os.listdir(directory):
        match = REVIEW_FILE_RE.match(name)
        if not match:
            continue
        if match.group("base") == base and match.group("stg") == stage_number:
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

    # Scan for existing stg-files.
    existing: List[str] = []
    for name in os.listdir(directory):
        m = STAGE_FILE_RE.match(name)
        if m and m.group("base") == base_name:
            existing.append(name)
    existing.sort()
    result["existing"] = existing
    if existing:
        result["warning"] = (
            f"Found {len(existing)} existing stg-file(s) for base '{base_name}'. "
            "Ask the user before overwriting."
        )
    print_json(result, 0)


# ---------- stage-name ----------

def cmd_stage_name(base: str, n_str: str) -> None:
    n = int(n_str)
    print(stage_filename(base, n))


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
            stage_id = cells[0].strip()
            if not re.match(r"^stg\d{2,}$", stage_id, re.IGNORECASE):
                continue
            depends_raw = cells[2].strip()
            depends: List[str] = []
            if depends_raw and depends_raw not in ("—", "-", ""):
                depends = [d.strip() for d in re.split(r"[,\s]+", depends_raw) if d.strip()]
            rows.append({
                "id": stage_id.lower(),
                "title": cells[1].strip(),
                "depends": ",".join(depends),
                "group": cells[3].strip(),
                "weight": cells[4].strip(),
            })
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
    stage_ids = {s["id"] for s in stages}
    for s in stages:
        deps = [d for d in s["depends"].split(",") if d]
        for d in deps:
            if d.lower() not in stage_ids:
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


def count_tasks_in_stage(text: str) -> int:
    """Count tasks in a stage file's '## Задачи' / '## Tasks' section."""
    # Find the section header.
    m = re.search(r"^##\s+(?:Задачи|Tasks)\s*$", text, re.MULTILINE)
    if not m:
        return 0
    start = m.end()
    next_sec = re.search(r"^##\s+", text[start:], re.MULTILINE)
    section = text[start: start + next_sec.start()] if next_sec else text[start:]
    # Count numbered list items "1. ", "2. " etc.
    return len(re.findall(r"^\s*\d+\.\s+\S", section, re.MULTILINE))


def count_tasks_in_original(text: str) -> int:
    """Coarse task estimate: numbered list items OR Task/Задача headings, whichever is larger."""
    numbered = len(re.findall(r"^\s*\d+\.\s+\S", text, re.MULTILINE))
    headings = len(re.findall(
        r"^#{2,4}\s*(?:Task|Задача)\s+\S+?:", text, re.MULTILINE))
    return max(numbered, headings)


def cmd_validate_all(directory: str, base_name: str) -> None:
    if not os.path.isdir(directory):
        print_json({"valid": False, "error": f"Directory not found: {directory}"}, 1)

    roadmap_path = os.path.join(directory, f"{base_name}-stg00-roadmap.md")
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
    if not stages:
        errors.append("Roadmap dependency table is empty")
        print_json({"valid": False, "errors": errors}, 1)

    # 1. Files on disk + validate-stage per file
    stage_ids = {s["id"] for s in stages}
    stage_files: Dict[str, str] = {}
    for s in stages:
        # Extract numeric N from id like "stg03"
        m = re.match(r"^stg(\d+)$", s["id"], re.IGNORECASE)
        if not m:
            errors.append(f"Invalid stage id: {s['id']}")
            continue
        n = int(m.group(1))
        fname = stage_filename(base_name, n)
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
    graph: Dict[str, List[str]] = {s["id"]: [d.lower() for d in s["depends"].split(",") if d] for s in stages}
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

def cmd_verify_baseline(directory: str, base_name: str, stages_arg: str) -> None:
    if not os.path.isdir(directory):
        print_json({"error": f"Directory not found: {directory}"}, 1)

    stages: Dict[str, object] = {}
    for stage in _stage_ids(stages_arg, directory, base_name):
        stage_path = os.path.join(directory, f"{base_name}-{stage}.md")
        stages[stage] = {
            "stg_sha": sha256_file(stage_path),
            "review_files": _reviews_for_stage(directory, base_name, stage),
        }

    print_json({"base_name": base_name, "stages": stages}, 0)


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
        stage_path = os.path.join(directory, f"{base_name}-{stage}.md")
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
        if not isinstance(ledger_entry, dict):
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
  splitter_tool.py stage-name <base> <N>
  splitter_tool.py detect-lang <file>
  splitter_tool.py validate-stage <file>
  splitter_tool.py validate-roadmap <file>
  splitter_tool.py validate-all <dir> <base_name>
    splitter_tool.py verify-baseline <dir> <base_name> [--stages all|stgNN[,stgNN...]]
    splitter_tool.py verify-status <dir> <base_name> --baseline <file> --ledger <file> --validator <file> [--stages all|stgNN[,stgNN...]]
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
            cmd_verify_baseline(args[0], args[1], stages_arg)
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
