"""Tests for the worktree snapshot of brainstorm_tool.py (spec 1 of plan-refactoring-05).

Run: python -m pytest skills/plan-brainstorming/tests/test_worktree_snapshot.py -q
"""
import hashlib
import importlib.util
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

TOOL = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts", "brainstorm_tool.py"))


def _load_module():
    spec = importlib.util.spec_from_file_location("brainstorm_tool", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ft = _load_module()


class SnapshotCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = os.path.realpath(tmp.name)

    def write(self, rel, data=b"x\n"):
        path = os.path.join(self.root, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)
        return path

    def git(self, *args):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=self.root,
                       capture_output=True, check=True)

    def repo(self, ignore=b"docs/.*/\n*.log\nbuild/\n"):
        """A repository with .gitignore and app.py committed and the ignored build/old.txt."""
        self.git("init", "-q")
        self.write(".gitignore", ignore)
        self.write("app.py", b"a = 1\n")
        self.write("build/old.txt", b"o\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")

    def diff(self, before, plan_dir=None, **kwargs):
        return ft.worktree_diff(before, ft.worktree_snapshot(self.root, plan_dir), plan_dir=plan_dir, **kwargs)


class SnapshotHelpersTest(SnapshotCase):
    def test_plan_folder_paths(self):
        self.assertEqual([ft._in_plan_dir(path, "docs/g") for path in ("docs/g/a.md", "docs/g/s/b.md", "docs/gx/a.md",
                                                                       "a.md")], [True, True, False, False])
        self.assertEqual([ft._in_plan_dir(path, "") for path in ("a.md", "build/", "docs/a.md")], [True, False, False])
        self.assertFalse(ft._in_plan_dir("a.md", None))

    def test_a_file_entry_and_an_unreadable_one(self):
        path = self.write("p.md", b"abc\n")
        warnings = []
        entry = ft._snapshot_file(self.root, "p.md", "!!", True, warnings)
        self.assertEqual(entry, ["!!", 4, os.stat(path).st_mtime_ns, hashlib.sha256(b"abc\n").hexdigest()])
        self.assertEqual(ft._snapshot_file(self.root, "gone.md", "", False, warnings), ["", "unreadable"])
        self.assertEqual(warnings, ["unreadable: gone.md"])


@unittest.skipUnless(shutil.which("git"), "git required")
class SnapshotGitHelpersTest(SnapshotCase):
    def test_a_failing_git_is_snapshot_failed(self):
        self.assertIsNone(ft._snapshot_top(self.root))  # not a repository
        with self.assertRaises(ft.SnapshotError) as ctx:
            ft._snapshot_status(self.root)
        self.assertTrue(str(ctx.exception).startswith("snapshot-failed: "), str(ctx.exception))

    def test_status_and_blobs_of_the_listed_paths(self):  # moved from executor_tool.py (spec 1 of 05)
        self.repo()
        os.remove(os.path.join(self.root, "app.py"))
        self.write("docs/new/a.md", b"n\n")
        self.assertEqual(ft._snapshot_top(self.root), self.root)
        listed = ft._snapshot_status(self.root)
        self.assertEqual(listed, [(" D", "app.py"), ("??", "docs/new/a.md")])
        warnings = []
        blobs = ft._snapshot_blobs(self.root, [path for _, path in listed], warnings)
        self.assertIsNone(blobs["app.py"])
        self.assertRegex(blobs["docs/new/a.md"], r"^[0-9a-f]{40,64}$")
        self.assertEqual(warnings, [])


class WalkSnapshotTest(SnapshotCase):
    def test_entries_by_the_root_gitignore(self):
        self.write(".gitignore", b"docs/.*/\n*.log\n")
        self.write("app.py", b"a = 1\n")
        self.write("top.log", b"l\n")
        self.write("docs/.plans/g/p.md", b"p\n")
        self.write(".git", b"gitdir: elsewhere\n")  # a worktree's .git file
        self.write(".git-dir/.git/config", b"x\n")  # a nested .git folder
        snap = ft._walk_snapshot(self.root, "docs/.plans/g", {"own.json"})
        self.assertEqual((snap["origin"], snap["head"], snap["root"], snap["plan_dir"], snap["warnings"]),
                         ("walk", None, self.root, "docs/.plans/g", []))
        entries = snap["entries"]
        self.assertEqual(sorted(entries), [".gitignore", "app.py", "docs/.plans/g/p.md", "top.log"])
        self.assertEqual((entries["app.py"][:2], len(entries["app.py"]), entries["top.log"][:2]),
                         (["", 6], 3, ["!!", 2]))
        self.assertEqual((entries["docs/.plans/g/p.md"][0], entries["docs/.plans/g/p.md"][3]),
                         ("!!", hashlib.sha256(b"p\n").hexdigest()))

    def test_without_gitignore_nothing_is_ignored_and_skip_is_left_out(self):
        self.write("x.log", b"1\n")
        self.write("own.json", b"{}\n")
        snap = ft._walk_snapshot(self.root, None, {"own.json"})
        self.assertEqual((sorted(snap["entries"]), snap["entries"]["x.log"][0]), (["x.log"], ""))

    def test_an_unreadable_file(self):
        self.write("a.md", b"1\n")
        with mock.patch.object(ft.os, "stat", side_effect=PermissionError("denied")):
            snap = ft._walk_snapshot(self.root, None, set())
        self.assertEqual((snap["entries"]["a.md"], snap["warnings"]), (["", "unreadable"], ["unreadable: a.md"]))


