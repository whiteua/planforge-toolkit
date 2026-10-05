"""Tests for splitter_tool.py granularity_warning.

Uses unittest (stdlib) so no external dependencies are needed.
Run: python -m unittest discover -s plan-splitter/tests -v
"""
import importlib.util
import json
import os
import shutil
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

    def test_preflight_refuses_a_plan_still_being_written(self):  # spec 3 of plan-refactoring-02
        with tempfile.TemporaryDirectory() as d:
            plan = os.path.join(d, "plan-impl.md")
            with open(plan, "w", encoding="utf-8") as f:
                f.write("# P\n\n### Task 1: A\n\n> Writing: in progress (spec sha256 0123456789ab)\n")
            proc = subprocess.run([sys.executable, TOOL, "preflight", d, "plan-impl"], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 1, proc.stdout)
            self.assertTrue(json.loads(proc.stdout)["error"].startswith("plan-incomplete: "), proc.stdout)
            with open(plan, "w", encoding="utf-8") as f:
                f.write("# P\n\n### Task 1: A\n")
            proc = subprocess.run([sys.executable, TOOL, "preflight", d, "plan-impl"], capture_output=True, text=True)
            self.assertEqual((proc.returncode, json.loads(proc.stdout).get("error")), (0, None))

    def test_json_output_is_ascii_safe(self):
        proc = subprocess.run([sys.executable, TOOL, "detect-lang", TOOL], capture_output=True, text=True,
                              encoding="ascii", errors="strict")
        self.assertEqual(proc.returncode, 0)
        self.assertIn('"lang"', proc.stdout)


class TestSharedTaskParser(unittest.TestCase):
    FIXTURE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "plan-writing", "tests",
                                           "fixtures", "plan01-impl.md"))

    def test_local_count_matches_on_the_reference_plan(self):
        mod = _load_module()
        with open(self.FIXTURE, encoding="utf-8") as fh:
            text = fh.read()
        shared = mod.count_tasks_in_original(text)
        mod._load_brainstorm_tool = lambda: None
        self.assertEqual((shared, mod.count_tasks_in_original(text)), (3, 3))


FIXTURE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "plan-writing", "tests",
                                       "fixtures", "plan01-impl.md"))


