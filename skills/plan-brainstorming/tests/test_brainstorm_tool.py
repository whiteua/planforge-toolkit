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
from unittest import mock


SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "scripts")
TOOL = os.path.abspath(os.path.join(SCRIPTS, "brainstorm_tool.py"))
SETTINGS_FIXTURE = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "plan-writing", "tests", "fixtures", "settings01-spec.md"))


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


class DetectLangTest(unittest.TestCase):
    def _file(self, tmp, name, text):
        path = os.path.join(tmp, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def test_detect_lang_text(self):
        self.assertEqual(ft.detect_lang_text("Добавить флаг verbose в CLI."), "ru")
        self.assertEqual(ft.detect_lang_text("Add a verbose flag to the CLI."), "en")
        self.assertEqual(ft.detect_lang_text(""), "en")
        self.assertEqual(ft.detect_lang_text("123 -> 456 !!"), "en")
        # threshold: more than 5% of the letters, exactly 5% is still English
        self.assertEqual(ft.detect_lang_text("ж" * 5 + "a" * 95), "en")
        self.assertEqual(ft.detect_lang_text("ж" * 6 + "a" * 94), "ru")

    def test_cli_goal_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out = _run("detect-lang", self._file(tmp, "goal.md", "# Цель\nУбрать неограниченные запросы к базе.\n"))
            self.assertEqual(code, 0)
            self.assertEqual((out["ok"], out["lang"]), (True, "ru"))
            self.assertGreater(out["cyrillic_ratio"], 0.5)
            code, out = _run("detect-lang", self._file(tmp, "idea.md", "Remove unbounded queries.\n"))
            self.assertEqual((code, out["lang"], out["cyrillic_ratio"]), (0, "en", 0.0))
            code, out = _run("detect-lang", self._file(tmp, "empty.md", ""))
            self.assertEqual((code, out["lang"], out["cyrillic_ratio"]), (0, "en", 0.0))
            self.assertEqual(_run("detect-lang", os.path.join(tmp, "missing.md"))[0], 2)

    def test_cli_findings_json_with_escaped_cyrillic(self):
        with tempfile.TemporaryDirectory() as tmp:
            # json.dump escapes Cyrillic as \uXXXX by default: the raw text has no Cyrillic letters.
            code, out = _run("detect-lang", self._file(tmp, "review.json", json.dumps(SAMPLE)))
            self.assertEqual(code, 0)
            self.assertEqual(out["lang"], "ru")


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

    def test_claude_md_in_components_warns(self):  # spec 1 of plan-refactoring-02
        text = VALID_SPEC.replace("- `sql-structure.ts`: detects OFFSET without FETCH.\n",
                                  "- `sql-structure.ts`: detects OFFSET without FETCH.\n- `CLAUDE.md`: the new rule.\n")
        result = self.check(text)
        self.assertEqual(result["errors"], [])
        self.assertTrue(any(w.startswith("claude-md-in-components:") for w in result["warnings"]), result["warnings"])
        self.assertFalse(any(w.startswith("claude-md-in-components") for w in self.check(VALID_SPEC)["warnings"]))
        elsewhere = VALID_SPEC.replace("Validate row limits in the SQL analyzer.", "CLAUDE.md stays as it is.")
        self.assertFalse(any(w.startswith("claude-md-in-components") for w in self.check(elsewhere)["warnings"]))

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

    def test_bold_tier_line_is_recognized(self):
        for variant in ("> **Tier:** Quick", "> **Tier**: Quick", ">  Tier:   Quick  "):
            result = self.check(VALID_SPEC.replace("> Tier: Quick", variant))
            self.assertEqual(result["tier"], "Quick", variant)
            self.assertEqual(result["warnings"], [], variant)

    def test_open_questions_none_with_rationale(self):
        result = self.check(VALID_SPEC.replace("## Open Questions\n(none)", "## Open Questions\n(none) — all resolved in review"))
        self.assertEqual(result["errors"], [])
        result = self.check(VALID_SPEC.replace("## Open Questions\n(none)", "## Open Questions\n(none)\n- but this one?"))
        self.assertTrue(any("Open Questions" in e for e in result["errors"]))

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


COMPONENTS_LINE = "- `sql-structure.ts`: detects OFFSET without FETCH.\n"
TESTING_LINE = "Regression test per failure scenario.\n"


def _volume_spec(components, testing=TESTING_LINE, tier="Quick"):
    """VALID_SPEC with the Components item and the Testing Strategy text replaced; tier None drops the line."""
    text = VALID_SPEC.replace(COMPONENTS_LINE, components).replace(TESTING_LINE, testing)
    if tier is None:
        return text.replace("> Tier: Quick\n\n", "")
    return text.replace("> Tier: Quick", f"> Tier: {tier}")


class SpecVolumeTest(unittest.TestCase):
    def test_valid_spec_volume(self):
        volume = ft.check_spec(VALID_SPEC)["volume"]
        self.assertEqual(volume, {
            "components": 1, "testing_items": 0, "out_of_scope_items": 1,
            "spec_bytes": len(VALID_SPEC.encode("utf-8")),
            "estimate_tasks": 1, "budget_tasks": 40, "over_budget": False,
        })

    def test_shared_budget_constants(self):
        self.assertEqual(ft.SIZE_BUDGET, {"tasks": 40, "bytes": 150000})
        self.assertEqual(ft.TIER_TASK_FACTOR, {"Quick": 1, "Standard": 2, "Deep": 3})

    def test_table_list_and_subheadings_count(self):
        table = "| Component | Role |\n|---|---|\n| `a.py` | parse |\n| `b.py` | check |\n| `c.py` | print |\n"
        listed = "- `a.py`: parse\n- `b.py`: check\n  - nested detail\n"
        headed = "### a.py\nParses.\n\n#### b.py\nChecks.\n"
        for block, expected in ((table, 3), (listed, 2), (headed, 2)):
            with self.subTest(block=block):
                result = ft.check_spec(_volume_spec(block))
                self.assertEqual(result["errors"], [])
                self.assertEqual(result["volume"]["components"], expected)

    def test_estimate_by_tier(self):
        components = "- a\n- b\n- c\n"
        testing = "- unit\n- cli\n"
        for tier, expected in (("Quick", 5), ("Standard", 8), ("Deep", 11), (None, 8), ("Huge", 8)):
            with self.subTest(tier=tier):
                volume = ft.check_spec(_volume_spec(components, testing, tier))["volume"]
                self.assertEqual((volume["components"], volume["testing_items"]), (3, 2))
                self.assertEqual(volume["estimate_tasks"], expected)
                self.assertFalse(volume["over_budget"])

    def test_over_budget(self):
        components = "".join(f"- c{i}\n" for i in range(25))
        volume = ft.check_spec(_volume_spec(components, "- unit\n- cli\n", "Deep"))["volume"]
        self.assertEqual(volume["estimate_tasks"], 77)
        self.assertEqual(volume["budget_tasks"], 40)
        self.assertTrue(volume["over_budget"])

    def test_prose_components_warn_volume_unknown(self):
        result = ft.check_spec(_volume_spec("Two modules parse and check the query.\n", "- unit\n"))
        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(result["volume"]["components"], 0)
        self.assertEqual(result["volume"]["estimate_tasks"], 1)
        self.assertIn(ft.VOLUME_UNKNOWN, result["warnings"])
        self.assertNotIn(ft.VOLUME_UNKNOWN, ft.check_spec(VALID_SPEC)["warnings"])
        none = ft.check_spec(_volume_spec("(none) — configuration only.\n"))
        self.assertNotIn(ft.VOLUME_UNKNOWN, none["warnings"])

    def test_volume_when_check_fails(self):
        result = ft.check_spec(VALID_SPEC.replace("## Data Flow\n(none) - single synchronous check.\n\n", ""))
        self.assertFalse(result["ok"])
        self.assertEqual(result["volume"]["components"], 1)

    def test_settings_fixture(self):
        with open(SETTINGS_FIXTURE, encoding="utf-8") as fh:
            text = fh.read()
        volume = ft.check_spec(text)["volume"]
        self.assertEqual((volume["components"], volume["testing_items"], volume["out_of_scope_items"]), (2, 0, 1))
        self.assertEqual(volume["estimate_tasks"], 4)
        self.assertEqual(volume["spec_bytes"], len(text.encode("utf-8")))

    def test_cli_returns_volume(self):
        code, out = _run("spec-check", SETTINGS_FIXTURE)
        self.assertEqual(code, 0, out)
        self.assertEqual(out["volume"]["estimate_tasks"], 4)
        self.assertFalse(out["volume"]["over_budget"])


RU_SPEC = (
    VALID_SPEC.replace("Remove unbounded queries.", "Убрать неограниченные запросы.")
    .replace("Validate row limits in the SQL analyzer.", "Проверять лимит строк в анализаторе SQL.")
    .replace("Unbounded queries are rejected with a clear error.", "Неограниченный запрос отклоняется с понятной ошибкой.")
    .replace("Regression test per failure scenario.", "Регрессионный тест на каждый сценарий отказа.")
)


class SpecCheckLangTest(unittest.TestCase):
    def test_lang_follows_the_body(self):
        self.assertEqual(ft.check_spec(VALID_SPEC)["lang"], "en")
        result = ft.check_spec(RU_SPEC)
        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(result["lang"], "ru")

    def test_code_fences_do_not_count(self):
        fenced = VALID_SPEC.replace(
            "TODO inside a fence is ignored",
            "Этот текст внутри блока кода не считается телом спеки и не меняет язык диалога",
        )
        self.assertEqual(ft.check_spec(fenced)["lang"], "en")

    def test_cli_reports_lang(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "a-spec.md")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(RU_SPEC)
            code, out = _run("spec-check", path)
        self.assertEqual(code, 0)
        self.assertEqual(out["lang"], "ru")


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

    def test_coverage_unknown_only_is_warning(self):
        spec = self._spec("| F1 | fix |\n| F2 | fix |\nlint code F401 is unrelated\n")
        code, out = _run("findings-coverage", self.findings_path, spec)
        self.assertEqual(code, 0, out)
        self.assertEqual(out["unknown"], ["F401"])
        self.assertTrue(out["warnings"])

    def test_no_command_exit_2(self):
        proc = subprocess.run([sys.executable, TOOL], capture_output=True)
        self.assertEqual(proc.returncode, 2)


FENCE = "`" * 3


class ParseChainTest(unittest.TestCase):
    def test_valid_chain(self):
        errors = []
        chain = ft._parse_chain("revision=deep; split=never;", "line 2", errors)
        self.assertEqual(chain, {"revision": "deep", "split": "never"})
        self.assertEqual(errors, [])

    def test_chain_errors(self):
        errors = []
        chain = ft._parse_chain("color=red; split=sometimes; stop; split=auto; split=never", "line 2", errors)
        self.assertEqual(chain, {"split": "auto"})
        self.assertEqual(errors, [
            "line 2: unknown chain key 'color' (allowed: split, revision, stop, resolver)",
            "line 2: unknown value 'sometimes' for chain key 'split' (allowed: auto, always, never)",
            "line 2: chain item 'stop' is not key=value",
            "line 2: duplicate chain key 'split'",
        ])

    def test_unfenced_lines(self):
        text = "a\n" + FENCE + "\nb\n" + FENCE + "\nc  "
        self.assertEqual(ft._unfenced_lines(text), [(1, "a"), (5, "c")])


class ParseMetadataChainTest(unittest.TestCase):
    def meta(self, *lines):
        # Line 1 is the Tier line; lines after '# Goal' are not metadata.
        return ft.parse_metadata("\n".join(("> Tier: Deep",) + lines + ("", "# Goal", "> Chain: split=bogus")))

    def test_chain_and_backlog(self):
        result = self.meta("> Chain: revision=deep; split=never", "> Backlog: values-fix")
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["chain"], {"revision": "deep", "split": "never"})
        self.assertEqual(result["backlog"], "values-fix")
        self.assertEqual(result["environments"], [])

    def test_bold_forms(self):
        result = self.meta("> **Chain:** stop=strict", "> **Backlog**: values-fix")
        self.assertEqual((result["chain"], result["backlog"]), ({"stop": "strict"}, "values-fix"))

    def test_line_errors(self):
        result = self.meta("> Chain: split=sometimes", "> Chain: stop=strict", "> Backlog:", "> Backlog: a", "> Backlog: b")
        self.assertEqual(result["errors"], [
            "line 2: unknown value 'sometimes' for chain key 'split' (allowed: auto, always, never)",
            "line 3: duplicate Chain line",
            "line 4: empty Backlog line (expected '> Backlog: <section name>')",
            "line 6: duplicate Backlog line",
        ])

    def test_malformed_metadata_lines(self):
        result = self.meta("> chain: split=never", "> Chain : split=never", "> **backlog:** x", "> tier: Deep",
                           "> Environment `db` (test)", "> Tiers and chains are prose here")
        self.assertEqual(result["errors"], [
            "line 2: malformed-metadata: > chain: split=never",
            "line 3: malformed-metadata: > Chain : split=never",
            "line 4: malformed-metadata: > **backlog:** x",
            "line 5: malformed-metadata: > tier: Deep",
            "line 6: malformed-metadata: > Environment `db` (test)",
        ])
        self.assertEqual((result["chain"], result["backlog"]), (None, None))
        self.assertEqual(self.meta(FENCE, "> chain: split=never", FENCE)["errors"], [])

    def test_fenced_lines_and_old_spec(self):
        self.assertEqual(self.meta(FENCE, "> Chain: split=bogus", FENCE)["errors"], [])
        empty = {"chain": None, "environments": [], "backlog": None, "errors": [], "warnings": []}
        self.assertEqual(ft.parse_metadata(VALID_SPEC), empty)


