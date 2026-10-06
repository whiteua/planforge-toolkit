from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "scripts" / "next_review_index.py"

_spec = importlib.util.spec_from_file_location("nri_digest", TOOL)
nri = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(nri)


def review(n: int, fps: dict) -> str:
    lines = [f"# Ревизия {n}: demo", "", f"**Iteration**: {n}", "", "## Issues", ""]
    for index, (_label, (severity, category, fingerprint)) in enumerate(fps.items(), start=1):
        lines += [
            f"### [{n}.{index}] {severity} · {category} · {index}",
            "- **Required fix (contract)**:",
            f"  Fix {index} text",
            f"- **Fingerprint**: {fingerprint}",
            "",
        ]
    return "\n".join(lines)


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(TOOL), *args], text=True, capture_output=True)


class Digest(unittest.TestCase):
    def test_empty_history(self):
        with tempfile.TemporaryDirectory() as d:
            p = run("digest", d, "demo")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout), {"iteration": 1, "active_contracts": [], "resolved_contracts": []})

    def test_active_and_resolved_split(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "demo-review-1.md").write_text(
                review(1, {"x": ("blocker", "logic", "aaaa1111"), "y": ("minor", "tests", "bbbb2222")}),
                encoding="utf-8",
            )
            Path(d, "demo-review-2.md").write_text(
                review(2, {"x": ("blocker", "logic", "aaaa1111")}),
                encoding="utf-8",
            )
            p = run("digest", d, "demo")
        out = json.loads(p.stdout)
        self.assertEqual(out["iteration"], 3)
        self.assertEqual([c["fingerprint"] for c in out["active_contracts"]], ["aaaa1111"])
        self.assertEqual(out["active_contracts"][0]["status"], "Open")
        self.assertEqual(out["active_contracts"][0]["severity"], "blocker")
        self.assertEqual(out["active_contracts"][0]["fix"], "Fix 1 text")
        self.assertEqual([c["fingerprint"] for c in out["resolved_contracts"]], ["bbbb2222"])
        self.assertEqual(out["resolved_contracts"][0]["status"], "Fixed")
        self.assertEqual(out["resolved_contracts"][0]["severity"], "minor")
        self.assertEqual(out["resolved_contracts"][0]["fix"], "Fix 2 text")


class TaskScopeUnits(unittest.TestCase):
    def test_contract_tasks(self):
        self.assertEqual(nri.contract_tasks("Task 3, Step 2"), ["3"])
        self.assertEqual(nri.contract_tasks("### Task 12: x / Task 7.1; Задача 4; Task 12"), ["12", "7.1", "4"])
        self.assertEqual(nri.contract_tasks("## 3. Data model"), [])

    def test_review_issue_keeps_the_fields_of_a_carry(self):
        text = ("### [1.1] minor · logic · T\n\n- **Location in plan**: Task 2, Step 1\n- **Location in code**: a.py:3\n"
                "- **Code cross-check**: verified — ok\n- **Problem**:\n  Broken step\n- **Required fix (contract)**:\n"
                "  Fix it\n- **Acceptance**:\n  Fixed\n- **Fingerprint**: aaaa1111\n")
        issue = nri.parse_review_issues(text)[0]
        self.assertEqual((issue["problem"], issue["code_cross_check"], issue["location_in_code"]),
                         ("Broken step", "verified — ok", "a.py:3"))


def task_plan(n: int = 10, refs: dict = None, edits: dict = None, goal: str = "demo") -> str:
    """A plan of N tasks. REFS: {task: [tasks its Preconditions name]}; EDITS: {task: other step text}."""
    blocks = [f"# Demo plan\n\n**Goal:** {goal}.\n"]
    for number in range(1, n + 1):
        block = [f"### Task {number}: Title {number}", ""]
        if refs and number in refs:
            block += ["**Preconditions:**"] + [f"- Task {ref} is done" for ref in refs[number]] + [""]
        block += [f"- [ ] **Step 1: {(edits or {}).get(number, f'do {number}')}**", ""]
        blocks.append("\n".join(block))
    return "\n".join(blocks)


