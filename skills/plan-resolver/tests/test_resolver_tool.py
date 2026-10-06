from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import shutil
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
    # write_bytes keeps "\n" as written; Path.write_text(newline=...) needs Python 3.10
    path.write_bytes(content.encode("utf-8"))


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
            write(root / ".git" / "index", "refreshed by git status")  # .git is never part of the snapshot
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


PLAN_WITH_CHECKPOINT = (
    "### Task 1: Code\n\n**Files:**\n- Modify: `src/app.py:1-3`\n- Test: `tests/test_app.py`\n\n"
    "### Task 2: Checkpoint — offline suites\n\n- [ ] **Step 1:** Run: `npm test`\n\n**Done when:** green\n\n"
    "### Task 3: Tests only\n\n**Files:**\n- Test: `tests/test_more.py`\n"
)


class EvidenceProbeTests(unittest.TestCase):
    def _report(self, tmp: str, stages: str) -> Path:
        root = Path(tmp)
        write(root / "main-plan.md", PLAN_WITH_CHECKPOINT)
        report = root / "main-plan-report-1-final.md"
        write(report, valid_report(final=True).replace("- ✅ 1. Подготовка evidence_anchor: src/app.py#L1-L3", stages))
        return report

    def test_census_reports_code_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = self._report(tmp, "- ✅ 1. a\n- ✅ 2. b\n- ✅ 3. c")
            data = read_json(run_tool("task-census", str(Path(tmp) / "main-plan.md"), str(report)))
            self.assertEqual(data["code_tasks"], ["1"])

    def test_probe_closes_a_checkpoint_but_not_a_code_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan = str(Path(tmp) / "main-plan.md")
            good = self._report(
                tmp,
                "- ✅ 1. Code evidence_anchor: src/app.py#L1-L3\n"
                "- ✅ 2. Checkpoint\n  - evidence_probe: npm test → exit 0\n"
                "- ✅ 3. Tests only evidence_probe: node dist/test-more.js → exit 0",
            )
            data = read_json(run_tool("validate-report", str(good), "--plan", plan))
            self.assertTrue(data["valid"], data)
            self.assertEqual(data["summary"]["probe_closed"], ["2", "3"])

            bad = self._report(tmp, "- ✅ 1. Code evidence_probe: npm test → exit 0\n- ✅ 2. x evidence_probe: a → 0\n- ✅ 3. y evidence_probe: a → 0")
            data = read_json(run_tool("validate-report", str(bad), "--plan", plan))
            self.assertFalse(data["valid"])
            self.assertTrue(any("task '1' changes code in the plan" in e for e in data["errors"]), data)

    def test_executor_reported_is_listed_as_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = self._report(
                tmp,
                "- ✅ 1. Code evidence_anchor: src/app.py#L1-L3\n"
                "- ✅ 2. Smoke on the database evidence_probe: npm run smoke → exit 0 verification: executor-reported\n"
                "- ✅ 3. c evidence_probe: a → 0",
            )
            data = read_json(run_tool("validate-report", str(report)))
            self.assertTrue(data["valid"], data)
            self.assertEqual(data["summary"]["executor_reported"], ["2"])
            self.assertTrue(any("not re-verified by this audit: 2" in w for w in data["warnings"]), data)


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
    def test_fingerprint_base_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as snaps:
            root = Path(tmp)
            write(root / "a.txt", "a\n")
            write(root / "b.txt", "b\n")
            start = Path(snaps) / "start.json"
            data = read_json(run_tool("fingerprint-workspace", str(root), str(start)))
            self.assertEqual((data["origin"], data["entry_count"], data["warnings"]), ("walk", 2, []))
            write(root / "b.txt", "bb changed\n")
            current = Path(snaps) / "current.json"
            data = read_json(run_tool("fingerprint-workspace", str(root), str(current), "--base", str(start)))
            self.assertEqual(data["warnings"], ["base-ignored"])
            process = run_tool("assert-readonly", str(start), str(current), "a.txt")
            self.assertEqual(read_json(process)["violations"], ["b.txt"])

    def test_assert_readonly_accepts_several_allowed_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as snaps:
            root = Path(tmp)
            write(root / "plan.md", "# Plan\n")
            write(root / "BACKLOG.md", "# Backlog\n")
            start = Path(snaps) / "start.json"
            current = Path(snaps) / "current.json"
            self.assertEqual(run_tool("fingerprint-workspace", str(root), str(start)).returncode, 0)
            write(root / "plan-report-1.md", "report\n")
            write(root / "BACKLOG.md", "# Backlog\n\n## plan\n\n- [ ] x — plan-resolver, plan.md, 2026-10-01\n")
            self.assertEqual(run_tool("fingerprint-workspace", str(root), str(current)).returncode, 0)
            process = run_tool("assert-readonly", str(start), str(current), "plan-report-1.md", "BACKLOG.md")
            data = read_json(process)
            self.assertEqual(process.returncode, 0, data)
            self.assertEqual(data["allowed_paths"], ["plan-report-1.md", "BACKLOG.md"])
            write(root / "plan.md", "# Changed\n")
            self.assertEqual(run_tool("fingerprint-workspace", str(root), str(current)).returncode, 0)
            process = run_tool("assert-readonly", str(start), str(current), "plan-report-1.md", "BACKLOG.md")
            data = read_json(process)
            self.assertEqual(process.returncode, 1, data)
            self.assertEqual(data["violations"], ["plan.md"])

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
            self.assertEqual(data["stuck_open"], {"consecutive_if_open": 2, "limit": 5, "ask_required": False})
            self.assertRegex(header["audited_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_bootstrap_stuck_open_at_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root / "main-plan.md", "# Main\n")
            report = valid_report().replace("audit_iteration: 1", "audit_iteration: 4").replace(
                "consecutive_open_invocations: 1", "consecutive_open_invocations: 4"
            )
            for n in range(1, 5):
                write(root / f"main-plan-report-{n}.md", report)
            data = read_json(run_tool("bootstrap", str(root), "main-plan.md", *[f"main-plan-report-{n}.md" for n in range(1, 5)]))
            self.assertTrue(data["stuck_open"]["ask_required"])
            self.assertEqual(data["stuck_open"]["consecutive_if_open"], 5)

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


class SharedTaskParserTests(unittest.TestCase):
    """Contract plans take their ids from brainstorm_tool.parse_plan_tasks; others keep the local parse."""

    FIXTURE = ROOT.parent / "plan-writing" / "tests" / "fixtures" / "plan01-impl.md"

    def load(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("resolver_tool", str(TOOL))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_local_parse_matches_on_the_reference_plan(self) -> None:
        module = self.load()
        text = self.FIXTURE.read_text(encoding="utf-8")
        shared = (module.extract_plan_task_ids(text), module.plan_code_task_ids(text))
        module._load_brainstorm_tool = lambda: None
        self.assertEqual((module.extract_plan_task_ids(text), module.plan_code_task_ids(text)), shared)
        self.assertEqual(shared, (["1", "1.1", "2"], ["1", "1.1"]))

    def test_contract_plan_ignores_other_numbered_headings(self) -> None:
        module = self.load()
        text = ("# P\n\n## A. Overview\n\n### Task 1: Code\n\n**Files:**\n- Modify: `src/a.py`\n\n"
                "### Task 2: Tests\n\n**Files:**\n- Test: `tests/test_a.py`\n")
        self.assertEqual((module.extract_plan_task_ids(text), module.plan_code_task_ids(text)), (["1", "2"], ["1"]))
        module._load_brainstorm_tool = lambda: None
        self.assertEqual(module.extract_plan_task_ids(text), ["a", "1", "2"])


def load_resolver():
    """resolver_tool.py as a module (the script is not a package)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("resolver_tool", str(TOOL))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class StubLineTests(unittest.TestCase):
    """carry-forward stubs (`- 12.1 Title <!-- reaudit -->`) keep their id and title for the census and the validator."""

    def test_html_comments_do_not_hide_the_id_or_the_title(self) -> None:
        module = load_resolver()
        self.assertEqual(module.extract_stage_id("  - 12.1 Child <!-- reaudit -->"), "12.1")
        self.assertEqual(module.extract_stage_id("- <!-- reaudit --> 40. Title"), "40")
        self.assertEqual(module.clean_stage_title("- 40. Title <!-- reaudit -->", ""), "Title")
        self.assertEqual(module.clean_stage_title("  - 12.1 Child <!-- reaudit -->", ""), "Child")
        self.assertEqual(module.SECTION_ALIASES["evidence"], ("## Отпечаток улик", "## Evidence fingerprint"))


def scoped_report(fields: str, final: bool = False) -> str:
    """valid_report with frontmatter lines added after `language` (e.g. audit_scope, audit_tasks)."""
    return valid_report(final=final).replace("language: ru\n", "language: ru\n" + fields)


class AuditScopeFieldTests(unittest.TestCase):
    """audit_scope / audit_tasks in the frontmatter (spec 6): validated, optional for old reports."""

    def validate(self, name: str, text: str, *extra: str) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / name
            write(report, text)
            write(Path(tmp) / "main-plan.md", "### Task 1: A\n\n### Task 1.1: B\n\n### Task 2: C\n")
            args = [arg.replace("{plan}", str(Path(tmp) / "main-plan.md")) for arg in extra]
            return read_json(run_tool("validate-report", str(report), *args))

    def test_old_report_without_fields_is_valid_and_read_as_full(self) -> None:
        data = self.validate("main-plan-report-1.md", valid_report())
        self.assertTrue(data["valid"], data)
        self.assertIn("[WARNING] audit_scope is missing: the report is read as a full pass", data["warnings"])

    def test_scope_and_task_forms(self) -> None:
        for fields in ("audit_scope: full\naudit_tasks: all\n", "audit_scope: incremental\naudit_tasks: [1, 1.1]\n",
                       "audit_scope: incremental\naudit_tasks: []\n"):
            data = self.validate("main-plan-report-1.md", scoped_report(fields), "--plan", "{plan}")
            self.assertTrue(data["valid"], (fields, data))
            self.assertFalse(any("audit_scope" in w for w in data["warnings"]), data)
        data = self.validate("main-plan-report-1.md", scoped_report("audit_scope: partial\n"))
        self.assertIn("audit_scope must be full or incremental", data["errors"])
        for tasks in ("1, 2", "[1, x y]", "[1;2]"):
            data = self.validate("main-plan-report-1.md", scoped_report(f"audit_scope: incremental\naudit_tasks: {tasks}\n"))
            self.assertIn("audit_tasks must be all or a list of task ids like [7, 8, 12.1]", data["errors"], tasks)

    def test_audit_tasks_must_name_plan_tasks(self) -> None:
        text = scoped_report("audit_scope: incremental\naudit_tasks: [1, 9, 1.1]\n")
        data = self.validate("main-plan-report-1.md", text, "--plan", "{plan}")
        self.assertIn("audit_tasks names tasks the plan does not have: 9", data["errors"])
        self.assertTrue(self.validate("main-plan-report-1.md", text)["valid"])  # without --plan ids are not checked

    def test_incremental_without_tasks_warns(self) -> None:
        data = self.validate("main-plan-report-1.md", scoped_report("audit_scope: incremental\n"))
        self.assertTrue(data["valid"], data)
        self.assertIn(
            "[WARNING] audit_scope: incremental without audit_tasks: run-stats counts this pass as full", data["warnings"]
        )

    def test_open_incremental_report_without_issues_and_zero_counter_is_valid(self) -> None:
        # everything closed after an incremental pass: an open report (not -final) with the counter reset
        text = scoped_report("audit_scope: incremental\naudit_tasks: [1]\n", final=True)
        self.assertIn("consecutive_open_invocations: 0", text)
        data = self.validate("main-plan-report-2.md", text)
        self.assertTrue(data["valid"], data)


class FinalReportScopeTests(unittest.TestCase):
    """`-final` only after a full pass: an incremental pass never closes the plan."""

    def test_final_report_requires_a_full_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "main-plan-report-2-final.md"
            write(report, scoped_report("audit_scope: incremental\naudit_tasks: [1]\n", final=True))
            data = read_json(run_tool("validate-report", str(report)))
            self.assertIn("final report requires a full pass (audit_scope: full)", data["errors"])
            write(report, scoped_report("audit_scope: full\naudit_tasks: all\n", final=True))
            data = read_json(run_tool("validate-report", str(report)))
            self.assertTrue(data["valid"], data)


EVIDENCE_OK = (
    "\n## Отпечаток улик\n\n| File | SHA-256 |\n|---|---|\n"
    f"| src/app.py | {'c' * 64} |\n| notes/local.md | excluded |\n| src/gone.py | missing |\n"
)


class PlaceholderAndEvidenceRowTests(unittest.TestCase):
    """validate-report rejects unfilled carry-forward markers and malformed evidence rows."""

    def validate(self, text: str) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "main-plan-report-2.md"
            write(report, text)
            return read_json(run_tool("validate-report", str(report)))

    def test_unfilled_stub_and_unverified_issue_are_errors(self) -> None:
        stub = valid_report().replace(
            "- ✅ 1. Подготовка evidence_anchor: src/app.py#L1-L3", "- 1. Подготовка <!-- reaudit -->"
        )
        data = self.validate(stub)
        self.assertIn("unfilled placeholder <!-- reaudit -->: 1 left", data["errors"])
        reverify = valid_report().replace("| Невыполненный контракт\n", "| Невыполненный контракт <!-- re-verify -->\n")
        data = self.validate(reverify)
        self.assertIn("unfilled placeholder <!-- re-verify -->: 1 left", data["errors"])

    def test_evidence_rows(self) -> None:
        data = self.validate(valid_report() + EVIDENCE_OK)
        self.assertTrue(data["valid"], data)
        for bad in (f"| src/app.py | {'c' * 63} |", "| src/app.py | changed |", "{{evidence_fingerprint}}", "| | missing |"):
            data = self.validate(valid_report() + EVIDENCE_OK + bad + "\n")
            self.assertTrue(any(e.startswith("evidence fingerprint row is malformed") and bad in e for e in data["errors"]), (bad, data))


INC_PLAN = (
    "# Plan\n\n"
    "### Task 1: Alpha\n\n**Files:**\n- Modify: `src/a.py`\n- Test: `tests/test_a.py`\n\n"
    "### Task 2: Beta\n\n**Files:**\n- Modify: `src/b.py`\n- Modify: `src/c.py`\n\n"
    "### Task 2.1: Beta docs\n\n**Files:**\n- Modify: `docs/b.md`\n- Modify: `B.lang`\n\n"
    "### Task 3: Checkpoint — suite\n\n- [ ] **Step 1:** Run: `pytest`\n\n**Done when:** green\n"
)
INC_FILES = {
    "src/a.py": "a1\na2\n",
    "src/b.py": "b1\nb2\n",
    "src/c.py": "c1\n",
    "tests/test_a.py": "t1\n",
    "docs/b.md": "d1\n",
    ".gitignore": "notes/\n",
    "notes/n.md": "local notes\n",
}
INC_STAGES = (
    "- ✅ 1. Alpha evidence_anchor: src/a.py#L1-L2\n"
    "  - evidence_anchor: tests/test_a.py#L1-L1\n"
    "- ✅ 2. Beta evidence_anchor: src/b.py#L1-L2\n"
    "  - ✅ 2.1 Beta docs evidence_anchor: docs/b.md#L1-L1\n"
    "- ✅ 3. Checkpoint — suite\n"
    "  - evidence_probe: pytest → exit 0"
)
INC_ISSUE = (
    "1) Ошибка 1: ⭕️ not-fixed | high | Beta breaks\n- **level**: high\n- **status**: ⭕️ not-fixed\n"
    "- **title**: Beta breaks\n- **linked_items**: 1\n- **origin**: new\n- **evidence**: src/a.py#L2-L2\n"
    f"- **description**: {LONG_DESCRIPTION}\n- **recommendations**: Исправить Alpha."
)


def inc_report(plan_sha: str, stages: str = INC_STAGES, issues: str = "Ошибок не найдено.", tail: str = "") -> str:
    """An open first report of INC_PLAN with the pass fields of spec 6."""
    return (
        "---\nmaster_plan_path: main-plan.md\n"
        f"master_plan_sha256: {plan_sha}\nmaster_plan_size: 1\naudited_at: 2026-10-04T10:00:00Z\n"
        "audit_iteration: 1\nconsecutive_open_invocations: 1\nprevious_report_path: null\n"
        "previous_report_sha256: null\nlanguage: ru\naudit_scope: full\naudit_tasks: all\n---\n"
        "# Отчет о выполнении плана 1\n\n## Основные стадии плана\n\n"
        f"{stages}\n\n## Список ошибок\n\n{issues}\n\n## Задача\n\nПроверить Alpha.\n{tail}"
    )


class EvidenceFileHelperTests(unittest.TestCase):
    """Which files are evidence: anchors per stage item and Files per plan task."""

    def test_anchor_files_per_stage_item_and_plan_files_per_task(self) -> None:
        module = load_resolver()
        self.assertEqual(module.anchor_path("`src/a.py#L1-L2"), "src/a.py")
        self.assertEqual(module.anchor_path("src\\a.py#L3"), "src/a.py")
        self.assertEqual(
            module.stage_anchor_paths(inc_report("a" * 64)),
            {"1": ["src/a.py", "tests/test_a.py"], "2": ["src/b.py"], "2.1": ["docs/b.md"], "3": []},
        )
        self.assertEqual(
            module.plan_task_files(INC_PLAN),
            {"1": ["src/a.py", "tests/test_a.py"], "2": ["src/b.py", "src/c.py"], "2.1": ["docs/b.md", "B.lang"], "3": []},
        )
        module._load_brainstorm_tool = lambda: None
        self.assertIsNone(module.plan_task_files(INC_PLAN))


class IncrementalFixture:
    """A workspace with INC_PLAN, its files and an open first report; snapshots live in a second temp dir."""

    def make(self, tmp: str, snaps: str, stages: str = INC_STAGES, issues: str = "Ошибок не найдено.", tail: str = ""):
        root = Path(tmp)
        write(root / "main-plan.md", INC_PLAN)
        for rel, body in INC_FILES.items():
            write(root / rel, body)
        report = root / "main-plan-report-1.md"
        write(report, inc_report(sha256(root / "main-plan.md"), stages, issues, tail))
        start = Path(snaps) / "start.json"
        process = run_tool("fingerprint-workspace", str(root), str(start))
        assert process.returncode == 0, process.stdout
        return root, report, start


class EvidenceValueTests(IncrementalFixture, unittest.TestCase):
    """The value of an evidence file: its SHA-256 at the moment of the call, or `missing` (spec 2 of 05)."""

    def test_evidence_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as snaps:
            root, _report, _start = self.make(tmp, snaps)
            module = load_resolver()
            self.assertEqual(module.evidence_value("src/a.py", str(root)), sha256(root / "src" / "a.py"))
            self.assertEqual(module.evidence_value("notes/n.md", str(root)), sha256(root / "notes" / "n.md"))  # ignored
            write(root / "src" / "a.py", "a1 changed\n")
            self.assertEqual(module.evidence_value("src/a.py", str(root)), sha256(root / "src" / "a.py"))  # hashed now
            self.assertEqual(module.evidence_value("src/ghost.py", str(root)), "missing")
            self.assertEqual(module.evidence_value("../" + Path(snaps).name + "/start.json", str(root)), "missing")


class EvidenceTableTests(IncrementalFixture, unittest.TestCase):
    """Evidence files of a report: stage anchors, issue evidence and the plan tasks' Files."""

    def test_table_covers_anchors_issue_evidence_and_plan_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as snaps:
            root, report, start = self.make(tmp, snaps, issues=INC_ISSUE)
            module = load_resolver()
            snapshot = json.loads(start.read_text(encoding="utf-8"))
            table, warnings = module.evidence_table(report.read_text(encoding="utf-8"), INC_PLAN, snapshot)
            self.assertEqual(sorted(table), ["docs/b.md", "src/a.py", "src/b.py", "src/c.py", "tests/test_a.py"])
            self.assertEqual(table["src/c.py"], sha256(root / "src" / "c.py"))  # only in a Files block
            self.assertNotIn("B.lang", table)  # a Files token that names no file is not evidence
            self.assertEqual(warnings, [])

    def test_ignored_and_missing_files(self) -> None:
        stages = INC_STAGES.replace("docs/b.md#L1-L1", "notes/n.md#L1-L1").replace("src/b.py#L1-L2", "src/ghost.py#L1-L2")
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as snaps:
            root, report, start = self.make(tmp, snaps, stages=stages)
            module = load_resolver()
            snapshot = json.loads(start.read_text(encoding="utf-8"))
            table, warnings = module.evidence_table(report.read_text(encoding="utf-8"), INC_PLAN, snapshot)
            self.assertEqual((table["notes/n.md"], table["src/ghost.py"]), (sha256(root / "notes" / "n.md"), "missing"))
            self.assertEqual(warnings, [])  # an ignored file is hashed like any other: no `excluded` any more

    def test_without_the_task_parser_only_anchors_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as snaps:
            _root, report, start = self.make(tmp, snaps)
            module = load_resolver()
            module._load_brainstorm_tool = lambda: None
            snapshot = json.loads(start.read_text(encoding="utf-8"))
            table, warnings = module.evidence_table(report.read_text(encoding="utf-8"), INC_PLAN, snapshot)
            self.assertNotIn("src/c.py", table)
            self.assertTrue(any(w.startswith("plan-files-unavailable") for w in warnings), warnings)


class PipelineFileTests(unittest.TestCase):
    """F10 of plan-refactoring-02: which paths are the pipeline's own files."""

    def test_backlog_at_the_root_and_chain_names_in_the_plan_folder(self) -> None:
        module = load_resolver()
        for path, plan_dir, expected in (("BACKLOG.md", "docs", True), ("docs/BACKLOG.md", "docs", False),
                                         ("docs/g-chain.json", "docs", True), ("docs/g-impl-review-2.md", "docs", True),
                                         ("api/openapi-spec.md", "docs", False), ("docs/notes.md", "docs", False),
                                         ("g-chain.json", "", True), ("docs/g-chain.json", None, False),
                                         (".BACKLOG.md.k2j3_x9a.tmp", None, True),  # spec 1 of plan-refactoring-05
                                         ("docs/.BACKLOG.md.k2j3_x9a.tmp", "docs", False),
                                         ("docs/.g-chain.json.ab12cd_3.tmp", "docs", True)):
            with self.subTest(path=path, plan_dir=plan_dir):
                self.assertIs(module.is_pipeline_file(path, plan_dir), expected)

    def test_plan_dir_of(self) -> None:
        module = load_resolver()
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as other:
            root = Path(tmp)
            write(root / "docs" / "p-impl.md", "x\n")
            write(root / "p-impl.md", "x\n")
            self.assertEqual(module.plan_dir_of(str(root / "docs" / "p-impl.md"), str(root)), "docs")
            self.assertEqual(module.plan_dir_of(str(root / "p-impl.md"), str(root)), "")
            self.assertIsNone(module.plan_dir_of(str(Path(other) / "p-impl.md"), str(root)))

    def test_chain_file_pattern_equals_the_executors(self) -> None:
        import importlib.util
        path = ROOT.parent / "plan-executor" / "scripts" / "executor_tool.py"
        spec = importlib.util.spec_from_file_location("executor_tool_for_resolver_test", str(path))
        executor = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(executor)
        self.assertEqual(load_resolver().CHAIN_FILE_RE.pattern, executor._CHAIN_FILE_RE.pattern)


PIPE_PLAN = (
    "# Plan\n\n"
    "### Task 1: Alpha\n\n**Files:**\n- Modify: `src/a.py`\n- Modify: `BACKLOG.md`\n- Modify: `g-chain.json`\n\n"
    "### Task 2: Beta\n\n**Files:**\n- Modify: `src/b.py`\n\n"
    "### Task 3: Gamma\n\n**Files:**\n- Modify: `docs/x-spec.md`\n"
)
PIPE_FILES = {
    "src/a.py": "a1\n",
    "src/b.py": "b1\n",
    "docs/x-spec.md": "x1\n",
    ".gitignore": "BACKLOG.md\n*-chain.json\n",
    "BACKLOG.md": "# Backlog\n",
    "g-chain.json": "{}\n",
}
PIPE_STAGES = (
    "- ✅ 1. Alpha evidence_anchor: src/a.py#L1-L1\n"
    "- ✅ 2. Beta evidence_anchor: src/b.py#L1-L1\n"
    "- ✅ 3. Gamma evidence_anchor: docs/x-spec.md#L1-L1"
)


class PipelineEvidenceTests(unittest.TestCase):
    """F10 of plan-refactoring-02: BACKLOG.md and the chain files in the plan's folder are never evidence; a file
    with a chain-like name elsewhere is."""

    def make(self, tmp: str, snaps: str):
        root = Path(tmp)
        write(root / "main-plan.md", PIPE_PLAN)
        for rel, body in PIPE_FILES.items():
            write(root / rel, body)
        report = root / "main-plan-report-1.md"
        write(report, inc_report(sha256(root / "main-plan.md"), PIPE_STAGES))
        start = Path(snaps) / "start.json"
        self.assertEqual(run_tool("fingerprint-workspace", str(root), str(start)).returncode, 0)
        return root, report, start

    def test_the_table_leaves_out_the_pipeline_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as snaps:
            root, report, start = self.make(tmp, snaps)
            snapshot = json.loads(start.read_text(encoding="utf-8"))
            table, warnings = load_resolver().evidence_table(report.read_text(encoding="utf-8"), PIPE_PLAN, snapshot,
                                                             str(root / "main-plan.md"))
            self.assertEqual(sorted(table), ["docs/x-spec.md", "src/a.py", "src/b.py"])
            self.assertEqual(warnings, [])
            process = run_tool("evidence-fingerprint", str(report), "--snapshot", str(start), "--plan",
                               str(root / "main-plan.md"))
            self.assertEqual((process.returncode, read_json(process)["missing"]), (0, []))
            self.assertNotIn("BACKLOG.md", report.read_text(encoding="utf-8"))

    def test_old_pipeline_rows_send_no_task_to_reaudit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as snaps:
            root, report, start = self.make(tmp, snaps)
            module = load_resolver()
            snapshot = json.loads(start.read_text(encoding="utf-8"))
            table, _ = module.evidence_table(report.read_text(encoding="utf-8"), PIPE_PLAN, snapshot)
            table.update({"BACKLOG.md": "excluded", "g-chain.json": "excluded"})  # rows written before F10
            text = module.put_evidence_section(report.read_text(encoding="utf-8"),
                                               module.render_evidence_section(table, ru=True))
            write(report, text)
            data = module.rescan_scope(str(root / "main-plan.md"), str(report), snapshot, 0.5)
            self.assertEqual((data["unverified_files"], data["reaudit"]), ([], []))
            self.assertEqual((data["scope"], data["reason"]), ("incremental", "0 of 3 tasks touched"))

    def test_a_chain_like_name_outside_the_plan_folder_is_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as snaps:
            root, report, start = self.make(tmp, snaps)
            self.assertEqual(run_tool("evidence-fingerprint", str(report), "--snapshot", str(start), "--plan",
                                      str(root / "main-plan.md")).returncode, 0)
            snapshot = json.loads(start.read_text(encoding="utf-8"))
            write(root / "docs" / "x-spec.md", "x2\n")  # changed after the last report
            data = load_resolver().rescan_scope(str(root / "main-plan.md"), str(report), snapshot, 0.5)
            self.assertEqual((data["changed_files"], data["reaudit"]), (["docs/x-spec.md"], ["3"]))


class EvidenceSectionTests(unittest.TestCase):
    """The evidence section: rendered in the report's language, replaced whole, placed before the Fix Log."""

    def test_render_and_place_the_section(self) -> None:
        module = load_resolver()
        section = module.render_evidence_section({"src/a.py": "c" * 64, "notes/n.md": "excluded"}, ru=True)
        self.assertEqual(
            section,
            "## Отпечаток улик\n\n| File | SHA-256 |\n|---|---|\n| src/a.py | " + "c" * 64 + " |\n| notes/n.md | excluded |\n",
        )
        english = module.render_evidence_section({}, ru=False)
        self.assertEqual(english, "## Evidence fingerprint\n\n| File | SHA-256 |\n|---|---|\n")
        report = "# R\n\n## Задача\n\nX.\n"
        appended = module.put_evidence_section(report, section)
        self.assertEqual(appended, report + "\n" + section)
        self.assertEqual(module.put_evidence_section(appended, english), report + "\n" + english)
        log = "## Журнал исправлений\n\n- Ошибка 1: applied\n"
        placed = module.put_evidence_section(report + "\n" + log, section)
        self.assertEqual(placed, report + "\n" + section + "\n" + log)
        self.assertEqual(module.put_evidence_section(placed, section), placed)


class EvidenceFingerprintCommandTests(IncrementalFixture, unittest.TestCase):
    """`evidence-fingerprint <report> --snapshot <start> --plan <plan>` writes the section in place."""

    def run_evidence(self, report: Path, start: Path, plan: Path) -> subprocess.CompletedProcess:
        return run_tool("evidence-fingerprint", str(report), "--snapshot", str(start), "--plan", str(plan))

    def test_section_is_appended_then_replaced_whole(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as snaps:
            root, report, start = self.make(tmp, snaps)
            process = self.run_evidence(report, start, root / "main-plan.md")
            data = read_json(process)
            self.assertEqual(process.returncode, 0, data)
            self.assertEqual((data["file_count"], data["missing"]), (5, []))
            self.assertNotIn("excluded", data)
            text = report.read_text(encoding="utf-8")
            self.assertTrue(text.endswith(f"| tests/test_a.py | {sha256(root / 'tests' / 'test_a.py')} |\n"), text)
            self.assertIn("\n## Отпечаток улик\n\n| File | SHA-256 |\n|---|---|\n| docs/b.md | ", text)
            self.assertEqual(self.run_evidence(report, start, root / "main-plan.md").returncode, 0)
            self.assertEqual(report.read_text(encoding="utf-8"), text)  # replaced, not appended twice
            self.assertTrue(read_json(run_tool("validate-report", str(report), "--root", str(root)))["valid"])

    def test_english_report_and_crlf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as snaps:
            root, report, start = self.make(tmp, snaps)
            report.write_bytes(report.read_bytes().replace(b"language: ru", b"language: en").replace(b"\n", b"\r\n"))
            self.assertEqual(self.run_evidence(report, start, root / "main-plan.md").returncode, 0)
            raw = report.read_bytes()
            self.assertIn(b"\r\n## Evidence fingerprint\r\n", raw)
            self.assertEqual(raw.count(b"\r\n"), raw.count(b"\n"))

    def test_bad_snapshot_is_exit_two(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as snaps, tempfile.TemporaryDirectory() as other:
            root, report, _start = self.make(tmp, snaps)
            foreign = Path(snaps) / "other.json"
            self.assertEqual(run_tool("fingerprint-workspace", other, str(foreign)).returncode, 0)
            process = self.run_evidence(report, foreign, root / "main-plan.md")
            self.assertEqual(process.returncode, 2, process.stdout)
            self.assertTrue(read_json(process)["errors"][0].startswith("snapshot-root-mismatch"))
            self.assertEqual(self.run_evidence(report, root / "main-plan.md", root / "main-plan.md").returncode, 2)


class RescanHelperTests(unittest.TestCase):
    """Helpers of rescan-scope: the evidence table of a report, parents, linked items, stub titles."""

    def test_helpers(self) -> None:
        module = load_resolver()
        self.assertEqual(module.parse_evidence_table(valid_report() + EVIDENCE_OK),
                         {"src/app.py": "c" * 64, "notes/local.md": "excluded", "src/gone.py": "missing"})
        self.assertIsNone(module.parse_evidence_table(valid_report()))
        self.assertEqual((module.parent_ids("12.1.3"), module.parent_ids("7")), (["12.1", "12"], []))
        self.assertEqual(module.linked_ids("Task 16, 16.1; `2`, 99", ["2", "16", "16.1"]), ["16", "16.1", "2"])
        item = {"title": "Alpha done evidence_anchor: src/a.py#L1-L2 confidence: high"}
        self.assertEqual(module.stub_title(item), "Alpha done")


class TaskIdNormalizationTests(unittest.TestCase):
    """F7 of plan-refactoring-02: `Task 01` of a plan and `1` of a report are one task."""

    def test_zero_padded_ids(self) -> None:
        module = load_resolver()
        self.assertEqual([module.normalize_plan_task_id(v) for v in ("01.02", "7", "A1", "1.10")],
                         ["1.2", "7", "a1", "1.10"])
        plan = "# P\n\n### Task 01: A\n\n**Files:**\n- Modify: `src/a.py`\n\n- [ ] **Step 1: a**\n"
        self.assertEqual(module.plan_task_files(plan), {"1": ["src/a.py"]})
        self.assertEqual(module.linked_ids("Task 01.1", ["1.1"]), ["1.1"])


class RescanScopeTests(IncrementalFixture, unittest.TestCase):
    """rescan_scope: tasks to audit again from the last report's evidence fingerprint and the start snapshot."""

    def scope(self, stages: str = INC_STAGES, issues: str = "Ошибок не найдено.", change=(), remove=(), plan_edit: str = "",
              ratio: float = 0.5, fingerprint: bool = True) -> dict:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as snaps:
            root, report, start = self.make(tmp, snaps, stages=stages, issues=issues)
            plan = root / "main-plan.md"
            if fingerprint:
                self.assertEqual(run_tool("evidence-fingerprint", str(report), "--snapshot", str(start), "--plan", str(plan)).returncode, 0)
            if plan_edit:
                write(plan, INC_PLAN + plan_edit)
            snapshot = json.loads(start.read_text(encoding="utf-8"))
            for path in change:  # the file changed after the last report: rescan-scope hashes it now
                write(root / path, "changed after the last report\n")
            for path in remove:  # the file is gone
                (root / path).unlink()
            return load_resolver().rescan_scope(str(plan), str(report), snapshot, ratio)

    def test_nothing_changed_reaudits_only_the_probe_closed_checkpoint(self) -> None:
        data = self.scope()
        self.assertEqual((data["scope"], data["reason"]), ("incremental", "1 of 4 tasks touched"))
        self.assertEqual((data["reaudit"], data["carry"]), (["3"], ["1", "2", "2.1"]))
        self.assertEqual((data["changed_files"], data["missing_files"], data["plan_sha_changed"]), ([], [], False))

    def test_a_changed_anchor_file_reaudits_its_task_and_the_parent(self) -> None:
        data = self.scope(change=["docs/b.md"])
        self.assertEqual(data["changed_files"], ["docs/b.md"])
        self.assertEqual((data["reaudit"], data["carry"]), (["2", "2.1", "3"], ["1"]))
        self.assertEqual(data["audit_tasks"], ["2", "2.1", "3"])
        self.assertEqual(data["titles"], {"2": "Beta", "2.1": "Beta docs", "3": "Checkpoint — suite"})
        self.assertEqual(data["line_ranges"], {"2": [9, 14], "2.1": [15, 20], "3": [21, 25]})

    def test_a_file_named_only_in_the_plan_files_counts(self) -> None:
        self.assertEqual(self.scope(change=["src/c.py"])["reaudit"], ["2", "3"])
        data = self.scope(remove=["tests/test_a.py"])
        self.assertEqual((data["missing_files"], data["reaudit"]), (["tests/test_a.py"], ["1", "3"]))

    def test_open_items_linked_items_and_unverified_evidence(self) -> None:
        stages = INC_STAGES.replace("- ✅ 2.1 Beta docs", "- ⚠️ 2.1 Beta docs").replace("docs/b.md#L1-L1", "notes/n.md#L1-L1")
        data = self.scope(stages=stages, issues=INC_ISSUE)
        self.assertEqual(data["reaudit"], ["1", "2", "2.1", "3"])
        self.assertEqual(data["unverified_files"], [])  # an ignored anchor file is hashed, not excluded
        self.assertEqual(data["issues"], [{"id": 1, "status": "not-fixed", "linked_items": ["1"]}])
        self.assertEqual((data["scope"], data["reason"]), ("full", "ratio"))  # 4 of 4 > 0.5

    def test_an_old_excluded_row_is_unverified(self) -> None:  # spec 2 of plan-refactoring-05
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as snaps:
            root, report, start = self.make(tmp, snaps)
            plan = root / "main-plan.md"
            self.assertEqual(run_tool("evidence-fingerprint", str(report), "--snapshot", str(start), "--plan", str(plan)).returncode, 0)
            row = f"| docs/b.md | {sha256(root / 'docs' / 'b.md')} |"
            write(report, report.read_text(encoding="utf-8").replace(row, "| docs/b.md | excluded |"))
            snapshot = json.loads(start.read_text(encoding="utf-8"))
            data = load_resolver().rescan_scope(str(plan), str(report), snapshot, 0.75)
            self.assertEqual((data["unverified_files"], data["changed_files"], data["reaudit"]),
                             (["docs/b.md"], [], ["2", "2.1", "3"]))

    def test_full_scope_reasons(self) -> None:
        data = self.scope(plan_edit="\n### Task 4: Gamma\n\n**Files:**\n- Modify: `src/c.py`\n")
        self.assertEqual((data["scope"], data["reason"], data["plan_sha_changed"]), ("full", "plan-changed", True))
        self.assertIn("4", data["reaudit"])  # a task new in the plan
        self.assertEqual(self.scope(fingerprint=False)["reason"], "no-evidence-fingerprint")
        self.assertEqual(self.scope(ratio=0.2)["reason"], "ratio")  # 1 of 4 > 0.2
        self.assertEqual(self.scope(change=["src/b.py"])["reaudit"], ["2", "3"])  # a parent does not pull its children
        self.assertEqual(self.scope(change=["src/b.py", "docs/b.md"])["reason"], "ratio")  # 3 of 4 > 0.5
        data = self.scope(change=["src/b.py", "docs/b.md"], ratio=0.75)
        self.assertEqual((data["scope"], data["reaudit"]), ("incremental", ["2", "2.1", "3"]))  # 3 of 4 <= 0.75


class RescanScopeCommandTests(IncrementalFixture, unittest.TestCase):
    """`rescan-scope <plan> <last_report> --snapshot <start> [--ratio]`: JSON on stdout, exit 2 on bad input."""

    def test_cli_output_and_input_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as snaps, tempfile.TemporaryDirectory() as other:
            root, report, start = self.make(tmp, snaps)
            plan = root / "main-plan.md"
            self.assertEqual(run_tool("evidence-fingerprint", str(report), "--snapshot", str(start), "--plan", str(plan)).returncode, 0)
            process = run_tool("rescan-scope", str(plan), str(report), "--snapshot", str(start))
            data = read_json(process)
            self.assertEqual(process.returncode, 0, data)
            self.assertEqual((data["scope"], data["reaudit"], data["ratio"]), ("incremental", ["3"], 0.5))
            self.assertEqual((data["last_report"], data["root"]), (os.path.abspath(str(report)), os.path.realpath(tmp)))
            foreign = Path(snaps) / "other.json"
            self.assertEqual(run_tool("fingerprint-workspace", other, str(foreign)).returncode, 0)
            process = run_tool("rescan-scope", str(plan), str(report), "--snapshot", str(foreign))
            self.assertEqual(process.returncode, 2, process.stdout)
            self.assertTrue(read_json(process)["errors"][0].startswith("snapshot-root-mismatch"))
            self.assertEqual(run_tool("rescan-scope", str(plan), str(report), "--snapshot", str(plan)).returncode, 2)
            self.assertEqual(run_tool("rescan-scope", str(plan), str(report), "--snapshot", str(start), "--ratio", "0").returncode, 2)
            self.assertEqual(run_tool("rescan-scope", str(plan), str(root / "nope.md"), "--snapshot", str(start)).returncode, 2)


class RealPathTests(IncrementalFixture, unittest.TestCase):
    """F12 of plan-refactoring-02: paths are compared after realpath and normcase."""

    def links(self, pairs) -> None:
        try:
            for link, target in pairs:
                os.symlink(str(target), str(link), target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlinks unavailable: {exc}")

    def test_a_link_to_the_root_is_inside_and_a_link_out_is_not(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as snaps, \
                tempfile.TemporaryDirectory() as far:
            root, report, start = self.make(tmp, snaps)
            write(Path(far) / "main-plan.md", INC_PLAN)
            alias = Path(snaps) / "alias"
            self.links([(alias, root), (root / "ext", far)])
            process = run_tool("evidence-fingerprint", str(alias / report.name), "--snapshot", str(start),
                               "--plan", str(alias / "main-plan.md"))
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            process = run_tool("rescan-scope", str(alias / "main-plan.md"), str(alias / report.name), "--snapshot", str(start))
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            process = run_tool("rescan-scope", str(root / "ext" / "main-plan.md"), str(report), "--snapshot", str(start))
            self.assertEqual(process.returncode, 2, process.stdout)
            self.assertTrue(read_json(process)["errors"][0].startswith("snapshot-root-mismatch"))

    def test_ensure_inside_spells_the_path_under_the_root(self) -> None:
        module = load_resolver()
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as far:
            root = Path(tmp)
            write(root / "p.md", "x\n")
            write(Path(far) / "q.md", "y\n")
            self.links([(Path(far) / "alias", root), (root / "out", far)])
            self.assertEqual(module.ensure_inside(str(root), str(Path(far) / "alias" / "p.md")),
                             (os.path.join(os.path.abspath(str(root)), "p.md"), "p.md"))
            with self.assertRaises(module.ToolError):
                module.ensure_inside(str(root), "out/q.md")


class Utf8InputTests(IncrementalFixture, unittest.TestCase):
    """F12 of plan-refactoring-02: a plan, report or snapshot that is not UTF-8 is a JSON error with exit 2."""

    def test_not_utf8_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as snaps:
            root, report, start = self.make(tmp, snaps)
            plan = root / "main-plan.md"
            broken = Path(snaps) / "broken.json"
            broken.write_bytes('{"root": "Задача", "files": {}}'.encode("cp1251"))
            process = run_tool("rescan-scope", str(plan), str(report), "--snapshot", str(broken))
            self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
            self.assertTrue(read_json(process)["errors"][0].startswith("invalid fingerprint snapshot"))
            plan.write_bytes("# План\n\n### Task 1: Альфа\n".encode("cp1251"))
            for args in (("rescan-scope", str(plan), str(report), "--snapshot", str(start)),
                         ("evidence-fingerprint", str(report), "--snapshot", str(start), "--plan", str(plan))):
                process = run_tool(*args)
                self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
                self.assertTrue(read_json(process)["errors"][0].startswith("not-utf8:"), process.stdout)
            write(plan, INC_PLAN)
            report.write_bytes("# Отчёт\n".encode("cp1251"))
            process = run_tool("evidence-fingerprint", str(report), "--snapshot", str(start), "--plan", str(plan))
            self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
            self.assertTrue(read_json(process)["errors"][0].startswith("not-utf8:"), process.stdout)


class CarryStageLinesTests(unittest.TestCase):
    """carry_stage_lines: closed lines copied by the script, a stub where the audit must write again."""

    def test_carried_lines_are_byte_for_byte_and_stubs_keep_the_indent(self) -> None:
        module = load_resolver()
        titles = {"2": "Beta", "2.1": "Beta docs", "3": "Checkpoint — suite"}
        body, carried = module.carry_stage_lines(inc_report("a" * 64), ["2", "2.1", "3"], titles)
        self.assertEqual(
            body,
            "- ✅ 1. Alpha evidence_anchor: src/a.py#L1-L2\n"
            "  - evidence_anchor: tests/test_a.py#L1-L1\n"
            "- 2. Beta <!-- reaudit -->\n"
            "  - 2.1 Beta docs <!-- reaudit -->\n"
            "- 3. Checkpoint — suite <!-- reaudit -->",
        )  # the detail line `evidence_probe: pytest` of re-audited task 3 is not carried
        self.assertEqual(carried, 1)

    def test_unknown_tasks_are_appended_and_json_inputs_are_read(self) -> None:
        module = load_resolver()
        titles = {"3": "Checkpoint — suite", "4": "Gamma", "4.1": "Gamma docs"}
        body, _carried = module.carry_stage_lines(inc_report("a" * 64), ["3", "4", "4.1"], titles)
        self.assertTrue(body.endswith(
            "- 3. Checkpoint — suite <!-- reaudit -->\n- 4. Gamma <!-- reaudit -->\n  - 4.1 Gamma docs <!-- reaudit -->"
        ), body)
        with tempfile.TemporaryDirectory() as tmp:
            for name, data in (("bom.json", "﻿{\"x\": 1}".encode("utf-8")), ("utf16.json", json.dumps({"x": 1}).encode("utf-16"))):
                (Path(tmp) / name).write_bytes(data)
                self.assertEqual(module.load_json_input(str(Path(tmp) / name)), {"x": 1})


FIXED_ISSUE = INC_ISSUE.replace("1) Ошибка 1: ⭕️ not-fixed", "1) Ошибка 1: ✅ fixed").replace(
    "- **status**: ⭕️ not-fixed", "- **status**: ✅ fixed"
)
OPEN_ISSUE_2 = INC_ISSUE.replace("1) Ошибка 1:", "2) Ошибка 2:").replace("Beta breaks", "Docs stale")
CARRY_TAIL = (
    "\n## Предупреждения валидатора\n\n- [WARNING] something — принято\n"
    "\n## Отпечаток улик\n\n| File | SHA-256 |\n|---|---|\n| src/a.py | " + "c" * 64 + " |\n"
    "\n## Журнал исправлений\n\n- Ошибка 2: applied | files: docs/b.md\n"
)


class CarryIssueBlocksTests(unittest.TestCase):
    """carry_issue_blocks: every issue block with its number; open ones marked for re-verification."""

    def test_issue_blocks_keep_their_numbers_and_open_ones_are_marked(self) -> None:
        text = inc_report("a" * 64, issues=FIXED_ISSUE + "\n\n" + OPEN_ISSUE_2, tail=CARRY_TAIL)
        body, reverify = load_resolver().carry_issue_blocks(text)
        self.assertTrue(body.startswith("1) Ошибка 1: ✅ fixed | high | Beta breaks\n"), body)
        self.assertIn("\n\n2) Ошибка 2: ⭕️ not-fixed | high | Docs stale <!-- re-verify -->\n", body)
        self.assertIn("- **title**: Docs stale\n", body)  # the title cycle-check matches stays as it was
        self.assertTrue(body.endswith("- **recommendations**: Исправить Alpha."), body)
        self.assertEqual(reverify, [2])


CARRY_HEADER = {
    "master_plan_path": "main-plan.md",
    "master_plan_sha256": "a" * 64,
    "master_plan_size": 1,
    "audited_at": "2026-10-04T11:00:00Z",
    "audit_iteration": 2,
    "consecutive_open_invocations_if_open": 2,
    "consecutive_open_invocations_if_final": 0,
    "previous_report_path": "main-plan-report-1.md",
    "previous_report_sha256": "b" * 64,
    "language": "ru",
    "audit_scope": "full",
    "audit_tasks": "all",
}


class CarryForwardDraftTests(unittest.TestCase):
    """carry_forward_draft: frontmatter from bootstrap.report_header, stages, issues, stub sections."""

    def draft(self, reaudit, titles, audit_tasks):
        text = inc_report("a" * 64, issues=FIXED_ISSUE + "\n\n" + OPEN_ISSUE_2, tail=CARRY_TAIL)
        scope = {"scope": "incremental", "reaudit": reaudit, "titles": titles, "audit_tasks": audit_tasks}
        return load_resolver().carry_forward_draft(text, scope, CARRY_HEADER)

    def test_frontmatter_and_title_from_the_header(self) -> None:
        draft, summary = self.draft(["2", "2.1", "3"], {"2": "Beta", "2.1": "Beta docs", "3": "Checkpoint — suite"}, ["2", "2.1", "3"])
        self.assertTrue(draft.startswith(
            "---\nmaster_plan_path: main-plan.md\nmaster_plan_sha256: " + "a" * 64 + "\nmaster_plan_size: 1\n"
            "audited_at: 2026-10-04T11:00:00Z\naudit_iteration: 2\nconsecutive_open_invocations: 2\n"
            "previous_report_path: main-plan-report-1.md\nprevious_report_sha256: " + "b" * 64 + "\nlanguage: ru\n"
            "audit_scope: incremental\naudit_tasks: [2, 2.1, 3]\n---\n\n# Отчет о выполнении плана 2\n\n"
            "## Основные стадии плана\n\n- ✅ 1. Alpha"
        ), draft)
        self.assertEqual((summary["carried"], summary["stubs"], summary["reverify_issues"]), (1, 3, [2]))

    def test_sections_of_the_draft(self) -> None:
        draft, _summary = self.draft(["3"], {"3": "Checkpoint — suite"}, ["3"])
        self.assertIn("- 3. Checkpoint — suite <!-- reaudit -->\n\n## Список ошибок\n\n1) Ошибка 1: ✅ fixed", draft)
        self.assertIn("Docs stale <!-- re-verify -->\n", draft)
        self.assertTrue(draft.endswith(
            "## Дополнительный контекст\n\n<!-- reaudit -->\n\n## Задача\n\n<!-- reaudit -->\n"
        ), draft)
        for section in ("## Предупреждения валидатора", "## Отпечаток улик", "## Журнал исправлений", "Проверить Alpha."):
            self.assertNotIn(section, draft)


class CarryForwardSetup(IncrementalFixture):
    """A first report with its evidence, the rescan-scope result and a bootstrap header in the snapshot dir."""

    def prepare(self, tmp: str, snaps: str):
        root, report, start = self.make(tmp, snaps)
        plan = root / "main-plan.md"
        self.assertEqual(run_tool("evidence-fingerprint", str(report), "--snapshot", str(start), "--plan", str(plan)).returncode, 0)
        scope = read_json(run_tool("rescan-scope", str(plan), str(report), "--snapshot", str(start)))
        scope_json, header_json = Path(snaps) / "scope.json", Path(snaps) / "header.json"
        write(scope_json, json.dumps(scope))
        write(header_json, json.dumps(dict(CARRY_HEADER, master_plan_sha256=sha256(plan))))
        return root, report, scope, scope_json, header_json

    def carry(self, report: Path, scope_json: Path, header_json: Path, out: Path) -> subprocess.CompletedProcess:
        return run_tool("carry-forward", str(report), "--scope", str(scope_json), "--header", str(header_json), "--out", str(out))


class CarryForwardCommandTests(CarryForwardSetup, unittest.TestCase):
    """`carry-forward <last_report> --scope <json> --header <json> --out <draft>` writes the draft once."""

    def test_writes_the_draft_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as snaps:
            root, report, _scope, scope_json, header_json = self.prepare(tmp, snaps)
            out = root / "main-plan-report-2.md"
            process = self.carry(report, scope_json, header_json, out)
            data = read_json(process)
            self.assertEqual(process.returncode, 0, data)
            self.assertEqual((data["carried"], data["stubs"], data["audit_tasks"]), (3, 1, ["3"]))
            self.assertIn("- 3. Checkpoint — suite <!-- reaudit -->\n", out.read_text(encoding="utf-8"))
            process = self.carry(report, scope_json, header_json, out)
            self.assertEqual(process.returncode, 2)  # reports are immutable
            self.assertTrue(read_json(process)["errors"][0].startswith("report-exists"))

    def test_accepts_the_bootstrap_result_utf16_json_and_keeps_crlf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as snaps:
            root, report, scope, _scope_json, header_json = self.prepare(tmp, snaps)
            report.write_bytes(report.read_bytes().replace(b"\n", b"\r\n"))
            utf16 = Path(snaps) / "scope16.json"
            utf16.write_bytes(json.dumps(scope).encode("utf-16"))  # PowerShell `>` writes UTF-16 with a BOM
            write(header_json, json.dumps({"valid": True, "report_header": CARRY_HEADER}))
            out = root / "main-plan-report-2.md"
            process = self.carry(report, utf16, header_json, out)
            self.assertEqual(process.returncode, 0, process.stdout)
            raw = out.read_bytes()
            self.assertEqual(raw.count(b"\r\n"), raw.count(b"\n"))
            self.assertIn("- ✅ 1. Alpha evidence_anchor: src/a.py#L1-L2\r\n".encode("utf-8"), raw)


class CarryForwardGuardTests(CarryForwardSetup, unittest.TestCase):
    """carry-forward refuses inputs inside the workspace, a scope of another report, a full scope, a bare header."""

    def test_input_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as snaps:
            root, report, scope, scope_json, header_json = self.prepare(tmp, snaps)
            out = root / "main-plan-report-2.md"

            def error(process: subprocess.CompletedProcess, code: int) -> str:
                self.assertEqual(process.returncode, code, process.stdout)
                self.assertFalse(out.exists())
                return read_json(process)["errors"][0]

            inside = root / "scope.json"
            write(inside, json.dumps(scope))
            self.assertTrue(error(self.carry(report, inside, header_json, out), 2).startswith("inputs-inside-workspace"))
            inside.unlink()
            other = Path(snaps) / "other.json"
            write(other, json.dumps(dict(scope, last_report=str(root / "main-plan-report-9.md"))))
            self.assertTrue(error(self.carry(report, other, header_json, out), 2).startswith("scope-mismatch"))
            write(other, json.dumps(dict(scope, scope="full", reason="ratio")))
            self.assertEqual(error(self.carry(report, other, header_json, out), 1), "use-full-pass: rescan-scope chose a full pass (ratio)")
            bare = dict(CARRY_HEADER)
            del bare["language"]
            write(other, json.dumps(bare))
            self.assertEqual(error(self.carry(report, scope_json, other, out), 2), "header-missing-fields: language")
            write(other, "not json")
            self.assertTrue(error(self.carry(report, other, header_json, out), 2).startswith("bad-input-json"))


class BootstrapFullTests(unittest.TestCase):
    """`/plan-resolver <plan> [reports…] full` → `bootstrap … --full` → pass_type `subsequent-full`."""

    def test_full_flag_and_scope_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root / "main-plan.md", "# Main\n")
            data = read_json(run_tool("bootstrap", str(root), "main-plan.md", "--full"))
            self.assertEqual((data["pass_type"], data["warnings"]), ("first", ["--full ignored on the first pass"]))
            self.assertEqual((data["report_header"]["audit_scope"], data["report_header"]["audit_tasks"]), ("full", "all"))
            write(root / "main-plan-report-1.md", valid_report())
            data = read_json(run_tool("bootstrap", str(root), "main-plan.md", "main-plan-report-1.md", "--full"))
            self.assertEqual((data["pass_type"], data["warnings"]), ("subsequent-full", []))
            data = read_json(run_tool("bootstrap", str(root), "main-plan.md", "main-plan-report-1.md"))
            self.assertEqual(data["pass_type"], "subsequent")


class FullAuditRequiredTests(unittest.TestCase):
    """cycle-check: an incremental pass that closes everything is followed by a full pass, which cannot stall."""

    INCREMENTAL = "audit_scope: incremental\naudit_tasks: [1]\n"

    def cycle(self, prev: str, new: str, cycle: int, limit: int = 2, new_name: str = "main-plan-report-3.md") -> str:
        with tempfile.TemporaryDirectory() as tmp:
            write(Path(tmp) / "main-plan-report-2.md", prev)
            write(Path(tmp) / new_name, new)
            process = run_tool("cycle-check", str(Path(tmp) / "main-plan-report-2.md"), str(Path(tmp) / new_name), str(cycle), str(limit))
            self.assertEqual(process.returncode, 0, process.stdout)
            return read_json(process)["action"]

    def test_incremental_pass_with_everything_closed_needs_a_full_pass(self) -> None:
        prev = issues_report([("⭕️ not-fixed", "high", "A")])
        green = scoped_report(self.INCREMENTAL, final=True)  # open name, no issues, every stage ✅
        self.assertEqual(self.cycle(prev, green, 1), "full-audit-required")
        self.assertEqual(self.cycle(prev, green, 2, limit=2), "full-audit-required")  # the loop decides on the limit
        # a full pass with the same content is not asked again (before spec 6 this was ask-user)
        self.assertEqual(self.cycle(prev, scoped_report("audit_scope: full\naudit_tasks: all\n", final=True), 1), "ask-user")
        open_stage = green.replace("- ✅ 1. Подготовка", "- ⚠️ 1. Подготовка")
        self.assertEqual(self.cycle(prev, open_stage, 1), "ask-user")

    def test_the_full_pass_after_it_completes_continues_or_hits_the_limit(self) -> None:
        green = scoped_report(self.INCREMENTAL, final=True)
        final = scoped_report("audit_scope: full\naudit_tasks: all\n", final=True)
        self.assertEqual(self.cycle(green, final, 2, new_name="main-plan-report-3-final.md"), "complete")
        found = issues_report([("⭕️ not-fixed", "high", "New A")], n=3)
        self.assertEqual(self.cycle(green, found, 1), "continue")  # not stop-stalled: nothing was open before
        self.assertEqual(self.cycle(green, found, 2), "stop-limit")


CHAIN_TOOL = ROOT.parent / "plan-chain-runner" / "scripts" / "chain_tool.py"


class IncrementalPassE2ETests(IncrementalFixture, unittest.TestCase):
    """First pass with a fingerprint → code change → rescan-scope → carry-forward → filled draft → cycle-check."""

    def test_incremental_pass_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as snaps:
            root, report1, start1 = self.make(tmp, snaps, issues=INC_ISSUE)
            plan = root / "main-plan.md"
            self.assertEqual(run_tool("evidence-fingerprint", str(report1), "--snapshot", str(start1), "--plan", str(plan)).returncode, 0)
            write(root / "src" / "a.py", "a1\na2 fixed\n")  # the FIX phase changes the anchored file

            boot = read_json(run_tool("bootstrap", str(root), "main-plan.md", "main-plan-report-1.md"))
            self.assertEqual(boot["pass_type"], "subsequent")
            start2 = Path(snaps) / "start-2.json"
            self.assertEqual(run_tool("fingerprint-workspace", str(root), str(start2), "--base", str(start1)).returncode, 0)
            scope = read_json(run_tool("rescan-scope", str(plan), str(report1), "--snapshot", str(start2)))
            self.assertEqual((scope["scope"], scope["changed_files"], scope["reaudit"]), ("incremental", ["src/a.py"], ["1", "3"]))
            scope_json, header_json = Path(snaps) / "scope.json", Path(snaps) / "bootstrap.json"
            write(scope_json, json.dumps(scope))
            write(header_json, json.dumps(boot))
            report2 = root / boot["next_open_name"]
            process = run_tool("carry-forward", str(report1), "--scope", str(scope_json), "--header", str(header_json), "--out", str(report2))
            self.assertEqual(process.returncode, 0, process.stdout)

            census = read_json(run_tool("task-census", str(plan), str(report2)))
            self.assertEqual((census["valid"], census["uncovered"]), (True, []))  # the stubs keep every id
            data = read_json(run_tool("validate-report", str(report2), "--root", str(root), "--plan", str(plan)))
            self.assertIn("unfilled placeholder <!-- reaudit -->: 4 left", data["errors"])

            text = report2.read_text(encoding="utf-8")
            text = text.replace("- 1. Alpha <!-- reaudit -->", "- ✅ 1. Alpha evidence_anchor: src/a.py#L1-L2")
            text = text.replace("- 3. Checkpoint — suite <!-- reaudit -->", "- ✅ 3. Checkpoint — suite\n  - evidence_probe: pytest → exit 0")
            text = text.replace("1) Ошибка 1: ⭕️ not-fixed | high | Beta breaks <!-- re-verify -->", "1) Ошибка 1: ✅ fixed | high | Beta breaks")
            text = text.replace("- **status**: ⭕️ not-fixed", "- **status**: ✅ fixed")
            text = text.replace("consecutive_open_invocations: 2", "consecutive_open_invocations: 0")
            text = text.replace("<!-- reaudit -->", "Инкрементальный проход: всё закрыто, нужен полный проход.", 2)
            write(report2, text)
            self.assertEqual(run_tool("evidence-fingerprint", str(report2), "--snapshot", str(start2), "--plan", str(plan)).returncode, 0)
            data = read_json(run_tool("validate-report", str(report2), "--root", str(root), "--plan", str(plan)))
            self.assertTrue(data["valid"], data)
            action = read_json(run_tool("cycle-check", str(report1), str(report2), "1", "2"))["action"]
            self.assertEqual(action, "full-audit-required")
            self.assertTrue(report2.read_text(encoding="utf-8").startswith("---\nmaster_plan_path: main-plan.md\n"))

            if CHAIN_TOOL.is_file():  # run-stats (spec 1) reads the pass fields: the contract of the two specs
                import importlib.util
                spec = importlib.util.spec_from_file_location("chain_tool", str(CHAIN_TOOL))
                chain = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(chain)
                self.assertEqual(chain._audit_scope(report2.read_text(encoding="utf-8"), frontmatter=True), ("incremental", ["1", "3"]))
                self.assertEqual(chain._audit_scope(report1.read_text(encoding="utf-8"), frontmatter=True), ("full", None))


class CompactClosedLineTests(unittest.TestCase):
    """REPORT-FORMAT.md: a closed leaf is one line with one anchor; validate-report warns, never fails."""

    def validate(self, stages: str) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "main-plan-report-2.md"
            write(report, valid_report().replace("- ✅ 1. Подготовка evidence_anchor: src/app.py#L1-L3", stages))
            process = run_tool("validate-report", str(report))
            data = read_json(process)
        self.assertEqual(process.returncode, 0, data)
        self.assertTrue(data["valid"], data)
        return data

    @staticmethod
    def compact_warnings(data: dict) -> list:
        return [w for w in data["warnings"] if "verbose-closed-task" in w or "too-many-anchors" in w]

    def test_two_detail_lines_on_a_closed_task_warn(self) -> None:
        data = self.validate(
            "- ✅ 1. Phase\n  - ✅ 1.1 Done\n    - evidence_anchor: src/app.py#L1-L3\n    - Реализовано в main."
        )
        self.assertEqual(self.compact_warnings(data), ["[WARNING] verbose-closed-task: 1.1 has 2 detail lines"])

    def test_three_anchors_warn(self) -> None:
        data = self.validate(
            "- ✅ 1. Phase\n  - ✅ 1.1 Done evidence_anchor: src/a.py#L1-L3, src/b.py#L2-L4, tests/test_a.py#L5-L9"
        )
        self.assertEqual(self.compact_warnings(data), ["[WARNING] too-many-anchors: 1.1 has 3 anchors"])

    def test_compact_line_and_open_details_do_not_warn(self) -> None:
        data = self.validate(
            "- ⚠️ 1. Phase\n"
            "  - ✅ 1.1 Done evidence_anchor: src/a.py#L1-L3 tests/test_a.py#L5-L9\n"
            "  - ✅ 1.2 Done\n    - evidence_anchor: src/c.py#L4-L8\n"
            "  - ⚠️ 1.3 Partial\n    - evidence_anchor: src/b.py#L1-L2\n"
            "    - Нет ветки для пустого ввода.\n    - Тест не покрывает ошибку."
        )
        self.assertEqual(self.compact_warnings(data), [])

    def test_parse_report_counts_detail_lines(self) -> None:
        phases, tasks, _ = load_resolver().parse_stage_items(
            "## Основные стадии плана\n\n- ✅ 1. Phase\n  - ✅ 1.1 Done\n    - evidence_anchor: a.py#L1-L2\n    - note\n"
        )
        self.assertEqual(([p["details"] for p in phases], [t["details"] for t in tasks]), ([0], [2]))


class SnapshotHelperTests(unittest.TestCase):
    """Spec 2 of plan-refactoring-05: the snapshot tool, the snapshot file, the evidence root, allowed paths."""

    def test_snapshot_tool_and_loader(self) -> None:
        module = load_resolver()
        self.assertTrue(callable(module.snapshot_tool().worktree_snapshot))
        module._load_brainstorm_tool = lambda: None
        with self.assertRaises(module.ToolError) as ctx:
            module.snapshot_tool()
        self.assertEqual(ctx.exception.code, 1)
        self.assertTrue(str(ctx.exception).startswith("snapshot-unavailable"))
        with tempfile.TemporaryDirectory() as tmp:
            good, old = Path(tmp) / "good.json", Path(tmp) / "old.json"
            write(good, json.dumps({"origin": "walk", "root": tmp, "entries": {}}))
            write(old, json.dumps({"algorithm": "sha256-tree-v2", "root": tmp, "files": {}}))
            self.assertEqual(module.load_worktree(str(good))["origin"], "walk")
            with self.assertRaises(module.ToolError) as ctx:
                module.load_worktree(str(old))
            self.assertTrue(str(ctx.exception).startswith("invalid fingerprint snapshot"))

    def test_evidence_root_and_allowed_paths(self) -> None:
        module = load_resolver()
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as other:
            top = os.path.realpath(tmp)
            sub = os.path.join(top, "svc")
            self.assertEqual(module.evidence_root({"root": top, "workspace": sub}), sub)
            self.assertEqual(module.evidence_root({"root": top}), top)
            self.assertEqual(module.normalize_allowed_path("r.md", top), "r.md")
            self.assertEqual(module.normalize_allowed_path("docs/r.md", top, sub), "svc/docs/r.md")
            self.assertEqual(module.normalize_allowed_path(os.path.join(sub, "B.md"), top, sub), "svc/B.md")
            for bad in ("../x.md", os.path.join(other, "x.md")):
                with self.assertRaises(module.ToolError):
                    module.normalize_allowed_path(bad, top, sub)


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=str(root), capture_output=True,
                   check=True)


def make_repo(root: Path) -> None:
    """A repository with the ignored plan folder docs/.plans/, ignored *.log and the committed app.py and b.py."""
    git(root, "init", "-q")
    write(root / ".gitignore", "docs/.plans/\n*.log\n")
    write(root / "app.py", "a = 1\n")
    write(root / "b.py", "b = 1\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")


PLAN_REL = "docs/.plans/g/g-impl.md"


class FingerprintWorkspaceTests(unittest.TestCase):
    """fingerprint-workspace writes brainstorm_tool.worktree_snapshot plus `workspace` (spec 2 of plan-refactoring-05)."""

    def test_walk_without_git(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as snaps:
            write(Path(tmp) / "a.py", "a\n")
            out = Path(snaps) / "s.json"
            data = read_json(run_tool("fingerprint-workspace", tmp, str(out)))
            self.assertEqual((data["origin"], data["root"], data["plan_dir"], data["entry_count"]),
                             ("walk", os.path.realpath(tmp), None, 1))
            snapshot = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual((snapshot["workspace"], sorted(snapshot["entries"])), (os.path.realpath(tmp), ["a.py"]))
            self.assertEqual(run_tool("fingerprint-workspace", tmp, str(Path(tmp) / "in.json")).returncode, 2)

    @unittest.skipUnless(shutil.which("git"), "git required")
    def test_git_with_the_plan_folder_and_base(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as snaps:
            root = Path(os.path.realpath(tmp))
            make_repo(root)
            write(root / PLAN_REL, "# Plan\n")
            write(root / "top.log", "l\n")
            plain, with_plan, based = (Path(snaps) / name for name in ("plain.json", "plan.json", "based.json"))
            self.assertEqual(run_tool("fingerprint-workspace", str(root), str(plain)).returncode, 0)
            data = read_json(run_tool("fingerprint-workspace", str(root), str(with_plan), "--plan", str(root / PLAN_REL)))
            self.assertEqual((data["origin"], data["plan_dir"], data["warnings"]), ("git", "docs/.plans/g", []))
            entries = json.loads(with_plan.read_text(encoding="utf-8"))["entries"]
            self.assertEqual(entries[PLAN_REL][3], sha256(root / PLAN_REL))  # an ignored file of the plan folder
            self.assertEqual(entries["top.log"], ["!!"])
            self.assertNotIn(PLAN_REL, json.loads(plain.read_text(encoding="utf-8"))["entries"])
            data = read_json(run_tool("fingerprint-workspace", str(root), str(based), "--plan", str(root / PLAN_REL),
                                      "--base", str(plain)))
            self.assertEqual(data["warnings"], ["base-ignored"])
            self.assertEqual(json.loads(based.read_text(encoding="utf-8"))["entries"], entries)

    def test_without_brainstorm_tool_is_snapshot_unavailable(self) -> None:
        module = load_resolver()
        module._load_brainstorm_tool = lambda: None
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as snaps:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = module.main(["fingerprint-workspace", tmp, str(Path(snaps) / "s.json")])
            self.assertEqual(code, 1)
            self.assertTrue(json.loads(out.getvalue())["errors"][0].startswith("snapshot-unavailable"))


@unittest.skipUnless(shutil.which("git"), "git required")
class SnapshotDiffGitTests(unittest.TestCase):
    """snapshot-diff over git snapshots: the classes of spec 2 of plan-refactoring-05; ignored paths outside the plan
    folder never reach `changed` (fix_files)."""

    def snap(self, root: Path, out: Path) -> Path:
        process = run_tool("fingerprint-workspace", str(root), str(out), "--plan", str(root / PLAN_REL))
        self.assertEqual(process.returncode, 0, process.stdout)
        return out

    def test_classes_and_ignored_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as snaps:
            root = Path(os.path.realpath(tmp))
            make_repo(root)
            write(root / PLAN_REL, "# Plan\n")
            write(root / "docs/.plans/g/g-impl-report-1.md", "report\n")
            write(root / "b.py", "b = 2\n")  # modified before the window
            write(root / "gone.py", "g\n")  # untracked, deleted in the window
            before = self.snap(root, Path(snaps) / "before.json")
            write(root / "app.py", "a = 2\n")  # a clean tracked file edited
            write(root / "new.py", "n\n")
            write(root / "b.py", "b = 1\n")  # reverted to HEAD: leaves git status
            (root / "gone.py").unlink()
            write(root / "top.log", "l\n")  # ignored outside the plan folder
            write(root / "docs/.plans/g/g-impl-report-1.md", "report\n\n## Fix Log\n")  # ignored, in the plan folder
            data = read_json(run_tool("snapshot-diff", str(before), str(self.snap(root, Path(snaps) / "after.json"))))
            self.assertEqual(data["changed"], ["app.py", "b.py", "docs/.plans/g/g-impl-report-1.md", "gone.py", "new.py"])
            self.assertEqual((data["added"], data["removed"], data["modified"]),
                             (["new.py"], ["gone.py"], ["app.py", "b.py", "docs/.plans/g/g-impl-report-1.md"]))
            self.assertEqual((data["ignored_changed"], data["origin"]), (["top.log"], "git"))

    def test_a_deleted_tracked_file_is_removed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as snaps:
            root = Path(os.path.realpath(tmp))
            make_repo(root)
            write(root / PLAN_REL, "# Plan\n")
            before = self.snap(root, Path(snaps) / "before.json")
            (root / "app.py").unlink()
            data = read_json(run_tool("snapshot-diff", str(before), str(self.snap(root, Path(snaps) / "after.json"))))
            self.assertEqual((data["changed"], data["removed"]), (["app.py"], ["app.py"]))


class AssertReadonlyTests(unittest.TestCase):
    """assert-readonly by brainstorm_tool.worktree_diff (spec 2 of plan-refactoring-05), the walk without git."""

    def test_probe_caches_are_ignored_changed_only_with_the_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as snaps:
            root = Path(tmp)
            plan = root / "docs" / "main-plan.md"
            write(plan, "# Main\n")
            write(root / ".gitignore", ".pytest_cache/\n*.tsbuildinfo\n")
            start, current = Path(snaps) / "start.json", Path(snaps) / "current.json"
            self.assertEqual(run_tool("fingerprint-workspace", str(root), str(start), "--plan", str(plan)).returncode, 0)
            report = root / "docs" / "main-plan-report-1.md"
            write(report, "report\n")
            write(root / ".pytest_cache" / "v" / "nodeids", "[]")  # side effects of read-only probes
            write(root / "tsconfig.tsbuildinfo", "{}")
            self.assertEqual(run_tool("fingerprint-workspace", str(root), str(current), "--plan", str(plan)).returncode, 0)
            process = run_tool("assert-readonly", str(start), str(current), str(report), "--plan", str(plan))
            data = read_json(process)
            self.assertEqual(process.returncode, 0, data)
            self.assertEqual((data["ignored_changed"], data["added"], data["origin"], data["warnings"]),
                             ([".pytest_cache/v/nodeids", "tsconfig.tsbuildinfo"], ["docs/main-plan-report-1.md"],
                              "walk", []))
            process = run_tool("assert-readonly", str(start), str(current), str(report))
            data = read_json(process)
            self.assertEqual(process.returncode, 1, data)
            self.assertEqual((data["violations"], data["ignored_changed"], data["warnings"]),
                             ([".pytest_cache/v/nodeids", "tsconfig.tsbuildinfo"], [], ["plan-unknown"]))


@unittest.skipUnless(shutil.which("git"), "git required")
class AssertReadonlyGitTests(unittest.TestCase):
    """assert-readonly over git snapshots: the plan folder is guarded, ignored paths elsewhere are information, a
    moved HEAD is the violation `HEAD` (spec 2 of plan-refactoring-05)."""

    def setUp(self) -> None:
        tmp, snaps = tempfile.TemporaryDirectory(), tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.addCleanup(snaps.cleanup)
        self.root, self.snaps = Path(os.path.realpath(tmp.name)), Path(snaps.name)
        make_repo(self.root)
        write(self.root / PLAN_REL, "# Plan\n")

    def window(self, change, plan: bool = True):
        """Start snapshot, `change()`, current snapshot, assert-readonly with the plan's next report allowed."""
        flags = ["--plan", str(self.root / PLAN_REL)] if plan else []
        start, current = self.snaps / "start.json", self.snaps / "current.json"
        self.assertEqual(run_tool("fingerprint-workspace", str(self.root), str(start), *flags).returncode, 0)
        change()
        self.assertEqual(run_tool("fingerprint-workspace", str(self.root), str(current), *flags).returncode, 0)
        report = self.root / "docs/.plans/g/g-impl-report-1.md"
        process = run_tool("assert-readonly", str(start), str(current), str(report), *flags)
        return process.returncode, read_json(process)

    def test_an_ignored_file_of_the_plan_folder_is_a_violation(self) -> None:
        def change() -> None:
            write(self.root / "docs/.plans/g/g-impl-report-1.md", "report\n")  # allowed
            write(self.root / PLAN_REL, "# Plan changed\n")
        code, data = self.window(change)
        self.assertEqual((code, data["violations"], data["ignored_changed"]), (1, [PLAN_REL], []))

    def test_an_ignored_file_outside_the_plan_folder_is_information(self) -> None:
        code, data = self.window(lambda: write(self.root / "top.log", "l\n"))
        self.assertEqual((code, data["valid"], data["violations"], data["ignored_changed"], data["origin"]),
                         (0, True, [], ["top.log"], "git"))

    def test_without_the_plan_an_ignored_change_is_a_violation(self) -> None:
        code, data = self.window(lambda: write(self.root / "top.log", "l\n"), plan=False)
        self.assertEqual((code, data["violations"], data["warnings"]), (1, ["top.log"], ["plan-unknown"]))

    def test_a_commit_in_the_window_is_the_violation_head(self) -> None:
        def change() -> None:
            write(self.root / "app.py", "a = 2\n")
            git(self.root, "commit", "-qam", "inside the audit")
        code, data = self.window(change)
        self.assertEqual((code, data["violations"], data["head_moved"]), (1, ["HEAD"], True))


@unittest.skipUnless(shutil.which("git"), "git required")
class WorkspaceInSubfolderTests(unittest.TestCase):
    """A workspace root below the repository top (spec 2 of plan-refactoring-05): the snapshot root is the top, so
    snapshot-diff gives repository-root paths (fix_files need no prefix); allowed paths and evidence paths stay
    relative to the workspace."""

    def test_paths_of_a_workspace_in_a_subfolder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as snaps:
            top = Path(os.path.realpath(tmp))
            make_repo(top)
            svc = top / "svc"
            plan = svc / "docs" / "p-impl.md"
            write(plan, "# Plan\n\n### Task 1: A\n\n**Files:**\n- Modify: `app.py`\n")
            write(svc / "app.py", "s = 1\n")
            git(top, "add", "-A")
            git(top, "commit", "-q", "-m", "svc")
            start, end = Path(snaps) / "start.json", Path(snaps) / "end.json"
            data = read_json(run_tool("fingerprint-workspace", str(svc), str(start), "--plan", str(plan)))
            self.assertEqual((data["root"], data["plan_dir"]), (str(top), "svc/docs"))
            write(svc / "app.py", "s = 2\n")
            report = svc / "docs" / "p-impl-report-1.md"
            write(report, inc_report(sha256(plan), "- ✅ 1. A evidence_anchor: app.py#L1-L1"))
            self.assertEqual(run_tool("fingerprint-workspace", str(svc), str(end), "--plan", str(plan)).returncode, 0)
            diff = read_json(run_tool("snapshot-diff", str(start), str(end)))
            self.assertEqual(diff["changed"], ["svc/app.py", "svc/docs/p-impl-report-1.md"])
            data = read_json(run_tool("assert-readonly", str(start), str(end), "docs/p-impl-report-1.md", "--plan", str(plan)))
            self.assertEqual((data["allowed_paths"], data["violations"]), (["svc/docs/p-impl-report-1.md"], ["svc/app.py"]))
            process = run_tool("evidence-fingerprint", str(report), "--snapshot", str(start), "--plan", str(plan))
            self.assertEqual((process.returncode, read_json(process)["missing"]), (0, []))
            self.assertIn(f"| app.py | {sha256(svc / 'app.py')} |", report.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
