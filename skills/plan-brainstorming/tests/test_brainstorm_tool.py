"""Tests for brainstorm_tool.py.

Uses unittest (stdlib) so no external dependencies are needed.
Run: python -m pytest skills/plan-brainstorming/tests -q
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest


SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "scripts")
TOOL = os.path.abspath(os.path.join(SCRIPTS, "brainstorm_tool.py"))


def _load_module():
    spec = importlib.util.spec_from_file_location("brainstorm_tool", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ft = _load_module()

SAMPLE = [
    {
        "file": "src/db/row-limit.ts",
        "line": 52,
        "summary": "Лимит строк отключается при OFFSET без FETCH.",
        "failure_scenario": "SELECT * FROM T ORDER BY ID OFFSET 0 ROWS → вся таблица в память.",
    },
    {
        "file": "src/db/connection.ts",
        "line": 56,
        "summary": "connectWithRetry() никогда не отвергает промис.",
        "failure_scenario": "БД недоступна → все вызовы инструментов зависают навсегда.",
    },
]


def _run(*args, stdin=None):
    proc = subprocess.run(
        [sys.executable, TOOL, *args],
        input=stdin,
        capture_output=True,
        encoding="utf-8",
    )
    return proc.returncode, (json.loads(proc.stdout) if proc.stdout.strip() else None)


class LoadFindingsTest(unittest.TestCase):
    def test_valid_sample_gets_sequential_ids(self):
        findings, errors, warnings = ft.load_findings(json.dumps(SAMPLE))
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])
        self.assertEqual([f["id"] for f in findings], ["F1", "F2"])
        self.assertEqual(findings[0]["line"], 52)

    def test_report_wrapper_is_accepted(self):
        findings, errors, _ = ft.load_findings(json.dumps({"findings": SAMPLE, "level": "high"}))
        self.assertEqual(errors, [])
        self.assertEqual(len(findings), 2)

    def test_missing_required_field_is_error(self):
        bad = [{"file": "a.py", "summary": "x"}]
        _, errors, _ = ft.load_findings(json.dumps(bad))
        self.assertEqual(errors, ["F1: 'failure_scenario' must be a non-empty string"])

    def test_line_is_optional_but_must_be_positive_int(self):
        base = {"file": "a.py", "summary": "s", "failure_scenario": "f"}
        findings, errors, _ = ft.load_findings(json.dumps([base]))
        self.assertEqual(errors, [])
        self.assertIsNone(findings[0]["line"])
        for bad_line in (0, -3, "12", True, 1.5):
            _, errors, _ = ft.load_findings(json.dumps([dict(base, line=bad_line)]))
            self.assertTrue(errors, f"line={bad_line!r} should be rejected")

    def test_optional_fields_pass_through_and_unknown_warn(self):
        item = dict(SAMPLE[0], category="correctness", verdict="CONFIRMED", severity="high")
        findings, errors, warnings = ft.load_findings(json.dumps([item]))
        self.assertEqual(errors, [])
        self.assertEqual(findings[0]["category"], "correctness")
        self.assertEqual(findings[0]["extra"], {"severity": "high"})
        self.assertEqual(len(warnings), 1)

    def test_path_is_normalized(self):
        item = dict(SAMPLE[0], file=".\\src\\db\\row-limit.ts")
        findings, _, _ = ft.load_findings(json.dumps([item]))
        self.assertEqual(findings[0]["file"], "src/db/row-limit.ts")

    def test_duplicate_is_warned(self):
        _, errors, warnings = ft.load_findings(json.dumps([SAMPLE[0], SAMPLE[0]]))
        self.assertEqual(errors, [])
        self.assertEqual(warnings, ["F2: duplicate of F1 (same file, line and summary)"])

    def test_empty_list_is_error(self):
        _, errors, _ = ft.load_findings("[]")
        self.assertEqual(errors, ["findings list is empty"])

    def test_non_array_and_bad_json_raise(self):
        with self.assertRaises(ft.InputError):
            ft.load_findings('{"file": "a.py"}')
        with self.assertRaises(ft.InputError):
            ft.load_findings("[{")


class LocationTest(unittest.TestCase):
    def test_statuses(self):
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "src"))
            with open(os.path.join(root, "src", "a.py"), "w", encoding="utf-8") as fh:
                fh.write("one\ntwo\nthree")
            items = [
                {"file": "src/a.py", "line": 3, "summary": "s", "failure_scenario": "f"},
                {"file": "src/a.py", "line": 4, "summary": "s2", "failure_scenario": "f"},
                {"file": "src/gone.py", "line": 1, "summary": "s", "failure_scenario": "f"},
            ]
            findings, _, _ = ft.load_findings(json.dumps(items))
            warnings = ft.check_locations(findings, root)
        self.assertEqual([f["location"] for f in findings], ["ok", "line_out_of_range", "file_missing"])
        self.assertEqual(len(warnings), 2)


VALID_SPEC = """> Tier: Quick

# Goal
Remove unbounded queries.

## Architecture
Validate row limits in the SQL analyzer.

## Components
- `sql-structure.ts`: detects OFFSET without FETCH.

```markdown
## Not A Heading
TODO inside a fence is ignored
```

## Data Flow
(none) - single synchronous check.

## Error Handling
Unbounded queries are rejected with a clear error.

## Testing Strategy
Regression test per failure scenario.

## Out of Scope
- Connection retry logic.

