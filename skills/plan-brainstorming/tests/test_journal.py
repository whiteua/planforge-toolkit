"""Tests for the chain journal commands of brainstorm_tool.py.

Run: python -m pytest skills/plan-brainstorming/tests/test_journal.py -q
"""
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock


TOOL = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts", "brainstorm_tool.py"))


def _load_module():
    spec = importlib.util.spec_from_file_location("brainstorm_tool", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bt = _load_module()


class JournalBasicsTest(unittest.TestCase):
    def test_constants(self):
        self.assertEqual(bt.STAGES, ("writing", "revision", "split", "execution", "diffs", "audit", "commit"))
        self.assertEqual(set(bt.STAGE_OWNERS), set(bt.STAGES))
        self.assertEqual(bt.REENTRY_REASONS, ("drift", "audit-open", "recommit", "user-request"))
        self.assertIn("lock-takeover", bt.EVENT_KINDS)
        self.assertEqual((bt.LOCK_WAIT_SECONDS, bt.LOCK_STALE_SECONDS), (10.0, 60.0))

    def test_iso_now_follows_now(self):
        with mock.patch.object(bt, "_now", return_value=86400.0):
            self.assertEqual(bt._iso_now(), "1970-01-02T00:00:00Z")

    def test_main_maps_journal_error_to_exit_1(self):
        def fail(args):
            raise bt.JournalError("illegal-transition: writing pending → done")

        with mock.patch.object(bt, "cmd_detect_lang", fail), contextlib.redirect_stdout(io.StringIO()) as out:
            code = bt.main(["detect-lang", TOOL])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out.getvalue()), {"ok": False, "errors": ["illegal-transition: writing pending → done"]})


SPEC = "> Tier: Quick\n> Backlog: alpha\n\n# Goal\n\nЖурнал цепочки для цели.\n"
PLAN = "# Alpha\n\n**Spec:** alpha-1-spec.md\n\n**Tier:** Quick\n\n### Task 1: Первая задача\n\nТекст.\n"
SOURCE = "# Alpha {}\n\n> Source: [alpha-1-impl.md](alpha-1-impl.md)\n"


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


class JournalCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = os.path.realpath(tmp.name)
        self.spec = _write(os.path.join(self.dir, "alpha-1-spec.md"), SPEC)
        self.plan = _write(os.path.join(self.dir, "alpha-1-impl.md"), PLAN)
        self.journal = os.path.join(self.dir, "alpha-chain.json")


class JournalPathTest(JournalCase):
    def test_spec_plan_roadmap_and_part_share_one_journal(self):
        roadmap = _write(os.path.join(self.dir, "alpha-1-impl-roadmap.md"), SOURCE.format("roadmap"))
        part = _write(os.path.join(self.dir, "alpha-1-impl-a.md"), SOURCE.format("part a"))
        for path in (self.spec, self.plan, roadmap, part):
            out = bt.journal_path_for(path)
            self.assertEqual((out["journal"], out["goal"], out["spec"]), (self.journal, "alpha", self.spec))
            self.assertFalse(out["exists"])
        self.assertEqual(bt.journal_path_for(part)["plan"], self.plan)
        self.assertIsNone(bt.journal_path_for(self.spec)["plan"])

    def test_goal_without_backlog_line_is_spec_name(self):
        spec = _write(os.path.join(self.dir, "beta-2-spec.md"), SPEC.replace("> Backlog: alpha\n", ""))
        out = bt.journal_path_for(spec)
        self.assertEqual((out["goal"], os.path.basename(out["journal"])), ("beta-2", "beta-2-chain.json"))

    def test_plan_without_spec_keeps_journal_next_to_plan(self):
        plan = _write(os.path.join(self.dir, "sub", "gamma-impl.md"), "# Gamma\n\n### Task 1: x\n")
        out = bt.journal_path_for(plan)
        self.assertEqual((out["goal"], out["spec"], out["plan"]), ("gamma", None, plan))
        self.assertEqual(out["journal"], os.path.join(self.dir, "sub", "gamma-chain.json"))

    def test_missing_spec_and_unsafe_goal_are_input_errors(self):
        unsafe = _write(os.path.join(self.dir, "x-spec.md"), SPEC.replace("> Backlog: alpha", "> Backlog: ../evil"))
        with self.assertRaisesRegex(bt.InputError, "journal-goal-invalid"):
            bt.journal_path_for(unsafe)
        os.remove(self.spec)
        with self.assertRaisesRegex(bt.InputError, "journal-source-missing"):
            bt.journal_path_for(self.plan)


class JournalLoadLockTest(JournalCase):
    def test_missing_and_corrupt_journal(self):
        with self.assertRaisesRegex(bt.InputError, "journal-missing"):
            bt.journal_load(self.journal)
        for text in ("{not json", "[]", '{"version": 2}'):
            _write(self.journal, text)
            with self.assertRaisesRegex(bt.InputError, "journal-corrupt"):
                bt.journal_load(self.journal)

    def test_lock_is_exclusive_and_released(self):
        lock = self.journal + ".lock"
        with bt._journal_lock(self.journal) as took_over:
            self.assertFalse(took_over)
            with open(lock, encoding="utf-8") as fh:
                self.assertEqual(json.load(fh)["pid"], os.getpid())
            with mock.patch.object(bt, "LOCK_WAIT_SECONDS", 0.2):
                with self.assertRaisesRegex(bt.JournalError, "journal-locked: "):
                    with bt._journal_lock(self.journal):
                        self.fail("a held lock was taken twice")
            self.assertTrue(os.path.exists(lock))
        self.assertFalse(os.path.exists(lock))

    def test_abandoned_lock_is_taken_over(self):
        lock = _write(self.journal + ".lock", json.dumps({"pid": 1, "at": bt._now()}))
        os.utime(lock, (bt._now() - 61, bt._now() - 61))  # the age is the file's mtime
        with bt._journal_lock(self.journal) as took_over:
            self.assertTrue(took_over)
            with open(lock, encoding="utf-8") as fh:
                self.assertEqual(json.load(fh)["pid"], os.getpid())
        self.assertEqual(sorted(os.listdir(self.dir)), ["alpha-1-impl.md", "alpha-1-spec.md"])

    def test_second_takeover_keeps_the_fresh_lock(self):
        lock = _write(self.journal + ".lock", "{}")
        os.utime(lock, (bt._now() - 120, bt._now() - 120))
        real_age, calls = bt._lock_age, []

        def a_takes_over_first(path):
            # B has judged the lock abandoned; before B moves it, A takes it over and writes its own.
            if not calls:
                os.remove(path)
                _write(path, json.dumps({"pid": "A"}))
            calls.append(path)
            return 120.0 if len(calls) == 1 else real_age(path)

        with mock.patch.object(bt, "_lock_age", a_takes_over_first), mock.patch.object(bt, "LOCK_WAIT_SECONDS", 0.2):
            with self.assertRaisesRegex(bt.JournalError, "journal-locked: "):
                with bt._journal_lock(self.journal):
                    self.fail("B took over A's fresh lock")
        with open(lock, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh), {"pid": "A"})
        self.assertEqual(sorted(os.listdir(self.dir)), ["alpha-1-impl.md", "alpha-1-spec.md", "alpha-chain.json.lock"])

    def test_release_retries_a_busy_lock(self):
        real_remove, failures = os.remove, [PermissionError(13, "in use"), PermissionError(13, "in use")]

        def busy_then_free(path):  # Windows: a waiter's open handle blocks the removal for a moment
            if path.endswith(".lock") and failures:
                raise failures.pop()
            real_remove(path)

        with mock.patch.object(bt.os, "remove", busy_then_free):
            with bt._journal_lock(self.journal):
                pass
        self.assertEqual((failures, os.path.exists(self.journal + ".lock")), ([], False))


class JournalUpdateTest(JournalCase):
    def setUp(self):
        super().setUp()
        _write(self.journal, json.dumps(bt._new_journal("alpha", "ru")))

    def test_mutation_is_saved_and_result_returned(self):
        self.assertEqual(bt.journal_update(self.journal, lambda data: data["specs"].append({"path": "x"}) or 7), 7)
        self.assertEqual(bt.journal_load(self.journal)["specs"], [{"path": "x"}])
        self.assertEqual(sorted(os.listdir(self.dir)), ["alpha-1-impl.md", "alpha-1-spec.md", "alpha-chain.json"])
        stamp = os.stat(self.journal).st_mtime_ns
        bt.journal_update(self.journal, lambda data: None)
        self.assertEqual(os.stat(self.journal).st_mtime_ns, stamp)  # nothing changed: not rewritten

    def test_corrupt_and_missing_journal_are_not_written(self):
        _write(self.journal, "{broken")
        with self.assertRaisesRegex(bt.InputError, "journal-corrupt"):
            bt.journal_update(self.journal, lambda data: data.clear())
        with open(self.journal, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "{broken")
        with self.assertRaisesRegex(bt.InputError, "journal-missing"):
            bt.journal_update(os.path.join(self.dir, "none-chain.json"), lambda data: None)

    def test_lock_takeover_is_logged(self):
        lock = _write(self.journal + ".lock", json.dumps({"pid": 1, "at": bt._now() - 61}))
        os.utime(lock, (bt._now() - 61, bt._now() - 61))  # Task 12: the age is the file's mtime
        bt.journal_update(self.journal, lambda data: None)
        events = bt.journal_load(self.journal)["events"]
        self.assertEqual([(e["kind"], e["data"]) for e in events], [("lock-takeover", {"lock": self.journal + ".lock"})])
        self.assertFalse(os.path.exists(self.journal + ".lock"))


class JournalWriteFailureTest(JournalCase):
    def setUp(self):
        super().setUp()
        _write(self.journal, json.dumps(bt._new_journal("alpha", "ru")))
        self.files = sorted(os.listdir(self.dir))

    def add_spec(self):
        return bt.journal_update(self.journal, lambda data: data["specs"].append({"path": "x", "sha256": "0"}))

    def test_failed_replace_is_a_json_error_without_a_temp_file(self):
        with mock.patch.object(bt, "cmd_detect_lang", lambda args: (0, self.add_spec())), \
                mock.patch.object(bt.os, "replace", side_effect=PermissionError(13, "denied")), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            code = bt.main(["detect-lang", TOOL])
        result = json.loads(out.getvalue())
        self.assertEqual((code, result["ok"]), (1, False))
        self.assertTrue(result["errors"][0].startswith("journal-write-failed: "), result)
        self.assertEqual(sorted(os.listdir(self.dir)), self.files)
        self.assertEqual(bt.journal_load(self.journal)["specs"], [])

    def test_read_only_journal_leaves_no_temp_file(self):
        os.chmod(self.journal, 0o444)  # Windows: os.replace onto a read-only file fails
        self.addCleanup(os.chmod, self.journal, 0o666)
        try:
            self.add_spec()
        except bt.JournalError as exc:  # Windows; POSIX replaces a read-only file in a writable folder
            self.assertTrue(str(exc).startswith("journal-write-failed: "), exc)
        self.assertEqual(sorted(os.listdir(self.dir)), self.files)