class EnvironmentRulesTest(unittest.TestCase):
    def test_parse_rights(self):
        errors = []
        self.assertEqual(ft._parse_rights("read=run, write=task", "line 1", "app_test", errors), ("run", "task"))
        self.assertEqual(ft._parse_rights("read=deny; write=run", "line 1", "app_test", errors), ("deny", "run"))
        self.assertEqual(errors, [])

    def test_missing_or_bad_rights(self):
        errors = []
        self.assertEqual(ft._parse_rights(None, "line 1", "app_test", errors), (None, None))
        ft._parse_rights("read=run", "line 2", "app_test", errors)
        ft._parse_rights("read=always, write=run", "line 3", "app_test", errors)
        self.assertEqual(errors, [
            "line 1: environment `app_test` misses read= and write= (values: run, task, deny)",
            "line 2: environment `app_test` misses write= (values: run, task, deny)",
            "line 3: environment `app_test`: bad right 'read=always' (expected read= or write= with run, task, deny)",
        ])

    def test_prod_write_run_and_ui_markers(self):
        entry = {"name": "app-db", "kind": "prod", "write": "run", "quote": "Чтение прода? — Да"}
        self.assertEqual(ft._environment_errors(entry, "line 1"), [
            "line 1: environment `app-db` is prod: write=run is not allowed (prod changes are task or deny only)"
        ])
        self.assertEqual(ft._environment_errors(dict(entry, kind="test"), "line 1"), [])
        for marker in ("(Recommended)", "(recommended)", "(РЕКОМЕНДУЮ)"):
            issues = ft._environment_errors(dict(entry, kind="test", quote="Да " + marker), "line 1")
            self.assertEqual(issues, [
                f"line 1: environment `app-db`: quote contains the interface marker '{marker}' "
                "(record the question and the user's answer only)"
            ], marker)


ENV_TEST = '> Environment: `app_test` (test) — read=run, write=run — "Тесты на app_test? — Да" (2026-10-01)'
ENV_PROD = "> Environment: `app-db` (prod) - read=run, write=deny - «Чтение прода? — Да, только чтение» (2026-10-01)"


class ParseMetadataEnvironmentTest(unittest.TestCase):
    def meta(self, *lines):
        return ft.parse_metadata("\n".join(lines + ("", "# Goal")))

    def test_valid_lines(self):
        result = self.meta(ENV_TEST, ENV_PROD)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["environments"], [
            {"name": "app_test", "kind": "test", "read": "run", "write": "run",
             "quote": "Тесты на app_test? — Да", "date": "2026-10-01"},
            {"name": "app-db", "kind": "prod", "read": "run", "write": "deny",
             "quote": "Чтение прода? — Да, только чтение", "date": "2026-10-01"},
        ])

    def test_line_rules(self):
        prod_write = self.meta(ENV_PROD.replace("write=deny", "write=run"))["errors"]
        self.assertEqual(prod_write, [
            "line 1: environment `app-db` is prod: write=run is not allowed (prod changes are task or deny only)"
        ])
        old_form = self.meta('> Environment: `app_test` (test) — "Тесты? — Да" (2026-10-01)')["errors"]
        self.assertEqual(old_form, ["line 1: environment `app_test` misses read= and write= (values: run, task, deny)"])
        marker = self.meta(ENV_TEST.replace('Да"', 'Да (Recommended)"'))["errors"]
        self.assertEqual(len(marker), 1)
        self.assertIn("interface marker '(Recommended)'", marker[0])

    def test_unmatched_and_duplicate_lines(self):
        result = self.meta("> Environment: app_test (staging)", ENV_TEST, ENV_TEST)
        self.assertEqual(len(result["errors"]), 2)
        self.assertTrue(result["errors"][0].startswith("line 1: Environment line does not match"))
        self.assertEqual(result["errors"][1], "line 3: duplicate Environment `app_test`")
        self.assertEqual([env["name"] for env in result["environments"]], ["app_test"])


META_SPEC = VALID_SPEC.replace(
    "> Tier: Quick\n", "> Tier: Quick\n> Chain: revision=deep\n" + ENV_TEST + "\n> Backlog: values-fix\n"
)


class SpecCheckMetadataTest(unittest.TestCase):
    def test_metadata_in_output(self):
        result = ft.check_spec(META_SPEC)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["warnings"], [])
        self.assertEqual(result["chain"], {"revision": "deep"})
        self.assertEqual([env["name"] for env in result["environments"]], ["app_test"])
        self.assertEqual(result["backlog"], "values-fix")

    def test_old_spec_keeps_its_result(self):
        result = ft.check_spec(VALID_SPEC)
        self.assertEqual((result["ok"], result["errors"], result["warnings"]), (True, [], []))
        self.assertEqual((result["chain"], result["environments"], result["backlog"]), (None, [], None))

    def test_metadata_error_fails_the_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "m-spec.md")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(META_SPEC.replace("(test)", "(prod)"))
            code, out = _run("spec-check", path)
        self.assertEqual(code, 1)
        self.assertEqual(out["errors"], [
            "line 3: environment `app_test` is prod: write=run is not allowed (prod changes are task or deny only)"
        ])
        self.assertEqual(out["chain"], {"revision": "deep"})

    def test_malformed_metadata_fails_the_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "m-spec.md")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(META_SPEC.replace("> Chain: revision=deep", "> chain: revision=deep"))
            code, out = _run("spec-check", path)
        self.assertEqual((code, out["ok"], out["chain"]), (1, False, None))
        self.assertEqual(out["errors"], ["line 2: malformed-metadata: > chain: revision=deep"])

    def test_backlog_that_is_not_a_file_name_fails_the_cli(self):
        for value in ("a/b", "ops:infra", ".."):
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "m-spec.md")
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(META_SPEC.replace("> Backlog: values-fix", "> Backlog: " + value))
                code, out = _run("spec-check", path)
            self.assertEqual((code, out["ok"], out["backlog"]), (1, False, value))
            self.assertEqual(out["errors"], ["line 4: backlog-not-a-file-name: " + value])


class PlanEnvironmentTest(unittest.TestCase):
    def entry(self, line):
        result = {"environments": [], "errors": [], "warnings": []}
        ft._plan_environment(line, "line 7", result)
        return result

    def test_new_form(self):
        new = self.entry('- `app_test` (test; read=run, write=task) — "Тесты на app_test? — Да" (2026-10-01)')
        self.assertEqual((new["errors"], new["warnings"]), ([], []))
        self.assertEqual(new["environments"], [{"name": "app_test", "kind": "test", "read": "run", "write": "task",
                                                "quote": "Тесты на app_test? — Да", "date": "2026-10-01"}])
        prod = self.entry('- `app_db` (prod; read=run, write=run) — "Пишем в прод? — Да" (2026-10-01)')
        self.assertEqual(prod["errors"], [
            "line 7: environment `app_db` is prod: write=run is not allowed (prod changes are task or deny only)"
        ])

    def test_old_form_only_warns(self):
        old = self.entry('- `old_db` (prod) — "можно читать old_db (Recommended)"')
        self.assertEqual(old["errors"], [])
        self.assertEqual(old["warnings"], [
            "environment `old_db` has no read/write rights",
            "line 7: environment `old_db`: quote contains the interface marker '(Recommended)' "
            "(record the question and the user's answer only)",
        ])
        self.assertEqual((old["environments"][0]["read"], old["environments"][0]["date"]), (None, None))

    def test_unmatched_entries(self):
        broken = self.entry("- `app_db` read=run, write=task")
        self.assertEqual((len(broken["errors"]), broken["warnings"]), (1, []))
        legacy = self.entry("- `app_db` — без вида окружения")
        self.assertEqual((legacy["errors"], len(legacy["warnings"])), ([], 1))

    def test_old_form_with_other_tail_is_kept(self):
        old = self.entry('- `dev_db` (test) — "this database is made for tests" (user, 2026-09-30)')
        self.assertEqual(old["errors"], [])
        self.assertEqual(old["warnings"], ["environment `dev_db` has no read/write rights"])
        self.assertEqual([(e["name"], e["read"], e["write"], e["date"]) for e in old["environments"]],
                         [("dev_db", None, None, None)])

    def test_link_target(self):
        for value in ("[x-spec.md](./x-spec.md)", "`./x-spec.md`", "./x-spec.md"):
            self.assertEqual(ft._link_target(value), "./x-spec.md", value)


PLAN_HEADER = "\n".join([
    "# X Implementation Plan",
    "",
    "**Spec:** [x-spec.md](./x-spec.md)",
    "",
    "**Tier:** Deep",
    "",
    "**Chain:** split=never; resolver=skip",
    "",
    "**Backlog:** values-fix",
    "",
    "**Environments:**",
    '- `app_test` (test; read=run, write=task) — "Тесты на app_test? — Да" (2026-10-01)',
    '- `old_db` (prod) — "можно читать old_db" (2026-09-01)',
    "",
    FENCE,
    "**Chain:** split=bogus",
    FENCE,
    "",
    "### Task 1: Something",
    "",
    "**Backlog:** not-a-header-line",
])


class ParsePlanHeaderTest(unittest.TestCase):
    def test_header_settings(self):
        result = ft.parse_plan_header(PLAN_HEADER)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["warnings"], ["environment `old_db` has no read/write rights"])
        self.assertEqual((result["spec"], result["tier"]), ("./x-spec.md", "Deep"))
        self.assertEqual(result["chain"], {"split": "never", "resolver": "skip"})
        self.assertEqual(result["backlog"], "values-fix")
        self.assertEqual([(e["name"], e["read"], e["write"]) for e in result["environments"]],
                         [("app_test", "run", "task"), ("old_db", None, None)])

    def test_plain_header_has_no_settings(self):
        result = ft.parse_plan_header("# X\n\n**Spec:** `x-spec.md`\n\n**Tier:** Quick\n\n### Task 1: A\n")
        self.assertEqual((result["spec"], result["tier"]), ("x-spec.md", "Quick"))
        self.assertEqual((result["chain"], result["environments"], result["backlog"]), (None, [], None))
        self.assertEqual((result["errors"], result["warnings"]), ([], []))

    def test_header_errors(self):
        text = PLAN_HEADER.replace("split=never", "split=sometimes").replace(
            "**Backlog:** values-fix", "**Backlog:** values-fix\n**Chain:** stop=strict")
        self.assertEqual(ft.parse_plan_header(text)["errors"], [
            "line 7: unknown value 'sometimes' for chain key 'split' (allowed: auto, always, never)",
            "line 10: duplicate Chain line",
        ])