## Open Questions
(none)
"""


class SpecCheckTest(unittest.TestCase):
    def check(self, text):
        return ft.check_spec(text)

    def test_valid_spec(self):
        result = self.check(VALID_SPEC)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["warnings"], [])
        self.assertEqual(result["tier"], "Quick")

    def test_missing_heading(self):
        result = self.check(VALID_SPEC.replace("## Data Flow\n(none) - single synchronous check.\n\n", ""))
        self.assertIn("missing heading: ## Data Flow", result["errors"])

    def test_out_of_order(self):
        text = (
            VALID_SPEC.replace("## Architecture", "## TMP")
            .replace("## Components", "## Architecture")
            .replace("## TMP", "## Components")
        )
        result = self.check(text)
        self.assertTrue(any(e.startswith("headings out of order") for e in result["errors"]))

    def test_open_questions_must_be_empty(self):
        result = self.check(VALID_SPEC.replace("## Open Questions\n(none)", "## Open Questions\n- Retry or fail?"))
        self.assertFalse(result["ok"])

    def test_empty_open_questions_is_ok(self):
        result = self.check(VALID_SPEC.replace("## Open Questions\n(none)\n", "## Open Questions\n"))
        self.assertTrue(result["ok"])

    def test_empty_section_and_bare_none(self):
        text = VALID_SPEC.replace("Unbounded queries are rejected with a clear error.", "")
        text = text.replace("(none) - single synchronous check.", "(none)")
        result = self.check(text)
        self.assertIn("empty section: ## Error Handling (use '(none)' with a one-line rationale)", result["errors"])
        self.assertIn("## Data Flow: '(none)' without a one-line rationale", result["warnings"])

    def test_out_of_scope_cannot_be_none(self):
        result = self.check(VALID_SPEC.replace("- Connection retry logic.", "(none)"))
        self.assertIn("## Out of Scope must list excluded work explicitly", result["errors"])

    def test_tier_missing_or_unknown_is_warning(self):
        self.assertTrue(self.check(VALID_SPEC.replace("> Tier: Quick\n\n", ""))["ok"])
        result = self.check(VALID_SPEC.replace("Tier: Quick", "Tier: Huge"))
        self.assertTrue(result["ok"])
        self.assertEqual(result["tier"], "Huge")
        self.assertTrue(result["warnings"])

    def test_placeholder_and_extra_heading_warn(self):
        text = VALID_SPEC.replace("Regression test per failure scenario.", "TBD\n\n## Notes\nx")
        result = self.check(text)
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["warnings"]), 2)

    def test_russian_body_with_english_headings(self):
        text = VALID_SPEC.replace("Remove unbounded queries.", "Убрать неограниченные запросы.")
        self.assertTrue(self.check(text)["ok"])

    def test_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            good = os.path.join(tmp, "a-spec.md")
            bad = os.path.join(tmp, "b-spec.md")
            with open(good, "w", encoding="utf-8") as fh:
                fh.write(VALID_SPEC)
            with open(bad, "w", encoding="utf-8") as fh:
                fh.write("# Goal\nx\n")
            self.assertEqual(_run("spec-check", good)[0], 0)
            code, out = _run("spec-check", bad)
            self.assertEqual(code, 1)
            self.assertFalse(out["ok"])
            self.assertEqual(_run("spec-check", os.path.join(tmp, "missing.md"))[0], 2)


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.findings_path = os.path.join(self.tmp.name, "review01.json")
        with open(self.findings_path, "w", encoding="utf-8") as fh:
            json.dump(SAMPLE, fh, ensure_ascii=False)

    def _spec(self, body):
        path = os.path.join(self.tmp.name, "review01-spec.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body)
        return path

    def test_parse_file_ok(self):
        code, out = _run("findings-parse", self.findings_path)
        self.assertEqual(code, 0)
        self.assertTrue(out["ok"])
        self.assertEqual(out["count"], 2)
        self.assertEqual(out["by_file"], {"src/db/row-limit.ts": ["F1"], "src/db/connection.ts": ["F2"]})
        self.assertIn("OFFSET", out["findings"][0]["summary"])

    def test_parse_stdin_with_root_reports_missing_files(self):
        code, out = _run("findings-parse", "-", "--root", self.tmp.name, stdin=json.dumps(SAMPLE, ensure_ascii=False))
        self.assertEqual(code, 0)
        self.assertEqual([f["location"] for f in out["findings"]], ["file_missing", "file_missing"])

    def test_parse_validation_error_exit_1(self):
        code, out = _run("findings-parse", "-", stdin='[{"file": "a.py"}]')
        self.assertEqual(code, 1)
        self.assertFalse(out["ok"])

    def test_parse_bad_json_exit_2(self):
        code, out = _run("findings-parse", "-", stdin="not json")
        self.assertEqual(code, 2)
        self.assertFalse(out["ok"])

    def test_parse_missing_file_exit_2(self):
        code, _ = _run("findings-parse", os.path.join(self.tmp.name, "nope.json"))
        self.assertEqual(code, 2)

    def test_coverage_ok(self):
        spec = self._spec("| F1 | fix |\n\n## Out of Scope\n- F2: deferred\n")
        code, out = _run("findings-coverage", self.findings_path, spec)
        self.assertEqual(code, 0)
        self.assertEqual(out["covered"], ["F1", "F2"])

    def test_coverage_missing_and_unknown(self):
        spec = self._spec("| F1 | fix |\n| F7 | ghost |\n| F10x | not an id |\n")
        code, out = _run("findings-coverage", self.findings_path, spec)
        self.assertEqual(code, 1)
        self.assertEqual(out["missing"], ["F2"])
        self.assertEqual(out["unknown"], ["F7"])

    def test_no_command_exit_2(self):
        proc = subprocess.run([sys.executable, TOOL], capture_output=True)
        self.assertEqual(proc.returncode, 2)


if __name__ == "__main__":
    unittest.main()
