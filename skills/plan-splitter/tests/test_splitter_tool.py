"""Tests for splitter_tool.py granularity_warning.

Uses unittest (stdlib) so no external dependencies are needed.
Run: python -m unittest discover -s plan-splitter/tests -v
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest


SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "scripts")
TOOL = os.path.abspath(os.path.join(SCRIPTS, "splitter_tool.py"))


def _load_module():
    spec = importlib.util.spec_from_file_location("splitter_tool", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

SMALL_STAGE = """# Стадия 01: Малая

> Источник: x | Roadmap: y | Зависит от: — | Блокирует: — | Вес: 🟢

## Цель
Сделать малое.

## Входные данные
Оригинальный план.

## Задачи
1. Первая задача.
2. Вторая задача.
3. Третья задача.

## Критерии завершения
- [ ] Готово.

## Выходные данные (handoff)
Артефакт A.

## Примечания
Нет.
"""


def _big_stage(n_tasks: int) -> str:
    tasks = "\n".join(f"{i}. Задача номер {i}." for i in range(1, n_tasks + 1))
    return SMALL_STAGE.replace(
        "## Задачи\n1. Первая задача.\n2. Вторая задача.\n3. Третья задача.",
        "## Задачи\n" + tasks,
    )


def _run_validate_stage(text: str) -> dict:
    with tempfile.NamedTemporaryFile(
        "w", suffix=".md", delete=False, encoding="utf-8"
    ) as f:
        f.write(text)
        path = f.name
    try:
        proc = subprocess.run(
            [sys.executable, TOOL, "validate-stage", path],
            capture_output=True, text=True,
        )
        return json.loads(proc.stdout)
    finally:
        os.unlink(path)


class TestGranularityWarning(unittest.TestCase):
    def test_absent_for_small_stage(self):
        result = _run_validate_stage(SMALL_STAGE)
        self.assertIsNone(result["granularity_warning"])

    def test_present_for_large_stage(self):
        result = _run_validate_stage(_big_stage(16))
        self.assertIsInstance(result["granularity_warning"], str)
        self.assertIn("16", result["granularity_warning"])


class TestCountTasksInOriginal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_module()

    def test_task_headings_counted(self):
        text = (
            "# Plan\n\n"
            "### Task 1: do a thing\n\nDetails.\n\n"
            "### Task 2: do another thing\n\nDetails.\n"
        )
        self.assertEqual(self.mod.count_tasks_in_original(text), 2)

    def test_numbered_items_counted(self):
        text = "# Plan\n\n" + "\n".join(
            f"{i}. Step {i}." for i in range(1, 6)
        ) + "\n"
        self.assertEqual(self.mod.count_tasks_in_original(text), 5)

    def test_headings_win_over_nested_steps(self):
        # Task headings are the unit; numbered steps inside them are not tasks.
        text = (
            "# Plan\n\n"
            "### Задача 1: первая\n\n"
            "1. шаг\n2. шаг\n3. шаг\n\n"
            "### Task 2 — вторая\n\n"
            "4. шаг\n5. шаг\n6. шаг\n"
        )
        self.assertEqual(self.mod.count_tasks_in_original(text), 2)

    def test_numbered_items_in_fences_and_indented_are_ignored(self):
        text = "# Plan\n\n1. Step one\n   1. nested\n```\n1. code\n2. code\n```\n2. Step two\n"
        self.assertEqual(self.mod.count_tasks_in_original(text), 2)


class TestPartIds(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_module()

    def test_bijective_base26(self):
        self.assertEqual([self.mod.part_id(n) for n in (1, 2, 26, 27, 28, 52, 53)],
                         ["a", "b", "z", "aa", "ab", "az", "ba"])

    def test_stage_filename_accepts_ordinal_and_id(self):
        self.assertEqual(self.mod.stage_filename("plan", 3), "plan-c.md")
        self.assertEqual(self.mod.stage_filename("plan", "C"), "plan-c.md")
        with self.assertRaises(ValueError):
            self.mod.stage_filename("plan", "stg01")

    def test_roadmap_table_normalizes_case_and_separators(self):
        text = (
            "| Stage | Title | Depends on | Parallel group | Weight |\n"
            "|---|---|---|---|---|\n"
            "| A | First | — | A | 🟢 light |\n"
            "| b | Second | A c | B | 🟡 medium |\n"
            "| stg03 | Old | a | B | 🟡 medium |\n"
        )
        rows = self.mod.parse_roadmap_table(text)
        self.assertEqual([r["id"] for r in rows], ["a", "b", "stg03"])
        self.assertEqual(rows[1]["depends"], "a,c")
        self.assertIn("invalid stage id", rows[2]["error"])

    def test_preflight_lists_all_split_artifacts(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ("plan.md", "plan-roadmap.md", "plan-a.md", "plan-a-review-1.md",
                         "plan-b-completion.md", "plan-verify-ledger.json", "plan-impl.md", "other-a.md"):
                with open(os.path.join(d, name), "w", encoding="utf-8") as f:
                    f.write("x")
            proc = subprocess.run([sys.executable, TOOL, "preflight", d, "plan"], capture_output=True, text=True)
            data = json.loads(proc.stdout)
            self.assertEqual(data["existing"], ["plan-a-review-1.md", "plan-a.md", "plan-b-completion.md",
                                                "plan-roadmap.md", "plan-verify-ledger.json"])

    def test_json_output_is_ascii_safe(self):
        proc = subprocess.run([sys.executable, TOOL, "detect-lang", TOOL], capture_output=True, text=True,
                              encoding="ascii", errors="strict")
        self.assertEqual(proc.returncode, 0)
        self.assertIn('"lang"', proc.stdout)


if __name__ == "__main__":
    unittest.main()