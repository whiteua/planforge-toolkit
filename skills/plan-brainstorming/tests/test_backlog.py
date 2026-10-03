"""Tests for the BACKLOG.md commands of brainstorm_tool.py.

Run: python -m pytest skills/plan-brainstorming/tests/test_backlog.py -q
"""
import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest


TOOL = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts", "brainstorm_tool.py"))


def _load_module():
    spec = importlib.util.spec_from_file_location("brainstorm_tool", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bt = _load_module()

BASE = "# Backlog\n\n## My notes\n\n- my idea\n\n## alpha\n\n- [ ] a1 — plan-executor, alpha-impl.md, 2026-09-01\n\n## beta\n\n- [ ] b1 — plan-resolver, beta-impl-report-1.md, 2026-09-02\n"


class BacklogKeyTest(unittest.TestCase):
    def test_key_ignores_mark_and_date_but_not_source(self):
        key = bt._backlog_key("- [ ] a1 — plan-executor, alpha-impl.md, 2026-09-01")
        self.assertEqual(key, bt._backlog_key("- [x] a1 — plan-executor, alpha-impl.md, 2026-10-01\r\n"))
        self.assertNotEqual(key, bt._backlog_key("- [ ] a1 — plan-resolver, alpha-impl-report-1.md, 2026-09-01"))
        self.assertEqual(bt._backlog_key("- alpha-1-spec.md — ядро"), "- alpha-1-spec.md — ядро")
        self.assertIsNone(bt._backlog_key("## alpha"))

    def test_lines_split_on_newline_only(self):
        self.assertEqual(bt._backlog_lines("a\r\nb c\nd"), ["a\r\n", "b c\n", "d"])
        self.assertEqual(bt._backlog_lines(""), [])


def _apply(text, section, entry):
    insertion = bt._backlog_insertion(text, section, entry)
    if insertion is None:
        return None
    offset, inserted = insertion
    return text[:offset] + inserted + text[offset:]


class BacklogInsertionTest(unittest.TestCase):
    def test_existing_section_appends_after_its_last_line(self):
        entry = "- [ ] a2 — plan-resolver, alpha-impl-report-1.md, 2026-10-01"
        result = _apply(BASE, "alpha", entry)
        self.assertEqual(result, BASE.replace("2026-09-01\n", "2026-09-01\n" + entry + "\n"))

    def test_missing_section_goes_to_file_end(self):
        entry = "- [ ] g1 — plan-brainstorming, gamma-spec.md, 2026-10-01"
        self.assertEqual(_apply(BASE, "gamma", entry), BASE + "\n## gamma\n\n" + entry + "\n")

    def test_same_item_and_source_is_duplicate_whatever_date_or_mark(self):
        same = "- [ ] a1 — plan-executor, alpha-impl.md, 2026-10-01"
        self.assertIsNone(bt._backlog_insertion(BASE, "alpha", same))
        self.assertIsNone(bt._backlog_insertion(BASE.replace("- [ ] a1", "- [x] a1"), "alpha", same))
        self.assertIsNotNone(bt._backlog_insertion(BASE, "beta", same))

    def test_crlf_and_missing_final_newline_are_kept(self):
        text = "# Backlog\r\n\r\n## alpha\r\n\r\n- [ ] a1 — x, y, 2026-09-01"
        self.assertEqual(_apply(text, "alpha", "- a2"), text + "\r\n- a2\r\n")

    def test_empty_section_keeps_blank_line_after_heading(self):
        text = "# Backlog\n\n## alpha\n\n## beta\n"
        self.assertEqual(_apply(text, "alpha", "- a1"), "# Backlog\n\n## alpha\n\n- a1\n\n## beta\n")


class BacklogFenceAndBomTest(unittest.TestCase):
    FENCED = ("# Backlog\n\n## My notes\n\n- my idea\n\n```md\n## alpha\n- [ ] example\n```\n\n"
              "## alpha\n\n- [ ] a1 — plan-executor, alpha-impl.md, 2026-09-01\n")

    def apply(self, text, section, entry):
        offset, inserted = bt._backlog_insertion(text, section, entry)
        return text[:offset] + inserted + text[offset:]

    def test_heading_inside_a_fence_is_not_a_section(self):
        new = self.apply(self.FENCED, "alpha", "- [ ] a2 — x, y, 2026-10-01")
        self.assertTrue(new.startswith(self.FENCED))
        self.assertTrue(new.endswith("2026-09-01\n- [ ] a2 — x, y, 2026-10-01\n"))

    def test_comment_inside_a_fence_does_not_end_the_section(self):
        text = "# Backlog\n\n## alpha\n\n```bash\n# comment\n```\n- [ ] a1 — p, q, 2026-09-01\n\n## beta\n"
        new = self.apply(text, "alpha", "- [ ] a2 — p, q, 2026-10-01")
        self.assertIn("2026-09-01\n- [ ] a2 — p, q, 2026-10-01\n\n## beta\n", new)

    def test_bom_before_the_first_heading_is_ignored(self):
        text = "﻿## alpha\n\n- [ ] a1 — p, q, 2026-09-01\n"
        new = self.apply(text, "alpha", "- [ ] a2 — p, q, 2026-10-01")
        self.assertEqual(new.count("## alpha"), 1)
        self.assertTrue(new.startswith("﻿"))

    def test_parse_skips_fenced_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "BACKLOG.md")
            with open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write(self.FENCED)
            items = bt.backlog_parse(path)["items"]
        self.assertEqual([(i["section"], i["text"]) for i in items], [("alpha", "a1")])

    def test_write_goes_through_a_temp_file_and_replace(self):
        calls = []
        real = bt.os.replace
        bt.os.replace = lambda src, dst: (calls.append((src, dst)), real(src, dst))[1]
        try:
            with tempfile.TemporaryDirectory() as tmp:
                bt.backlog_append(tmp, "alpha", "p, q", "a1", date="2026-10-01")
                self.assertEqual(len(calls), 1)
                self.assertEqual(os.path.dirname(calls[0][0]), os.path.abspath(tmp))
                self.assertEqual(calls[0][1], os.path.join(os.path.abspath(tmp), "BACKLOG.md"))
                self.assertEqual(sorted(os.listdir(tmp)), ["BACKLOG.md"])
        finally:
            bt.os.replace = real


class AtomicWriteTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name
        self.path = os.path.join(self.dir, "a.json")

    def _read(self, path):
        with open(path, "rb") as fh:
            return fh.read()

    def test_writes_utf8_bytes_and_leaves_no_temp_file(self):
        bt._atomic_write_text(self.path, "строка\nline\n")
        self.assertEqual(self._read(self.path), "строка\nline\n".encode("utf-8"))
        bt._atomic_write_text(self.path, "x\r\n")
        self.assertEqual(self._read(self.path), b"x\r\n")
        self.assertEqual(os.listdir(self.dir), ["a.json"])

    def test_failed_replace_keeps_the_file_and_removes_the_temp(self):
        with open(self.path, "wb") as fh:
            fh.write(b"old\n")
        real = bt.os.replace

        def failing_replace(src, dst):
            raise OSError("disk full")

        bt.os.replace = failing_replace
        try:
            with self.assertRaises(OSError):
                bt._atomic_write_text(self.path, "new\n")
        finally:
            bt.os.replace = real
        self.assertEqual(self._read(self.path), b"old\n")
        self.assertEqual(os.listdir(self.dir), ["a.json"])

    @unittest.skipIf(os.name == "nt", "file modes are checked on POSIX")
    def test_existing_mode_is_kept(self):
        for mode in (0o644, 0o664):
            with open(self.path, "wb") as fh:
                fh.write(b"old\n")
            os.chmod(self.path, mode)
            bt._atomic_write_text(self.path, "new\n")
            self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), mode)
            self.assertEqual(self._read(self.path), b"new\n")

    @unittest.skipIf(os.name == "nt", "file modes are checked on POSIX")
    def test_new_file_gets_the_umask_mode(self):
        # os.umask returns the previous mask; the cleanup restores it after the test.
        self.addCleanup(os.umask, os.umask(0o022))
        bt._atomic_write_text(self.path, "new\n")
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o644)
        self.assertEqual(self._read(self.path), b"new\n")

    @unittest.skipIf(os.name == "nt", "symlinks are checked on POSIX")
    def test_symlink_stays_and_its_target_is_written(self):
        shared = os.path.join(self.dir, "shared")
        os.mkdir(shared)
        target = os.path.join(shared, "a.json")
        with open(target, "wb") as fh:
            fh.write(b"old\n")
        os.symlink(target, self.path)
        bt._atomic_write_text(self.path, "new\n")
        self.assertTrue(os.path.islink(self.path))
        self.assertEqual(self._read(target), b"new\n")
        self.assertEqual(os.listdir(shared), ["a.json"])


class BacklogAppendTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.path = os.path.join(self.root, "BACKLOG.md")

    def tearDown(self):
        self._tmp.cleanup()

    def _read(self):
        with open(self.path, "rb") as fh:
            return fh.read()

    def test_creates_file_with_user_section_in_both_languages(self):
        out = bt.backlog_append(self.root, "alpha", "plan-executor, alpha-impl.md", "a1", date="2026-10-01")
        self.assertEqual((out["ok"], out["action"], out["section"]), (True, "created", "alpha"))
        self.assertEqual(out["path"], os.path.abspath(self.path))
        self.assertEqual(self._read().decode("utf-8"),
                         "# Backlog\n\n## My notes\n\n## alpha\n\n- [ ] a1 — plan-executor, alpha-impl.md, 2026-10-01\n")
        os.remove(self.path)
        bt.backlog_append(self.root, "alpha", "plan-executor, alpha-impl.md", "a1", lang="ru", date="2026-10-01")
        self.assertTrue(self._read().decode("utf-8").startswith("# Backlog\n\n## Свои заметки\n\n## alpha\n"))

    def test_order_duplicate_and_plain(self):
        bt.backlog_append(self.root, "alpha", "plan-executor, alpha-impl.md", "a1", date="2026-10-01")
        bt.backlog_append(self.root, "alpha", "plan-executor, alpha-impl.md", "a2", date="2026-10-01")
        again = bt.backlog_append(self.root, "alpha", "plan-executor, alpha-impl.md", "a1", date="2026-10-02")
        self.assertEqual(again["action"], "exists")
        out = bt.backlog_append(self.root, "alpha", "plan-brainstorming, alpha-spec.md", "alpha-1-spec.md — ядро", plain=True)
        self.assertEqual(out["action"], "appended")
        self.assertEqual(self._read().decode("utf-8").splitlines()[-3:], [
            "- [ ] a1 — plan-executor, alpha-impl.md, 2026-10-01",
            "- [ ] a2 — plan-executor, alpha-impl.md, 2026-10-01",
            "- alpha-1-spec.md — ядро",
        ])

    def test_user_section_and_bad_input_are_refused(self):
        for section in ("My notes", "Свои заметки", "my notes", " MY NOTES ", "свои ЗАМЕТКИ"):
            with self.assertRaisesRegex(bt.BacklogError, "^user-section: "):
                bt.backlog_append(self.root, section, "plan-executor, x.md", "a1")
        self.assertTrue(bt._is_user_section("My Notes"))
        self.assertFalse(bt._is_user_section("My notes 2"))
        with self.assertRaises(bt.InputError):
            bt.backlog_append(self.root, "alpha", "plan-executor, x.md", "two\nlines")
        with self.assertRaises(bt.InputError):
            bt.backlog_append(self.root, "alpha", "plan-executor, x.md", "a1", date="01.10.2026")
        self.assertFalse(os.path.exists(self.path))

    def test_bytes_outside_insertion_and_user_section_unchanged(self):
        original = ("# Backlog\r\n\r\n## Свои заметки\r\n\r\n- моя идея\r\n\r\n## alpha\r\n\r\n"
                    "- [ ] a1 — x, y, 2026-09-01\r\n\r\n## beta\r\n")
        with open(self.path, "wb") as fh:
            fh.write(original.encode("utf-8"))
        bt.backlog_append(self.root, "alpha", "plan-resolver, alpha-impl-report-1.md", "a2", date="2026-10-01")
        inserted = "- [ ] a2 — plan-resolver, alpha-impl-report-1.md, 2026-10-01\r\n".encode("utf-8")
        data = self._read()
        self.assertEqual(data.replace(inserted, b"", 1), original.encode("utf-8"))
        self.assertLess(data.index(inserted), data.index(b"## beta"))

    def test_append_writes_through_atomic_write_text(self):
        calls = []
        real = bt._atomic_write_text
        bt._atomic_write_text = lambda path, text: (calls.append((path, text)), real(path, text))[1]
        try:
            bt.backlog_append(self.root, "alpha", "p, q", "a1", date="2026-10-01")
        finally:
            bt._atomic_write_text = real
        self.assertEqual(calls, [(os.path.abspath(self.path), self._read().decode("utf-8"))])

    @unittest.skipIf(os.name == "nt", "file modes and symlinks are checked on POSIX")
    def test_append_keeps_mode_and_symlink(self):
        shared = os.path.join(self.root, "shared")
        os.mkdir(shared)
        target = os.path.join(shared, "BACKLOG.md")
        with open(target, "wb") as fh:
            fh.write("# Backlog\n\n## alpha\n\n- [ ] a1 — p, q, 2026-09-01\n".encode("utf-8"))
        os.chmod(target, 0o644)
        os.symlink(target, self.path)
        out = bt.backlog_append(self.root, "alpha", "p, q", "a2", date="2026-10-01")
        self.assertEqual(out["action"], "appended")
        self.assertTrue(os.path.islink(self.path))
        self.assertEqual(stat.S_IMODE(os.stat(target).st_mode), 0o644)
        self.assertTrue(self._read().decode("utf-8").endswith("2026-09-01\n- [ ] a2 — p, q, 2026-10-01\n"))
        self.assertEqual(os.listdir(shared), ["BACKLOG.md"])

    def test_non_utf8_file_is_not_written(self):
        original = "# Backlog\n\n## alpha\n\n- [ ] старое\n".encode("cp1251")
        with open(self.path, "wb") as fh:
            fh.write(original)
        with self.assertRaises(bt.BacklogError):
            bt.backlog_append(self.root, "alpha", "plan-executor, x.md", "a1")
        self.assertEqual(self._read(), original)


class BacklogParseTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._tmp.name, "BACKLOG.md")
        text = BASE + "- [x] b2 — plan-executor, beta-impl.md, 2026-09-03\n- [ ] свой пункт без источника\n"
        with open(self.path, "wb") as fh:
            fh.write(text.replace("- my idea", "- [ ] my idea").encode("utf-8"))

    def tearDown(self):
        self._tmp.cleanup()

    def test_only_unchecked_items_with_section_source_date(self):
        items = bt.backlog_parse(self.path)["items"]
        self.assertEqual([item["text"] for item in items], ["my idea", "a1", "b1", "свой пункт без источника"])
        self.assertEqual(items[1], {"section": "alpha", "text": "a1", "source": "plan-executor, alpha-impl.md",
                                    "date": "2026-09-01", "line": 9})
        self.assertEqual(items[0]["section"], "My notes")
        self.assertEqual((items[3]["source"], items[3]["date"]), (None, None))

    def test_section_filter(self):
        out = bt.backlog_parse(self.path, "beta")
        self.assertTrue(out["ok"])
        self.assertEqual([item["text"] for item in out["items"]], ["b1", "свой пункт без источника"])
        self.assertEqual(bt.backlog_parse(self.path, "gamma")["items"], [])


MARK_BASE = ("# Backlog\n\n## My notes\n\n- [ ] a1\n\n## alpha\n\n- [ ] a1 — plan-executor, alpha-impl.md, 2026-09-01\n"
             "- [x] done one — plan-resolver, r.md, 2026-09-02\n```\n- [ ] a2\n```\n- [ ] a2\n- [ ] twin\n- [ ] twin\n"
             "\n## beta\n\n- [ ] a1 — plan-resolver, beta.md, 2026-09-03\n")


