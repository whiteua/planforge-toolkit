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

- ✅ 1. Подготовка evidence_anchor: src/app.py#L1-L3

## Список ошибок

{issue_block}

## Задача

План реализован полностью; дальнейших действий не требуется.
"""


def report_with_closed_task(final: bool, task_line: str) -> str:
    base = valid_report(final=final)
    return base.replace("- ✅ 1. Подготовка evidence_anchor: src/app.py#L1-L3", "- ✅ 1. Phase\n  " + task_line)


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

    def test_bootstrap_language_empty_plan_defaults_en(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root / "main-plan.md", "1. 2. 3.\n")
            data = read_json(run_tool("bootstrap", str(root), "main-plan.md"))
            self.assertEqual(data["language"], "en")

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
            # Probe side effects (tool caches) must not count as workspace mutations.
            write(root / ".pytest_cache" / "v" / "nodeids", "[]")
            write(root / ".mypy_cache" / "3.12" / "x.json", "{}")
            write(root / ".eslintcache", "{}")
            write(root / "tsconfig.tsbuildinfo", "{}")
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


class AnchorVerificationTests(unittest.TestCase):
    def _root(self, tmp: str) -> Path:
        root = Path(tmp)
        write(root / "src" / "app.py", "\n".join(f"line {i}" for i in range(1, 21)) + "\n")
        return root

    def test_valid_anchor_passes_with_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            report = root / "main-plan-report-2-final.md"
            write(report, report_with_closed_task(True, "- ✅ 1.1 Done evidence_anchor: src/app.py#L10-L20"))
            process = run_tool("validate-report", str(report), "--root", str(root))
            self.assertEqual(process.returncode, 0, read_json(process))

    def test_missing_file_and_out_of_range_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            report = root / "main-plan-report-1.md"
            write(report, report_with_closed_task(False, "- ✅ 1.1 Done evidence_anchor: src/nope.py#L1-L2"))
            data = read_json(run_tool("validate-report", str(report), "--root", str(root)))
            self.assertFalse(data["valid"])
            self.assertTrue(any("anchor file not found" in e for e in data["errors"]), data)
            write(report, report_with_closed_task(False, "- ✅ 1.1 Done evidence_anchor: src/app.py#L15-L99"))
            data = read_json(run_tool("validate-report", str(report), "--root", str(root)))
            self.assertTrue(any("beyond end of file" in e for e in data["errors"]), data)

    def test_issue_evidence_is_verified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            report = root / "main-plan-report-1.md"
            write(report, issues_report([("⭕️ not-fixed", "high", "Bug A")]).replace("**evidence**: src/app.py#L1-L3", "**evidence**: src/ghost.py#L1-L3"))
            data = read_json(run_tool("validate-report", str(report), "--root", str(root)))
            self.assertTrue(any("issue 1: anchor file not found" in e for e in data["errors"]), data)

    def test_closed_leaf_phase_needs_anchor_in_final(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "main-plan-report-2-final.md"
            write(report, valid_report(final=True).replace(" evidence_anchor: src/app.py#L1-L3", ""))
            data = read_json(run_tool("validate-report", str(report)))
            self.assertTrue(any("task '1' with ✅ is missing an evidence anchor" in e for e in data["errors"]), data)


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

    def test_final_with_sub_bullet_anchor_passes(self) -> None:
        # The documented format: the anchor on an indented detail line under the task.
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "main-plan-report-2-final.md"
            write(report, report_with_closed_task(True, "- ✅ 1.1 Done\n    - evidence_anchor: src/x.py#L10-L20"))
            process = run_tool("validate-report", str(report))
            data = read_json(process)
            self.assertEqual(process.returncode, 0, data)

    def test_title_with_yo_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "main-plan-report-1.md"
            write(report, valid_report().replace("# Отчет о выполнении плана 1", "# Отчёт о выполнении плана 1"))
            process = run_tool("validate-report", str(report))
            self.assertEqual(process.returncode, 0, read_json(process))

    def test_validate_missing_file_exit_2(self) -> None:
        process = run_tool("validate-report", "no/such/report.md")
        self.assertEqual(process.returncode, 2)

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
                "| a | Scaffold | - |\n"
                "| b | Ledger | a |\n",
            )
            report = valid_report().replace(
                "- ✅ 1. Подготовка",
                "- ✅ a: Scaffold done\n"
                "- ✅ b: Ledger done",
            )
            write(root / "main-plan-report-1.md", report)
            process = run_tool(
                "task-census", str(root / "main-plan.md"), str(root / "main-plan-report-1.md")
            )
            data = read_json(process)
            self.assertEqual(process.returncode, 0, data)
            self.assertEqual(data["units_extracted"], 2)
            self.assertEqual(data["plan_ids"], ["a", "b"])
            self.assertEqual(data["covered"], ["a", "b"])
            self.assertEqual(data["uncovered"], [])

    def test_numbered_prose_is_not_a_unit_in_structured_plans(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root / "main-plan.md", "### Task 1: A\n\nSteps:\n1. do x\n2. do y\n\n### Task 2: B\n\n- 3. not a task\n")
            report = valid_report().replace("- ✅ 1. Подготовка", "- ✅ 1 A done\n- ✅ 2 B done")
            write(root / "main-plan-report-1.md", report)
            data = read_json(run_tool("task-census", str(root / "main-plan.md"), str(root / "main-plan-report-1.md")))
            self.assertEqual(data["plan_ids"], ["1", "2"])
            self.assertEqual(data["uncovered"], [])

    def test_task_heading_separators_match_executor(self) -> None:
        # "Task 1.2 —" used to be truncated to id "1" by regex backtracking.
        import importlib.util
        spec = importlib.util.spec_from_file_location("resolver_tool", str(ROOT / "scripts" / "resolver_tool.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        extract = module.extract_plan_task_ids
        text = (
            "### Task 1.1: colon\n### Task 1.2 — em dash\n### Задача 2.2: ru\n"
            "#### Task 2.3 - hyphen\n### Task 3. dot\n## A note\n## a: part heading\n"
        )
        self.assertEqual(extract(text), ["1.1", "1.2", "2.2", "2.3", "3", "a"])

    def test_plan_writing_task_headings_skip_code_fences(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(
                root / "main-plan.md",
                "# Plan\n\n### Task 1: Parse flag\n\n```markdown\n## Task 9: file content\n1. not a task\n```\n\n"
                "### Task 1.1: Docs\n\n### Задача 2: Проверка\n",
            )
            report = valid_report().replace(
                "- ✅ 1. Подготовка", "- ✅ 1 Parse flag\n  - ✅ 1.1 Docs\n- ⚠️ 2 Проверка"
            )
            write(root / "main-plan-report-1.md", report)
            process = run_tool(
                "task-census", str(root / "main-plan.md"), str(root / "main-plan-report-1.md")
            )
            data = read_json(process)
            self.assertEqual(process.returncode, 0, data)
            self.assertEqual(data["plan_ids"], ["1", "1.1", "2"])

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


def issues_report(issues: list, n: int = 1, extra: str = "") -> str:
    """issues: list of (status, level, title) tuples."""
    blocks = []
    for idx, (status, level, title) in enumerate(issues, start=1):
        blocks.append(
            f"""{idx}) Ошибка {idx}: {status} | {level} | {title}
