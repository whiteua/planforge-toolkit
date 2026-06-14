from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "scripts" / "resolver_tool.py"
LONG_DESCRIPTION = (
    "Эта ошибка описывает проверяемое несоответствие достаточно подробно, чтобы валидатор "
    "мог убедиться в наличии полноценного контекста для внешнего исполнителя. Описание "
    "содержит причину, наблюдаемый симптом, ожидаемое поведение, затронутую область и "
    "минимальные рекомендации по повторной проверке после исправления."
)


def run_tool(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(TOOL), *args], text=True, capture_output=True)


def read_json(process: subprocess.CompletedProcess[str]) -> dict:
    try:
        return json.loads(process.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(process.stdout + process.stderr) from exc


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def valid_report(final: bool = False, issue_status: str = "⭕️ not-fixed") -> str:
    issue_block = "Ошибок не найдено."
    consecutive = 0 if final else 1
    if not final:
        issue_block = f"""
1) Ошибка 1: {issue_status} | critical | Невыполненный контракт
- **level**: critical
- **status**: {issue_status}
- **title**: Невыполненный контракт
- **description**: {LONG_DESCRIPTION}
- **recommendations**: Повторно проверить соответствующий код и убедиться, что контракт закрыт.
""".strip()
    return f"""---
master_plan_path: main-plan.md
master_plan_sha256: {'a' * 64}
master_plan_size: 123
audited_at: 2026-05-10T07:54:08Z
audit_iteration: 1
consecutive_open_invocations: {consecutive}
previous_report_path: null
previous_report_sha256: null
language: ru
---
# Отчет о выполнении плана 1

## Основные стадии плана

- ✅ 1. Подготовка

## Список ошибок

{issue_block}

## Задача

План реализован полностью; дальнейших действий не требуется.
"""


def report_with_closed_task(final: bool, task_line: str) -> str:
    base = valid_report(final=final)
    return base.replace("- ✅ 1. Подготовка", "- ✅ 1. Phase\n  " + task_line)


class BootstrapTests(unittest.TestCase):
    def test_bootstrap_first_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root / "main-plan.md", "# Main\n")
            process = run_tool("bootstrap", str(root), "main-plan.md")
            data = read_json(process)
            self.assertEqual(process.returncode, 0, data)
            self.assertTrue(data["valid"])
            self.assertEqual(data["pass_type"], "first")
            self.assertEqual(data["next_n"], 1)
            self.assertEqual(data["next_open_name"], "main-plan-report-1.md")
            self.assertEqual(process.stderr, "")

    def test_bootstrap_language_ru_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root / "main-plan.md", "# План\n\nОписание задач на русском языке.\n")
            data = read_json(run_tool("bootstrap", str(root), "main-plan.md"))
            self.assertEqual(data["language"], "ru")

    def test_bootstrap_language_en_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root / "main-plan.md", "# Plan\n\nEnglish-only task descriptions here.\n")
            data = read_json(run_tool("bootstrap", str(root), "main-plan.md"))
            self.assertEqual(data["language"], "en")

    def test_bootstrap_language_empty_plan_defaults_ru(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root / "main-plan.md", "1. 2. 3.\n")
            data = read_json(run_tool("bootstrap", str(root), "main-plan.md"))
            self.assertEqual(data["language"], "ru")

    def test_bootstrap_has_no_deprecation_warning_under_strict_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root / "main-plan.md", "# Main\n")
            process = subprocess.run(
                [sys.executable, "-W", "error::DeprecationWarning", str(TOOL), "bootstrap", str(root), "main-plan.md"],
                text=True,
                capture_output=True,
            )
            data = read_json(process)
            self.assertEqual(process.returncode, 0, data)
            self.assertEqual(process.stderr, "")

    def test_bootstrap_report_gap_is_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root / "main-plan.md", "# Main\n")
            write(root / "main-plan-report-1.md", valid_report())
            write(root / "main-plan-report-3.md", valid_report())
            process = run_tool(
                "bootstrap",
                str(root),
                "main-plan.md",
                "main-plan-report-1.md",
                "main-plan-report-3.md",
            )
            data = read_json(process)
            self.assertEqual(process.returncode, 2, data)
            self.assertIn("bootstrap-gap-in-reports", "\n".join(data["errors"]))

    def test_bootstrap_final_report_stops(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root / "main-plan.md", "# Main\n")
            write(root / "main-plan-report-1-final.md", valid_report(final=True))
            process = run_tool("bootstrap", str(root), "main-plan.md", "main-plan-report-1-final.md")
            data = read_json(process)
            self.assertEqual(process.returncode, 64, data)
            self.assertTrue(data["closed"])

    def test_bootstrap_rejects_duplicate_and_mismatched_base(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root / "main-plan.md", "# Main\n")
            write(root / "main-plan-report-1.md", valid_report())
            write(root / "other-plan-report-1.md", valid_report())
            process = run_tool(
                "bootstrap",
                str(root),
                "main-plan.md",
                "main-plan-report-1.md",
                "other-plan-report-1.md",
            )
            data = read_json(process)
            joined = "\n".join(data["errors"])
            self.assertEqual(process.returncode, 2, data)
            self.assertIn("bootstrap-base-mismatch", joined)
            self.assertIn("bootstrap-duplicate-report", joined)