class TaskDigestTable(unittest.TestCase):
    def test_parse_task_digest(self):
        table = ("## Notes for implementation\n\nnone\n\n## Task digest\n\n| Task | Hash |\n|---|---|\n"
                 "| 1 | 9f3c2a1b |\n| 1.1 | 0E77AD21 |\n")
        self.assertEqual(nri.parse_task_digest(table), {"tasks": {"1": "9f3c2a1b", "1.1": "0e77ad21"}, "malformed": []})
        self.assertEqual(nri.parse_task_digest(table + "| 2 | zz |\n")["malformed"], ["| 2 | zz |"])
        self.assertIsNone(nri.parse_task_digest("- **Problem**:\n  ## Task digest\n"))
        self.assertEqual(nri.parse_task_digest("## Task digest\n\n")["malformed"], ["(no rows)"])

    def test_dependents_closure_is_transitive_and_ends_on_a_cycle(self):
        tasks = [{"id": "3", "refs": []}, {"id": "4", "refs": ["3", "9"]}, {"id": "5", "refs": []},
                 {"id": "9", "refs": ["4"]}]
        self.assertEqual(nri.dependents_closure(["3"], tasks), ["4", "9"])
        self.assertEqual(nri.dependents_closure(["5"], tasks), [])

    def test_plan_task_index(self):
        tasks, reason = nri.plan_task_index(task_plan(n=2, refs={2: [1]}))
        self.assertEqual(([task["id"] for task in tasks], tasks[1]["refs"], reason), (["1", "2"], ["1"], None))
        self.assertEqual(nri.plan_task_index("# Plan\n\nNo tasks.\n"), (None, "no-tasks"))
        self.assertEqual(nri.plan_task_index(task_plan(n=1) + "\n### Task 1: Again\n"), (None, "duplicate-task-ids"))
        with mock.patch.object(nri, "_load_brainstorm_tool", return_value=None):
            self.assertEqual(nri.plan_task_index(task_plan(n=1)), (None, "task-parser-unavailable"))

    def test_zero_padded_ids_and_their_references(self):  # F7 of plan-refactoring-02
        plan = ("# P\n\n### Task 01: A\n\n- [ ] **Step 1: a**\n\n### Task 2: B\n\n**Preconditions:**\n"
                "- Task 1 is done\n\n- [ ] **Step 1: b**\n")
        tasks, reason = nri.plan_task_index(plan)
        self.assertEqual(([task["id"] for task in tasks], reason), (["1", "2"], None))
        self.assertEqual(nri.dependents_closure(["1"], tasks), ["2"])
        self.assertEqual(nri.contract_tasks("Task 01, Step 2; Задача 3.01"), ["1", "3.1"])
        self.assertEqual([nri.normalize_task_id(v) for v in ("01.02", "007", "A1")], ["1.2", "7", "A1"])
        table = "## Task digest\n\n| Task | Hash |\n|---|---|\n| 01 | 9f3c2a1b |\n| 1 | 0e77ad21 |\n"
        self.assertEqual(nri.parse_task_digest(table), {"tasks": {"1": "9f3c2a1b"}, "malformed": ["| 1 | 0e77ad21 |"]})


def plan_issue(fix: str, location: str) -> dict:
    return {"severity": "major", "category": "logic", "title": f"Title {fix}", "location_in_plan": location,
            "code_cross_check": "verified - checked", "problem": f"Problem {fix}", "required_fix": fix,
            "acceptance": f"Plan has {fix}"}


