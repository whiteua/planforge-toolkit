import importlib.util
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "scripts" / "executor_tool.py"
PLAN = "# P\n\n### Task 1: A\n\n- [ ] **Step 1: edit**\n\n### Task 2: B\n\n- [ ] **Step 1: edit**\n"


def load_tool():
    spec = importlib.util.spec_from_file_location("executor_tool", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_cli(*args):
    result = subprocess.run([sys.executable, str(TOOL_PATH), *args], capture_output=True, text=True,
                            encoding="utf-8")
    return result.returncode, json.loads(result.stdout)


class RunDiffCase(unittest.TestCase):
    def setUp(self):
        self.tool = load_tool()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.repo = self.base / "repo"
        self.repo.mkdir()
        self.exec_dir = str(self.base / "exec")

    def git(self, *args):
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=str(self.repo),
                              capture_output=True, text=True, encoding="utf-8", check=True).stdout

    def write(self, rel, content):
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
        return path

    def init_repo(self, files):
        self.git("init", "-q")
        for rel, content in files.items():
            self.write(rel, content)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")

    def start(self, plan_rel="docs/plans/p1-impl.md", plan_text=PLAN):
        """Write (and in git, commit) the plan, then ledger-init with the repo as workdir."""
        plan = self.write(plan_rel, plan_text)
        if (self.repo / ".git").exists():
            self.git("add", "-A")
            self.git("commit", "-q", "-m", "plan")
        self.tool.cmd_ledger_init(types.SimpleNamespace(
            plan_path=str(plan), exec_dir=self.exec_dir, whole=False, workdir=str(self.repo),
            allow_dirty=False, accept_drift=False, allow_temp=False))
        return plan

    def unit(self, unit_id, files):
        """One unit of the run: begin, write `files` (None deletes the file), finish pass."""
        self.tool.unit_begin(self.exec_dir)
        for rel, content in files.items():
            if content is None:
                (self.repo / rel).unlink()
            else:
                self.write(rel, content)
        return self.tool.unit_finish(self.exec_dir, unit_id, "pass")


class TestRunDiffNoGit(RunDiffCase):
    def test_no_git_is_exit_1_and_distinct_from_unavailable(self):
        self.write("app.py", "x = 1\n")
        self.start(plan_rel="p1-impl.md")
        self.unit("task-1", {"app.py": "x = 2\n"})
        with self.assertRaises(ValueError) as ctx:
            self.tool.run_diff(self.exec_dir)
        self.assertTrue(str(ctx.exception).startswith("no-git:"), str(ctx.exception))
        self.assertEqual(ctx.exception.code, 1)
        code, out = run_cli("run-diff", self.exec_dir)
        self.assertEqual(code, 1)
        self.assertTrue(out["errors"][0].startswith("no-git:"), out)


class TestPipelineArtifact(unittest.TestCase):
    def setUp(self):
        self.tool = load_tool()

    def test_chain_artifacts_anywhere_and_root_backlog(self):
        for rel in ("g-spec.md", "a/b/g-spec.md", "g-impl.md", "x/g-impl-a.md", "g-impl-roadmap.md",
                    "g-impl-review-3.md", "g-impl-report-2-final.md", "g-chain.json", "g-diffs.md",
                    "g-followups.json", "BACKLOG.md"):
            self.assertTrue(self.tool._is_pipeline_artifact(rel, None), rel)

    def test_regular_files_are_kept(self):
        for rel in ("src/app.py", "sub/BACKLOG.md", "docs/spec.md", "README.md", "g-chain.json.bak",
                    "docs/plans2/x.py"):
            self.assertFalse(self.tool._is_pipeline_artifact(rel, "docs/plans"), rel)

    def test_plan_directory_unless_it_is_the_root(self):
        self.assertTrue(self.tool._is_pipeline_artifact("docs/plans/notes.txt", "docs/plans"))
        self.assertTrue(self.tool._is_pipeline_artifact("docs\\plans\\deep\\x.py", "docs\\plans"))
        for root in (None, "", "."):
            self.assertFalse(self.tool._is_pipeline_artifact("notes.txt", root), root)