class PreflightAndFingerprintTests(unittest.TestCase):
    def test_preflight_checks_both_reserved_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root / "main-plan-report-1-final.md", "exists")
            process = run_tool("preflight", str(root), "main-plan-report-1.md", "main-plan-report-1-final.md")
            data = read_json(process)
            self.assertEqual(process.returncode, 1, data)
            self.assertFalse(data["valid"])
            self.assertEqual(len(data["existing"]), 1)

    def test_fingerprint_and_readonly_guard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root = Path(tmp)
            snap_dir = Path(outside)
            write(root / "main-plan.md", "# Main\n")
            write(root / "node_modules" / "ignored.txt", "ignored")
            start_json = snap_dir / "start.json"
            current_json = snap_dir / "current.json"
            process = run_tool("fingerprint-workspace", str(root), str(start_json))
            self.assertEqual(process.returncode, 0, read_json(process))
            write(root / "main-plan-report-1.md", "report")
            process = run_tool("fingerprint-workspace", str(root), str(current_json))
            self.assertEqual(process.returncode, 0, read_json(process))
            process = run_tool("assert-readonly", str(start_json), str(current_json), "main-plan-report-1.md")
            data = read_json(process)
            self.assertEqual(process.returncode, 0, data)
            self.assertTrue(data["valid"])
            write(root / "main-plan.md", "# Changed\n")
            process = run_tool("fingerprint-workspace", str(root), str(current_json))
            self.assertEqual(process.returncode, 0, read_json(process))
            process = run_tool("assert-readonly", str(start_json), str(current_json), "main-plan-report-1.md")
            data = read_json(process)
            self.assertEqual(process.returncode, 1, data)
            self.assertIn("main-plan.md", data["violations"])


