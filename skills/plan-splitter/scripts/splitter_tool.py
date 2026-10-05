#!/usr/bin/env python3
"""
splitter_tool.py — utility for the plan-splitter skill.

Subcommands:
  preflight <dir> <base_name>
      Check write access to <dir> and list existing split artifacts for this base
      (roadmap, part files, review/completion files, verify JSONs). Returns JSON:
      {"writable": bool, "existing": ["<file>", ...], "warning": "<text>"|null}.
      Existing files are a WARNING, not an error: the agent decides what to do.
      A plan <dir>/<base_name>.md that still carries plan-writing's writing marker is exit 1 with
      "error": "plan-incomplete: ..." (the plan is not split).

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

  validate-all <dir> <base_name> [--skip-task-bodies]
      Cross-validation of the whole set: '<base>-roadmap.md' + all '<base>-<id>.md' parts.
      Checks: file existence, DAG (no cycles), depends->exist, parallel-group consistency,
      task-coverage (sum of part tasks == original-plan tasks), original-plan hash,
      task bodies (task_bodies: every plan task body in exactly one part, by the shared parser's
      sha1; skipped by --skip-task-bodies, e.g. after a full-cycle verification edited the parts),
      task lines (every '**External:**', '**Size:**' and '**Structural event:**' line of the original, outside
      code fences, appears verbatim in some part).
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

  gate <plan> [--keep-tasks 20] [--keep-bytes 100000] [--split-tasks 40] [--split-bytes 150000] [--modules 3]
      Numeric split gate over brainstorm_tool.parse_plan_tasks: factors task_count, plan_bytes, modules
      (distinct Files folders two levels deep), dependency_shape (linear | groups by Preconditions refs);
      verdict keep | split | borderline with reasons and thresholds, and silent_verdict (borderline decided by the
      budget: keep within --split-tasks and --split-bytes, else split). Exit 1 no-tasks; exit 2 for an
      unreadable plan, a bad flag value or plan-brainstorming not installed alongside.
      Errors of gate, split-write and validate-all print {"ok": false, "errors": [...]}.

  split-write <plan> --parts <parts.json> [--lang ru|en] [--force]
      Write <base>-roadmap.md and <base>-<id>.md from assets/*-template.<lang>.md and the model's
      boundaries (parts.json: optional title/overview; per part id, title, depends, group, weight,
      goal, inputs, outputs, notes, optional criteria, tasks). Task texts are copied byte for byte
      (heading to the next task); every check runs before the first write. Exit 1 for boundary errors
      or existing files without --force (nothing written), exit 2 for bad input. The plan is not changed.

Stdlib only. Python 3.8+.
"""
from __future__ import annotations

import datetime
import functools
import hashlib
import importlib.util
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

# Numeric split gate (gate / gate_verdict). split_tasks and split_bytes are plan-brainstorming's SIZE_BUDGET,
# the plan-oversized threshold of plan-check; plan-writing/tests SizeBudgetContractTest holds them equal.
GATE_THRESHOLDS = {"keep_tasks": 20, "keep_bytes": 100000, "split_tasks": 40, "split_bytes": 150000, "modules": 3}
GATE_FLAGS = (("--keep-tasks", "keep_tasks"), ("--keep-bytes", "keep_bytes"), ("--split-tasks", "split_tasks"),
              ("--split-bytes", "split_bytes"), ("--modules", "modules"))
BRAINSTORM_MISSING = "plan-brainstorming not installed alongside"


class SplitterError(Exception):
    """Error of gate, split-write and validate-all, printed as JSON: code 2 = input, 1 = contract.
    `details` go into the JSON; details["errors"] replaces the one-message list."""

    def __init__(self, message: str, code: int = 1, **details: object) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


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

    # A plan plan-writing has not finished is not split (spec 3 of plan-refactoring-02): the shared parser reports
    # its writing marker as `incomplete`. Without plan-brainstorming or a readable plan nothing is checked.
    plan = os.path.join(directory, base_name + ".md")
    parse = getattr(_load_brainstorm_tool(), "parse_plan_tasks", None)
    if parse is not None and os.path.isfile(plan):
        try:
            incomplete = bool(parse(read_text(plan)).get("incomplete"))
        except (OSError, UnicodeDecodeError):
            incomplete = False
        if incomplete:
            result["error"] = (f"plan-incomplete: {plan}: the plan carries plan-writing's writing marker "
                               "'> Writing: in progress'; finish it with plan-writing first")
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
    """Tasks of a part: its `### Task N:` bodies by brainstorm_tool.parse_plan_tasks when it has them (a part
    from split-write lists each task twice: the numbered list and the body); otherwise the top-level
    numbered items in the '## Задачи' / '## Tasks' section (code fences ignored)."""
    parse = getattr(_load_brainstorm_tool(), "parse_plan_tasks", None)
    if parse is not None:
        parsed = parse(text)
        if parsed["tasks"] and not parsed["malformed"]:
            return len(parsed["tasks"])
    m = re.search(r"^##\s+(?:Задачи|Tasks)\s*$", text, re.MULTILINE)
    if not m:
        return 0
    start = m.end()
    next_sec = re.search(r"^##\s+", text[start:], re.MULTILINE)
    section = text[start: start + next_sec.start()] if next_sec else text[start:]
    return sum(1 for line in _lines_outside_fences(section) if re.match(r"^\d+\.\s+\S", line))


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