def _run(*args):
    proc = subprocess.run([sys.executable, TOOL, *args], capture_output=True, encoding="utf-8")
    return proc.returncode, (json.loads(proc.stdout) if proc.stdout.strip() else None)


class JournalCreateTest(JournalCase):
    def test_cli_create_registers_spec_once(self):
        code, out = _run("journal-path", self.plan, "--create")
        self.assertEqual((code, out["created"], out["exists"], out["journal"]), (0, True, True, self.journal))
        data = bt.journal_load(self.journal)
        self.assertEqual((data["goal"], data["lang"], data["events"]), ("alpha", "ru", []))
        self.assertEqual([(p["id"], p["spec"], p["plan"]) for p in data["plans"]],
                         [("alpha-1-impl", "alpha-1-spec.md", "alpha-1-impl.md")])
        self.assertEqual({stage["status"] for stage in data["plans"][0]["stages"].values()}, {"pending"})
        self.assertEqual(data["specs"], [{"path": "alpha-1-spec.md", "sha256": bt._sha256(self.spec)}])
        self.assertEqual(data["limits"], {"enabled": False, "time_minutes": None, "cost": None})
        code, out = _run("journal-path", self.spec, "--create")
        self.assertEqual((code, out["created"]), (0, False))
        self.assertEqual(len(bt.journal_load(self.journal)["specs"]), 1)

    def test_cli_without_create_and_corrupt_journal(self):
        code, out = _run("journal-path", self.spec)
        self.assertEqual((code, out["exists"]), (0, False))
        self.assertFalse(os.path.exists(self.journal))
        _write(self.journal, "{broken")
        code, out = _run("journal-path", self.spec, "--create")
        self.assertEqual(code, 2)
        self.assertIn("journal-corrupt", out["errors"][0])

    def test_journal_rel_uses_forward_slashes(self):
        nested = os.path.join(self.dir, "sub", "p-impl.md")
        self.assertEqual(bt._journal_rel(self.journal, nested), "sub/p-impl.md")

    def test_cli_create_from_a_spec_or_a_roadmap(self):
        self.assertEqual(_run("journal-path", self.spec, "--create")[0], 0)
        self.assertEqual(bt.journal_load(self.journal)["plans"], [])  # a spec registers only itself
        roadmap = _write(os.path.join(self.dir, "alpha-1-impl-roadmap.md"), SOURCE.format("roadmap"))
        for _ in range(2):
            self.assertEqual(_run("journal-path", roadmap, "--create")[0], 0)
        self.assertEqual([p["id"] for p in bt.journal_load(self.journal)["plans"]], ["alpha-1-impl"])


class JournalTransitionTest(JournalCase):
    def setUp(self):
        super().setUp()
        bt.journal_create(self.journal, "alpha", "ru", self.spec)
        self.data = bt.journal_load(self.journal)
        self.entry = bt._plan_entry(self.data, self.journal, self.plan)

    def check(self, stage, old, new, reason=None):
        bt._check_transition(self.data, self.entry, stage, old, new, reason, self.journal)

    def test_plan_entry_is_created_once_with_the_only_spec(self):
        self.assertEqual((self.entry["id"], self.entry["spec"], self.entry["plan"]),
                         ("alpha-1-impl", "alpha-1-spec.md", "alpha-1-impl.md"))
        self.assertEqual(self.entry["stages"], {stage: {"status": "pending"} for stage in bt.STAGES})
        self.assertIs(bt._plan_entry(self.data, self.journal, "alpha-1-impl"), self.entry)
        self.assertIs(bt._plan_entry(self.data, self.journal, "docs/alpha-1-impl.MD"), self.entry)
        for plan, create in (("other-impl", True), ("other-impl.md", False)):
            with self.assertRaisesRegex(bt.InputError, "unknown-plan"):
                bt._plan_entry(self.data, self.journal, plan, create=create)

    def test_allowed_and_illegal_transitions(self):
        for old, new in (("pending", "running"), ("pending", "skipped"), ("running", "done"), ("running", "stopped"),
                         ("running", "failed"), ("running", "skipped"), ("stopped", "running"),
                         ("failed", "running"), ("done", "done"), ("skipped", "skipped")):
            self.check("execution", old, new)
        for old, new in (("pending", "done"), ("skipped", "running"), ("done", "pending"), ("stopped", "done"),
                         ("failed", "done"), ("running", "pending")):
            with self.assertRaisesRegex(bt.JournalError, f"illegal-transition: execution {old} → {new}"):
                self.check("execution", old, new)

    def test_reentry_needs_one_of_four_reasons(self):
        self.check("commit", "done", "running", "recommit")
        self.check("revision", "done", "running", "user-request")
        self.check("audit", "done", "running", "user-request")
        self.entry["stages"]["audit"]["artifacts"] = {"status": "open"}
        self.check("audit", "done", "running", "audit-open")
        self.entry["stages"]["audit"]["artifacts"] = {"status": "final"}
        for stage, reason in (("audit", "audit-open"), ("writing", None), ("writing", "later"), ("writing", "drift"),
                              ("execution", "recommit"), ("split", "user-request")):
            with self.assertRaisesRegex(bt.JournalError, f"illegal-transition: {stage} done → running"):
                self.check(stage, "done", "running", reason)

    def test_drift_reentry_needs_an_answered_question_or_a_changed_input(self):
        self.entry["stages"]["writing"].update(input="alpha-1-spec.md", input_sha256=bt._sha256(self.spec))
        question = {"id": "Q1", "plan": "alpha-1-impl", "stage": "writing", "status": "open",
                    "text": "drift: writing input changed: alpha-1-spec.md"}
        self.data["questions"] = [question]
        with self.assertRaisesRegex(bt.JournalError, "illegal-transition: writing done → running"):
            self.check("writing", "done", "running", "drift")  # the question is not answered yet
        for status in ("answered", "applied"):
            question["status"] = status
            self.check("writing", "done", "running", "drift")
        self.data["questions"] = []
        _write(self.spec, SPEC + "\nИзменение.\n")
        self.check("writing", "done", "running", "drift")  # the input changed since done
        with self.assertRaisesRegex(bt.JournalError, "illegal-transition: revision done → running"):
            self.check("revision", "done", "running", "drift")  # no drift question, no stored input

    def test_stopped_stage_resumes_only_without_open_questions(self):
        self.data["questions"] = [{"id": f"Q{n}", "plan": "alpha-1-impl", "stage": "execution", "status": status}
                                  for n, status in ((1, "open"), (2, "answered"), (3, "open"))]
        with self.assertRaisesRegex(bt.JournalError, "open-questions: Q1, Q3"):
            self.check("execution", "stopped", "running")
        self.check("audit", "stopped", "running")


class JournalEventTest(JournalCase):
    def setUp(self):
        super().setUp()
        bt.journal_create(self.journal, "alpha", "ru", self.spec)

    def event(self, stage, status, **kwargs):
        return bt.journal_event(self.journal, "plan-writing", self.plan, stage, status, **kwargs)

    def stage(self, name):
        return bt.journal_load(self.journal)["plans"][0]["stages"][name]

    def test_first_event_creates_plan_and_done_stores_input_hash(self):
        out = self.event("writing", "running")
        self.assertEqual(out, {"ok": True, "plan": "alpha-1-impl", "stage": "writing",
                               "from": "pending", "to": "running", "changed": True})
        self.event("writing", "done", input_path=self.spec, artifacts=["plan=alpha-1-impl.md"])
        record = self.stage("writing")
        self.assertEqual((record["status"], record["input"], record["input_sha256"]),
                         ("done", "alpha-1-spec.md", bt._sha256(self.spec)))
        self.assertEqual(record["artifacts"], {"plan": "alpha-1-impl.md"})
        self.assertTrue(record["started_at"] <= record["finished_at"])
        events = bt.journal_load(self.journal)["events"]
        self.assertEqual([(e["kind"], e["skill"], e["plan"], e["data"]) for e in events],
                         [("stage-start", "plan-writing", "alpha-1-impl", {"from": "pending", "to": "running"}),
                          ("stage-end", "plan-writing", "alpha-1-impl", {"from": "running", "to": "done"})])

    def test_same_status_merges_artifacts(self):
        self.event("split", "running", artifacts=["parts[]=a.md"])
        out = self.event("split", "running", artifacts=["parts[]=a.md", "parts[]=b.md", "roadmap=r.md"], data={"n": 2})
        self.assertFalse(out["changed"])
        self.assertEqual(self.stage("split")["artifacts"], {"parts": ["a.md", "b.md"], "roadmap": "r.md"})
        last = bt.journal_load(self.journal)["events"][-1]
        self.assertEqual((last["kind"], last["data"]), ("stage-update", {"n": 2, "from": "running", "to": "running"}))
        for status in ("running", "done", "done"):
            self.event("diffs", status, artifacts=["diffs=alpha-1-diffs.md"])
        self.assertEqual(bt.journal_load(self.journal)["events"][-1]["kind"], "diffs-rebuilt")


class JournalEventCliTest(JournalCase):
    def test_cli_event_exit_codes_and_untouched_journal_on_error(self):
        bt.journal_create(self.journal, "alpha", "ru", self.spec)
        base = ["journal-event", self.journal, "--skill", "plan-resolver", "--plan", self.plan, "--stage", "audit"]
        code, out = _run(*base, "--status", "running", "--artifact", "fix_files[]=a.py", "--data", '{"pass": 1}')
        self.assertEqual((code, out["to"], out["changed"]), (0, "running", True))
        code, out = _run(*base, "--status", "done", "--artifact", "status=final", "--input", self.plan)
        self.assertEqual((code, out["from"], out["to"]), (0, "running", "done"))
        stamp = os.stat(self.journal).st_mtime_ns
        code, out = _run(*base, "--status", "pending")
        self.assertEqual((code, out["errors"]), (1, ["illegal-transition: audit done → pending"]))
        self.assertEqual(_run(*base, "--status", "running")[0], 1)  # re-entry without --reason
        self.assertEqual(_run(*base, "--status", "running", "--reason", "audit-open")[0], 1)  # report final
        # The stored status decides, not this call's artifacts; drift needs an answer or a changed input.
        for extra in (["--reason", "audit-open", "--artifact", "status=open"], ["--reason", "drift"]):
            code, out = _run(*base, "--status", "running", *extra)
            self.assertEqual(code, 1, extra)
            self.assertTrue(out["errors"][0].startswith("illegal-transition: audit done → running"), out)
        for extra in (["--data", "[1]"], ["--artifact", "novalue"], ["--status", "finished"]):
            self.assertEqual(_run(*base, "--status", "done", *extra)[0], 2)
        self.assertEqual(os.stat(self.journal).st_mtime_ns, stamp)
        code, out = _run(*base, "--status", "done", "--artifact", "status=open")  # a later report is open
        self.assertEqual((code, out["changed"]), (0, False))
        code, out = _run(*base, "--status", "running", "--reason", "audit-open")
        self.assertEqual((code, out["from"], out["to"]), (0, "done", "running"))
        last = bt.journal_load(self.journal)["events"][-1]
        self.assertEqual((last["kind"], last["data"]), ("stage-start", {"from": "done", "to": "running", "reason": "audit-open"}))


