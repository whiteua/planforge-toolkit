from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "scripts" / "splitter_tool.py"
VALIDATOR = ROOT.parent / "plan-iterative-revision" / "scripts" / "next_review_index.py"


def run_tool(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(TOOL), *args],
        text=True,
        capture_output=True,
        encoding="utf-8",
    )


def read_json(process: subprocess.CompletedProcess[str]) -> dict:
    try:
        return json.loads(process.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(process.stdout + process.stderr) from exc


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # write_bytes keeps "\n" as written; Path.write_text(newline=...) needs Python 3.10
    path.write_bytes(content.encode("utf-8"))


def write_json(path: Path, data: dict) -> None:
    write(path, json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stage_text(title: str) -> str:
    return f"""# {title}

## Goal
Prepare the stage.

## Inputs
Roadmap and previous outputs.

## Tasks
1. Do the focused task.

## Completion criteria
- [ ] The task is done.

## Outputs
Updated artifact.

## Notes
None.
"""


ROADMAP = """# Roadmap: plan

## Overview
Two parts.

## Dependency graph

| Stage | Title | Depends on | Parallel group | Weight |
|---|---|---|---|---|
| a | First | — | A | 🟢 light |
| b | Second | a | B | 🟢 light |

```mermaid
graph LR
    a --> b
```

## Stages

### a: First
### b: Second
"""


def make_stage_dir(directory: Path, base: str = "plan") -> None:
    write(directory / f"{base}-roadmap.md", ROADMAP)
    write(directory / f"{base}-a.md", stage_text("Stage a"))
    write(directory / f"{base}-b.md", stage_text("Stage b"))


def baseline_for(directory: Path, base: str, stages: str = "all") -> Path:
    baseline_path = directory / f"{base}-verify-baseline.json"
    process = run_tool("verify-baseline", str(directory), base, "--stages", stages)
    if process.returncode != 0:
        raise AssertionError(process.stdout + process.stderr)
    write(baseline_path, process.stdout)
    return baseline_path


def fingerprint(category: str, required_fix: str) -> str:
    process = subprocess.run(
        [sys.executable, str(VALIDATOR), "fingerprint", category, required_fix],
        text=True,
        capture_output=True,
        encoding="utf-8",
    )
    if process.returncode != 0:
        raise AssertionError(process.stdout + process.stderr)
    return process.stdout.strip()


def valid_review_text(stage: str, wrong_fingerprint: bool = False) -> str:
    required_fix = "Update the review validator to enforce required sections and Code cross-check vocabulary."
    issue_fingerprint = "deadbeef" if wrong_fingerprint else fingerprint("contract", required_fix)
    return f"""# Revision 1: {stage}

**Iteration**: 1
**Audited plan**: {stage}.md
**Plan SHA-256**: 0000000000000000000000000000000000000000000000000000000000000000
**Plan size**: 100 bytes
**Audited at**: 2026-05-09T00:00:00Z
**Previous review**: none
**Issues found**: 1 (blocker: 0, major: 1, minor: 0, nit: 0)

## Audit state

| Check | Status | Notes |
|---|---|---|
| Previous review contracts checked | n-a | none |
| Taxonomy sweep completed | yes | 10 classes |
| Code cross-check completed | yes | verified status used |
| Review validated | yes | validator fixture |
| Deferred conflicts carried | 0 | none |

## Summary

Sample valid review for validator regression checks.

## Issues

### [1.1] major · contract · Validator contract check

- **Location in plan**: REVIEW-FILE-FORMAT.md
- **Location in code**: scripts/next_review_index.py
- **Code cross-check**: verified - validator implementation is present.
- **Problem**:
  The validator must enforce the documented review contract.
- **Evidence**:
  > Plan quote: Validator checks the review format.
- **Required fix (contract)**:
  {required_fix}
- **Acceptance**:
  This fixture passes validate-review --strict-fingerprint.
- **Fingerprint**: {issue_fingerprint}

## Deferred from previous review

None.

## Notes for implementation

None.
"""


def ledger_data(base: str, stage: str, result: str, remaining_issues: int = 0, verify_mode: str = "full-cycle") -> dict:
    return {
        "base_name": base,
        "verify_mode": verify_mode,
        "stages": {
            stage: {
                "verify_mode": verify_mode,
                "result": result,
                "iterations": 1,
                "remaining_issues": remaining_issues,
                "attempts": 1,
                "error": None,
            }
        },
    }


def run_status(directory: Path, base: str, baseline_path: Path, ledger_path: Path, stages: str = "a") -> subprocess.CompletedProcess[str]:
    return run_tool(
        "verify-status", str(directory), base,
        "--baseline", str(baseline_path),
        "--ledger", str(ledger_path),
        "--validator", str(VALIDATOR),
        "--stages", stages,
    )


class VerifyBaselineTests(unittest.TestCase):
    def test_baseline_snapshots_sha_and_reviews(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            base = "plan"
            make_stage_dir(directory, base)
            write(directory / f"{base}-a-review-1.md", "# existing review\n")

            process = run_tool("verify-baseline", str(directory), base, "--stages", "all")

            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            data = read_json(process)
            self.assertEqual(data["stages"]["a"]["stg_sha"], sha256(directory / f"{base}-a.md"))
            self.assertEqual(data["stages"]["a"]["review_files"], [f"{base}-a-review-1.md"])
            self.assertEqual(data["stages"]["b"]["review_files"], [])


class VerifyStatusBasicTests(unittest.TestCase):
    def test_clean_stage_satisfied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            base = "plan"
            make_stage_dir(directory, base)
            baseline_path = baseline_for(directory, base, "a")
            ledger_path = directory / f"{base}-verify-ledger.json"
            write_json(ledger_path, ledger_data(base, "a", "clean"))

            process = run_status(directory, base, baseline_path, ledger_path)

            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            self.assertEqual(read_json(process)["stages"]["a"]["verdict"], "satisfied")

    def test_missing_ledger_entry_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            base = "plan"
            make_stage_dir(directory, base)
            baseline_path = baseline_for(directory, base, "a")
            ledger_path = directory / f"{base}-verify-ledger.json"
            write_json(ledger_path, {
                "base_name": base,
                "verify_mode": "full-cycle",
                "stages": {},
            })

            process = run_status(directory, base, baseline_path, ledger_path)

            self.assertEqual(process.returncode, 1, process.stdout + process.stderr)
            self.assertEqual(read_json(process)["stages"]["a"]["verdict"], "missing")


class VerifyStatusConvergedTests(unittest.TestCase):
    def test_converged_genuine_satisfied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            base = "plan"
            make_stage_dir(directory, base)
            baseline_path = baseline_for(directory, base, "a")
            ledger_path = directory / f"{base}-verify-ledger.json"
            write(directory / f"{base}-a-review-1.md", valid_review_text(f"{base}-a"))
            write(directory / f"{base}-a.md", stage_text("Stage a") + "\nImplemented fix.\n")
            write_json(ledger_path, ledger_data(base, "a", "converged"))

            process = run_status(directory, base, baseline_path, ledger_path)

            data = read_json(process)
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            self.assertTrue(data["stages"]["a"]["reviews_validated"])
            self.assertEqual(data["stages"]["a"]["verdict"], "satisfied")

    def test_converged_without_file_inconsistent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            base = "plan"
            make_stage_dir(directory, base)
            baseline_path = baseline_for(directory, base, "a")
            ledger_path = directory / f"{base}-verify-ledger.json"
            write(directory / f"{base}-a.md", stage_text("Stage a") + "\nImplemented fix.\n")
            write_json(ledger_path, ledger_data(base, "a", "converged"))

            process = run_status(directory, base, baseline_path, ledger_path)

            data = read_json(process)
            self.assertEqual(process.returncode, 1, process.stdout + process.stderr)
            self.assertFalse(data["stages"]["a"]["reviews_validated"])
            self.assertEqual(data["stages"]["a"]["verdict"], "inconsistent")

    def test_converged_stub_review_inconsistent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            base = "plan"
            make_stage_dir(directory, base)
            baseline_path = baseline_for(directory, base, "a")
            ledger_path = directory / f"{base}-verify-ledger.json"
            write(directory / f"{base}-a-review-1.md", "# placeholder\n")
            write(directory / f"{base}-a.md", stage_text("Stage a") + "\nImplemented fix.\n")
            write_json(ledger_path, ledger_data(base, "a", "converged"))

            process = run_status(directory, base, baseline_path, ledger_path)

            data = read_json(process)
            self.assertEqual(process.returncode, 1, process.stdout + process.stderr)
            self.assertFalse(data["stages"]["a"]["reviews_validated"])
            self.assertEqual(data["stages"]["a"]["verdict"], "inconsistent")

    def test_converged_wrong_fingerprint_inconsistent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            base = "plan"
            make_stage_dir(directory, base)
            baseline_path = baseline_for(directory, base, "a")
            ledger_path = directory / f"{base}-verify-ledger.json"
            write(directory / f"{base}-a-review-1.md", valid_review_text(f"{base}-a", wrong_fingerprint=True))
            write(directory / f"{base}-a.md", stage_text("Stage a") + "\nImplemented fix.\n")
            write_json(ledger_path, ledger_data(base, "a", "converged"))

            process = run_status(directory, base, baseline_path, ledger_path)

            data = read_json(process)
            self.assertEqual(process.returncode, 1, process.stdout + process.stderr)
            self.assertFalse(data["stages"]["a"]["reviews_validated"])
            self.assertEqual(data["stages"]["a"]["verdict"], "inconsistent")

    def test_converged_pragmatic_remaining_issues_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            base = "plan"
            make_stage_dir(directory, base)
            baseline_path = baseline_for(directory, base, "a")
            ledger_path = directory / f"{base}-verify-ledger.json"
            write(directory / f"{base}-a-review-1.md", valid_review_text(f"{base}-a"))
            write_json(ledger_path, ledger_data(base, "a", "converged", remaining_issues=2))

            process = run_status(directory, base, baseline_path, ledger_path)

            data = read_json(process)
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            self.assertTrue(data["stages"]["a"]["reviews_validated"])
            self.assertFalse(data["stages"]["a"]["stg_sha_changed"])
            self.assertEqual(data["stages"]["a"]["verdict"], "satisfied_with_warning")

    def test_converged_audit_only_no_change_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            base = "plan"
            make_stage_dir(directory, base)
            baseline_path = baseline_for(directory, base, "a")
            ledger_path = directory / f"{base}-verify-ledger.json"
            write(directory / f"{base}-a-review-1.md", valid_review_text(f"{base}-a"))
            write_json(ledger_path, ledger_data(base, "a", "converged", verify_mode="audit-only"))

            process = run_status(directory, base, baseline_path, ledger_path)

            data = read_json(process)
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            self.assertTrue(data["stages"]["a"]["reviews_validated"])
            self.assertFalse(data["stages"]["a"]["stg_sha_changed"])
            self.assertEqual(data["stages"]["a"]["verdict"], "satisfied_with_warning")


class VerifyStatusHonestFailTests(unittest.TestCase):
    def test_limit_with_final_review_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            base = "plan"
            make_stage_dir(directory, base)
            baseline_path = baseline_for(directory, base, "a")
            ledger_path = directory / f"{base}-verify-ledger.json"
            write(directory / f"{base}-a-review-1.md", valid_review_text(f"{base}-a"))
            write_json(ledger_path, ledger_data(base, "a", "limit", remaining_issues=2))

            process = run_status(directory, base, baseline_path, ledger_path)

            data = read_json(process)
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            self.assertTrue(data["stages"]["a"]["reviews_validated"])
            self.assertEqual(data["stages"]["a"]["verdict"], "satisfied_with_warning")

    def test_limit_without_review_inconsistent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            base = "plan"
            make_stage_dir(directory, base)
            baseline_path = baseline_for(directory, base, "a")
            ledger_path = directory / f"{base}-verify-ledger.json"
            write_json(ledger_path, ledger_data(base, "a", "limit", remaining_issues=2))

            process = run_status(directory, base, baseline_path, ledger_path)

            data = read_json(process)
            self.assertEqual(process.returncode, 1, process.stdout + process.stderr)
            self.assertFalse(data["stages"]["a"]["reviews_validated"])
            self.assertEqual(data["stages"]["a"]["verdict"], "inconsistent")

    def test_escalated_with_final_review_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            base = "plan"
            make_stage_dir(directory, base)
            baseline_path = baseline_for(directory, base, "a")
            ledger_path = directory / f"{base}-verify-ledger.json"
            write(directory / f"{base}-a-review-1.md", valid_review_text(f"{base}-a"))
            write_json(ledger_path, ledger_data(base, "a", "escalated", remaining_issues=3))

            process = run_status(directory, base, baseline_path, ledger_path)

            data = read_json(process)
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            self.assertTrue(data["stages"]["a"]["reviews_validated"])
            self.assertEqual(data["stages"]["a"]["verdict"], "satisfied_with_warning")


class VerifyRecordTests(unittest.TestCase):
    def test_record_writes_ledger_from_batch_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            base = "plan"
            make_stage_dir(directory, base)
            ledger_path = directory / f"{base}-verify-ledger.json"
            results = {"parts": {"a": {"result": "clean", "iterations": 0, "remaining_issues": 0},
                                 "B": {"result": "bogus", "iterations": 1, "remaining_issues": 2}}}
            process = subprocess.run(
                [sys.executable, str(TOOL), "verify-record", str(directory), base,
                 "--results", "-", "--ledger", str(ledger_path), "--mode", "audit-only"],
                text=True, capture_output=True, encoding="utf-8", input=json.dumps(results),
            )
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            self.assertEqual(ledger["verify_mode"], "audit-only")
            self.assertEqual(ledger["stages"]["a"]["result"], "clean")
            self.assertEqual(ledger["stages"]["a"]["attempts"], 1)
            self.assertIsNone(ledger["stages"]["b"]["result"])
            self.assertIn("invalid result", ledger["stages"]["b"]["error"])
            # Second record (re-dispatch) increments attempts and keeps the other entry.
            results = {"parts": {"b": {"result": "converged", "iterations": 1, "remaining_issues": 0}}}
            process = subprocess.run(
                [sys.executable, str(TOOL), "verify-record", str(directory), base,
                 "--results", "-", "--ledger", str(ledger_path)],
                text=True, capture_output=True, encoding="utf-8", input=json.dumps(results),
            )
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            self.assertEqual(ledger["stages"]["b"]["attempts"], 2)
            self.assertEqual(ledger["stages"]["a"]["result"], "clean")

    def test_recorded_failure_is_missing_not_inconsistent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            base = "plan"
            make_stage_dir(directory, base)
            baseline_path = directory / f"{base}-verify-baseline.json"
            process = run_tool("verify-baseline", str(directory), base, "--stages", "a", "--out", str(baseline_path))
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            self.assertEqual(json.loads(baseline_path.read_text(encoding="utf-8")), read_json(process))
            ledger_path = directory / f"{base}-verify-ledger.json"
            results = {"parts": {"a": {"result": None, "error": "subagent died"}}}
            process = subprocess.run(
                [sys.executable, str(TOOL), "verify-record", str(directory), base,
                 "--results", "-", "--ledger", str(ledger_path)],
                text=True, capture_output=True, encoding="utf-8", input=json.dumps(results),
            )
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            process = run_status(directory, base, baseline_path, ledger_path, stages="a")
            self.assertEqual(process.returncode, 1)
            self.assertEqual(read_json(process)["stages"]["a"]["verdict"], "missing")

    def test_baseline_all_follows_roadmap_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            make_stage_dir(directory, "plan")
            write(directory / "plan-db.md", "# not a part\n")
            data = read_json(run_tool("verify-baseline", str(directory), "plan", "--stages", "all"))
            self.assertEqual(list(data["stages"]), ["a", "b"])

    def test_status_accepts_upper_and_space_separated_stage_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            base = "plan"
            make_stage_dir(directory, base)
            baseline_path = baseline_for(directory, base, "all")
            ledger_path = directory / f"{base}-verify-ledger.json"
            ledger = ledger_data(base, "a", "clean")
            ledger["stages"]["b"] = dict(ledger["stages"]["a"])
            write_json(ledger_path, ledger)
            process = run_status(directory, base, baseline_path, ledger_path, stages="A b")
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            self.assertEqual(set(read_json(process)["stages"]), {"a", "b"})


TASK_LINES_PLAN = (
    "# Plan\n\n### Task 1: one\n\n**External:** `db_test` (read) — select count(*)\n\n"
    "**Size:** 140 lines — the migration and its schema test cannot be split\n\n"
    "```markdown\n**External:** `fenced` (write) — example only\n```\n"
)
EXTERNAL_LINE = "**External:** `db_test` (read) — select count(*)"
SIZE_LINE = "**Size:** 140 lines — the migration and its schema test cannot be split"


class ValidateAllTaskLineTests(unittest.TestCase):
    def test_task_lines_copied_verbatim_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            make_stage_dir(directory)
            write(directory / "plan.md", TASK_LINES_PLAN)
            write(directory / "plan-a.md", stage_text("Stage a").replace(
                "1. Do the focused task.\n",
                "1. Do the focused task.\n   " + EXTERNAL_LINE + "\n   " + SIZE_LINE + "\n",
            ))
            write(directory / "plan-b.md", stage_text("Stage b").replace("1. Do the focused task.\n", ""))
            process = run_tool("validate-all", str(directory), "plan", "--skip-task-bodies")
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            self.assertEqual(read_json(process)["task_lines"], {"missing": [], "original": 2})

    def test_task_lines_lost_in_parts_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            make_stage_dir(directory)
            write(directory / "plan.md", TASK_LINES_PLAN)
            write(directory / "plan-a.md", stage_text("Stage a").replace(
                "1. Do the focused task.\n", "1. Do the focused task.\n   " + EXTERNAL_LINE + "\n",
            ))
            process = run_tool("validate-all", str(directory), "plan")
            data = read_json(process)
            self.assertEqual(process.returncode, 1)
            self.assertEqual(data["task_lines"]["missing"], [SIZE_LINE])
            self.assertTrue(any("not copied verbatim" in error for error in data["errors"]))


if __name__ == "__main__":
    unittest.main()