def _brainstorm_required():
    """brainstorm_tool with parse_plan_tasks, else SplitterError exit 2: gate, split-write and validate-all
    cannot cut or check a plan without the shared task parser."""
    module = _load_brainstorm_tool()
    if module is None or not hasattr(module, "parse_plan_tasks"):
        raise SplitterError(BRAINSTORM_MISSING, 2)
    return module


def _read_plan(path: str) -> str:
    try:
        return read_text(path)
    except (OSError, UnicodeDecodeError) as exc:
        raise SplitterError(f"plan-unreadable: {path}: {exc}", 2) from exc


def _module_of(path: str) -> str:
    """Module of a Files path: its folder, at most two levels deep ('.' for a file at the root)."""
    folders = path.replace("\\", "/").strip("/").split("/")[:-1]
    return "/".join(folders[:2]) or "."


def _dependency_shape(tasks: List[Dict[str, object]]) -> str:
    """'linear' when the Preconditions references (refs) branch nowhere: no task has two or more
    incoming or outgoing edges; otherwise 'groups'. References to unknown tasks are ignored."""
    ids = {task["id"] for task in tasks}
    incoming: Dict[str, int] = {}
    outgoing: Dict[str, int] = {}
    for task in tasks:
        for ref in task["refs"]:
            if ref in ids and ref != task["id"]:
                outgoing[ref] = outgoing.get(ref, 0) + 1
                incoming[task["id"]] = incoming.get(task["id"], 0) + 1
    return "groups" if any(n >= 2 for n in list(incoming.values()) + list(outgoing.values())) else "linear"


def _gate_reason(name: str, value: int, keep: int, split: int) -> str:
    if value <= keep:
        return f"{name} {value} <= {keep}"
    if value > split:
        return f"{name} {value} > {split}"
    return f"{name} {value} in ({keep}, {split}]"


def gate_verdict(plan_path: str, thresholds: Optional[Dict[str, int]] = None) -> Dict[str, object]:
    """Numeric split gate over brainstorm_tool.parse_plan_tasks. keep: <= keep_tasks tasks, <= keep_bytes
    bytes and <= modules modules; split: (> split_tasks tasks or > split_bytes bytes) and (> modules modules
    or dependency_shape 'groups'); otherwise borderline. silent_verdict decides borderline without a confirmation
    channel: keep within split_tasks and split_bytes, else split. Pure (no printing, no exit): plan-chain-runner
    calls it in-process. Raises SplitterError: no-tasks (1), plan-unreadable or no parser (2)."""
    limits = dict(GATE_THRESHOLDS, **(thresholds or {}))
    parsed = _brainstorm_required().parse_plan_tasks(_read_plan(plan_path))
    tasks = parsed["tasks"]
    if not tasks:
        raise SplitterError(f"no-tasks: {plan_path}", 1)
    factors = {
        "task_count": len(tasks),
        "plan_bytes": os.path.getsize(plan_path),
        "modules": len({_module_of(entry["path"]) for task in tasks for entry in task["files"]}),
        "dependency_shape": _dependency_shape(tasks),
    }
    count, size, modules = factors["task_count"], factors["plan_bytes"], factors["modules"]
    if count <= limits["keep_tasks"] and size <= limits["keep_bytes"] and modules <= limits["modules"]:
        verdict = "keep"
    elif ((count > limits["split_tasks"] or size > limits["split_bytes"])
          and (modules > limits["modules"] or factors["dependency_shape"] == "groups")):
        verdict = "split"
    else:
        verdict = "borderline"
    # Without a confirmation channel nobody decides a borderline plan: the size budget does (spec plan-refactoring-03).
    within = count <= limits["split_tasks"] and size <= limits["split_bytes"]
    silent = verdict if verdict != "borderline" else ("keep" if within else "split")
    reasons = [
        _gate_reason("task_count", count, limits["keep_tasks"], limits["split_tasks"]),
        _gate_reason("plan_bytes", size, limits["keep_bytes"], limits["split_bytes"]),
        f"modules {modules} {'>' if modules > limits['modules'] else '<='} {limits['modules']}",
        f"dependency_shape {factors['dependency_shape']}",
    ]
    return {"ok": True, "plan": plan_path, "verdict": verdict, "silent_verdict": silent, "factors": factors,
            "thresholds": limits,
            "reasons": reasons,
            "warnings": [f"malformed-task-heading: line {item['line']}" for item in parsed["malformed"]]}