@unittest.skipUnless(shutil.which("git"), "git required")
class GitSnapshotTest(SnapshotCase):
    def setUp(self):
        super().setUp()
        self.repo()

    def test_fields_and_entries(self):
        self.write("app.py", b"a = 2\n")
        self.write("new.py", b"n\n")
        self.write("top.log", b"l\n")
        self.write("docs/.plans/g/g-1-impl.md", b"plan\n")
        snap = ft.worktree_snapshot(self.root, "docs/.plans/g")
        self.assertEqual((snap["origin"], snap["root"], snap["plan_dir"], snap["warnings"]),
                         ("git", self.root, "docs/.plans/g", []))
        self.assertIn(snap["head"]["branch"], ("master", "main"))
        self.assertRegex(snap["head"]["sha"], r"^[0-9a-f]{40,64}$")
        entries = snap["entries"]
        self.assertEqual(sorted(entries), ["app.py", "build/", "docs/.plans/", "docs/.plans/g/g-1-impl.md", "new.py",
                                           "top.log"])
        self.assertEqual((entries["app.py"][0], entries["new.py"][0], entries["top.log"], entries["build/"]),
                         (" M", "??", ["!!"], ["!!"]))
        self.assertRegex(entries["app.py"][1], r"^[0-9a-f]{40,64}$")
        plan = entries["docs/.plans/g/g-1-impl.md"]
        self.assertEqual((plan[0], plan[1], plan[3]), ("!!", 5, hashlib.sha256(b"plan\n").hexdigest()))
        self.assertNotIn("app.py", ft.worktree_snapshot(self.root, skip={"app.py"})["entries"])

    def test_a_plan_at_the_root_hashes_the_ignored_top_level_files(self):
        self.write("notes.log", b"1\n")
        self.write("src/n.log", b"1\n")
        entries = ft.worktree_snapshot(self.root, "")["entries"]
        self.assertEqual((len(entries["notes.log"]), entries["src/n.log"], entries["build/"]), (4, ["!!"], ["!!"]))

    def test_non_ascii_names(self):
        self.write("docs/заметки.md", b"n\n")
        self.assertEqual(ft.worktree_snapshot(self.root)["entries"]["docs/заметки.md"][0], "??")

    def test_unreadable_files_are_labelled(self):
        self.write("app.py", b"a = 2\n")
        self.write("docs/.plans/g/x.md", b"1\n")
        real = open

        def deny(path, *args, **kwargs):
            if str(path).endswith(("app.py", "x.md")):
                raise PermissionError(path)
            return real(path, *args, **kwargs)

        with mock.patch("builtins.open", side_effect=deny):
            snap = ft.worktree_snapshot(self.root, "docs/.plans/g")
        self.assertEqual((snap["entries"]["app.py"], snap["entries"]["docs/.plans/g/x.md"]),
                         ([" M", "unreadable"], ["!!", "unreadable"]))
        self.assertEqual(snap["warnings"], ["unreadable: app.py", "unreadable: docs/.plans/g/x.md"])

    def test_a_git_failure_is_snapshot_failed(self):
        with mock.patch.object(ft, "_snapshot_status", side_effect=ft.SnapshotError("snapshot-failed: boom")):
            with self.assertRaises(ft.SnapshotError):
                ft.worktree_snapshot(self.root)


class WalkDispatchTest(SnapshotCase):
    def test_without_git_the_snapshot_walks(self):
        self.write("a.md", b"1\n")
        with mock.patch.object(ft, "_snapshot_top", return_value=None):
            snap = ft.worktree_snapshot(self.root, None, skip={"own.json"})
        self.assertEqual((snap["origin"], sorted(snap["entries"])), ("walk", ["a.md"]))


