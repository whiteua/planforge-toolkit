"""Tests for plan_tool.py.

Uses unittest (stdlib) so no external dependencies are needed.
Run: python -m pytest skills/plan-writing/tests -q
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.abspath(os.path.join(HERE, "..", "scripts", "plan_tool.py"))
FIXTURE = os.path.join(HERE, "fixtures", "plan01-impl.md")
EXECUTOR = os.path.abspath(os.path.join(HERE, "..", "..", "plan-executor", "scripts", "executor_tool.py"))
RESOLVER = os.path.abspath(os.path.join(HERE, "..", "..", "plan-resolver", "scripts", "resolver_tool.py"))
BRAINSTORM = os.path.abspath(os.path.join(HERE, "..", "..", "plan-brainstorming", "scripts", "brainstorm_tool.py"))
SETTINGS_SPEC = os.path.join(HERE, "fixtures", "settings01-spec.md")
SETTINGS_PLAN = os.path.join(HERE, "fixtures", "settings01-impl.md")
SPLITTER = os.path.abspath(os.path.join(HERE, "..", "..", "plan-splitter", "scripts", "splitter_tool.py"))
REVISION = os.path.abspath(os.path.join(HERE, "..", "..", "plan-iterative-revision", "scripts", "next_review_index.py"))


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

    STRUCTURAL = "**Structural event:** convention — a new rule for the pipeline skills\n\n"

    def _claude_md_task(self, line=""):
        return VALID.replace("**Files:**\n- Modify: `README.md`\n\n", "**Files:**\n- Modify: `CLAUDE.md`\n\n" + line)

    def test_claude_md_edit_needs_a_structural_event(self):  # spec 1 of plan-refactoring-02
        warned = self.check(self._claude_md_task())
        self.assertTrue(warned["ok"], warned["errors"])
        self.assertTrue(any(w.startswith("Task 1.1: claude-md-edit:") for w in warned["warnings"]), warned["warnings"])
        marked = self.check(self._claude_md_task(self.STRUCTURAL))
        self.assertEqual((marked["errors"], marked["warnings"]), ([], []))
        created = self.check(VALID.replace("- Modify: `README.md`", "- Create: `sub/CLAUDE.md`"))
        self.assertTrue(any("claude-md-edit" in w for w in created["warnings"]), created["warnings"])

    def test_structural_event_key_and_reason_are_checked(self):
        self.assertError(self._claude_md_task("**Structural event:** feature — x\n\n"), "malformed structural event line")
        self.assertError(self._claude_md_task("**Structural event:** convention\n\n"), "malformed structural event line")

    def test_skeleton_keeps_the_structural_event(self):
        text, _ = pt._render_skeleton(self._claude_md_task(self.STRUCTURAL))
        self.assertIn("**Structural event:** convention — a new rule for the pipeline skills", text)

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


class SizeBudgetTest(unittest.TestCase):
    def test_size_budget_sources(self):
        self.assertEqual(pt.size_budget(), {"tasks": 40, "bytes": 150000, "source": "brainstorm_tool"})
        self.assertEqual(pt.size_budget(max_tasks=50), {"tasks": 50, "bytes": 150000, "source": "flags"})
        self.assertEqual(pt.size_budget(max_bytes=200000), {"tasks": 40, "bytes": 200000, "source": "flags"})
        with mock.patch.object(pt, "_load_brainstorm_tool", return_value=None):
            self.assertEqual(pt.size_budget(), {"tasks": 40, "bytes": 150000, "source": "default"})

    def test_size_class(self):
        budget = {"tasks": 40, "bytes": 150000, "source": "default"}
        cases = ((0, 10, None), (3, 10, "small"), (15, 10, "small"), (16, 10, "medium"),
                 (40, 150000, "medium"), (41, 10, "large"), (10, 150001, "large"))
        for count, size, expected in cases:
            with self.subTest(count=count, size=size):
                self.assertEqual(pt.size_class(count, size, budget), expected)


TASK_TEMPLATE = (
    "### Task {n}: Step {n}\n\n**Files:**\n- Modify: `cli.py`\n\n**Preconditions:**\n- none\n\n"
    "**Postconditions:**\n- step {n} done\n\n- [ ] **Step 1: Run**\n\nRun: `python cli.py f`\nExpected: PASS\n\n"
)


def _plan_with_tasks(count, pad_bytes=0):
    """VALID's header plus `count` minimal Standard tasks and about `pad_bytes` of prose at the end."""
    pad = ("x" * 99 + "\n") * (pad_bytes // 100)
    return VALID.split("### Task 1:")[0] + "".join(TASK_TEMPLATE.format(n=n) for n in range(1, count + 1)) + pad


def _oversized(result):
    return [w for w in result["warnings"] if w.startswith("plan-oversized:")]


class PlanSizeTest(unittest.TestCase):
    def test_size_classes(self):
        for count, expected in ((3, "small"), (15, "small"), (16, "medium"), (20, "medium"),
                                (40, "medium"), (41, "large")):
            with self.subTest(count=count):
                result = pt.check_plan(_plan_with_tasks(count))
                self.assertTrue(result["ok"], result["errors"])
                self.assertEqual(result["task_count"], count)
                self.assertEqual(result["size_class"], expected)
                self.assertEqual(bool(_oversized(result)), expected == "large")

    def test_oversized_warning_text_and_budget(self):
        text = _plan_with_tasks(41)
        result = pt.check_plan(text)
        self.assertEqual(result["budget"], {"tasks": 40, "bytes": 150000, "source": "brainstorm_tool"})
        self.assertEqual(_oversized(result), [
            f"plan-oversized: 41 tasks, {len(text.encode('utf-8'))} bytes (budget 40 tasks / 150000 bytes)"])

    def test_large_by_bytes(self):
        result = pt.check_plan(_plan_with_tasks(10, pad_bytes=160000))
        self.assertTrue(result["ok"], result["errors"])
        self.assertGreater(result["plan_bytes"], 150000)
        self.assertEqual(result["size_class"], "large")
        self.assertEqual(len(_oversized(result)), 1)

    def test_budget_argument_overrides(self):
        budget = pt.size_budget(max_tasks=50)
        self.assertEqual(budget, {"tasks": 50, "bytes": 150000, "source": "flags"})
        result = pt.check_plan(_plan_with_tasks(41), None, None, budget)
        self.assertEqual(result["size_class"], "medium")
        self.assertEqual(_oversized(result), [])

    def test_default_budget_without_brainstorm_tool(self):
        with mock.patch.object(pt, "_load_brainstorm_tool", return_value=None):
            self.assertEqual(pt.size_budget(), {"tasks": 40, "bytes": 150000, "source": "default"})
            result = pt.check_plan(_plan_with_tasks(41))
        self.assertEqual(result["budget"]["source"], "default")
        self.assertEqual(result["size_class"], "large")

    def test_no_tasks_no_size_class(self):
        result = pt.check_plan("# Plan\n")
        self.assertFalse(result["ok"])
        self.assertIsNone(result["size_class"])
        self.assertEqual(_oversized(result), [])

    def test_cli_flags_and_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "big-impl.md")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(_plan_with_tasks(41))
            code, out = _run(TOOL, "plan-check", path)
            self.assertEqual(code, 0, out["errors"])
            self.assertEqual(out["size_class"], "large")
            self.assertEqual(len(_oversized(out)), 1)
            code, out = _run(TOOL, "plan-check", path, "--max-tasks", "50", "--max-bytes", "200000")
            self.assertEqual(code, 0, out["errors"])
            self.assertEqual(out["budget"], {"tasks": 50, "bytes": 200000, "source": "flags"})
            self.assertEqual((out["size_class"], _oversized(out)), ("medium", []))
            for flag, value in (("--max-tasks", "0"), ("--max-tasks", "-3"), ("--max-bytes", "abc")):
                code, out = _run(TOOL, "plan-check", path, flag, value)
                self.assertEqual(code, 2, (flag, value))
                self.assertFalse(out["ok"])
                self.assertIn(flag, out["errors"][0])


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


