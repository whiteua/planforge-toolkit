"""Tests for plan_tool.py.

Uses unittest (stdlib) so no external dependencies are needed.
Run: python -m pytest skills/plan-writing/tests -q
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest


HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.abspath(os.path.join(HERE, "..", "scripts", "plan_tool.py"))
FIXTURE = os.path.join(HERE, "fixtures", "plan01-impl.md")
EXECUTOR = os.path.abspath(os.path.join(HERE, "..", "..", "plan-executor", "scripts", "executor_tool.py"))
RESOLVER = os.path.abspath(os.path.join(HERE, "..", "..", "plan-resolver", "scripts", "resolver_tool.py"))
BRAINSTORM = os.path.abspath(os.path.join(HERE, "..", "..", "plan-brainstorming", "scripts", "brainstorm_tool.py"))
SETTINGS_SPEC = os.path.join(HERE, "fixtures", "settings01-spec.md")
SETTINGS_PLAN = os.path.join(HERE, "fixtures", "settings01-impl.md")


def _load_module():
    spec = importlib.util.spec_from_file_location("plan_tool", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pt = _load_module()

with open(FIXTURE, encoding="utf-8") as _fh:
    VALID = _fh.read()


def _run(tool, *args):
    # Sibling tools may print with the console code page; force UTF-8 for the comparison.
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    proc = subprocess.run([sys.executable, tool, *args], capture_output=True, encoding="utf-8", env=env)
    return proc.returncode, (json.loads(proc.stdout) if proc.stdout.strip() else None)


class PlanPathTest(unittest.TestCase):
    def test_derivation(self):
        cases = {
            "docs/plan01-spec.md": ("plan01", "docs/plan01-impl.md"),
            "docs/review01-conn-spec.md": ("review01-conn", "docs/review01-conn-impl.md"),
            "docs/spec.md": ("", "docs/impl.md"),
            "docs/auth.md": ("auth", "docs/auth-impl.md"),
        }
        for spec_path, (root, impl) in cases.items():
            result = pt.plan_path(spec_path)
            self.assertEqual((result["plan_root"], result["impl_path"]), (root, impl), spec_path)

    def test_cli(self):
        code, out = _run(TOOL, "plan-path", "a/plan02-spec.md")
        self.assertEqual(code, 0)
        self.assertEqual(out["impl_path"], "a/plan02-impl.md")


class PlanCheckTest(unittest.TestCase):
    def check(self, text, root=None):
        return pt.check_plan(text, root)

    def assertError(self, text, fragment):
        result = self.check(text)
        self.assertFalse(result["ok"])
        self.assertTrue(any(fragment in e for e in result["errors"]), result["errors"])

    def test_valid_fixture(self):
        result = self.check(VALID)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["warnings"], [])
        self.assertEqual([t["id"] for t in result["tasks"]], ["1", "1.1", "2"])
        self.assertEqual([t["checkpoint"] for t in result["tasks"]], [False, False, True])
        self.assertEqual((result["spec"], result["tier"]), ("plan01-spec.md", "Standard"))

    def test_header_fields_required(self):
        self.assertError(VALID.replace("**Spec:** plan01-spec.md\n", ""), "**Spec:**")
        self.assertError(VALID.replace("**Tier:** Standard", "**Tier:** Huge"), "unknown tier")

    def test_duplicate_and_malformed_ids(self):
        self.assertError(VALID.replace("### Task 1.1:", "### Task 1:"), "duplicate task id 1")
        self.assertError(VALID.replace("### Task 1.1:", "### Task A:"), "must be N or N.M")
        self.assertError(VALID.replace("### Task 1.1: Document", "### Task 1.1 Document"), "malformed task heading")

    def test_old_phase_checkpoint_rejected(self):
        self.assertError(VALID.replace("### Task 2: Checkpoint", "### Phase Checkpoint"), "Phase Checkpoint")

    def test_task_core(self):
        self.assertError(VALID.replace("**Files:**\n- Modify: `README.md`\n", ""), "Task 1.1: missing '**Files:**'")
        self.assertError(VALID.replace("- [ ] **Step 1: Add the example**", "Add the example"), "Task 1.1: no steps")
        self.assertError(VALID.replace("**Preconditions:**\n- Task 1 is done.\n", ""), "Task 1.1: missing '**Preconditions:**'")
        self.assertError(VALID.replace("**Done when:** both lines appear as expected.", ""), "Task 2: missing done-state")

    def test_quick_tier(self):
        quick = VALID.replace("**Tier:** Standard", "**Tier:** Quick")
        self.assertError(quick, "not used on the Quick tier")
        quick = quick.split("### Task 2: Checkpoint")[0]
        for block in ("**Preconditions:**\n- `cli.py` prints the line count for one positional `path`.\n",
                      "**Preconditions:**\n- Task 1 is done.\n"):
            quick = quick.replace(block, "")
        quick = quick.replace(
            "**Postconditions:**\n- `python cli.py f --verbose` prints `f` on the first line and the count on the second.\n"
            "- Output without `--verbose` is unchanged.\n",
            "**Done when:** `python cli.py f --verbose` prints `f`, then the count.\n",
        ).replace("**Postconditions:**\n- README shows one `--verbose` example.\n", "**Done when:** README shows the example.\n")
        self.assertEqual(self.check(quick)["errors"], [])

    def test_commit_mentioned_in_prose_is_fine(self):
        text = VALID.replace("Expected: PASS\n", "Expected: PASS\n\n**Constraints:**\n- Do not run git commit; the engineer commits.\n", 1)
        self.assertEqual(self.check(text)["errors"], [])

    def test_commit_in_step_line_rejected(self):
        text = VALID.replace("Expected: PASS\n", "Expected: PASS\n- [ ] **Step 9:** git commit -m done\n", 1)
        self.assertError(text, "commit step")

    def test_commit_step_rejected(self):
        text = VALID.replace("Expected: PASS\n", "Expected: PASS\n\n```bash\ngit commit -m \"feat: x\"\n```\n", 1)
        self.assertError(text, "commit step")

    def test_placeholders_outside_fences_only(self):
        self.assertError(VALID.replace("Output without", "TBD: output without"), "placeholder")
        self.assertError(VALID.replace("Add the example", "Similar to Task 1"), "placeholder")
        fenced = VALID.replace('p.add_argument("--verbose", action="store_true")', "# TODO in code is fine")
        self.assertTrue(self.check(fenced)["ok"])

    def test_file_paths_must_be_backticked(self):
        self.assertError(VALID.replace("- Modify: `README.md`", "- Modify: README.md"), "must be in backticks")

    def test_root_checks_modify_targets(self):
        with tempfile.TemporaryDirectory() as root:
            with open(os.path.join(root, "cli.py"), "w", encoding="utf-8") as fh:
                fh.write("a\nb\nc\n")
            result = self.check(VALID, root)
        self.assertTrue(result["ok"])
        self.assertTrue(any("beyond end of cli.py" in w for w in result["warnings"]), result["warnings"])
        self.assertTrue(any("Modify target not found under root: README.md" in w for w in result["warnings"]), result["warnings"])

    def test_root_checks_create_test_and_referenced_paths(self):
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            for name in ("README.md", "cli.py"):
                with open(os.path.join(root, name), "w", encoding="utf-8") as fh:
                    fh.write("x\n" * 5)
            text = VALID.replace("- Modify: `README.md`\n", "- Create: `README.md`\n- Test: `tests/test_new.py`\n", 1)
            text = text.replace("- [ ] **Step 1: Add the example**", "- [ ] **Step 1: Add the example** (see `docs/missing/notes.md`)", 1)
            warnings = self.check(text, root)["warnings"]
            self.assertTrue(any("Create target already exists" in w for w in warnings), warnings)
            self.assertTrue(any("Test target not found" in w for w in warnings), warnings)
            self.assertTrue(any("referenced path not found under root: docs/missing/notes.md" in w for w in warnings), warnings)
            # A file created earlier in the plan is not reported as missing later.
            text = VALID.replace("- Modify: `README.md`\n", "- Create: `docs/new.md`\n- Test: `docs/new.md`\n", 1)
            warnings = self.check(text, root)["warnings"]
            self.assertFalse(any("docs/new.md" in w for w in warnings), warnings)

    def test_environments_and_external(self):
        env_block = (
            '**Environments:**\n'
            '- `dev_db` (test) — "this database is made for tests" (user, 2026-09-30)\n\n'
        )
        with_env = VALID.replace("**Tier:** Standard\n", "**Tier:** Standard\n\n" + env_block, 1)
        self.assertEqual(self.check(with_env)["errors"], [])
        self.assertEqual(self.check(with_env)["environments"], ["dev_db"])

        # a task that runs something on the environment must declare it
        uses = with_env.replace("Expected: PASS\n", "Expected: PASS\n\nRun: `npx env-cmd -e dev_db -- node dist/smoke.js`\n", 1)
        self.assertError(uses, "uses environment `dev_db` without a '**External:**")
        declared = uses.replace("**Preconditions:**", "**External:** `dev_db` — smoke test\n\n**Preconditions:**", 1)
        result = self.check(declared)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["tasks"][0]["external"], ["dev_db"])

        # an environment nobody permitted, and an entry without the user's words
        self.assertError(declared.replace("**External:** `dev_db`", "**External:** `prod_db`"), "`prod_db` is not listed")
        self.assertError(with_env.replace(' — "this database is made for tests"', " — test database"),
                         "has no quoted user permission")

    def test_code_size_warning(self):
        big = "\n".join(f"x{i} = {i}" for i in range(120))
        text = VALID.replace('p.add_argument("--verbose", action="store_true")', big)
        result = self.check(text)
        self.assertTrue(result["ok"])
        self.assertTrue(any("100-lines" in w for w in result["warnings"]))

    SIZE_LINE = "**Size:** 151 lines — таблица данных не делится по смыслу"

    def _with_big_task(self, code_lines, size_line=None):
        """VALID plus Task 90 with exactly `code_lines` lines of code."""
        body = "\n".join(f"y{i} = {i}" for i in range(code_lines))
        task = (
            "\n### Task 90: Big generated table\n\n**Files:**\n- Create: `big.py`\n\n"
            + (size_line + "\n\n" if size_line else "")
            + "**Preconditions:**\n- none\n\n**Postconditions:**\n- `big.py` exists.\n\n"
            "- [ ] **Step 1: Write the table**\n\n```python\n" + body + "\n```\n"
        )
        return VALID.rstrip("\n") + "\n" + task

    def test_code_size_limits(self):
        at_limit = self.check(self._with_big_task(100))
        self.assertTrue(at_limit["ok"], at_limit["errors"])
        self.assertFalse(any(w.startswith("Task 90:") for w in at_limit["warnings"]))
        warned = self.check(self._with_big_task(150))
        self.assertTrue(warned["ok"], warned["errors"])
        self.assertTrue(any(w.startswith("Task 90: 150 lines") and "100-lines" in w for w in warned["warnings"]))
        failed = self.check(self._with_big_task(151))
        self.assertFalse(failed["ok"])
        self.assertIn(
            "Task 90: 151 lines of code (limit 100, error above 150) "
            "without a '**Size:** <N> lines — <reason>' line",
            failed["errors"],
        )
        self.assertFalse(any(w.startswith("Task 90:") for w in failed["warnings"]))
        self.assertNotIn("90", failed["oversized"])

    def test_size_line_justifies_large_task(self):
        result = self.check(self._with_big_task(151, self.SIZE_LINE))
        self.assertTrue(result["ok"], result["errors"])
        self.assertFalse(any(w.startswith("Task 90:") for w in result["warnings"]))
        self.assertIn("90", result["oversized"])
        self.assertNotIn("90", self.check(VALID)["oversized"])

    def test_malformed_size_line(self):
        self.assertError(self._with_big_task(10, "**Size:** big"), "malformed size line")

    def test_size_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec_name = self.check(VALID)["spec"]
            with open(os.path.join(tmp, spec_name), "w", encoding="utf-8") as fh:
                fh.write("> Tier: Standard\n\n# Goal\n\nx\n")
            path = os.path.join(tmp, "size-impl.md")
            for text, expected_code, listed in (
                (self._with_big_task(151), 1, False),
                (self._with_big_task(151, self.SIZE_LINE), 0, True),
            ):
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(text)
                code, out = _run(TOOL, "plan-check", path)
                self.assertEqual(code, expected_code, out["errors"])
                self.assertEqual("90" in out["oversized"], listed)

    def test_russian_body(self):
        text = VALID.replace("Parse the verbose flag", "Разбор флага verbose").replace(
            "Output without `--verbose` is unchanged.", "Вывод без флага не меняется.")
        self.assertTrue(self.check(text)["ok"])

    def test_cli_exit_codes(self):
        self.assertEqual(_run(TOOL, "plan-check", FIXTURE)[0], 0)
        with tempfile.TemporaryDirectory() as tmp:
            bad = os.path.join(tmp, "bad-impl.md")
            with open(bad, "w", encoding="utf-8") as fh:
                fh.write("# Plan\n")
            code, out = _run(TOOL, "plan-check", bad)
            self.assertEqual(code, 1)
            self.assertFalse(out["ok"])
            self.assertEqual(_run(TOOL, "plan-check", os.path.join(tmp, "missing.md"))[0], 2)
        proc = subprocess.run([sys.executable, TOOL], capture_output=True)
        self.assertEqual(proc.returncode, 2)


RU_PLAN = (
    VALID.replace(
        "**Goal:** `cli.py --verbose` prints the input path before the line count.",
        "**Goal:** `cli.py --verbose` печатает путь к файлу перед числом строк.",
    )
    .replace(
        "**Architecture:** One new argparse flag in the existing `main()`; output order is path, then count.",
        "**Architecture:** Один новый флаг argparse в существующей `main()`; сначала путь, затем число строк.",
    )
    .replace("Output without `--verbose` is unchanged.", "Вывод без `--verbose` не меняется.")
    .replace("Task 1 is done.", "Задача 1 выполнена.")
)


class PlanCheckLangTest(unittest.TestCase):
    def test_detect_lang_text(self):
        self.assertEqual(pt.detect_lang_text("Добавить флаг"), "ru")
        self.assertEqual(pt.detect_lang_text("Add a flag"), "en")
        self.assertEqual(pt.detect_lang_text(""), "en")
        self.assertEqual(pt.detect_lang_text("ж" * 5 + "a" * 95), "en")
        self.assertEqual(pt.detect_lang_text("ж" * 6 + "a" * 94), "ru")

    def test_lang_follows_the_body(self):
        self.assertEqual(pt.check_plan(VALID)["lang"], "en")
        result = pt.check_plan(RU_PLAN)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["lang"], "ru")

    def test_code_fences_do_not_count(self):
        fenced = VALID.replace(
            'p.add_argument("--verbose", action="store_true")',
            "# Этот комментарий внутри блока кода не считается телом плана и не меняет язык диалога\n"
            "# Ещё одна строка комментария на русском языке внутри того же блока кода",
        )
        self.assertEqual(pt.check_plan(fenced)["lang"], "en")

    def test_cli_reports_lang(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "ru-impl.md")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(RU_PLAN)
            code, out = _run(TOOL, "plan-check", path)
        self.assertEqual(code, 0)
        self.assertEqual(out["lang"], "ru")


@unittest.skipUnless(os.path.isfile(EXECUTOR), "plan-executor not installed alongside")
class ExecutorContractTest(unittest.TestCase):
    """plan-executor must see exactly the tasks that plan-check sees."""

    def test_executor_parses_same_task_ids(self):
        code, out = _run(EXECUTOR, "parse-tasks", FIXTURE)
        self.assertEqual(code, 0)
        units = out.get("units", out.get("tasks", []))
        expected = ["task-" + t["id"] for t in pt.check_plan(VALID)["tasks"]]
        self.assertEqual([u["id"] for u in units], expected)


@unittest.skipUnless(os.path.isfile(RESOLVER), "plan-resolver not installed alongside")
class ResolverContractTest(unittest.TestCase):
    """plan-resolver task-census must extract the plan's task ids."""

    def test_census_sees_plan_tasks(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = os.path.join(tmp, "plan01-impl-report-1.md")
            with open(report, "w", encoding="utf-8") as fh:
                fh.write("# r\n\n## Основные стадии плана\n\n- ✅ 1 Task\n")
            code, out = _run(RESOLVER, "task-census", FIXTURE, report)
        self.assertEqual(out["plan_ids"], [t["id"] for t in pt.check_plan(VALID)["tasks"]])
        self.assertEqual(out["uncovered"], ["1.1", "2"])
        self.assertEqual(code, 1)


@unittest.skipUnless(os.path.isfile(BRAINSTORM), "plan-brainstorming not installed alongside")
class SettingsTest(unittest.TestCase):
    """plan-check reads settings by the shared rule: plan header first, else the spec at **Spec:**."""

    def setUp(self):
        with open(SETTINGS_PLAN, encoding="utf-8") as fh:
            self.plan = fh.read()
        with open(SETTINGS_SPEC, encoding="utf-8") as fh:
            self.spec = fh.read()

    def check_pair(self, plan, spec=None):
        """plan-check on `plan` written as settings01-impl.md next to `spec` (None: no spec file)."""
        with tempfile.TemporaryDirectory() as tmp:
            if spec is not None:
                with open(os.path.join(tmp, "settings01-spec.md"), "w", encoding="utf-8") as fh:
                    fh.write(spec)
            path = os.path.join(tmp, "settings01-impl.md")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(plan)
            return pt.check_plan(plan, None, path)

    def test_plan_settings_reads_spec(self):
        settings, errors, warnings = pt._plan_settings(SETTINGS_PLAN)
        self.assertEqual(errors, [])
        self.assertEqual(settings["from"], "spec")
        self.assertEqual([e["name"] for e in settings["environments"]], ["dev_db", "prod_db"])
        self.assertEqual(settings["chain"]["split"], "never")

    def test_plan_settings_missing_spec_is_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "plan01-impl.md")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(VALID)
            settings, errors, warnings = pt._plan_settings(path)
        self.assertEqual(errors, [])
        self.assertFalse(settings["ok"])
        self.assertTrue(any("settings-source-missing" in w for w in warnings), warnings)

    def test_plan_settings_without_path(self):
        self.assertEqual(pt._plan_settings(None), (None, [], []))

    def test_check_plan_reports_settings_and_size(self):
        result = pt.check_plan(self.plan, None, SETTINGS_PLAN)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["settings"]["from"], "spec")
        self.assertEqual(result["environments"], ["dev_db", "prod_db"])
        self.assertEqual(result["task_count"], 2)
        self.assertEqual(result["plan_bytes"], len(self.plan.encode("utf-8")))

    def test_text_only_call_keeps_legacy_result(self):
        result = pt.check_plan(VALID)
        self.assertIsNone(result["settings"])
        self.assertEqual(result["task_count"], 3)
        self.assertEqual(result["warnings"], [])

    def test_unlisted_environment_names_both_sources(self):
        plan = self.plan.replace("`prod_db` (read)", "`stage_db` (read)")
        result = pt.check_plan(plan, None, SETTINGS_PLAN)
        self.assertTrue(any("`stage_db` is not listed in the settings" in e for e in result["errors"]), result["errors"])

    def test_external_without_settings_is_error(self):
        result = self.check_pair(self.plan)
        self.assertFalse(result["ok"])
        self.assertTrue(any("settings are unavailable" in e for e in result["errors"]), result["errors"])

    def test_missing_spec_without_external_is_warning(self):
        result = self.check_pair(VALID)
        self.assertEqual(result["errors"], [])
        self.assertTrue(any("settings-source-missing" in w for w in result["warnings"]), result["warnings"])

    def test_access_required_when_environment_has_rights(self):
        plan = self.plan.replace("`dev_db` (write)", "`dev_db`")
        result = self.check_pair(plan, self.spec)
        self.assertTrue(any("needs the access type" in e for e in result["errors"]), result["errors"])

    def test_write_on_write_deny_is_error(self):
        plan = self.plan.replace("`prod_db` (read)", "`prod_db` (write)")
        result = self.check_pair(plan, self.spec)
        self.assertTrue(any("write=deny" in e for e in result["errors"]), result["errors"])

    def test_read_on_read_deny_is_error(self):
        spec = self.spec.replace("read=run, write=task", "read=deny, write=task")
        plan = self.plan.replace("`dev_db` (write)", "`dev_db` (read)")
        result = self.check_pair(plan, spec)
        self.assertTrue(any("read=deny" in e for e in result["errors"]), result["errors"])

    def test_legacy_header_without_rights_still_passes(self):
        env_block = '**Environments:**\n- `dev_db` (test) — "this database is made for tests" (2026-09-30)\n\n'
        plan = VALID.replace("**Tier:** Standard\n", "**Tier:** Standard\n\n" + env_block, 1)
        plan = plan.replace("**Preconditions:**", "**External:** `dev_db` — smoke test\n\n**Preconditions:**", 1)
        result = self.check_pair(plan)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["settings"]["from"], "plan-header")
        self.assertIsNone(result["settings"]["environments"][0]["read"])
        self.assertTrue(any("has no access type" in w for w in result["warnings"]), result["warnings"])

    def test_header_settings_win_over_spec(self):
        header = '**Environments:**\n- `dev_db` (test; read=run, write=run) — "Smoke test on dev_db? — Yes" (2026-10-01)\n\n'
        plan = self.plan.replace("**Tier:** Standard\n", "**Tier:** Standard\n\n" + header, 1)
        result = self.check_pair(plan, self.spec)
        self.assertEqual(result["settings"]["from"], "plan-header")
        self.assertEqual(result["environments"], ["dev_db"])
        self.assertTrue(any("`prod_db` is not listed" in e for e in result["errors"]), result["errors"])

    def test_bad_chain_and_duplicate_backlog_in_header_fail(self):
        header = "**Chain:** split=bogus\n\n**Backlog:** a\n\n**Backlog:** b\n\n"
        plan = VALID.replace("**Tier:** Standard\n", "**Tier:** Standard\n\n" + header, 1)
        result = self.check_pair(plan)
        self.assertFalse(result["ok"])
        settings_errors = [e for e in result["errors"] if e.startswith("settings: line ")]
        self.assertTrue(any("unknown value 'bogus' for chain key 'split'" in e for e in settings_errors), result["errors"])
        self.assertTrue(any("duplicate Backlog line" in e for e in settings_errors), result["errors"])