class JournalQuestionTest(JournalCase):
    def setUp(self):
        super().setUp()
        bt.journal_create(self.journal, "alpha", "ru", self.spec)
        bt.journal_event(self.journal, "plan-executor", self.plan, "execution", "running")

    def test_unit_event_keeps_stage(self):
        out = bt.journal_unit(self.journal, "alpha-1-impl", "unit-finish", {"unit": "a-3", "done": 1, "total": 4})
        self.assertEqual(out, {"ok": True, "plan": "alpha-1-impl", "kind": "unit-finish"})
        data = bt.journal_load(self.journal)
        self.assertEqual(data["plans"][0]["stages"]["execution"]["status"], "running")
        last = data["events"][-1]
        self.assertEqual((last["skill"], last["stage"], last["kind"], last["data"]),
                         ("plan-executor", "execution", "unit-finish", {"unit": "a-3", "done": 1, "total": 4}))
        with self.assertRaisesRegex(bt.InputError, "unknown unit event kind"):
            bt.journal_unit(self.journal, "alpha-1-impl", "unit-x", {})

    def test_silent_question_stops_running_stage(self):
        out = bt.journal_question(self.journal, "plan-executor", self.plan, "execution", "Откатить?", ["да", "нет"])
        self.assertEqual(out, {"ok": True, "id": "Q1", "status": "open", "stage_status": "stopped"})
        data = bt.journal_load(self.journal)
        question = data["questions"][0]
        self.assertEqual((question["options"], question["answer"], question["answered_at"]), (["да", "нет"], None, None))
        self.assertEqual([e["kind"] for e in data["events"]][-2:], ["stage-end", "question"])
        with self.assertRaisesRegex(bt.JournalError, "open-questions: Q1"):
            bt.journal_event(self.journal, "plan-executor", self.plan, "execution", "running")

    def test_interactive_question_keeps_stage(self):
        out = bt.journal_question(self.journal, "plan-executor", self.plan, "execution", "Дальше?", answer="да")
        self.assertEqual((out["id"], out["status"], out["stage_status"]), ("Q1", "answered", "running"))
        out = bt.journal_question(self.journal, "plan-resolver", self.plan, "audit", "Аудит?")
        self.assertEqual((out["id"], out["status"], out["stage_status"]), ("Q2", "open", "pending"))
        self.assertEqual(bt.journal_load(self.journal)["questions"][0]["answer"], "да")


class JournalQuestionSpecTest(JournalCase):
    def setUp(self):
        super().setUp()
        self.spec2 = _write(os.path.join(self.dir, "alpha-2-spec.md"), SPEC)
        self.plan2 = os.path.join(self.dir, "alpha-2-impl.md")  # not written yet: a question before plan-writing
        bt.journal_create(self.journal, "alpha", "ru", self.spec)
        bt.journal_create(self.journal, "alpha", "ru", self.spec2)

    def entry(self, plan_id):
        return next(p for p in bt.journal_load(self.journal)["plans"] if p["id"] == plan_id)

    def test_a_question_with_spec_creates_the_entry_with_it(self):
        bt.journal_question(self.journal, "plan-chain-runner", self.plan2, "execution", "dirty-worktree: x",
                            ["allow-dirty", "stop"], answer="allow-dirty", spec=self.spec2)
        self.assertEqual(self.entry("alpha-2-impl")["spec"], "alpha-2-spec.md")

    def test_an_entry_without_spec_gets_it_and_a_different_spec_is_refused(self):
        bt.journal_question(self.journal, "plan-chain-runner", self.plan2, "execution", "first?")
        self.assertIsNone(self.entry("alpha-2-impl")["spec"])  # two specs: no fallback
        bt.journal_question(self.journal, "plan-chain-runner", self.plan2, "execution", "second?", spec=self.spec2)
        self.assertEqual(self.entry("alpha-2-impl")["spec"], "alpha-2-spec.md")
        before = bt.journal_load(self.journal)
        with self.assertRaisesRegex(bt.InputError, "^journal-plan-unknown: "):
            bt.journal_question(self.journal, "plan-chain-runner", self.plan2, "execution", "third?", spec=self.spec)
        self.assertEqual(bt.journal_load(self.journal), before)
        with self.assertRaisesRegex(bt.InputError, "^journal-plan-unknown: "):
            bt.journal_event(self.journal, "plan-writing", self.plan2, "writing", "running", spec=self.spec)


class JournalQuestionCliTest(JournalCase):
    def test_cli_unit_and_question(self):
        bt.journal_create(self.journal, "alpha", "ru", self.spec)
        bt.journal_event(self.journal, "plan-executor", self.plan, "execution", "running")
        code, out = _run("journal-unit", self.journal, "--plan", "alpha-1-impl", "--kind", "unit-begin",
                         "--data", '{"unit": "a-1", "done": 0, "total": 2}')
        self.assertEqual((code, out["kind"]), (0, "unit-begin"))
        self.assertEqual(_run("journal-unit", self.journal, "--plan", "alpha-1-impl", "--kind", "unit-begin",
                              "--data", "[]")[0], 2)
        code, out = _run("journal-question", self.journal, "--skill", "plan-executor", "--plan", self.plan,
                         "--stage", "execution", "--text", "Откатить юнит?", "--option", "да", "--option", "нет")
        self.assertEqual((code, out["id"], out["status"], out["stage_status"]), (0, "Q1", "open", "stopped"))
        self.assertEqual(bt.journal_load(self.journal)["questions"][0]["options"], ["да", "нет"])
        self.assertEqual(_run("journal-question", self.journal, "--skill", "x", "--plan", "nope",
                              "--stage", "execution", "--text", "?")[0], 2)

    def test_cli_question_with_spec(self):
        spec2 = _write(os.path.join(self.dir, "alpha-2-spec.md"), SPEC)
        bt.journal_create(self.journal, "alpha", "ru", self.spec)
        bt.journal_create(self.journal, "alpha", "ru", spec2)
        plan2 = os.path.join(self.dir, "alpha-2-impl.md")
        base = ("journal-question", self.journal, "--skill", "plan-chain-runner", "--plan", plan2,
                "--stage", "execution", "--text", "dirty-worktree: x")
        code, out = _run(*base, "--spec", spec2)
        self.assertEqual((code, out["id"]), (0, "Q1"))
        self.assertEqual(bt.journal_load(self.journal)["plans"][-1]["spec"], "alpha-2-spec.md")
        code, out = _run(*base, "--spec", self.spec)
        self.assertEqual(code, 2)
        self.assertTrue(out["errors"][0].startswith("journal-plan-unknown: "), out)


class JournalAnswerTest(JournalCase):
    def setUp(self):
        super().setUp()
        bt.journal_create(self.journal, "alpha", "ru", self.spec)
        bt.journal_event(self.journal, "plan-executor", self.plan, "execution", "running")
        bt.journal_question(self.journal, "plan-executor", self.plan, "execution", "Откатить?", ["да", "нет"])

    def test_open_answered_applied_and_resume(self):
        code, out = _run("journal-answer", self.journal, "Q1", "--answer", "да")
        self.assertEqual((code, out), (0, {"ok": True, "id": "Q1", "status": "answered"}))
        bt.journal_event(self.journal, "plan-executor", self.plan, "execution", "running")
        code, out = _run("journal-answer", self.journal, "Q1", "--applied")
        self.assertEqual((code, out["status"]), (0, "applied"))
        data = bt.journal_load(self.journal)
        question = data["questions"][0]
        self.assertEqual((question["answer"], bool(question["answered_at"]), bool(question["applied_at"])), ("да", True, True))
        self.assertEqual([e["kind"] for e in data["events"]][-3:], ["answer", "stage-start", "applied"])

    def test_errors(self):
        with self.assertRaisesRegex(bt.JournalError, "illegal-transition: Q1 open → applied"):
            bt.journal_answer(self.journal, "Q1", applied=True)
        with self.assertRaisesRegex(bt.JournalError, "answer-required: Q1"):
            bt.journal_answer(self.journal, "Q1")
        code, out = _run("journal-answer", self.journal, "Q9", "--answer", "да")
        self.assertEqual((code, out["errors"]), (2, ["unknown-question: Q9"]))
        self.assertEqual(_run("journal-answer", self.journal, "Q1", "--applied")[0], 1)


class JournalFindingTest(JournalCase):
    def setUp(self):
        super().setUp()
        bt.journal_create(self.journal, "alpha", "ru", self.spec)

    def finding(self, **kwargs):
        return bt.journal_finding(self.journal, "plan-resolver", self.plan, "src/a.py", "Нет проверки пути.",
                                  "Путь ../x выходит из корня.", **kwargs)

    def test_ids_duplicates_and_backlog(self):
        root = os.path.join(self.dir, "repo")
        os.makedirs(root)
        self.assertEqual(self.finding(line=7, backlog_root=root),
                         {"ok": True, "id": "F1", "action": "recorded", "backlog": "appended"})
        with open(os.path.join(root, "BACKLOG.md"), encoding="utf-8") as fh:
            self.assertIn("## alpha\n\n- [ ] Нет проверки пути. (src/a.py:7) — plan-resolver, alpha-1-impl.md, ", fh.read())
        self.assertEqual(self.finding(backlog_root=root)["action"], "exists")
        code, out = _run("journal-finding", self.journal, "--skill", "plan-executor", "--plan", self.plan,
                         "--file", "./src/b.py", "--summary", "Другое.", "--failure-scenario", "Сбой.")
        self.assertEqual((code, out["id"], out["backlog"]), (0, "F2", None))
        findings = bt.journal_load(self.journal)["findings"]
        self.assertEqual([(f["id"], f["file"], f["line"], f["backlog"]) for f in findings],
                         [("F1", "src/a.py", 7, "appended"), ("F2", "src/b.py", None, None)])

    def test_backlog_failure_keeps_the_finding(self):
        out = self.finding(backlog_root=os.path.join(self.dir, "missing"))
        self.assertEqual((out["action"], out["backlog"]), ("recorded", "failed"))
        self.assertIn("root is not a directory", out["backlog_error"])
        self.assertEqual(bt.journal_load(self.journal)["findings"][0]["backlog"], "failed")
        notes = os.path.join(self.dir, "notes-chain.json")
        bt.journal_create(notes, "My notes", "en", self.spec)  # a goal equal to the user section
        out = bt.journal_finding(notes, "plan-resolver", self.plan, "a.py", "S.", "F.", backlog_root=self.dir)
        self.assertEqual(out["backlog"], "failed")
        self.assertFalse(os.path.exists(os.path.join(self.dir, "BACKLOG.md")))
        self.assertEqual(_run("journal-finding", self.journal, "--skill", "s", "--plan", self.plan, "--file", "a",
                              "--summary", " ", "--failure-scenario", "f")[0], 2)


