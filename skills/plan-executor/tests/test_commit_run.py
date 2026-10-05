import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "scripts" / "executor_tool.py"
PLAN = "# P\n\n### Task 1: A\n\n- [ ] **Step 1: edit**\n\n### Task 2: B\n\n- [ ] **Step 1: edit**\n"


def load_tool():
    spec = importlib.util.spec_from_file_location("executor_tool", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless(shutil.which("git"), "git required")
class RepoCase(unittest.TestCase):
    def setUp(self):
        self.tool = load_tool()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        (self.repo / "docs").mkdir(parents=True)
        self.exec_dir = str(self.root / "exec")
        self.git("init", "-q")
        self.git("config", "user.name", "t")
        self.git("config", "user.email", "t@t")
        self.write("app.py", "x = 1\n")
        self.write("util.py", "y = 1\n")
        self.plan = self.write("docs/plan01-impl.md", PLAN)

    def git(self, *args):
        proc = subprocess.run(["git", *args], cwd=self.repo, capture_output=True, text=True, check=True)
        return proc.stdout.strip()

    def write(self, rel, text):
        path = self.repo / rel
        path.write_text(text, encoding="utf-8")
        return str(path)

    def commit_all(self, message="base"):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD")

    def init(self, **kwargs):
        args = dict(plan_path=self.plan, exec_dir=self.exec_dir, whole=False, workdir=str(self.repo),
                    allow_dirty=False, accept_drift=False, allow_temp=False)
        args.update(kwargs)
        return self.tool.cmd_ledger_init(types.SimpleNamespace(**args))

    def cli(self, *args):
        proc = subprocess.run([sys.executable, str(TOOL_PATH), *args], capture_output=True, text=True,
                              encoding="utf-8", check=False)
        return proc.returncode, json.loads(proc.stdout)


class TestBaselineHead(RepoCase):
    def test_ledger_init_stores_head_of_the_start(self):
        head = self.commit_all()
        led = self.init()
        self.assertEqual(led["baseline_head"], head)
        self.write("util.py", "y = 2\n")
        self.commit_all("user commit during the run")
        self.assertEqual(self.init()["baseline_head"], head)  # resume keeps the start
        self.assertEqual(self.tool._load(self.exec_dir)["baseline_head"], head)

    def test_unborn_head_is_an_empty_string(self):
        led = self.init(allow_dirty=True)
        self.assertEqual(led["baseline_head"], "")

    def test_no_git_leaves_the_field_out(self):
        shutil.rmtree(self.repo / ".git")
        self.assertNotIn("baseline_head", self.init())

    def test_schema_declares_baseline_head(self):
        schema = json.loads((ROOT / "assets" / "ledger.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(schema["properties"]["baseline_head"]["type"], "string")
        self.assertNotIn("baseline_head", schema["required"])


class TestLedgerPath(RepoCase):
    ROADMAP = ("# R\n\n> Source: [plan01-impl.md](./plan01-impl.md)\n\n"
               "| Stage | Title | Depends | Group | Weight |\n|---|---|---|---|---|\n| a | A | - | - | green |\n")

    def test_path_matches_auto_and_reads_nothing(self):
        self.commit_all()
        code, before = self.cli("ledger-path", self.plan, "--workdir", str(self.repo))
        self.assertEqual((code, before["ok"], before["exists"], before["matched"]), (0, True, False, None))
        led = self.init(exec_dir="auto")
        self.assertEqual(before["exec_dir"], led["exec_dir"])
        state = Path(led["exec_dir"]) / "state.json"
        snapshot = state.read_bytes()
        code, after = self.cli("ledger-path", self.plan, "--workdir", str(self.repo))
        self.assertEqual((code, after["exists"], after["exec_dir"], after["matched"]),
                         (0, True, led["exec_dir"], "plan"))
        self.assertEqual(state.read_bytes(), snapshot)

    def test_roadmap_run_is_found_from_the_master_plan(self):
        roadmap = self.write("docs/plan01-impl-roadmap.md", self.ROADMAP)
        self.commit_all()
        led = self.init(plan_path=roadmap, exec_dir="auto")
        for path in (self.plan, roadmap):
            code, out = self.cli("ledger-path", path, "--workdir", str(self.repo))
            self.assertEqual((code, out["exec_dir"], out["exists"], out["matched"]),
                             (0, led["exec_dir"], True, "roadmap"), path)

    def test_ledgers_of_the_plan_and_its_roadmap_are_ambiguous(self):
        roadmap = self.write("docs/plan01-impl-roadmap.md", self.ROADMAP)
        self.commit_all()
        dirs = sorted([self.init(plan_path=roadmap, exec_dir="auto")["exec_dir"],
                       self.init(exec_dir="auto", whole=True)["exec_dir"]])
        code, out = self.cli("ledger-path", self.plan, "--workdir", str(self.repo))
        self.assertEqual(code, 2)
        self.assertIn("ledger-ambiguous", out["errors"][0])
        self.assertEqual(sorted(out["exec_dirs"]), dirs)

    def test_workdir_is_required(self):
        proc = subprocess.run([sys.executable, str(TOOL_PATH), "ledger-path", self.plan], capture_output=True,
                              text=True, check=False)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("--workdir", proc.stderr)


class TestChainFiles(RepoCase):
    """Files of the pipeline (journal, reviews, reports, diffs, followups, spec and plan files) are written
    between units: never a foreign change, never rolled back. Any other file, in the plan folder too, is."""

    def setUp(self):
        super().setUp()
        self.write("docs/guide.md", "guide\n")
        self.write("docs/plan01-impl-review-1.md", "review 1\n")
        self.commit_all()
        self.led = self.init()
        self.tool.unit_begin(self.exec_dir)
        self.write("app.py", "x = 2\n")
        self.tool.unit_finish(self.exec_dir, "task-1", "pass")
        self.write("docs/plan01-impl-review-1.md", "review 1, edited\n")
        self.write("docs/plan01-impl-report-1.md", "report\n")
        self.write("docs/plan01-followups.json", "[]\n")
        self.write("docs/guide.md", "guide, edited by hand\n")

    def read(self, rel):
        return (self.repo / rel).read_text(encoding="utf-8")

    def test_names(self):
        for rel in ("docs/g-chain.json", "g-chain.json.lock", "a/g-diffs.md", "g-followups.json", "docs/g-spec.md",
                    "docs/g-impl.md", "docs/g-impl-b.md", "docs/g-impl-roadmap.md", "docs/g-roadmap.md", "docs/g-impl-completion.md",
                    "docs/g-impl-review-2.md", "docs/g-impl-report-3.md", "docs/g-impl-report-3-final.md",
                    "BACKLOG.md"):
            self.assertTrue(self.tool._is_chain_file(rel), rel)
        for rel in ("docs/guide.md", "sub/BACKLOG.md", "docs/spec.md", "docs/g-impl-notes.txt",
                    "g-review-x.md", "g-chain.json.bak", "app.py"):
            self.assertFalse(self.tool._is_chain_file(rel), rel)
        for rel, folder in (("docs/g-spec.md", "docs"), ("docs/g-impl-review-2.md", "docs"), ("g-spec.md", ""),
                            ("BACKLOG.md", "docs")):
            self.assertTrue(self.tool._is_chain_file(rel, folder), (rel, folder))
        for rel, folder in (("api/openapi-spec.md", "docs"), ("docs/new/g-spec.md", "docs"),
                            ("docs/g-spec.md", ""), ("sub/BACKLOG.md", "docs")):
            self.assertFalse(self.tool._is_chain_file(rel, folder), (rel, folder))
        self.assertTrue(self.tool._is_chain_file("api/openapi-spec.md"))  # no ledger: the name alone, as before

    def test_plan_dir_of_the_ledger(self):
        self.assertEqual(self.tool._plan_dir(self.tool._load(self.exec_dir)), "docs")
        self.assertEqual(self.tool._plan_dir({"plan_path": self.plan, "workdir": None}, top=str(self.repo)), "docs")
        self.assertEqual(self.tool._plan_dir({"plan_path": str(self.repo / "p-impl.md"),
                                              "workdir": str(self.repo)}), "")
        for led in (None, {}, {"plan_path": self.plan}, {"plan_path": str(self.root / "elsewhere-impl.md"),
                                                          "workdir": str(self.repo)},
                    {"plan_path": self.plan, "workdir": str(self.root / "missing")}):
            self.assertIsNone(self.tool._plan_dir(led), led)

    def test_foreign_check_and_full_rollback_skip_only_chain_files(self):
        begun = self.tool.unit_begin(self.exec_dir)
        self.assertEqual(begun["foreign_changes"], [{"path": "docs/guide.md", "status": "modified"}])
        self.tool.checkpoint_restore(str(self.repo), self.led["baseline_checkpoint"])
        self.assertEqual((self.read("docs/guide.md"), self.read("app.py")), ("guide\n", "x = 1\n"))
        self.assertEqual(self.read("docs/plan01-impl-review-1.md"), "review 1, edited\n")
        self.assertEqual(self.read("docs/plan01-impl-report-1.md"), "report\n")
        self.assertTrue((self.repo / "docs/plan01-followups.json").is_file())

    def test_paths_rollback_skips_chain_files(self):
        expected = self.tool._load(self.exec_dir)["expected_tree"]
        out = self.tool.cmd_checkpoint_restore(types.SimpleNamespace(
            workdir=str(self.repo), checkpoint_id=expected, exec_dir=self.exec_dir,
            paths=["docs/guide.md", "docs/plan01-impl-review-1.md"]))
        self.assertEqual(out["restored"], ["docs/guide.md"])
        self.assertEqual(self.read("docs/plan01-impl-review-1.md"), "review 1, edited\n")
        events = self.tool._load(self.exec_dir)["foreign_events"]
        self.assertEqual([(e["decision"], [p["path"] for p in e["paths"]]) for e in events],
                         [("restored", ["docs/guide.md"])])
        with self.assertRaises(ValueError) as ctx:
            self.tool.checkpoint_restore_paths(str(self.repo), expected, ["docs/plan01-impl-review-1.md", "BACKLOG.md"])
        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("paths-empty", str(ctx.exception))


class TestJournalOutsideSnapshots(RepoCase):
    """The run's journal is its own record, like the ledger: it changes after every unit, so snapshots
    leave it out and it never makes the working tree dirty. Any other *-chain.json is a project file."""

    def setUp(self):
        super().setUp()
        self.write("docs/plan01-chain.json", "{}\n")  # tracked, as after a user commit
        self.commit_all()
        self.led = self.init()
        (self.repo / "config").mkdir()

    def test_journal_written_during_a_unit_is_not_part_of_the_run(self):
        self.tool.unit_begin(self.exec_dir)
        self.write("app.py", "x = 2\n")
        self.write("config/supply-chain.json", "{}\n")
        self.write("docs/plan01-chain.json", "[1]\n")
        self.write("docs/plan01-chain.json.lock", "{}\n")
        self.tool.unit_finish(self.exec_dir, "task-1", "pass")
        self.assertEqual([f["path"] for f in self.tool.run_diff(self.exec_dir)["files"]],
                         ["app.py", "config/supply-chain.json"])

    def test_journal_does_not_make_the_tree_dirty(self):
        journal = self.tool._journal_file(self.plan)
        self.assertEqual(Path(journal).resolve(), (self.repo / "docs" / "plan01-chain.json").resolve())
        self.write("docs/plan01-chain.json", "[3]\n")
        self.write("docs/plan01-chain.json.lock", "{}\n")
        self.assertEqual(self.tool.checkpoint_detect(str(self.repo), journal=journal), {"vcs": "git", "dirty": False})
        self.write("other-chain.json", "{}\n")
        self.assertTrue(self.tool.checkpoint_detect(str(self.repo), journal=journal)["dirty"])
        self.assertFalse(self.tool.checkpoint_detect(str(self.repo))["dirty"])  # unknown journal: every *-chain.json
        self.write("docs/plan01-followups.json", "[]\n")  # a chain file: not dirty either (h2)
        self.assertFalse(self.tool.checkpoint_detect(str(self.repo))["dirty"])
        self.write("docs/notes.txt", "x\n")
        self.assertTrue(self.tool.checkpoint_detect(str(self.repo))["dirty"])

    def test_chain_files_never_make_the_tree_dirty(self):  # h2
        journal = self.tool._journal_file(self.plan)
        (self.repo / "docs" / "new").mkdir()
        for rel in ("docs/plan01-followups.json", "docs/plan01-diffs.md", "docs/plan01-impl-review-1.md",
                    "docs/new/plan02-spec.md", "docs/new/plan02-impl.md", "docs/plan01-impl-report-1.md", "BACKLOG.md"):
            self.write(rel, "x\n")
        self.assertEqual(self.tool.checkpoint_detect(str(self.repo), journal=journal), {"vcs": "git", "dirty": False})
        self.assertEqual(self.init(exec_dir=str(self.root / "exec2"))["baseline_head"], self.git("rev-parse", "HEAD"))
        self.write("docs/new/other.md", "x\n")  # a project file next to them still is
        self.assertTrue(self.tool.checkpoint_detect(str(self.repo), journal=journal)["dirty"])

    def test_working_tree_trees_leave_out_the_same_journal(self):
        self.tool.unit_begin(self.exec_dir)
        self.write("config/supply-chain.json", "{}\n")
        self.write("docs/plan01-chain.json", "[1]\n")
        self.tool.unit_finish(self.exec_dir, "task-1", "pass")
        check = self.tool._foreign_check(self.tool._load(self.exec_dir))
        self.assertEqual(check["current_tree"], check["expected_tree"])


class TestJournalInTheRepository(RepoCase):
    """ledger-init opens the journal after the dirty-worktree check and the baseline snapshot."""

    SPEC = "> Tier: Deep\n\n# Goal\n\nGoal.\n"
    TASKS = "### Task 1: A\n\n- [ ] **Step 1: edit**\n"

    def test_fresh_journal_is_neither_dirty_nor_in_the_baseline(self):
        self.write("docs/plan01-spec.md", self.SPEC)
        self.plan = self.write("docs/plan01-impl.md", "# P\n\n**Spec:** plan01-spec.md\n\n" + self.TASKS)
        self.commit_all()
        led = self.init()
        journal = self.repo / "docs" / "plan01-chain.json"
        self.assertEqual(Path(led["journal"]["path"]).resolve(), journal.resolve())
        self.assertNotIn("plan01-chain.json", self.git("ls-tree", "-r", "--name-only", led["baseline_checkpoint"]))
        self.assertEqual(self.tool.unit_begin(self.exec_dir)["reason"], "ready")
        other = self.write("docs/plan02-impl.md", "# Q\n\n**Spec:** plan01-spec.md\n\n" + self.TASKS)
        self.git("add", "docs/plan02-impl.md")
        self.git("commit", "-q", "-m", "second plan")
        second = self.init(plan_path=other, exec_dir=str(self.root / "exec2"))
        self.assertEqual((second["journal"]["path"], second["journal"]["plan"]), (led["journal"]["path"], "plan02-impl"))


class CommitCase(RepoCase):
    def run_plan(self, first, second=None, **init):
        """ledger-init, then both units pass; each dict maps files to the text the unit writes (None deletes)."""
        self.init(**init)
        for unit, edits in (("task-1", first), ("task-2", second or {})):
            self.tool.unit_begin(self.exec_dir)
            for rel, text in edits.items():
                if text is None:
                    (self.repo / rel).unlink()
                else:
                    self.write(rel, text)
            self.tool.unit_finish(self.exec_dir, unit, "pass")

    def commit(self, subject="feat(plan01): add the feature", journal=None):
        message = self.root / "message.txt"
        message.write_text(subject + "\n\nGoal of the spec.\n", encoding="utf-8")
        return self.tool.commit_run(self.exec_dir, str(message), journal=journal)

    def files_of(self, rev="HEAD"):
        return sorted(self.git("show", "--name-only", "--format=", rev).split())


class TestCommitRun(CommitCase):
    def test_commits_only_the_run_files(self):
        base = self.commit_all()
        self.run_plan({"app.py": "x = 2\n", "BACKLOG.md": "- [ ] later\n"},
                      {"new.py": "z = 1\n", "docs/plan01-impl.md": PLAN + "\n", "notes-review-1.md": "r\n"})
        self.write("notes.txt", "the user's file, not the run's\n")
        result = self.commit()
        self.assertEqual((result["ok"], result["empty"], result["files"]),
                         (True, False, ["app.py", "new.py", "notes-review-1.md"]))
        self.assertEqual(result["excluded"], ["BACKLOG.md", "docs/plan01-impl.md"])
        self.assertEqual(result["excluded_outside_chain"], [])  # a chain name outside the plan folder is committed (F5)
        self.assertEqual(result["sha"], self.git("rev-parse", "HEAD"))
        self.assertEqual(result["subject"], "feat(plan01): add the feature")
        self.assertEqual(self.files_of(), ["app.py", "new.py", "notes-review-1.md"])
        self.assertEqual(self.git("rev-parse", "HEAD~1"), base)
        self.assertEqual(self.git("diff", "--cached", "--name-only"), "")

    def test_a_second_call_is_empty(self):
        self.commit_all()
        self.run_plan({"app.py": "x = 2\n"})
        self.commit()
        head = self.git("rev-parse", "HEAD")
        self.assertEqual(self.commit(), {"ok": True, "empty": True, "files": [], "excluded": [],
                                         "excluded_outside_chain": []})
        self.assertEqual(self.git("rev-parse", "HEAD"), head)

    def test_unborn_head_commits_the_new_files(self):
        self.run_plan({"new.py": "z = 1\n"}, allow_dirty=True)
        self.assertEqual(self.commit()["files"], ["new.py"])
        self.assertEqual(self.files_of(), ["new.py"])

    def test_a_rename_stages_both_paths(self):
        self.commit_all()
        self.run_plan({"util.py": None, "tools.py": "y = 1\n"})
        self.assertEqual(self.commit()["files"], ["tools.py", "util.py"])
        tracked = self.git("ls-tree", "-r", "--name-only", "HEAD").split()
        self.assertEqual(("tools.py" in tracked, "util.py" in tracked), (True, False))
        self.assertEqual(self.git("status", "--porcelain", "--", "tools.py", "util.py"), "")

    def test_a_chain_json_outside_the_plan_folder_is_committed(self):  # F5 of plan-refactoring-02
        self.commit_all()
        (self.repo / "config").mkdir()
        self.run_plan({"app.py": "x = 2\n", "config/supply-chain.json": "{}\n", "docs/other-chain.json": "{}\n"})
        result = self.commit()
        self.assertEqual(result["files"], ["app.py", "config/supply-chain.json"])
        self.assertEqual(result["excluded"], ["docs/other-chain.json"])
        self.assertEqual(result["excluded_outside_chain"], ["docs/other-chain.json"])  # not the run's journal

    def test_a_project_file_in_the_plan_folder_is_committed(self):  # F5 of plan-refactoring-02
        self.commit_all()
        self.run_plan({"app.py": "x = 2\n", "docs/api.md": "# API\n", "docs/plan01-impl-review-1.md": "r\n"})
        result = self.commit()
        self.assertEqual(result["files"], ["app.py", "docs/api.md"])
        self.assertEqual((result["excluded"], result["excluded_outside_chain"]), (["docs/plan01-impl-review-1.md"], []))
        self.assertEqual(self.git("status", "--porcelain", "--", "docs/api.md"), "")

    def test_a_fixture_named_like_a_plan_is_committed(self):  # F5 of plan-refactoring-02 (commit c1bc241)
        self.commit_all()
        (self.repo / "tests" / "fixtures").mkdir(parents=True)
        self.run_plan({"tests/fixtures/tricky-impl.md": "### Task 1: x\n"})
        self.assertEqual(self.commit()["files"], ["tests/fixtures/tricky-impl.md"])

    def test_no_git(self):
        shutil.rmtree(self.repo / ".git")
        self.run_plan({"app.py": "x = 2\n"})
        with self.assertRaises(ValueError) as ctx:
            self.commit()
        self.assertIn("no-git", str(ctx.exception))
        self.assertEqual(ctx.exception.code, 1)


DEVIATION_PLAN = ("# P\n\n**Deviations from spec:**\n- the spec says X -> the plan does Y (the user, 2026-10-05)\n\n---\n\n"
                  "### Task 1: A\n\n- [ ] **Step 1: edit**\n\n### Task 2: B\n\n- [ ] **Step 1: edit**\n")


class TestPlanDeviations(unittest.TestCase):
    """Spec 2 of plan-refactoring-02: the deviations from the spec are the header's items and the units' notes."""

    def test_header_items_and_notes_once(self):
        tool = load_tool()
        external = "External: prod (read) confirmed by the engineer for this task"  # GATE.md: a confirmation, not a deviation
        units = [{"notes": ["kept the old flag", "subagent-unavailable", external, "kept the old flag"]}]
        self.assertEqual(tool.plan_deviations(DEVIATION_PLAN, units),
                         ["the spec says X -> the plan does Y (the user, 2026-10-05)", "kept the old flag"])
        self.assertEqual(tool.plan_deviations(PLAN, [{"notes": ["subagent-unavailable", external]}]), [])
        self.assertEqual(tool.SUBAGENT_UNAVAILABLE, "subagent-unavailable")

    def test_the_block_ends_at_the_first_other_line(self):
        text = "**Deviations from spec:**\n- one\n\n**Baseline:** x\n- not a deviation\n\n### Task 1: A\n- no\n"
        self.assertEqual(load_tool().plan_deviations(text), ["one"])


class TestBacklogDeviations(unittest.TestCase):
    """Spec 2 of plan-refactoring-02: the deviations go into the goal's BACKLOG.md section once."""

    EXPECTED = ["amend spec plan01-impl.md: the spec says X -> the plan does Y (the user, 2026-10-05)",
                "amend spec plan01-impl.md: kept the old flag"]

    def setUp(self):
        self.tool = load_tool()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.top = Path(tmp.name)
        (self.top / "docs").mkdir()
        self.plan = self.top / "docs" / "plan01-impl.md"
        self.plan.write_text(DEVIATION_PLAN, encoding="utf-8")
        self.led = {"plan_path": str(self.plan),
                    "units": [{"id": "task-1", "notes": ["kept the old flag", "subagent-unavailable"]}]}

    def write(self):
        return self.tool._backlog_deviations(self.led, str(self.top))

    def test_lines_are_appended_once(self):
        self.assertEqual(self.write(), ({"section": "plan01", "appended": self.EXPECTED, "exists": []}, []))
        text = (self.top / "BACKLOG.md").read_text(encoding="utf-8")
        self.assertEqual(text.count("- [ ] amend spec plan01-impl.md: "), 2)
        self.assertNotIn("subagent-unavailable", text)
        self.assertEqual(self.write(), ({"section": "plan01", "appended": [], "exists": self.EXPECTED}, []))
        self.assertEqual((self.top / "BACKLOG.md").read_text(encoding="utf-8"), text)

    def test_no_deviation_no_backlog(self):
        self.plan.write_text(PLAN, encoding="utf-8")
        self.led["units"] = [{"id": "task-1", "notes": ["subagent-unavailable"]}]
        self.assertEqual(self.write(), (None, []))
        self.assertFalse((self.top / "BACKLOG.md").exists())

    def test_an_open_item_of_another_source_is_not_appended(self):
        (self.top / "BACKLOG.md").write_text(f"# Backlog\n\n## plan01\n\n- [ ] {self.EXPECTED[1]} — someone, 2026-10-01\n",
                                             encoding="utf-8")
        self.assertEqual(self.write()[0], {"section": "plan01", "appended": self.EXPECTED[:1], "exists": self.EXPECTED[1:]})

    def test_a_russian_plan_writes_russian_lines(self):
        self.plan.write_text("# П\n\n**Deviations from spec:**\n- спека говорит X, план делает Y\n\n---\n\n### Task 1: А\n",
                             encoding="utf-8")
        self.led["units"] = []
        self.assertEqual(self.write()[0]["appended"], ["поправить спеку plan01-impl.md: спека говорит X, план делает Y"])


class TestCommitRunDeviations(CommitCase):
    """Spec 2 of plan-refactoring-02: commit-run reports the deviations it wrote; the backlog never stops it."""

    def setUp(self):
        super().setUp()
        self.write("docs/plan01-impl.md", DEVIATION_PLAN)
        self.commit_all()
        self.run_plan({"app.py": "x = 2\n"})

    def test_backlog_field_and_a_repeated_call(self):
        result = self.commit()
        self.assertEqual((result["files"], result["backlog"]["appended"], result["backlog"]["exists"]),
                         (["app.py"], [TestBacklogDeviations.EXPECTED[0]], []))
        self.assertNotIn("BACKLOG.md", self.files_of())
        again = self.commit()
        self.assertEqual((again["empty"], again["backlog"]["exists"]), (True, [TestBacklogDeviations.EXPECTED[0]]))

    def test_without_brainstorm_tool_a_warning_and_the_commit(self):
        self.tool._load_brainstorm_tool = lambda: None
        result = self.commit()
        self.assertEqual((result["files"], result["sha"]), (["app.py"], self.git("rev-parse", "HEAD")))
        self.assertNotIn("backlog", result)
        self.assertTrue(result["warnings"][0].startswith("backlog-unavailable: "), result["warnings"])
        self.assertFalse((self.repo / "BACKLOG.md").exists())

    def test_a_backlog_that_is_not_utf8_is_a_warning(self):
        (self.repo / "BACKLOG.md").write_bytes("# Backlog\n\n## plan01\n\n- [ ] старое\n".encode("cp1251"))
        result = self.commit()
        self.assertEqual((result["files"], result["backlog"]["appended"]), (["app.py"], []))
        self.assertTrue(all(w.startswith("backlog-write-failed: ") for w in result["warnings"]), result["warnings"])

    def test_a_refused_commit_writes_nothing(self):
        with self.assertRaises(ValueError) as ctx:
            self.commit(subject="update stuff")  # bad-subject: refused before anything is committed
        self.assertEqual(ctx.exception.code, 2)
        self.assertFalse((self.repo / "BACKLOG.md").exists())
        result = self.commit()
        self.assertEqual((result["backlog"]["appended"], result["backlog"]["exists"]),
                         ([TestBacklogDeviations.EXPECTED[0]], []))


class TestCommitRefusals(CommitCase):
    def setUp(self):
        super().setUp()
        self.base = self.commit_all()
        self.run_plan({"app.py": "x = 2\n"})

    def refused(self, code, error, **kwargs):
        with self.assertRaises(ValueError) as ctx:
            self.commit(**kwargs)
        self.assertEqual((ctx.exception.code, self.git("rev-parse", "HEAD")), (code, self.base))
        self.assertIn(error, str(ctx.exception))
        return ctx.exception

    def test_old_ledger_without_baseline_head(self):
        led = self.tool._load(self.exec_dir)
        del led["baseline_head"]
        self.tool._save(self.exec_dir, led)
        self.refused(1, "baseline-head-unknown")

    def test_staged_changes_of_the_user(self):
        self.write("notes.txt", "x\n")
        self.git("add", "notes.txt")
        self.assertEqual(self.refused(1, "index-not-empty").details["staged"], ["notes.txt"])
        self.assertEqual(self.git("diff", "--cached", "--name-only"), "notes.txt")

    def test_subject_format_and_length(self):
        for subject in ("update stuff", "feat: no scope", "feature(plan01): wrong type",
                        "feat(plan01):no space", "feat(plan01): " + "x" * 59):
            self.refused(2, "bad-subject", subject=subject)
        self.assertEqual(self.git("diff", "--cached", "--name-only"), "")
        self.assertEqual(len(self.commit(subject="fix(plan01): " + "x" * 59)["subject"]), 72)

    def test_pruned_refs_alone_still_commit(self):
        self.tool.checkpoint_prune(str(self.repo), self.tool._load(self.exec_dir)["run_id"])
        self.assertEqual(self.commit()["files"], ["app.py"])

    def test_collected_snapshots_are_a_clear_refusal(self):
        self.tool.checkpoint_prune(str(self.repo), self.tool._load(self.exec_dir)["run_id"])
        self.git("gc", "-q", "--prune=now")
        self.refused(1, "snapshots-missing")

    def test_a_missing_expected_tree_points_to_accept_changes(self):  # f2
        led = self.tool._load(self.exec_dir)
        led["expected_tree"] = "0" * 40
        self.tool._save(self.exec_dir, led)
        error = self.refused(1, "snapshots-missing")
        self.assertIn("accept-changes", str(error))


class TestCommitRunState(CommitCase):
    def first_unit_done(self):
        self.base = self.commit_all()
        self.init()
        self.tool.unit_begin(self.exec_dir)
        self.write("app.py", "x = 2\n")
        self.tool.unit_finish(self.exec_dir, "task-1", "pass")

    def test_a_running_unit_is_refused(self):
        self.first_unit_done()
        self.tool.unit_begin(self.exec_dir)
        self.write("util.py", "y = 2  # half of task-2\n")
        with self.assertRaises(ValueError) as ctx:
            self.commit()
        self.assertEqual((ctx.exception.code, ctx.exception.details["units"]),
                         (1, [{"id": "task-2", "status": "running"}]))
        self.assertIn("run-incomplete", str(ctx.exception))
        self.assertEqual((self.git("rev-parse", "HEAD"), self.git("diff", "--cached", "--name-only")), (self.base, ""))

    def test_failed_and_pending_units_are_reported(self):
        self.first_unit_done()
        result = self.commit()
        self.assertEqual((result["files"], result["incomplete"]), (["app.py"], [{"id": "task-2", "status": "pending"}]))
        self.tool.unit_begin(self.exec_dir)
        self.tool.unit_finish(self.exec_dir, "task-2", "fail", error="gate failed")
        self.assertEqual(self.commit()["incomplete"], [{"id": "task-2", "status": "failed"}])

    def test_head_moved_off_the_start_line_is_refused(self):
        first = self.commit_all("first")
        self.write("util.py", "y = 2\n")
        start = self.commit_all("second")
        self.run_plan({"app.py": "x = 2\n"})
        self.git("checkout", "-q", "-b", "other", first)  # the run's uncommitted app.py comes along
        with self.assertRaises(ValueError) as ctx:
            self.commit()
        self.assertEqual((ctx.exception.code, ctx.exception.details), (1, {"baseline_head": start, "head": first}))
        self.assertIn("head-moved", str(ctx.exception))
        self.assertEqual((self.git("rev-parse", "HEAD"), self.git("diff", "--cached", "--name-only")), (first, ""))


class TestCommitConflicts(CommitCase):
    def set_fix_files(self, *files):
        """What plan-resolver records in the journal: audit.artifacts.fix_files of this plan."""
        journal = self.tool._load(self.exec_dir)["journal"]
        path = Path(journal["path"])
        data = json.loads(path.read_text(encoding="utf-8"))
        entry = next(plan for plan in data["plans"] if plan["id"] == journal["plan"])
        entry["stages"]["audit"].setdefault("artifacts", {})["fix_files"] = list(files)
        path.write_text(json.dumps(data), encoding="utf-8")

    def refused(self, error):
        head = self.git("rev-parse", "HEAD")
        with self.assertRaises(ValueError) as ctx:
            self.commit()
        self.assertEqual((ctx.exception.code, self.git("rev-parse", "HEAD")), (1, head))
        self.assertIn(error, str(ctx.exception))
        return ctx.exception.details["files"]

    def test_user_work_from_before_the_run_is_mixed(self):
        self.commit_all()
        self.write("app.py", "x = 1  # the user's uncommitted work\n")
        self.write("util.py", "y = 1  # uncommitted too, the run leaves it alone\n")
        self.run_plan({"app.py": "x = 2\n", "new.py": "z = 1\n"}, allow_dirty=True)
        self.assertEqual(self.refused("mixed-files"), ["app.py"])

    def test_change_after_the_last_unit_is_foreign(self):
        self.commit_all()
        self.run_plan({"app.py": "x = 2\n", "new.py": "z = 1\n"})
        self.write("app.py", "x = 2  # edited by hand after the run\n")
        self.assertEqual(self.refused("foreign-changes"), ["app.py"])

    def test_audit_fixes_and_user_commits_are_neither_foreign_nor_mixed(self):
        self.commit_all()
        self.run_plan({"app.py": "x = 2\n"})
        self.write("util.py", "y = 2\n")
        self.git("add", "util.py")
        self.git("commit", "-q", "-m", "the user's commit during the run")
        self.assertEqual(self.commit()["files"], ["app.py"])
        self.write("app.py", "x = 3\n")
        self.write("fix.py", "f = 1\n")
        self.set_fix_files("app.py", "fix.py")
        result = self.commit(subject="fix(plan01): apply the audit fixes")
        self.assertEqual((result["files"], self.files_of()), (["app.py", "fix.py"], ["app.py", "fix.py"]))

    def fail_second_unit_in_app_py(self):
        self.commit_all()
        self.init()
        self.tool.unit_begin(self.exec_dir)
        self.write("app.py", "x = 2\n")
        self.tool.unit_finish(self.exec_dir, "task-1", "pass")
        self.tool.unit_begin(self.exec_dir)
        self.write("app.py", "x = 2\nz = 'half of task-2'\n")
        return self.tool.unit_finish(self.exec_dir, "task-2", "fail", error="gate failed")

    def test_a_failed_attempt_left_in_place_is_refused(self):  # f1
        failed = self.fail_second_unit_in_app_py()
        self.assertEqual(self.refused("failed-attempt"), ["app.py"])
        with self.assertRaises(ValueError) as ctx:
            self.commit()
        self.assertIn("or were changed outside the run", str(ctx.exception))
        self.assertEqual(self.git("diff", "--cached", "--name-only"), "")
        self.tool.cmd_checkpoint_restore(types.SimpleNamespace(  # rolled back: the done unit's state commits
            workdir=str(self.repo), checkpoint_id=failed["restore_to"], exec_dir=self.exec_dir, paths=None))
        result = self.commit()
        self.assertEqual((result["files"], self.git("show", "HEAD:app.py")), (["app.py"], "x = 2"))

    def test_an_audit_fix_after_a_failed_attempt_commits(self):  # f1
        self.fail_second_unit_in_app_py()
        self.write("app.py", "x = 3\n")
        self.set_fix_files("app.py")
        self.assertEqual(self.commit(subject="fix(plan01): apply the audit fixes")["files"], ["app.py"])


class TestCommitHooks(CommitCase):
    def setUp(self):
        super().setUp()
        self.base = self.commit_all()
        self.run_plan({"app.py": "x = 2\n", "new.py": "z = 1\n"})

    def failing_hook(self):
        hook = self.repo / ".git" / "hooks" / "pre-commit"
        hook.write_bytes(b"#!/bin/sh\necho 'lint failed: app.py'\nexit 1\n")
        hook.chmod(0o755)

    def test_failing_hook_restores_the_index(self):
        self.failing_hook()
        with self.assertRaises(ValueError) as ctx:
            self.commit()
        self.assertIn("commit-failed", str(ctx.exception))
        self.assertIn("lint failed", str(ctx.exception))
        self.assertEqual(self.git("rev-parse", "HEAD"), self.base)
        self.assertEqual(self.git("diff", "--cached", "--name-only"), "")
        self.assertEqual((self.repo / "app.py").read_text(encoding="utf-8"), "x = 2\n")
        self.assertTrue((self.repo / "new.py").is_file())

    def test_git_never_skips_hooks_amends_pushes_or_forces(self):
        calls, real = [], self.tool._git

        def recording(workdir, *args, env=None):
            calls.append(args)
            return real(workdir, *args, env=env)

        self.tool._git = recording
        self.failing_hook()
        with self.assertRaises(ValueError):
            self.commit()
        (self.repo / ".git" / "hooks" / "pre-commit").unlink()
        self.commit()
        self.assertIn("commit", [arg for args in calls for arg in args])
        forbidden = {"--no-verify", "-n", "--amend", "push", "--force", "-f"}
        self.assertEqual([args for args in calls if forbidden & set(args)], [])


class TestCommitRunCli(CommitCase):
    def setUp(self):
        super().setUp()
        self.base = self.commit_all()
        self.run_plan({"app.py": "x = 2\n"})
        self.journal = Path(self.tool._load(self.exec_dir)["journal"]["path"])
        self.message = self.root / "message.txt"
        self.message.write_text("feat(plan01): add the feature\n\nGoal of the spec.\n", encoding="utf-8")

    def commits(self):
        data = json.loads(self.journal.read_text(encoding="utf-8"))
        return data["plans"][0]["stages"]["commit"].get("artifacts", {}).get("commits", [])

    def test_commit_is_recorded_in_the_journal(self):
        code, out = self.cli("commit-run", self.exec_dir, "--message-file", str(self.message))
        self.assertEqual((code, out["files"], out["sha"]), (0, ["app.py"], self.git("rev-parse", "HEAD")))
        self.assertNotIn("journal_error", out)
        self.assertEqual([(c["sha"], c["subject"], c["files"]) for c in self.commits()],
                         [(out["sha"], "feat(plan01): add the feature", ["app.py"])])

    def test_journal_argument_without_a_ledger_journal(self):
        led = self.tool._load(self.exec_dir)
        led["journal"] = None
        self.tool._save(self.exec_dir, led)
        code, out = self.cli("commit-run", self.exec_dir, "--message-file", str(self.message),
                             "--journal", str(self.journal))
        self.assertEqual(code, 0)
        self.assertEqual([c["sha"] for c in self.commits()], [out["sha"]])

    def test_a_missing_journal_does_not_stop_the_commit(self):
        missing = str(self.root / "gone-chain.json")
        code, out = self.cli("commit-run", self.exec_dir, "--message-file", str(self.message), "--journal", missing)
        self.assertEqual((code, out["files"]), (0, ["app.py"]))
        self.assertIn("journal-missing", out["journal_error"])

    def test_exit_codes_of_refusals(self):
        self.message.write_text("update\n", encoding="utf-8")
        code, out = self.cli("commit-run", self.exec_dir, "--message-file", str(self.message))
        self.assertEqual((code, out["ok"]), (2, False))
        self.assertIn("bad-subject", out["errors"][0])
        self.write("notes.txt", "x\n")
        self.git("add", "notes.txt")
        code, out = self.cli("commit-run", self.exec_dir, "--message-file", str(self.message))
        self.assertEqual((code, out["staged"]), (1, ["notes.txt"]))


class TestProjectFilesNamedLikeChainFiles(CommitCase):
    """F3: a chain-file name outside the run's plan folder is a project file: foreign changes see it, and
    the commit takes it as the run's work (F5 of plan-refactoring-02); the same name in the plan folder stays the
    pipeline's."""

    def setUp(self):
        super().setUp()
        (self.repo / "api").mkdir()
        self.write("api/openapi-spec.md", "v1\n")
        self.commit_all()

    def test_a_hand_edit_is_a_foreign_change(self):
        self.init()
        self.tool.unit_begin(self.exec_dir)
        self.write("app.py", "x = 2\n")
        self.tool.unit_finish(self.exec_dir, "task-1", "pass")
        self.write("api/openapi-spec.md", "v2, by hand\n")
        self.write("docs/g-spec.md", "a spec of the next goal\n")
        begun = self.tool.unit_begin(self.exec_dir)
        self.assertEqual(begun["reason"], "foreign-changes")
        self.assertEqual(begun["foreign_changes"], [{"path": "api/openapi-spec.md", "status": "modified"}])

    def test_commit_takes_it_as_the_runs_work(self):  # F5 of plan-refactoring-02
        self.run_plan({"app.py": "x = 2\n", "api/openapi-spec.md": "v2\n"})
        result = self.commit()
        self.assertEqual((result["files"], result["excluded"], result["excluded_outside_chain"]),
                         (["api/openapi-spec.md", "app.py"], [], []))


class TestRollbackOfProjectFilesNamedLikeChainFiles(RepoCase):
    """F3: with the ledger (--exec-dir) a rollback restores api/openapi-spec.md; the plan folder's own
    files stay as they are; without the ledger the name alone decides, as before."""

    def setUp(self):
        super().setUp()
        (self.repo / "api").mkdir()
        self.write("api/openapi-spec.md", "v1\n")
        self.write("docs/plan01-impl-review-1.md", "review 1\n")
        self.commit_all()
        self.led = self.init()
        self.tool.unit_begin(self.exec_dir)
        self.write("app.py", "x = 2\n")
        self.tool.unit_finish(self.exec_dir, "task-1", "pass")
        self.write("api/openapi-spec.md", "v2, by hand\n")
        self.write("docs/plan01-impl-review-1.md", "review 1, edited\n")
        self.write("docs/g-spec.md", "next goal\n")

    def read(self, rel):
        return (self.repo / rel).read_text(encoding="utf-8")

    def restore(self, **kwargs):
        args = dict(workdir=str(self.repo), checkpoint_id=self.led["baseline_checkpoint"],
                    exec_dir=self.exec_dir, paths=None)
        args.update(kwargs)
        return self.tool.cmd_checkpoint_restore(types.SimpleNamespace(**args))

    def test_full_rollback_with_the_ledger_returns_the_project_file(self):
        self.restore()
        self.assertEqual((self.read("api/openapi-spec.md"), self.read("app.py")), ("v1\n", "x = 1\n"))
        self.assertEqual(self.read("docs/plan01-impl-review-1.md"), "review 1, edited\n")
        self.assertEqual(self.read("docs/g-spec.md"), "next goal\n")

    def test_paths_rollback_with_the_ledger_takes_the_project_file(self):
        out = self.restore(paths=["api/openapi-spec.md"])
        self.assertEqual(out["restored"], ["api/openapi-spec.md"])
        self.assertEqual(self.read("api/openapi-spec.md"), "v1\n")
        events = self.tool._load(self.exec_dir)["foreign_events"]
        self.assertEqual([(e["decision"], [p["path"] for p in e["paths"]]) for e in events],
                         [("restored", ["api/openapi-spec.md"])])

    def test_without_the_ledger_the_name_alone_decides(self):
        self.restore(exec_dir=None)
        self.assertEqual(self.read("api/openapi-spec.md"), "v2, by hand\n")
        self.assertEqual(self.read("app.py"), "x = 1\n")


class TestRollbackKeepsTheRunJournalInAnotherFolder(RepoCase):
    """The run's own journal and its lock lie next to the spec; a spec outside the plan's folder puts them
    outside it, and a full rollback must still leave them alone (they are in no snapshot)."""

    def setUp(self):
        super().setUp()
        (self.repo / "specs").mkdir()
        self.write("specs/g-spec.md", "> Tier: Quick\n\n# Goal\n\nx\n")
        self.plan = self.write("docs/plan01-impl.md", "**Spec:** ../specs/g-spec.md\n\n" + PLAN)
        self.commit_all()
        self.led = self.init()
        self.tool.unit_begin(self.exec_dir)
        self.write("app.py", "x = 2\n")
        self.tool.unit_finish(self.exec_dir, "task-1", "pass")
        self.write("specs/g-chain.json", "{}\n")
        self.write("specs/g-chain.json.lock", "lock\n")

    def restore(self, **kwargs):
        args = dict(workdir=str(self.repo), checkpoint_id=self.led["baseline_checkpoint"],
                    exec_dir=self.exec_dir, paths=None)
        args.update(kwargs)
        return self.tool.cmd_checkpoint_restore(types.SimpleNamespace(**args))

    def test_full_rollback_keeps_the_journal_and_its_lock(self):
        self.restore()
        self.assertEqual((self.repo / "app.py").read_text(encoding="utf-8"), "x = 1\n")
        self.assertTrue((self.repo / "specs" / "g-chain.json").is_file())
        self.assertTrue((self.repo / "specs" / "g-chain.json.lock").is_file())

    def test_paths_rollback_does_not_take_the_journal(self):
        with self.assertRaisesRegex(self.tool.ToolError, "paths-empty"):
            self.restore(paths=["specs/g-chain.json", "specs/g-chain.json.lock"])
        self.assertTrue((self.repo / "specs" / "g-chain.json").is_file())


class TestDirtyCheckUntrackedFolders(RepoCase):
    """F6: git status lists an untracked folder as one entry (--untracked-files=normal); only such folders are
    listed file by file (one ls-files call), and every file is judged by _is_chain_file."""

    def setUp(self):
        super().setUp()
        self.commit_all()
        self.calls = []
        real = self.tool._git

        def spy(workdir, *args, env=None):
            self.calls.append(args)
            return real(workdir, *args, env=env)

        self.tool._git = spy

    def detect(self, **kwargs):
        return self.tool.checkpoint_detect(str(self.repo), **kwargs)

    def commands(self, name):
        return [args for args in self.calls if args[0] == name]

    def test_a_folder_of_chain_files_is_clean_and_listed_once(self):
        (self.repo / "docs" / "new").mkdir()
        self.write("docs/new/plan02-spec.md", "x\n")
        self.write("docs/new/plan02-impl.md", "x\n")
        self.assertEqual(self.detect(), {"vcs": "git", "dirty": False})
        self.assertIn("--untracked-files=normal", self.commands("status")[0])
        lists = self.commands("ls-files")
        self.assertEqual(len(lists), 1, lists)
        self.assertIn(":(top,literal)docs/new", lists[0])

    def test_a_project_file_in_the_folder_makes_it_dirty(self):
        (self.repo / "docs" / "new").mkdir()
        self.write("docs/new/plan02-spec.md", "x\n")
        self.write("docs/new/other.md", "x\n")
        self.assertTrue(self.detect()["dirty"])

    def test_show_untracked_files_no_changes_nothing(self):
        self.git("config", "status.showUntrackedFiles", "no")
        (self.repo / "tools").mkdir()
        self.write("tools/run.py", "x\n")
        self.assertTrue(self.detect()["dirty"])

    def test_a_failed_listing_counts_as_dirty(self):
        (self.repo / "docs" / "new").mkdir()
        self.write("docs/new/plan02-spec.md", "x\n")
        real = self.tool._git

        def failing(workdir, *args, env=None):
            if args[0] == "ls-files":
                raise self.tool.ToolError("ls-files failed", 1)
            return real(workdir, *args, env=env)

        self.tool._git = failing
        self.assertTrue(self.detect()["dirty"])

    def test_the_plan_folder_decides_with_plan_dir(self):  # F3
        (self.repo / "api").mkdir()
        self.write("api/openapi-spec.md", "x\n")
        self.write("docs/g-spec.md", "x\n")
        self.assertFalse(self.detect()["dirty"])  # no ledger: the name alone, as before
        self.assertTrue(self.detect(plan_dir="docs")["dirty"])
        (self.repo / "api" / "openapi-spec.md").unlink()
        (self.repo / "api").rmdir()
        self.assertFalse(self.detect(plan_dir="docs")["dirty"])


class TestOneDiffReport(CommitCase):
    def test_finalize_and_commit_share_one_report(self):  # spec plan-refactoring-03
        self.commit_all()
        self.run_plan({"app.py": "x = 2\n"})
        finalize = self.tool.run_diff_markdown(self.exec_dir)["markdown"]
        self.assertTrue(self.commit()["ok"])
        self.assertEqual(self.tool.run_diff_markdown(self.exec_dir)["markdown"], finalize)
        self.assertEqual(sorted(path.name for path in (self.repo / "docs").glob("*-diffs.md")), ["plan01-diffs.md"])


if __name__ == "__main__":
    unittest.main()