def check_parts(tasks: List[Dict[str, object]], parts: List[Dict[str, object]]) -> Tuple[List[str], List[str]]:
    """Errors and warnings of the model's part boundaries (parts.json) against the plan's tasks. Every
    check runs before split-write writes anything; one error means no file is written."""
    errors: List[str] = []
    ids = [str(part["id"]) for part in parts]
    expected = [part_id(n) for n in range(1, len(parts) + 1)]
    if ids != expected:
        errors.append(f"part-ids-not-sequential: {', '.join(ids)} (expected {', '.join(expected)})")
    known = {task["id"] for task in tasks}
    owner: Dict[str, str] = {}
    duplicated: List[str] = []
    unknown: List[str] = []
    for part in parts:
        for task_id in part["tasks"]:
            if task_id not in known:
                unknown.append(task_id)
            elif task_id in owner:
                duplicated.append(task_id)
            else:
                owner[task_id] = str(part["id"])
    unassigned = [task["id"] for task in tasks if task["id"] not in owner]
    for code, found in (("tasks-unassigned", unassigned), ("tasks-duplicated", duplicated),
                        ("tasks-unknown", unknown)):
        if found:
            errors.append(f"{code}: {', '.join(found)}")
    graph_errors, warnings = _check_part_graph(tasks, parts, owner)
    return errors + graph_errors, warnings


def _ancestors(graph: Dict[str, List[str]], node: str) -> Set[str]:
    """Every part `node` depends on, directly or through other parts (cycles tolerated)."""
    seen: Set[str] = set()
    stack = list(graph.get(node, []))
    while stack:
        dep = stack.pop()
        if dep not in seen:
            seen.add(dep)
            stack.extend(graph.get(dep, []))
    return seen


def _check_part_graph(tasks: List[Dict[str, object]], parts: List[Dict[str, object]],
                      owner: Dict[str, str]) -> Tuple[List[str], List[str]]:
    """Part dependencies: known, acyclic, never in the part's own parallel group. A Preconditions reference
    never points into a later part, nor into a part the referring one does not depend on (directly or
    through other parts). Task N.M in another part than Task N is only a warning."""
    errors: List[str] = []
    graph = {str(part["id"]): [str(dep) for dep in part["depends"]] for part in parts}
    group = {str(part["id"]): part["group"] for part in parts}
    unknown = [f"{pid} -> {dep}" for pid, deps in graph.items() for dep in deps if dep not in graph]
    if unknown:
        errors.append("unknown-dependency: " + ", ".join(unknown))
    cycle = has_cycle(graph)
    if cycle:
        errors.append("dependency-cycle: " + " -> ".join(cycle))
    same = [f"{pid} and {dep} in group {group[pid]}" for pid, deps in graph.items() for dep in deps
            if group.get(dep) == group[pid]]
    if same:
        errors.append("group-conflict: " + ", ".join(same))
    position = {pid: index for index, pid in enumerate(graph)}
    late: List[str] = []
    missing: List[str] = []
    for task in tasks:
        here = owner.get(task["id"])
        for ref in task["refs"]:
            there = owner.get(ref)
            if here is None or there is None or there == here:
                continue
            link = f"Task {task['id']} ({here}) -> Task {ref} ({there})"
            if position[there] > position[here]:
                late.append(link)
            elif there not in _ancestors(graph, here):
                missing.append(link)
    if late:
        errors.append("dependency-order: " + ", ".join(late))
    if missing:
        errors.append("missing-depends: " + ", ".join(missing))
    warnings = []
    for task in tasks:
        base = str(task["id"]).split(".")[0]
        if base != task["id"] and base in owner and task["id"] in owner and owner[base] != owner[task["id"]]:
            warnings.append(f"subtask-separated: Task {task['id']} ({owner[task['id']]}) and Task {base} ({owner[base]})")
    return errors, warnings


