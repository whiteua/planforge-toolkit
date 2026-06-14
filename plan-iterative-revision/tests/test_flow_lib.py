from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "scripts" / "next_review_index.py"

spec = importlib.util.spec_from_file_location("nri", TOOL)
nri = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nri)


REVIEW_TXT = """# Ревизия 1: demo

**Iteration**: 1

## Issues

### [1.1] blocker · logic · sample
- **Required fix (contract)**:
  Add rollback transaction in Section 3.2
- **Fingerprint**: aaaa1111

### [1.2] minor · tests · deferred sample
- **Required fix (contract)**:
  Cover edge case in Section 4
- **Fingerprint**: bbbb2222
  deferred-conflict
"""


class ParseLib(unittest.TestCase):
    def test_parse_issues_fields(self):
        issues = nri.parse_review_issues(REVIEW_TXT)
        self.assertEqual(len(issues), 2)
        first = issues[0]
        self.assertEqual(first["fingerprint"], "aaaa1111")
        self.assertEqual(first["severity"], "blocker")
        self.assertEqual(first["category"], "logic")
        self.assertEqual(first["fix"], "Add rollback transaction in Section 3.2")
        self.assertEqual(first["status"], "Open")

    def test_parse_detects_deferred(self):
        issues = nri.parse_review_issues(REVIEW_TXT)
        self.assertEqual(issues[1]["status"], "Deferred")

    def test_ordered_sets_sorted_by_n(self, ):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            base = "demo"
            (Path(d) / f"{base}-review-2.md").write_text(REVIEW_TXT, encoding="utf-8")
            one = REVIEW_TXT.replace("aaaa1111", "cccc3333").replace("bbbb2222", "dddd4444")
            (Path(d) / f"{base}-review-1.md").write_text(one, encoding="utf-8")
            sets = nri.ordered_fingerprint_sets(d, base)
        self.assertEqual(sets, [{"cccc3333", "dddd4444"}, {"aaaa1111", "bbbb2222"}])


class Flows(unittest.TestCase):
    def test_i1_all_new(self):
        f = nri.compute_flows([], {"a", "b"})
        self.assertEqual(f, {"new": 2, "resolved": 0, "persisted": 0, "reintroduced": 0})

    def test_resolved_persisted_new(self):
        # S1={a,b}, S2(current)={b,c}: b persisted, a resolved, c new
        f = nri.compute_flows([{"a", "b"}], {"b", "c"})
        self.assertEqual(f, {"new": 1, "resolved": 1, "persisted": 1, "reintroduced": 0})

    def test_reintroduced(self):
        # S1={a}, S2={}, S3(current)={a}: a was in cumulative, left, returned
        f = nri.compute_flows([{"a"}, set()], {"a"})
        self.assertEqual(f, {"new": 0, "resolved": 0, "persisted": 0, "reintroduced": 1})

    def test_partition_identity(self):
        f = nri.compute_flows([{"a", "b"}, {"b"}], {"b", "c", "d"})
        self.assertEqual(f["new"] + f["persisted"] + f["reintroduced"], 3)

    def test_persisted_counts(self):
        c = nri.persisted_counts([{"a"}, {"a"}], {"a", "x"})
        self.assertEqual(c, {"a": 2})


class Classify(unittest.TestCase):
    def test_clean_on_empty_current(self):
        self.assertEqual(nri.classify_flow([{"a"}], set()), ("clean", None))

    def test_regression_hard_stop(self):
        # i=3, a reintroduced
        self.assertEqual(nri.classify_flow([{"a"}, set()], {"a"}), ("escalated", "regression"))

    def test_churn_when_nothing_resolved_two_windows(self):
        # i=3: S1={a}, S2={a,b}, S3(current)={a,b,c}; resolved empty in last two transitions, new>0
        self.assertEqual(nri.classify_flow([{"a"}, {"a", "b"}], {"a", "b", "c"}), ("stagnation", "churn"))

    def test_continue_default(self):
        # i=2: progress, no churn arming
        self.assertEqual(nri.classify_flow([{"a", "b"}], {"b", "c"}), ("continue", None))

    def test_no_false_churn_before_i3(self):
        # i=2 even with new and no resolved must not churn
        self.assertEqual(nri.classify_flow([{"a"}], {"a", "b"}), ("continue", None))