@unittest.skipUnless(os.path.isfile(BRAINSTORM), "plan-brainstorming not installed alongside")
class BrainstormContractTest(unittest.TestCase):
    """plan-check must see the settings that spec-check and resolve_settings see."""

    def test_spec_check_and_plan_check_agree(self):
        code, spec_out = _run(BRAINSTORM, "spec-check", SETTINGS_SPEC)
        self.assertEqual(code, 0, spec_out)
        code, plan_out = _run(TOOL, "plan-check", SETTINGS_PLAN)
        self.assertEqual(code, 0, plan_out)
        resolved = pt._load_brainstorm_tool().resolve_settings(SETTINGS_PLAN)
        self.assertEqual([e["name"] for e in resolved["environments"]], ["dev_db", "prod_db"])
        self.assertEqual(spec_out["environments"], resolved["environments"])
        self.assertEqual(plan_out["settings"]["environments"], resolved["environments"])
        self.assertEqual(plan_out["settings"]["chain"], resolved["chain"])
        self.assertEqual(plan_out["environments"], ["dev_db", "prod_db"])
        self.assertEqual(plan_out["task_count"], 2)

    def test_cli_on_legacy_fixture(self):
        code, out = _run(TOOL, "plan-check", FIXTURE)
        self.assertEqual(code, 0, out)
        self.assertEqual(out["task_count"], 3)
        self.assertTrue(any("settings-source-missing" in w for w in out["warnings"]), out["warnings"])


if __name__ == "__main__":
    unittest.main()