@unittest.skipUnless(shutil.which("git"), "git required")
class TestDiffEntries(RunDiffCase):
    BODY = "".join(f"line {i}\n" for i in range(20))

    def setUp(self):
        super().setUp()
        self.init_repo({"keep.py": "a = 1\n", "gone.py": "b = 1\n", "old name.py": self.BODY})
        self.base_sha = self.git("rev-parse", "HEAD").strip()
        self.write("keep.py", "a = 2\nc = 3\n")
        (self.repo / "gone.py").unlink()
        (self.repo / "old name.py").rename(self.repo / "new name.py")
        self.write("blob.bin", b"\x00\x01\x02binary")
        self.write("dir/added.py", "x = 1\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "change")

    def test_statuses_numstat_rename_and_binary(self):
        entries = self.tool._diff_entries(str(self.repo), self.base_sha, "HEAD")
        got = {e["path"]: (e["status"], e["old_path"], e["added"], e["deleted"], e["binary"]) for e in entries}
        self.assertEqual([e["path"] for e in entries], sorted(got))
        self.assertEqual(got, {
            "keep.py": ("M", None, 2, 1, False),
            "gone.py": ("D", None, 0, 1, False),
            "new name.py": ("R", "old name.py", 0, 0, False),
            "blob.bin": ("A", None, None, None, True),
            "dir/added.py": ("A", None, 1, 0, False),
        })

    def test_paths_limit_the_diff(self):
        only = self.tool._diff_entries(str(self.repo), self.base_sha, "HEAD", ["keep.py", "dir/added.py"])
        self.assertEqual([e["path"] for e in only], ["dir/added.py", "keep.py"])
        self.assertEqual(self.tool._diff_entries(str(self.repo), self.base_sha, "HEAD", []), [])


class TestMarkdownHelpers(unittest.TestCase):
    def setUp(self):
        self.tool = load_tool()

    def test_fence_is_longer_than_any_backtick_run(self):
        self.assertEqual(self.tool._fence("plain"), "```")
        self.assertEqual(self.tool._fence("+a ``` b"), "````")
        self.assertEqual(self.tool._fence("`````"), "``````")

    def test_link_is_relative_to_the_report_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.realpath(tmp)
            report_dir = os.path.join(root, "docs", "plans")
            link = self.tool._md_link
            self.assertEqual(link(report_dir, os.path.join(root, "src", "app.py"), "src/app.py"),
                             "[src/app.py](../../src/app.py)")
            self.assertEqual(link(report_dir, os.path.join(root, "my dir", "a b.py"), "my dir/a b.py"),
                             "[my dir/a b.py](<../../my dir/a b.py>)")
            self.assertEqual(link(root, os.path.join(root, "a|b.py"), "a|b.py"), "[a\\|b.py](a\\|b.py)")
            self.assertEqual(link(root, os.path.join(root, "a]b`c.py"), "a]b`c.py"), "[a\\]b\\`c.py](a]b%60c.py)")
            self.assertEqual(link(root, os.path.join(root, "50% #1.py"), "50% #1.py"),
                             "[50% #1.py](<50%25 %231.py>)")

    def test_a_target_on_another_drive_is_a_file_uri(self):  # F2
        target = os.path.abspath(os.path.join(os.sep, "x", "a b#1.py"))
        with mock.patch.object(self.tool.os.path, "relpath", side_effect=ValueError("path is on mount 'D:'")):
            link = self.tool._md_link(os.getcwd(), target, "a b#1.py")
        self.assertEqual(link, f"[a b#1.py]({Path(target).as_uri()})")
        self.assertIn("%20", link)
        self.assertIn("%23", link)

    def test_section_keeps_400_lines_and_names_the_full_diff_command(self):
        strings = self.tool._DIFF_STRINGS["en"]
        diff = "".join(f"+l{i}\n" for i in range(450))
        text = "\n".join(self.tool._file_section("### x", diff, 'git diff a b -- "x"', strings))
        self.assertIn("+l399", text)
        self.assertNotIn("+l400", text)
        self.assertIn('First 400 of 450 lines shown. Full diff: `git diff a b -- "x"`', text)
        short = "\n".join(self.tool._file_section("### y", "+a ``` b\n", "cmd", strings))
        self.assertEqual(short, "### y\n\n````diff\n+a ``` b\n````")

    def test_top_literal_double_quotes_with_a_posix_fallback(self):  # F2
        quote = self.tool._top_literal
        self.assertEqual(quote("my dir/a.py"), '":(top,literal)my dir/a.py"')
        self.assertEqual(quote("it's.py"), '":(top,literal)it\'s.py"')
        self.assertFalse(self.tool._posix_only("it's.py"))
        for rel in ('a"b.py', "a$b.py", "a`b.py", "a!b.py", "a\\b.py"):
            self.assertEqual(quote(rel), shlex.quote(":(top,literal)" + rel), rel)
            self.assertTrue(self.tool._posix_only(rel), rel)

    def test_section_command_with_a_backtick_and_the_posix_note(self):  # F2
        strings = self.tool._DIFF_STRINGS["en"]
        diff = "".join(f"+l{i}\n" for i in range(450))
        text = "\n".join(self.tool._file_section("### x", diff, "git diff a b -- ':(top,literal)a`b.py'", strings,
                                                 posix=True))
        self.assertIn("Full diff: `` git diff a b -- ':(top,literal)a`b.py' `` (command for a POSIX shell: bash, zsh)",
                      text)
        self.assertEqual(self.tool._DIFF_STRINGS["ru"]["posix"], "(команда для оболочки POSIX: bash, zsh)")

    def test_section_splits_only_on_newlines(self):  # e6: git lines may hold  , \x0c, \x1c
        strings = self.tool._DIFF_STRINGS["en"]
        section = self.tool._file_section("### z", "+a b\x0cc\x1cd\n+e\n", "cmd", strings)
        self.assertEqual(section, ["### z", "", "```diff", "+a b\x0cc\x1cd\n+e", "```"])


class TestRenderDiffReport(unittest.TestCase):
    def setUp(self):
        self.tool = load_tool()

    def entry(self, path, **changes):
        entry = {"path": path, "old_path": None, "status": "M", "added": 1, "deleted": 1, "binary": False,
                 "fixed": False, "link": f"[{path}]({path})", "diff": f"diff --git a/{path} b/{path}\n-x\n+y\n",
                 "command": f'git diff a b -- "{path}"'}
        entry.update(changes)
        return entry

    def test_english_header_table_and_sections(self):
        entries = [self.entry("app.py"),
                   self.entry("new.py", status="R", old_path="old.py", added=0, deleted=0),
                   self.entry("blob.bin", status="A", added=None, deleted=None, binary=True),
                   self.entry("fix.py", fixed=True)]
        text = self.tool._render_diff_report("en", "[p1-impl.md](p1-impl.md)", "p1-impl", "a" * 40, "b" * 40,
                                             entries, fixes=True, excluded=["docs/api.md", "notes-spec.md"])
        lines = text.splitlines()
        self.assertEqual(lines[0], "# Diff report: p1-impl")
        self.assertEqual(lines[-4:], ["## Not included (pipeline artifacts)", "", "- `docs/api.md`",
                                      "- `notes-spec.md`"])
        for line in ("- Plan: [p1-impl.md](p1-impl.md)", f"- Baseline snapshot: `{'a' * 40}`",
                     f"- Last snapshot: `{'b' * 40}`",
                     "- Audit fixes: from the baseline snapshot to the working tree",
                     "## Summary", "| File | Status | + | − | Note |", "| [app.py](app.py) | M | 1 | 1 |  |",
                     "| [new.py](new.py) | R | 0 | 0 | renamed from `old.py` |",
                     "| [blob.bin](blob.bin) | A | - | - | binary file |",
                     "| [fix.py](fix.py) | M | 1 | 1 | fixed by audit |",
                     "## Changes by file", "### [app.py](app.py)", "### [fix.py](fix.py) — fixed by audit"):
            self.assertIn(line, lines)
        self.assertNotIn("### [blob.bin](blob.bin)", lines)
        self.assertEqual(text.count("```diff"), 3)
        self.assertRegex(text, r"- Date: \d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")

    def test_russian_headings_and_empty_run(self):
        text = self.tool._render_diff_report("ru", "[p](p)", "p1-impl", "a", "b", [self.entry("app.py")],
                                             fixes=False)
        self.assertTrue(text.startswith("# Diff-отчёт: p1-impl\n"))
        for line in ("- План: [p](p)", "## Сводка", "| Файл | Статус | + | − | Примечание |", "## Изменения по файлам"):
            self.assertIn(line, text.splitlines())
        self.assertNotIn("Исправления аудита", text)
        empty = self.tool._render_diff_report("ru", "[p](p)", "p1-impl", "a", "b", [], fixes=False)
        self.assertTrue(empty.endswith("Прогон не изменил файлов вне артефактов конвейера.\n"))
        self.assertNotIn("| Файл |", empty)
        self.assertNotIn("Не включены", empty + text)
        only_excluded = self.tool._render_diff_report("ru", "[p](p)", "p1-impl", "a", "b", [], fixes=False,
                                                      excluded=["p1-impl-report-1.md"])
        self.assertTrue(only_excluded.endswith("Прогон не изменил файлов вне артефактов конвейера.\n\n"
                                               "## Не включены (артефакты конвейера)\n\n- `p1-impl-report-1.md`\n"))


def write_journal(directory, plans):
    path = Path(directory) / "p1-chain.json"
    path.write_text(json.dumps({"version": 1, "goal": "p1", "lang": "en", "plans": plans}), encoding="utf-8")
    return str(path)


def audit_plan(plan_id, fix_files):
    return {"id": plan_id, "stages": {"audit": {"status": "done", "artifacts": {"fix_files": fix_files}}}}


class TestAuditFixFiles(unittest.TestCase):
    def setUp(self):
        self.tool = load_tool()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_plan_id_from_the_plan_or_roadmap_file_name(self):
        journal = write_journal(self.tmp.name, [{"id": "other-impl", "stages": {}},
                                                audit_plan("p1-impl", ["src/b.py", "./src/a.py", "src\\b.py"])])
        for plan in ("/x/docs/p1-impl.md", "/x/docs/p1-impl-roadmap.md"):
            self.assertEqual(self.tool._audit_fix_files({"plan_path": plan}, journal), ["src/a.py", "src/b.py"])

    def test_ledger_journal_field_gives_path_and_plan_id(self):
        journal = write_journal(self.tmp.name, [audit_plan("custom", ["c.py"])])
        led = {"plan_path": "/x/p1-impl.md", "journal": {"path": journal, "plan": "custom"}}
        self.assertEqual(self.tool._audit_fix_files(led, None), ["c.py"])

    def test_no_journal_or_no_audit_gives_nothing(self):
        self.assertEqual(self.tool._audit_fix_files({"plan_path": "/x/p1-impl.md"}, None), [])
        journal = write_journal(self.tmp.name, [{"id": "p1-impl", "stages": {"writing": {"status": "done"}}}])
        self.assertEqual(self.tool._audit_fix_files({"plan_path": "/x/p1-impl.md"}, journal), [])

    def test_errors_are_input_errors(self):
        led = {"plan_path": "/x/p1-impl.md"}
        missing = str(Path(self.tmp.name) / "missing-chain.json")
        for plans, error in (([audit_plan("p2-impl", [])], "journal-plan-unknown"), (None, "journal-missing"),
                             ([audit_plan("p1-impl", ["../etc/passwd"])], "invalid-path")):
            journal = missing if plans is None else write_journal(self.tmp.name, plans)
            with self.assertRaises(ValueError) as ctx:
                self.tool._audit_fix_files(led, journal)
            self.assertIn(error, str(ctx.exception))
            self.assertEqual(ctx.exception.code, 2)

    def test_badly_shaped_journal_is_journal_corrupt(self):  # e1
        led = {"plan_path": "/x/p1-impl.md"}
        for plans in ("plans", [{"id": "p1-impl", "stages": []}], [{"id": "p1-impl", "stages": {"audit": "done"}}],
                      [{"id": "p1-impl", "stages": {"audit": {"artifacts": ["x"]}}}],
                      [audit_plan("p1-impl", [1])], [audit_plan("p1-impl", {"a.py": 1})]):
            journal = write_journal(self.tmp.name, plans)
            with self.assertRaises(ValueError, msg=plans) as ctx:
                self.tool._audit_fix_files(led, journal)
            self.assertIn("journal-corrupt", str(ctx.exception))
            self.assertEqual(ctx.exception.code, 2)


RU_PLAN = "# План\n\n### Task 1: Первая\n\n- [ ] **Step 1: правка**\n\n### Task 2: Вторая\n\n- [ ] **Step 1: правка**\n"


@unittest.skipUnless(shutil.which("git"), "git required")
class TestRunDiffMarkdown(RunDiffCase):
    BODY = "".join(f"line {i}\n" for i in range(10))

    def setUp(self):
        super().setUp()
        self.init_repo({"src/app.py": "x = 1\n", "old.py": self.BODY, "drop.py": "d = 1\n"})
        self.out = self.repo / "docs" / "plans" / "p1-diffs.md"

    def report(self):
        result = self.tool.run_diff_markdown(self.exec_dir, str(self.out))
        return result, self.out.read_text(encoding="utf-8")

    def test_table_links_sections_and_exclusions(self):
        self.start()
        self.unit("task-1", {"src/app.py": "x = 2\n", "old.py": None, "new.py": self.BODY, "drop.py": None,
                             "my dir/a b.py": "s = 1\n", "blob.bin": b"\x00\x01\x02", "BACKLOG.md": "# B\n",
                             "docs/plans/p1-impl-review-1.md": "r\n", "notes-spec.md": "s\n"})
        result, text = self.report()
        files = {f["path"]: (f["status"], f["old_path"], f["added"], f["deleted"], f["binary"]) for f in result["files"]}
        self.assertEqual(files, {"blob.bin": ("A", None, None, None, True), "drop.py": ("D", None, 0, 1, False),
                                 "my dir/a b.py": ("A", None, 1, 0, False), "new.py": ("R", "old.py", 0, 0, False),
                                 "src/app.py": ("M", None, 1, 1, False)})
        self.assertEqual(result["excluded"], ["BACKLOG.md", "docs/plans/p1-impl-review-1.md", "notes-spec.md"])
        self.assertEqual((result["lang"], result["path"]), ("en", str(self.out.resolve())))
        lines = text.splitlines()
        for line in ("# Diff report: p1-impl", "- Plan: [p1-impl.md](p1-impl.md)",
                     f"- Baseline snapshot: `{result['baseline']}`",
                     "| [src/app.py](../../src/app.py) | M | 1 | 1 |  |",
                     "| [my dir/a b.py](<../../my dir/a b.py>) | A | 1 | 0 |  |",
                     "| [new.py](../../new.py) | R | 0 | 0 | renamed from `old.py` |",
                     "| [blob.bin](../../blob.bin) | A | - | - | binary file |",
                     "### [src/app.py](../../src/app.py)", "+x = 2"):
            self.assertIn(line, lines)
        self.assertNotIn("### [blob.bin](../../blob.bin)", lines)
        self.assertIn("## Not included (pipeline artifacts)", lines)
        for artifact in ("BACKLOG.md", "docs/plans/p1-impl-review-1.md", "notes-spec.md"):
            self.assertIn(f"- `{artifact}`", lines)  # listed as not included, never in the table or a diff
            self.assertNotIn(f"[{artifact}]", text)
            self.assertNotIn(f"b/{artifact}", text)

    def test_russian_plan_truncation_fence_and_overwrite(self):
        self.start(plan_text=RU_PLAN)
        self.unit("task-1", {"big.py": "".join(f"v{i} = {i}\n" for i in range(450)),
                             "src/app.py": "x = '```'\n"})
        result, text = self.report()
        self.assertEqual(result["lang"], "ru")
        self.assertTrue(text.startswith("# Diff-отчёт: p1-impl\n"))
        self.assertIn("| Файл | Статус | + | − | Примечание |", text)
        self.assertRegex(text, r"Показаны первые 400 из \d+ строк\. Полный diff: "
                               r"`git diff [0-9a-f]{40} [0-9a-f]{40} -- \":\(top,literal\)big\.py\"`")
        self.assertIn("````diff\n", text)
        self.report()  # an existing report is overwritten, not appended to
        self.assertEqual(self.out.read_text(encoding="utf-8").count("# Diff-отчёт"), 1)

    def test_plan_at_the_root_and_a_run_without_code_changes(self):
        self.start(plan_rel="p1-impl.md")
        self.out = self.repo / "p1-diffs.md"
        self.unit("task-1", {"p1-impl-report-1.md": "r\n"})
        result, text = self.report()
        self.assertEqual((result["files"], result["excluded"]), ([], ["p1-impl-report-1.md"]))
        self.assertIn("The run changed no files outside the pipeline artifacts.", text)
        self.assertTrue(text.endswith("## Not included (pipeline artifacts)\n\n- `p1-impl-report-1.md`\n"))


@unittest.skipUnless(shutil.which("git"), "git required")
class TestIncludeFixes(RunDiffCase):
    def setUp(self):
        super().setUp()
        self.init_repo({"src/app.py": "x = 1\n", "src/util.py": "u = 1\n"})
        self.start()
        self.unit("task-1", {"src/app.py": "x = 2\n"})
        self.unit("task-2", {"src/util.py": "u = 2\n"})
        # The audit's fix loop runs after the run: no snapshot holds these edits.
        self.write("src/app.py", "x = 3\n")
        self.write("src/fix.py", "f = 1\n")
        self.journal = write_journal(self.base, [audit_plan("p1-impl", ["src/app.py", "src/fix.py"])])
        self.out = self.repo / "docs" / "plans" / "p1-diffs.md"

    def test_fix_files_are_diffed_to_the_working_tree_and_marked(self):
        result = self.tool.run_diff_markdown(self.exec_dir, str(self.out), journal=self.journal)
        text = self.out.read_text(encoding="utf-8")
        files = {f["path"]: (f["status"], f["fixed"]) for f in result["files"]}
        self.assertEqual(files, {"src/app.py": ("M", True), "src/fix.py": ("A", True), "src/util.py": ("M", False)})
        self.assertEqual(result["fix_files"], ["src/app.py", "src/fix.py"])
        lines = text.splitlines()
        for line in ("- Audit fixes: from the baseline snapshot to the working tree",
                     "| [src/app.py](../../src/app.py) | M | 1 | 1 | fixed by audit |",
                     "### [src/fix.py](../../src/fix.py) — fixed by audit", "+x = 3", "+f = 1", "+u = 2"):
            self.assertIn(line, lines)
        self.assertNotIn("+x = 2", lines)

    def test_without_journal_the_report_stops_at_the_last_snapshot(self):
        result = self.tool.run_diff_markdown(self.exec_dir, str(self.out))
        text = self.out.read_text(encoding="utf-8")
        self.assertEqual([(f["path"], f["fixed"]) for f in result["files"]],
                         [("src/app.py", False), ("src/util.py", False)])
        self.assertIn("+x = 2", text.splitlines())
        self.assertNotIn("fix.py", text)
        self.assertEqual(result["fix_files"], [])

    def test_a_fix_that_reverts_a_run_file_drops_it_from_the_report(self):
        self.write("src/app.py", "x = 1\n")  # the audit takes the run's change back
        result = self.tool.run_diff_markdown(self.exec_dir, str(self.out), journal=self.journal)
        text = self.out.read_text(encoding="utf-8")
        self.assertEqual([(f["path"], f["fixed"]) for f in result["files"]],
                         [("src/fix.py", True), ("src/util.py", False)])
        self.assertEqual(result["fix_files"], ["src/app.py", "src/fix.py"])
        self.assertNotIn("src/app.py", text)
        self.assertNotIn("+x = 2", text.splitlines())


@unittest.skipUnless(shutil.which("git"), "git required")
class TestDiffReportGateFixes(RunDiffCase):
    BODY = "".join(f"line {i}\n" for i in range(20))

    def setUp(self):
        super().setUp()
        self.out = self.repo / "docs" / "plans" / "p1-diffs.md"

    def test_a_fixed_rename_keeps_its_deletion(self):  # e2
        self.init_repo({"old.py": self.BODY})
        self.start()
        self.unit("task-1", {"old.py": None, "new.py": self.BODY})
        self.write("new.py", self.BODY + "fixed\n")
        journal = write_journal(self.base, [audit_plan("p1-impl", ["new.py"])])
        result = self.tool.run_diff_markdown(self.exec_dir, str(self.out), journal=journal)
        text = self.out.read_text(encoding="utf-8")
        self.assertEqual({f["path"]: (f["status"], f["old_path"], f["fixed"]) for f in result["files"]},
                         {"new.py": ("R", "old.py", True)})
        self.assertIn("rename from old.py", text.splitlines())
        self.assertIn("+fixed", text.splitlines())

    def test_a_recreated_old_path_of_a_rename_is_not_marked_fixed(self):  # F5
        self.init_repo({"old.py": self.BODY})
        self.start()
        self.unit("task-1", {"old.py": None, "new.py": self.BODY})
        self.write("old.py", "recreated\n")
        self.write("new.py", self.BODY + "fixed\n")
        journal = write_journal(self.base, [audit_plan("p1-impl", ["new.py"])])
        result = self.tool.run_diff_markdown(self.exec_dir, str(self.out), journal=journal)
        lines = self.out.read_text(encoding="utf-8").splitlines()
        self.assertEqual({f["path"]: f["fixed"] for f in result["files"]}, {"new.py": True, "old.py": False})
        self.assertIn("### [old.py](../../old.py)", lines)
        self.assertIn("### [new.py](../../new.py) — fixed by audit", lines)

    def test_user_git_config_does_not_change_the_diff(self):  # e3
        self.init_repo({"app.py": "x = 1\n"})
        for key, value in (("color.ui", "always"), ("color.diff", "always"), ("diff.noprefix", "true"),
                           ("diff.external", "echo EXTERNAL")):
            self.git("config", key, value)
        self.start()
        self.unit("task-1", {"app.py": "x = 2\n"})
        result = self.tool.run_diff_markdown(self.exec_dir, str(self.out))
        text = self.out.read_text(encoding="utf-8")
        self.assertEqual([(f["path"], f["added"], f["deleted"]) for f in result["files"]], [("app.py", 1, 1)])
        lines = text.splitlines()
        for line in ("diff --git a/app.py b/app.py", "--- a/app.py", "+++ b/app.py", "-x = 1", "+x = 2"):
            self.assertIn(line, lines)
        self.assertNotIn("\x1b[", text)
        self.assertNotIn("EXTERNAL", text)

    def test_an_ignored_fix_file_is_listed_as_not_included(self):  # e4
        self.init_repo({"app.py": "x = 1\n", ".gitignore": "*.log\n"})
        self.start()
        self.unit("task-1", {"app.py": "x = 2\n"})
        self.write("debug.log", "fixed by the audit\n")
        journal = write_journal(self.base, [audit_plan("p1-impl", ["app.py", "debug.log"])])
        result = self.tool.run_diff_markdown(self.exec_dir, str(self.out), journal=journal)
        text = self.out.read_text(encoding="utf-8")
        self.assertEqual(([f["path"] for f in result["files"]], result["ignored"]), (["app.py"], ["debug.log"]))
        self.assertTrue(text.endswith("## Not included (ignored by git)\n\n- `debug.log`\n"), text)

    def test_full_diff_command_quotes_a_literal_path(self):  # e7
        self.init_repo({"app.py": "x = 1\n"})
        self.start()
        self.unit("task-1", {"my dir/big file.py": "".join(f"v{i} = {i}\n" for i in range(450))})
        result = self.tool.run_diff_markdown(self.exec_dir, str(self.out))
        text = self.out.read_text(encoding="utf-8")
        self.assertIn(f"Full diff: `git diff {result['baseline']} {result['last']} -- "
                      f"\":(top,literal)my dir/big file.py\"`", text)
        self.assertNotIn("POSIX", text)

    def test_full_diff_command_for_a_quote_and_a_dollar(self):  # F2
        self.init_repo({"app.py": "x = 1\n"})
        self.start()
        body = "".join(f"v{i} = {i}\n" for i in range(450))
        self.unit("task-1", {"it's big.py": body, "cost$big.py": body})
        result = self.tool.run_diff_markdown(self.exec_dir, str(self.out))
        text = self.out.read_text(encoding="utf-8")
        head = f"Full diff: `git diff {result['baseline']} {result['last']} -- "
        self.assertIn(head + "\":(top,literal)it's big.py\"`\n", text)
        self.assertIn(head + "':(top,literal)cost$big.py'` (command for a POSIX shell: bash, zsh)\n", text)


class TestRunDiffCli(RunDiffCase):
    @unittest.skipUnless(shutil.which("git"), "git required")
    def test_markdown_flag_writes_the_report_and_plain_output_is_unchanged(self):
        self.init_repo({"app.py": "x = 1\n"})
        self.start()
        self.unit("task-1", {"app.py": "x = 2\n"})
        out = self.repo / "docs" / "plans" / "p1-diffs.md"
        code, data = run_cli("run-diff", self.exec_dir, "--markdown", str(out))
        self.assertEqual((code, data["ok"], data["path"]), (0, True, str(out.resolve())))
        self.assertEqual([f["path"] for f in data["files"]], ["app.py"])
        self.assertTrue(out.read_text(encoding="utf-8").startswith("# Diff report: p1-impl\n"))
        code, data = run_cli("run-diff", self.exec_dir)
        self.assertEqual(code, 0)
        self.assertEqual(sorted(data), ["baseline", "command", "files", "last", "stat"])
        journal = write_journal(self.base, [audit_plan("p1-impl", ["app.py"])])
        code, data = run_cli("run-diff", self.exec_dir, "--markdown", str(out), "--include-fixes", journal)
        self.assertEqual((code, data["fix_files"]), (0, ["app.py"]))

    def test_include_fixes_needs_markdown(self):
        code, data = run_cli("run-diff", self.exec_dir, "--include-fixes", "p1-chain.json")
        self.assertEqual(code, 2)
        self.assertIn("include-fixes-needs-markdown", data["errors"][0])

    def test_no_git_with_markdown_writes_nothing(self):
        self.write("app.py", "x = 1\n")
        self.start(plan_rel="p1-impl.md")
        self.unit("task-1", {"app.py": "x = 2\n"})
        out = self.base / "p1-diffs.md"
        code, data = run_cli("run-diff", self.exec_dir, "--markdown", str(out))
        self.assertEqual(code, 1)
        self.assertTrue(data["errors"][0].startswith("no-git:"), data)
        self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