# ---------- split-write: templates ----------

TEMPLATE_ITEM_RE = re.compile(r"<!-- item:(?P<name>[a-z-]+) -->\n(?P<body>.*?)\n<!-- /item -->\n?", re.DOTALL)
PLACEHOLDER_RE = re.compile(r"\{\{([A-Z0-9_]+)\}\}")
ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")


def _split_items(text: str) -> Tuple[str, Dict[str, str]]:
    """A template without its `<!-- item:name -->` blocks (the one-line patterns split-write repeats),
    and those blocks by name."""
    items = {match.group("name"): match.group("body") for match in TEMPLATE_ITEM_RE.finditer(text)}
    return TEMPLATE_ITEM_RE.sub("", text).rstrip("\n") + "\n", items


def _template(name: str, lang: str) -> Tuple[str, Dict[str, str]]:
    return _split_items(read_text(os.path.join(ASSETS_DIR, f"{name}.{lang}.md")))


def _fill(template: str, values: Dict[str, str]) -> str:
    """`{{NAME}}` replaced in one pass: inserted text (task bodies) is never scanned again."""
    return PLACEHOLDER_RE.sub(lambda match: values[match.group(1)], template)


H1_RE = re.compile(r"^#\s+(.+?)\s*$")
GOAL_RE = re.compile(r"^\*\*Goal:\*\*\s*(\S.*?)\s*$")


def _task_spans(lines: List[str], tasks: List[Dict[str, object]]) -> Dict[str, str]:
    """Each task's text as split-write copies it: from its heading to the line before the next task (the
    last task: to the end of the plan), trailing blank lines dropped. That is the parser's body plus the
    lines the parser leaves outside every task (e.g. a heading inside a nested fence it took for a section
    end): the body stays byte for byte, the shared parser finds the same task (same sha1) in the part,
    and nothing of the plan is lost."""
    spans: Dict[str, str] = {}
    for index, task in enumerate(tasks):
        end = tasks[index + 1]["line_start"] - 1 if index + 1 < len(tasks) else len(lines)
        block = lines[task["line_start"] - 1:end]
        while block and not block[-1].strip():
            block.pop()
        spans[task["id"]] = "\n".join(block)
    return spans


def _plan_header(lines: List[str], first_task: int) -> str:
    """Plan lines before the first task, verbatim, without the H1 title, a closing `---` and edge blank lines."""
    head = list(lines[:first_task - 1])
    title = next((index for index, line in enumerate(head) if H1_RE.match(line)), None)
    if title is not None:
        del head[title]
    while head and (not head[-1].strip() or head[-1].strip() == "---"):
        head.pop()
    while head and not head[0].strip():
        head.pop(0)
    return "\n".join(head)


DONE_WHEN_RE = re.compile(r"^\*\*Done when:\*\*\s*(\S.*?)\s*$")
POSTCONDITIONS_RE = re.compile(r"^\*\*Postconditions:\*\*")


def _done_state(text: str) -> Optional[str]:
    """The task's done-state in one line: its **Done when:** text, else its Postconditions items joined
    with '; ' (code fences ignored); None when it has neither."""
    lines = [line.strip() for line in _lines_outside_fences(text)]
    for line in lines:
        match = DONE_WHEN_RE.match(line)
        if match:
            return match.group(1)
    items: List[str] = []
    inside = False
    for line in lines:
        if POSTCONDITIONS_RE.match(line):
            inside = True
        elif inside and line.startswith(("- ", "* ")) and not line.startswith("- [ ]"):
            items.append(line[2:].strip())
        elif inside and line:
            break
    return "; ".join(items) or None


def _lines_outside_tasks(lines: List[str], tasks: List[Dict[str, object]]) -> List[str]:
    """Ranges of the non-blank plan lines after the first task that belong to no parsed task body;
    split-write copies them with the task before them and names them in a warning."""
    covered: Set[int] = set()
    for task in tasks:
        covered.update(range(task["line_start"], task["line_end"] + 1))
    groups: List[List[int]] = []
    for number in range(tasks[0]["line_start"], len(lines) + 1):
        if number in covered:
            continue
        if groups and groups[-1][-1] == number - 1:
            groups[-1].append(number)
        else:
            groups.append([number])
    ranges: List[str] = []
    for group in groups:
        filled = [number for number in group if lines[number - 1].strip()]
        if filled:
            ranges.append(str(filled[0]) if filled[0] == filled[-1] else f"{filled[0]}-{filled[-1]}")
    return ranges