class SizeBudgetContractTest(unittest.TestCase):
    """One plan size budget: brainstorm_tool.SIZE_BUDGET, the plan_tool fallback and the splitter gate."""

    def test_plan_tool_fallback_equals_shared_budget(self):
        self.assertEqual(pt._load_brainstorm_tool().SIZE_BUDGET, pt.SIZE_BUDGET_DEFAULT)
        self.assertEqual(pt.size_budget()["source"], "brainstorm_tool")

    def test_splitter_gate_uses_the_same_thresholds(self):
        with open(SPLITTER, encoding="utf-8") as fh:
            if "def gate_verdict(" not in fh.read():
                self.skipTest("splitter gate_verdict not implemented yet (spec plan-refactoring-01-3)")
        code, out = _run(SPLITTER, "gate", FIXTURE)
        self.assertEqual(code, 0, out)
        thresholds = out["thresholds"]
        self.assertEqual((thresholds["split_tasks"], thresholds["split_bytes"]),
                         (pt.SIZE_BUDGET_DEFAULT["tasks"], pt.SIZE_BUDGET_DEFAULT["bytes"]))


@unittest.skipUnless(os.path.isfile(BRAINSTORM), "plan-brainstorming not installed alongside")
class NonUtf8SpecTest(unittest.TestCase):
    def test_plan_check_reports_a_spec_that_is_not_utf8_as_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "a-spec.md"), "wb") as fh:
                fh.write("> Tier: Quick\n\n# Goal\n\nПривет\n".encode("cp1251"))
            plan = os.path.join(tmp, "a-impl.md")
            with open(plan, "w", encoding="utf-8") as fh:
                fh.write("**Spec:** a-spec.md\n\n### Task 1: x\n")
            code, out = _run(TOOL, "plan-check", plan)
        self.assertEqual(code, 2)
        self.assertFalse(out["ok"])
        self.assertIn("cannot read", out["errors"][0])


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