class ReportTests(unittest.TestCase):
    def test_validate_and_parse_open_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "main-plan-report-1.md"
            write(report, valid_report())
            process = run_tool("validate-report", str(report))
            data = read_json(process)
            self.assertEqual(process.returncode, 0, data)
            self.assertTrue(data["valid"])
            process = run_tool("parse-report", str(report))
            data = read_json(process)
            self.assertEqual(process.returncode, 0, data)
            self.assertEqual(data["issues"][0]["status"], "not-fixed")
            self.assertEqual(data["issues"][0]["level"], "critical")

    def test_parse_report_extracts_phases_and_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "main-plan-report-1.md"
            content = valid_report().replace(
                "- ✅ 1. Подготовка",
                "- ✅ 1. Bootstrap\n  - ⚠️ 1.1 Validate paths\n  - not-applicable 1.2 Read docs\n- ⭕️ 2. Writer\n  - ‼️ 2.1 Final name",
            )
            write(report, content)
            process = run_tool("parse-report", str(report))
            data = read_json(process)
            self.assertEqual(process.returncode, 0, data)
            self.assertEqual([phase["id"] for phase in data["phases"]], ["1", "2"])
            self.assertEqual([task["id"] for task in data["tasks"]], ["1.1", "1.2", "2.1"])
            self.assertEqual(data["tasks"][0]["phase"], 1)
            self.assertEqual(data["tasks"][1]["status"], "not-applicable")
            self.assertFalse(data["tasks"][1]["actionable"])
            self.assertGreaterEqual(data["tasks"][2]["line_start"], 1)

    def test_validate_report_rejects_invalid_or_missing_issue_emoji(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            invalid = Path(tmp) / "invalid-emoji-report.md"
            write(invalid, valid_report(issue_status="🐛 not-fixed"))
            process = run_tool("validate-report", str(invalid))
            data = read_json(process)
            self.assertEqual(process.returncode, 1, data)
            self.assertIn("issue 1 has invalid emoji marker", "\n".join(data["errors"]))

            missing = Path(tmp) / "missing-emoji-report.md"
            write(missing, valid_report(issue_status="not-fixed"))
            process = run_tool("validate-report", str(missing))
            data = read_json(process)
            self.assertEqual(process.returncode, 1, data)
            self.assertIn("issue 1 is missing emoji marker", "\n".join(data["errors"]))

            for marker_status in ("✅ fixed", "⚠️ fixed-with-errors", "⭕️ not-fixed", "‼️ regressed"):
                allowed = Path(tmp) / (marker_status.split()[1] + ".md")
                write(allowed, valid_report(issue_status=marker_status))
                process = run_tool("validate-report", str(allowed))
                data = read_json(process)
                self.assertEqual(process.returncode, 0, data)

    def test_final_report_requires_closed_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp) / "main-plan-report-2-final.md"
            write(good, valid_report(final=True))
            process = run_tool("validate-report", str(good))
            self.assertEqual(process.returncode, 0, read_json(process))

            bad = Path(tmp) / "main-plan-report-3-final.md"
            write(bad, valid_report(final=False))
            process = run_tool("validate-report", str(bad))
            data = read_json(process)
            self.assertEqual(process.returncode, 1, data)
            self.assertIn("final report contains non-fixed issues", "\n".join(data["errors"]))

    def test_iteration_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "main-plan-report-4.md"
            content = valid_report().replace("audit_iteration: 1", "audit_iteration: 4").replace(
                "consecutive_open_invocations: 1", "consecutive_open_invocations: 4"
            )
            write(report, content)
            process = run_tool("iteration-check", str(report), "5")
            data = read_json(process)
            self.assertEqual(process.returncode, 0, data)
            self.assertEqual(data["consecutive"], 5)
            self.assertTrue(data["ask_required"])