def _or_dash(value: object) -> str:
    return str(value or "").strip() or "—"


def _render_part(base: str, part: Dict[str, object], tasks: List[Dict[str, object]], spans: Dict[str, str],
                 header: str, blocks: List[str], lang: str) -> str:
    """One part from assets/stage-template.<lang>.md: the model's fields, the plan header and the task
    texts verbatim; criteria from parts.json, else one line per task from its done-state."""
    template, items = _template("stage-template", lang)
    texts = [spans[task["id"]] for task in tasks]
    task_list = [_fill(items["task"], {"N": str(number), "TASK_ID": task["id"], "TASK_TITLE": task["title"]})
                 for number, task in enumerate(tasks, start=1)]
    if part.get("criteria"):
        criteria = [_fill(items["criterion-text"], {"TEXT": line}) for line in part["criteria"]]
    else:
        criteria = []
        for task, text in zip(tasks, texts):
            state = _done_state(text)
            criteria.append(_fill(items["criterion"] if state else items["criterion-empty"],
                                  {"TASK_ID": task["id"], "TEXT": state or ""}))
    return _fill(template, {
        "ID": part["id"], "TITLE": part["title"], "BASE_NAME": base,
        "DEPENDS_ON_OR_DASH": ", ".join(part["depends"]) or "—", "BLOCKS_OR_DASH": ", ".join(blocks) or "—",
        "WEIGHT": part["weight"], "GOAL": _or_dash(part["goal"]), "INPUTS": _or_dash(part["inputs"]),
        "PLAN_HEADER": header or "—", "TASK_LIST": "\n".join(task_list), "TASK_BODIES": "\n\n".join(texts),
        "CRITERIA": "\n".join(criteria), "OUTPUTS": _or_dash(part["outputs"]), "NOTES": _or_dash(part["notes"]),
    })


def _render_roadmap(base: str, title: str, overview: str, parts: List[Dict[str, object]],
                    blocks: Dict[str, List[str]], lang: str) -> str:
    """The roadmap from assets/roadmap-template.<lang>.md: table, parallel groups, one Mermaid edge per
    dependency (no dependency at all: an edge from `plan` to each part, the diagram needs one) and one
    stage block per part with the part's goal as its summary."""
    template, items = _template("roadmap-template", lang)
    rows: List[str] = []
    sections: List[str] = []
    edges: List[str] = []
    groups: Dict[str, List[str]] = {}
    for part in parts:
        fields = {"ID": part["id"], "TITLE": part["title"], "DEPENDS": ", ".join(part["depends"]) or "—",
                  "GROUP": part["group"], "WEIGHT": part["weight"], "BASE_NAME": base,
                  "BLOCKS": ", ".join(blocks[part["id"]]) or "—", "SUMMARY": _or_dash(part["goal"])}
        rows.append(_fill(items["row"], fields))
        sections.append(_fill(items["stage"], fields))
        groups.setdefault(part["group"], []).append(part["id"])
        edges.extend(f"    {dep} --> {part['id']}" for dep in part["depends"])
    if not edges:
        edges = [f"    plan --> {part['id']}" for part in parts]
    return _fill(template, {
        "PLAN_TITLE": title, "BASE_NAME": base, "N": str(len(parts)), "OVERVIEW": _or_dash(overview),
        "ISO8601_UTC": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "TABLE_ROWS": "\n".join(rows), "MERMAID_EDGES": "\n".join(edges), "STAGE_SECTIONS": "\n\n".join(sections),
        "GROUP_LINES": "\n".join(_fill(items["group"], {"GROUP": name, "MEMBERS": ", ".join(members)})
                                 for name, members in groups.items()),
    })


