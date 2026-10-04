from __future__ import annotations

import contextlib
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

spec = importlib.util.spec_from_file_location("nri", TOOL)
nri = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nri)


def issue(fix: str, severity: str = "major", category: str = "logic", **extra) -> dict:
    data = {
        "severity": severity,
        "category": category,
        "title": f"Title for {fix}",
        "location_in_plan": "## Section 1",
        "code_cross_check": "verified - checked",
        "problem": f"Problem for {fix}",
        "required_fix": fix,
        "acceptance": f"Plan contains {fix}",
    }
    data.update(extra)
    return data


class RecordBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.plan = self.dir / "demo.md"
        self.plan.write_text("# Demo plan\n\nSome English plan text.\n", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def record(self, issues, *flags, run_start: int = 1, max_iter: int = 5, payload_extra=None):
        payload = {"summary": "Summary.", "issues": issues}
        payload.update(payload_extra or {})
        args = [
            sys.executable, str(TOOL), "record", str(self.plan),
            "--run-start", str(run_start), "--max", str(max_iter), "--issues", "-", *flags,
        ]
        proc = subprocess.run(args, text=True, capture_output=True, input=json.dumps(payload), encoding="utf-8")
        return proc

    def ok(self, *args, **kwargs) -> dict:
        proc = self.record(*args, **kwargs)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return json.loads(proc.stdout)

    def reviews(self):
        return sorted(p.name for p in self.dir.glob("demo-review-*.md"))


class RecordGates(RecordBase):
    def test_clean_first_iteration_writes_nothing(self):
        out = self.ok([])
        self.assertEqual((out["action"], out["result"]), ("stop", "clean"))
        self.assertEqual(out["final"]["iterations"], 0)
        self.assertEqual(out["final"]["remaining_issues"], 0)
        self.assertEqual(self.reviews(), [])
        self.assertFalse((self.dir / "demo-completion.md").exists())

    def test_implement_writes_strictly_valid_review(self):
        out = self.ok([issue("Fix A", "minor"), issue("Fix B", "blocker")])
        self.assertEqual(out["action"], "implement")
        self.assertEqual([i["id"] for i in out["issues"]], ["1.1", "1.2"])
        self.assertEqual([i["severity"] for i in out["issues"]], ["blocker", "minor"])
        self.assertEqual(self.reviews(), ["demo-review-1.md"])
        valid, report = nri.validate_review(out["review_path"], strict_fingerprint=True)
        self.assertTrue(valid, report)
        text = Path(out["review_path"]).read_text(encoding="utf-8")
        self.assertIn("# Revision 1: demo", text)
        self.assertIn("**Previous review**: none", text)
        self.assertNotIn("**Status**", text)

    def test_converged_writes_completion(self):
        self.ok([issue("Fix A")])
        out = self.ok([])
        self.assertEqual(out["result"], "converged")
        self.assertEqual(out["final"]["iterations"], 1)
        self.assertEqual(out["final"]["remaining_issues"], 0)
        completion = Path(out["completion_path"]).read_text(encoding="utf-8")
        self.assertIn("- demo-review-1.md", completion)
        self.assertIn("**Audits**: 2", completion)
        self.assertIn("**Reviews written**: 1", completion)
        self.assertNotIn("{{", completion)

    def test_unescaped_newline_in_code_quote_warns(self):
        good = self.ok([issue('Add `process.exit(0)` after console.log("\\nDone\\n");')])
        self.assertEqual(good["warnings"], [])
        bad = self.ok([issue('Add exit after console.log("\nDone\n"); in the test')], run_start=2)
        self.assertTrue(any("unbalanced quote" in w for w in bad["warnings"]), bad["warnings"])

    def test_run_start_ignores_previous_runs(self):
        self.ok([issue("Fix A")])
        self.ok([issue("Fix B")])
        # New run starts at 3: the old history must not trigger regression / unchanged.
        out = self.ok([issue("Fix A")], run_start=3)
        self.assertEqual(out["action"], "implement")
        self.assertEqual(out["iteration"], 1)
        self.assertEqual(out["flows"]["reintroduced"], 0)

    def test_carry_keeps_category_and_fingerprint(self):
        first = self.ok([issue("Fix A", category="db")])
        fp = first["issues"][0]["fingerprint"]
        out = self.ok([{"carry": fp, "severity": "blocker", "code_cross_check": "not applicable",
                        "problem": "Contract not applied"}])
        self.assertEqual(out["issues"][0]["fingerprint"], fp)
        # Same set twice in a row → unchanged stagnation, still recorded as a final review.
        self.assertEqual((out["result"], out["stop_reason"]), ("stagnation", "unchanged"))
        text = Path(out["review_path"]).read_text(encoding="utf-8")
        self.assertIn("· db ·", text)
        self.assertIn("- **Carried from**: demo-review-1.md#1.1", text)

    def test_unknown_carry_is_error(self):
        proc = self.record([{"carry": "deadbeef", "severity": "major"}])
        self.assertEqual(proc.returncode, 2)
        self.assertIn("carry", json.loads(proc.stdout)["error"])
        self.assertEqual(self.reviews(), [])

    def test_stuck_after_three_consecutive_audits(self):
        self.ok([issue("Fix A"), issue("Fix B")])
        self.ok([issue("Fix A"), issue("Fix C")])
        out = self.ok([issue("Fix A"), issue("Fix D")])
        fp_a = nri.make_fingerprint("logic", "Fix A")
        self.assertEqual((out["result"], out["stop_reason"]), ("escalated", "stuck"))
        self.assertEqual(out["escalated"], [fp_a])
        self.assertIn("**Status**: ESCALATED", Path(out["review_path"]).read_text(encoding="utf-8"))

    def test_regression_hard_stop(self):
        self.ok([issue("Fix A")])
        self.ok([issue("Fix B")])
        out = self.ok([issue("Fix A"), issue("Fix C")])
        self.assertEqual((out["result"], out["stop_reason"]), ("escalated", "regression"))

    def test_pragmatic_drain_on_nits(self):
        out = self.ok([issue("Fix A", "nit")])
        self.assertEqual((out["result"], out["stop_reason"]), ("converged", "drain"))
        self.assertEqual(out["final"]["remaining_issues"], 1)
        self.assertIn("**Status**: FINAL", Path(out["review_path"]).read_text(encoding="utf-8"))

    def test_strict_policy_implements_nits(self):
        out = self.ok([issue("Fix A", "nit")], "--stop-policy", "strict")
        self.assertEqual(out["action"], "implement")

    def test_limit_autonomous_and_interactive(self):
        self.ok([issue("Fix A")], max_iter=1)
        asked = self.ok([issue("Fix B")], "--interaction", "interactive", max_iter=1)
        self.assertEqual(asked["action"], "ask_limit")
        self.assertEqual(self.reviews(), ["demo-review-1.md"])
        out = self.ok([issue("Fix B")], max_iter=1)
        self.assertEqual(out["result"], "limit")
        self.assertEqual(self.reviews(), ["demo-review-1.md", "demo-review-2.md"])

    def test_user_stop_and_audit_only(self):
        out = self.ok([issue("Fix A")], "--user-stop")
        self.assertEqual(out["result"], "limit")
        self.assertIn("skipped by user", Path(out["review_path"]).read_text(encoding="utf-8"))
        out = self.ok([issue("Fix B")], "--mode", "audit-only", run_start=2)
        self.assertEqual(out["result"], "converged")
        self.assertIn("audit-only", Path(out["review_path"]).read_text(encoding="utf-8"))

    def test_duplicates_merge_to_highest_severity(self):
        out = self.ok([issue("Fix A", "minor", location_in_plan="## One"),
                       issue("Fix A", "blocker", location_in_plan="## Two")])
        self.assertEqual(len(out["issues"]), 1)
        self.assertEqual(out["issues"][0]["severity"], "blocker")
        text = Path(out["review_path"]).read_text(encoding="utf-8")
        self.assertIn("## Two; ## One", text)

    def test_invalid_input_writes_nothing(self):
        bad = issue("Fix A")
        del bad["acceptance"]
        bad["code_cross_check"] = "maybe"
        proc = self.record([bad])
        self.assertEqual(proc.returncode, 2)
        error = json.loads(proc.stdout)["error"]
        self.assertIn("missing acceptance", error)
        self.assertIn("code_cross_check", error)
        self.assertEqual(self.reviews(), [])

    def test_multiline_fields_round_trip(self):
        fix = "Add step:\n- **bold** item\n### not a heading\n```sql\nSELECT 1;\n```"
        out = self.ok([issue(fix, evidence="> quote\n\n```py\nx = 1\n```")])
        valid, report = nri.validate_review(out["review_path"], strict_fingerprint=True)
        self.assertTrue(valid, report)
        self.assertEqual(out["issues"][0]["fingerprint"], nri.make_fingerprint("logic", fix))

    def test_russian_plan_gets_russian_title(self):
        self.plan.write_text("# План\n\nТекст плана на русском языке.\n", encoding="utf-8")
        out = self.ok([issue("Fix A")])
        self.assertIn("# Ревизия 1: demo", Path(out["review_path"]).read_text(encoding="utf-8"))

    def test_lenses_used_reported(self):
        out = self.ok([], payload_extra={"audit_state": {"lenses_used": 4}})
        self.assertEqual(out["final"]["lenses_used"], 4)

    def test_unknown_lang_rejected(self):
        proc = self.record([], "--lang", "de")
        self.assertEqual(proc.returncode, 64)
        self.assertIn("--lang", json.loads(proc.stdout)["error"])

    def test_usage_errors(self):
        proc = subprocess.run([sys.executable, str(TOOL), "record", str(self.plan)], text=True, capture_output=True)
        self.assertEqual(proc.returncode, 64)
        self.assertIn("error", json.loads(proc.stdout))


class DecideUnit(unittest.TestCase):
    def issues(self, *fps, severity="major"):
        return [{"fingerprint": fp, "severity": severity} for fp in fps]

    def test_churn_when_nothing_resolved(self):
        d = nri.decide([{"a"}, {"a", "b"}], self.issues("a", "b", "c"), 9, "pragmatic", "full-cycle", "autonomous", False)
        self.assertEqual((d["result"], d["stop_reason"]), ("stagnation", "churn"))

    def test_stuck_when_others_resolve(self):
        d = nri.decide([{"a", "b"}, {"a", "c"}], self.issues("a", "d"), 9, "pragmatic", "full-cycle", "autonomous", False)
        self.assertEqual((d["stop_reason"], d["escalated"]), ("stuck", ["a"]))

    def test_limit_after_max(self):
        d = nri.decide([{"a"}], self.issues("b"), 1, "pragmatic", "full-cycle", "autonomous", False)
        self.assertEqual(d["result"], "limit")

    def test_drain_never_hides_major(self):
        d = nri.decide([], self.issues("a", severity="major"), 5, "pragmatic", "full-cycle", "autonomous", False)
        self.assertEqual(d["action"], "implement")


class RevisionJournalEventUnit(unittest.TestCase):
    """Every way decide() ends a run maps to one journal status; the loop states map to None."""

    def issues(self, *fps, severity="major"):
        return [{"fingerprint": fp, "severity": severity} for fp in fps]

    def decide(self, history, issues, max_iter=9, policy="pragmatic", mode="full-cycle",
               interaction="autonomous", user_stop=False):
        return nri.decide(history, issues, max_iter, policy, mode, interaction, user_stop)

    def test_every_gate_is_mapped(self):
        cases = {
            "clean": (self.decide([], []), "done"),
            "converged": (self.decide([{"a"}], []), "done"),
            "drain": (self.decide([], self.issues("a", severity="nit")), "done"),
            "audit-only": (self.decide([], self.issues("a"), mode="audit-only"), "done"),
            "user-stop": (self.decide([], self.issues("a"), user_stop=True), "stopped"),
            "regression": (self.decide([{"a"}, {"b"}], self.issues("a", "c")), "stopped"),
            "unchanged": (self.decide([{"a"}], self.issues("a")), "stopped"),
            "churn": (self.decide([{"a"}, {"a", "b"}], self.issues("a", "b", "c")), "stopped"),
            "stuck": (self.decide([{"a", "b"}, {"a", "c"}], self.issues("a", "d")), "stopped"),
            "limit": (self.decide([{"a"}], self.issues("b"), max_iter=1), "stopped"),
        }
        self.assertEqual(set(cases), set(nri.REVISION_JOURNAL_STATUS))
        for verdict, (decision, status) in cases.items():
            event = nri.revision_journal_event(decision, "p.md", None, None, None)
            self.assertEqual(event["stage"], "revision", verdict)
            self.assertEqual(event["status"], status, verdict)
            self.assertEqual(event["artifacts"], [f"verdict={verdict}"], verdict)
            self.assertEqual("input" in event, status == "done", verdict)

    def test_loop_states_give_none(self):
        implement = self.decide([], self.issues("a"))
        ask = self.decide([{"a"}], self.issues("b"), max_iter=1, interaction="interactive")
        self.assertEqual((implement["action"], ask["action"]), ("implement", "ask_limit"))
        for decision in (implement, ask):
            self.assertIsNone(nri.revision_journal_event(decision, "p.md", "r.md", None, None))

    def test_paths_relative_to_the_journal(self):
        with tempfile.TemporaryDirectory() as d:
            journal = Path(d) / "docs" / "goal-chain.json"
            review = Path(d) / "docs" / "plans" / "p-review-2.md"
            completion = Path(d) / "docs" / "plans" / "p-completion.md"
            event = nri.revision_journal_event(self.decide([{"a"}], []), str(Path(d) / "p.md"),
                                               str(review), str(completion), str(journal))
            self.assertEqual(event["artifacts"], ["review=plans/p-review-2.md",
                                                  "completion=plans/p-completion.md", "verdict=converged"])
            self.assertEqual(event["input"], str(Path(d) / "p.md"))
            self.assertEqual(nri.journal_ref(str(review), None), str(review))


class RecordJournalEvent(RecordBase):
    """record returns journal_event: done on clean/converged, stopped on gates, None in the loop."""

    def with_journal(self):
        # demo.md has no **Spec:** line: its journal lies next to it as demo-chain.json.
        (self.dir / "demo-chain.json").write_text("{}\n", encoding="utf-8")

    def test_loop_has_no_event(self):
        out = self.ok([issue("Fix A")])
        self.assertEqual(out["action"], "implement")
        self.assertIsNone(out["journal_event"])
        asked = self.ok([issue("Fix B")], "--interaction", "interactive", max_iter=1)
        self.assertEqual(asked["action"], "ask_limit")
        self.assertIsNone(asked["journal_event"])

    def test_clean_is_done_without_review(self):
        out = self.ok([])
        self.assertEqual(out["journal_event"], {
            "stage": "revision", "status": "done", "artifacts": ["verdict=clean"], "input": str(self.plan),
        })

    def test_converged_names_review_and_completion_relative_to_journal(self):
        self.with_journal()
        self.ok([issue("Fix A")])
        out = self.ok([])
        self.assertEqual(out["journal_event"]["status"], "done")
        self.assertEqual(out["journal_event"]["artifacts"],
                         ["review=demo-review-1.md", "completion=demo-completion.md", "verdict=converged"])

    def test_without_journal_paths_are_absolute(self):
        self.ok([issue("Fix A")])
        out = self.ok([])
        self.assertEqual(out["journal_event"]["artifacts"][:2], [
            "review=" + str(self.dir / "demo-review-1.md"), "completion=" + str(self.dir / "demo-completion.md"),
        ])

    def test_drain_is_done_with_the_final_review(self):
        self.with_journal()
        out = self.ok([issue("Fix A", "nit")])
        self.assertEqual((out["journal_event"]["status"], out["journal_event"]["artifacts"]),
                         ("done", ["review=demo-review-1.md", "verdict=drain"]))

    def test_stuck_and_limit_are_stopped(self):
        self.with_journal()
        self.ok([issue("Fix A"), issue("Fix B")])
        self.ok([issue("Fix A"), issue("Fix C")])
        out = self.ok([issue("Fix A"), issue("Fix D")])
        self.assertEqual(out["journal_event"], {
            "stage": "revision", "status": "stopped", "artifacts": ["review=demo-review-3.md", "verdict=stuck"],
        })
        out = self.ok([issue("Fix E")], run_start=4, max_iter=0)
        self.assertEqual(out["result"], "limit")
        self.assertEqual(out["journal_event"]["artifacts"], ["review=demo-review-4.md", "verdict=limit"])
        self.assertEqual(out["journal_event"]["status"], "stopped")


def task_plan(n: int = 4, edits: dict = None) -> str:
    """A plan of N tasks; EDITS: {task: other step text}."""
    blocks = ["# Demo plan\n\nSome English plan text.\n"]
    for number in range(1, n + 1):
        step = (edits or {}).get(number, f"do {number}")
        blocks.append(f"### Task {number}: Title {number}\n\n- [ ] **Step 1: {step}**\n")
    return "\n".join(blocks)


class IncrementalBase(RecordBase):
    """A plan with four tasks; helpers for --scope incremental."""

    def setUp(self):
        super().setUp()
        self.plan.write_text(task_plan(), encoding="utf-8")

    def text(self, out) -> str:
        return Path(out["review_path"]).read_text(encoding="utf-8")

    def incremental(self, issues, tasks: str, **kwargs):
        return self.ok(issues, "--scope", "incremental", "--tasks", tasks, **kwargs)


class RecordScopeArgs(IncrementalBase):
    def test_scope_arguments_are_checked(self):
        cases = [
            (("--scope", "partial"), "--scope"),
            (("--scope", "incremental"), "--tasks"),
            (("--scope", "incremental", "--tasks", "1", "--mode", "audit-only"), "audit-only"),
        ]
        for flags, message in cases:
            proc = self.record([issue("Fix A")], *flags)
            self.assertEqual(proc.returncode, 64, flags)
            self.assertIn(message, json.loads(proc.stdout)["error"], flags)
        self.assertEqual(self.reviews(), [])
        out = self.ok([issue("Fix A")], "--scope", "full", "--tasks", "ignored")
        self.assertEqual(out["action"], "implement")


class RecordTaskDigest(IncrementalBase):
    def test_full_by_default_with_task_digest(self):
        text = self.text(self.ok([issue("Fix A")]))
        self.assertIn("**Previous review**: none\n**Audit scope**: full\n**Audit tasks**: all\n", text)
        parsed = nri._load_brainstorm_tool().parse_plan_tasks(self.plan.read_text(encoding="utf-8"))
        expected = {task["id"]: task["sha1"] for task in parsed["tasks"]}
        self.assertEqual(nri.parse_task_digest(text), {"tasks": expected, "malformed": []})

    def test_incremental_with_issues_writes_incremental_review(self):
        self.ok([issue("Fix A")])
        out = self.incremental([issue("Fix B", location_in_plan="Task 2")], "2, 3")
        self.assertEqual(out["action"], "implement")
        text = self.text(out)
        self.assertIn("**Audit scope**: incremental\n**Audit tasks**: 2, 3\n", text)
        self.assertEqual(len(nri.parse_task_digest(text)["tasks"]), 4)

    def test_plan_without_tasks_gets_no_table(self):
        self.plan.write_text("# Demo plan\n\nSome English plan text.\n", encoding="utf-8")
        text = self.text(self.ok([issue("Fix A")]))
        self.assertIn("**Audit scope**: full\n", text)
        self.assertIsNone(nri.parse_task_digest(text))


class RecordFullAuditRequired(IncrementalBase):
    def test_clean_incremental_requires_full_audit(self):
        self.ok([issue("Fix A", location_in_plan="Task 2")])
        self.plan.write_text(task_plan(edits={2: "fixed"}), encoding="utf-8")
        out = self.incremental([], "2")
        self.assertEqual((out["action"], out["result"], out["review_path"]), ("full-audit-required", None, None))
        self.assertIsNone(out["journal_event"])
        self.assertNotIn("final", out)
        self.assertEqual(self.reviews(), ["demo-review-1.md"])
        self.assertEqual(nri.next_review_number(str(self.dir), "demo")[0], 2)
        out = self.ok([], "--scope", "full")
        self.assertEqual(out["result"], "converged")
        self.assertTrue((self.dir / "demo-completion.md").exists())

    def test_first_audit_and_unknown_tasks_exit_64(self):
        proc = self.record([issue("Fix A")], "--scope", "incremental", "--tasks", "1")
        self.assertEqual(proc.returncode, 64)
        self.assertIn("first audit", json.loads(proc.stdout)["error"])
        self.ok([issue("Fix A")])
        proc = self.record([issue("Fix B")], "--scope", "incremental", "--tasks", "2,99")
        self.assertEqual(proc.returncode, 64)
        self.assertIn("99", json.loads(proc.stdout)["error"])
        self.assertEqual(self.reviews(), ["demo-review-1.md"])

    def test_without_plan_brainstorming(self):
        issues_file = self.dir / "issues.json"
        issues_file.write_text(json.dumps({"summary": "S.", "issues": [issue("Fix A", location_in_plan="Task 2")]}),
                               encoding="utf-8")
        args = ["nri", "record", str(self.plan), "--run-start", "1", "--max", "5", "--issues", str(issues_file)]
        out = io.StringIO()
        with mock.patch.object(nri, "_load_brainstorm_tool", return_value=None), contextlib.redirect_stdout(out):
            self.assertEqual(nri.main(args), 0)
            first = json.loads(out.getvalue())
            out.seek(0)
            out.truncate()
            issues_file.write_text(json.dumps({"summary": "S.", "issues": []}), encoding="utf-8")
            self.assertEqual(nri.main(args + ["--scope", "incremental", "--tasks", "2"]), 0)
        text = self.text(first)
        self.assertIn("**Audit scope**: full\n**Audit tasks**: all\n", text)
        self.assertNotIn("## Task digest", text)
        self.assertEqual(json.loads(out.getvalue())["action"], "full-audit-required")


class DecideFullAuditRequired(unittest.TestCase):
    def test_only_an_empty_incremental_audit(self):
        decide = lambda history, scope: nri.decide(history, [], 9, "pragmatic", "full-cycle", "autonomous", False, scope)
        d = decide([{"a"}], "incremental")
        self.assertEqual((d["action"], d["result"], d["write_review"]), ("full-audit-required", None, False))
        self.assertEqual(decide([{"a"}], "full")["result"], "converged")


class RecordDroppedContracts(IncrementalBase):
    def test_dropped_contract_of_unchanged_task_is_carried(self):
        self.ok([issue("Fix A", "minor", location_in_plan="Task 2, Step 1"), issue("Fix B", location_in_plan="Task 3")])
        fp_a = nri.make_fingerprint("logic", "Fix A")
        self.plan.write_text(task_plan(edits={3: "fixed"}), encoding="utf-8")
        out = self.incremental([issue("Fix C", location_in_plan="Task 3")], "3")
        self.assertEqual({it["fingerprint"] for it in out["issues"]}, {fp_a, nri.make_fingerprint("logic", "Fix C")})
        self.assertIn(f"contracts-dropped: [{fp_a}]", out["warnings"])
        self.assertEqual(out["flows"]["resolved"], 1)  # Fix B: its task changed, so the skipped contract is closed
        carried = next(it for it in out["issues"] if it["fingerprint"] == fp_a)
        self.assertEqual(carried["severity"], "minor")
        text = self.text(out)
        self.assertIn("- **Carried from**: demo-review-1.md#", text)
        self.assertIn("Problem for Fix A", text)

    def test_carry_of_an_old_review_contract(self):
        item = nri.carry_of({"fingerprint": "aaaa1111", "severity": "minor", "required_fix": "Fix X",
                             "problem": "", "code_cross_check": "", "location_in_code": ""})
        self.assertEqual((item["carry"], item["severity"]), ("aaaa1111", "minor"))
        self.assertEqual((item["problem"], item["code_cross_check"]), ("Fix X", nri.CARRIED_BY_RECORD))

    def test_closed_contracts_without_new_issues_need_a_full_audit(self):
        self.ok([issue("Fix A", location_in_plan="Task 2"), issue("Fix B")])  # Fix B: "## Section 1", no task
        self.plan.write_text(task_plan(edits={2: "fixed"}), encoding="utf-8")
        out = self.incremental([], "2")
        self.assertEqual((out["action"], out["warnings"]), ("full-audit-required", []))


class RecordGatesIncremental(IncrementalBase):
    def test_unchanged_and_drain_under_incremental(self):
        self.ok([issue("Fix A", location_in_plan="Task 2")])
        fp = nri.make_fingerprint("logic", "Fix A")
        out = self.incremental([{"carry": fp, "severity": "major", "code_cross_check": "not applicable",
                                 "problem": "Still missing"}], "2")
        self.assertEqual((out["result"], out["stop_reason"]), ("stagnation", "unchanged"))
        self.ok([issue("Fix A", location_in_plan="Task 2")], run_start=3)  # a new run: its first audit is full
        self.plan.write_text(task_plan(edits={2: "fixed"}), encoding="utf-8")
        out = self.incremental([issue("Fix N", "nit", location_in_plan="Task 1")], "1,2", run_start=3)
        self.assertEqual((out["result"], out["stop_reason"]), ("converged", "drain"))


class DecideGatesIncremental(unittest.TestCase):
    """Every gate but the new first rule fires under --scope incremental as under full."""

    def test_other_gates_do_not_depend_on_scope(self):
        issues = lambda *fps, severity="major": [{"fingerprint": fp, "severity": severity} for fp in fps]
        cases = [
            ([{"a"}], issues("b", severity="nit"), ("converged", "drain")),
            ([{"a"}], issues("a"), ("stagnation", "unchanged")),
            ([{"a"}, {"a", "b"}], issues("a", "b", "c"), ("stagnation", "churn")),
            ([{"a", "b"}, {"a", "c"}], issues("a", "d"), ("escalated", "stuck")),
            ([{"a"}, {"b"}], issues("a", "c"), ("escalated", "regression")),
        ]
        for history, found, expected in cases:
            for scope in ("full", "incremental"):
                d = nri.decide(history, found, 9, "pragmatic", "full-cycle", "autonomous", False, scope)
                self.assertEqual((d["result"], d["stop_reason"]), expected, (scope, expected))


if __name__ == "__main__":
    unittest.main()