class BacklogMarkLinesTest(unittest.TestCase):
    def find(self, section, item, text=MARK_BASE):
        return bt._backlog_mark_lines(bt._backlog_lines(text), section, item)

    def test_item_text_follows_backlog_parse(self):
        self.assertEqual(bt._backlog_item_text("a1 — plan-executor, alpha-impl.md, 2026-09-01"),
                         ("a1", "plan-executor, alpha-impl.md", "2026-09-01"))
        self.assertEqual(bt._backlog_item_text("без источника — просто тире"), ("без источника — просто тире", None, None))

    def test_lines_of_one_section_outside_fences(self):
        self.assertEqual(self.find("alpha", "a1"), ([8], []))
        self.assertEqual(self.find("beta", "a1"), ([19], []))
        self.assertEqual(self.find("alpha", "a2"), ([13], []))  # the fenced copy (index 11) is not an item
        self.assertEqual(self.find("alpha", "done one"), ([], [9]))
        self.assertEqual(self.find("alpha", "twin"), ([14, 15], []))
        self.assertEqual(self.find("alpha", "nope"), ([], []))
        self.assertEqual(self.find("gamma", "a1"), ([], []))

    def test_crlf_and_bom(self):
        text = "﻿## alpha\r\n\r\n- [ ] a1\r\n"
        self.assertEqual(self.find("alpha", "a1", text), ([2], []))


class BacklogMarkTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name
        self.path = os.path.join(self.root, "BACKLOG.md")

    def write(self, text, encoding="utf-8"):
        with open(self.path, "wb") as fh:
            fh.write(text.encode(encoding))
        return text.encode(encoding)

    def read(self):
        with open(self.path, "rb") as fh:
            return fh.read()

    def test_marks_one_line_and_nothing_else(self):
        original = self.write(MARK_BASE.replace("\n", "\r\n"))
        out = bt.backlog_mark(self.root, "beta", "a1")
        self.assertEqual((out["ok"], out["action"], out["line"]), (True, "marked", 20))
        data = self.read()
        self.assertEqual(len(data), len(original))
        self.assertEqual([i for i, (a, b) in enumerate(zip(original, data)) if a != b],
                         [original.index(b"- [ ] a1 \xe2\x80\x94 plan-resolver, beta.md") + 3])
        self.assertEqual(bt.backlog_mark(self.root, "beta", "a1")["action"], "already")
        self.assertEqual(bt.backlog_mark(self.root, "alpha", "a1")["action"], "marked")  # same text, other section

    def test_not_found_ambiguous_and_fenced_leave_the_file(self):
        original = self.write(MARK_BASE)
        missing = bt.backlog_mark(self.root, "alpha", "nope")
        self.assertEqual((missing["ok"], missing["action"]), (False, "not-found"))
        twin = bt.backlog_mark(self.root, "alpha", "twin")
        self.assertEqual((twin["ok"], twin["action"], twin["lines"]), (False, "ambiguous", [15, 16]))
        self.assertEqual(self.read(), original)
        self.assertEqual(bt.backlog_mark(self.root, "alpha", "a2")["line"], 14)  # not the fenced line 12
        self.assertIn(b"```\n- [ ] a2\n```", self.read())

    def test_user_section_non_utf8_and_missing_file(self):
        self.assertEqual(bt.backlog_mark(self.root, "alpha", "a1")["action"], "not-found")
        self.write(MARK_BASE)
        for section in ("My notes", "свои заметки"):
            with self.assertRaisesRegex(bt.BacklogError, "^user-section: "):
                bt.backlog_mark(self.root, section, "a1")
        original = self.write("# Backlog\n\n## alpha\n\n- [ ] старое\n", "cp1251")
        with self.assertRaises(bt.BacklogError):
            bt.backlog_mark(self.root, "alpha", "старое")
        self.assertEqual(self.read(), original)