def render_split(plan_path: str, payload: Dict[str, object], lang: str) -> Dict[str, object]:
    """split-write without writing: checks the plan and every boundary first, then renders the roadmap and
    the parts. A boundary error raises SplitterError (exit 1) with all errors in details["errors"]."""
    text = _read_plan(plan_path)
    module = _brainstorm_required()
    parsed = module.parse_plan_tasks(text)
    tasks = parsed["tasks"]
    if not tasks:
        raise SplitterError(f"no-tasks: {plan_path}", 1)
    broken = [f"malformed task heading at line {item['line']}" for item in parsed["malformed"]]
    broken += [f"Task {item['id']} repeated at lines {', '.join(map(str, item['lines']))}"
               for item in parsed["duplicates"]]
    if broken:
        raise SplitterError("plan-task-headings: " + "; ".join(broken), 1)
    parts = _parts_shape(payload)
    # parts.json may write an id as the plan does (`01`): compared as the shared parser writes it (F7).
    normalize = getattr(module, "normalize_task_id", lambda task_id: task_id)
    for part in parts:
        part["tasks"] = [normalize(task_id) for task_id in part["tasks"]]
    errors, warnings = check_parts(tasks, parts)
    if errors:
        raise SplitterError(errors[0], 1, errors=errors, warnings=warnings)
    lines = text.splitlines()
    loose = _lines_outside_tasks(lines, tasks)
    if loose:
        warnings.append("lines-outside-tasks: " + ", ".join(loose) + " (copied with the task before them)")
    base = os.path.splitext(os.path.basename(plan_path))[0]
    head_lines = lines[:tasks[0]["line_start"] - 1]
    header = _plan_header(lines, tasks[0]["line_start"])
    title = payload.get("title") or next((m.group(1) for m in map(H1_RE.match, head_lines) if m), base)
    overview = payload.get("overview") or next((m.group(1) for m in map(GOAL_RE.match, head_lines) if m), "")
    spans = _task_spans(lines, tasks)
    order = {task["id"]: index for index, task in enumerate(tasks)}
    by_id = {task["id"]: task for task in tasks}
    blocks = {part["id"]: [other["id"] for other in parts if part["id"] in other["depends"]] for part in parts}
    files = [(roadmap_filename(base), _render_roadmap(base, title, overview, parts, blocks, lang))]
    summary = []
    for part in parts:
        own = sorted((by_id[task_id] for task_id in part["tasks"]), key=lambda task: order[task["id"]])
        files.append((stage_filename(base, part["id"]),
                      _render_part(base, part, own, spans, header, blocks[part["id"]], lang)))
        summary.append({"id": part["id"], "tasks": len(own)})
    return {"base": base, "files": files, "parts": summary, "warnings": warnings}


PART_TEXT_KEYS = ("id", "title", "group", "weight", "goal", "inputs", "outputs", "notes")
PART_LIST_KEYS = ("depends", "tasks")


def _parts_shape(payload: Dict[str, object]) -> List[Dict[str, object]]:
    """The parts of parts.json after a shape check; every violation goes into one SplitterError (exit 2)."""
    parts = payload.get("parts")
    if not isinstance(parts, list) or not parts:
        raise SplitterError("parts-json-invalid: 'parts' must be a non-empty list", 2)
    problems = [f"'{key}' must be a string" for key in ("title", "overview")
                if key in payload and not isinstance(payload[key], str)]
    for index, part in enumerate(parts):
        where = f"parts[{index}]"
        if not isinstance(part, dict):
            problems.append(f"{where} must be an object")
            continue
        problems += [f"{where}.{key} must be a string" for key in PART_TEXT_KEYS if not isinstance(part.get(key), str)]
        for key in PART_LIST_KEYS + (("criteria",) if "criteria" in part else ()):
            value = part.get(key)
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                problems.append(f"{where}.{key} must be a list of strings")
        for key in ("title", "group", "weight"):
            value = part.get(key)
            if isinstance(value, str) and ("|" in value or "\n" in value or not value.strip()):
                problems.append(f"{where}.{key} must be one non-empty line without '|'")
    if problems:
        raise SplitterError("parts-json-invalid: " + "; ".join(problems), 2)
    return parts


def _load_parts(path: str) -> Dict[str, object]:
    try:
        return _load_json(path)
    except (ValueError, OSError, UnicodeDecodeError) as exc:
        raise SplitterError(f"parts-json-invalid: {exc}", 2) from exc


def count_tasks_in_original(text: str) -> int:
    """Tasks of a contract plan by brainstorm_tool.parse_plan_tasks (no malformed task heading);
    otherwise Task/Задача headings when the plan has them, else top-level numbered items outside fences."""
    parse = getattr(_load_brainstorm_tool(), "parse_plan_tasks", None)
    if parse is not None:
        parsed = parse(text)
        if parsed["tasks"] and not parsed["malformed"]:
            return len(parsed["tasks"])
    lines = _lines_outside_fences(text)
    headings = sum(1 for line in lines if re.match(r"^#{2,4}\s*(?:Task|Задача)\s+\S+?\s*(?:[:\-]|—|\.\s)", line))
    if headings:
        return headings
    return sum(1 for line in lines if re.match(r"^\d+\.\s+\S", line))


