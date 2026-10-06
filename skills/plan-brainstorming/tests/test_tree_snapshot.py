"""Tests for tree_snapshot / tree_diff of brainstorm_tool.py (spec 2 of plan-refactoring-04).

Run: python -m pytest skills/plan-brainstorming/tests/test_tree_snapshot.py -q
"""
import hashlib
import importlib.util
import os
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


class TreeCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name

    def write(self, rel, data=b"x\n"):
        path = os.path.join(self.root, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)
        return path


class TreeSnapshotTest(TreeCase):
    def test_every_file_with_size_and_sha256(self):
        self.write("app.py", b"a = 1\n")
        self.write("docs/.plans/g/g-1-impl.md", b"plan\n")
        self.write(".gitignore", b"docs/.*/\n*.log\n")
        self.write("build.log", b"ignored by git\n")
        snap = ft.tree_snapshot(self.root)
        self.assertEqual(sorted(snap), [".gitignore", "app.py", "build.log", "docs/.plans/g/g-1-impl.md"])
        self.assertEqual(snap["app.py"], [6, hashlib.sha256(b"a = 1\n").hexdigest(), None, None])

    def test_skipped_directories_git_and_paths(self):
        self.write("keep.md")
        for name in ft.TREE_SKIP_DIRS + (".git",):
            self.write(f"{name}/inner.txt")
            self.write(f"sub/{name}/deep.txt")
        self.write("own/delegate.json")
        self.assertEqual(sorted(ft.tree_snapshot(self.root, skip={"own/delegate.json"})), ["keep.md"])
        self.assertEqual(ft.TREE_SKIP_DIRS,
                         ("node_modules", ".venv", "venv", "__pycache__", ".pytest_cache", "dist", "build"))


class TreeLabelsTest(TreeCase):
    def test_large_file_keeps_size_and_mtime(self):
        path = self.write("big.bin", b"0123456789")
        os.utime(path, ns=(1_000_000_000, 1_000_000_000))
        with mock.patch.object(ft, "TREE_LARGE_BYTES", 4):
            before = ft.tree_snapshot(self.root)
            self.assertEqual(before["big.bin"], [10, None, 1_000_000_000, "large"])
            self.write("big.bin", b"abcdefghij")  # same size, other bytes, same mtime: no hash, so unseen
            os.utime(path, ns=(1_000_000_000, 1_000_000_000))
            self.assertEqual(ft.tree_diff(before, ft.tree_snapshot(self.root)), [])
            os.utime(path, ns=(2_000_000_000, 2_000_000_000))
            self.assertEqual(ft.tree_diff(before, ft.tree_snapshot(self.root)), ["big.bin"])
            self.write("big.bin", b"0123456789AB")
            os.utime(path, ns=(1_000_000_000, 1_000_000_000))
            self.assertEqual(ft.tree_diff(before, ft.tree_snapshot(self.root)), ["big.bin"])
        self.assertEqual(ft.TREE_LARGE_BYTES, 8 * 1024 * 1024)

    def test_unreadable_file_and_its_change(self):
        path = self.write("secret.txt", b"s\n")
        real = ft._tree_file_sha256

        def deny(target):
            if os.path.abspath(target) == os.path.abspath(path):
                raise PermissionError(target)
            return real(target)

        with mock.patch.object(ft, "_tree_file_sha256", side_effect=deny):
            before = ft.tree_snapshot(self.root)
        self.assertEqual(before["secret.txt"], [2, None, None, "unreadable"])
        self.assertEqual(ft.tree_diff(before, ft.tree_snapshot(self.root)), ["secret.txt"])


class TreeDiffTest(TreeCase):
    def test_changed_appeared_and_gone(self):
        for name in ("a.md", "b.md", "c.md"):
            self.write(name, b"1\n")
        before = ft.tree_snapshot(self.root)
        self.write("a.md", b"2\n")
        os.remove(os.path.join(self.root, "b.md"))
        self.write("d/new.md")
        self.assertEqual(ft.tree_diff(before, ft.tree_snapshot(self.root)), ["a.md", "b.md", "d/new.md"])
        self.assertEqual(ft.tree_diff(before, before), [])

    def test_a_directory_link_is_not_walked(self):  # tree_snapshot of Task 1; checked here to keep Task 1 small
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        with open(os.path.join(outside.name, "far.md"), "w", encoding="utf-8") as fh:
            fh.write("far\n")
        try:
            os.symlink(outside.name, os.path.join(self.root, "link"), target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlinks unavailable: {exc}")
        self.assertEqual(ft.tree_snapshot(self.root), {})


if __name__ == "__main__":
    unittest.main()