class ValidateQualityGateTests(unittest.TestCase):
    def _ambiguous_report(self, n: int, anchor: str, prev_name: str, prev_sha: str) -> str:
        text = valid_report(final=False).replace(
            "- ✅ 1. Подготовка",
            "- ✅ 1. Phase\n  - ⚠️ 1.1 ambiguous Tricky evidence_anchor: " + anchor,
        )
        text = text.replace("audit_iteration: 1", f"audit_iteration: {n}")
        text = text.replace("previous_report_path: null", f"previous_report_path: {prev_name}")
        text = text.replace("previous_report_sha256: null", f"previous_report_sha256: {prev_sha}")
        return text

    def test_final_missing_evidence_on_check_task_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "main-plan-report-2-final.md"
            write(report, report_with_closed_task(True, "- ✅ 1.1 Implemented thing"))
            process = run_tool("validate-report", str(report))
            data = read_json(process)
            self.assertEqual(process.returncode, 1, data)
            self.assertIn("1.1", "\n".join(data["errors"]))
            self.assertIn("evidence", "\n".join(data["errors"]).lower())

    def test_intermediate_missing_evidence_is_warning_not_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "main-plan-report-2.md"
            write(report, report_with_closed_task(False, "- ✅ 1.1 Implemented thing"))
            process = run_tool("validate-report", str(report))
            data = read_json(process)
            self.assertEqual(process.returncode, 0, data)
            self.assertTrue(any(w.startswith("[WARNING] ") for w in data["warnings"]), data)
            self.assertTrue(any("1.1" in w for w in data["warnings"]), data)

    def test_final_with_evidence_anchor_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "main-plan-report-2-final.md"
            write(report, report_with_closed_task(True, "- ✅ 1.1 Done — evidence: src/x.py#L10-L20"))
            process = run_tool("validate-report", str(report))
            data = read_json(process)
            self.assertEqual(process.returncode, 0, data)

    def test_final_low_confidence_close_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "main-plan-report-2-final.md"
            line = "- ✅ 1.1 Done — evidence: src/x.py#L10-L20 confidence: low"
            write(report, report_with_closed_task(True, line))
            process = run_tool("validate-report", str(report))
            data = read_json(process)
            self.assertEqual(process.returncode, 1, data)
            self.assertIn("1.1", "\n".join(data["errors"]))
            self.assertIn("confidence", "\n".join(data["errors"]).lower())

    def test_intermediate_low_confidence_is_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "main-plan-report-2.md"
            line = "- ✅ 1.1 Done — evidence: src/x.py#L10-L20 confidence: low"
            write(report, report_with_closed_task(False, line))
            process = run_tool("validate-report", str(report))
            data = read_json(process)
            self.assertEqual(process.returncode, 0, data)
            self.assertTrue(any(w.startswith("[WARNING] ") for w in data["warnings"]), data)
            self.assertTrue(any("confidence" in w.lower() for w in data["warnings"]), data)

    def test_final_fixed_issue_with_low_confidence_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "main-plan-report-2-final.md"
            content = valid_report(final=False, issue_status="✅ fixed").replace(
                "consecutive_open_invocations: 1",
                "consecutive_open_invocations: 0",
            ).replace(
                "- **recommendations**: Повторно проверить соответствующий код и убедиться, что контракт закрыт.",
                "- **recommendations**: Повторно проверить соответствующий код и убедиться, что контракт закрыт.\n"
                "confidence: low",
            )
            write(report, content)
            process = run_tool("validate-report", str(report))
            data = read_json(process)
            joined_errors = "\n".join(data["errors"]).lower()
            self.assertEqual(process.returncode, 1, data)
            self.assertIn("confidence", joined_errors)
            self.assertIn("issue", joined_errors)

    def test_intermediate_fixed_issue_with_low_confidence_is_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "main-plan-report-2.md"
            content = valid_report(final=False, issue_status="✅ fixed").replace(
                "- **recommendations**: Повторно проверить соответствующий код и убедиться, что контракт закрыт.",
                "- **recommendations**: Повторно проверить соответствующий код и убедиться, что контракт закрыт.\n"
                "confidence: low",
            )
            write(report, content)
            process = run_tool("validate-report", str(report))
            data = read_json(process)
            joined_warnings = "\n".join(data["warnings"]).lower()
            self.assertEqual(process.returncode, 0, data)
            self.assertTrue(any(w.startswith("[WARNING] ") for w in data["warnings"]), data)
            self.assertIn("confidence", joined_warnings)
            self.assertIn("issue", joined_warnings)

    def test_repeated_ambiguous_same_anchor_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prev = root / "main-plan-report-1.md"
            write(
                prev,
                valid_report(final=False).replace(
                    "- ✅ 1. Подготовка",
                    "- ✅ 1. Phase\n  - ⚠️ 1.1 ambiguous Tricky evidence_anchor: src/x.py#L5-L9",
                ),
            )
            cur = root / "main-plan-report-2.md"
            write(cur, self._ambiguous_report(2, "src/x.py#L5-L9", prev.name, sha256(prev)))
            process = run_tool("validate-report", str(cur))
            data = read_json(process)
            self.assertEqual(process.returncode, 0, data)
            self.assertTrue(any("ambiguous" in w.lower() and "1.1" in w for w in data["warnings"]), data)

    def test_changed_anchor_no_oscillation_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prev = root / "main-plan-report-1.md"
            write(
                prev,
                valid_report(final=False).replace(
                    "- ✅ 1. Подготовка",
                    "- ✅ 1. Phase\n  - ⚠️ 1.1 ambiguous Tricky evidence_anchor: src/x.py#L5-L9",
                ),
            )
            cur = root / "main-plan-report-2.md"
            write(cur, self._ambiguous_report(2, "src/x.py#L40-L60", prev.name, sha256(prev)))
            process = run_tool("validate-report", str(cur))
            data = read_json(process)
            self.assertEqual(process.returncode, 0, data)
            self.assertFalse(any("stuck in ambiguous" in w for w in data["warnings"]), data)