# Task lines that are task properties, not prose: copied into the parts character for character
# (`**Structural event:**`: spec 1 of plan-refactoring-02, checked by plan_tool.py plan-check).
TASK_LINE_RE = re.compile(r"^\s*\*\*(?:External|Size|Structural event):\*\*\s*\S")


def task_property_lines(text: str) -> List[str]:
    """`**External:**`, `**Size:**` and `**Structural event:**` task lines outside code fences, without indentation."""
    return [line.strip() for line in _lines_outside_fences(text) if TASK_LINE_RE.match(line)]


def task_bodies_check(original_text: str, stage_texts: Dict[str, str]) -> Optional[Dict[str, object]]:
    """Task bodies of the parts against the plan by the shared parser's sha1: every plan task exactly once.
    None when the plan has no contract tasks (such a plan keeps the previous checks only)."""
    module = _brainstorm_required()
    plan = module.parse_plan_tasks(original_text)
    if not plan["tasks"] or plan["malformed"]:
        return None
    wanted = {task["sha1"] for task in plan["tasks"]}
    seen: Dict[str, int] = {}
    foreign: List[str] = []
    for stage_id, text in stage_texts.items():
        for task in module.parse_plan_tasks(text)["tasks"]:
            if task["sha1"] in wanted:
                seen[task["sha1"]] = seen.get(task["sha1"], 0) + 1
            else:
                foreign.append(f"{stage_id}: Task {task['id']}")
    return {"plan": len(plan["tasks"]),
            "matched": sum(1 for task in plan["tasks"] if seen.get(task["sha1"]) == 1),
            "missing": [task["id"] for task in plan["tasks"] if not seen.get(task["sha1"])],
            "duplicated": [task["id"] for task in plan["tasks"] if seen.get(task["sha1"], 0) > 1],
            "foreign": foreign}


