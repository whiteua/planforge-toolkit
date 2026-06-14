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

    def test_mixed_takes_max(self):
        # 2 Task headings + 6 numbered items -> max wins (6).
        text = (
            "# Plan\n\n"
            "### Задача 1: первая\n\n"
            "1. шаг\n2. шаг\n3. шаг\n\n"
            "### Задача 2: вторая\n\n"
            "4. шаг\n5. шаг\n6. шаг\n"
        )
        self.assertEqual(self.mod.count_tasks_in_original(text), 6)


if __name__ == "__main__":
    unittest.main()