class TestGateFactors(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_module()

    def test_module_is_the_folder_two_levels_deep(self):
        paths = ("skills/plan-splitter/scripts/x.py", "docs/a.md", "README.md", "a\\b\\c\\d.py")
        self.assertEqual([self.mod._module_of(p) for p in paths], ["skills/plan-splitter", "docs", ".", "a/b"])

    def test_dependency_shape(self):
        chain = [{"id": "1", "refs": []}, {"id": "2", "refs": ["1"]}, {"id": "3", "refs": ["2", "9"]}]
        self.assertEqual(self.mod._dependency_shape(chain), "linear")
        self.assertEqual(self.mod._dependency_shape([{"id": "1", "refs": []}, {"id": "2", "refs": []}]), "linear")
        self.assertEqual(self.mod._dependency_shape(chain + [{"id": "4", "refs": ["1"]}]), "groups")

    def test_brainstorm_required(self):
        mod = _load_module()
        self.assertTrue(callable(mod._brainstorm_required().parse_plan_tasks))
        mod._load_brainstorm_tool = lambda: None
        with self.assertRaises(mod.SplitterError) as caught:
            mod._brainstorm_required()
        self.assertEqual((str(caught.exception), caught.exception.code),
                         ("plan-brainstorming not installed alongside", 2))


def _gate_plan(count: int, modules: int, refs: bool = False) -> str:
    """Synthetic contract plan: `count` tasks over `modules` two-level folders; with refs every task after
    the second names Task 1 in its Preconditions (a branch)."""
    tasks = []
    for n in range(1, count + 1):
        pre = "**Preconditions:**\n- Task 1 is done.\n\n" if refs and n > 2 else ""
        tasks.append(f"### Task {n}: t{n}\n\n**Files:**\n- Modify: `m{n % modules}/sub/f{n}.py`\n\n{pre}"
                     "- [ ] **Step 1:** x\n")
    return "# P\n\n**Tier:** Standard\n\n" + "\n".join(tasks)


class TestGateVerdict(unittest.TestCase):
    def setUp(self):
        self.mod = _load_module()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name

    def plan(self, text, name="x-impl.md"):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def test_reference_plan_is_keep(self):
        out = self.mod.gate_verdict(FIXTURE)
        self.assertEqual(out["verdict"], "keep")
        self.assertEqual((out["factors"]["task_count"], out["factors"]["modules"], out["factors"]["dependency_shape"]),
                         (3, 2, "linear"))
        self.assertEqual(out["thresholds"], self.mod.GATE_THRESHOLDS)
        self.assertEqual(out["reasons"][0], "task_count 3 <= 20")

    def test_split_and_borderline(self):
        verdict = lambda text: self.mod.gate_verdict(self.plan(text))["verdict"]
        self.assertEqual(verdict(_gate_plan(45, 4)), "split")
        self.assertEqual(verdict(_gate_plan(30, 2)), "borderline")
        self.assertEqual(verdict(_gate_plan(45, 2)), "borderline")
        self.assertEqual(verdict(_gate_plan(45, 2, refs=True)), "split")

    def test_silent_verdict(self):  # spec plan-refactoring-03: a run without a confirmation channel
        silent = lambda text: self.mod.gate_verdict(self.plan(text))["silent_verdict"]
        self.assertEqual(self.mod.gate_verdict(FIXTURE)["silent_verdict"], "keep")
        self.assertEqual(silent(_gate_plan(45, 4)), "split")
        self.assertEqual(silent(_gate_plan(30, 2)), "keep")
        self.assertEqual(silent(_gate_plan(45, 2)), "split")
        self.assertEqual(silent(_gate_plan(30, 2) + "\n" + "x" * 150001 + "\n"), "split")
        self.assertEqual(self.mod.gate_verdict(self.plan(_gate_plan(30, 2)))["verdict"], "borderline")

    def test_thresholds_change_the_verdict(self):
        self.assertEqual(self.mod.gate_verdict(FIXTURE, {"keep_tasks": 2})["verdict"], "borderline")
        split = self.mod.gate_verdict(FIXTURE, {"keep_tasks": 1, "split_tasks": 2, "modules": 1})
        self.assertEqual((split["verdict"], split["thresholds"]["split_tasks"]), ("split", 2))

    def test_errors(self):
        with self.assertRaises(self.mod.SplitterError) as caught:
            self.mod.gate_verdict(self.plan("# Prose\n\n1. step\n"))
        self.assertEqual(caught.exception.code, 1)
        self.assertTrue(str(caught.exception).startswith("no-tasks: "))
        with self.assertRaises(self.mod.SplitterError) as caught:
            self.mod.gate_verdict(os.path.join(self.dir, "missing.md"))
        self.assertEqual(caught.exception.code, 2)
        self.mod._load_brainstorm_tool = lambda: None
        with self.assertRaises(self.mod.SplitterError) as caught:
            self.mod.gate_verdict(FIXTURE)
        self.assertEqual(caught.exception.code, 2)


def _run_tool(*args):
    proc = subprocess.run([sys.executable, TOOL, *args], capture_output=True, text=True)
    return proc.returncode, json.loads(proc.stdout)


class TestGateCli(unittest.TestCase):
    def test_gate_prints_the_verdict(self):
        code, out = _run_tool("gate", FIXTURE)
        self.assertEqual((code, out["ok"], out["verdict"]), (0, True, "keep"))
        code, out = _run_tool("gate", FIXTURE, "--keep-tasks", "2")
        self.assertEqual((code, out["verdict"], out["thresholds"]["keep_tasks"]), (0, "borderline", 2))

    def test_gate_errors_are_json(self):
        with tempfile.TemporaryDirectory() as d:
            prose = os.path.join(d, "p.md")
            with open(prose, "w", encoding="utf-8") as fh:
                fh.write("# Prose\n")
            code, out = _run_tool("gate", prose)
            self.assertEqual((code, out["ok"]), (1, False))
            self.assertTrue(out["errors"][0].startswith("no-tasks: "))
            self.assertEqual(_run_tool("gate", os.path.join(d, "missing.md"))[0], 2)
        self.assertEqual(_run_tool("gate", FIXTURE, "--modules", "x")[0], 2)
        code, out = _run_tool("gate", FIXTURE, "--modules")
        self.assertEqual((code, out["ok"]), (2, False))
        self.assertIn("Missing value for --modules", out["errors"][0])


def _parts(*specs):
    """parts.json entries from (tasks, depends, group) per part; ids a, b, … in order."""
    return [{"id": chr(ord("a") + i), "title": f"P{i}", "depends": list(deps), "group": group,
             "weight": "🟡 medium", "goal": "g", "inputs": "i", "outputs": "o", "notes": "", "tasks": list(tasks)}
            for i, (tasks, deps, group) in enumerate(specs)]


class TestCheckParts(unittest.TestCase):
    TASKS = [{"id": "1", "refs": []}, {"id": "1.1", "refs": ["1"]}, {"id": "2", "refs": []}]

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_module()

    def check(self, parts):
        return self.mod.check_parts(self.TASKS, parts)

    def test_valid_boundaries(self):
        self.assertEqual(self.check(_parts((["1", "1.1"], [], "A"), (["2"], ["a"], "B"))), ([], []))

    def test_task_assignment_errors(self):
        errors, _ = self.check(_parts((["1", "9"], [], "A"), (["1", "2"], ["a"], "B")))
        self.assertEqual(errors, ["tasks-unassigned: 1.1", "tasks-duplicated: 1", "tasks-unknown: 9"])

    def test_part_ids_must_be_sequential(self):
        parts = _parts((["1", "1.1"], [], "A"), (["2"], ["a"], "B"))
        parts[1]["id"] = "c"
        self.assertEqual(self.check(parts)[0][0], "part-ids-not-sequential: a, c (expected a, b)")

    def test_dependency_errors(self):
        cases = [
            (_parts((["1", "1.1"], ["z"], "A"), (["2"], ["a"], "B")), "unknown-dependency: a -> z"),
            (_parts((["1", "1.1"], ["b"], "A"), (["2"], ["a"], "B")), "dependency-cycle: "),
            (_parts((["1", "1.1"], [], "A"), (["2"], ["a"], "A")), "group-conflict: b and a in group A"),
        ]
        for parts, prefix in cases:
            with self.subTest(prefix=prefix):
                errors, _ = self.check(parts)
                self.assertTrue(any(e.startswith(prefix) for e in errors), errors)

    def test_reference_order_and_depends(self):
        errors, _ = self.check(_parts((["1"], [], "A"), (["1.1", "2"], [], "B")))
        self.assertEqual(errors, ["missing-depends: Task 1.1 (b) -> Task 1 (a)"])
        errors, _ = self.check(_parts((["1.1", "2"], [], "A"), (["1"], ["a"], "B")))
        self.assertEqual(errors, ["dependency-order: Task 1.1 (a) -> Task 1 (b)"])
        tasks = self.TASKS + [{"id": "3", "refs": ["1"]}]
        parts = _parts((["1"], [], "A"), (["1.1"], ["a"], "B"), (["2", "3"], ["b"], "C"))
        self.assertEqual(self.mod.check_parts(tasks, parts)[0], [])

    def test_subtask_separated_is_a_warning(self):
        errors, warnings = self.check(_parts((["1"], [], "A"), (["1.1", "2"], ["a"], "B")))
        self.assertEqual((errors, warnings), ([], ["subtask-separated: Task 1.1 (b) and Task 1 (a)"]))


class TestTemplateHelpers(unittest.TestCase):
    def test_items_are_cut_out_and_values_never_rescanned(self):
        mod = _load_module()
        doc, items = mod._split_items("# {{T}}\n\n{{BODY}}\n\n<!-- item:row -->\n| {{ID}} |\n<!-- /item -->\n")
        self.assertEqual((doc, items), ("# {{T}}\n\n{{BODY}}\n", {"row": "| {{ID}} |"}))
        self.assertEqual(mod._fill(doc, {"T": "x", "BODY": "keeps {{T}} as text"}), "# x\n\nkeeps {{T}} as text\n")
        with self.assertRaises(KeyError):
            mod._fill("{{MISSING}}", {})


STAGE_PLACEHOLDERS = {"ID", "TITLE", "BASE_NAME", "DEPENDS_ON_OR_DASH", "BLOCKS_OR_DASH", "WEIGHT", "GOAL",
                      "INPUTS", "PLAN_HEADER", "TASK_LIST", "TASK_BODIES", "CRITERIA", "OUTPUTS", "NOTES"}


class TestSplitTemplates(unittest.TestCase):
    def check(self, name, placeholders, item_names):
        mod = _load_module()
        found = {}
        for lang in ("ru", "en"):
            with self.subTest(name=name, lang=lang):
                doc, items = mod._template(name, lang)
                self.assertEqual(set(mod.PLACEHOLDER_RE.findall(doc)), placeholders)
                self.assertEqual(set(items), item_names)
                found[lang] = {key: set(mod.PLACEHOLDER_RE.findall(value)) for key, value in items.items()}
        self.assertEqual(found["ru"], found["en"])

    def test_stage_template(self):
        self.check("stage-template", STAGE_PLACEHOLDERS, {"task", "criterion", "criterion-empty", "criterion-text"})

    def test_roadmap_template(self):
        self.check("roadmap-template", {"PLAN_TITLE", "BASE_NAME", "ISO8601_UTC", "N", "OVERVIEW", "TABLE_ROWS",
                                        "GROUP_LINES", "MERMAID_EDGES", "STAGE_SECTIONS"}, {"row", "group", "stage"})


def _fixture_pieces(mod):
    with open(FIXTURE, encoding="utf-8") as fh:
        text = fh.read()
    return text, text.splitlines(), mod._load_brainstorm_tool().parse_plan_tasks(text)["tasks"]


class TestPlanPieces(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_module()
        cls.text, cls.lines, cls.tasks = _fixture_pieces(cls.mod)

    def test_task_spans_hash_like_the_parser(self):
        import hashlib
        spans = self.mod._task_spans(self.lines, self.tasks)
        for task in self.tasks:
            digest = hashlib.sha1((spans[task["id"]] + "\n").encode("utf-8")).hexdigest()[:8]
            self.assertEqual(digest, task["sha1"], task["id"])

    def test_header_without_title_and_rule(self):
        header = self.mod._plan_header(self.lines, self.tasks[0]["line_start"])
        self.assertTrue(header.startswith("> **For agentic workers:**"))
        self.assertTrue(header.endswith("**Tech Stack:** Python 3.8 stdlib, unittest."))
        self.assertNotIn("# Verbose Flag", header)

    def test_done_state(self):
        spans = self.mod._task_spans(self.lines, self.tasks)
        self.assertEqual([self.mod._done_state(spans[t["id"]]) for t in self.tasks],
                         ["`python cli.py f --verbose` prints `f` on the first line and the count on the second.; "
                          "Output without `--verbose` is unchanged.",
                          "README shows one `--verbose` example.", "both lines appear as expected."])
        self.assertIsNone(self.mod._done_state("### Task 9: x\n\n- [ ] **Step 1:** y"))

    def test_lines_outside_tasks(self):
        self.assertEqual(self.mod._lines_outside_tasks(self.lines, self.tasks), [])
        lines = self.lines + ["", "## Appendix", "text"]
        self.assertEqual(self.mod._lines_outside_tasks(lines, self.tasks), [f"{len(lines) - 1}-{len(lines)}"])


class TestRenderPart(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_module()
        cls.text, cls.lines, cls.tasks = _fixture_pieces(cls.mod)
        cls.spans = cls.mod._task_spans(cls.lines, cls.tasks)

    def render(self, part):
        return self.mod._render_part("plan01-impl", part, self.tasks[:2], self.spans, "HEADER", ["b"], "en")

    def test_part_holds_the_task_bodies_verbatim(self):
        text = self.render(_parts((["1", "1.1"], [], "A"))[0])
        parsed = self.mod._load_brainstorm_tool().parse_plan_tasks(text)
        self.assertEqual([t["sha1"] for t in parsed["tasks"]], [t["sha1"] for t in self.tasks[:2]])
        self.assertTrue(text.startswith("# Stage a: P0\n\n> Source: [plan01-impl.md](./plan01-impl.md)\n"))
        self.assertIn("> Blocks: b", text)
        self.assertIn("Source plan context (header, verbatim):\n\nHEADER\n", text)
        self.assertIn("1. Task 1: Parse the verbose flag\n2. Task 1.1: Document the flag", text)
        self.assertIn("- [ ] Task 1.1: README shows one `--verbose` example.", text)
        self.assertIn("## Notes\n\n—\n", text)

    def test_criteria_from_parts_json_replace_the_done_states(self):
        part = dict(_parts((["1", "1.1"], [], "A"))[0], criteria=["all green"])
        self.assertIn("## Completion criteria\n\n- [ ] all green\n\n## Outputs", self.render(part))


class TestRenderSplit(unittest.TestCase):
    def test_roadmap_and_parts(self):
        mod = _load_module()
        out = mod.render_split(FIXTURE, {"parts": _parts((["1", "1.1"], [], "A"), (["2"], ["a"], "B"))}, "en")
        self.assertEqual([name for name, _ in out["files"]],
                         ["plan01-impl-roadmap.md", "plan01-impl-a.md", "plan01-impl-b.md"])
        roadmap = out["files"][0][1]
        self.assertIn("# Roadmap: Verbose Flag Implementation Plan", roadmap)
        self.assertIn("| a | P0 | — | A | 🟡 medium |\n| b | P1 | a | B | 🟡 medium |", roadmap)
        self.assertIn("    a --> b", roadmap)
        self.assertIn("`cli.py --verbose` prints the input path before the line count.", roadmap)
        self.assertEqual([row["id"] for row in mod.parse_roadmap_table(roadmap)], ["a", "b"])
        self.assertEqual(mod.validate_mermaid_block(roadmap), [])
        self.assertEqual((out["base"], out["parts"], out["warnings"]),
                         ("plan01-impl", [{"id": "a", "tasks": 2}, {"id": "b", "tasks": 1}], []))

    def test_independent_parts_get_plan_edges_and_errors_stop_rendering(self):
        mod = _load_module()
        out = mod.render_split(FIXTURE, {"parts": _parts((["1", "1.1"], [], "A"), (["2"], [], "A"))}, "ru")
        self.assertIn("    plan --> a\n    plan --> b", out["files"][0][1])
        self.assertTrue(out["files"][1][1].startswith("# Стадия a: P0"))
        with self.assertRaises(mod.SplitterError) as caught:
            mod.render_split(FIXTURE, {"parts": _parts((["1"], [], "A"))}, "en")
        self.assertEqual(caught.exception.details["errors"], ["tasks-unassigned: 1.1, 2"])


class TestPartsShape(unittest.TestCase):
    def test_shape_errors_are_input_errors(self):
        mod = _load_module()
        good = {"parts": _parts((["1"], [], "A"))}
        self.assertEqual(mod._parts_shape(good), good["parts"])
        bad = {"parts": _parts((["1"], [], "A|B"))}
        bad["parts"][0]["tasks"] = "1"
        del bad["parts"][0]["goal"]
        with self.assertRaises(mod.SplitterError) as caught:
            mod._parts_shape(bad)
        self.assertEqual(caught.exception.code, 2)
        for fragment in ("parts[0].goal must be a string", "parts[0].tasks must be a list of strings",
                         "parts[0].group must be one non-empty line without '|'"):
            self.assertIn(fragment, str(caught.exception))
        with self.assertRaises(mod.SplitterError):
            mod._parts_shape({"parts": []})
        with self.assertRaises(mod.SplitterError) as caught:
            mod._load_parts(os.path.join(os.path.dirname(TOOL), "missing.json"))
        self.assertEqual(caught.exception.code, 2)


class _SplitDir(unittest.TestCase):
    """A copy of the reference plan in a temp folder; split-write and validate-all run on it."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name
        self.plan = os.path.join(self.dir, "plan01-impl.md")
        shutil.copyfile(FIXTURE, self.plan)

    def split(self, parts, *extra):
        path = os.path.join(self.dir, "parts.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"parts": parts}, fh, ensure_ascii=False)
        return _run_tool("split-write", self.plan, "--parts", path, *extra)

    def written(self):
        return sorted(name for name in os.listdir(self.dir) if name.startswith("plan01-impl-"))

    def edit(self, name, old, new):
        path = os.path.join(self.dir, name)
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text.replace(old, new))


class TestSplitWriteCli(_SplitDir):
    def test_writes_roadmap_and_parts_and_keeps_the_plan(self):
        before = _load_module().sha256_file(self.plan)
        code, out = self.split(_parts((["1", "1.1"], [], "A"), (["2"], ["a"], "B")))
        self.assertEqual((code, out["ok"], out["lang"], out["plan_sha256"]), (0, True, "en", before))
        self.assertEqual(self.written(), ["plan01-impl-a.md", "plan01-impl-b.md", "plan01-impl-roadmap.md"])
        self.assertEqual([(p["id"], p["tasks"]) for p in out["parts"]], [("a", 2), ("b", 1)])
        self.assertEqual(_load_module().sha256_file(self.plan), before)

    def test_exists_without_force_and_overwrite_with_force(self):
        parts = _parts((["1", "1.1"], [], "A"), (["2"], ["a"], "B"))
        self.assertEqual(self.split(parts)[0], 0)
        code, out = self.split(parts)
        self.assertEqual((code, out["errors"][0].split(":")[0]), (1, "exists"))
        self.assertEqual(self.split(parts, "--force")[0], 0)

    def test_boundary_error_writes_nothing(self):
        code, out = self.split(_parts((["1"], [], "A"), (["2", "1.1"], ["a"], "A")))
        self.assertEqual(code, 1)
        self.assertIn("group-conflict: b and a in group A", out["errors"])
        self.assertEqual(self.written(), [])

    def test_lang_switches_the_template(self):
        self.assertEqual(self.split(_parts((["1", "1.1", "2"], [], "A")), "--lang", "ru")[0], 0)
        with open(os.path.join(self.dir, "plan01-impl-a.md"), encoding="utf-8") as fh:
            self.assertTrue(fh.read().startswith("# Стадия a: P0"))

    def test_input_errors_exit_2(self):
        bad = os.path.join(self.dir, "bad.json")
        with open(bad, "w", encoding="utf-8") as fh:
            fh.write("{")
        self.assertEqual(_run_tool("split-write", self.plan, "--parts", bad)[0], 2)
        self.assertEqual(_run_tool("split-write", self.plan)[0], 2)
        self.assertEqual(_run_tool("split-write", self.plan, "--parts")[0], 2)
        self.assertEqual(self.split(_parts((["1", "1.1", "2"], [], "A")), "--lang", "de")[0], 2)


class TestStageCounting(_SplitDir):
    def test_part_counts_each_task_body_once(self):
        mod = _load_module()
        plan = os.path.join(self.dir, "num-impl.md")
        with open(plan, "w", encoding="utf-8") as fh:
            fh.write("# P\n\n**Goal:** g\n\n### Task 1: A\n\n1. first\n2. second\n\n### Task 2: B\n\n- [ ] **Step 1:** x\n")
        part = mod.render_split(plan, {"parts": _parts((["1", "2"], [], "A"))}, "en")["files"][1][1]
        self.assertEqual(mod.count_tasks_in_stage(part), 2)
        self.assertEqual(mod.count_tasks_in_stage(SMALL_STAGE), 3)

    def test_more_tasks_in_the_parts_than_in_the_plan_fails(self):
        self.assertEqual(self.split(_parts((["1", "1.1"], [], "A"), (["2"], ["a"], "B")))[0], 0)
        code, out = _run_tool("validate-all", self.dir, "plan01-impl")
        self.assertEqual((code, out["coverage"]["ok"], out["coverage"]["stage_tasks_total"]), (0, True, 3))
        self.edit("plan01-impl-b.md", "## Completion criteria", "### Task 3: Extra\n\nx\n\n## Completion criteria")
        code, out = _run_tool("validate-all", self.dir, "plan01-impl")
        self.assertEqual((code, out["coverage"]["ok"]), (1, False))
        self.assertIn("Task coverage differs from original: stages have 4 vs original 3", out["errors"])


class TestTaskBodies(_SplitDir):
    def test_split_parts_match_and_a_rephrased_task_fails(self):
        self.assertEqual(self.split(_parts((["1", "1.1"], [], "A"), (["2"], ["a"], "B")))[0], 0)
        code, out = _run_tool("validate-all", self.dir, "plan01-impl")
        self.assertEqual((code, out["task_bodies"]),
                         (0, {"plan": 3, "matched": 3, "missing": [], "duplicated": [], "foreign": []}))
        self.assertEqual(_run_tool("validate-roadmap", os.path.join(self.dir, "plan01-impl-roadmap.md"))[0], 0)
        for part in ("a", "b"):
            self.assertEqual(_run_tool("validate-stage", os.path.join(self.dir, f"plan01-impl-{part}.md"))[0], 0)
        self.edit("plan01-impl-b.md", "both lines appear as expected.", "both lines appear.")
        code, out = _run_tool("validate-all", self.dir, "plan01-impl")
        self.assertEqual((code, out["valid"]), (1, False))
        self.assertEqual((out["task_bodies"]["missing"], out["task_bodies"]["foreign"]), (["2"], ["b: Task 2"]))
        code, out = _run_tool("validate-all", self.dir, "plan01-impl", "--skip-task-bodies")
        self.assertEqual((code, out["task_bodies"]), (0, None))

    def test_validate_all_needs_the_shared_parser(self):
        mod = _load_module()
        mod._load_brainstorm_tool = lambda: None
        with self.assertRaises(mod.SplitterError) as caught:
            mod.cmd_validate_all(self.dir, "plan01-impl")
        self.assertEqual(caught.exception.code, 2)


class TestTaskLines(_SplitDir):
    """**External:**, **Size:** and **Structural event:** lines reach the parts verbatim (spec 1 of plan-refactoring-02)."""

    LINE = "**Structural event:** convention — the rule moves to CLAUDE.md"

    def test_structural_event_line_is_copied_and_checked(self):
        self.edit("plan01-impl.md", "- Modify: `README.md`\n", "- Modify: `CLAUDE.md`\n\n" + self.LINE + "\n")
        self.assertEqual(self.split(_parts((["1", "1.1"], [], "A"), (["2"], ["a"], "B")))[0], 0)
        code, out = _run_tool("validate-all", self.dir, "plan01-impl")
        self.assertEqual((code, out["task_lines"]), (0, {"original": 1, "missing": []}))
        self.edit("plan01-impl-a.md", self.LINE, "**Structural event:** convention — changed")
        code, out = _run_tool("validate-all", self.dir, "plan01-impl", "--skip-task-bodies")
        self.assertEqual(code, 1)
        self.assertIn("Task line not copied verbatim into any part: " + self.LINE, out["errors"])
        fenced = "```\n" + self.LINE + "\n```\n" + self.LINE + "\n"
        self.assertEqual(_load_module().task_property_lines(fenced), [self.LINE])


class TestPaddedTaskIds(_SplitDir):
    def test_parts_json_ids_meet_the_plan_ids_in_any_padding(self):  # F7 of plan-refactoring-02
        mod = _load_module()
        plan = os.path.join(self.dir, "pad-impl.md")
        with open(plan, "w", encoding="utf-8") as fh:
            fh.write("# P\n\n**Goal:** g\n\n### Task 01: A\n\n- [ ] **Step 1:** x\n\n### Task 02: B\n\n- [ ] **Step 1:** y\n")
        result = mod.render_split(plan, {"parts": _parts((["01"], [], "A"), (["2"], ["a"], "B"))}, "en")
        self.assertEqual(result["parts"], [{"id": "a", "tasks": 1}, {"id": "b", "tasks": 1}])


if __name__ == "__main__":
    unittest.main()