@unittest.skipUnless(os.path.isfile(BRAINSTORM), "plan-brainstorming not installed alongside")
class JournalTest(unittest.TestCase):
    """plan-check returns the chain journal (brainstorm_tool.journal_path_for) when the file exists."""

    def write_plan(self, tmp, spec_line="**Spec:** demo-spec.md", with_spec=True):
        if with_spec:
            with open(os.path.join(tmp, "demo-spec.md"), "w", encoding="utf-8") as fh:
                fh.write("> Tier: Standard\n\n# Goal\n\nDemo.\n")
        path = os.path.join(tmp, "demo-impl.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(VALID.replace("**Spec:** plan01-spec.md", spec_line))
        return path

    def test_journal_null_until_the_file_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = self.write_plan(tmp)
            code, out = _run(TOOL, "plan-check", plan)
            self.assertEqual(code, 0, out)
            self.assertIsNone(out["journal"])
            journal = os.path.join(tmp, "demo-chain.json")
            with open(journal, "w", encoding="utf-8") as fh:
                fh.write("{}\n")
            code, out = _run(TOOL, "plan-check", plan)
            self.assertEqual(code, 0, out)
            self.assertEqual(os.path.normcase(out["journal"]), os.path.normcase(os.path.abspath(journal)))

    def test_plan_without_spec_line_keeps_journal_next_to_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = self.write_plan(tmp, spec_line="", with_spec=False)
            journal = os.path.join(tmp, "demo-chain.json")
            with open(journal, "w", encoding="utf-8") as fh:
                fh.write("{}\n")
            code, out = _run(TOOL, "plan-check", plan)
            self.assertEqual(code, 1, out)  # the plan fails the header check, the journal is still reported
            self.assertEqual(os.path.normcase(out["journal"]), os.path.normcase(os.path.abspath(journal)))

    def test_missing_spec_gives_null(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = self.write_plan(tmp, with_spec=False)
            code, out = _run(TOOL, "plan-check", plan)
            self.assertEqual(code, 0, out)
            self.assertIsNone(out["journal"])

    def test_missing_old_or_failing_module_gives_null(self):
        class Old:
            pass

        class Broken:
            @staticmethod
            def journal_path_for(path):
                raise RuntimeError("boom")

        for module in (None, Old(), Broken()):
            with mock.patch.object(pt, "_load_brainstorm_tool", return_value=module):
                self.assertIsNone(pt._journal_for(FIXTURE), module)


class LocalTaskParserTest(unittest.TestCase):
    """_local_plan_tasks: the fallback of plan_tool without plan-brainstorming, in the shared parser's shape."""

    KEYS = ("id", "title", "line_start", "line_end", "checkpoint", "code_lines")

    def test_local_parse_matches_the_shared_parser_on_the_reference_plan(self):
        lines = pt._split_lines(VALID)
        shared, local_used = pt._plan_tasks(VALID, lines)
        local = pt._local_plan_tasks(lines)
        self.assertFalse(local_used)
        self.assertEqual([{k: t[k] for k in self.KEYS} for t in local["tasks"]],
                         [{k: t[k] for k in self.KEYS} for t in shared["tasks"]])
        self.assertEqual((local["malformed"], local["duplicates"]), ([], []))

    def test_plan_tasks_without_the_parser(self):
        for module in (None, object()):
            with mock.patch.object(pt, "_load_brainstorm_tool", return_value=module):
                parsed, local_used = pt._plan_tasks(VALID, pt._split_lines(VALID))
            self.assertTrue(local_used)
            self.assertEqual([t["id"] for t in parsed["tasks"]], ["1", "1.1", "2"])

    def test_local_malformed_and_duplicates(self):
        text = VALID.replace("### Task 1.1:", "### Task 1:").replace("### Task 2: Checkpoint", "### Task 2 Checkpoint")
        local = pt._local_plan_tasks(pt._split_lines(text))
        self.assertEqual(local["duplicates"], [{"id": "1", "lines": [17, 56]}])
        self.assertEqual(local["malformed"], [{"line": 74, "text": "### Task 2 Checkpoint — flag works end to end"}])


class CheckPlanSharedParserTest(unittest.TestCase):
    """check_plan takes tasks and bodies from the shared parser; the fallback keeps the verdict."""

    def test_fallback_keeps_the_result_and_warns(self):
        shared = pt.check_plan(VALID)
        with mock.patch.object(pt, "_load_brainstorm_tool", return_value=None):
            local = pt.check_plan(VALID)
        self.assertEqual((local["tasks"], local["errors"]), (shared["tasks"], shared["errors"]))
        self.assertEqual([(t["id"], t["line"]) for t in shared["tasks"]], [("1", 17), ("1.1", 56), ("2", 74)])
        self.assertIn("plan-brainstorming not installed alongside", local["warnings"])
        self.assertNotIn("plan-brainstorming not installed alongside", shared["warnings"])

    def test_fallback_keeps_the_error_texts(self):
        for broken in (VALID.replace("### Task 1.1:", "### Task 1:"),
                       VALID.replace("### Task 1.1:", "### Task A:"),
                       VALID.replace("### Task 1.1: Document", "### Task 1.1 Document"),
                       VALID.replace("### Task 2: Checkpoint", "### Phase Checkpoint")):
            shared = pt.check_plan(broken)["errors"]
            with mock.patch.object(pt, "_load_brainstorm_tool", return_value=None):
                self.assertEqual(pt.check_plan(broken)["errors"], shared)

    def test_heading_of_task_level_closes_the_body(self):
        code = "\n".join(f"z{i} = {i}" for i in range(120))
        text = VALID.rstrip("\n") + "\n\n### Notes\n\n```python\n" + code + "\n```\n"
        self.assertFalse(any(w.startswith("Task 2:") for w in pt.check_plan(text)["warnings"]))
        with mock.patch.object(pt, "_load_brainstorm_tool", return_value=None):
            local = pt.check_plan(text)["warnings"]
        self.assertTrue(any(w.startswith("Task 2: 120 lines") for w in local), local)


TRICKY = os.path.join(HERE, "fixtures", "tricky-impl.md")
CHAIN = os.path.abspath(os.path.join(HERE, "..", "..", "plan-chain-runner", "scripts", "chain_tool.py"))


def _load_by_path(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless(all(os.path.isfile(p) for p in (BRAINSTORM, EXECUTOR, RESOLVER, SPLITTER)),
                     "pipeline skills not installed alongside")
class TaskParserContractTest(unittest.TestCase):
    """One task parser: every consumer sees the tasks of brainstorm_tool.parse_plan_tasks."""

    FIXTURES = (FIXTURE, TRICKY)

    def parsed(self, path):
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        return text, _load_by_path("brainstorm_tool", BRAINSTORM).parse_plan_tasks(text)

    def test_fixtures_are_contract_plans(self):
        for path in self.FIXTURES:
            text, parsed = self.parsed(path)
            self.assertTrue(parsed["tasks"], path)
            self.assertEqual((parsed["malformed"], parsed["duplicates"]), ([], []), path)
            self.assertEqual(pt.check_plan(text)["errors"], [], path)

    def test_tricky_boundaries(self):
        _, parsed = self.parsed(TRICKY)
        self.assertEqual([(t["id"], t["level"], t["line_start"], t["line_end"]) for t in parsed["tasks"]],
                         [("1", 3, 15, 40), ("1.1", 3, 41, 57), ("2", 3, 64, 80), ("3", 4, 81, 96), ("4", 3, 97, 105)])
        self.assertEqual([t["refs"] for t in parsed["tasks"]], [[], ["1"], ["1", "1.1"], ["2"], []])

    def test_plan_check_sees_the_same_headings(self):
        for path in self.FIXTURES:
            text, parsed = self.parsed(path)
            self.assertEqual([(t["id"], t["line"]) for t in pt.check_plan(text)["tasks"]],
                             [(t["id"], t["line_start"]) for t in parsed["tasks"]], path)

    def test_executor_units_have_the_same_lines(self):
        for path in self.FIXTURES:
            _, parsed = self.parsed(path)
            code, out = _run(EXECUTOR, "parse-tasks", path)
            self.assertEqual(code, 0, out)
            self.assertEqual([(u["id"], u["source"]["line_start"], u["source"]["line_end"]) for u in out["units"]],
                             [("task-" + t["id"], t["line_start"], t["line_end"]) for t in parsed["tasks"]], path)

    def test_resolver_census_sees_the_same_ids(self):
        for path in self.FIXTURES:
            _, parsed = self.parsed(path)
            with tempfile.TemporaryDirectory() as tmp:
                report = os.path.join(tmp, "x-impl-report-1.md")
                with open(report, "w", encoding="utf-8") as fh:
                    fh.write("# r\n\n## Основные стадии плана\n\n- ✅ 1 Task\n")
                _, out = _run(RESOLVER, "task-census", path, report)
            self.assertEqual(out["plan_ids"], [t["id"].lower() for t in parsed["tasks"]], path)

    def test_splitter_counts_the_same_tasks(self):
        splitter = _load_by_path("splitter_tool", SPLITTER)
        for path in self.FIXTURES:
            text, parsed = self.parsed(path)
            self.assertEqual(splitter.count_tasks_in_original(text), len(parsed["tasks"]), path)

    def test_chain_runner_counts_the_same_tasks(self):
        if not os.path.isfile(CHAIN):
            self.skipTest("plan-chain-runner not installed alongside")
        chain = _load_by_path("chain_tool", CHAIN)
        if not hasattr(chain, "_count_plan_tasks"):
            self.skipTest("chain_tool._count_plan_tasks not implemented yet (spec plan-refactoring-01-1)")
        for path in self.FIXTURES:
            text, parsed = self.parsed(path)
            self.assertEqual(chain._count_plan_tasks(text), len(parsed["tasks"]), path)


@unittest.skipUnless(all(os.path.isfile(p) for p in (BRAINSTORM, EXECUTOR, RESOLVER, SPLITTER, REVISION)),
                     "pipeline skills not installed alongside")
class SplitWriteContractTest(unittest.TestCase):
    """Roadmap and parts written by splitter split-write are read by every parser of roadmaps and parts."""

    def split(self, tmp, source, name, parts):
        plan = os.path.join(tmp, name)
        shutil.copyfile(source, plan)
        path = os.path.join(tmp, "parts.json")
        entries = [{"id": pid, "title": f"Part {pid}", "depends": deps, "group": group, "weight": "🟡 medium",
                    "goal": "g", "inputs": "i", "outputs": "o", "notes": "", "tasks": tasks}
                   for pid, tasks, deps, group in parts]
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"parts": entries}, fh)
        code, out = _run(SPLITTER, "split-write", plan, "--parts", path)
        self.assertEqual(code, 0, out)
        return plan, out["roadmap"]

    def test_parsers_agree_on_split_write_parts(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan, roadmap = self.split(tmp, FIXTURE, "plan01-impl.md",
                                       [("a", ["1", "1.1"], [], "A"), ("b", ["2"], ["a"], "B")])
            code, rows = _run(EXECUTOR, "parse-roadmap", roadmap)
            self.assertEqual((code, [r["stage"] for r in rows], rows[1]["depends"]), (0, ["a", "b"], ["a"]))
            code, out = _run(REVISION, "parts", roadmap)
            self.assertEqual((code, [p["id"] for p in out["parts"]]), (0, ["a", "b"]))
            code, out = _run(SPLITTER, "validate-all", tmp, "plan01-impl")
            self.assertEqual((code, out["task_bodies"]["matched"], out["coverage"]["ok"]), (0, 3, True))
            report = os.path.join(tmp, "plan01-impl-report-1.md")
            with open(report, "w", encoding="utf-8") as fh:
                fh.write("# r\n\n## Основные стадии плана\n\n- ✅ 1 Task\n")
            _, census = _run(RESOLVER, "task-census", plan, report)
            self.assertEqual(census["plan_ids"], ["1", "1.1", "2"])

    def test_external_lines_reach_the_parts(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.split(tmp, SETTINGS_PLAN, "settings01-impl.md", [("a", ["1"], [], "A"), ("b", ["2"], ["a"], "B")])
            code, out = _run(SPLITTER, "validate-all", tmp, "settings01-impl")
            self.assertEqual((code, out["task_lines"]), (0, {"original": 2, "missing": []}))

    def test_all_three_task_lines_reach_the_parts(self):  # spec 1 of plan-refactoring-02
        size = "**Size:** 120 lines — the smoke rows are one table"
        structural = "**Structural event:** convention — the count rule is shared"
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copyfile(SETTINGS_SPEC, os.path.join(tmp, "settings01-spec.md"))
            with open(SETTINGS_PLAN, encoding="utf-8") as fh:
                text = fh.read()
            text = text.replace("load two rows and run the smoke test\n",
                                "load two rows and run the smoke test\n\n" + size + "\n")
            text = text.replace("- Test: `tests/test_counts.py`\n",
                                "- Test: `tests/test_counts.py`\n- Modify: `CLAUDE.md`\n\n" + structural + "\n")
            source = os.path.join(tmp, "source.md")
            with open(source, "w", encoding="utf-8") as fh:
                fh.write(text)
            plan, _ = self.split(tmp, source, "settings01-impl.md", [("a", ["1"], [], "A"), ("b", ["2"], ["a"], "B")])
            code, out = _run(TOOL, "plan-check", plan)
            self.assertEqual((code, out["errors"]), (0, []))
            self.assertFalse(any("claude-md-edit" in w for w in out["warnings"]), out["warnings"])
            code, out = _run(SPLITTER, "validate-all", tmp, "settings01-impl")
            self.assertEqual((code, out["task_lines"]), (0, {"original": 4, "missing": []}))


@unittest.skipUnless(all(os.path.isfile(p) for p in (BRAINSTORM, RESOLVER, REVISION)),
                     "pipeline skills not installed alongside")
class TaskIdContractTest(unittest.TestCase):
    """F7 of plan-refactoring-02: one normalization rule of task ids in every script that compares them."""

    def test_task_ids_are_normalized_alike(self):
        brainstorm = _load_by_path("brainstorm_tool", BRAINSTORM)
        resolver = _load_by_path("resolver_tool", RESOLVER)
        revision = _load_by_path("next_review_index", REVISION)
        for value in ("01.02", "007", "1.10", "12", "a1", "x.01"):
            expected = brainstorm.normalize_task_id(value)
            self.assertEqual(revision.normalize_task_id(value), expected, value)
            self.assertEqual(resolver.normalize_plan_task_id(value), expected.lower(), value)


class SkeletonHelperTest(unittest.TestCase):
    def test_code_blocks_and_unclosed_fence(self):
        lines = ["a", "```python", "x = 1", "```", "~~~", "y"]
        blocks, warnings = pt._code_blocks(lines)
        self.assertEqual(blocks, {2: (4, "python"), 5: (7, "")})
        self.assertEqual(len(warnings), 1)
        self.assertTrue(warnings[0].startswith("unclosed-fence: the code block at line 5"))

    def test_code_line(self):
        body = ["class Bar:", "    def foo(self, a) -> int:", "        return a", "x = 1"]
        self.assertEqual(pt._code_line(body, "python", "signatures"),
                         "[code python, 4 lines: class Bar; def foo(self, a) -> int]")
        self.assertEqual(pt._code_line(body, "python", "none"), "[code python, 4 lines]")
        self.assertEqual(pt._code_line(body, "markdown", "signatures"), "[code markdown, 4 lines]")
        self.assertEqual(pt._code_line(body, "", "signatures"), "[code, 4 lines]")
        many = [f"def f{i}():" for i in range(7)]
        self.assertEqual(pt._code_line(many, "python", "signatures"),
                         "[code python, 7 lines: def f0(); def f1(); def f2(); def f3(); def f4(); …]")

    def test_parse_tasks_needs_the_shared_parser(self):
        self.assertEqual([t["id"] for t in pt._parse_tasks(VALID)], ["1", "1.1", "2"])
        for module in (None, object()):
            with mock.patch.object(pt, "_load_brainstorm_tool", return_value=module):
                with self.assertRaises(pt.InputError) as ctx:
                    pt._parse_tasks(VALID)
            self.assertEqual(str(ctx.exception), "plan-brainstorming not installed alongside")


class SkeletonTest(unittest.TestCase):
    def test_reference_plan(self):
        text, warnings = pt._render_skeleton(VALID)
        self.assertEqual(warnings, [])
        header = VALID[:VALID.index("### Task 1:")]
        self.assertTrue(text.startswith(header))
        for kept in ("### Task 1: Parse the verbose flag", "- Modify: `cli.py:4-6`", "**Preconditions:**",
                     "- Output without `--verbose` is unchanged.", "- [ ] **Step 2: Run the test to verify it fails**",
                     "Run: `python -m pytest tests/test_cli.py -q`", "Expected: PASS",
                     "[code python, 5 lines: def test_verbose_prints_path(tmp_path)]", "[code python, 1 lines]",
                     "[code markdown, 2 lines]", "**Done when:** both lines appear as expected."):
            self.assertIn(kept, text)
        self.assertNotIn("target.write_text", text)
        self.assertNotIn("## Task 9", text)
        self.assertNotIn("\n\n\n", text)

    def test_tasks_filter(self):
        text, _ = pt._render_skeleton(VALID, ["1.1"])
        self.assertIn("### Task 1.1: Document the flag", text)
        self.assertNotIn("### Task 1: Parse", text)
        self.assertNotIn("### Task 2:", text)
        self.assertTrue(text.startswith("# Verbose Flag Implementation Plan"))
        with self.assertRaises(pt.InputError) as ctx:
            pt._render_skeleton(VALID, ["1.1", "7"])
        self.assertEqual(str(ctx.exception), "task-not-found: 7")


class TaskTextTest(unittest.TestCase):
    def test_task_bytes(self):
        lines = VALID.splitlines(keepends=True)
        self.assertEqual(pt._task_text(VALID, "1.1"), "".join(lines[55:73]))
        crlf = VALID.replace("\n", "\r\n")
        self.assertEqual(pt._task_text(crlf, "1.1"), "".join(lines[55:73]).replace("\n", "\r\n"))
        with self.assertRaises(pt.InputError) as ctx:
            pt._task_text(VALID, "9")
        self.assertEqual(str(ctx.exception), "task-not-found: 9")
        with mock.patch.object(pt, "_load_brainstorm_tool", return_value=None):
            with self.assertRaises(pt.InputError) as ctx:
                pt._task_text(VALID, "1")
        self.assertEqual(str(ctx.exception), "plan-brainstorming not installed alongside")

    def test_zero_padded_ids(self):  # F7 of plan-refactoring-02
        lines = VALID.splitlines(keepends=True)
        self.assertEqual(pt._task_text(VALID, "01.1"), "".join(lines[55:73]))
        text, _ = pt._render_skeleton(VALID, ["01.01"])
        self.assertIn("### Task 1.1: Document the flag", text)
        self.assertNotIn("### Task 1: Parse", text)

    def test_no_tasks_and_unclosed_fence(self):
        text, warnings = pt._render_skeleton("# Notes\n\nplain text\n")
        self.assertEqual(text, "# Notes\n\nplain text\n")
        self.assertTrue(warnings[0].startswith("no-tasks"))
        tail = VALID + "\n```python\ndef dangling():\n"
        text, warnings = pt._render_skeleton(tail)
        self.assertTrue(text.endswith("[code python, 1 lines: def dangling()]\n"), text[-80:])
        self.assertTrue(any(w.startswith("unclosed-fence") for w in warnings))


SYNTHETIC = """# Demo Implementation Plan

**Spec:** demo-spec.md

**Tier:** Standard

---

### Task 1: Tool

**Files:**
- Create: `src/tool.ts`

**Preconditions:**
- none

**Postconditions:**
- `run()` returns 0.

**If stuck:**
- read the tool docs.

- [ ] **Step 1: Implement**

This prose explains the step and is dropped.

@@@ts
export function run(): number {
  return helper();
}
function helper(): number {
  return 0;
}
@@@

@@@json
{"def": "not a signature"}
@@@

@@@
def plain(): pass
@@@

Run: `npm test`
Expected: PASS
""".replace("@@@", "`" * 3)


class SkeletonRulesTest(unittest.TestCase):
    def test_synthetic_plan(self):
        text, warnings = pt._render_skeleton(SYNTHETIC)
        self.assertEqual(warnings, [])
        self.assertIn("[code ts, 6 lines: export function run(): number; function helper(): number]", text)
        self.assertIn("[code json, 1 lines]", text)
        self.assertIn("[code, 1 lines]", text)
        self.assertIn("**If stuck:**\n- read the tool docs.", text)
        self.assertNotIn("This prose explains", text)
        self.assertIn("Run: `npm test`\nExpected: PASS", text)
        bare, _ = pt._render_skeleton(SYNTHETIC, code_mode="none")
        self.assertIn("[code ts, 6 lines]", bare)

    def test_headings_between_tasks_stay(self):
        with open(os.path.join(HERE, "fixtures", "tricky-impl.md"), encoding="utf-8") as fh:
            text, _ = pt._render_skeleton(fh.read())
        for heading in ("## Phase 1: Основа", "### Notes", "## Phase 2: Проверка", "#### Task 3: Вложенная задача",
                        "## Итог"):
            self.assertIn(heading, text)
        self.assertNotIn("Подзаголовок уровня задачи", text)

    def test_skeleton_of_a_large_plan_is_small(self):
        task = SYNTHETIC[SYNTHETIC.index("### Task 1:"):]
        code = "\n".join(f"    value_{i} = compute({i})" for i in range(30))
        task = task.replace("  return 0;\n", "  return 0;\n" + code + "\n")
        plan = SYNTHETIC[:SYNTHETIC.index("### Task 1:")] + "\n".join(
            task.replace("### Task 1:", f"### Task {n}:") for n in range(1, 41))
        text, _ = pt._render_skeleton(plan)
        self.assertEqual(text.count("### Task "), 40)
        self.assertLessEqual(len(text.encode("utf-8")), 0.6 * len(plan.encode("utf-8")))


def _run_text(*args):
    """plan_tool.py as a subprocess: (exit code, stdout bytes, stderr text)."""
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    proc = subprocess.run([sys.executable, TOOL, *args], capture_output=True, env=env)
    return proc.returncode, proc.stdout, proc.stderr.decode("utf-8")


class SkeletonCliTest(unittest.TestCase):
    def test_skeleton_and_task_cli(self):
        code, out, err = _run_text("skeleton", FIXTURE)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out.decode("utf-8"), pt._render_skeleton(VALID)[0])
        code, out, _ = _run_text("skeleton", FIXTURE, "--tasks", "1.1", "--code", "none")
        self.assertEqual(code, 0)
        self.assertIn(b"### Task 1.1:", out)
        with open(FIXTURE, "rb") as fh:
            raw = fh.read()
        code, out, _ = _run_text("task", FIXTURE, "1.1")
        self.assertEqual((code, out), (0, b"".join(raw.splitlines(keepends=True)[55:73])))

    def test_cli_errors(self):
        for args, needle in ((("skeleton", FIXTURE, "--tasks", "1,42"), "task-not-found: 42"),
                             (("task", FIXTURE, "42"), "task-not-found: 42"),
                             (("skeleton", os.path.join(HERE, "missing-impl.md")), "plan-unreadable"),
                             (("skeleton", FIXTURE, "--code", "x"), "invalid choice")):
            code, out, err = _run_text(*args)
            self.assertEqual((code, out), (2, b""), args)
            self.assertIn(needle, err, args)

    def test_cli_warnings_go_to_stderr(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "notes-impl.md")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("# Notes\n\nplain text\n")
            code, out, err = _run_text("skeleton", path)
        self.assertEqual((code, out), (0, b"# Notes\n\nplain text\n"))
        self.assertIn("warning: no-tasks", err)


if __name__ == "__main__":
    unittest.main()