class WorkflowE2ETests(unittest.TestCase):
    def write_snapshot(self, workspace: Path, snapshot: Path) -> None:
        process = run_tool("fingerprint-workspace", str(workspace), str(snapshot))
        self.assertEqual(process.returncode, 0, read_json(process))

    def validate_report_and_guard(self, workspace: Path, snapshot_dir: Path, report: Path, start_snapshot: Path) -> None:
        process = run_tool("validate-report", str(report))
        self.assertEqual(process.returncode, 0, read_json(process))
        current_snapshot = snapshot_dir / (report.stem + "-current.json")
        self.write_snapshot(workspace, current_snapshot)
        process = run_tool("assert-readonly", str(start_snapshot), str(current_snapshot), report.name)
        self.assertEqual(process.returncode, 0, read_json(process))

    def test_smoke_first_and_subsequent_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as snapshots:
            root = Path(tmp)
            snapshot_dir = Path(snapshots)
            write(root / "main-plan.md", "# Main\n\n- implement feature\n")
            write(root / "src" / "feature.txt", "todo\n")

            process = run_tool("bootstrap", str(root), "main-plan.md")
            bootstrap = read_json(process)
            self.assertEqual(process.returncode, 0, bootstrap)
            self.assertEqual(bootstrap["pass_type"], "first")
            process = run_tool("preflight", str(root), bootstrap["next_open_name"], bootstrap["next_final_name"])
            self.assertEqual(process.returncode, 0, read_json(process))
            start = snapshot_dir / "start-1.json"
            self.write_snapshot(root, start)
            report1 = root / bootstrap["next_open_name"]
            write(report1, valid_report())
            self.validate_report_and_guard(root, snapshot_dir, report1, start)

            write(root / "src" / "feature.txt", "implemented between invocations\n")
            process = run_tool("bootstrap", str(root), "main-plan.md", report1.name)
            bootstrap = read_json(process)
            self.assertEqual(process.returncode, 0, bootstrap)
            self.assertEqual(bootstrap["pass_type"], "subsequent")
            self.assertEqual(bootstrap["next_n"], 2)
            process = run_tool("preflight", str(root), bootstrap["next_open_name"], bootstrap["next_final_name"])
            self.assertEqual(process.returncode, 0, read_json(process))
            start = snapshot_dir / "start-2.json"
            self.write_snapshot(root, start)
            report2 = root / bootstrap["next_open_name"]
            report2_text = valid_report(issue_status="⚠️ fixed-with-errors").replace(
                "audit_iteration: 1", "audit_iteration: 2"
            ).replace("previous_report_path: null", "previous_report_path: main-plan-report-1.md").replace(
                "previous_report_sha256: null", f"previous_report_sha256: {sha256(report1)}"
            )
            write(report2, report2_text)
            self.validate_report_and_guard(root, snapshot_dir, report2, start)

    def test_drift_workflow_records_blocker_in_same_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as snapshots:
            root = Path(tmp)
            snapshot_dir = Path(snapshots)
            write(root / "main-plan.md", "# Main\n")
            start = snapshot_dir / "start.json"
            current = snapshot_dir / "current.json"
            self.write_snapshot(root, start)
            report = root / "main-plan-report-1.md"
            write(report, valid_report())
            write(root / "main-plan.md", "# Main changed during audit\n")
            self.write_snapshot(root, current)
            process = run_tool("assert-readonly", str(start), str(current), report.name)
            data = read_json(process)
            self.assertEqual(process.returncode, 1, data)
            self.assertIn("main-plan.md", data["violations"])

            blocker = valid_report().replace(
                "Невыполненный контракт",
                "probe-mutated-workspace",
            ).replace(
                LONG_DESCRIPTION,
                LONG_DESCRIPTION + " Drift guard обнаружил изменение main-plan.md вне разрешённого отчёта.",
            )
            write(report, blocker)
            process = run_tool("validate-report", str(report))
            self.assertEqual(process.returncode, 0, read_json(process))
            self.assertIn("probe-mutated-workspace", report.read_text(encoding="utf-8"))

    def test_final_workflow_uses_final_name_and_closes_bootstrap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as snapshots:
            root = Path(tmp)
            snapshot_dir = Path(snapshots)
            write(root / "main-plan.md", "# Main\n")
            process = run_tool("bootstrap", str(root), "main-plan.md")
            bootstrap = read_json(process)
            self.assertEqual(process.returncode, 0, bootstrap)
            process = run_tool("preflight", str(root), bootstrap["next_open_name"], bootstrap["next_final_name"])
            self.assertEqual(process.returncode, 0, read_json(process))
            start = snapshot_dir / "start-final.json"
            self.write_snapshot(root, start)
            final_report = root / bootstrap["next_final_name"]
            write(final_report, valid_report(final=True))
            self.validate_report_and_guard(root, snapshot_dir, final_report, start)
            process = run_tool("bootstrap", str(root), "main-plan.md", final_report.name)
            data = read_json(process)
            self.assertEqual(process.returncode, 64, data)
            self.assertTrue(data["closed"])