class CompleteChainTest(unittest.TestCase):
    def test_defaults_and_revision_from_tier(self):
        self.assertEqual(ft._complete_chain(None, "Deep"),
                         {"split": "auto", "revision": "deep", "stop": "pragmatic", "resolver": "audit"})
        self.assertEqual(ft._complete_chain({"stop": "strict"}, "Quick")["revision"], "quick")
        self.assertEqual(ft._complete_chain({"stop": "strict"}, None),
                         {"split": "auto", "revision": "standard", "stop": "strict", "resolver": "audit"})
        self.assertEqual(ft._complete_chain({"revision": "deep"}, "Huge")["revision"], "deep")

    def test_settings_missing(self):
        result = {"ok": True, "tier": "Quick", "chain": None, "errors": []}
        ft._settings_missing(result, "/x/x-spec.md")
        self.assertEqual(result["ok"], False)
        self.assertEqual(result["errors"], ["settings-source-missing: /x/x-spec.md"])
        self.assertEqual(result["chain"]["revision"], "quick")


class ResolveSettingsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name
        self.spec = self.write("x-spec.md", META_SPEC)
        self.plan = self.write("x-impl.md", "# X\n\n**Spec:** x-spec.md\n\n**Tier:** Quick\n\n### Task 1: A\n")

    def write(self, name, text):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return os.path.abspath(path)

    def assert_from_spec(self, result):
        import hashlib
        with open(self.spec, "rb") as fh:
            digest = hashlib.sha256(fh.read()).hexdigest()
        self.assertEqual((result["ok"], result["from"], result["source"]), (True, "spec", self.spec))
        self.assertEqual((result["source_sha256"], result["tier"]), (digest, "Quick"))
        self.assertEqual(result["chain"], {"split": "auto", "revision": "deep", "stop": "pragmatic", "resolver": "audit"})
        self.assertEqual((result["chain_explicit"], result["backlog"]), (True, "values-fix"))
        self.assertEqual([env["name"] for env in result["environments"]], ["app_test"])

    def test_spec_plan_roadmap_and_part_read_the_spec(self):
        roadmap = self.write("x-impl-roadmap.md", "# Roadmap\n\n> Source: [x-impl.md](./x-impl.md)\n")
        part = self.write("x-impl-a.md", "# Стадия a: A\n\n> Источник: [x-impl.md](./x-impl.md)\n")
        for path in (self.spec, self.plan, roadmap, part):
            self.assert_from_spec(ft.resolve_settings(path))

    def test_source_line_forms(self):
        for line in ("> Source: [x](x-impl.md)", "> **Source:** [x](x-impl.md)", "> **Source**: [x](x-impl.md)",
                     "> Источник: [x](x-impl.md)", "> **Источник:** [x](x-impl.md)", "> **Источник**: [x](x-impl.md)",
                     "> Source: [x](<x-impl.md>)"):
            match = ft.SOURCE_RE.match(line)
            self.assertIsNotNone(match, line)
            self.assertEqual(match.group("target"), "x-impl.md", line)
        self.assertEqual(ft.SOURCE_RE.match("> Source: [p](<a b/p.md>)").group("target"), "a b/p.md")
        self.assertIsNone(ft.SOURCE_RE.match("> Source: [p](a b/p.md)"))
        os.mkdir(os.path.join(self.dir, "a b"))
        self.write(os.path.join("a b", "x-impl.md"), "# X\n\n**Spec:** ../x-spec.md\n\n**Tier:** Quick\n\n### Task 1: A\n")
        roadmap = self.write("x-impl-roadmap.md", "# Roadmap\n\n> **Source:** [x-impl.md](<a b/x-impl.md>)\n")
        self.assert_from_spec(ft.resolve_settings(roadmap))

    def test_plan_header_settings_win(self):
        plan = self.write("y-impl.md", PLAN_HEADER.replace("./x-spec.md", "./missing-spec.md"))
        result = ft.resolve_settings(plan)
        self.assertEqual((result["ok"], result["from"], result["source"], result["tier"]), (True, "plan-header", plan, "Deep"))
        self.assertEqual(result["chain"], {"split": "never", "revision": "deep", "stop": "pragmatic", "resolver": "skip"})
        self.assertEqual(result["chain_explicit"], True)
        self.assertEqual(result["warnings"], ["environment `old_db` has no read/write rights"])

    def test_defaults_and_missing_targets(self):
        result = ft.resolve_settings(self.write("z-spec.md", VALID_SPEC))
        self.assertEqual((result["ok"], result["chain_explicit"], result["chain"]["revision"]), (True, False, "quick"))
        plan = self.write("w-impl.md", "# W\n\n**Spec:** w-spec.md\n\n**Tier:** Deep\n\n### Task 1: A\n")
        missing = os.path.join(self.dir, "w-spec.md")
        result = ft.resolve_settings(plan)
        self.assertEqual((result["ok"], result["errors"]), (False, [f"settings-source-missing: {missing}"]))
        self.assertEqual(result["chain"]["revision"], "deep")
        self.assertFalse(ft.resolve_settings(self.write("v-roadmap.md", "> Source: [v.md](./v.md)\n"))["ok"])

    def test_file_without_settings_source(self):
        # A plan without **Spec:** (older executor fixtures), not a spec, not a roadmap/part.
        path = self.write("notes.md", "# N\n\n### Task 1: A\n\n**External:** `db` — x\n")
        self.assertEqual(ft.resolve_settings(path), {
            "ok": True, "from": "none", "source": None, "source_sha256": None, "tier": None,
            "chain": {"split": "auto", "revision": "standard", "stop": "pragmatic", "resolver": "audit"},
            "chain_explicit": False, "environments": [], "backlog": None, "errors": [], "warnings": []})


class SettingsCliTest(unittest.TestCase):
    def test_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = os.path.join(tmp, "x-spec.md")
            plan = os.path.join(tmp, "x-impl.md")
            with open(spec, "w", encoding="utf-8") as fh:
                fh.write(META_SPEC)
            with open(plan, "w", encoding="utf-8") as fh:
                fh.write("# X\n\n**Spec:** gone-spec.md\n\n**Tier:** Quick\n\n### Task 1: A\n")
            code, out = _run("settings", spec)
            self.assertEqual((code, out["from"], out["chain"]["revision"]), (0, "spec", "deep"))
            self.assertEqual(out["environments"][0]["quote"], "Тесты на app_test? — Да")
            code, out = _run("settings", plan)
            self.assertEqual((code, out["ok"]), (2, False))
            self.assertTrue(out["errors"][0].startswith("settings-source-missing: "))
            self.assertEqual(_run("settings", os.path.join(tmp, "nope.md"))[0], 2)
            with open(spec, "w", encoding="utf-8") as fh:
                fh.write(META_SPEC.replace("revision=deep", "revision=huge"))
            code, out = _run("settings", spec)
            self.assertEqual((code, out["ok"], out["chain_explicit"]), (1, False, True))

    def test_malformed_metadata_is_a_settings_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = os.path.join(tmp, "x-spec.md")
            with open(spec, "w", encoding="utf-8") as fh:
                fh.write(META_SPEC.replace("> Chain: revision=deep", "> Chain : revision=deep"))
            code, out = _run("settings", spec)
        self.assertEqual((code, out["ok"], out["errors"]), (0, True, []))
        self.assertEqual(out["warnings"], ["malformed-metadata: > Chain : revision=deep"])
        self.assertEqual((out["chain_explicit"], out["chain"]["revision"], out["backlog"]), (False, "quick", "values-fix"))