class JournalCommitExportTest(JournalCase):
    def setUp(self):
        super().setUp()
        bt.journal_create(self.journal, "alpha", "ru", self.spec)

    def test_commit_is_recorded_once_without_transition(self):
        args = ["journal-commit", self.journal, "--plan", self.plan, "--sha", "a" * 40,
                "--subject", "feat(alpha-1): journal", "--file", "a.py", "--file", "b.py"]
        self.assertEqual(_run(*args)[1]["commits"], 1)
        self.assertEqual(_run(*args)[1]["commits"], 1)
        data = bt.journal_load(self.journal)
        stage = data["plans"][0]["stages"]["commit"]
        self.assertEqual((stage["status"], stage["artifacts"]["commits"][0]["files"]), ("pending", ["a.py", "b.py"]))
        self.assertEqual([e["kind"] for e in data["events"]], ["commit"])
        self.assertEqual(_run("journal-commit", self.journal, "--plan", self.plan, "--sha", "zz", "--subject", "x")[0], 2)

    def test_export_passes_findings_parse(self):
        self.assertEqual(bt.journal_export_findings(self.journal)["count"], 0)
        followups = os.path.join(self.dir, "alpha-followups.json")
        with open(followups, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "[]\n")
        bt.journal_finding(self.journal, "plan-executor", self.plan, "a.py", "Первая.", "Сбой 1.", line=3)
        bt.journal_finding(self.journal, "plan-resolver", self.plan, "b.py", "Вторая.", "Сбой 2.")
        code, out = _run("journal-export-findings", self.journal)
        self.assertEqual((code, out["path"], out["count"]), (0, followups, 2))
        code, parsed = _run("findings-parse", followups)
        self.assertEqual((code, parsed["errors"]), (0, []))
        self.assertEqual([(f["id"], f["file"], f["line"]) for f in parsed["findings"]],
                         [("F1", "a.py", 3), ("F2", "b.py", None)])

    def record(self, count):
        for n in range(1, count + 1):
            bt.journal_finding(self.journal, "plan-resolver", self.plan, f"src/f{n}.py", f"Находка {n}.", f"Сбой {n}.")

    def export(self, items):
        followups = _write(os.path.join(self.dir, "alpha-followups.json"),
                           json.dumps(items, ensure_ascii=False, indent=2) + "\n")
        code, out = _run("journal-export-findings", self.journal)
        with open(followups, encoding="utf-8") as fh:
            return code, out, json.load(fh)

    def test_bl33_export_keeps_the_file_items_the_journal_lacks(self):
        self.record(8)
        items = [{"file": "./src/f1.py" if n == 1 else f"src/f{n}.py", "line": None, "summary": f"Находка {n}.",
                  "failure_scenario": f"Сбой {n}."} for n in range(1, 9)]
        items[3:3] = [{"file": f"old/o{n}.py", "line": n, "summary": f"Старая {n}.", "failure_scenario": "Сбой."}
                      for n in range(1, 7)]
        code, out, exported = self.export(items)
        self.assertEqual((code, out["count"], exported), (0, 14, items))

    def test_bl33_journal_findings_missing_from_the_file_follow_by_id(self):
        self.record(3)
        kept = [{"file": "src/f2.py", "line": None, "summary": "Находка 2.", "failure_scenario": "Сбой 2."},
                {"file": "old/o1.py", "line": 4, "summary": "Старая.", "failure_scenario": "Сбой."}]
        code, out, exported = self.export(kept)
        self.assertEqual((code, out["count"]), (0, 4))
        self.assertEqual([(item["file"], item["summary"]) for item in exported],
                         [("src/f2.py", "Находка 2."), ("old/o1.py", "Старая."),
                          ("src/f1.py", "Находка 1."), ("src/f3.py", "Находка 3.")])

    def test_bl33_a_file_that_is_not_a_json_list_is_left_as_it_is(self):
        followups = os.path.join(self.dir, "alpha-followups.json")
        for text in ("{broken", '{"findings": []}\n'):
            with self.subTest(text=text):
                _write(followups, text)
                code, out = _run("journal-export-findings", self.journal)
                self.assertEqual((code, out["ok"]), (2, False))
                self.assertTrue(out["errors"][0].startswith("followups-unreadable: " + followups))
                with open(followups, encoding="utf-8") as fh:
                    self.assertEqual(fh.read(), text)


class JournalSchemaTest(unittest.TestCase):
    def test_schema_names_match_the_code(self):
        path = os.path.join(os.path.dirname(TOOL), "..", "assets", "chain-journal.schema.json")
        with open(path, encoding="utf-8") as fh:
            schema = json.load(fh)
        self.assertEqual(schema["$schema"], "http://json-schema.org/draft-07/schema#")
        self.assertEqual(schema["required"], list(bt._new_journal("alpha", "ru")))
        definitions = schema["definitions"]
        self.assertEqual(tuple(definitions["status"]["enum"]), bt.STAGE_STATUSES)
        self.assertEqual(tuple(definitions["plan"]["properties"]["stages"]["required"]), bt.STAGES)
        self.assertEqual(tuple(definitions["event"]["properties"]["kind"]["enum"]), bt.EVENT_KINDS)


import importlib.util  # noqa: E402 - the J2 classes below are self-contained
import json  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402

_J2_TOOL = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts", "brainstorm_tool.py"))
_j2_spec = importlib.util.spec_from_file_location("brainstorm_tool_j2", _J2_TOOL)
j2 = importlib.util.module_from_spec(_j2_spec)
_j2_spec.loader.exec_module(j2)


def _j2_run(*args):
    proc = subprocess.run([sys.executable, _J2_TOOL, *args], capture_output=True, text=True, encoding="utf-8")
    return proc.returncode, (json.loads(proc.stdout) if proc.stdout.strip() else {})


def _j2_write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return path


def _j2_event(plan, stage, kind, **data):
    return {"at": "2026-10-02T10:00:00Z", "skill": "t", "plan": plan, "stage": stage, "kind": kind, "data": data}


def _j2_journal(tmp, plans=None, events=(), questions=(), findings=()):
    """A journal written directly as JSON: goal 'g'; plans = {id: {stage: status or stage dict}}."""
    data = {"version": 1, "goal": "g", "lang": "en", "created_at": "2026-10-02T10:00:00Z",
            "specs": [{"path": "g-spec.md", "sha256": "0" * 64}], "plans": [],
            "questions": list(questions), "findings": list(findings), "events": list(events),
            "limits": {"enabled": False, "time_minutes": None, "cost": None}}
    for plan_id, stages in (plans or {}).items():
        full = {name: {"status": "pending"} for name in j2.STAGES}
        full.update({name: v if isinstance(v, dict) else {"status": v} for name, v in stages.items()})
        data["plans"].append({"id": plan_id, "spec": "g-spec.md", "plan": plan_id + ".md", "stages": full})
    return _j2_write(os.path.join(tmp, "g-chain.json"), json.dumps(data, indent=2))


def _j2_question(qid, plan, stage, status="open"):
    return {"id": qid, "plan": plan, "stage": stage, "skill": "t", "text": "which?", "options": ["a", "b"],
            "status": status, "answer": None if status == "open" else "a", "asked_at": "2026-10-02T10:00:00Z",
            "answered_at": None if status == "open" else "2026-10-02T10:05:00Z"}


def _j2_finding(fid, plan):
    return {"id": fid, "plan": plan, "skill": "t", "file": "a.py", "line": 3, "summary": "s.",
            "failure_scenario": "f.", "recorded_at": "2026-10-02T10:00:00Z", "backlog": None}


class JournalShowHelpersTest(unittest.TestCase):
    def test_plan_id_from_a_path_or_an_id(self):
        self.assertEqual(j2._journal_plan_id(os.path.join("docs", "x-impl.md")), "x-impl")
        self.assertEqual(j2._journal_plan_id("docs/x-impl.MD"), "x-impl")
        self.assertEqual(j2._journal_plan_id("x-impl"), "x-impl")

    def test_next_action_by_status_and_open_questions(self):
        self.assertEqual(j2._journal_next_action("stopped", ["Q1"]), "answer")
        self.assertEqual(j2._journal_next_action("stopped", []), "resume")
        self.assertEqual(j2._journal_next_action("failed", []), "retry")
        self.assertEqual(j2._journal_next_action("pending", []), "run")
        self.assertEqual(j2._journal_next_action("running", []), "run")
        self.assertEqual(j2._journal_next_action(None, []), "complete")


class JournalShowTest(unittest.TestCase):
    def test_next_action_follows_the_current_stage(self):
        done = {name: "done" for name in j2.STAGES}
        with tempfile.TemporaryDirectory() as tmp:
            path = _j2_journal(tmp, plans={
                "a-impl": {"writing": "done", "revision": "stopped"},
                "b-impl": {"writing": "done", "revision": "stopped"},
                "c-impl": {"writing": "failed"},
                "d-impl": dict(done, split="skipped"),
                "e-impl": {"writing": "running"},
                "f-impl": dict(done),
                "g-impl": {"writing": "done", "revision": "running"},
            }, questions=[_j2_question("Q1", "a-impl", "revision"), _j2_question("Q2", "b-impl", "revision", "answered"),
                          _j2_question("Q3", "f-impl", "audit"), _j2_question("Q4", "g-impl", "writing")])
            plans = {item["id"]: item for item in j2.journal_show(path)["plans"]}
        self.assertEqual({key: (p["current"], p["next_action"], p["owner"]) for key, p in plans.items()}, {
            "a-impl": ("revision", "answer", "plan-iterative-revision"),
            "b-impl": ("revision", "resume", "plan-iterative-revision"),
            "c-impl": ("writing", "retry", "plan-writing"),
            "d-impl": (None, "complete", None),
            "e-impl": ("writing", "run", "plan-writing"),
            "f-impl": (None, "answer", "plan-resolver"),  # an open question of a done stage still waits
            "g-impl": ("revision", "answer", "plan-writing"),  # the owner is the asking stage's skill
        })
        self.assertEqual(plans["a-impl"]["open_questions"], ["Q1"])
        self.assertEqual(plans["d-impl"]["stages"]["split"], "skipped")

    def test_progress_filter_and_counts(self):
        events = [_j2_event("a-impl", "execution", "unit-begin", unit="1", done=0, total=5),
                  _j2_event("a-impl", "execution", "unit-finish", unit="1", outcome="done", done=1, total=5),
                  _j2_event("b-impl", "writing", "stage-start", **{"from": "pending", "to": "running"})]
        with tempfile.TemporaryDirectory() as tmp:
            path = _j2_journal(tmp, plans={"a-impl": {}, "b-impl": {}}, events=events,
                               questions=[_j2_question("Q1", "a-impl", "execution"), _j2_question("Q2", "b-impl", "writing")],
                               findings=[_j2_finding("F1", "a-impl")])
            whole = j2.journal_show(path)
            only = j2.journal_show(path, os.path.join("docs", "a-impl.md"))
            by_id = j2.journal_show(path, "b-impl")
            with self.assertRaisesRegex(j2.InputError, "unknown-plan"):
                j2.journal_show(path, "zzz-impl")
        self.assertEqual((whole["goal"], whole["lang"], whole["findings"]), ("g", "en", 1))
        self.assertEqual([q["id"] for q in whole["open_questions"]], ["Q1", "Q2"])
        self.assertEqual(whole["limits"], {"enabled": False, "time_minutes": None, "cost": None})
        self.assertEqual([p["id"] for p in only["plans"]], ["a-impl"])
        self.assertEqual(only["plans"][0]["progress"], {"done": 1, "total": 5})
        self.assertEqual(only["open_questions"], [{"id": "Q1", "plan": "a-impl", "stage": "execution",
                                                   "text": "which?", "options": ["a", "b"]}])
        self.assertIsNone(by_id["plans"][0]["progress"])