class TaskCensusTests(unittest.TestCase):
    def test_no_units_is_loud_exit_two(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root / "main-plan.md", "# Main\n\n- implement feature\n")
            write(root / "main-plan-report-1.md", valid_report())
            process = run_tool(
                "task-census", str(root / "main-plan.md"), str(root / "main-plan-report-1.md")
            )
            data = read_json(process)
            self.assertEqual(process.returncode, 2, data)
            self.assertFalse(data["valid"])
            self.assertEqual(data["units_extracted"], 0)
            self.assertEqual(data["plan_ids"], [])
            self.assertEqual(data["covered"], [])
            self.assertEqual(data["uncovered"], [])
            self.assertEqual(
                data["errors"],
                ["task-census-no-units: no syntactic task units extracted from plan"],
            )

    def test_any_status_counts_as_covered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(
                root / "main-plan.md",
                "## 1. Phase\n- 1.1 Fixed\n- 1.2 Partial\n- 1.3 Open\n- 1.4 Regressed\n- 1.5 Skipped\n",
            )
            report = valid_report().replace(
                "- ✅ 1. Подготовка",
                "- ✅ 1. Phase\n"
                "  - ✅ 1.1 Fixed\n"
                "  - ⚠️ 1.2 Partial\n"
                "  - ⭕️ 1.3 Open\n"
                "  - ‼️ 1.4 Regressed\n"
                "  - not-applicable 1.5 Skipped",
            )
            write(root / "main-plan-report-1.md", report)
            process = run_tool(
                "task-census", str(root / "main-plan.md"), str(root / "main-plan-report-1.md")
            )
            data = read_json(process)
            self.assertEqual(process.returncode, 0, data)
            self.assertEqual(data["covered"], ["1", "1.1", "1.2", "1.3", "1.4", "1.5"])
            self.assertEqual(data["uncovered"], [])

    def test_roadmap_stage_ids_are_covered_by_report_stage_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(
                root / "main-plan.md",
                "| Stage | Title | Depends |\n"
                "|---|---|---|\n"
                "| stg01 | Scaffold | - |\n"
                "| stg02 | Ledger | stg01 |\n",
            )
            report = valid_report().replace(
                "- ✅ 1. Подготовка",
                "- ✅ 1 stg01 Scaffold done\n"
                "- ✅ 2 stg02 Ledger done",
            )
            write(root / "main-plan-report-1.md", report)
            process = run_tool(
                "task-census", str(root / "main-plan.md"), str(root / "main-plan-report-1.md")
            )
            data = read_json(process)
            self.assertEqual(process.returncode, 0, data)
            self.assertEqual(data["units_extracted"], 2)
            self.assertEqual(data["plan_ids"], ["stg01", "stg02"])
            self.assertEqual(data["covered"], ["stg01", "stg02"])
            self.assertEqual(data["uncovered"], [])

    def test_full_coverage_exit_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root / "main-plan.md", "## 1. Phase\n- 1.1 Do thing\n- 1.2 Other thing\n")
            report = valid_report().replace(
                "- ✅ 1. Подготовка",
                "- ✅ 1. Phase\n  - ⚠️ 1.1 Do thing\n  - ⭕️ 1.2 Other thing",
            )
            write(root / "main-plan-report-1.md", report)
            process = run_tool(
                "task-census", str(root / "main-plan.md"), str(root / "main-plan-report-1.md")
            )
            data = read_json(process)
            self.assertEqual(process.returncode, 0, data)
            self.assertEqual(data["uncovered"], [])
            self.assertGreaterEqual(data["units_extracted"], 3)

    def test_uncovered_exit_one_lists_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root / "main-plan.md", "## 1. Phase\n- 1.1 Done\n- 1.2 Missing\n")
            report = valid_report().replace(
                "- ✅ 1. Подготовка", "- ✅ 1. Phase\n  - ⚠️ 1.1 Done"
            )
            write(root / "main-plan-report-1.md", report)
            process = run_tool(
                "task-census", str(root / "main-plan.md"), str(root / "main-plan-report-1.md")
            )
            data = read_json(process)
            self.assertEqual(process.returncode, 1, data)
            self.assertIn("1.2", data["uncovered"])
            self.assertNotIn("1.1", data["uncovered"])


if __name__ == "__main__":
    unittest.main()
