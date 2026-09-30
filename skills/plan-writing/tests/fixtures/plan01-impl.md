# Verbose Flag Implementation Plan

> **For agentic workers:** Execute this plan with the `plan-executor` skill (one unit at a time, ledger-backed, gated). If the plan has not been audited yet, run `plan-iterative-revision` on it first. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** plan01-spec.md

**Tier:** Standard

**Goal:** `cli.py --verbose` prints the input path before the line count.

**Architecture:** One new argparse flag in the existing `main()`; output order is path, then count.

**Tech Stack:** Python 3.8 stdlib, unittest.

---

### Task 1: Parse the verbose flag

**Files:**
- Modify: `cli.py:4-6`
- Test: `tests/test_cli.py`

**Preconditions:**
- `cli.py` prints the line count for one positional `path`.

**Postconditions:**
- `python cli.py f --verbose` prints `f` on the first line and the count on the second.
- Output without `--verbose` is unchanged.

- [ ] **Step 1: Write the failing test**

```python
def test_verbose_prints_path(tmp_path):
    target = tmp_path / "f.txt"
    target.write_text("a\nb\n")
    out = run_cli(str(target), "--verbose")
    assert out.splitlines() == [str(target), "2"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_cli.py::test_verbose_prints_path -q`
Expected: FAIL with "unrecognized arguments: --verbose"

- [ ] **Step 3: Implement**

```python
p.add_argument("--verbose", action="store_true")
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_cli.py -q`
Expected: PASS

### Task 1.1: Document the flag

**Files:**
- Modify: `README.md`

**Preconditions:**
- Task 1 is done.

**Postconditions:**
- README shows one `--verbose` example.

- [ ] **Step 1: Add the example**

```markdown
## Task 9: this heading is file content, not a task
Run `python cli.py notes.txt --verbose`.
```

### Task 2: Checkpoint — flag works end to end

- [ ] **Step 1: Run the smoke check**

Run: `python cli.py README.md --verbose`
Expected: first line `README.md`, second line a number

**Done when:** both lines appear as expected.