class JournalShowCliTest(unittest.TestCase):
    def test_cli_show_and_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _j2_journal(tmp, plans={"a-impl": {"writing": "done"}})
            code, out = _j2_run("journal-show", path, "--plan", os.path.join(tmp, "a-impl.md"))
            self.assertEqual((code, out["ok"]), (0, True))
            self.assertEqual((out["plans"][0]["current"], out["plans"][0]["next_action"]), ("revision", "run"))
            self.assertEqual(_j2_run("journal-show", path, "--plan", "nope")[0], 2)
            self.assertEqual(_j2_run("journal-show", os.path.join(tmp, "missing-chain.json"))[0], 2)
            _j2_write(path, "{not json")
            code, out = _j2_run("journal-show", path)
            self.assertEqual(code, 2)
            self.assertIn("journal-corrupt", out["errors"][0])


class JournalValidateStructureTest(unittest.TestCase):
    def _errors(self, mutate):
        with tempfile.TemporaryDirectory() as tmp:
            path = _j2_journal(tmp, plans={"a-impl": {}},
                               questions=[_j2_question("Q1", "a-impl", "writing", "answered")],
                               findings=[_j2_finding("F1", "a-impl")], events=[_j2_event("a-impl", "", "finding")])
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            mutate(data)
            _j2_write(path, json.dumps(data))
            return j2.journal_validate(path)["errors"]

    def test_a_well_formed_journal_has_no_errors(self):
        self.assertEqual(self._errors(lambda data: None), [])

    def test_each_structure_rule(self):
        def stage(data, name, value):
            data["plans"][0]["stages"][name] = value
        cases = [
            (lambda d: d.pop("limits"), "'limits' must be dict"),
            (lambda d: d.update(goal=3), "'goal' must be str"),
            (lambda d: d["plans"].append(dict(d["plans"][0])), "duplicate plan id a-impl"),
            (lambda d: stage(d, "deploy", {"status": "done"}), "unknown stage 'deploy'"),
            (lambda d: stage(d, "split", {"status": "paused"}), "stage 'split' needs a status"),
            (lambda d: d["plans"][0]["stages"].pop("commit"), "stage 'commit' needs a status"),
            (lambda d: stage(d, "split", {"status": "done", "artifacts": ["roadmap=x"]}),
             "plans[0]: stage 'split' 'artifacts' must be an object"),
            (lambda d: stage(d, "split", {"status": "done", "input": 5}),
             "plans[0]: stage 'split' 'input' must be a string"),
            (lambda d: stage(d, "split", {"status": "done", "input_sha256": None}),
             "plans[0]: stage 'split' 'input_sha256' must be a string"),
            (lambda d: d["questions"][0].update(id="Q2"), "question ids must be Q1..Q1"),
            (lambda d: d["questions"][0].update(status="closed"), "Q1: status must be one of"),
            (lambda d: d["questions"][0].update(answer=None), "Q1: status answered needs an answer"),
            (lambda d: d["findings"].append({"id": "F1"}), "finding ids must be F1..F2"),
            (lambda d: d["events"][0].update(kind="note"), "events[0]: kind must be one of"),
            (lambda d: d["findings"][0].pop("summary"), "findings[0]: 'summary' must be a non-empty string"),
            (lambda d: d["events"][0].pop("data"), "events[0]: 'data' must be dict"),
        ]
        for mutate, expected in cases:
            with self.subTest(expected=expected):
                errors = self._errors(mutate)
                self.assertTrue(any(expected in error for error in errors), errors)


class JournalValidateTimeTest(JournalValidateStructureTest):
    def test_each_time_field(self):
        stages = lambda d: d["plans"][0]["stages"]  # noqa: E731
        cases = [
            (lambda d: d.update(created_at=""), "created_at: not a journal time"),
            (lambda d: d["events"][0].update(at=5), "events[0].at: not a journal time"),
            (lambda d: d["findings"][0].update(recorded_at="2026-10-02 10:00:00"), "findings[0].recorded_at: not a"),
            (lambda d: d["questions"][0].update(asked_at="2026-10-02T10:00:00"), "questions[0].asked_at: not a"),
            (lambda d: d["questions"][0].update(answered_at=""), "questions[0].answered_at: not a"),
            (lambda d: d["questions"][0].update(applied_at=None), "questions[0].applied_at: not a"),
            (lambda d: stages(d)["writing"].update(started_at="yesterday"), "stages.writing.started_at: not a"),
            (lambda d: stages(d)["audit"].update(finished_at=1.5), "plans[0].stages.audit.finished_at: not a"),
            (lambda d: d.update(runner={"sessions": [{"started_at": "x", "ended_at": 3}]}),
             "runner.sessions[0].started_at: not a"),
        ]
        for mutate, expected in cases:
            with self.subTest(expected=expected):
                errors = self._errors(mutate)
                self.assertTrue(any(expected in error for error in errors), errors)
        self.assertIn("runner.sessions[0].ended_at: not a journal time (YYYY-MM-DDTHH:MM:SSZ)",
                      self._errors(lambda d: d.update(runner={"sessions": [{"started_at": "x", "ended_at": 3}]})))

    def test_nulls_where_allowed_pass(self):
        def nulls(data):
            data["plans"][0]["stages"]["split"].update(started_at=None, finished_at=None)
            data["questions"][0].update(applied_at="2026-10-02T10:06:00Z")
        self.assertEqual(self._errors(nulls), [])

    def test_rebuild_keeps_a_journal_whose_only_fault_is_a_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _j2_journal(tmp, plans={"a-impl": {}}, events=[dict(_j2_event("a-impl", "", "finding"), at="now")])
            with open(path, encoding="utf-8") as fh:
                before = fh.read()
            self.assertEqual(j2._journal_rebuild(path), (False, None, []))
            with open(path, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), before)
            self.assertEqual(j2.journal_validate(path)["errors"],
                             ["events[0].at: not a journal time (YYYY-MM-DDTHH:MM:SSZ)"])


def _j2_move(plan, stage, before, after, kind=None):
    return _j2_event(plan, stage, kind or ("stage-start" if after == "running" else "stage-end"),
                     **{"from": before, "to": after})


class JournalValidateReplayTest(unittest.TestCase):
    def _errors(self, events, stages):
        with tempfile.TemporaryDirectory() as tmp:
            return j2.journal_validate(_j2_journal(tmp, plans={"a-impl": stages}, events=events))["errors"]

    def test_replayed_events_end_at_the_stored_statuses(self):
        events = [_j2_move("a-impl", "writing", "pending", "running"),
                  _j2_event("a-impl", "writing", "stage-update", **{"from": "running", "to": "running"}),
                  _j2_move("a-impl", "writing", "running", "done"),
                  _j2_move("a-impl", "revision", "pending", "running"),
                  _j2_move("a-impl", "revision", "running", "stopped"),
                  _j2_event("a-impl", "revision", "question", id="Q1"),
                  _j2_move("a-impl", "revision", "stopped", "running"),
                  _j2_move("a-impl", "revision", "running", "done"),
                  _j2_move("a-impl", "revision", "done", "running"),
                  _j2_move("a-impl", "split", "pending", "done", kind="reconcile"),
                  _j2_move("a-impl", "diffs", "pending", "running"),
                  _j2_move("a-impl", "diffs", "running", "done"),
                  _j2_event("a-impl", "diffs", "diffs-rebuilt", **{"from": "done", "to": "done"})]
        stages = {"writing": "done", "revision": "running", "split": "done", "diffs": "done"}
        self.assertEqual(self._errors(events, stages), [])

    def test_illegal_transition_broken_chain_and_stale_status(self):
        errors = self._errors([_j2_move("a-impl", "writing", "pending", "done"),
                               _j2_move("a-impl", "revision", "running", "done")],
                              {"writing": "done", "revision": "done", "split": "skipped"})
        self.assertEqual(errors, [
            "events[0] a-impl writing: illegal transition pending → done",
            "events[1] a-impl revision: from 'running' but the replayed status is 'pending'",
            "a-impl split: stored status 'skipped' but the events end at 'pending'",
        ])

    def test_replay_waits_for_a_clean_structure(self):
        errors = self._errors([_j2_move("a-impl", "writing", "pending", "done")], {"writing": "paused"})
        self.assertEqual(len(errors), 1)
        self.assertIn("stage 'writing' needs a status", errors[0])


