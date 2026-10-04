from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "scripts" / "resolver_tool.py"
ASSETS = ROOT / "assets"


def render(template: str, language: str) -> str:
    replacements = {
        "{{master_plan_path}}": "main-plan.md",
        "{{master_plan_sha256}}": "b" * 64,
        "{{master_plan_size}}": "42",
        "{{audited_at}}": "2026-05-10T07:54:08Z",
        "{{audit_iteration}}": "1",
        "{{consecutive_open_invocations}}": "0",
        "{{previous_report_path}}": "null",
        "{{previous_report_sha256}}": "null",
        "{{audit_scope}}": "full",
        "{{audit_tasks}}": "all",
        "{{evidence_fingerprint}}": "| File | SHA-256 |\n|---|---|\n| src/app.py | " + "c" * 64 + " |",
        "{{plan_stages}}": "- ✅ 1. Bootstrap implemented evidence_anchor: src/app.py#L1-L9"
        if language == "en"
        else "- ✅ 1. Bootstrap реализован evidence_anchor: src/app.py#L1-L9",
        "{{issues}}": "No issues found." if language == "en" else "Ошибок не найдено.",
        "{{additional_context}}": "No additional context." if language == "en" else "Дополнительного контекста нет.",
        "{{task}}": "Plan is fully implemented; no further action is required."
        if language == "en"
        else "План реализован полностью; дальнейших действий не требуется.",
    }
    for key, value in replacements.items():
        template = template.replace(key, value)
    return template


class TemplateContractTests(unittest.TestCase):
    def test_ru_and_en_templates_validate_after_render(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for language in ("ru", "en"):
                template_path = ASSETS / f"report-template.{language}.md"
                rendered = render(template_path.read_text(encoding="utf-8"), language)
                report_path = Path(tmp) / f"main-plan-report-1-final-{language}.md"
                # The validator recognizes final reports by the exact suffix, so use a per-language folder.
                language_dir = Path(tmp) / language
                language_dir.mkdir(parents=True, exist_ok=True)
                report_path = language_dir / "main-plan-report-1-final.md"
                report_path.write_bytes(rendered.encode("utf-8"))
                process = subprocess.run(
                    [sys.executable, str(TOOL), "validate-report", str(report_path)],
                    text=True,
                    capture_output=True,
                )
                data = json.loads(process.stdout)
                self.assertEqual(process.returncode, 0, data)
                self.assertTrue(data["valid"])
                self.assertEqual(data["warnings"], [])  # audit_scope is in the frontmatter
                heading = "## Evidence fingerprint" if language == "en" else "## Отпечаток улик"
                self.assertIn(f"\n{heading}\n\n| File | SHA-256 |\n", rendered)


if __name__ == "__main__":
    unittest.main()