def cmd_validate_all(directory: str, base_name: str, skip_task_bodies: bool = False) -> None:
    _brainstorm_required()
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
            "ok": stage_tasks_total == original_tasks if original_tasks > 0 else True,
        }
        if original_tasks > 0 and stage_tasks_total != original_tasks:
            errors.append(
                f"Task coverage differs from original: stages have {stage_tasks_total} "
                f"vs original {original_tasks}"
            )
        coverage["original_hash"] = sha256_file(original_path)
    else:
        coverage["note"] = f"Original plan not found at {original_path}; skipping coverage check"

    # 6. Task lines (**External:**, **Size:**, **Structural event:**): each one of the original is copied verbatim into some part
    task_lines: Dict[str, object] = {}
    if os.path.isfile(original_path):
        part_lines: Set[str] = set()
        for fpath in stage_files.values():
            part_lines.update(line.strip() for line in read_text(fpath).splitlines())
        original_lines = task_property_lines(read_text(original_path))
        missing_lines = [line for line in original_lines if line not in part_lines]
        task_lines = {"original": len(original_lines), "missing": missing_lines}
        errors.extend(f"Task line not copied verbatim into any part: {line}" for line in missing_lines)

    # 7. Task bodies: every plan task body is in exactly one part, byte for byte (shared parser, sha1).
    # --skip-task-bodies: after a full-cycle deep verification, which edits the parts.
    task_bodies: Optional[Dict[str, object]] = None
    if os.path.isfile(original_path) and not skip_task_bodies:
        task_bodies = task_bodies_check(read_text(original_path),
                                        {sid: read_text(fpath) for sid, fpath in stage_files.items()})
        if task_bodies is not None:
            if task_bodies["missing"]:
                errors.append("Task bodies missing from the parts: " + ", ".join(task_bodies["missing"]))
            if task_bodies["duplicated"]:
                errors.append("Task bodies in more than one part: " + ", ".join(task_bodies["duplicated"]))
            if task_bodies["foreign"]:
                errors.append("Part tasks not in the plan: " + ", ".join(task_bodies["foreign"]))

    valid = not errors
    print_json(
        {
            "valid": valid,
            "errors": errors,
            "stages": stages,
            "coverage": coverage,
            "task_lines": task_lines,
            "task_bodies": task_bodies,
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


# ---------- gate ----------

def _flag_value(flags: List[str], flag: str) -> Optional[str]:
    """_get_flag with its ValueError ("Missing value for <flag>") turned into SplitterError exit 2, so the
    new commands answer a flag without a value with JSON and the input-error code."""
    try:
        return _get_flag(flags, flag)
    except ValueError as exc:
        raise SplitterError(str(exc), 2) from exc


def cmd_gate(plan_path: str, flags: List[str]) -> None:
    thresholds: Dict[str, int] = {}
    for flag, key in GATE_FLAGS:
        raw = _flag_value(flags, flag)
        if raw is None:
            continue
        if not raw.isdigit():
            raise SplitterError(f"{flag} needs a non-negative integer, got {raw}", 2)
        thresholds[key] = int(raw)
    print_json(gate_verdict(plan_path, thresholds), 0)


# ---------- split-write ----------

def _atomic_write(path: str, content: str) -> None:
    """Write through a temp file in the same folder and os.replace: a file is either old or complete."""
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", prefix=".splitter-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def cmd_split_write(plan_path: str, flags: List[str]) -> None:
    parts_path = _flag_value(flags, "--parts")
    if not parts_path:
        raise SplitterError("split-write needs --parts <parts.json>", 2)
    text = _read_plan(plan_path)
    lang = _flag_value(flags, "--lang") or detect_lang_for_text(text)[0]
    if lang not in ("ru", "en"):
        raise SplitterError(f"--lang must be ru or en, got {lang}", 2)
    payload = _load_parts(parts_path)
    plan_sha = sha256_file(plan_path)
    rendered = render_split(plan_path, payload, lang)
    directory = os.path.dirname(os.path.abspath(plan_path))
    existing = [name for name, _ in rendered["files"] if os.path.exists(os.path.join(directory, name))]
    if existing and "--force" not in flags:
        raise SplitterError("exists", 1, errors=[f"exists: {', '.join(existing)}"], exists=existing)
    written: List[str] = []
    for name, content in rendered["files"]:
        try:
            _atomic_write(os.path.join(directory, name), content)
        except OSError as exc:
            raise SplitterError(f"write-failed: {name}: {exc}", 1, written=written) from exc
        written.append(name)
    if sha256_file(plan_path) != plan_sha:
        raise SplitterError("plan-changed: the source plan changed during split-write", 1, written=written)
    sizes = {name: len(content.encode("utf-8")) for name, content in rendered["files"]}
    parts = []
    for item in rendered["parts"]:
        name = stage_filename(rendered["base"], item["id"])
        parts.append(dict(item, path=os.path.join(directory, name), bytes=sizes[name]))
    print_json({"ok": True, "roadmap": os.path.join(directory, written[0]), "parts": parts, "plan_sha256": plan_sha,
                "lang": lang, "warnings": rendered["warnings"], "written": written}, 0)


# ---------- main ----------

USAGE = """Usage:
  splitter_tool.py preflight <dir> <base_name>
  splitter_tool.py part-id <N>
  splitter_tool.py stage-name <base> <N|id>
  splitter_tool.py detect-lang <file>
  splitter_tool.py validate-stage <file>
  splitter_tool.py validate-roadmap <file>
  splitter_tool.py validate-all <dir> <base_name> [--skip-task-bodies]
  splitter_tool.py verify-baseline <dir> <base_name> [--stages all|a[,b...]] [--out <file>]
  splitter_tool.py verify-record <dir> <base_name> --results <file|-> --ledger <file> [--mode full-cycle|audit-only]
  splitter_tool.py verify-status <dir> <base_name> --baseline <file> --ledger <file> --validator <file> [--stages all|a[,b...]]
  splitter_tool.py hash <file>
  splitter_tool.py gate <plan> [--keep-tasks N] [--keep-bytes N] [--split-tasks N] [--split-bytes N] [--modules N]
  splitter_tool.py split-write <plan> --parts <parts.json> [--lang ru|en] [--force]
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
        elif cmd == "validate-all" and len(args) in (2, 3) and args[2:] in ([], ["--skip-task-bodies"]):
            cmd_validate_all(args[0], args[1], skip_task_bodies=len(args) == 3)
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
        elif cmd == "gate" and args:
            cmd_gate(args[0], args[1:])
        elif cmd == "split-write" and args:
            cmd_split_write(args[0], args[1:])
        else:
            sys.stderr.write(USAGE)
            sys.exit(2)
    except SplitterError as e:
        print_json(dict(e.details, ok=False, errors=e.details.get("errors") or [str(e)]), e.code)
    except Exception as e:
        sys.stderr.write(f"Error: {e}\n")
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv)