class JournalValidateCliTest(unittest.TestCase):
    def test_a_journal_written_by_the_journal_commands_validates(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = _j2_write(os.path.join(tmp, "g-spec.md"), "> Tier: Quick\n\n# Goal\n\nx\n")
            plan = _j2_write(os.path.join(tmp, "g-impl.md"), "**Spec:** g-spec.md\n\n### Task 1: x\n")
            journal = os.path.join(tmp, "g-chain.json")
            j2.journal_create(journal, "g", "en", spec)
            j2.journal_event(journal, "plan-writing", plan, "writing", "running")
            j2.journal_event(journal, "plan-writing", plan, "writing", "done", input_path=spec,
                             artifacts=["plan=g-impl.md"])
            j2.journal_event(journal, "plan-iterative-revision", plan, "revision", "running")
            j2.journal_question(journal, "plan-iterative-revision", plan, "revision", "which?")
            j2.journal_question(journal, "plan-iterative-revision", plan, "revision", "and?", answer="a")
            code, out = _j2_run("journal-validate", journal)
            self.assertEqual((code, out), (0, {"ok": True, "errors": []}))
            self.assertEqual(j2.journal_show(journal)["plans"][0]["next_action"], "answer")

    def test_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _j2_journal(tmp, plans={"a-impl": {"writing": "done"}})
            code, out = _j2_run("journal-validate", path)
            self.assertEqual(code, 1)
            self.assertEqual(out["errors"], ["a-impl writing: stored status 'done' but the events end at 'pending'"])
            self.assertEqual(_j2_run("journal-validate", os.path.join(tmp, "missing-chain.json"))[0], 2)


class StageEvidenceTest(unittest.TestCase):
    def test_artifact_files_next_to_the_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = os.path.join(tmp, "g-chain.json")
            entry = {"id": "x-impl", "plan": "docs/x-impl.md", "stages": {}}
            evidence = lambda stage: j2._stage_evidence(journal, entry, stage, [])  # noqa: E731
            self.assertEqual([evidence(s) for s in ("writing", "revision", "split", "diffs", "audit")], [None] * 5)
            docs = os.path.join(tmp, "docs")
            for name in ("x-impl.md", "x-impl-completion.md", "x-impl-roadmap.md", "x-diffs.md",
                         "x-impl-report-1.md", "x-impl-report-2.md", "x-impl-review-1.md"):
                _j2_write(os.path.join(docs, name), "x\n")
            self.assertEqual(evidence("writing"), ({"plan": "docs/x-impl.md"}, "plan exists: docs/x-impl.md"))
            self.assertEqual(evidence("revision")[0], {"completion": "docs/x-impl-completion.md"})
            self.assertEqual(evidence("split")[0], {"roadmap": "docs/x-impl-roadmap.md"})
            self.assertEqual(evidence("diffs")[0], {"diffs": "docs/x-diffs.md"})
            self.assertEqual(evidence("audit")[0], {"report": "docs/x-impl-report-2.md", "status": "open"})
            _j2_write(os.path.join(docs, "x-impl-report-2-final.md"), "x\n")
            self.assertEqual(evidence("audit")[0], {"report": "docs/x-impl-report-2-final.md", "status": "final"})
            _j2_write(os.path.join(docs, "x-impl-report-10.md"), "x\n")
            self.assertEqual(evidence("audit")[0]["report"], "docs/x-impl-report-10.md")

    def test_plan_without_impl_suffix_uses_its_whole_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            _j2_write(os.path.join(tmp, "y-diffs.md"), "x\n")
            entry = {"id": "y", "plan": "y.md", "stages": {}}
            evidence = j2._stage_evidence(os.path.join(tmp, "g-chain.json"), entry, "diffs", [])
            self.assertEqual(evidence[0], {"diffs": "y-diffs.md"})


class JournalReconcileTest(unittest.TestCase):
    def test_artifacts_finish_pending_and_running_stages_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("a-impl.md", "a-impl-completion.md", "a-impl-roadmap.md", "a-impl-report-1-final.md",
                         "b-impl.md", "b-impl-completion.md", "b-impl-roadmap.md"):
                _j2_write(os.path.join(tmp, name), "x\n")
            path = _j2_journal(tmp, plans={
                "a-impl": {"writing": "running", "revision": "pending", "split": "skipped",
                           "execution": "running", "audit": "pending"},
                "b-impl": {"writing": "done", "revision": "stopped", "split": "failed"},
            }, events=[_j2_move("a-impl", "writing", "pending", "running"),
                       _j2_move("a-impl", "split", "pending", "skipped"),
                       _j2_move("a-impl", "execution", "pending", "running"),
                       _j2_move("b-impl", "writing", "pending", "done", kind="reconcile"),
                       _j2_move("b-impl", "revision", "pending", "stopped", kind="reconcile"),
                       _j2_move("b-impl", "split", "pending", "failed", kind="reconcile")])
            result = j2.journal_reconcile(path)
            stored = {p["id"]: p["stages"] for p in j2.journal_load(path)["plans"]}
            self.assertEqual(j2.journal_validate(path), {"ok": True, "errors": []})
        self.assertEqual([(c["plan"], c["stage"], c["from"], c["to"]) for c in result["changes"]], [
            ("a-impl", "revision", "pending", "done"),
            ("a-impl", "audit", "pending", "done"),
        ])
        self.assertEqual(result["running"], [{"plan": "a-impl", "stage": "writing"},  # an existing plan may be unfinished
                                             {"plan": "a-impl", "stage": "execution"}])
        self.assertEqual((result["ok"], result["questions"]), (True, []))
        self.assertEqual(stored["a-impl"]["audit"]["artifacts"], {"report": "a-impl-report-1-final.md", "status": "final"})
        self.assertEqual(stored["a-impl"]["split"]["status"], "skipped")
        self.assertEqual({k: v["status"] for k, v in stored["b-impl"].items() if k in ("revision", "split")},
                         {"revision": "stopped", "split": "failed"})

    def test_running_stage_needs_evidence_newer_than_its_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = _j2_write(os.path.join(tmp, "a-impl-report-1.md"), "x\n")
            os.utime(report, (946684800, 946684800))  # 2000-01-01: a report of an earlier pass
            path = _j2_journal(tmp, plans={"a-impl": {
                "writing": "done", "audit": {"status": "running", "started_at": "2001-01-01T00:00:00Z"}}},
                events=[_j2_move("a-impl", "writing", "pending", "done", kind="reconcile"),
                        _j2_move("a-impl", "audit", "pending", "running")])
            old = j2.journal_reconcile(path)
            _j2_write(report, "x\n")  # written by this pass
            fresh = j2.journal_reconcile(path)
            audit = j2.journal_load(path)["plans"][0]["stages"]["audit"]
        self.assertEqual((old["changes"], old["running"]), ([], [{"plan": "a-impl", "stage": "audit"}]))
        self.assertEqual([(c["stage"], c["from"], c["to"]) for c in fresh["changes"]], [("audit", "running", "done")])
        self.assertEqual((audit["status"], audit["artifacts"]["status"]), ("done", "open"))


def _j2_git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd,
                          capture_output=True, text=True, check=True).stdout.strip()


class ReconcileLedgerAndCommitTest(unittest.TestCase):
    def _ledger(self, tmp, statuses):
        units = [{"id": str(n), "status": status, "attempts": attempts}
                 for n, (status, attempts) in enumerate(statuses, start=1)]
        _j2_write(os.path.join(tmp, "exec", "state.json"), json.dumps({"units": units}))

    def test_execution_follows_the_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            entry = {"id": "a-impl", "plan": "a-impl.md",
                     "stages": {"execution": {"status": "running", "artifacts": {"exec_dir": "exec"}}}}
            journal, warnings = os.path.join(tmp, "g-chain.json"), []
            self.assertIsNone(j2._stage_evidence(journal, entry, "execution", warnings))
            self._ledger(tmp, [("done", 1), ("failed", 3), ("failed", 1)])
            self.assertIsNone(j2._stage_evidence(journal, entry, "execution", warnings))
            self.assertEqual(warnings, ["a-impl execution: units without retries left: 2"])
            self._ledger(tmp, [("done", 1), ("done", 2)])
            self.assertEqual(j2._stage_evidence(journal, entry, "execution", []), ({}, "ledger: 2 of 2 units done"))

    def test_commit_needs_every_sha_in_the_plan_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            _j2_git(tmp, "init", "-q")
            _j2_write(os.path.join(tmp, "a.txt"), "a\n")
            _j2_git(tmp, "add", "a.txt")
            _j2_git(tmp, "commit", "-q", "-m", "a")
            sha = _j2_git(tmp, "rev-parse", "HEAD")
            journal = os.path.join(tmp, "g-chain.json")

            def evidence(*shas):
                commits = [{"sha": value, "subject": "s", "files": []} for value in shas]
                entry = {"id": "a-impl", "plan": "a-impl.md",
                         "stages": {"commit": {"status": "running", "artifacts": {"commits": commits}}}}
                return j2._stage_evidence(journal, entry, "commit", [])

            self.assertEqual(evidence(sha), ({}, "commits found in git: 1"))
            self.assertIsNone(evidence())
            self.assertIsNone(evidence(sha, "0" * 40))
            self.assertIsNone(evidence("--all"))


class ReconcileDriftTest(unittest.TestCase):
    def test_changed_input_of_a_done_stage_becomes_one_question_per_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = _j2_write(os.path.join(tmp, "g-spec.md"), "spec v1\n")
            plan = _j2_write(os.path.join(tmp, "a-impl.md"), "plan v1\n")
            roadmap = _j2_write(os.path.join(tmp, "a-impl-roadmap.md"), "roadmap v1\n")
            done = lambda path: {"status": "done", "input_sha256": j2._sha256(path)}  # noqa: E731
            path = _j2_journal(tmp, plans={"a-impl": {
                "writing": done(spec), "revision": done(plan), "split": done(plan), "execution": done(roadmap),
            }}, events=[_j2_move("a-impl", stage, "pending", "done", kind="reconcile")
                        for stage in ("writing", "revision", "split", "execution")])
            self.assertEqual(j2.journal_reconcile(path)["questions"], [])
            _j2_write(plan, "plan v2\n")
            short = j2._sha256(plan)[:12]
            first = j2.journal_reconcile(path)
            second = j2.journal_reconcile(path)
            for qid in first["questions"]:  # "keep it as is": answered and applied, the stage is not re-run
                j2.journal_answer(path, qid, answer="keep")
                j2.journal_answer(path, qid, applied=True)
            third = j2.journal_reconcile(path)
            _j2_write(plan, "plan v3\n")
            fourth = j2.journal_reconcile(path)
            data = j2.journal_load(path)
            self.assertEqual(j2.journal_validate(path), {"ok": True, "errors": []})
        self.assertEqual((first["questions"], second["questions"], third["questions"], fourth["questions"]),
                         (["Q1", "Q2"], [], [], ["Q3", "Q4"]))
        self.assertEqual([(q["stage"], q["text"], q["status"]) for q in data["questions"][:2]], [
            ("revision", f"drift: revision input changed: a-impl.md (sha256 {short})", "applied"),
            ("split", f"drift: split input changed: a-impl.md (sha256 {short})", "applied"),
        ])
        self.assertEqual({s: v["status"] for s, v in data["plans"][0]["stages"].items() if v["status"] == "done"},
                         {"writing": "done", "revision": "done", "split": "done", "execution": "done"})