class NonUtf8InputTest(unittest.TestCase):
    """F1: a file not in UTF-8 is an input error (JSON, exit 2), never a traceback."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.spec = os.path.join(self.tmp.name, "legacy-spec.md")
        with open(self.spec, "wb") as fh:
            fh.write("> Tier: Quick\n\n# Goal\n\nЦель в cp1251.\n".encode("cp1251"))
        self.findings = os.path.join(self.tmp.name, "review01.json")
        with open(self.findings, "w", encoding="utf-8") as fh:
            json.dump(SAMPLE, fh, ensure_ascii=False)

    def test_commands_report_json_and_exit_2(self):
        for args in (("journal-path", self.spec), ("spec-check", self.spec),
                     ("findings-coverage", self.findings, self.spec)):
            with self.subTest(command=args[0]):
                proc = subprocess.run([sys.executable, TOOL, *args], capture_output=True, encoding="utf-8")
                self.assertEqual(proc.returncode, 2, proc.stderr)
                self.assertNotIn("Traceback", proc.stderr)
                out = json.loads(proc.stdout)
                self.assertFalse(out["ok"])
                self.assertEqual(len(out["errors"]), 1, out["errors"])
                self.assertTrue(out["errors"][0].startswith(f"cannot read {self.spec}: "), out["errors"])

    def test_read_source_raises_input_error(self):
        with self.assertRaises(ft.InputError) as ctx:
            ft._read_source(self.spec)
        self.assertIn("cannot read", str(ctx.exception))


TASKS_PLAN = "\n".join([
    "# P",
    "",
    "## Phase 1: Core",
    "",
    "### Task 1: Parser",
    "",
    FENCE + "markdown",
    "## Task 9: not a task",
    FENCE,
    "",
    "#### Step notes",
    "",
    "### Notes",
    "",
    "### Task 1.1: Docs",
    "",
    "## Phase 2: Next",
    "",
    "#### Задача 2: Checkpoint — smoke",
    "",
    "### Task: no id",
    "### Task 3 title",
    "### Task 2: Again",
    "",
])


class PlanTasksTest(unittest.TestCase):
    """parse_plan_tasks: the one parser of `### Task N: <title>` for every pipeline script."""

    def test_boundaries_sections_and_levels(self):
        parsed = ft.parse_plan_tasks(TASKS_PLAN)
        self.assertEqual([(t["id"], t["level"], t["line_start"], t["line_end"]) for t in parsed["tasks"]],
                         [("1", 3, 5, 12), ("1.1", 3, 15, 16), ("2", 4, 19, 20), ("2", 3, 23, 23)])
        self.assertEqual([t["section"] for t in parsed["tasks"]],
                         ["## Phase 1: Core", "## Phase 1: Core", "## Phase 2: Next", "## Phase 2: Next"])
        self.assertEqual([t["checkpoint"] for t in parsed["tasks"]], [False, False, True, False])
        self.assertEqual(parsed["tasks"][0]["title"], "Parser")

    def test_malformed_and_duplicates(self):
        parsed = ft.parse_plan_tasks(TASKS_PLAN)
        self.assertEqual(parsed["malformed"], [{"line": 21, "text": "### Task: no id"},
                                               {"line": 22, "text": "### Task 3 title"}])
        self.assertEqual(parsed["duplicates"], [{"id": "2", "lines": [19, 23]}])

    def test_subtask_right_after_task_ends_it(self):
        parsed = ft.parse_plan_tasks("### Task 1: A\nbody\n### Task 1.1: B\nmore\n")
        self.assertEqual([(t["id"], t["line_start"], t["line_end"]) for t in parsed["tasks"]],
                         [("1", 1, 2), ("1.1", 3, 4)])

    def test_plan_without_tasks(self):
        self.assertEqual(ft.parse_plan_tasks("# Plan\n\n1. step\n"),
                         {"tasks": [], "malformed": [], "duplicates": [], "incomplete": False, "marker_spec_sha": None})

    def test_ids_and_refs_are_normalized(self):  # F7 of plan-refactoring-02
        self.assertEqual([ft.normalize_task_id(v) for v in ("01.02", "007", "1.10", " 3 ", "A1", "x.01")],
                         ["1.2", "7", "1.10", "3", "A1", "x.01"])
        plan = "### Task 01: A\nbody\n\n### Task 02: B\n\n**Preconditions:**\n- Task 1 is done, Task 01.0 too\n"
        parsed = ft.parse_plan_tasks(plan)
        self.assertEqual([(t["id"], t["refs"]) for t in parsed["tasks"]], [("1", []), ("2", ["1", "1.0"])])
        duplicated = ft.parse_plan_tasks("### Task 1: A\nx\n\n### Task 01: B\ny\n")
        self.assertEqual(duplicated["duplicates"], [{"id": "1", "lines": [1, 4]}])

    def test_writing_marker(self):  # spec 3 of plan-refactoring-02
        marker = "> Writing: in progress (spec sha256 0123456789ab)"
        plan = "# P\n\n### Task 1: A\nbody\n\n### Task 2: B\nmore\n\n" + marker + "\n"
        parsed = ft.parse_plan_tasks(plan)
        self.assertEqual((parsed["incomplete"], parsed["marker_spec_sha"]), (True, "0123456789ab"))
        self.assertEqual([(t["id"], t["line_start"], t["line_end"]) for t in parsed["tasks"]], [("1", 3, 5), ("2", 6, 8)])
        self.assertEqual(parsed["tasks"][1]["size_bytes"], len("### Task 2: B\nmore\n"))
        self.assertEqual(ft.writing_marker(plan), {"line": 9, "spec_sha": "0123456789ab"})
        middle = ft.parse_plan_tasks("### Task 1: A\nbody\n> Writing: in progress\n### Task 2: B\n")
        self.assertEqual((middle["incomplete"], middle["marker_spec_sha"]), (True, None))
        self.assertEqual([(t["id"], t["line_start"], t["line_end"]) for t in middle["tasks"]], [("1", 1, 2)])
        broken = ft.parse_plan_tasks("### Task 1: A\n\n> Writing: in progress (spec sha256 XYZ)\n")
        self.assertEqual((broken["incomplete"], broken["marker_spec_sha"]), (True, None))
        fenced = ft.parse_plan_tasks("### Task 1: A\n\n" + FENCE + "text\n" + marker + "\n" + FENCE + "\n")
        self.assertEqual((fenced["incomplete"], fenced["marker_spec_sha"]), (False, None))
        self.assertIsNone(ft.writing_marker("# P\n"))


NESTED_FENCE_PLAN = "\n".join([
    "### Task 1: Outer",
    "text",
    "````markdown",
    "### Task 9: quoted inside a four-backtick block",
    "```python",
    "x = 1",
    "```",
    "more",
    "````",
    "after",
    "### Task 2: Next",
    "body",
    "~~~",
    "```",
    "### Task 8: inside a tilde block",
    "~~~",
    "tail",
])


class NestedFenceTest(unittest.TestCase):
    """F6/F13: a ```` block may hold ``` lines; a fence closes only on its own character and length."""

    def test_nested_fences_do_not_split_tasks(self):
        parsed = ft.parse_plan_tasks(NESTED_FENCE_PLAN)
        self.assertEqual([(t["id"], t["line_start"], t["line_end"]) for t in parsed["tasks"]],
                         [("1", 1, 10), ("2", 11, 17)])
        self.assertEqual(parsed["malformed"], [])

    def test_code_lines_count_only_lines_inside_fences(self):
        parsed = ft.parse_plan_tasks(NESTED_FENCE_PLAN)
        self.assertEqual([t["code_lines"] for t in parsed["tasks"]], [5, 2])

    def test_unclosed_fence_runs_to_the_end(self):
        parsed = ft.parse_plan_tasks("### Task 1: A\n````\n### Task 2: B\n```\nstill code\n")
        self.assertEqual([(t["id"], t["line_end"]) for t in parsed["tasks"]], [("1", 5)])

    def test_backtick_fence_with_backtick_in_info_is_text(self):
        unfenced = ft._unfenced_lines("``` not a `fence`\n### Task 1: A\n")
        self.assertEqual([number for number, _ in unfenced], [1, 2])

    def test_spec_check_ignores_nested_fences(self):
        spec = VALID_SPEC.replace("## Architecture\n", "## Architecture\n````markdown\n```\n# Goal\n```\n````\n", 1)
        result = ft.check_spec(spec)
        self.assertTrue(result["ok"], result["errors"])


class PlanTaskBodyTest(unittest.TestCase):
    def test_code_lines_count_lines_inside_fences(self):
        parsed = ft.parse_plan_tasks(TASKS_PLAN)
        self.assertEqual([t["code_lines"] for t in parsed["tasks"]], [1, 0, 0, 0])

    def test_sha1_ignores_line_endings_and_trailing_blank_lines(self):
        base = ft.parse_plan_tasks("### Task 1: A\nbody\n")["tasks"][0]
        crlf = ft.parse_plan_tasks("### Task 1: A\r\nbody\r\n\r\n\r\n")["tasks"][0]
        changed = ft.parse_plan_tasks("### Task 1: A\nbody!\n")["tasks"][0]
        self.assertEqual((crlf["sha1"], crlf["size_bytes"]), (base["sha1"], base["size_bytes"]))
        self.assertEqual(base["size_bytes"], len("### Task 1: A\nbody\n"))
        self.assertRegex(base["sha1"], r"^[0-9a-f]{8}$")
        self.assertNotEqual(changed["sha1"], base["sha1"])


FILES_PLAN = "\n".join([
    "### Task 1: Files and refs",
    "",
    "**Files:**",
    "- Create: `src/parser.py`",
    "- Modify: `src/app.py:4-6` (current state / change / preserve)",
    "- Test: [test_parser.py](tests/test_parser.py)",
    "- `notes.txt`",
    "",
    "**Preconditions:**",
    "- Task 1.2 is done; Задача 3 тоже, Task 1.2 again.",
    "",
    "**Postconditions:**",
    "- Task 7 is not a precondition.",
    "",
    "- [ ] **Step 1: Do it**",
    "",
    "- Modify: `outside.py` is not in the Files block",
    "",
])


class PlanTaskFilesRefsTest(unittest.TestCase):
    def test_files_follow_executor_rules(self):
        task = ft.parse_plan_tasks(FILES_PLAN)["tasks"][0]
        self.assertEqual(task["files"], [
            {"path": "src/parser.py", "action": "create", "lines": None},
            {"path": "src/app.py", "action": "modify", "lines": "4-6"},
            {"path": "test_parser.py", "action": "test", "lines": None},
            {"path": "notes.txt", "action": None, "lines": None},
        ])

    def test_refs_come_from_preconditions_only(self):
        task = ft.parse_plan_tasks(FILES_PLAN)["tasks"][0]
        self.assertEqual(task["refs"], ["1.2", "3"])

    def test_task_without_blocks(self):
        task = ft.parse_plan_tasks("### Task 2: Checkpoint — x\n\n**Done when:** ok\n")["tasks"][0]
        self.assertEqual((task["files"], task["refs"]), ([], []))
        self.assertEqual(list(task), ["id", "title", "level", "line_start", "line_end", "checkpoint", "section",
                                      "files", "refs", "size_bytes", "code_lines", "sha1"])


class PlanTasksCliTest(unittest.TestCase):
    def test_cli_prints_the_parse(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "x-impl.md")
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(TASKS_PLAN)
            code, out = _run("plan-tasks", path)
        self.assertEqual(code, 0, out)
        self.assertTrue(out["ok"])
        self.assertEqual(out["tasks"], ft.parse_plan_tasks(TASKS_PLAN)["tasks"])
        self.assertEqual(len(out["malformed"]), 2)

    def test_cli_unreadable_plan_is_exit_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = os.path.join(tmp, "missing-impl.md")
            code, out = _run("plan-tasks", missing)
            self.assertEqual((code, out), (2, {"ok": False, "errors": [f"plan-unreadable: {missing}"]}))
            legacy = os.path.join(tmp, "cp1251-impl.md")
            with open(legacy, "wb") as fh:
                fh.write("### Task 1: Задача\n".encode("cp1251"))
            code, out = _run("plan-tasks", legacy)
            self.assertEqual((code, out["errors"]), (2, [f"plan-unreadable: {legacy}"]))

    def test_header_ends_at_the_first_task_heading_malformed_included(self):
        text = "# X\n\n**Spec:** x-spec.md\n\n### Task: no id\n\n**Backlog:** not-header\n\n### Task 1: A\n"
        result = ft.parse_plan_header(text)
        self.assertEqual((result["spec"], result["backlog"]), ("x-spec.md", None))
        self.assertFalse(hasattr(ft, "PLAN_TASK_RE"))