- **level**: {level}
- **status**: {status}
- **title**: {title}
- **origin**: carry
- **evidence**: src/app.py#L{idx}-L{idx + 2}
- **description**: {LONG_DESCRIPTION}
- **recommendations**: Исправить {title}."""
        )
    body = "\n\n".join(blocks) or "Ошибок не найдено."
    return valid_report().replace(valid_report().split("## Список ошибок\n\n", 1)[1].split("\n\n## Задача", 1)[0], body).replace(
        "# Отчет о выполнении плана 1", f"# Отчет о выполнении плана {n}"
    ) + extra


class SnapshotDiffTests(unittest.TestCase):
    def test_lists_added_removed_modified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root = Path(tmp)
            write(root / "a.py", "a")
            write(root / "b.py", "b")
            before = Path(outside) / "before.json"
            after = Path(outside) / "after.json"
            self.assertEqual(run_tool("fingerprint-workspace", str(root), str(before)).returncode, 0)
            write(root / "a.py", "a2")
            (root / "b.py").unlink()
            write(root / "c.py", "c")
            self.assertEqual(run_tool("fingerprint-workspace", str(root), str(after)).returncode, 0)
            data = read_json(run_tool("snapshot-diff", str(before), str(after)))
            self.assertEqual((data["added"], data["removed"], data["modified"]), (["c.py"], ["b.py"], ["a.py"]))


class MarkFixLineEndings(unittest.TestCase):
    def test_crlf_report_keeps_crlf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "main-plan-report-1.md"
            text = issues_report([("⭕️ not-fixed", "high", "Bug A")]).replace("\n", "\r\n")
            report.write_bytes(text.encode("utf-8"))
            process = run_tool("mark-fix", str(report), "1", "applied", "--note", "done")
            self.assertEqual(process.returncode, 0, read_json(process))
            raw = report.read_bytes()
            self.assertEqual(raw.count(b"\r\n"), raw.count(b"\n"))
            self.assertIn("Ошибка 1: applied".encode("utf-8"), raw)

    def test_lf_report_keeps_lf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "main-plan-report-1.md"
            report.write_bytes(issues_report([("⭕️ not-fixed", "high", "Bug A")]).encode("utf-8"))
            self.assertEqual(run_tool("mark-fix", str(report), "1", "applied").returncode, 0)
            self.assertNotIn(b"\r\n", report.read_bytes())


class FixLoopToolTests(unittest.TestCase):
    def test_fingerprint_base_reuses_unchanged_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as snaps:
            root = Path(tmp)
            write(root / "a.txt", "a\n")
            write(root / "b.txt", "b\n")
            start = Path(snaps) / "start.json"
            data = read_json(run_tool("fingerprint-workspace", str(root), str(start)))
            self.assertEqual((data["hashed"], data["base_used"]), (2, False))
            write(root / "b.txt", "bb changed\n")
            current = Path(snaps) / "current.json"
            data = read_json(run_tool("fingerprint-workspace", str(root), str(current), "--base", str(start)))
            self.assertEqual((data["hashed"], data["base_used"]), (1, True))
            process = run_tool("assert-readonly", str(start), str(current), "a.txt")
            self.assertEqual(read_json(process)["violations"], ["b.txt"])

    def test_parse_report_missing_file_is_exit_two(self) -> None:
        self.assertEqual(run_tool("parse-report", "no-such-report-1.md").returncode, 2)

    def test_bootstrap_prefills_report_header(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root / "docs" / "main-plan.md", "# Main\n")
            report1 = root / "docs" / "main-plan-report-1.md"
            write(report1, valid_report())
            data = read_json(run_tool("bootstrap", str(root), "docs/main-plan.md", "docs/main-plan-report-1.md"))
            header = data["report_header"]
            self.assertEqual(header["master_plan_path"], "main-plan.md")
            self.assertEqual(header["audit_iteration"], 2)
            self.assertEqual(header["previous_report_path"], "main-plan-report-1.md")
            self.assertEqual(header["previous_report_sha256"], sha256(report1))
            self.assertEqual(header["consecutive_open_invocations_if_open"], 2)
            self.assertEqual(header["consecutive_open_invocations_if_final"], 0)

    def test_discover_by_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root / "main-plan.md", "# Main\n")
            data = read_json(run_tool("discover", str(root), "main-plan.md"))
            self.assertEqual((data["state"], data["plans_list"]), ("none", ["main-plan.md"]))
            write(root / "main-plan-report-2.md", valid_report())
            write(root / "main-plan-report-1.md", valid_report())
            write(root / "other-report-1.md", valid_report())
            data = read_json(run_tool("discover", str(root), "main-plan.md"))
            self.assertEqual(data["state"], "open")
            self.assertEqual(data["plans_list"], ["main-plan.md", "main-plan-report-1.md", "main-plan-report-2.md"])
            write(root / "main-plan-report-3-final.md", valid_report(final=True))
            self.assertEqual(read_json(run_tool("discover", str(root), "main-plan.md"))["state"], "closed")

    def test_discover_workspace_finds_single_open_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root / "a" / "alpha.md", "# A\n")
            write(root / "a" / "alpha-report-1.md", valid_report())
            write(root / "b" / "beta.md", "# B\n")
            write(root / "b" / "beta-report-1-final.md", valid_report(final=True))
            process = run_tool("discover", str(root))
            data = read_json(process)
            self.assertEqual(process.returncode, 0, data)
            self.assertEqual(data["candidates"], [{"master_plan": "a/alpha.md", "last_report": "a/alpha-report-1.md"}])
            write(root / "c" / "gamma.md", "# C\n")
            write(root / "c" / "gamma-report-1.md", valid_report())
            process = run_tool("discover", str(root))
            self.assertEqual(process.returncode, 1)
            self.assertEqual(len(read_json(process)["candidates"]), 2)

    def test_open_issues_orders_by_severity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "main-plan-report-1.md"
            write(report, issues_report([
                ("⭕️ not-fixed", "low", "Косметика"),
                ("✅ fixed", "critical", "Уже закрыто"),
                ("⚠️ regressed", "high", "Регрессия"),
            ]))
            data = read_json(run_tool("open-issues", str(report)))
            self.assertEqual(data["open_count"], 2)
            self.assertEqual(data["fix_order"], [3, 1])
            self.assertEqual(data["issues"][0]["evidence"], "src/app.py#L1-L3")
            self.assertEqual(data["language"], "ru")

    def test_protect_and_assert_protected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as snaps:
            plan = Path(tmp) / "main-plan.md"
            write(plan, "# Main\n")
            snapshot = Path(snaps) / "protect.json"
            self.assertEqual(run_tool("protect", str(snapshot), str(plan)).returncode, 0)
            self.assertEqual(run_tool("assert-protected", str(snapshot)).returncode, 0)
            write(plan, "# Main edited\n")
            process = run_tool("assert-protected", str(snapshot))
            self.assertEqual(process.returncode, 1)
            data = read_json(process)
            self.assertEqual(len(data["modified"]), 1)
            self.assertTrue(data["modified"][0].endswith("main-plan.md"))
            plan.unlink()
            self.assertEqual(len(read_json(run_tool("assert-protected", str(snapshot)))["removed"]), 1)

    def test_mark_fix_upserts_fix_log_and_keeps_report_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "main-plan-report-1.md"
            write(report, issues_report([("⭕️ not-fixed", "high", "A"), ("⭕️ not-fixed", "low", "B")]))
            process = run_tool("mark-fix", str(report), "1", "applied", "--files", "src/app.py", "--note", "done")
            self.assertEqual(process.returncode, 0, read_json(process))
            self.assertEqual(run_tool("mark-fix", str(report), "2", "needs-user", "--note", "plan contradicts").returncode, 0)
            process = run_tool("mark-fix", str(report), "1", "skipped")
            self.assertEqual(read_json(process)["action"], "updated")
            text = report.read_text(encoding="utf-8")
            self.assertEqual(text.count("## Журнал исправлений"), 1)
            self.assertIn("- Ошибка 1: skipped\n", text)
            self.assertIn("- Ошибка 2: needs-user | note: plan contradicts", text)
            self.assertEqual(run_tool("validate-report", str(report)).returncode, 0)
            self.assertEqual(run_tool("mark-fix", str(report), "9", "applied").returncode, 1)

    def test_mark_fix_rejects_final_and_fixed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            final = Path(tmp) / "main-plan-report-1-final.md"
            write(final, valid_report(final=True))
            self.assertEqual(run_tool("mark-fix", str(final), "1", "applied").returncode, 1)
            report = Path(tmp) / "main-plan-report-2.md"
            write(report, issues_report([("✅ fixed", "high", "A")]))
            self.assertEqual(run_tool("mark-fix", str(report), "1", "applied").returncode, 1)

    def cycle(self, prev_issues: list, new_issues: list, cycle: int, limit: int = 2, final: bool = False, log: str = "") -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            prev = Path(tmp) / "main-plan-report-1.md"
            write(prev, issues_report(prev_issues, extra=log))
            new = Path(tmp) / ("main-plan-report-2-final.md" if final else "main-plan-report-2.md")
            write(new, issues_report(new_issues, n=2))
            process = run_tool("cycle-check", str(prev), str(new), str(cycle), str(limit))
            self.assertEqual(process.returncode, 0, process.stdout)
            return read_json(process)

    def test_cycle_check_actions(self) -> None:
        open_a, open_b = ("⭕️ not-fixed", "high", "A"), ("⭕️ not-fixed", "low", "B")
        fixed_a, fixed_b = ("✅ fixed", "high", "A"), ("✅ fixed", "low", "B")
        self.assertEqual(self.cycle([open_a], [fixed_a], 1, final=True)["action"], "complete")
        self.assertEqual(self.cycle([open_a, open_b], [fixed_a, open_b], 1)["action"], "continue")
        self.assertEqual(self.cycle([open_a, open_b], [fixed_a, open_b], 2)["action"], "stop-limit")
        stalled = self.cycle([open_a], [open_a], 1, log="\n## Журнал исправлений\n\n- Ошибка 1: applied\n")
        self.assertEqual(stalled["action"], "stop-stalled")
        self.assertEqual(stalled["claimed_not_fixed_ids"], [1])
        ask = self.cycle([open_a, open_b], [fixed_a, open_b], 1, log="\n## Журнал исправлений\n\n- Ошибка 2: needs-user\n")
        self.assertEqual((ask["action"], ask["needs_user_ids"]), ("ask-user", [2]))
        # already-fixed carry-over issues do not count as progress of this cycle
        self.assertEqual(self.cycle([fixed_a, open_b], [fixed_a, open_b], 1)["action"], "stop-stalled")


if __name__ == "__main__":
    unittest.main()