class ReconcileRebuildTest(unittest.TestCase):
    def test_corrupt_journal_is_kept_aside_and_rebuilt_from_the_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            _j2_write(os.path.join(tmp, "g-1-spec.md"), "> Backlog: g\n\n# Goal\n\nОдин.\n")
            _j2_write(os.path.join(tmp, "g-2-spec.md"), "> Backlog: g\n\n# Goal\n\nДва.\n")
            _j2_write(os.path.join(tmp, "other-spec.md"), "# Goal\n\nx\n")
            _j2_write(os.path.join(tmp, "g-1-impl.md"), "**Spec:** g-1-spec.md\n\n### Task 1: x\n")
            _j2_write(os.path.join(tmp, "g-1-impl-completion.md"), "x\n")
            _j2_write(os.path.join(tmp, "other-impl.md"), "**Spec:** other-spec.md\n\n### Task 1: x\n")
            exported = json.dumps([{"file": "a.py", "line": 3, "summary": "Первая.", "failure_scenario": "Сбой 1."},
                                   {"file": "b.py", "line": None, "summary": "Вторая.", "failure_scenario": "Сбой 2."}],
                                  ensure_ascii=False, indent=2) + "\n"
            followups = _j2_write(os.path.join(tmp, "g-followups.json"), exported)  # the last export
            path = _j2_write(os.path.join(tmp, "g-chain.json"), "{broken")
            with self.assertRaisesRegex(j2.InputError, "journal-corrupt"):
                j2.journal_reconcile(path)
            result = j2.journal_reconcile(path, rebuild=True)
            data = j2.journal_load(path)
            with open(result["backup"], encoding="utf-8") as fh:
                kept = fh.read()
            again = j2.journal_reconcile(path, rebuild=True)
            self.assertEqual(j2.journal_validate(path), {"ok": True, "errors": []})
            j2.journal_export_findings(path)
            with open(followups, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), exported)  # the export after a rebuild loses no finding
        self.assertEqual((result["rebuilt"], kept), (True, "{broken"))
        self.assertRegex(os.path.basename(result["backup"]), r"^g-chain\.json\.corrupt-\d{14}$")
        self.assertEqual((data["goal"], data["lang"]), ("g", "ru"))
        self.assertEqual([s["path"] for s in data["specs"]], ["g-1-spec.md", "g-2-spec.md"])
        self.assertEqual([(p["id"], p["spec"]) for p in data["plans"]], [("g-1-impl", "g-1-spec.md")])
        self.assertEqual([(f["id"], f["plan"], f["skill"], f["line"]) for f in data["findings"]],
                         [("F1", "g-1-impl", "journal-rebuild", 3), ("F2", "g-1-impl", "journal-rebuild", None)])
        self.assertEqual(result["warnings"], ["rebuilt journal: questions, events, commits, exec_dir and input_sha256 "
                                              "cannot be restored from the files"])
        self.assertEqual([(c["stage"], c["to"]) for c in result["changes"]], [("writing", "done"), ("revision", "done")])
        self.assertEqual((again["rebuilt"], again["backup"], again["changes"], again["warnings"]), (False, None, [], []))


class ReconcileCliTest(unittest.TestCase):
    def test_cli_reconcile(self):
        with tempfile.TemporaryDirectory() as tmp:
            _j2_write(os.path.join(tmp, "a-impl.md"), "x\n")
            path = _j2_journal(tmp, plans={"a-impl": {}})
            code, out = _j2_run("journal-reconcile", path)
            self.assertEqual((code, [c["stage"] for c in out["changes"]]), (0, ["writing"]))
            _j2_write(path, "[]")
            self.assertEqual(_j2_run("journal-reconcile", path)[0], 2)
            code, out = _j2_run("journal-reconcile", path, "--rebuild")
            self.assertEqual((code, out["rebuilt"]), (0, True))


class JournalGateFixesTest(unittest.TestCase):
    def test_load_retries_a_journal_busy_for_a_moment(self):  # b1: Windows, a reader meets os.replace
        with tempfile.TemporaryDirectory() as tmp:
            path = _j2_journal(tmp)
            real_open, failures = open, [PermissionError(13, "in use")]

            def busy_then_free(file, *args, **kwargs):
                if file == path and failures:
                    raise failures.pop()
                return real_open(file, *args, **kwargs)

            with mock.patch.object(j2, "open", busy_then_free, create=True):
                data = j2.journal_load(path)
        self.assertEqual((failures, data["goal"]), ([], "g"))

    def test_valid_json_with_a_broken_structure_is_journal_corrupt(self):  # b2
        with tempfile.TemporaryDirectory() as tmp:
            path = _j2_write(os.path.join(tmp, "g-chain.json"), '{"version": 1, "plans": [{"id": "a"}]}')
            for args in (["journal-show", path], ["journal-reconcile", path]):
                code, out = _j2_run(*args)
                self.assertEqual(code, 2, (args, out))
                self.assertTrue(out["errors"][0].startswith("journal-corrupt: "), out)

    def test_rebuild_into_a_missing_folder_is_an_input_error(self):  # c1
        with tempfile.TemporaryDirectory() as tmp:
            code, out = _j2_run("journal-reconcile", os.path.join(tmp, "none", "g-chain.json"), "--rebuild")
        self.assertEqual(code, 2, out)
        self.assertTrue(out["errors"][0].startswith("cannot list "), out)

    def test_failed_rebuild_keeps_the_corrupt_journal_in_place(self):  # c2
        with tempfile.TemporaryDirectory() as tmp:
            path = _j2_write(os.path.join(tmp, "g-chain.json"), "{broken")
            with mock.patch.object(j2, "_rebuild_sources", side_effect=j2.InputError("cannot read x")):
                with self.assertRaisesRegex(j2.InputError, "cannot read x"):
                    j2.journal_reconcile(path, rebuild=True)
            with open(path, encoding="utf-8") as fh:
                kept = fh.read()
            names = sorted(os.listdir(tmp))
        self.assertEqual((kept, names), ("{broken", ["g-chain.json"]))

    def test_rebuild_replaces_a_structurally_broken_journal(self):  # b2 follow-up
        with tempfile.TemporaryDirectory() as tmp:
            _j2_write(os.path.join(tmp, "g-impl.md"), "### Task 1: x\n")
            path = _j2_write(os.path.join(tmp, "g-chain.json"), '{"version":1,"plans":[{"id":"a"}]}')
            code, out = _j2_run("journal-reconcile", path, "--rebuild")
            with open(out.get("backup") or path, encoding="utf-8") as fh:
                kept = fh.read()
            valid = j2.journal_validate(path)
        self.assertEqual((code, out.get("rebuilt"), kept), (0, True, '{"version":1,"plans":[{"id":"a"}]}'), out)
        self.assertRegex(os.path.basename(out["backup"]), r"^g-chain\.json\.corrupt-\d{14}$")
        self.assertEqual(valid, {"ok": True, "errors": []})

    def test_two_rebuilds_in_one_second_keep_both_backups(self):  # c3
        with tempfile.TemporaryDirectory() as tmp:
            _j2_write(os.path.join(tmp, "g-impl.md"), "### Task 1: x\n")
            path = _j2_write(os.path.join(tmp, "g-chain.json"), "{first")
            with mock.patch.object(j2, "_now", return_value=time.time()):
                one = j2.journal_reconcile(path, rebuild=True)["backup"]
                _j2_write(path, "{second")
                two = j2.journal_reconcile(path, rebuild=True)["backup"]
            kept = []
            for backup in (one, two):
                with open(backup, encoding="utf-8") as fh:
                    kept.append(fh.read())
        self.assertNotEqual(one, two)
        self.assertEqual(kept, ["{first", "{second"])

    def test_a_concurrent_reconcile_asks_each_drift_question_once(self):  # c4
        with tempfile.TemporaryDirectory() as tmp:
            plan = _j2_write(os.path.join(tmp, "a-impl.md"), "plan v1\n")
            path = _j2_journal(tmp, plans={"a-impl": {
                "writing": "done", "revision": {"status": "done", "input_sha256": j2._sha256(plan)}}},
                events=[_j2_move("a-impl", stage, "pending", "done", kind="reconcile")
                        for stage in ("writing", "revision")])
            _j2_write(plan, "plan v2\n")
            real_update, raced = j2.journal_update, []

            def update_then_race(journal, mutate, create=None):
                result = real_update(journal, mutate, create)
                if not raced:  # another session reconciles right after this update
                    raced.append(True)
                    j2.journal_reconcile(journal)
                return result

            with mock.patch.object(j2, "journal_update", update_then_race):
                j2.journal_reconcile(path)
            texts = [q["text"] for q in j2.journal_load(path)["questions"]]
            self.assertEqual(j2.journal_validate(path), {"ok": True, "errors": []})
        self.assertEqual(len(texts), 1, texts)


class RunnerConstantsTest(unittest.TestCase):
    def test_runner_constants(self):
        self.assertEqual(j2.RUNNER_VERSION, 1)
        self.assertEqual(j2.RUNNER_PROFILES, ("claude-code", "github-copilot", "fallback"))
        self.assertEqual(j2.ROLES, ("writing", "revision", "split", "execution", "audit", "commit"))
        self.assertTrue(set(j2.ROLES) <= set(j2.STAGES))
        self.assertEqual(j2.RUNNER_SESSION_ENDS, ("stopped", "complete", "interrupted"))

    def test_start_commit_forms(self):
        for value in ("a1b2c3d", "0" * 40, "declined", "none"):
            self.assertTrue(j2.RUNNER_START_COMMIT_RE.match(value), value)
        for value in ("", "a1b2c3", "A1B2C3D", "HEAD", "declined ", "g1b2c3d"):
            self.assertIsNone(j2.RUNNER_START_COMMIT_RE.match(value), value)


class RunnerCycleTest(unittest.TestCase):
    def test_acyclic_graphs(self):
        self.assertIsNone(j2._runner_cycle({}))
        self.assertIsNone(j2._runner_cycle({"b": ["a"], "c": ["b", "a"]}))
        self.assertIsNone(j2._runner_cycle({"d": ["b", "c"], "b": ["a"], "c": ["a"], "a": []}))

    def test_the_first_cycle_in_stored_order(self):
        self.assertEqual(j2._runner_cycle({"a": ["b"], "b": ["a"]}), ["a", "b", "a"])
        self.assertEqual(j2._runner_cycle({"a": ["a"]}), ["a", "a"])
        self.assertEqual(j2._runner_cycle({"x": ["a"], "a": ["b"], "b": ["c"], "c": ["a"]}),
                         ["a", "b", "c", "a"])
        self.assertEqual(j2._runner_cycle({"b": ["a"], "a": ["b"]}), ["b", "a", "b"])


class RunnerGraphErrorsTest(unittest.TestCase):
    SPECS = ["g-1-spec.md", "g-2-spec.md", "g-3-spec.md"]

    def test_a_graph_over_the_specs_has_no_errors(self):
        self.assertEqual(j2._runner_graph_errors({}, self.SPECS), [])
        self.assertEqual(j2._runner_graph_errors(
            {"g-2-spec.md": ["g-1-spec.md"], "g-3-spec.md": ["g-1-spec.md", "g-2-spec.md"]}, self.SPECS), [])

    def test_types(self):
        expected = ["runner: 'graph' must be an object of string lists"]
        for graph in (None, [], {"g-2-spec.md": "g-1-spec.md"}, {"g-2-spec.md": [1]}):
            with self.subTest(graph=graph):
                self.assertEqual(j2._runner_graph_errors(graph, self.SPECS), expected)

    def test_unknown_specs(self):
        self.assertEqual(j2._runner_graph_errors({"x-spec.md": ["g-1-spec.md", "y-spec.md"]}, self.SPECS), [
            "runner: graph key 'x-spec.md' is not in specs",
            "runner: graph dependency 'y-spec.md' of 'x-spec.md' is not in specs",
        ])

    def test_membership_is_skipped_without_valid_specs(self):
        self.assertEqual(j2._runner_graph_errors({"x-spec.md": ["y-spec.md"]}, None), [])

    def test_cycle(self):
        graph = {"g-1-spec.md": ["g-2-spec.md"], "g-2-spec.md": ["g-1-spec.md"]}
        self.assertEqual(j2._runner_graph_errors(graph, self.SPECS),
                         ["runner-graph-cycle: g-1-spec.md -> g-2-spec.md -> g-1-spec.md"])


