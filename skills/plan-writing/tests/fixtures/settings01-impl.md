# Verbose Flag Smoke Plan

> **For agentic workers:** Execute this plan with the `plan-executor` skill (one unit at a time, ledger-backed, gated). Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** settings01-spec.md

**Tier:** Standard

**Goal:** `cli.py --verbose` is smoke-tested on the test database and compared with production counts.

**Architecture:** Two test modules, one per environment.

**Tech Stack:** Python 3.8 stdlib, pytest.

---

### Task 1: Smoke test on the test database

**Files:**
- Test: `tests/test_smoke.py`

**External:** `dev_db` (write) — load two rows and run the smoke test

**Preconditions:**
- `cli.py` supports `--verbose`.

**Postconditions:**
- The smoke test passes.

- [ ] **Step 1: Run the smoke test**

Run: `DB=dev_db python -m pytest tests/test_smoke.py -q`
Expected: PASS

### Task 2: Compare counts with production

**Files:**
- Test: `tests/test_counts.py`

**External:** `prod_db` (read) — one SELECT COUNT(*)

**Preconditions:**
- Task 1 is done.

**Postconditions:**
- The production count equals the count printed by `cli.py`.

- [ ] **Step 1: Run the count check**

Run: `DB=prod_db python -m pytest tests/test_counts.py -q`
Expected: PASS
