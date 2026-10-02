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


if __name__ == "__main__":
    unittest.main()