class RunnerModelsErrorsTest(unittest.TestCase):
    def test_roles_with_models_and_efforts(self):
        models = {"writing": {"model": "fable", "effort": "high"}, "commit": {"model": "gpt-5-mini", "effort": None},
                  "execution": {"model": None, "effort": None},  # profile fallback: the skill runs in the session
                  "audit": {"model": "claude-opus-5.5", "effort": None, "fallback": "gpt-5-mini"}}
        self.assertEqual(j2._runner_models_errors({}), [])
        self.assertEqual(j2._runner_models_errors(models), [])

    def test_each_models_rule(self):
        cases = [
            ([], ["runner: 'models' must be an object"]),
            ({"deploy": {"model": "x", "effort": None}},
             ["runner: unknown role 'deploy' in models (roles: writing, revision, split, execution, audit, commit)"]),
            ({"split": "opus"}, ["runner: models.split needs 'model' and 'effort', each a non-empty string or null"]),
            ({"split": {"model": "opus"}}, ["runner: models.split needs 'model' and 'effort', each a non-empty string or null"]),
            ({"split": {"model": "", "effort": None}},
             ["runner: models.split needs 'model' and 'effort', each a non-empty string or null"]),
            ({"split": {"model": "opus", "effort": 3}},
             ["runner: models.split needs 'model' and 'effort', each a non-empty string or null"]),
        ]
        for models, expected in cases:
            with self.subTest(models=models):
                self.assertEqual(j2._runner_models_errors(models), expected)


class RunnerSessionsErrorsTest(unittest.TestCase):
    def test_finished_and_open_sessions(self):
        sessions = [{"id": "s1", "started_at": "2026-10-02T10:00:00Z", "ended_at": "2026-10-02T11:00:00Z",
                     "end": "stopped"},
                    {"id": "s2", "started_at": "2026-10-02T12:00:00Z", "ended_at": None, "end": None}]
        self.assertEqual(j2._runner_sessions_errors([]), [])
        self.assertEqual(j2._runner_sessions_errors(sessions), [])

    def test_each_sessions_rule(self):
        good = {"id": "s1", "started_at": "2026-10-02T10:00:00Z", "ended_at": None, "end": None}
        cases = [
            ({}, ["runner: 'sessions' must be a list"]),
            ([["s1"]], ["runner: sessions[0]: must be an object"]),
            ([dict(good, id="")], ["runner: sessions[0]: 'id' must be a non-empty string"]),
            ([{k: v for k, v in good.items() if k != "started_at"}],
             ["runner: sessions[0]: 'started_at' must be a non-empty string"]),
            ([{k: v for k, v in good.items() if k != "ended_at"}],
             ["runner: sessions[0]: 'ended_at' must be a string or null"]),
            ([good, dict(good, end="crashed")],
             ["runner: sessions[1]: 'end' must be one of stopped, complete, interrupted or null"]),
            ([{k: v for k, v in good.items() if k != "end"}],
             ["runner: sessions[0]: 'end' must be one of stopped, complete, interrupted or null"]),
        ]
        for sessions, expected in cases:
            with self.subTest(expected=expected[0]):
                self.assertEqual(j2._runner_sessions_errors(sessions), expected)


def _jr_runner(**changes):
    """A valid runner section of goal 'g' with two specs; `changes` replace or (value None) drop keys."""
    runner = {"version": 1, "profile": "claude-code", "specs": ["g-1-spec.md", "g-2-spec.md"],
              "graph": {"g-2-spec.md": ["g-1-spec.md"]},
              "models": {"writing": {"model": "fable", "effort": "high"}, "commit": {"model": "sonnet", "effort": "low"}},
              "start_commit": "a1b2c3d",
              "sessions": [{"id": "s1", "started_at": "2026-10-02T10:00:00Z", "ended_at": None, "end": None}]}
    runner.update(changes)
    return {key: value for key, value in runner.items() if value is not None}


class RunnerErrorsTest(unittest.TestCase):
    def test_a_valid_runner_has_no_errors(self):
        self.assertEqual(j2._runner_errors(_jr_runner()), [])
        self.assertEqual(j2._runner_errors(_jr_runner(start_commit=None)), [])  # the key is optional
        self.assertEqual(j2._runner_errors(_jr_runner(parallel=2)), [])  # optional, written by run-init --parallel
        for value in ("declined", "none", "0" * 40):
            self.assertEqual(j2._runner_errors(_jr_runner(start_commit=value)), [])
        fallback = {role: {"model": None, "effort": None} for role in j2.ROLES}
        self.assertEqual(j2._runner_errors(_jr_runner(profile="fallback", models=fallback, sessions=[])), [])

    def test_each_runner_rule(self):
        cases = [
            ([], ["runner: must be an object"]),
            (_jr_runner(version=2), ["runner: 'version' must be 1"]),
            (_jr_runner(version=True), ["runner: 'version' must be 1"]),
            (_jr_runner(profile="codex"), ["runner: 'profile' must be one of claude-code, github-copilot, fallback"]),
            (_jr_runner(specs="g-1-spec.md"), ["runner: 'specs' must be a list of non-empty strings"]),
            (_jr_runner(specs=["g-1-spec.md", ""], graph={}), ["runner: 'specs' must be a list of non-empty strings"]),
            (_jr_runner(specs=["g-1-spec.md"]), ["runner: graph key 'g-2-spec.md' is not in specs"]),
            (_jr_runner(graph=None), ["runner: 'graph' must be an object of string lists"]),
            (_jr_runner(graph={"g-1-spec.md": ["g-2-spec.md"], "g-2-spec.md": ["g-1-spec.md"]}),
             ["runner-graph-cycle: g-1-spec.md -> g-2-spec.md -> g-1-spec.md"]),
            (_jr_runner(models={"review": {"model": "x", "effort": None}}),
             ["runner: unknown role 'review' in models (roles: writing, revision, split, execution, audit, commit)"]),
            (_jr_runner(start_commit="HEAD"), ["runner: 'start_commit' must be a commit sha, 'declined' or 'none'"]),
            (_jr_runner(parallel=0), ["runner: 'parallel' must be an integer >= 1"]),
            (_jr_runner(sessions=None), ["runner: 'sessions' must be a list"]),
        ]
        for runner, expected in cases:
            with self.subTest(expected=expected[0]):
                self.assertEqual(j2._runner_errors(runner), expected)


class RunnerValidateTest(unittest.TestCase):
    def _journal(self, tmp, runner):
        path = _j2_journal(tmp, plans={"a-impl": {}})
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        data["runner"] = runner
        return _j2_write(path, json.dumps(data, indent=2))

    def test_a_valid_runner_validates_and_survives_journal_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._journal(tmp, _jr_runner())
            self.assertEqual(j2.journal_validate(path), {"ok": True, "errors": []})
            j2.journal_question(path, "plan-chain-runner", os.path.join(tmp, "a-impl.md"), "writing",
                                "stage-failed: writing", options=["retry", "stop"])
            self.assertEqual(j2.journal_load(path)["runner"], _jr_runner())
            self.assertEqual(_j2_run("journal-validate", path), (0, {"ok": True, "errors": []}))

    def test_unknown_spec_and_cycle_fail_journal_validate(self):
        cases = [
            (_jr_runner(graph={"g-3-spec.md": ["g-1-spec.md"]}), ["runner: graph key 'g-3-spec.md' is not in specs"]),
            (_jr_runner(graph={"g-1-spec.md": ["g-2-spec.md"], "g-2-spec.md": ["g-1-spec.md"]}),
             ["runner-graph-cycle: g-1-spec.md -> g-2-spec.md -> g-1-spec.md"]),
            (None, ["runner: must be an object"]),
        ]
        for runner, expected in cases:
            with self.subTest(expected=expected[0]), tempfile.TemporaryDirectory() as tmp:
                path = self._journal(tmp, runner)
                self.assertEqual(j2.journal_validate(path), {"ok": False, "errors": expected})
                self.assertEqual(_j2_run("journal-validate", path), (1, {"ok": False, "errors": expected}))

    def test_runner_errors_come_after_the_other_structure_errors_and_stop_the_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._journal(tmp, _jr_runner(version=2))
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            data["plans"][0]["stages"]["writing"]["status"] = "done"  # a replay error, hidden by structure errors
            data["events"].append({"kind": "note"})
            _j2_write(path, json.dumps(data))
            errors = j2.journal_validate(path)["errors"]
        self.assertEqual(errors[-1], "runner: 'version' must be 1")
        self.assertFalse(any("stored status" in error for error in errors), errors)


class RunnerSchemaTest(unittest.TestCase):
    def test_runner_schema_names_match_the_code(self):
        path = os.path.join(os.path.dirname(_J2_TOOL), "..", "assets", "chain-journal.schema.json")
        with open(path, encoding="utf-8") as fh:
            schema = json.load(fh)
        self.assertEqual(schema["properties"]["runner"], {"$ref": "#/definitions/runner"})
        self.assertNotIn("runner", schema["required"])  # optional section
        runner = schema["definitions"]["runner"]
        props = runner["properties"]
        self.assertEqual(runner["required"], ["version", "profile", "specs", "graph", "models", "sessions"])
        self.assertEqual(props["version"], {"const": j2.RUNNER_VERSION})
        self.assertEqual(tuple(props["profile"]["enum"]), j2.RUNNER_PROFILES)
        self.assertEqual(tuple(props["models"]["propertyNames"]["enum"]), j2.ROLES)
        self.assertEqual(props["start_commit"]["pattern"], j2.RUNNER_START_COMMIT_RE.pattern)
        self.assertEqual(tuple(props["sessions"]["items"]["properties"]["end"]["enum"]), j2.RUNNER_SESSION_ENDS + (None,))


class RunnerLightTest(unittest.TestCase):
    """Spec 8 of plan-refactoring-01: runner.models.execution.light is optional and validates."""

    def test_execution_light_validates(self):
        models = {"execution": {"model": "opus", "effort": "medium", "light": "haiku"}}
        with tempfile.TemporaryDirectory() as tmp:
            path = RunnerValidateTest._journal(self, tmp, _jr_runner(models=models))  # its helper uses no state
            self.assertEqual(j2.journal_validate(path), {"ok": True, "errors": []})

    def test_schema_documents_light(self):
        path = os.path.join(os.path.dirname(_J2_TOOL), "..", "assets", "chain-journal.schema.json")
        with open(path, encoding="utf-8") as fh:
            entry = json.load(fh)["definitions"]["runner"]["properties"]["models"]["additionalProperties"]
        self.assertEqual(entry["properties"]["light"]["type"], ["string", "null"])
        self.assertEqual(entry["required"], ["model", "effort"])


if __name__ == "__main__":
    unittest.main()