def _run(*args):
    proc = subprocess.run([sys.executable, TOOL, *args], capture_output=True, encoding="utf-8")
    return proc.returncode, (json.loads(proc.stdout) if proc.stdout.strip() else None)


class BacklogCliTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_append_then_parse(self):
        args = ["backlog-append", self.root, "--section", "alpha", "--source", "plan-resolver, alpha-impl-report-1.md",
                "--item", "проверить таймаут", "--lang", "ru", "--date", "2026-10-01"]
        code, out = _run(*args)
        self.assertEqual((code, out["action"]), (0, "created"), out)
        code, out = _run(*args)
        self.assertEqual((code, out["action"]), (0, "exists"), out)
        code, out = _run("backlog-append", self.root, "--section", "alpha", "--source", "plan-brainstorming, alpha-spec.md",
                         "--item", "alpha-1-spec.md — ядро", "--plain")
        self.assertEqual((code, out["action"]), (0, "appended"), out)
        code, out = _run("backlog-parse", os.path.join(self.root, "BACKLOG.md"), "--section", "alpha")
        self.assertEqual(code, 0, out)
        self.assertEqual([(i["text"], i["source"], i["date"]) for i in out["items"]],
                         [("проверить таймаут", "plan-resolver, alpha-impl-report-1.md", "2026-10-01")])

    def test_exit_codes(self):
        code, out = _run("backlog-append", self.root, "--section", "my notes", "--source", "s, a", "--item", "x")
        self.assertEqual((code, out["ok"]), (1, False))
        self.assertTrue(out["errors"][0].startswith("user-section: "), out)
        self.assertFalse(os.path.exists(os.path.join(self.root, "BACKLOG.md")))
        code, _ = _run("backlog-parse", os.path.join(self.root, "missing.md"))
        self.assertEqual(code, 2)
        with open(os.path.join(self.root, "BACKLOG.md"), "wb") as fh:
            fh.write("# Backlog\n\n## alpha\n\n- [ ] старое\n".encode("cp1251"))
        code, out = _run("backlog-append", self.root, "--section", "alpha", "--source", "s, a", "--item", "x")
        self.assertEqual((code, out["ok"]), (1, False))

    def test_mark_exit_codes(self):
        with open(os.path.join(self.root, "BACKLOG.md"), "wb") as fh:
            fh.write(MARK_BASE.encode("utf-8"))
        args = ("backlog-mark", self.root, "--section", "beta", "--item", "a1")
        self.assertEqual([(code, out["action"]) for code, out in (_run(*args), _run(*args))],
                         [(0, "marked"), (0, "already")])
        code, out = _run("backlog-mark", self.root, "--section", "alpha", "--item", "twin")
        self.assertEqual((code, out["action"], out["lines"]), (1, "ambiguous", [15, 16]))
        self.assertEqual(_run("backlog-mark", self.root, "--section", "alpha", "--item", "nope")[0], 1)
        code, out = _run("backlog-mark", self.root, "--section", "My notes", "--item", "a1")
        self.assertEqual((code, out["ok"]), (1, False))
        self.assertTrue(out["errors"][0].startswith("user-section: "), out)
        self.assertEqual(_run("backlog-mark", self.root, "--section", "alpha", "--item", " ")[0], 2)


if __name__ == "__main__":
    unittest.main()