def _put(root, name, text, encoding="utf-8"):
    path = os.path.join(root, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(text.encode(encoding))
    return path


GOAL_SPEC = ("> Tier: {tier}\n> Backlog: g\n\n# Goal\n\n{goal}\n\n## Architecture\n\n{arch}\n\n"
             "## Components\n\n| Component | Responsibility |\n|---|---|\n{rows}\n\n## Data Flow\n\n(none) — CLI.\n\n"
             "## Error Handling\n\n- Exit 2.\n\n## Testing Strategy\n\n- Unit tests.\n\n## Out of Scope\n\n- Other.\n\n"
             "## Open Questions\n\n(none)\n")


def _goal_spec(goal="Do the thing. More words.", rows="| `a.py` | A |", arch="Plain.", tier="Standard"):
    return GOAL_SPEC.format(tier=tier, goal=goal, arch=arch, rows=rows)


class InputsHelpersTest(unittest.TestCase):
    def test_plan_root(self):
        for name, root in (("plan02-goal.md", "plan02"), ("plan01.md", "plan01"), ("goal.md", "goal"),
                           ("superplan03-abstract.md", "superplan03"), ("review01.json", "review01"),
                           ("plan-refactoring-01-goal.md", "plan-refactoring-01"), ("a-goal.md", "a-goal")):
            self.assertEqual(ft._plan_root(name), root, name)

    def test_findings_count(self):
        self.assertEqual(ft._findings_count(json.dumps(SAMPLE)), 2)
        self.assertEqual(ft._findings_count(json.dumps({"findings": SAMPLE})), 2)
        self.assertIsNone(ft._findings_count('[{"file": "a.py"}]'))
        self.assertIsNone(ft._findings_count("[]"))
        with self.assertRaises(ValueError):
            ft._findings_count("[not json")


class InputsClassifyTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name

    def kind(self, name, text, encoding="utf-8"):
        entry, _ = ft._classify_input(_put(self.dir, name, text, encoding))
        return entry["kind"]

    def test_every_kind(self):
        self.assertEqual(self.kind("x-spec.md", _goal_spec()), "spec")
        self.assertEqual(self.kind("y-spec.md", "# Title\n"), "markdown")  # -spec.md without # Goal
        self.assertEqual(self.kind("BACKLOG.md", "# Backlog\n"), "backlog")
        self.assertEqual(self.kind("x-impl.md", "# P\n\n### Task 1: A\n"), "plan")
        self.assertEqual(self.kind("z-impl.md", "# P\n"), "markdown")
        self.assertEqual(self.kind("g-roadmap.md", "> Goal: g\n> Specs: 1\n"), "goal-roadmap")
        self.assertEqual(self.kind("notes.txt", "plain text\n"), "text")
        self.assertEqual(self.kind("data.json", '{"a": 1}'), "json")
        self.assertEqual(self.kind("list.json", '[{"file": "a.py"}]'), "json")  # no summary
        self.assertEqual(self.kind("bad.json", "[not json"), "text")
        self.assertEqual(self.kind("blob.bin", "Привет", encoding="cp1251"), "binary")
        missing = os.path.join(self.dir, "none.md")
        self.assertEqual(ft._classify_input(missing), ({"path": missing, "exists": False, "kind": "missing"}, False))

    def test_findings_count_lang_and_size(self):
        path = _put(self.dir, "review.json", json.dumps({"findings": SAMPLE}))
        entry, candidate = ft._classify_input(path)
        self.assertEqual((entry["kind"], entry["count"], entry["lang"], entry["lines"]), ("findings", 2, "ru", 1))
        self.assertEqual((entry["bytes"], candidate), (os.path.getsize(path), False))

    def test_goal_candidates_are_markdown_without_spec_headings(self):
        self.assertTrue(ft._classify_input(_put(self.dir, "idea.md", "# Idea\n\nТекст.\n"))[1])
        self.assertFalse(ft._classify_input(_put(self.dir, "old.md", "# Goal\n\nx\n"))[1])


class InputsReportTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name
        self.goal = _put(self.dir, "goal.md", "# Цель\n\nСделать отчёт.\n")
        self.research = _put(self.dir, "research.md", "# Research\n\nNotes.\n")
        self.findings = _put(self.dir, "findings.json", json.dumps(SAMPLE))

    def test_multi_with_note(self):
        code, out = ft.inputs_report([self.research, self.goal, self.findings], "research — справочно")
        self.assertEqual((code, out["mode"], out["plan_root"], out["lang"], out["warnings"]),
                         (0, "multi", "goal", "ru", []))
        self.assertEqual([f["kind"] for f in out["files"]], ["markdown", "goal", "findings"])
        self.assertEqual(out["note"], "research — справочно")

    def test_single_file_modes(self):
        spec = _put(self.dir, "x-spec.md", _goal_spec())
        backlog = _put(self.dir, "BACKLOG.md", "# Backlog\n")
        for paths, mode in (([spec], "amend"), ([self.findings], "findings"), ([backlog], "backlog"),
                            ([self.research], "idea"), ([spec, self.goal], "multi")):
            self.assertEqual(ft.inputs_report(paths, None)[1]["mode"], mode, paths)
        out = ft.inputs_report([self.research], None)[1]
        self.assertEqual((out["files"][0]["kind"], out["plan_root"]), ("goal", "research"))  # the only candidate

    def test_note_only_is_idea(self):
        code, out = ft.inputs_report([], "добавить поиск")
        self.assertEqual((code, out["mode"], out["files"], out["plan_root"], out["lang"]), (0, "idea", [], None, "ru"))
        with self.assertRaisesRegex(ft.InputError, "nothing-to-classify"):
            ft.inputs_report([], "  ")

    def test_several_goals_missing_and_binary(self):
        first = _put(self.dir, "a-goal.md", "# A\n")
        second = _put(self.dir, "b-goal.md", "# B\n")
        blob = _put(self.dir, "x.bin", "Привет", encoding="cp1251")
        missing = os.path.join(self.dir, "nope.md")
        code, out = ft.inputs_report([first, second, blob, missing], None)
        self.assertEqual((code, out["ok"], out["plan_root"]), (1, False, "a-goal"))
        self.assertEqual(out["warnings"], [f"binary: {blob}", f"several-goals: plan_root from {first}"])
        self.assertEqual(out["errors"], [f"missing: {missing}"])
        self.assertIsNone(ft.inputs_report([self.findings, _put(self.dir, "n.txt", "text\n")], None)[1]["plan_root"])

    def test_cli(self):
        code, out = _run("inputs", self.goal, self.findings, "--note", "fix")
        self.assertEqual((code, out["mode"], [f["kind"] for f in out["files"]]), (0, "multi", ["goal", "findings"]))
        code, out = _run("inputs")
        self.assertEqual((code, out["errors"]), (2, ["nothing-to-classify: give input files or --note"]))
        self.assertEqual(_run("inputs", os.path.join(self.dir, "nope.md"))[0], 1)


class GoalDirCase(unittest.TestCase):
    """A goal directory: specs g-N-spec.md and, with `journal=True`, g-chain.json registering them in order."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = os.path.realpath(tmp.name)
        self.journal = os.path.join(self.dir, "g-chain.json")

    def specs(self, texts, journal=True):
        paths = [_put(self.dir, f"g-{n}-spec.md", text) for n, text in texts]
        if journal:
            for path in paths:
                ft.journal_create(self.journal, "g", "ru", path)
        return [os.path.basename(path) for path in paths]


class GoalJournalTest(GoalDirCase):
    def test_specs_of_the_journal_in_its_order(self):
        names = self.specs([(2, _goal_spec()), (1, _goal_spec())])
        warnings = []
        self.assertEqual((ft._set_specs(self.dir, None, warnings), warnings), ((self.journal, names), []))
        ft._set_specs(self.dir, ["x-spec.md"], warnings)
        self.assertEqual(warnings, ["specs-ignored: the journal lists the goal's specs"])

    def test_without_a_journal(self):
        self.specs([(10, _goal_spec()), (2, _goal_spec())], journal=False)
        warnings = []
        self.assertEqual(ft._set_specs(self.dir, None, warnings), (None, ["g-2-spec.md", "g-10-spec.md"]))
        self.assertEqual(ft._set_specs(self.dir, [os.path.join(self.dir, "g-10-spec.md")], warnings),
                         (None, ["g-10-spec.md"]))
        self.assertEqual(warnings, ["no-journal", "no-journal"])

    def test_several_journals_and_spec_number(self):
        self.specs([(1, _goal_spec())])
        _put(self.dir, "h-chain.json", json.dumps(ft._new_journal("h", "en")))
        self.assertEqual(ft._goal_journal(self.dir, "g")[0], self.journal)
        with self.assertRaisesRegex(ft.InputError, "ambiguous-journal: g-chain.json, h-chain.json"):
            ft._goal_journal(self.dir)
        self.assertEqual((ft._spec_number("g-12-spec.md"), ft._spec_number("g-spec.md")), (12, None))

    def test_goal_picks_one_of_several_journals(self):
        names = self.specs([(1, _goal_spec()), (2, _goal_spec())])
        other = _put(self.dir, "h-1-spec.md", _goal_spec())
        other_journal = os.path.join(self.dir, "h-chain.json")
        ft.journal_create(other_journal, "h", "ru", other)
        with self.assertRaisesRegex(ft.InputError, "ambiguous-journal"):
            ft._set_specs(self.dir, None, [])
        self.assertEqual(ft._set_specs(self.dir, None, [], "g"), (self.journal, names))
        os.remove(self.journal)
        os.remove(other_journal)
        warnings = []
        self.assertEqual(ft._set_specs(self.dir, None, warnings, "g"), (None, names))  # h-1-spec.md stays out
        self.assertEqual(warnings, ["no-journal"])


class SpecSetHelpersTest(unittest.TestCase):
    def test_components_cells_and_names(self):
        lines = ["## Components", "", "| Unit | Role |", "|---|---|", "| `a/b.py`: `run_x` (`:12`), `--flag` | x |",
                 "| `c.py:40-45` `<dir>` | y |", "## Data Flow", "| `d.py` | z |"]
        cells = ft._components_cells(lines)
        self.assertEqual([name for cell in cells for name in ft._touch_names(cell)],
                         [("a/b.py", "path"), ("run_x", "symbol"), ("c.py", "path")])
        self.assertIsNone(ft._components_cells(["## Components", "- `a.py`: A"]))

    def test_components_end_at_the_next_section(self):  # F16 of plan-refactoring-02
        lines = ["## Components  ", "| Unit | Role |", "|---|---|", "| `a.py` | A |", "### Executor", "| `b.py` | B |",
                 "## Notes", "| Unit | Role |", "|---|---|", "| `c.py` | C |"]
        cells = ft._components_cells(lines)
        self.assertEqual([name for cell in cells for name, _ in ft._touch_names(cell)], ["a.py", "b.py"])

    def test_mentions_and_numbered_references(self):
        names = ["g-1-spec.md", "g-2-spec.md", "g-3-spec.md", "gg-3-spec.md"]
        text = "Спеку 1 и spec 3; после g-2-spec.md, не gg-1-spec.md."
        self.assertEqual(ft._spec_mentions(text, "g-2-spec.md", names), ["g-1-spec.md"])
        self.assertEqual(ft._spec_mentions("см. gg-3-spec.md", "g-1-spec.md", names), ["gg-3-spec.md"])
        text = "`references/LOOP.md` §2, START.md (пункт 3), step 4 of it"
        self.assertEqual([m.group("path") for m in ft.NUMBERED_REF_RE.finditer(text)], ["references/LOOP.md", "START.md"])


class SpecSetCheckTest(GoalDirCase):
    def test_touchpoints_undeclared_numbered_and_self_edges(self):
        one = _goal_spec(rows="| `skills/x/chain_tool.py`: `run_status` (`:12`) | A |\n| `LOOP.md` §2 | B |")
        two = _goal_spec(arch="Спека 1 даёт `run_status`; `LOOP.md` §2 правят обе.",
                         rows="| `skills/x/chain_tool.py:40` | A |\n| `run_status` | B |\n| `own.py` | C |")
        three = _goal_spec(rows="| `run_status` | A |")
        names = self.specs([(1, one), (2, two), (3, three)])
        out = ft.spec_set_check(self.dir)
        self.assertEqual((out["specs"], out["warnings"], out["journal"]), (names, [], self.journal))
        self.assertEqual(out["touchpoints"], [{"name": "skills/x/chain_tool.py", "kind": "path", "specs": names[:2]},
                                              {"name": "run_status", "kind": "symbol", "specs": names}])
        self.assertEqual(out["undeclared"], [{"name": "run_status", "specs": names}])  # 3 names nobody
        self.assertEqual(out["numbered_items"], [{"file": "LOOP.md", "specs": names[:2]}])
        self.assertEqual(out["self_edges"], [{"spec": names[1], "mentions": [names[0]]}])

    def test_file_name_mention_declares_the_pair(self):
        names = self.specs([(1, _goal_spec()), (2, _goal_spec(arch="После g-1-spec.md."))])
        out = ft.spec_set_check(self.dir)
        self.assertEqual((out["undeclared"], out["self_edges"]), ([], [{"spec": names[1], "mentions": [names[0]]}]))

    def test_shared_documents_and_test_rows_are_not_touchpoints(self):  # F15 of plan-refactoring-02
        rows = ("| `skills/x/tool.py` | A |\n| `CLAUDE.md`, `README.md`, `skills/x/USAGE.md`, `docs/HELPER-CLIS.md` | B |\n"
                "| Тесты: `skills/x/tests/test_tool.py` | C |\n| Docs: `docs/guide/deep.md` | D |")
        names = self.specs([(1, _goal_spec(rows=rows)), (2, _goal_spec(rows=rows))])
        out = ft.spec_set_check(self.dir)
        self.assertEqual(out["touchpoints"], [{"name": "skills/x/tool.py", "kind": "path", "specs": names}])

    def test_single_spec_no_journal_and_no_table(self):
        self.specs([(1, _goal_spec())])
        out = ft.spec_set_check(self.dir)
        self.assertEqual((out["warnings"], out["touchpoints"]), (["single-spec"], []))
        os.remove(self.journal)
        table = "| Component | Responsibility |\n|---|---|\n| `a.py` | A |"
        _put(self.dir, "g-2-spec.md", _goal_spec().replace(table, "- `a.py`: A"))
        out = ft.spec_set_check(self.dir)
        self.assertEqual((out["specs"], out["warnings"]),
                         (["g-1-spec.md", "g-2-spec.md"], ["no-journal", "no-components-table: g-2-spec.md"]))

    def test_cli_and_unreadable_spec(self):
        self.specs([(1, _goal_spec()), (2, _goal_spec())])
        code, out = _run("spec-set-check", self.dir)
        self.assertEqual((code, len(out["touchpoints"])), (0, 1))
        os.remove(os.path.join(self.dir, "g-2-spec.md"))
        code, out = _run("spec-set-check", self.dir)
        self.assertEqual(code, 2)
        self.assertIn("g-2-spec.md", out["errors"][0])

    def test_goal_option_picks_the_journal(self):
        self.specs([(1, _goal_spec()), (2, _goal_spec())])
        other = _put(self.dir, "h-1-spec.md", _goal_spec())
        ft.journal_create(os.path.join(self.dir, "h-chain.json"), "h", "ru", other)
        code, out = _run("spec-set-check", self.dir)
        self.assertEqual(code, 2)
        self.assertIn("ambiguous-journal", out["errors"][0])
        code, out = _run("spec-set-check", self.dir, "--goal", "g")
        self.assertEqual((code, out["specs"]), (0, ["g-1-spec.md", "g-2-spec.md"]))


def _graph(**extra):
    graph = {"title": "Цель G", "overview": "Три спеки.", "lang": "ru",
             "sources": [{"path": "goal.md", "role": "постановка"}], "instruction": "research — справочно",
             "specs": [{"file": "g-1-spec.md", "title": "Первая", "depends": [], "group": "A",
                        "notes": "раньше всех", "handoff": "парсер"},
                       {"file": "g-2-spec.md", "title": "Вторая | с чертой", "depends": [], "group": "A"},
                       {"file": "g-3-spec.md", "title": "Третья", "depends": ["g-2-spec.md", "g-1-spec.md"],
                        "group": "B"}],
             "shared": [{"name": "run_status", "specs": ["g-1-spec.md", "g-3-spec.md"],
                         "order": ["g-1-spec.md", "g-3-spec.md"], "note": "3 сохраняет поле"}]}
    graph.update(extra)
    return graph


class RoadmapGraphFieldsTest(unittest.TestCase):
    def test_fields(self):
        self.assertEqual((ft._graph_text("  x \n", "w"), ft._graph_text("  ", "w")), ("x", None))
        with self.assertRaisesRegex(ft.InputError, "graph-invalid: w is required"):
            ft._graph_text(None, "w", True)
        with self.assertRaisesRegex(ft.InputError, "graph-invalid: w must be a string"):
            ft._graph_text(3, "w")
        self.assertEqual(ft._graph_files(["./a-spec.md", "b\\c-spec.md"], "w"), ["a-spec.md", "b/c-spec.md"])
        self.assertEqual(ft._graph_files(None, "w"), [])
        with self.assertRaisesRegex(ft.InputError, "graph-invalid: w must be a list of spec files"):
            ft._graph_files(["a", ""], "w")
        with self.assertRaisesRegex(ft.InputError, "graph-invalid: sources must be a list of objects"):
            ft._graph_items({"sources": ["x"]}, "sources")
        self.assertEqual(ft._graph_items({}, "shared"), [])


class RoadmapGraphTest(unittest.TestCase):
    def test_shape(self):
        graph = ft._roadmap_graph(_graph())
        self.assertEqual((graph["goal"], graph["lang"], graph["title"], graph["notes"]), (None, "ru", "Цель G", None))
        self.assertEqual(graph["specs"][2], {"file": "g-3-spec.md", "title": "Третья", "group": "B", "notes": None,
                                             "depends": ["g-2-spec.md", "g-1-spec.md"], "handoff": None})
        self.assertEqual(graph["shared"][0], dict(_graph()["shared"][0], kind=None))
        self.assertEqual(graph["sources"], [{"path": "goal.md", "role": "постановка"}])

    def test_bad_json(self):
        one = {"file": "g-1-spec.md", "title": "T", "group": "A"}
        for graph, message in (([], "not a JSON object"), (_graph(specs=[]), "specs must list each spec once"),
                               (_graph(specs=[one, one]), "specs must list each spec once"),
                               (_graph(specs=[dict(one, group="A-1")]), r"specs\[0\]\.group must be"),
                               (_graph(specs=[dict(one, title=None)]), r"specs\[0\]\.title is required"),
                               (_graph(lang="de"), "lang must be ru or en")):
            with self.assertRaisesRegex(ft.InputError, "graph-invalid: " + message):
                ft._roadmap_graph(graph)


class RoadmapOrderTest(unittest.TestCase):
    def specs(self, *items):
        return [{"file": name, "depends": deps, "group": group} for name, deps, group in items]

    def test_levels_then_json_order(self):
        order, errors = ft._roadmap_order(self.specs(("b", ["a"], "B"), ("c", [], "A"), ("a", [], "A")))
        self.assertEqual((order, errors), (["c", "a", "b"], []))

    def test_errors(self):
        self.assertEqual(ft._roadmap_order(self.specs(("a", ["x"], "A")))[1], ["unknown-dependency: a -> x"])
        self.assertEqual(ft._roadmap_order(self.specs(("a", ["b"], "A"), ("b", ["a"], "B")))[1],
                         ["dependency-cycle: a -> b -> a"])
        self.assertEqual(ft._roadmap_order(self.specs(("a", [], "A"), ("b", ["a"], "A")))[1],
                         ["group-conflict: b and its dependency a are both in group A"])

    def test_shared_errors(self):
        position = {"a": 1, "b": 2}
        item = {"name": "x.py", "specs": ["a", "b"], "order": ["b", "a"]}
        self.assertEqual(ft._shared_errors([item], position),
                         ["shared-order-conflict: x.py: b → a goes against the execution order"])
        self.assertEqual(ft._shared_errors([dict(item, specs=["a", "z"], order=[])], position),
                         ["unknown-shared-spec: x.py: z"])
        self.assertEqual(ft._shared_errors([dict(item, order=["a", "b"])], position), [])


class RoadmapRenderHelpersTest(unittest.TestCase):
    def test_refs_nodes_cells(self):
        refs = ft._spec_refs(["g-1-spec.md", "g-2-spec.md", "h-2-spec.md", "x-spec.md"])
        self.assertEqual(refs, {"g-1-spec.md": "1", "g-2-spec.md": "g-2-spec.md", "h-2-spec.md": "h-2-spec.md",
                                "x-spec.md": "x-spec.md"})
        self.assertEqual((ft._node_id("3", 1), ft._node_id("x-spec.md", 4)), ("s3", "n4"))
        self.assertEqual((ft._cell("a |\n b"), ft._cell(None), ft._one_line("  ")), ("a \\| b", "—", "—"))

    def test_fence_and_goal_phrase(self):
        self.assertEqual(ft._fence("a ``` b", "text"), "````text\na ``` b\n````")
        self.assertEqual(ft._fence("x", "mermaid"), "```mermaid\nx\n```")
        self.assertEqual(ft._spec_goal_phrase(_goal_spec("Первая фраза. Вторая.")), "Первая фраза.")
        self.assertEqual(ft._spec_goal_phrase("# Goal\n\n## Architecture\n"), "?")


class RoadmapRenderTest(unittest.TestCase):
    def render(self, graph, lang="ru"):
        graph = ft._roadmap_graph(graph)
        order = ft._roadmap_order(graph["specs"])[0]
        facts = {name: {"goal": f"Цель {name[2]}.", "tier": "Deep", "estimate": "~4"} for name in order}
        return ft._render_roadmap(lang, "g", graph, order, facts)

    def test_full_roadmap(self):
        text = self.render(_graph())
        self.assertTrue(text.startswith("> Goal: g\n> Specs: 3\n> Generated: "))
        self.assertIn("# Roadmap: Цель G\n\n## Overview\n\nТри спеки.\n", text)
        self.assertIn("| 2 | g-2-spec.md | Вторая \\| с чертой | — | A | Deep | ~4 |", text)
        self.assertIn("| 3 | g-3-spec.md | Третья | 2, 1 | B | Deep | ~4 |", text)
        self.assertIn('    subgraph g_A["A"]\n        s1["1. Первая"]\n        s2["2. Вторая | с чертой"]\n    end', text)
        self.assertIn("    s2 --> s3\n    s1 --> s3\n```", text)
        self.assertIn("- A: 1, 2 — можно вести одновременно\n- B: 3 — одна спека", text)
        self.assertIn("| `run_status` | 1, 3 | 1 → 3 | 3 сохраняет поле |", text)
        self.assertIn("### 1. g-1-spec.md\n\n- Цель: Цель 1.\n- Зависит от: —\n- Примечания: раньше всех\n"
                      "- Передаёт: парсер", text)
        self.assertIn("- `goal.md` — постановка\n\nИнструкция:\n\n```text\nresearch — справочно\n```", text)
        for heading in ft.ROADMAP_HEADINGS:
            self.assertIn("\n" + heading + "\n", text)

    def test_english_one_spec_without_shared_and_sources(self):
        text = self.render(_graph(specs=[_graph()["specs"][0]], shared=[], sources=[], instruction=None), "en")
        self.assertIn("- A: 1 — one spec", text)
        self.assertIn("## Shared touchpoints\n\nnone\n", text)
        self.assertIn("## Sources\n\n—\n\nInstruction: —\n", text)
        self.assertIn('graph LR\n    subgraph g_A["A"]\n        s1["1. Первая"]\n    end\n```', text)
        self.assertIn("## Shared touchpoints\n\nнет\n", self.render(_graph(shared=[])))

    def test_shared_name_with_a_bar_and_a_backtick(self):  # F17 of plan-refactoring-02
        shared = [{"name": "a | b`c", "specs": ["g-1-spec.md", "g-3-spec.md"], "order": ["g-1-spec.md", "g-3-spec.md"],
                   "note": "x"}]
        self.assertIn("| `` a \\| b`c `` | 1, 3 | 1 → 3 | x |", self.render(_graph(shared=shared)))
        self.assertIn("| `run_status` | 1, 3 | 1 → 3 | 3 сохраняет поле |", self.render(_graph()))


class SpecFactsTest(GoalDirCase):
    def test_facts(self):
        self.specs([(1, _goal_spec("Первая цель. Ещё.", tier="Deep")), (2, "# Goal\n\nbroken\n")], journal=False)
        one, two = (os.path.join(self.dir, f"g-{n}-spec.md") for n in (1, 2))
        warnings = []
        facts = ft._spec_facts(one, "g-1-spec.md", warnings)
        self.assertEqual((facts["tier"], facts["estimate"], facts["goal"]), ("Deep", "~4", "Первая цель."))
        self.assertEqual({k: v for k, v in ft._spec_facts(two, "g-2-spec.md", warnings).items() if k != "text"},
                         {"goal": "broken", "tier": "?", "estimate": "?"})
        real = ft.check_spec
        with mock.patch.object(ft, "check_spec", lambda text: {k: v for k, v in real(text).items() if k != "volume"}):
            self.assertEqual(ft._spec_facts(one, "g-1-spec.md", warnings)["estimate"], "—")
        self.assertEqual(warnings, ["spec-check-failed: g-2-spec.md", "no-volume: g-1-spec.md"])

    def test_own_roadmap(self):
        own = _put(self.dir, "g-roadmap.md", "> Goal: g\n")
        foreign = _put(self.dir, "x-roadmap.md", "# x\n")
        binary = _put(self.dir, "y-roadmap.md", "Привет", encoding="cp1251")
        self.assertEqual([ft._is_own_roadmap(path) for path in (own, foreign, binary)], [True, False, False])


class RoadmapCase(GoalDirCase):
    def setUp(self):
        super().setUp()
        self.specs([(1, _goal_spec("Первая цель. Вторая фраза.", tier="Deep")), (2, _goal_spec()), (3, _goal_spec())])
        self.roadmap = os.path.join(self.dir, "g-roadmap.md")

    def write(self, graph, lang=None, force=False):
        path = _put(self.dir, "graph.json", json.dumps(graph, ensure_ascii=False))
        return ft.roadmap_write(self.dir, path, lang, force)

    def text(self):
        with open(self.roadmap, encoding="utf-8") as fh:
            return fh.read()


class RoadmapWriteTest(RoadmapCase):
    def test_writes_the_roadmap(self):
        code, out = self.write(_graph())
        self.assertEqual((code, out["order"], out["warnings"], out["lang"], out["journal"]),
                         (0, ["g-1-spec.md", "g-2-spec.md", "g-3-spec.md"], [], "ru", self.journal))
        self.assertTrue(self.text().startswith("> Goal: g\n> Specs: 3\n"))
        self.assertIn("| 1 | g-1-spec.md | Первая | — | A | Deep | ~4 |", self.text())
        self.assertIn("- Цель: Первая цель.\n", self.text())

    def test_rewrites_its_own_roadmap_and_refuses_a_foreign_file(self):
        self.assertEqual(self.write(_graph())[0], 0)
        self.assertEqual(self.write(_graph(title="Новое имя"))[0], 0)
        self.assertIn("# Roadmap: Новое имя", self.text())
        _put(self.dir, "g-roadmap.md", "# Someone else's roadmap\n")
        code, out = self.write(_graph())
        self.assertEqual((code, out["errors"]),
                         (1, [f"exists-foreign: {self.roadmap} has no '> Goal:' line; --force overwrites it"]))
        self.assertEqual(self.text(), "# Someone else's roadmap\n")
        self.assertEqual(self.write(_graph(), force=True)[0], 0)

    def test_without_journal_in_english(self):
        os.remove(self.journal)
        code, out = self.write(_graph(goal="g", specs=[_graph()["specs"][0]], shared=[]), lang="en")
        self.assertEqual((code, out["warnings"], out["lang"]), (0, ["no-journal"], "en"))
        self.assertIn("- Goal: Первая цель.\n", self.text())
        with self.assertRaisesRegex(ft.InputError, "graph-invalid: goal is required"):
            self.write(_graph())


class RoadmapWriteErrorsTest(RoadmapCase):
    def test_every_error_leaves_the_file_untouched(self):
        specs = _graph()["specs"]

        def first(**change):
            return [dict(s, **change) if s["file"] == "g-1-spec.md" else s for s in specs]

        bad = [
            (_graph(specs=specs[:2], shared=[]), "specs-missing: g-3-spec.md"),
            (_graph(specs=specs + [{"file": "g-9-spec.md", "title": "X", "group": "C"}]), "spec-not-found: g-9-spec.md"),
            (_graph(specs=first(depends=["g-7-spec.md"])), "unknown-dependency: g-1-spec.md -> g-7-spec.md"),
            (_graph(specs=first(depends=["g-3-spec.md"])), "dependency-cycle: g-1-spec.md -> g-3-spec.md -> g-1-spec.md"),
            (_graph(specs=[dict(s, group="A") for s in specs]),
             "group-conflict: g-3-spec.md and its dependency g-2-spec.md are both in group A"),
            (_graph(shared=[{"name": "x.py", "specs": ["g-1-spec.md", "g-8-spec.md"]}]), "unknown-shared-spec: x.py: g-8-spec.md"),
            (_graph(shared=[{"name": "x.py", "specs": ["g-1-spec.md", "g-3-spec.md"], "order": ["g-3-spec.md", "g-1-spec.md"]}]),
             "shared-order-conflict: x.py: g-3-spec.md → g-1-spec.md goes against the execution order"),
            (_graph(goal="other"), "goal-mismatch: the journal's goal is g, the JSON says other"),
        ]
        for graph, error in bad:
            code, out = self.write(graph)
            self.assertEqual(code, 1, error)
            self.assertIn(error, out["errors"])
            self.assertFalse(os.path.exists(self.roadmap), error)

    def test_failing_spec_check_does_not_block(self):
        _put(self.dir, "g-2-spec.md", "# Goal\n\nbroken\n")
        code, out = self.write(_graph())
        self.assertEqual((code, out["warnings"]), (0, ["spec-check-failed: g-2-spec.md"]))
        self.assertIn("| 2 | g-2-spec.md | Вторая \\| с чертой | — | A | ? | ? |", self.text())

    def test_cli(self):
        path = _put(self.dir, "graph.json", json.dumps(_graph(), ensure_ascii=False))
        code, out = _run("roadmap-write", self.dir, "--graph", path, "--lang", "en")
        self.assertEqual((code, out["lang"]), (0, "en"))
        self.assertEqual(_run("roadmap-write", self.dir, "--graph", os.path.join(self.dir, "nope.json"))[0], 2)
        _put(self.dir, "bad.json", "{not json")
        code, out = _run("roadmap-write", self.dir, "--graph", os.path.join(self.dir, "bad.json"))
        self.assertEqual(code, 2)
        self.assertTrue(out["errors"][0].startswith("graph-invalid: "))


class RoadmapGroupsTest(RoadmapCase):
    def test_group_names_that_are_mermaid_words_or_node_ids(self):  # F18 of plan-refactoring-02
        specs = [dict(spec, group=group) for spec, group in zip(_graph()["specs"], ("end", "end", "s2"))]
        self.assertEqual(self.write(_graph(specs=specs))[0], 0)
        self.assertIn('    subgraph g_end["end"]\n', self.text())
        self.assertIn('    subgraph g_s2["s2"]\n', self.text())
        self.assertEqual(ft.roadmap_check(self.roadmap)[0]["errors"], [])
        _put(self.dir, "g-roadmap.md", self.text().replace('subgraph g_end["end"]', "subgraph end"))
        self.assertEqual(ft.roadmap_check(self.roadmap)[0]["errors"], [])  # the older form is accepted


class RoadmapBlocksTest(unittest.TestCase):
    def test_blocks_sections_and_tables(self):
        text = ("> Goal: g\n\n# Roadmap: T\n\n## Order\n\n| a | b \\| c |\n|---|---|\n| 1 | 2 |\n\n## Graph\n\n"
                "````mermaid\n## not a heading\n```\n````\n\n## Notes\n\n—\n")
        head, names, sections = ft._roadmap_sections(text)
        self.assertEqual((names, head[-2:]), (["## Order", "## Graph", "## Notes"], ["# Roadmap: T", ""]))
        self.assertEqual(ft._table_rows(sections["## Order"]), [["a", "b | c"], ["1", "2"]])
        self.assertEqual([block for block in sections["## Graph"] if block[0] is not None],
                         [("mermaid", ["## not a heading", "```"])])
        self.assertIsNone(ft._section_text(sections["## Notes"]))
        self.assertEqual(ft._section_text(sections["## Order"]).splitlines()[0], "| a | b \\| c |")


ORDER_HEADER = "| # | Spec | Title | Depends on | Group | Tier | Estimate |\n|---|---|---|---|---|---|---|\n"


def _order_blocks(rows):
    return ft._roadmap_sections("## Order\n\n" + ORDER_HEADER + rows)[2]["## Order"]


class RoadmapParseOrderTest(unittest.TestCase):
    def test_rows(self):
        errors, warnings = [], []
        rows = "| 1 | g-1-spec.md | A \\| B | — | A | Deep | ~4 |\n| 2 | g-2-spec.md | C | 1 | B | ? | |\n"
        specs = ft._parse_order(_order_blocks(rows), errors, warnings)
        self.assertEqual((errors, warnings), ([], ["no-estimate: g-2-spec.md"]))
        self.assertEqual([(s["n"], s["title"], s["depends"], s["tier"], s["estimate"]) for s in specs],
                         [(1, "A | B", "—", "Deep", 4), (2, "C", "1", None, None)])

    def test_errors(self):
        errors = []
        ft._parse_order(ft._roadmap_sections("## Order\n\n| # | Spec |\n|---|---|\n")[2]["## Order"], errors, [])
        self.assertTrue(errors[0].startswith("order-table: the header must be | # | Spec |"))
        errors = []
        ft._parse_order(_order_blocks("| 2 | g-1-spec.md | A | — | A | Deep | ~4 |\n| 3 | x |\n"), errors, [])
        self.assertEqual(errors, ["order-row: 3 | x", "order-numbering: # must run 1, 2, … in table order"])

    def test_only_ascii_digits_number_a_row(self):  # F19 of plan-refactoring-02
        errors = []
        specs = ft._parse_order(_order_blocks("| ¹ | g-1-spec.md | A | — | A | Deep | ~4 |\n"), errors, [])
        self.assertEqual(([s["n"] for s in specs], errors), ([None], ["order-numbering: # must run 1, 2, … in table order"]))


class OrderGraphErrorsTest(unittest.TestCase):
    ROWS = "| 1 | g-1-spec.md | A | — | A | Deep | ~4 |\n| 2 | g-2-spec.md | B | 1 | B | Deep | ~4 |\n"
    GRAPH = '## Graph\n\n```mermaid\ngraph LR\n    s1["1. A"]\n    s2["2. B"]\n    s1 --> s2\n```\n'

    def errors(self, rows=ROWS, graph=GRAPH):
        specs = ft._parse_order(_order_blocks(rows), [], [])
        errors = ft._order_graph_errors(specs, ft._roadmap_sections(graph)[2]["## Graph"])
        return specs, errors

    def test_valid_graph_resolves_depends(self):
        specs, errors = self.errors()
        self.assertEqual((errors, specs[1]["depends"]), ([], ["g-1-spec.md"]))

    def test_table_errors(self):
        self.assertEqual(self.errors(self.ROWS.replace("| B | 1 |", "| B | 7 |"))[1][0], "unknown-dependency: g-2-spec.md -> 7")
        rows = self.ROWS.replace("| A | — | A |", "| A | 2 | A |").replace("| B | 1 | B |", "| B | — | B |")
        self.assertIn("order-violation: g-1-spec.md (#1) depends on g-2-spec.md (#2)", self.errors(rows)[1])
        self.assertIn("group-conflict: g-2-spec.md and its dependency g-1-spec.md are both in group A",
                      self.errors(self.ROWS.replace("| 1 | B |", "| 1 | A |"))[1])

    def test_mermaid_errors(self):
        self.assertEqual(self.errors(graph="## Graph\n\nnone\n")[1], ["graph-missing: no mermaid block in ## Graph"])
        self.assertEqual(self.errors(graph=self.GRAPH.replace("    s1 --> s2\n", "    s2 --> s1\n"))[1],
                         ["graph-edge-without-row: s2 --> s1", "row-edge-missing-in-graph: s1 --> s2"])
        self.assertEqual(self.errors(graph=self.GRAPH.replace('    s2["2. B"]\n', '    s9["9. X"]\n'))[1],
                         ["graph-node-missing: s2 (g-2-spec.md)", "graph-node-unknown: s9"])
        self.assertEqual(self.errors(graph=self.GRAPH.replace("graph LR", "graph TD"))[1],
                         ["graph-not-lr: the mermaid block must start with 'graph LR'"])


class ParseSharedTest(unittest.TestCase):
    FILES = ["g-1-spec.md", "g-2-spec.md", "g-3-spec.md"]

    def parse(self, body):
        errors = []
        shared = ft._parse_shared(ft._roadmap_sections("## Shared touchpoints\n\n" + body)[2]["## Shared touchpoints"],
                                  self.FILES, errors)
        return shared, errors

    def test_rows_and_none(self):
        body = ("| File or symbol | Specs | Delivery order | Note |\n|---|---|---|---|\n"
                "| `skills/x.py` | 1, 3 | 1 → 3 | note |\n| `run_status` | 2, 3 | — | — |\n")
        self.assertEqual(self.parse(body), ([
            {"name": "skills/x.py", "kind": "path", "specs": ["g-1-spec.md", "g-3-spec.md"],
             "order": ["g-1-spec.md", "g-3-spec.md"], "note": "note"},
            {"name": "run_status", "kind": "symbol", "specs": ["g-2-spec.md", "g-3-spec.md"], "order": [], "note": None}], []))
        self.assertEqual(self.parse("нет\n"), ([], []))

    def test_code_span_names(self):  # F17 of plan-refactoring-02
        body = ("| File or symbol | Specs | Delivery order | Note |\n|---|---|---|---|\n"
                "| `` a \\| b`c `` | 1, 3 | 1 → 3 | x |\n")
        self.assertEqual(self.parse(body)[0][0]["name"], "a | b`c")
        self.assertEqual([ft._code_span_text(cell) for cell in ("`x`", "`` ` ``", "plain")], ["x", "`", "plain"])

    def test_errors(self):
        head = "| File or symbol | Specs | Delivery order | Note |\n|---|---|---|---|\n"
        self.assertEqual(self.parse(head + "| `a.py` | 1, 5 | — | x |\n")[1], ["unknown-shared-spec: a.py: 5"])
        self.assertEqual(self.parse(head + "| `a.py` | 1, 3 | 3 → 1 | x |\n")[1],
                         ["shared-order-conflict: a.py: g-3-spec.md → g-1-spec.md goes against the execution order"])
        self.assertTrue(self.parse("| File | Specs |\n|---|---|\n| a | 1 |\n")[1][0].startswith("shared-table: "))


class ParseSpecSectionsSourcesTest(unittest.TestCase):
    def test_spec_sections(self):
        text = ("## Specs\n\n### 1. g-1-spec.md\n\n- Цель: X.\n- Зависит от: —\n- Примечания: после 3\n- Передаёт: —\n\n"
                "### 2. g-2-spec.md\n\n- Goal: Y.\n- Notes: —\n- Hands off: the parser\n")
        specs = [{"file": "g-1-spec.md"}, {"file": "g-2-spec.md"}, {"file": "g-3-spec.md"}]
        errors = []
        ft._parse_spec_sections(ft._roadmap_sections(text)[2]["## Specs"], specs, errors)
        self.assertEqual([(s.get("notes"), s.get("handoff")) for s in specs],
                         [("после 3", None), (None, "the parser"), (None, None)])
        self.assertEqual(errors, ["spec-section-missing: g-3-spec.md"])

    def test_sources(self):
        text = "## Sources\n\n- `goal.md` — постановка\n- `r.md` — справочно\n\nИнструкция:\n\n````text\nкак ``` есть\n````\n"
        self.assertEqual(ft._parse_sources(ft._roadmap_sections(text)[2]["## Sources"]),
                         ([{"path": "goal.md", "role": "постановка"}, {"path": "r.md", "role": "справочно"}], "как ``` есть"))
        self.assertEqual(ft._parse_sources(ft._roadmap_sections("## Sources\n\n—\n\nInstruction: —\n")[2]["## Sources"]),
                         ([], None))


class RoadmapCheckParseTest(RoadmapCase):
    def setUp(self):
        super().setUp()
        self.assertEqual(self.write(_graph())[0], 0)

    def corrupt(self, old, new):
        text = self.text()
        self.assertIn(old, text)
        _put(self.dir, "g-roadmap.md", text.replace(old, new))
        return ft.roadmap_check(self.roadmap)[0]

    def test_written_roadmap_is_valid_and_parses_back(self):
        result, parsed = ft.roadmap_check(self.roadmap)
        self.assertEqual((result["valid"], result["errors"], result["warnings"]), (True, [], []))
        graph = _graph()
        self.assertEqual((parsed["goal"], parsed["title"], parsed["instruction"], parsed["sources"]),
                         ("g", graph["title"], graph["instruction"], graph["sources"]))
        self.assertEqual([(s["n"], s["file"], s["title"], s["depends"], s["group"], s["tier"], s["estimate"])
                          for s in parsed["specs"]],
                         [(1, "g-1-spec.md", "Первая", [], "A", "Deep", 4),
                          (2, "g-2-spec.md", "Вторая | с чертой", [], "A", "Standard", 3),
                          (3, "g-3-spec.md", "Третья", ["g-2-spec.md", "g-1-spec.md"], "B", "Standard", 3)])
        self.assertEqual((parsed["specs"][0]["notes"], parsed["specs"][0]["handoff"], parsed["specs"][1]["notes"]),
                         ("раньше всех", "парсер", None))
        self.assertEqual(parsed["groups"], {"A": ["g-1-spec.md", "g-2-spec.md"], "B": ["g-3-spec.md"]})
        self.assertEqual(parsed["shared"], [dict(graph["shared"][0], kind="symbol")])
        self.assertEqual((parsed["overview"], parsed["notes"]), ("Три спеки.", None))

    def test_broken_roadmaps(self):
        cases = [
            ("    s2 --> s3\n", "    s2 --> s3\n    s2 --> s1\n", "graph-edge-without-row: s2 --> s1"),
            ("| 1 | g-1-spec.md | Первая | — |", "| 1 | g-1-spec.md | Первая | 3 |", "dependency-cycle: "),
            ("| 1 | g-1-spec.md |", "| 1 | g-7-spec.md |", "spec-not-found: g-7-spec.md"),
            ("| `run_status` | 1, 3 | 1 → 3 |", "| `run_status` | 1, 5 | 1 → 3 |", "unknown-shared-spec: run_status: 5"),
            ("> Specs: 3", "> Specs: 4", "specs-count: '> Specs:' says 4"),
            ("## Parallelism", "## Parallel", "missing-section: ## Parallelism"),
            ("> Goal: g\n", "", "no-goal-line"),
        ]
        for old, new, error in cases:
            result = self.corrupt(old, new)
            self.assertFalse(result["valid"], error)
            self.assertTrue(any(e.startswith(error) for e in result["errors"]), (error, result["errors"]))
            self.assertEqual(self.write(_graph(), force=True)[0], 0)

    def test_estimate_marks(self):
        self.assertEqual(self.corrupt("| Deep | ~4 |", "| Deep | — |")["warnings"], [])
        self.assertEqual(self.corrupt("| Deep | — |", "| Deep |  |")["warnings"], ["no-estimate: g-1-spec.md"])


class RoadmapCliTest(RoadmapCase):
    def test_check_and_parse(self):
        self.assertEqual(self.write(_graph())[0], 0)
        code, out = _run("roadmap-check", self.roadmap)
        self.assertEqual((code, out["valid"], out["errors"]), (0, True, []))
        code, out = _run("roadmap-parse", self.roadmap)
        self.assertEqual((code, out["ok"], out["goal"], [s["n"] for s in out["specs"]]), (0, True, "g", [1, 2, 3]))
        self.assertEqual(out["specs"][2]["depends"], ["g-2-spec.md", "g-1-spec.md"])
        _put(self.dir, "g-roadmap.md", self.text().replace("    s1 --> s3\n", ""))
        code, out = _run("roadmap-check", self.roadmap)
        self.assertEqual((code, out["valid"], out["errors"]), (1, False, ["row-edge-missing-in-graph: s1 --> s3"]))
        code, out = _run("roadmap-parse", self.roadmap)
        self.assertEqual((code, out["ok"], out["errors"]), (1, False, ["row-edge-missing-in-graph: s1 --> s3"]))
        self.assertEqual(_run("roadmap-parse", os.path.join(self.dir, "nope.md"))[0], 2)

    def test_missing_volume_is_accepted(self):
        real = ft.check_spec
        with mock.patch.object(ft, "check_spec", lambda text: {k: v for k, v in real(text).items() if k != "volume"}):
            code, out = self.write(_graph())
        self.assertEqual(out["warnings"], ["no-volume: g-1-spec.md", "no-volume: g-2-spec.md", "no-volume: g-3-spec.md"])
        self.assertIn("| 1 | g-1-spec.md | Первая | — | A | Deep | — |", self.text())
        self.assertEqual(ft.roadmap_check(self.roadmap)[0]["warnings"], [])


def _marks_runner(**changes):
    """A valid runner section with one host-error record and one writing-resume record; `changes` replace keys."""
    host = {"plan": "a-impl", "stage": "writing", "at": "2026-10-05T10:00:00Z", "error": "API Error: 529 overloaded",
            "attempt": 1, "wait_seconds": 60, "wait_until": "2026-10-05T10:01:00Z", "waited_total": 60, "at_event": 3}
    resume = {"plan": "a-impl", "tasks": 4, "bytes": 900, "sha256": "a" * 64, "at_event": 5}
    runner = {"version": 1, "profile": "claude-code", "specs": [], "graph": {}, "models": {}, "sessions": [],
              "host_errors": [host], "writing_resumes": [resume]}
    runner.update(changes)
    return runner, host, resume


class RunnerMarksTest(unittest.TestCase):
    """Spec plan-refactoring-03: runner.host_errors and runner.writing_resumes are optional and checked."""

    def test_valid_marks_and_absent_lists(self):
        runner, host, _ = _marks_runner()
        self.assertEqual(ft._runner_errors(runner), [])
        exhausted = dict(host, wait_seconds=0,
                         exhausted_for={"plan": "a-impl", "stage": "writing", "attempt": 1, "event": 2})
        self.assertEqual(ft._runner_errors(_marks_runner(host_errors=[exhausted])[0]), [])
        bare = {key: value for key, value in runner.items() if key not in ("host_errors", "writing_resumes")}
        self.assertEqual(ft._runner_errors(bare), [])

    def test_each_rule(self):
        _, host, resume = _marks_runner()
        cases = [
            ({"host_errors": {}}, "runner: 'host_errors' must be a list"),
            ({"writing_resumes": ["x"]}, "runner: writing_resumes[0]: must be an object"),
            ({"host_errors": [dict(host, at="2026-10-05 10:00")]}, "runner: host_errors[0]: 'at' missing or invalid"),
            ({"host_errors": [dict(host, stage="build")]}, "runner: host_errors[0]: 'stage' missing or invalid"),
            ({"host_errors": [dict(host, attempt=0)]}, "runner: host_errors[0]: 'attempt' missing or invalid"),
            ({"host_errors": [{k: v for k, v in host.items() if k != "wait_until"}]},
             "runner: host_errors[0]: 'wait_until' missing or invalid"),
            ({"host_errors": [dict(host, exhausted_for={"plan": "a-impl"})]},
             "runner: host_errors[0]: 'exhausted_for' invalid"),
            ({"writing_resumes": [dict(resume, sha256="abc")]}, "runner: writing_resumes[0]: 'sha256' missing or invalid"),
            ({"writing_resumes": [dict(resume, tasks=True)]}, "runner: writing_resumes[0]: 'tasks' missing or invalid"),
        ]
        for change, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(ft._runner_errors(_marks_runner(**change)[0]), [expected])


class RunnerMarksSchemaTest(unittest.TestCase):
    def test_schema_names_the_record_keys(self):
        path = os.path.join(SCRIPTS, "..", "assets", "chain-journal.schema.json")
        with open(path, encoding="utf-8") as fh:
            props = json.load(fh)["definitions"]["runner"]["properties"]
        host = props["host_errors"]["items"]
        self.assertEqual(tuple(host["required"]), ft.RUNNER_HOST_ERROR_KEYS)
        self.assertEqual(tuple(host["properties"]["exhausted_for"]["required"]), ft.RUNNER_EXHAUSTED_KEYS)
        self.assertEqual(tuple(host["properties"]["stage"]["enum"]), ft.STAGES)
        self.assertEqual(tuple(props["writing_resumes"]["items"]["required"]), ft.RUNNER_WRITING_RESUME_KEYS)


ACTION_LINES_PLAN = "\n".join([
    "### Task 1: Action lines",
    "",
    "**Files:**",
    "- Modify: `a/cli.py:4-6` (сейчас: `executor_tool.py` / `-roadmap.md` / `parts.json`)",
    "- Create: `<base>-diffs.md` (шаблон, затем `b/real.py`)",
    "- Move: `old/x.py` → `new/x.py` (и `y.py`)",
    "- Test: [test_cli.py](tests/test_cli.py) и `other.py`",
    "- `notes.txt` и `<X>-diffs.md`",
    "",
    "- [ ] **Step 1: Do it**",
    "",
])
ACTION_LINES_FILES = [
    {"path": "a/cli.py", "action": "modify", "lines": "4-6"},
    {"path": "old/x.py", "action": "move", "lines": None},
    {"path": "new/x.py", "action": "move", "lines": None},
    {"path": "test_cli.py", "action": "test", "lines": None},
    {"path": "notes.txt", "action": None, "lines": None},
    {"path": "<X>-diffs.md", "action": None, "lines": None},
]


class PlanTaskActionLinesTest(unittest.TestCase):
    """Spec 1 of plan-refactoring-04: an action line gives its first name (two for Move:), never a placeholder;
    a line without an action gives every name, as before."""

    def test_action_lines(self):
        self.assertEqual(ft.parse_plan_tasks(ACTION_LINES_PLAN)["tasks"][0]["files"], ACTION_LINES_FILES)


if __name__ == "__main__":
    unittest.main()
