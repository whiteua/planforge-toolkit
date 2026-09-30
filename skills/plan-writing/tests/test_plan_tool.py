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
        self.assertEqual(len(result["warnings"]), 2)  # cli.py:4-6 beyond 3 lines; README.md missing
        self.assertTrue(any("beyond end of cli.py" in w for w in result["warnings"]))

    def test_code_size_warning(self):
        big = "\n".join(f"x{i} = {i}" for i in range(120))
        text = VALID.replace('p.add_argument("--verbose", action="store_true")', big)
        result = self.check(text)
        self.assertTrue(result["ok"])
        self.assertTrue(any("100-lines" in w for w in result["warnings"]))

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


if __name__ == "__main__":
    unittest.main()