@unittest.skipUnless(shutil.which("git"), "git required")
class GitDiffTest(SnapshotCase):
    def setUp(self):
        super().setUp()
        self.repo()

    def test_changes_and_their_classes(self):
        self.write("app.py", b"a = 2\n")
        self.write("docs/.plans/g/own.md", b"1\n")
        before = ft.worktree_snapshot(self.root, "docs/.plans/g")
        self.write("app.py", b"a = 3\n")  # a second write to a changed file
        self.write("new.py", b"n\n")
        self.write("top.log", b"l\n")
        self.write("build/new.txt", b"unseen\n")  # in an ignored folder outside the plan folder: the blind spot
        self.write("docs/.plans/g/own.md", b"2\n")
        out = self.diff(before, "docs/.plans/g")
        self.assertEqual((out["violations"], out["ignored_changed"], out["free"], out["head_moved"], out["origin"]),
                         (["app.py", "docs/.plans/g/own.md", "new.py"], ["top.log"], [], False, "git"))

    def test_a_plan_at_the_root(self):
        self.write("notes.log", b"1\n")
        self.write("build/a.log", b"1\n")
        before = ft.worktree_snapshot(self.root, "")
        self.write("notes.log", b"2\n")
        self.write("build/a.log", b"2\n")  # a file in an ignored folder is not hashed
        self.assertEqual(self.diff(before, "")["violations"], ["notes.log"])

    def test_a_commit_moves_head(self):
        before = ft.worktree_snapshot(self.root)
        self.write("app.py", b"a = 2\n")
        self.git("commit", "-qam", "next")
        out = self.diff(before)
        self.assertEqual((out["head_moved"], out["violations"]), (True, []))

    def test_a_change_of_readability_is_a_change(self):
        self.write("app.py", b"a = 2\n")
        with mock.patch.object(ft, "_snapshot_blobs", return_value={"app.py": "unreadable"}):
            before = ft.worktree_snapshot(self.root)
        self.assertEqual(self.diff(before)["violations"], ["app.py"])


class DiffTest(unittest.TestCase):
    def snap(self, entries, head=None):
        return {"origin": "git", "entries": entries, "head": head}

    def test_allowed_free_ignored_and_violations(self):
        before = self.snap({"gone.log": ["!!"], "p/old.md": ["!!", 1, 1, "a"]})
        after = self.snap({"a.py": ["??", "b"], "p/x-chain.json": ["!!", 1, 1, "c"], "n.log": ["!!"],
                           "p/own.md": ["!!", 1, 1, "d"], "docs/ok.md": [" M", "e"]})
        out = ft.worktree_diff(before, after, ["docs/"], "p", free=lambda path: path.endswith("-chain.json"))
        self.assertEqual(out["changed"], ["a.py", "docs/ok.md", "gone.log", "n.log", "p/old.md", "p/own.md",
                                          "p/x-chain.json"])
        self.assertEqual((out["free"], out["ignored_changed"], out["violations"]),
                         (["p/x-chain.json"], ["gone.log", "n.log"], ["a.py", "p/old.md", "p/own.md"]))
        out = ft.worktree_diff(before, after)  # no plan folder: every ignored path is information
        self.assertEqual(out["violations"], ["a.py", "docs/ok.md"])

    def test_head_is_a_flag(self):
        out = ft.worktree_diff(self.snap({}, {"sha": "1", "branch": "m"}), self.snap({}, {"sha": "2", "branch": "m"}))
        self.assertEqual((out["head_moved"], out["violations"]), (True, []))

    def test_ignored_paths_for_a_phantom_check(self):
        snap = {"plan_dir": "p", "entries": {"build/": ["!!"], "x.log": ["!!"], "p/a.md": ["!!", 1, 1, "h"]}}
        self.assertEqual([ft.worktree_ignored(snap, path) for path in
                          ("build/sub/o.txt", "x.log", "p/a.md", "p/b.md", "src/a.py")],
                         [True, True, False, False, False])


class WalkDiffTest(SnapshotCase):
    def test_sha256_sees_a_write_with_the_same_size_and_mtime(self):
        path = self.write("docs/.plans/g/p.md", b"aaaa\n")
        os.utime(path, ns=(1_000_000_000, 1_000_000_000))
        with mock.patch.object(ft, "_snapshot_top", return_value=None):
            before = ft.worktree_snapshot(self.root, "docs/.plans/g")
            self.write("docs/.plans/g/p.md", b"bbbb\n")
            os.utime(path, ns=(1_000_000_000, 1_000_000_000))
            self.assertEqual(self.diff(before, "docs/.plans/g")["violations"], ["docs/.plans/g/p.md"])

    def test_without_gitignore_nothing_is_ignored(self):
        with mock.patch.object(ft, "_snapshot_top", return_value=None):
            before = ft.worktree_snapshot(self.root)
            self.write("x.log", b"1\n")
            out = self.diff(before)
        self.assertEqual((out["violations"], out["ignored_changed"], out["origin"]), (["x.log"], [], "walk"))


if __name__ == "__main__":
    unittest.main()