class TaskPlanCase(unittest.TestCase):
    """A 10-task plan (Task 4 needs Task 3, Task 9 needs Task 4) and its first review, written by record."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.plan = self.dir / "demo.md"
        self.refs = {4: [3], 9: [4]}
        self.plan.write_text(task_plan(refs=self.refs), encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def first_review(self, location: str = "Task 7, Step 1") -> Path:
        payload = json.dumps({"summary": "S.", "issues": [plan_issue("Fix A", location)]})
        p = subprocess.run([sys.executable, str(TOOL), "record", str(self.plan), "--run-start", "1", "--max", "5",
                            "--issues", "-"], text=True, capture_output=True, input=payload, encoding="utf-8")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return Path(json.loads(p.stdout)["review_path"])

    def scope(self, review: Path) -> dict:
        text = review.read_text(encoding="utf-8")
        sha = hashlib.sha256(self.plan.read_bytes()).hexdigest()
        return nri.task_scope(self.plan.read_text(encoding="utf-8"), sha, text, nri.parse_review_issues(text))


class TaskScope(TaskPlanCase):
    def test_incremental_with_transitive_dependents(self):
        review = self.first_review()
        self.plan.write_text(task_plan(refs=self.refs, edits={3: "changed"}), encoding="utf-8")
        td = self.scope(review)
        self.assertEqual((td["available"], td["plan_sha_changed"], td["scope"]), (True, True, "incremental"))
        self.assertEqual((td["changed"], td["new"], td["removed"]), (["3"], [], []))
        self.assertEqual((td["focus"], td["dependents"], td["tasks"]), (["7"], ["4", "9"], ["3", "4", "7", "9"]))
        self.assertEqual(sorted(td["line_ranges"]), ["3", "4", "7", "9", "header"])
        self.assertEqual(td["line_ranges"]["header"], [1, 4])
        lines = self.plan.read_text(encoding="utf-8").splitlines()
        self.assertTrue(lines[td["line_ranges"]["3"][0] - 1].startswith("### Task 3:"))

    def test_same_plan_is_none_changed(self):
        td = self.scope(self.first_review())
        self.assertEqual((td["scope"], td["plan_sha_changed"], td["changed"], td["tasks"]),
                         ("none-changed", False, [], ["7"]))

    def test_header_only_edit_is_incremental_over_header_and_focus(self):
        review = self.first_review()
        self.plan.write_text(task_plan(refs=self.refs, goal="demo, edited"), encoding="utf-8")
        td = self.scope(review)
        self.assertEqual((td["scope"], td["plan_sha_changed"], td["changed"], td["tasks"]),
                         ("incremental", True, [], ["7"]))
        self.assertIn("header", td["line_ranges"])

    def test_without_a_table_or_with_a_broken_one_the_audit_is_full(self):
        review = self.first_review()
        self.plan.write_text(task_plan(refs=self.refs, edits={3: "changed"}), encoding="utf-8")
        text = review.read_text(encoding="utf-8")
        row = next(line for line in text.splitlines() if line.startswith("| 1 |"))
        review.write_text(text.replace(row, "| 1 | zz |"), encoding="utf-8")
        td = self.scope(review)
        self.assertEqual((td["scope"], td["reason"], td["warnings"]),
                         ("full", "task-digest-malformed", ["task-digest-malformed"]))
        review.write_text(text.split("## Task digest")[0], encoding="utf-8")
        self.assertEqual((self.scope(review)["scope"], self.scope(review)["reason"]), ("full", "no-task-digest"))


class TaskDigest(TaskPlanCase):
    """`digest` returns task_scope as `task_digest`, for the plan named by `**Audited plan**`."""

    def digest(self) -> dict:
        p = run("digest", str(self.dir), "demo", "--since", "1")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return json.loads(p.stdout)["task_digest"]

    def test_new_and_removed_tasks(self):
        self.first_review()
        self.plan.write_text(task_plan(n=11, refs=self.refs), encoding="utf-8")
        td = self.digest()
        self.assertEqual((td["new"], td["tasks"], td["scope"]), (["11"], ["7", "11"], "incremental"))
        self.plan.write_text(task_plan(n=9, refs=self.refs), encoding="utf-8")
        td = self.digest()
        self.assertEqual((td["removed"], td["tasks"], td["scope"]), (["10"], ["7"], "incremental"))

    def test_plan_path_comes_from_audited_plan(self):
        review = self.first_review()
        text = review.read_text(encoding="utf-8")
        review.write_text(text.replace("**Audited plan**: demo.md", "**Audited plan**: other.md"), encoding="utf-8")
        td = self.digest()
        self.assertEqual((td["available"], td["scope"], td["reason"]), (False, "full", "plan-not-found"))

    def test_audited_plan_header_is_cut_to_a_basename(self):
        review = self.first_review()
        outside = self.dir.parent / f"outside-{self.dir.name}.md"  # a plan outside the review directory
        outside.write_text(task_plan(refs=self.refs), encoding="utf-8")
        self.addCleanup(outside.unlink)
        text = review.read_text(encoding="utf-8")
        review.write_text(text.replace("**Audited plan**: demo.md", f"**Audited plan**: ../{outside.name}"),
                          encoding="utf-8")
        td = self.digest()
        self.assertEqual((td["available"], td["scope"], td["reason"]), (False, "full", "plan-not-found"))

    def test_referrer_of_a_removed_task_is_a_dependent(self):
        self.refs = {4: [3], 9: [10]}  # Task 9 names Task 10, which the next plan loses
        self.plan.write_text(task_plan(refs=self.refs), encoding="utf-8")
        self.first_review()
        self.plan.write_text(task_plan(n=9, refs=self.refs), encoding="utf-8")
        td = self.digest()
        self.assertEqual((td["removed"], td["changed"], td["dependents"], td["tasks"]), (["10"], [], ["9"], ["7", "9"]))

    def test_without_plan_brainstorming(self):
        self.first_review()
        out = io.StringIO()
        with mock.patch.object(nri, "_load_brainstorm_tool", return_value=None), contextlib.redirect_stdout(out):
            self.assertEqual(nri.cmd_digest(str(self.dir), "demo", 1), 0)
        td = json.loads(out.getvalue())["task_digest"]
        self.assertEqual((td["available"], td["scope"], td["reason"]), (False, "full", "task-parser-unavailable"))


class TaskScopeVerdicts(TaskPlanCase):
    """changed_ratio and contracts without a task id turn the scope to full."""

    def test_changed_ratio_counts_dependents_and_removed(self):
        review = self.first_review()
        self.plan.write_text(task_plan(refs=self.refs, edits={3: "changed"}), encoding="utf-8")
        self.assertEqual(self.scope(review)["changed_ratio"], 0.3)
        self.plan.write_text(task_plan(n=9, refs=self.refs), encoding="utf-8")
        self.assertEqual(self.scope(review)["changed_ratio"], 0.1)

    def test_more_than_half_changed_is_full(self):
        review = self.first_review()
        self.plan.write_text(task_plan(refs=self.refs, edits={n: "changed" for n in range(1, 7)}), encoding="utf-8")
        td = self.scope(review)
        self.assertEqual((td["scope"], td["reason"], td["changed_ratio"]), ("full", "changed-ratio", 0.7))

    def test_contract_without_task_forces_full(self):
        review = self.first_review(location="## 3. Data model")
        self.plan.write_text(task_plan(refs=self.refs, edits={3: "changed"}), encoding="utf-8")
        td = self.scope(review)
        self.assertEqual((td["scope"], td["reason"], td["focus"]), ("full", "contract-without-task", []))

    def test_unknown_task_id_forces_full(self):
        review = self.first_review(location="Task 77")
        self.plan.write_text(task_plan(refs=self.refs, edits={3: "changed"}), encoding="utf-8")
        self.assertEqual(self.scope(review)["reason"], "contract-without-task")


class CodeDigestUnits(unittest.TestCase):
    """Spec 1 of plan-refactoring-04: the states of the `## Code digest` table and what counts as a change."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "src" / "pkg.d").mkdir(parents=True)
        (self.root / "src" / "a.py").write_text("a = 1\n", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_states(self):
        root = str(self.root)
        sha = hashlib.sha256((self.root / "src" / "a.py").read_bytes()).hexdigest()[:12]
        paths = ("src/a.py", "src/pkg.d", "src/*.py", "../x.py", "/abs/x.py", "src/gone.py")
        self.assertEqual([nri.code_state(root, path) for path in paths],
                         [sha, "dir", "glob", "outside", "outside", "missing"])
        with mock.patch.object(nri, "file_sha256_or_none", side_effect=OSError("denied")):
            self.assertEqual(nri.code_state(root, "src/a.py"), "unreadable")

    def test_table_round_trip_and_changes(self):
        tasks = [{"id": "1", "files": [{"path": "src/a.py"}]},
                 {"id": "2", "files": [{"path": "src/gone.py"}, {"path": "src/a.py"}]},
                 {"id": "3", "files": [{"path": "src/pkg.d"}, {"path": "src/*.py"}]}]
        rows = nri.code_digest_rows(tasks, str(self.root))
        self.assertEqual([path for path, _ in rows], ["src/a.py", "src/gone.py", "src/pkg.d", "src/*.py"])
        table = nri.parse_code_digest("## Code digest\n\n| Path | Hash |\n|---|---|\n"
                                      + "".join(f"| {path} | {state} |\n" for path, state in rows))
        self.assertEqual(table, dict(rows))
        self.assertEqual(nri.code_changed_tasks(tasks, table, str(self.root)), [])
        (self.root / "src" / "gone.py").write_text("now here\n", encoding="utf-8")  # missing → a file
        self.assertEqual(nri.code_changed_tasks(tasks, table, str(self.root)), ["2"])
        (self.root / "src" / "a.py").write_text("a = 2\n", encoding="utf-8")
        self.assertEqual(nri.code_changed_tasks(tasks, table, str(self.root)), ["1", "2"])
        self.assertIsNone(nri.parse_code_digest("## Task digest\n\n| Task | Hash |\n"))

    def test_code_root_without_git_is_the_current_directory(self):
        self.assertEqual(nri.code_root(str(self.root)), (str(Path.cwd()), ["code-root-cwd"]))


class CodeScope(unittest.TestCase):
    """Spec 1 of plan-refactoring-04: a file changed between passes puts its tasks and their dependents in scope.
    Ten tasks: Task 1 names src/a.py, Task 2 src/b.py (missing at first), the rest src/c.py; Task 4 needs Task 1."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        (self.dir / "src").mkdir()
        for name in ("a", "c"):
            (self.dir / "src" / f"{name}.py").write_text(f"{name} = 1\n", encoding="utf-8")
        blocks = ["# Demo plan\n"]
        for number in range(1, 11):
            name = {1: "a", 2: "b"}.get(number, "c")
            block = [f"### Task {number}: Title {number}", "", "**Files:**", f"- Modify: `src/{name}.py`", ""]
            block += ["**Preconditions:**", "- Task 1 is done", ""] if number == 4 else []
            blocks.append("\n".join(block + [f"- [ ] **Step 1: do {number}**", ""]))
        self.plan = self.dir / "demo.md"
        self.plan.write_text("\n".join(blocks), encoding="utf-8")
        payload = json.dumps({"summary": "S.", "issues": [plan_issue("Fix A", "Task 7, Step 1")]})
        p = subprocess.run([sys.executable, str(TOOL), "record", str(self.plan), "--run-start", "1", "--max", "5",
                            "--issues", "-"], text=True, capture_output=True, input=payload, encoding="utf-8",
                           cwd=str(self.dir))  # outside git the current directory is the root of the Files paths
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.review = Path(json.loads(p.stdout)["review_path"])

    def tearDown(self):
        self._tmp.cleanup()

    def scope(self):
        text = self.review.read_text(encoding="utf-8")
        sha = hashlib.sha256(self.plan.read_bytes()).hexdigest()
        return nri.task_scope(self.plan.read_text(encoding="utf-8"), sha, text, nri.parse_review_issues(text),
                              str(self.dir))

    def test_same_code_and_plan_is_none_changed(self):
        td = self.scope()
        self.assertEqual((td["scope"], td["code_changed"], td["warnings"]), ("none-changed", [], []))

    def test_changed_file_brings_its_task_and_dependents(self):
        (self.dir / "src" / "a.py").write_text("a = 2\n", encoding="utf-8")
        td = self.scope()
        self.assertEqual((td["scope"], td["plan_sha_changed"], td["code_changed"]), ("incremental", False, ["1"]))
        self.assertEqual((td["dependents"], td["tasks"], td["changed_ratio"]), (["4"], ["1", "4", "7"], 0.2))

    def test_missing_file_appearing_is_a_change(self):
        (self.dir / "src" / "b.py").write_text("b = 1\n", encoding="utf-8")
        self.assertEqual(self.scope()["code_changed"], ["2"])

    def test_more_than_half_of_the_tasks_is_full(self):
        (self.dir / "src" / "c.py").write_text("c = 2\n", encoding="utf-8")
        td = self.scope()
        self.assertEqual((td["scope"], td["reason"]), ("full", "changed-ratio"))

    def test_review_without_the_table(self):
        self.review.write_text(self.review.read_text(encoding="utf-8").split("## Code digest")[0], encoding="utf-8")
        (self.dir / "src" / "a.py").write_text("a = 2\n", encoding="utf-8")
        td = self.scope()
        self.assertEqual((td["scope"], td["code_changed"], td["warnings"]), ("none-changed", [], ["no-code-digest"]))

    def test_digest_outside_git_reads_from_the_current_directory(self):
        (self.dir / "src" / "a.py").write_text("a = 2\n", encoding="utf-8")
        p = subprocess.run([sys.executable, str(TOOL), "digest", str(self.dir), "demo", "--since", "1"], text=True,
                           capture_output=True, cwd=str(self.dir))
        td = json.loads(p.stdout)["task_digest"]
        self.assertEqual((td["code_changed"], td["warnings"]), (["1"], ["code-root-cwd"]))
