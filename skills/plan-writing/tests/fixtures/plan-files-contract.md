# Дефекты прогона plan-refactoring-02 и правила раннера: план реализации

> **For agentic workers:** Execute this plan with the `plan-executor` skill (one unit at a time, ledger-backed, gated). If the plan has not been audited yet, run `plan-iterative-revision` on it first. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** plan-refactoring-03-spec.md

**Tier:** Standard

**Goal:** Временная ошибка хоста повторяет стадию по нарастающей паузе без вопроса, писатель продолжается по маркеру после `failed` и `stopped` и останавливается вопросом при застое, исполнение не стартует рядом с чужой ревизией (`reading-busy`), splitter в тихом прогоне решает borderline числами (`silent_verdict`) и не спрашивает, отчёт о диффе получает одно каноническое имя из `run-diff`, а инструкции executor, брифа light и `writing-skills` получают правило про heredoc и исправленную строку кодов выхода.

**Architecture:** Всё, что считает и решает, живёт в скриптах. `chain_tool.py` получает две команды (`host-wait`, `writing-resume`), пишущие только в свой раздел журнала `runner` (`runner.host_errors`, `runner.writing_resumes`); переходы стадии при исчерпании пауз идут через `brainstorm_tool.journal_event` со `--skill plan-chain-runner`, так что общие `events`, `EVENT_KINDS`, `STAGE_TRANSITIONS`, `STAGE_OWNERS` и схема артефактов не меняются. `run-next` ничего не пишет: метки снимаются вычислением по порядку событий журнала (`at_event` = `len(events)` в момент записи), единственное сравнение с часами — `wait_until` против `_now()`. Форму новых полей проверяет `brainstorm_tool._runner_errors`, а `chain-journal.schema.json` их описывает. splitter отдаёт `silent_verdict` из `gate_verdict`, раннер пропускает split без агента и на borderline-keep. В executor одна функция `diffs_path` строит путь отчёта от `plan_path` леджера; `run-diff --markdown` без пути пишет туда и возвращает путь полем `markdown`, чужой путь — exit 2 `diffs-path-mismatch`. Остальное — правки references, SKILL.md, USAGE.md и docs.

**Tech Stack:** Python 3.8+ stdlib, unittest под pytest, Markdown-инструкции скиллов.

**Baseline:** `python -m pytest skills -q` → 1295 passed, 5 skipped, 184 subtests passed (2026-10-06, коммит 415e7c1).

Решения в рамках спеки (не отклонения; проверить на ревизии):

- Запись `runner.host_errors` несёт поля спеки `{plan, stage, at, error, attempt, wait_seconds, wait_until}` и два служебных: `at_event` (`len(events)` при записи: серия сбрасывается по порядку событий, не по часам, как требует Architecture спеки; у `writing_resumes` оно есть в самой спеке) и `waited_total` (сумма пауз серии для ответа команды и вопроса `stage-failed:`). `exhausted_for {plan, stage, attempt, event}` пишется в последнюю запись исчерпанной серии.
- Паузы 60, 120, 300, 600, 600… с; последняя урезается так, чтобы сумма серии стала ровно 3600 (девятая пауза — 120 с), следующий вызов — исчерпание. Повторный вызов в уже исчерпанной серии (до движения стадии или ответа `retry` на `stage-failed:`) ничего не пишет и отвечает `exhausted: true`; `retry` начинает серию с нуля и без `stage-start` (`_host_series_start`).
- `run-next` с парой в `host-wait:` отдаёт `blocked: false`: ожидание хоста — не остановка прогона.
- `run-init` сохраняет `runner.host_errors` и `runner.writing_resumes`, как уже сохраняет `sessions`: иначе повторный `run-init` (ответ `model: retry <model>`) снял бы метку исчерпания.
- Тесты `_runner_errors` — в `test_brainstorm_tool.py`, как называет спека (прежние тесты раздела `runner` — в `test_journal.py`).
- Хост без ожидания (ни фонового `sleep`, ни `sleep` в оболочке): сразу вопрос `stage-failed: <stage>` с `retry`/`stop` (PROFILES.md, Host errors).

---

## Журнал: метки раннера

### Task 1: Проверка формы runner.host_errors и runner.writing_resumes

**Files:**
- Modify: `skills/plan-brainstorming/scripts/brainstorm_tool.py:1461-1462` (сейчас: `RUNNER_ROADMAP_SHA_RE` — последняя константа раздела runner / после неё — три кортежа ключей новых записей / сохранить прежние константы)
- Modify: `skills/plan-brainstorming/scripts/brainstorm_tool.py:2254-2306` (сейчас: `_runner_sessions_errors` и `_runner_errors`, незнакомые ключи раздела не проверяются / новые `_runner_mark_ok`, `_runner_marks_errors` и их вызов из `_runner_errors` / сохранить порядок прежних ошибок и сообщения)
- Test: `skills/plan-brainstorming/tests/test_brainstorm_tool.py`

**Preconditions:**
- `_runner_errors` (`brainstorm_tool.py:2274`) вызывается из `_journal_structure_errors` (`:2388`) и `chain_tool.run_init`; `JOURNAL_TIME_RE` определён в `brainstorm_tool.py:2309`, `STAGES` — в `:1444`.

**Postconditions:**
- `_runner_errors` возвращает ошибки формы `runner.host_errors` и `runner.writing_resumes`; раздел без этих ключей проверяется как раньше.
- Общие `events`, `EVENT_KINDS`, `STAGE_TRANSITIONS` не меняются.

- [ ] **Step 1: Write the failing test**

Перед строками `if __name__ == "__main__":` в конце `test_brainstorm_tool.py`:

```python
def _marks_runner(**changes):
    """A valid runner section with one host-error record and one writing-resume record; `changes` replace keys."""
    host = {"plan": "a-impl", "stage": "writing", "at": "2026-10-05T10:00:00Z", "error": "API Error: 529 overloaded",
            "attempt": 1, "wait_seconds": 60, "wait_until": "2026-10-05T10:01:00Z", "waited_total": 60, "at_event": 3}
    resume = {"plan": "a-impl", "tasks": 4, "bytes": 900, "sha256": "a" * 64, "at_event": 5}
    runner = {"version": 1, "profile": "claude-code", "specs": [], "graph": {}, "models": {}, "sessions": [],
              "host_errors": [host], "writing_resumes": [resume]}
    runner.update(changes)
    return runner, host, resume


class RunnerMarksTest(unittest.TestCase):
    """Spec plan-refactoring-03: runner.host_errors and runner.writing_resumes are optional and checked."""

    def test_valid_marks_and_absent_lists(self):
        runner, host, _ = _marks_runner()
        self.assertEqual(ft._runner_errors(runner), [])
        exhausted = dict(host, wait_seconds=0,
                         exhausted_for={"plan": "a-impl", "stage": "writing", "attempt": 1, "event": 2})
        self.assertEqual(ft._runner_errors(_marks_runner(host_errors=[exhausted])[0]), [])
        bare = {key: value for key, value in runner.items() if key not in ("host_errors", "writing_resumes")}
        self.assertEqual(ft._runner_errors(bare), [])

    def test_each_rule(self):
        _, host, resume = _marks_runner()
        cases = [
            ({"host_errors": {}}, "runner: 'host_errors' must be a list"),
            ({"writing_resumes": ["x"]}, "runner: writing_resumes[0]: must be an object"),
            ({"host_errors": [dict(host, at="2026-10-05 10:00")]}, "runner: host_errors[0]: 'at' missing or invalid"),
            ({"host_errors": [dict(host, stage="build")]}, "runner: host_errors[0]: 'stage' missing or invalid"),
            ({"host_errors": [dict(host, attempt=0)]}, "runner: host_errors[0]: 'attempt' missing or invalid"),
            ({"host_errors": [{k: v for k, v in host.items() if k != "wait_until"}]},
             "runner: host_errors[0]: 'wait_until' missing or invalid"),
            ({"host_errors": [dict(host, exhausted_for={"plan": "a-impl"})]},
             "runner: host_errors[0]: 'exhausted_for' invalid"),
            ({"writing_resumes": [dict(resume, sha256="abc")]}, "runner: writing_resumes[0]: 'sha256' missing or invalid"),
            ({"writing_resumes": [dict(resume, tasks=True)]}, "runner: writing_resumes[0]: 'tasks' missing or invalid"),
        ]
        for change, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(ft._runner_errors(_marks_runner(**change)[0]), [expected])
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest skills/plan-brainstorming/tests/test_brainstorm_tool.py -k RunnerMarksTest -q`
Expected: FAIL — `test_each_rule` получает `[]` вместо ожидаемой ошибки.

- [ ] **Step 3: Implement**

В `brainstorm_tool.py` сразу после строки `RUNNER_ROADMAP_SHA_RE = re.compile(r"^[0-9a-f]{64}$")` (`:1462`):

```python
# runner.host_errors and runner.writing_resumes (spec plan-refactoring-03): optional lists of chain_tool.py host-wait
# and writing-resume; at_event = len(events) when written (the scheduler orders records by events, not by the clock).
RUNNER_HOST_ERROR_KEYS = ("plan", "stage", "at", "error", "attempt", "wait_seconds", "wait_until", "waited_total",
                          "at_event")
RUNNER_EXHAUSTED_KEYS = ("plan", "stage", "attempt", "event")
RUNNER_WRITING_RESUME_KEYS = ("plan", "tasks", "bytes", "sha256", "at_event")
```

Между концом `_runner_sessions_errors` (`return errors` на `:2271`) и `def _runner_errors(` (`:2274`):

```python
def _runner_mark_ok(name: str, value: Any) -> bool:
    """One field of a host_errors / writing_resumes record or of exhausted_for: plan and error non-empty strings,
    stage in STAGES, at and wait_until journal times, sha256 64 hex, attempt an int >= 1, the rest an int >= 0."""
    if name in ("plan", "error"):
        return isinstance(value, str) and bool(value.strip())
    if name == "stage":
        return value in STAGES
    if name in ("at", "wait_until"):
        return isinstance(value, str) and bool(JOURNAL_TIME_RE.fullmatch(value))
    if name == "sha256":
        return isinstance(value, str) and bool(RUNNER_ROADMAP_SHA_RE.match(value))
    return isinstance(value, int) and not isinstance(value, bool) and value >= (1 if name == "attempt" else 0)


def _runner_marks_errors(runner: Dict[str, Any]) -> List[str]:
    """The optional runner.host_errors and runner.writing_resumes: every key of RUNNER_HOST_ERROR_KEYS /
    RUNNER_WRITING_RESUME_KEYS (_runner_mark_ok), exhausted_for with RUNNER_EXHAUSTED_KEYS."""
    errors: List[str] = []
    for key, names in (("host_errors", RUNNER_HOST_ERROR_KEYS), ("writing_resumes", RUNNER_WRITING_RESUME_KEYS)):
        items = runner.get(key, [])
        if not isinstance(items, list):
            errors.append(f"runner: '{key}' must be a list")
            continue
        for index, item in enumerate(items):
            where = f"runner: {key}[{index}]"
            if not isinstance(item, dict):
                errors.append(f"{where}: must be an object")
                continue
            errors.extend(f"{where}: '{name}' missing or invalid" for name in names
                          if not _runner_mark_ok(name, item.get(name)))
            mark = item.get("exhausted_for")
            if "exhausted_for" in item and not (key == "host_errors" and isinstance(mark, dict) and all(
                    _runner_mark_ok(name, mark.get(name)) for name in RUNNER_EXHAUSTED_KEYS)):
                errors.append(f"{where}: 'exhausted_for' invalid")
    return errors
```

В `_runner_errors` строку `    errors.extend(_runner_sessions_errors(runner.get("sessions")))` (`:2305`) заменить на:

```python
    errors.extend(_runner_sessions_errors(runner.get("sessions")))
    errors.extend(_runner_marks_errors(runner))
```

и в докстринге `_runner_errors` после `roadmap and roadmap_sha256 (optional keys), sessions.` дописать ` The optional host_errors and writing_resumes: _runner_marks_errors.`

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest skills/plan-brainstorming/tests -q`
Expected: PASS (все тесты skill, включая `RunnerErrorsTest` и `RunnerValidateTest` из `test_journal.py`).

### Task 2: Схема журнала описывает новые списки runner

**Files:**
- Modify: `skills/plan-brainstorming/assets/chain-journal.schema.json:62-77` (сейчас: раздел `runner` без `host_errors` и `writing_resumes` / два новых свойства после `roadmap_sha256`, описание раздела называет `host-wait` и `writing-resume` / сохранить `required` раздела и прежние свойства)
- Test: `skills/plan-brainstorming/tests/test_brainstorm_tool.py`

**Preconditions:**
- Task 1: константы `RUNNER_HOST_ERROR_KEYS`, `RUNNER_EXHAUSTED_KEYS`, `RUNNER_WRITING_RESUME_KEYS` в `brainstorm_tool.py`.

**Postconditions:**
- Схема описывает `runner.host_errors` (с `exhausted_for`) и `runner.writing_resumes`; `required` раздела `runner` прежний (`RunnerSchemaTest` в `test_journal.py` проходит без правок).

- [ ] **Step 1: Write the failing test**

Перед `if __name__ == "__main__":` в `test_brainstorm_tool.py`:

```python
class RunnerMarksSchemaTest(unittest.TestCase):
    def test_schema_names_the_record_keys(self):
        path = os.path.join(SCRIPTS, "..", "assets", "chain-journal.schema.json")
        with open(path, encoding="utf-8") as fh:
            props = json.load(fh)["definitions"]["runner"]["properties"]
        host = props["host_errors"]["items"]
        self.assertEqual(tuple(host["required"]), ft.RUNNER_HOST_ERROR_KEYS)
        self.assertEqual(tuple(host["properties"]["exhausted_for"]["required"]), ft.RUNNER_EXHAUSTED_KEYS)
        self.assertEqual(tuple(host["properties"]["stage"]["enum"]), ft.STAGES)
        self.assertEqual(tuple(props["writing_resumes"]["items"]["required"]), ft.RUNNER_WRITING_RESUME_KEYS)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest skills/plan-brainstorming/tests/test_brainstorm_tool.py -k RunnerMarksSchemaTest -q`
Expected: FAIL with `KeyError: 'host_errors'`

- [ ] **Step 3: Implement**

В `chain-journal.schema.json` в описании раздела (`:62`) заменить `written by plan-chain-runner (chain_tool.py run-init, run-session)` на `written by plan-chain-runner (chain_tool.py run-init, run-session, host-wait, writing-resume)`. После строки свойства `roadmap_sha256` (`:77`, кончается на `(run-status compares it with the file)"},`) вставить:

```json
        "host_errors": {"type": "array", "description": "optional; chain_tool.py host-wait: one record per pause after a host error of an agent call; at_event = len(events) when written, so a series ends at the stage's next stage-start, stage-end or retry answer; the last record of an exhausted series carries exhausted_for",
          "items": {"type": "object", "required": ["plan", "stage", "at", "error", "attempt", "wait_seconds", "wait_until", "waited_total", "at_event"], "properties": {
            "plan": {"type": "string", "minLength": 1}, "stage": {"enum": ["writing", "revision", "split", "execution", "diffs", "audit", "commit"]},
            "at": {"$ref": "#/definitions/time"}, "error": {"type": "string", "minLength": 1}, "attempt": {"type": "integer", "minimum": 1},
            "wait_seconds": {"type": "integer", "minimum": 0}, "wait_until": {"$ref": "#/definitions/time"},
            "waited_total": {"type": "integer", "minimum": 0}, "at_event": {"type": "integer", "minimum": 0},
            "exhausted_for": {"type": "object", "required": ["plan", "stage", "attempt", "event"]}}}},
        "writing_resumes": {"type": "array", "description": "optional; chain_tool.py writing-resume: the plan file before each relaunch of a cut-off writer; three equal records in a row make run-next ask stage-failed: writing",
          "items": {"type": "object", "required": ["plan", "tasks", "bytes", "sha256", "at_event"], "properties": {
            "plan": {"type": "string", "minLength": 1}, "tasks": {"type": "integer", "minimum": 0},
            "bytes": {"type": "integer", "minimum": 0}, "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            "at_event": {"type": "integer", "minimum": 0}}}},
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest skills/plan-brainstorming/tests -q`
Expected: PASS (`RunnerMarksSchemaTest` и `RunnerSchemaTest`).

## Раннер: ошибка хоста

### Task 3.1: Классификатор ошибки хоста

**Files:**
- Modify: `skills/plan-chain-runner/scripts/chain_tool.py:1001-1013` (сейчас: `_failures` и сразу `_stage_step` / между ними — `HOST_ERROR_RE`, `HOST_WAITS`, `HOST_WAIT_TOTAL`, `_iso_at`, `_plan_entry_of` / сохранить `_failures` и `_stage_step` без изменений)
- Test: `skills/plan-chain-runner/tests/test_chain_tool.py`

**Preconditions:**
- Task 1 (форма записи `runner.host_errors`); `_parse_iso` (`chain_tool.py:1269`), `brainstorm_tool._journal_plan_id` (`brainstorm_tool.py:2068`).

**Postconditions:**
- `HOST_ERROR_RE` распознаёт 529/overloaded, 429/rate limit, 5xx API, обрыв соединения, тайм-аут и не трогает обычный текст; `_plan_entry_of` находит запись плана по id или пути.
- Тестовые помощники `_host_record` и `_HostCase` есть для следующих задач; команды и `run-next` пока не меняются.

- [ ] **Step 1: Write the failing test**

Перед `if __name__ == "__main__":` в конце `test_chain_tool.py`:

```python
def _host_record(plan_id, stage, wait, at_event=0, until="2026-10-05T10:02:00Z", total=None, **extra):
    """A valid runner.host_errors record (spec plan-refactoring-03); `extra` adds or replaces keys."""
    return dict({"plan": plan_id, "stage": stage, "at": "2026-10-05T10:00:00Z", "error": "API Error: 529 overloaded",
                 "attempt": 1, "wait_seconds": wait, "wait_until": until,
                 "waited_total": wait if total is None else total, "at_event": at_event}, **extra)


class _HostCase(_T2Case):
    """_T2Case at a fixed clock, 2026-10-05T10:00:00Z, with a helper that sets runner lists in the journal file."""
    NOW = "2026-10-05T10:00:00Z"

    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(ct, "_now", return_value=ct._parse_iso(self.NOW))
        patcher.start()
        self.addCleanup(patcher.stop)

    def marks(self, path, **lists):
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        data["runner"].update(lists)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        return path


class HostHelpersTest(unittest.TestCase):
    def test_host_error_texts(self):
        for text in ('API Error: 529 {"type":"overloaded_error"}', "API Error: 429 rate_limit_error",
                     "API Error: 503 Service Unavailable", "HTTP 502 Bad Gateway", "Connection reset by peer",
                     "socket hang up", "Request timed out", "Tool timeout after 600000ms"):
            self.assertTrue(ct.HOST_ERROR_RE.search(text), text)
        for text in ("Plan written: 28 tasks", "API Error: 400 invalid_request_error", "stage done, 3 files changed"):
            self.assertIsNone(ct.HOST_ERROR_RE.search(text), text)

    def test_time_and_plan_entry(self):
        self.assertEqual(ct._iso_at(ct._parse_iso("2026-10-05T10:00:00Z") + 90), "2026-10-05T10:01:30Z")
        data = {"plans": [{"id": "a-impl"}]}
        self.assertIs(ct._plan_entry_of(data, "docs/a-impl.md"), data["plans"][0])
        with self.assertRaisesRegex(ct.InputError, "^unknown-plan: b-impl"):
            ct._plan_entry_of(data, "b-impl")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest skills/plan-chain-runner/tests/test_chain_tool.py -k HostHelpersTest -q`
Expected: FAIL with `AttributeError: module 'chain_tool' has no attribute 'HOST_ERROR_RE'`

- [ ] **Step 3: Implement**

В `chain_tool.py` заменить стык `_failures` и `_stage_step`:

```python
    return count


def _stage_step(
```

на (новый блок между ними, `_stage_step` не меняется):

```python
    return count


# host-wait (spec plan-refactoring-03): a transient error of the host's agent call repeats the stage after a growing
# pause. HOST_ERROR_RE classifies the error text of the launch tool, never an agent's ordinary reply.
HOST_ERROR_RE = re.compile(
    r"\b(?:529|429)\b|overloaded|rate[\s_-]?limit|too many requests"
    r"|\b(?:api|http)[\s_-]*(?:error|status)?[\s:=]*5\d\d\b"
    r"|internal server error|bad gateway|service unavailable|gateway time-?out"
    r"|connection (?:reset|refused|aborted|closed|error|lost|dropped)|econnreset|socket hang up|network error"
    r"|time[sd]?[\s_-]?out", re.IGNORECASE)
HOST_WAITS = (60, 120, 300, 600)  # seconds; the last one repeats until the series has waited HOST_WAIT_TOTAL
HOST_WAIT_TOTAL = 3600


def _iso_at(seconds: float) -> str:
    """A moment in seconds as a journal time YYYY-MM-DDTHH:MM:SSZ (UTC), like _iso_now."""
    return datetime.datetime.fromtimestamp(seconds, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _plan_entry_of(data: Dict[str, Any], plan: str) -> Dict[str, Any]:
    """The journal's plan entry named by `plan`, a plan id or a plan path; unknown-plan (exit 2) without one."""
    plan_id = _brainstorm()._journal_plan_id(plan)
    entry = next((item for item in data["plans"] if item.get("id") == plan_id), None)
    if entry is None:
        raise InputError(f"unknown-plan: {plan}")
    return entry


def _stage_step(
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest skills/plan-chain-runner/tests/test_chain_tool.py -k "HostHelpersTest or StageStepTest" -q`
Expected: PASS

### Task 3.2: Серия ошибок хоста по событиям журнала

**Files:**
- Modify: `skills/plan-chain-runner/scripts/chain_tool.py` (сейчас: блок Task 3.1 кончается `_plan_entry_of` перед `def _stage_step(` / `_last_stage_move`, `_host_series_start`, `_host_series`, `_host_item` между ними / сохранить блок Task 3.1)
- Test: `skills/plan-chain-runner/tests/test_chain_tool.py`

**Preconditions:**
- Task 3.1 (`_iso_at`, `_host_record`); `_runner_of` (`chain_tool.py:657`).

**Postconditions:**
- Серия — записи стадии после её последнего `stage-start`/`stage-end` или ответа `retry` на `stage-failed: <стадия>` (`at_event` больше номера этого события; запуск агента мог упасть до первого события стадии); `_host_item` дописывает запись, исчерпанную — с `exhausted_for`.

- [ ] **Step 1: Write the failing test**

Перед `if __name__ == "__main__":` в `test_chain_tool.py`:

```python
class HostSeriesTest(unittest.TestCase):
    def test_series_follows_the_stage_events(self):
        events = [_t2_event("01:00:00", "a-impl", "writing", "stage-start"),
                  _t2_event("01:01:00", "a-impl", "revision", "stage-start"),
                  _t2_event("01:02:00", "a-impl", "writing", "question")]
        data = {"events": events, "runner": {"host_errors": [
            _host_record("a-impl", "writing", 60, at_event=0), _host_record("a-impl", "writing", 120, at_event=1),
            _host_record("b-impl", "writing", 300, at_event=3)]}}
        self.assertEqual((ct._last_stage_move(data, "a-impl", "writing"), ct._last_stage_move(data, "a-impl", "audit")),
                         (0, -1))
        self.assertEqual([item["wait_seconds"] for item in ct._host_series(data, "a-impl", "writing")], [120])

    def test_a_retry_answer_starts_a_new_series(self):
        retry = _t2_question("Q1", "a-impl", "writing", "stage-failed: writing host errors", answer="retry")
        events = [_t2_event("01:00:00", "a-impl", "writing", "stage-end"),
                  _t2_event("01:02:00", "a-impl", "writing", "answer", id="Q1", answer="retry")]
        records = [_host_record("a-impl", "writing", 60, at_event=1), _host_record("a-impl", "writing", 120, at_event=2)]
        data = {"events": events, "questions": [retry], "runner": {"host_errors": records}}
        self.assertEqual(ct._host_series_start(data, "a-impl", "writing"), 1)
        self.assertEqual([item["wait_seconds"] for item in ct._host_series(data, "a-impl", "writing")], [120])

    def test_host_item_appends_a_record(self):
        now = ct._parse_iso("2026-10-05T10:00:00Z")
        doc = {"events": [{}], "runner": {"sessions": []}}
        item = ct._host_item(doc, "j", "a-impl", "writing", " API Error: 529 ", now, 60, 1, 60)
        self.assertEqual(item, _host_record("a-impl", "writing", 60, at_event=1, until="2026-10-05T10:01:00Z",
                                            error="API Error: 529"))
        doc["events"].append({"plan": "a-impl", "stage": "writing", "kind": "stage-end"})
        last = ct._host_item(doc, "j", "a-impl", "writing", "x", now, 0, 2, 60, exhausted=True)
        self.assertEqual(last["exhausted_for"], {"plan": "a-impl", "stage": "writing", "attempt": 2, "event": 1})
        self.assertEqual(len(doc["runner"]["host_errors"]), 2)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest skills/plan-chain-runner/tests/test_chain_tool.py -k HostSeriesTest -q`
Expected: FAIL with `AttributeError: module 'chain_tool' has no attribute '_last_stage_move'`

- [ ] **Step 3: Implement**

В `chain_tool.py` перед строкой `def _stage_step(` (после `_plan_entry_of`) вставить:

```python
def _last_stage_move(data: Dict[str, Any], plan_id: str, stage: str) -> int:
    """Index in `events` of the plan stage's last stage-start or stage-end, -1 without one."""
    for index in range(len(data["events"]) - 1, -1, -1):
        event = data["events"][index]
        if (event.get("plan"), event.get("stage")) == (plan_id, stage) and event.get("kind") in ("stage-start", "stage-end"):
            return index
    return -1


def _host_series_start(data: Dict[str, Any], plan_id: str, stage: str) -> int:
    """Index in `events` after which the stage's current host-error series begins: its last stage-start or stage-end,
    or the answer `retry` to a `stage-failed: <stage>` question (a launch that failed leaves no stage-start)."""
    retried = {q.get("id") for q in data.get("questions") or []
               if (q.get("plan"), q.get("stage")) == (plan_id, stage) and q.get("answer") == "retry"
               and str(q.get("text", "")).startswith(f"stage-failed: {stage}")}
    answers = [index for index, event in enumerate(data["events"])
               if event.get("kind") == "answer" and (event.get("plan"), event.get("stage")) == (plan_id, stage)
               and (event.get("data") or {}).get("id") in retried]
    return max([_last_stage_move(data, plan_id, stage), *answers])


def _host_series(data: Dict[str, Any], plan_id: str, stage: str) -> List[Dict[str, Any]]:
    """The stage's runner.host_errors written after _host_series_start: the current series."""
    last = _host_series_start(data, plan_id, stage)
    runner = data.get("runner") if isinstance(data.get("runner"), dict) else {}
    return [item for item in runner.get("host_errors") or []
            if (item.get("plan"), item.get("stage")) == (plan_id, stage) and item.get("at_event", -1) > last]


def _host_item(doc: Dict[str, Any], journal: str, plan_id: str, stage: str, error: str, now: float, wait: int,
               attempt: int, total: int, exhausted: bool = False) -> Dict[str, Any]:
    """Append one record to runner.host_errors inside a journal_update; an exhausted one carries exhausted_for, its
    event the stage's last stage-start or stage-end (the failed stage-end)."""
    item = {"plan": plan_id, "stage": stage, "at": _iso_at(now), "error": error.strip(), "attempt": attempt,
            "wait_seconds": wait, "wait_until": _iso_at(now + wait), "waited_total": total,
            "at_event": len(doc["events"])}
    if exhausted:
        item["exhausted_for"] = {"plan": plan_id, "stage": stage, "attempt": attempt,
                                 "event": _last_stage_move(doc, plan_id, stage)}
    _runner_of(doc, journal).setdefault("host_errors", []).append(item)
    return item


```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest skills/plan-chain-runner/tests/test_chain_tool.py -k "HostSeriesTest or HostHelpersTest" -q`
Expected: PASS

### Task 4: Исчерпание серии: стадия в failed под именем раннера

**Files:**
- Modify: `skills/plan-chain-runner/scripts/chain_tool.py` (сейчас: блок Task 3.2 кончается `_host_item` перед `def _stage_step(` / новая `_host_exhaust` между ними / сохранить блоки Task 3.1–3.2)
- Test: `skills/plan-chain-runner/tests/test_chain_tool.py`

**Preconditions:**
- Task 3.2 (`_host_item`); `brainstorm_tool.journal_event` (`brainstorm_tool.py:1805`) не сверяет `--skill` с `STAGE_OWNERS`; переходы `STAGE_TRANSITIONS` (`:1715`).

**Postconditions:**
- `_host_exhaust` переводит стадию `pending`/`stopped`/`failed` → `running` → `failed` (или `running` → `failed`) с `data {"why": "host-error"}` от `plan-chain-runner` и пишет запись с `exhausted_for`; `journal-validate` проходит, `journal-show` называет прежнего `owner`.
- Стадия `stopped` с открытым вопросом даёт ошибку журнала `open-questions` и ничего не пишет.

- [ ] **Step 1: Write the failing test**

Перед `if __name__ == "__main__":` в `test_chain_tool.py`:

```python
class HostExhaustTest(_HostCase):
    def test_the_stage_fails_under_the_runner_and_is_marked(self):
        path = self.journal(["a-spec.md"], plans=[_t2_plan("a-spec.md")])
        bt = ct._brainstorm()
        item = ct._host_exhaust(path, "a-impl", "writing", "pending", "API Error: 529", ct._now(), 10, 3600)
        data = bt.journal_load(path)
        self.assertEqual(data["plans"][0]["stages"]["writing"]["status"], "failed")
        self.assertEqual([(e["skill"], e["kind"], e["data"]) for e in data["events"]],
                         [("plan-chain-runner", "stage-start", {"why": "host-error", "from": "pending", "to": "running"}),
                          ("plan-chain-runner", "stage-end", {"why": "host-error", "from": "running", "to": "failed"})])
        self.assertEqual((item["wait_seconds"], item["waited_total"], item["at_event"]), (0, 3600, 2))
        self.assertEqual(item["exhausted_for"], {"plan": "a-impl", "stage": "writing", "attempt": 10, "event": 1})
        self.assertEqual(data["runner"]["host_errors"], [item])
        self.assertEqual(bt.journal_validate(path), {"ok": True, "errors": []})
        self.assertEqual(bt.journal_show(path)["plans"][0]["owner"], "plan-writing")

    def test_a_running_stage_fails_in_one_step(self):
        path = self.journal(["a-spec.md"], plans=[_t2_plan("a-spec.md", writing="running")])
        ct._host_exhaust(path, "a-impl", "writing", "running", "API Error: 529", ct._now(), 3, 3600)
        events = ct._brainstorm().journal_load(path)["events"]
        self.assertEqual([(e["kind"], e["data"]["from"], e["data"]["to"]) for e in events],
                         [("stage-end", "running", "failed")])

    def test_a_stopped_stage_with_an_open_question_is_a_journal_error(self):
        path = self.journal(["a-spec.md"], plans=[_t2_plan("a-spec.md", writing="stopped")],
                            questions=[_t2_question("Q1", "a-impl", "writing", "which?")])
        bt = ct._brainstorm()
        with self.assertRaisesRegex(bt.JournalError, "^open-questions: Q1"):
            ct._host_exhaust(path, "a-impl", "writing", "stopped", "API Error: 529", ct._now(), 2, 3600)
        self.assertNotIn("host_errors", bt.journal_load(path)["runner"])
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest skills/plan-chain-runner/tests/test_chain_tool.py -k HostExhaustTest -q`
Expected: FAIL with `AttributeError: module 'chain_tool' has no attribute '_host_exhaust'`

- [ ] **Step 3: Implement**

В `chain_tool.py` перед строкой `def _stage_step(` (после `_host_item` из Task 3.2) вставить:

```python
def _host_exhaust(journal: str, plan_id: str, stage: str, status: str, error: str, now: float, attempt: int,
                  total: int) -> Dict[str, Any]:
    """The series has waited HOST_WAIT_TOTAL: the stage goes to failed through journal_event under plan-chain-runner
    (data why: host-error; pending, stopped and failed through running), then the record with exhausted_for. A
    stopped stage with open questions is the journal's open-questions error: nothing is written."""
    bt = _brainstorm()
    if status in ("pending", "stopped", "failed"):
        bt.journal_event(journal, "plan-chain-runner", plan_id, stage, "running", data={"why": "host-error"})
    bt.journal_event(journal, "plan-chain-runner", plan_id, stage, "failed", data={"why": "host-error"})
    return bt.journal_update(journal, lambda doc: _host_item(doc, journal, plan_id, stage, error, now, 0, attempt,
                                                             total, exhausted=True))


```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest skills/plan-chain-runner/tests/test_chain_tool.py -k "HostExhaustTest or HostHelpersTest" -q`
Expected: PASS

### Task 5: Функция host_wait: паузы, исчерпание, новая серия

**Files:**
- Modify: `skills/plan-chain-runner/scripts/chain_tool.py` (сейчас: `_host_exhaust` из Task 4 перед `def _stage_step(` / новая `host_wait` после неё / сохранить Tasks 3.1–4)
- Test: `skills/plan-chain-runner/tests/test_chain_tool.py`

**Preconditions:**
- Tasks 3.1–4; `_runner_journal` (`chain_tool.py:839`).

**Postconditions:**
- `host_wait(journal, plan, stage, error)`: не ошибка хоста → `{"ok": true, "host_error": false}`, файл журнала не меняется; иначе паузы 60, 120, 300, 600, 600… с суммой ровно 3600, затем исчерпание; повтор в исчерпанной серии ничего не пишет; после `stage-start` или ответа `retry` на `stage-failed: <стадия>` серия считается с нуля.
- `stage-not-open` (exit 1) для `done`/`skipped`; `unknown-plan`, `unknown-stage` (exit 2).

- [ ] **Step 1: Write the failing test**

Перед `if __name__ == "__main__":` в `test_chain_tool.py`:

```python
class HostWaitTest(_HostCase):
    ERROR = "API Error: 529 overloaded"

    def test_pauses_grow_to_an_hour_then_the_stage_fails(self):
        path = self.journal(["a-spec.md"], plans=[_t2_plan("a-spec.md")])
        waits = [ct.host_wait(path, "a-impl.md", "writing", self.ERROR) for _ in range(9)]
        self.assertEqual([w["wait_seconds"] for w in waits], [60, 120, 300, 600, 600, 600, 600, 600, 120])
        self.assertEqual(waits[0], {"ok": True, "host_error": True, "attempt": 1, "wait_seconds": 60,
                                    "waited_total": 60, "wait_until": "2026-10-05T10:01:00Z", "exhausted": False})
        self.assertEqual((waits[-1]["attempt"], waits[-1]["waited_total"]), (9, 3600))
        last = ct.host_wait(path, "a-impl", "writing", self.ERROR)
        self.assertEqual((last["exhausted"], last["attempt"], last["waited_total"]), (True, 10, 3600))
        bt = ct._brainstorm()
        data = bt.journal_load(path)
        self.assertEqual(data["plans"][0]["stages"]["writing"]["status"], "failed")
        self.assertTrue(ct.host_wait(path, "a-impl", "writing", self.ERROR)["exhausted"])  # nothing new
        self.assertEqual(bt.journal_load(path)["runner"]["host_errors"], data["runner"]["host_errors"])
        bt.journal_event(path, "plan-writing", "a-impl", "writing", "running")  # retry: a new series
        again = ct.host_wait(path, "a-impl", "writing", self.ERROR)
        self.assertEqual((again["attempt"], again["wait_seconds"], again["exhausted"]), (1, 60, False))

    def test_a_retry_answer_starts_a_new_series_without_a_stage_move(self):
        path = self.journal(["a-spec.md"], plans=[_t2_plan("a-spec.md")])
        for _ in range(10):  # the launch fails every time, the stage never starts: the 10th call exhausts
            ct.host_wait(path, "a-impl", "writing", self.ERROR)
        bt = ct._brainstorm()
        bt.journal_question(path, "plan-chain-runner", "a-impl", "writing", "stage-failed: writing host errors",
                            options=["retry", "stop"], answer="retry")
        again = ct.host_wait(path, "a-impl", "writing", self.ERROR)  # no stage-start in between
        self.assertEqual((again["attempt"], again["wait_seconds"], again["exhausted"]), (1, 60, False))

    def test_not_a_host_error_or_not_open(self):
        path = self.journal(["a-spec.md"], plans=[_t2_plan("a-spec.md", done=("writing",))])
        with open(path, "rb") as fh:
            before = fh.read()
        self.assertEqual(ct.host_wait(path, "a-impl", "revision", "Plan reviewed: 2 issues"),
                         {"ok": True, "host_error": False})
        with open(path, "rb") as fh:
            self.assertEqual(fh.read(), before)
        with self.assertRaisesRegex(ct.ChainError, "^stage-not-open: a-impl writing is done"):
            ct.host_wait(path, "a-impl", "writing", self.ERROR)
        with self.assertRaisesRegex(ct.InputError, "^unknown-plan: b-impl"):
            ct.host_wait(path, "b-impl", "writing", self.ERROR)
        with self.assertRaisesRegex(ct.InputError, "^unknown-stage: build"):
            ct.host_wait(path, "a-impl", "build", self.ERROR)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest skills/plan-chain-runner/tests/test_chain_tool.py -k HostWaitTest -q`
Expected: FAIL with `AttributeError: module 'chain_tool' has no attribute 'host_wait'`

- [ ] **Step 3: Implement**

В `chain_tool.py` перед строкой `def _stage_step(` (после `_host_exhaust`) вставить:

```python
def host_wait(journal: str, plan: str, stage: str, error: str) -> Dict[str, Any]:
    """A failed agent call of the plan's stage: text HOST_ERROR_RE does not match → host_error false, nothing
    written; else the next pause of HOST_WAITS, then _host_exhaust after HOST_WAIT_TOTAL. An exhausted series answers
    so and writes nothing until the stage moves or a `retry` answers its question (_host_series_start).
    stage-not-open (exit 1) for a done or skipped stage; unknown plan or stage: exit 2."""
    bt = _brainstorm()
    journal = os.path.abspath(journal)
    if stage not in bt.STAGES:
        raise InputError(f"unknown-stage: {stage}")
    data, _ = _runner_journal(journal)
    entry = _plan_entry_of(data, plan)
    plan_id, status = entry["id"], (entry["stages"].get(stage) or {}).get("status", "pending")
    if status in ("done", "skipped"):
        raise ChainError(f"stage-not-open: {plan_id} {stage} is {status}", plan=plan_id, stage=stage, status=status)
    if not HOST_ERROR_RE.search(error or ""):
        return {"ok": True, "host_error": False}
    now = _now()

    def pause(doc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        series = _host_series(doc, plan_id, stage)
        exhausted = [item for item in series if "exhausted_for" in item]
        if exhausted:
            return exhausted[-1]
        waited = sum(item["wait_seconds"] for item in series)
        wait = min(HOST_WAITS[min(len(series), len(HOST_WAITS) - 1)], HOST_WAIT_TOTAL - waited)
        if wait <= 0:
            return None
        return _host_item(doc, journal, plan_id, stage, error, now, wait, len(series) + 1, waited + wait)

    item = bt.journal_update(journal, pause)
    if item is None:
        series = _host_series(bt.journal_load(journal), plan_id, stage)
        item = _host_exhaust(journal, plan_id, stage, status, error, now, len(series) + 1,
                             sum(record["wait_seconds"] for record in series))
    return {"ok": True, "host_error": True, "attempt": item["attempt"], "wait_seconds": item["wait_seconds"],
            "waited_total": item["waited_total"], "wait_until": item["wait_until"],
            "exhausted": "exhausted_for" in item}


```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest skills/plan-chain-runner/tests/test_chain_tool.py -k "HostWaitTest or HostExhaustTest or HostHelpersTest" -q`
Expected: PASS

### Task 6: Команда host-wait и сохранение меток при run-init

**Files:**
- Modify: `skills/plan-chain-runner/scripts/chain_tool.py:8-24` (сейчас: докстринг модуля без `host-wait` / строка команды и `stage-not-open` в кодах выхода / сохранить прочие строки)
- Modify: `skills/plan-chain-runner/scripts/chain_tool.py:523-568` (сейчас: `run_init` переносит из старого раздела только `sessions`, `start_commit`, `parallel`, `roadmap` / ещё `host_errors` и `writing_resumes` / сохранить остальную сборку раздела)
- Modify: `skills/plan-chain-runner/scripts/chain_tool.py:2046-2052` (сейчас: парсер `run-next` / после него парсер `host-wait` и `cmd_host_wait` / сохранить прочие парсеры)
- Test: `skills/plan-chain-runner/tests/test_chain_tool.py`

**Preconditions:**
- Task 5 (`host_wait`).

**Postconditions:**
- `chain_tool.py host-wait <journal> --plan P --stage S --error TEXT` печатает JSON `host_wait`; exit 0 / 1 `stage-not-open` / 2 `unknown-plan`.
- Повторный `run-init` сохраняет `runner.host_errors` и `runner.writing_resumes`.

- [ ] **Step 1: Write the failing test**

Перед `if __name__ == "__main__":` в `test_chain_tool.py`:

```python
class HostWaitCliTest(JournalCase):
    def test_exit_codes_and_run_init_keeps_the_marks(self):
        folder, journal = self.make_journal("a-spec.md", "b-spec.md")
        self.assertEqual(self.init(journal, folder)[0], 0)
        bt = ct._brainstorm()
        bt.journal_event(journal, "plan-writing", os.path.join(folder, "a-impl.md"), "writing", "running",
                         spec=os.path.join(folder, "a-spec.md"))
        code, out = self.run_cli("host-wait", journal, "--plan", "a-impl", "--stage", "writing",
                                 "--error", "API Error: 529 overloaded")
        self.assertEqual((code, out["host_error"], out["attempt"], out["wait_seconds"]), (0, True, 1, 60))
        self.assertEqual(self.run_cli("host-wait", journal, "--plan", "z-impl", "--stage", "writing",
                                      "--error", "x")[0], 2)
        bt.journal_event(journal, "plan-writing", "a-impl", "writing", "done")
        code, out = self.run_cli("host-wait", journal, "--plan", "a-impl", "--stage", "writing", "--error", "x")
        self.assertEqual((code, out["errors"][0].startswith("stage-not-open: ")), (1, True))
        marks = bt.journal_load(journal)["runner"]["host_errors"]
        self.assertEqual(self.init(journal, folder)[0], 0)
        self.assertEqual(bt.journal_load(journal)["runner"]["host_errors"], marks)
        self.assertEqual(bt.journal_validate(journal), {"ok": True, "errors": []})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest skills/plan-chain-runner/tests/test_chain_tool.py -k HostWaitCliTest -q`
Expected: FAIL — argparse завершает `host-wait` с кодом 2 (`invalid choice`), первое сравнение `(2, …) != (0, True, 1, 60)` (или `TypeError` на `out` = `None`).

- [ ] **Step 3: Implement**

Докстринг модуля: после строки `  run-next       <journal> [--parallel N] [--in-flight PLAN_ID:STAGE]...` добавить строку

```text
  host-wait      <journal> --plan P --stage S --error TEXT
```

а `runner-missing, no-model) or scheduler-bug` заменить на `runner-missing, no-model, stage-not-open) or scheduler-bug`.

В `run_init` после строки `                  "sessions": old.get("sessions") if isinstance(old.get("sessions"), list) else []}` (`:568`):

```python
        for key in ("host_errors", "writing_resumes"):  # the scheduler's marks outlive a new run-init
            if isinstance(old.get(key), list):
                runner[key] = old[key]
```

и в докстринге `run_init` `Sessions of an earlier run-init stay;` заменить на `Sessions, host_errors and writing_resumes of an earlier run-init stay;`.

Перед `def cmd_run_next(` (`:1265`) вставить:

```python
def cmd_host_wait(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    return 0, host_wait(args.journal, args.plan, args.stage, args.error)


```

В `build_parser` после `    p_run_next.set_defaults(func=cmd_run_next)`:

```python
    p_host = sub.add_parser("host-wait", help="a host error of an agent call: the next pause, or the stage failed "
                                              "after an hour of pauses")
    p_host.add_argument("journal", help="path to <goal>-chain.json with a runner section")
    p_host.add_argument("--plan", required=True, help="plan id or plan path")
    p_host.add_argument("--stage", required=True, help="the stage of the agent call")
    p_host.add_argument("--error", required=True, help="the error text of the launch tool, never the agent's reply")
    p_host.set_defaults(func=cmd_host_wait)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest skills/plan-chain-runner/tests/test_chain_tool.py -k "HostWaitCliTest or RunInit or MainTest" -q`
Expected: PASS

### Task 7: run-next держит пару в host-wait до wait_until

**Files:**
- Modify: `skills/plan-chain-runner/scripts/chain_tool.py:1137-1187` (сейчас: `_candidates` даёт паре в полёте `in-flight: <stage>`, остальным — шаг или прежние причины ожидания / до `wait_until` текущей серии причина `host-wait: <N>s`, и в полёте тоже / сохранить прочие причины и их порядок)
- Modify: `skills/plan-chain-runner/scripts/chain_tool.py:1260-1262` (сейчас: `blocked` = нет действий и нет полёта / ожидание хоста — не `blocked` / сохранить `done`)
- Test: `skills/plan-chain-runner/tests/test_chain_tool.py`

**Preconditions:**
- Tasks 3.1–3.2 (`_host_series`, `_HostCase`, `_host_record`); `_parse_iso` (`chain_tool.py:1269`).

**Postconditions:**
- Пока `_now()` раньше `wait_until` последней записи текущей неисчерпанной серии, пара в `waiting` с `host-wait: <N>s` (остаток в секундах, вверх) и действия не получает, даже без `--in-flight`; в момент `wait_until` и позже ожидания нет.
- `blocked` равен `false`, пока есть ожидание `host-wait:`.

- [ ] **Step 1: Write the failing test**

Перед `if __name__ == "__main__":` в `test_chain_tool.py`:

```python
class HostRunNextTest(_HostCase):
    def test_the_pair_waits_until_wait_until(self):
        path = self.journal(["a-spec.md", "b-spec.md"], plans=[_t2_plan("a-spec.md", writing="running")])
        self.marks(path, host_errors=[_host_record("a-impl", "writing", 120)])
        result = ct.run_next(path, 3)
        self.assertEqual([(a["plan"], a["stage"]) for a in result["actions"]], [("b-impl.md", "writing")])
        self.assertEqual([(w["plan"], w["reason"]) for w in result["waiting"]], [("a-impl.md", "host-wait: 120s")])
        self.assertEqual(ct.run_next(path, 3, ["a-impl:writing"])["waiting"][0]["reason"], "host-wait: 120s")
        with mock.patch.object(ct, "_now", return_value=ct._parse_iso("2026-10-05T10:02:00Z")):
            self.assertEqual([(a["plan"], a["stage"]) for a in ct.run_next(path, 3)["actions"]],
                             [("a-impl.md", "writing"), ("b-impl.md", "writing")])

    def test_a_host_wait_is_not_blocked(self):
        path = self.journal(["a-spec.md"], plans=[_t2_plan("a-spec.md", writing="running")])
        self.marks(path, host_errors=[_host_record("a-impl", "writing", 120)])
        result = ct.run_next(path, 3)
        self.assertEqual((result["actions"], result["done"], result["blocked"]), ([], False, False))
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest skills/plan-chain-runner/tests/test_chain_tool.py -k HostRunNextTest -q`
Expected: FAIL — в `actions` есть `("a-impl.md", "writing")`, `waiting` пуст.

- [ ] **Step 3: Implement**

Перед строкой `def _stage_step(` вставить:

```python
def _host_wait_left(data: Dict[str, Any], plan_id: str, stage: str) -> Optional[int]:
    """Seconds left (rounded up) until wait_until of the stage's current host-error series; None for no series, an
    exhausted one or a moment passed. The one comparison with the clock."""
    series = _host_series(data, plan_id, stage)
    if not series or "exhausted_for" in series[-1]:
        return None
    until = _parse_iso(series[-1].get("wait_until"))
    left = None if until is None else int(-(-(until - _now()) // 1))
    return left if left is not None and left > 0 else None


```

В `_candidates` заменить

```python
        if state["entry"]["id"] in flying:
            stage = flying[state["entry"]["id"]]
            waiting.append({"spec": state["spec"], "plan": state["entry"]["plan"], "stage": stage,
                            "reason": f"in-flight: {stage}"})
            continue
```

на

```python
        if state["entry"]["id"] in flying:
            stage = flying[state["entry"]["id"]]
            left = _host_wait_left(data, state["entry"]["id"], stage)
            waiting.append({"spec": state["spec"], "plan": state["entry"]["plan"], "stage": stage,
                            "reason": f"host-wait: {left}s" if left else f"in-flight: {stage}"})
            continue
```

и

```python
        why: Optional[str] = None
        if state["open"]:
            why = "open-question: " + ", ".join(state["open"])
```

на

```python
        why: Optional[str] = None
        left = _host_wait_left(data, state["entry"]["id"], stage)
        if left:  # a host error of its agent call: the pair waits until wait_until (spec plan-refactoring-03)
            why = f"host-wait: {left}s"
        elif state["open"]:
            why = "open-question: " + ", ".join(state["open"])
```

В `run_next` заменить

```python
    done = not flying and all(state["next"] is None and not state["open"] for state in states)
    return {"ok": True, "journal_dir": os.path.dirname(os.path.abspath(journal)), "actions": actions,
            "waiting": waiting, "done": done, "blocked": not done and not actions and not flying}
```

на

```python
    done = not flying and all(state["next"] is None and not state["open"] for state in states)
    hosting = any(item["reason"].startswith("host-wait: ") for item in waiting)  # a host wait is not a stop
    return {"ok": True, "journal_dir": os.path.dirname(os.path.abspath(journal)), "actions": actions,
            "waiting": waiting, "done": done, "blocked": not done and not actions and not flying and not hosting}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest skills/plan-chain-runner/tests/test_chain_tool.py -k "HostRunNextTest or RunNextTest or CandidatesTest" -q`
Expected: PASS

### Task 8: После исчерпания run-next сразу спрашивает stage-failed

**Files:**
- Modify: `skills/plan-chain-runner/scripts/chain_tool.py:1013-1045` (сейчас: `_stage_step` спрашивает `stage-failed:` только после второго `failed` / при действующей метке `exhausted_for` — сразу, с полем `host_error` / сохранить правило двух неудач и ответы `stop`, `model:`)
- Test: `skills/plan-chain-runner/tests/test_chain_tool.py`

**Preconditions:**
- Tasks 3.1–3.2, 7 (`_last_stage_move`, `_HostCase`).

**Postconditions:**
- Пока последний `stage-start`/`stage-end` стадии — событие из `exhausted_for.event`, `run-next` для `failed` стадии возвращает `ask` `stage-failed: <stage>` с `retry`/`stop` и `host_error` (`attempt`, `waited_total`, `error`) без автоповтора; ответ `retry` даёт `run` и (как новый `stage-start`) начинает серию пауз заново (Task 5).

- [ ] **Step 1: Write the failing test**

Перед `if __name__ == "__main__":` в `test_chain_tool.py`:

```python
class HostExhaustedRunNextTest(_HostCase):
    def test_an_exhausted_stage_asks_at_once_and_retry_runs_it(self):
        entry = _t2_plan("a-spec.md", writing="failed")
        entry["stages"]["writing"].update(started_at="2026-10-05T09:00:00Z", finished_at="2026-10-05T10:00:00Z")
        events = [_t2_event("09:00:00", "a-impl", "writing", "stage-start", **{"from": "pending", "to": "running"}),
                  _t2_event("10:00:00", "a-impl", "writing", "stage-end", **{"from": "running", "to": "failed"})]
        mark = _host_record("a-impl", "writing", 0, at_event=2, total=3600, attempt=10,
                            exhausted_for={"plan": "a-impl", "stage": "writing", "attempt": 10, "event": 1})
        path = self.marks(self.journal(["a-spec.md"], plans=[entry], events=events), host_errors=[mark])
        action = ct.run_next(path, 1)["actions"][0]
        self.assertEqual((action["kind"], action["prefix"], action["options"]),
                         ("ask", "stage-failed: writing", ["retry", "stop"]))
        self.assertEqual(action["host_error"], {"attempt": 10, "waited_total": 3600, "error": "API Error: 529 overloaded"})
        retry = _t2_question("Q1", "a-impl", "writing", "stage-failed: writing host errors", answer="retry",
                             at="2026-10-05T10:05:00Z")
        path = self.marks(self.journal(["a-spec.md"], plans=[entry], events=events, questions=[retry]),
                          host_errors=[mark])
        self.assertEqual(ct.run_next(path, 1)["actions"][0]["kind"], "run")
        moved = {"events": events + [_t2_event("10:06:00", "a-impl", "writing", "stage-start")],
                 "runner": {"host_errors": [mark]}}
        self.assertIsNone(ct._host_exhausted(moved, "a-impl", "writing"))
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest skills/plan-chain-runner/tests/test_chain_tool.py -k HostExhaustedRunNextTest -q`
Expected: FAIL — первое действие `run` (одна неудача ещё повторяется), не `ask`.

- [ ] **Step 3: Implement**

Перед строкой `def _stage_step(` вставить:

```python
def _host_exhausted(data: Dict[str, Any], plan_id: str, stage: str) -> Optional[Dict[str, Any]]:
    """The stage's last record with exhausted_for while its event is still the stage's last stage-start or
    stage-end, else None: the next stage-start lifts the mark."""
    runner = data.get("runner") if isinstance(data.get("runner"), dict) else {}
    for item in reversed(runner.get("host_errors") or []):
        mark = item.get("exhausted_for")
        if (item.get("plan"), item.get("stage")) == (plan_id, stage) and isinstance(mark, dict):
            return item if mark.get("event") == _last_stage_move(data, plan_id, stage) else None
    return None


```

В `_stage_step` заменить

```python
        if not current and _failures(data, state["entry"]["id"], stage) >= 2:
            return dict(where, kind="ask", prefix=f"stage-failed: {stage}",
                        options=list(QUESTION_OPTIONS["stage-failed"]))
```

на

```python
        exhausted = _host_exhausted(data, state["entry"]["id"], stage)
        if not current and (exhausted is not None or _failures(data, state["entry"]["id"], stage) >= 2):
            ask = dict(where, kind="ask", prefix=f"stage-failed: {stage}",
                       options=list(QUESTION_OPTIONS["stage-failed"]))
            if exhausted is not None:  # an hour of host errors: no automatic repeat
                ask["host_error"] = {key: exhausted[key] for key in ("attempt", "waited_total", "error")}
            return ask
```

и в докстринге `_stage_step` `an ask (rule 10: stage-failed)` заменить на `an ask (rule 10: stage-failed; at once after an exhausted host wait)`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest skills/plan-chain-runner/tests/test_chain_tool.py -k "HostExhaustedRunNextTest or StageStepTest or AskSpecTest" -q`
Expected: PASS

## Раннер: писатель, чтение кода, статус

### Task 9: Команда writing-resume

**Files:**
- Modify: `skills/plan-chain-runner/scripts/chain_tool.py:1129-1134` (сейчас: `_writing_resumes` только читает маркер / после неё `writing_resume`, пишущая запись в `runner.writing_resumes` / сохранить `_writing_resumes`)
- Modify: `skills/plan-chain-runner/scripts/chain_tool.py:8-24` (сейчас: докстринг без `writing-resume` / строка команды и `no-marker` в кодах выхода / сохранить остальное)
- Modify: `skills/plan-chain-runner/scripts/chain_tool.py:2046-2052` (сейчас: парсер без `writing-resume` / парсер и `cmd_writing_resume` / сохранить прочие парсеры)
- Test: `skills/plan-chain-runner/tests/test_chain_tool.py`

**Preconditions:**
- Tasks 1, 3.1, 6 (`_plan_entry_of`, парсер `host-wait`); `brainstorm_tool.parse_plan_tasks` (`brainstorm_tool.py:585`) возвращает `incomplete`.

**Postconditions:**
- `writing_resume(journal, plan)` дописывает `{plan, tasks, bytes, sha256, at_event}` в `runner.writing_resumes` и возвращает его с `ok`; нет файла плана → exit 2 `plan-missing`, нет маркера → exit 1 `no-marker`, ничего не пишется.

- [ ] **Step 1: Write the failing test**

В импорты `test_chain_tool.py` после `import contextlib` добавить строку `import hashlib`. Перед `if __name__ == "__main__":`:

```python
class WritingResumeCommandTest(_T2Case):
    """Spec plan-refactoring-03: writing-resume records the plan file before a writer is relaunched."""
    PLAN = WritingResumeTest.PLAN
    write_plan = WritingResumeTest.write_plan

    def test_records_tasks_bytes_and_sha256(self):
        path = self.journal(["a-spec.md"], plans=[_t2_plan("a-spec.md", writing="running")])
        self.write_plan(marker=True)
        with open(os.path.join(self.tmp, "a-impl.md"), "rb") as fh:
            raw = fh.read()
        record = {"plan": "a-impl", "tasks": 1, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
                  "at_event": 0}
        self.assertEqual(ct.writing_resume(path, "a-impl.md"), dict({"ok": True}, **record))
        data = ct._brainstorm().journal_load(path)
        self.assertEqual(data["runner"]["writing_resumes"], [record])
        self.assertEqual(ct._brainstorm()._journal_structure_errors(data), [])

    def test_no_marker_and_no_plan_file(self):
        path = self.journal(["a-spec.md"], plans=[_t2_plan("a-spec.md", writing="running")])
        self.write_plan(marker=False)
        code, out = self.run_cli("writing-resume", path, "--plan", "a-impl")
        self.assertEqual((code, out["errors"][0]), (1, "no-marker: a-impl.md"))
        os.remove(os.path.join(self.tmp, "a-impl.md"))
        code, out = self.run_cli("writing-resume", path, "--plan", "a-impl")
        self.assertEqual((code, out["errors"][0].startswith("plan-missing: ")), (2, True))
        self.assertNotIn("writing_resumes", ct._brainstorm().journal_load(path)["runner"])
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest skills/plan-chain-runner/tests/test_chain_tool.py -k WritingResumeCommandTest -q`
Expected: FAIL with `AttributeError: module 'chain_tool' has no attribute 'writing_resume'`

- [ ] **Step 3: Implement**

После строки `    return marker is not None and bool(text) and marker(text) is not None` (конец `_writing_resumes`) вставить:

```python


def writing_resume(journal: str, plan: str) -> Dict[str, Any]:
    """Before a writer is relaunched with resume: true: the plan file's task count (parse_plan_tasks), bytes and
    sha256 appended to runner.writing_resumes. No plan file: exit 2 plan-missing; no writing marker: exit 1
    no-marker; nothing is written then."""
    bt = _brainstorm()
    journal = os.path.abspath(journal)
    data, _ = _runner_journal(journal)
    entry = _plan_entry_of(data, plan)
    path = os.path.join(os.path.dirname(journal), entry["plan"])
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError as exc:
        raise InputError(f"plan-missing: {path}: {exc}") from exc
    parsed = bt.parse_plan_tasks(raw.decode("utf-8", errors="replace"))
    if not parsed["incomplete"]:
        raise ChainError(f"no-marker: {entry['plan']}", plan=entry["id"])

    def mutate(doc: Dict[str, Any]) -> Dict[str, Any]:
        item = {"plan": entry["id"], "tasks": len(parsed["tasks"]), "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(), "at_event": len(doc["events"])}
        _runner_of(doc, journal).setdefault("writing_resumes", []).append(item)
        return item

    return dict({"ok": True}, **bt.journal_update(journal, mutate))
```

Докстринг модуля: после строки `  host-wait      <journal> --plan P --stage S --error TEXT` добавить `  writing-resume <journal> --plan P`, а `no-model, stage-not-open)` заменить на `no-model, stage-not-open, no-marker)`. Перед `def cmd_run_next(`:

```python
def cmd_writing_resume(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    return 0, writing_resume(args.journal, args.plan)


```

В `build_parser` после `    p_host.set_defaults(func=cmd_host_wait)`:

```python
    p_resume = sub.add_parser("writing-resume", help="record the plan file before a cut-off writer is relaunched")
    p_resume.add_argument("journal", help="path to <goal>-chain.json with a runner section")
    p_resume.add_argument("--plan", required=True, help="plan id or plan path")
    p_resume.set_defaults(func=cmd_writing_resume)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest skills/plan-chain-runner/tests/test_chain_tool.py -k "WritingResume" -q`
Expected: PASS

### Task 10: Продолжение писателя после failed и stopped, застой — вопрос

**Files:**
- Modify: `skills/plan-chain-runner/scripts/chain_tool.py:1137-1187` (сейчас: `resume: true` только при `running` писателе с маркером, `:1184-1185` / ещё при `failed` и `stopped`; три одинаковые записи `writing-resume` подряд — `ask` `stage-failed: writing` / сохранить шаги прочих стадий)
- Modify: `skills/plan-chain-runner/tests/test_chain_tool.py:1625-1633` (сейчас: `test_no_resume_without_the_marker_or_a_running_writing` требует нет `resume` при `failed` / теперь `failed` и `stopped` с маркером продолжаются / сохранить проверки без маркера и без плана)
- Test: `skills/plan-chain-runner/tests/test_chain_tool.py`

**Preconditions:**
- Task 9 (записи `runner.writing_resumes`); `QUESTION_OPTIONS` (`chain_tool.py:998`).

**Postconditions:**
- Писатель `running`, `failed` или `stopped` с маркером получает `resume: true`; без маркера — прежнее правило.
- Последние три записи плана после последнего ответа `retry` на `stage-failed: writing` совпадают по `tasks` и `sha256` → вместо `resume` действие `ask` `stage-failed: writing` с `retry`/`stop`.

- [ ] **Step 1: Write the failing test**

В `WritingResumeTest` заменить метод

```python
    def test_no_resume_without_the_marker_or_a_running_writing(self):
        path = self.journal(["a-spec.md"], plans=[_t2_plan("a-spec.md", writing="running")])
        self.write_plan(marker=False)
        self.assertNotIn("resume", ct.run_next(path, 1)["actions"][0])
        path = self.journal(["a-spec.md"], plans=[_t2_plan("a-spec.md", writing="failed")])
        self.write_plan(marker=True)
        self.assertNotIn("resume", ct.run_next(path, 1)["actions"][0])
        path = self.journal(["a-spec.md"])
        self.assertNotIn("resume", ct.run_next(path, 1)["actions"][0])
```

на

```python
    def test_failed_and_stopped_resume_too_but_not_without_the_marker(self):  # spec plan-refactoring-03
        path = self.journal(["a-spec.md"], plans=[_t2_plan("a-spec.md", writing="running")])
        self.write_plan(marker=False)
        self.assertNotIn("resume", ct.run_next(path, 1)["actions"][0])
        self.write_plan(marker=True)
        for status in ("failed", "stopped"):
            path = self.journal(["a-spec.md"], plans=[_t2_plan("a-spec.md", writing=status)])
            self.assertTrue(ct.run_next(path, 1)["actions"][0].get("resume"), status)
        path = self.journal(["a-spec.md"])
        self.assertNotIn("resume", ct.run_next(path, 1)["actions"][0])
```

и перед `if __name__ == "__main__":` добавить:

```python
class WritingStallTest(_T2Case):
    """Spec plan-refactoring-03: three writing-resume records without progress turn the resume into stage-failed."""
    PLAN = WritingResumeTest.PLAN
    write_plan = WritingResumeTest.write_plan
    RECORD = {"plan": "a-impl", "tasks": 1, "bytes": 10, "sha256": "a" * 64, "at_event": 0}

    def action(self, records, questions=(), events=()):
        path = self.journal(["a-spec.md"], plans=[_t2_plan("a-spec.md", writing="running")], questions=questions,
                            events=events)
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        data["runner"]["writing_resumes"] = list(records)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        return ct.run_next(path, 1)["actions"][0]

    def test_three_equal_records_ask(self):
        self.write_plan(marker=True)
        ask = self.action([self.RECORD] * 3)
        self.assertEqual((ask["kind"], ask["prefix"], ask["options"]), ("ask", "stage-failed: writing", ["retry", "stop"]))
        for change in ({"tasks": 2}, {"sha256": "b" * 64}):
            self.assertTrue(self.action([self.RECORD, self.RECORD, dict(self.RECORD, **change)])["resume"], change)
        self.assertTrue(self.action([self.RECORD] * 2)["resume"])

    def test_retry_starts_the_count_again(self):
        self.write_plan(marker=True)
        retry = _t2_question("Q1", "a-impl", "writing", "stage-failed: writing no progress", answer="retry")
        answer = _t2_event("02:00:00", "a-impl", "writing", "answer", id="Q1", answer="retry")
        later = dict(self.RECORD, at_event=1)
        self.assertTrue(self.action([self.RECORD] * 3, [retry], [answer])["resume"])
        self.assertEqual(self.action([self.RECORD] * 3 + [later] * 3, [retry], [answer])["kind"], "ask")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest skills/plan-chain-runner/tests/test_chain_tool.py -k "WritingResumeTest or WritingStallTest" -q`
Expected: FAIL — нет `resume` у `failed`/`stopped`, нет `ask` при трёх одинаковых записях.

- [ ] **Step 3: Implement**

Перед строкой `def _candidates(` вставить:

```python
def _writing_stalled(data: Dict[str, Any], state: Dict[str, Any]) -> bool:
    """No progress: the plan's last three runner.writing_resumes records after the last `retry` answer of a
    `stage-failed: writing` question have the same task count and sha256."""
    plan_id = state["entry"]["id"]
    retried = {q.get("id") for q in state["questions"] if q.get("stage") == "writing" and q.get("answer") == "retry"
               and str(q.get("text", "")).startswith("stage-failed: writing")}
    start = max((index for index, event in enumerate(data["events"])
                 if event.get("kind") == "answer" and (event.get("data") or {}).get("id") in retried), default=-1)
    runner = data.get("runner") if isinstance(data.get("runner"), dict) else {}
    marks = [(item.get("tasks"), item.get("sha256")) for item in runner.get("writing_resumes") or []
             if item.get("plan") == plan_id and item.get("at_event", -1) > start]
    return len(marks) >= 3 and len(set(marks[-3:])) == 1


```

В `_candidates` заменить

```python
            if stage == "writing" and step["running"] and step["kind"] == "run" and _writing_resumes(state):
                step["resume"] = True  # relaunched with the same brief until done, failed or stopped (LOOP.md, 4)
```

на

```python
            if (stage == "writing" and step["kind"] == "run" and _writing_resumes(state)
                    and _record(state, stage).get("status") in ("running", "failed", "stopped")):
                if _writing_stalled(data, state):  # three relaunches without progress: a question, not a fourth
                    step = dict(where, kind="ask", prefix="stage-failed: writing",
                                options=list(QUESTION_OPTIONS["stage-failed"]), running=step["running"])
                else:
                    step["resume"] = True  # relaunched with the same brief, writing-resume first (LOOP.md, 4)
```

и в докстринге `_candidates` `A running writing whose plan file carries the writing marker gets resume: true (spec 3 of plan-refactoring-02).` заменить на `A writing running, failed or stopped whose plan file carries the writing marker gets resume: true (spec 3 of plan-refactoring-02), or the stage-failed: writing ask when it stalled (_writing_stalled).`

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest skills/plan-chain-runner/tests/test_chain_tool.py -k "Writing or RunNext" -q`
Expected: PASS

### Task 11: Зеркальное правило reading-busy

**Files:**
- Modify: `skills/plan-chain-runner/scripts/chain_tool.py:1137-1187` (сейчас: шаг выбора держателя `:1160-1161` берёт первый план, дошедший до кодовых стадий, без оглядки на чужое чтение; проверка `code-busy` `:1177-1178` / шаг не выполняется, пока у другого плана `revision`/`split` `running` или в полёте; ждущий получает `reading-busy: <id>`, новые чтения — `code-busy: <ждущий>` / сохранить первые три шага выбора держателя)
- Test: `skills/plan-chain-runner/tests/test_chain_tool.py`

**Preconditions:**
- `CODE_STAGES`, `CODE_READING_STAGES` (`chain_tool.py:1083-1086`); Task 10 (правки `_candidates`).

**Postconditions:**
- План, который стал бы держателем, ждёт `reading-busy: <план-читатель>`; идущие ревизия или split продолжаются; новые `revision`/`split` и кодовые стадии других планов ждут `code-busy: <ждущий план>`; план, уже держащий кодовые стадии, правило не затрагивает (`CodeBusyReadingStagesTest` проходит без правок).

- [ ] **Step 1: Write the failing test**

Перед `if __name__ == "__main__":` в `test_chain_tool.py`:

```python
class ReadingBusyTest(_T2Case):
    """Spec plan-refactoring-03: the next holder of the code stages waits for another plan's revision or split."""

    def plans(self):
        a = _t2_plan("a-spec.md", done=("writing", "revision", "split"))  # next: execution
        b = _t2_plan("b-spec.md", done=("writing",), revision="running")
        return a, b

    def test_a_revision_in_flight_holds_the_next_holder(self):
        a, b = self.plans()
        result = ct.run_next(self.journal(["a-spec.md", "b-spec.md"], plans=[a, b]), 3, ["b-impl:revision"])
        self.assertEqual((result["actions"], [(w["plan"], w["reason"]) for w in result["waiting"]]),
                         ([], [("a-impl.md", "reading-busy: b-impl"), ("b-impl.md", "in-flight: revision")]))

    def test_a_running_revision_goes_on_and_new_readers_wait(self):
        a, b = self.plans()
        steps, waiting = CandidatesTest.candidates(self, [a, b, _t2_plan("c-spec.md", done=("writing",))])
        self.assertEqual(steps, [("b-impl.md", "revision", True)])
        self.assertEqual(waiting, [("a-impl.md", "reading-busy: b-impl"), ("c-impl.md", "code-busy: a-impl")])

    def test_after_the_reader_the_holder_then_the_others(self):
        a = _t2_plan("a-spec.md", done=("writing", "revision", "split"))
        b = _t2_plan("b-spec.md", done=("writing", "revision"))
        c = _t2_plan("c-spec.md", done=("writing",))
        steps, waiting = CandidatesTest.candidates(self, [a, b, c])
        self.assertEqual((steps, waiting), ([("a-impl.md", "execution", False)],
                                            [("b-impl.md", "code-busy: a-impl"), ("c-impl.md", "code-busy: a-impl")]))
        steps, _ = CandidatesTest.candidates(self, [_t2_plan("a-spec.md", done=T2_STAGES), b, c])
        self.assertIn(("c-impl.md", "revision", False), steps)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest skills/plan-chain-runner/tests/test_chain_tool.py -k ReadingBusyTest -q`
Expected: FAIL — `a-impl.md` получает `execution`, а `b-impl.md` ждёт `code-busy: a-impl`.

- [ ] **Step 3: Implement**

Перед строкой `def _candidates(` вставить:

```python
def _reads_code(state: Dict[str, Any], flying: Dict[str, str]) -> bool:
    """The plan reads the code now: its revision or split is running or has an agent in flight (CODE_READING_STAGES)."""
    return (flying.get(state["entry"]["id"]) in CODE_READING_STAGES
            or any(_record(state, stage).get("status") == "running" for stage in CODE_READING_STAGES))


```

В `_candidates` заменить

```python
    holder = holder or next((state for state in states if state["entry"]["id"] not in flying and not state["open"]
                             and state["next"] is not None and state["next"][0] in CODE_STAGES), None)
```

на

```python
    pending_holder = None if holder else next((state for state in states if state["entry"]["id"] not in flying
                                               and not state["open"] and state["next"] is not None
                                               and state["next"][0] in CODE_STAGES), None)
    # Mirror rule: the first plan to reach the code stages takes them only when no other plan's revision or split runs
    # or is in flight; meanwhile new readers wait for it (code-busy), so they cannot starve it.
    reader = None if pending_holder is None else next(
        (state for state in states if state is not pending_holder and _reads_code(state, flying)), None)
    if pending_holder is not None and reader is None:
        holder = pending_holder
```

и

```python
        if why is None and stage in CODE_STAGES + CODE_READING_STAGES and holder is not None and holder is not state:
            why = f"code-busy: {holder['entry']['id']}"
```

на

```python
        if why is None and stage in CODE_STAGES + CODE_READING_STAGES and holder is not None and holder is not state:
            why = f"code-busy: {holder['entry']['id']}"
        elif why is None and reader is not None:
            if state is pending_holder:
                why = f"reading-busy: {reader['entry']['id']}"
            elif stage in CODE_STAGES or (stage in CODE_READING_STAGES
                                          and _record(state, stage).get("status") != "running"):
                why = f"code-busy: {pending_holder['entry']['id']}"
```

В докстринге `_candidates` после `The revision and split of the other plans wait for the holder too (CODE_READING_STAGES).` дописать ` The first plan to reach them waits with reading-busy while another plan's revision or split runs or is in flight, and new readers wait for it (code-busy).`

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest skills/plan-chain-runner/tests/test_chain_tool.py -k "ReadingBusyTest or CodeBusyReadingStagesTest or CandidatesTest or GateSchedulerTest or RunNext" -q`
Expected: PASS

### Task 12: run-status и run-stats: новые ожидания и паузы хоста

**Files:**
- Modify: `skills/plan-chain-runner/scripts/chain_tool.py:1682-1706` (сейчас: `waits` берёт `stop`-ожидания и `code-busy:` / ещё `reading-busy:` и `host-wait:` / сохранить прочие поля `run_status`)
- Modify: `skills/plan-chain-runner/scripts/chain_tool.py:1301-1320` (сейчас: стадия `_journal_stats` без пауз хоста / `host_waits`, `host_waited_seconds` по плану и стадии из `runner.host_errors` / сохранить прочие ключи)
- Modify: `skills/plan-chain-runner/scripts/chain_tool.py:1776-1778` (сейчас: `--plan` дополняет стадии `minutes: None` / и двумя новыми ключами со значением `None` / сохранить ветку журнала)
- Test: `skills/plan-chain-runner/tests/test_chain_tool.py`

**Preconditions:**
- Tasks 7, 11 (причины `host-wait:` и `reading-busy:`).

**Postconditions:**
- `run-status` `waits` перечисляет `reading-busy:` и `host-wait: <N>s`; `run-stats` даёт каждой стадии `host_waits` (число пауз) и `host_waited_seconds` (их сумма), с `--plan` — `null`.

- [ ] **Step 1: Write the failing test**

Перед `if __name__ == "__main__":` в `test_chain_tool.py`:

```python
class HostStatusTest(_HostCase):
    def test_waits_name_reading_busy_and_host_wait(self):
        plans = [_t2_plan("a-spec.md", done=("writing", "revision", "split")),
                 _t2_plan("b-spec.md", done=("writing",), revision="running"), _t2_plan("c-spec.md", writing="running")]
        path = self.journal(["a-spec.md", "b-spec.md", "c-spec.md"], plans=plans)
        self.marks(path, host_errors=[_host_record("c-impl", "writing", 120)])
        self.assertEqual([(w["plan"], w["reason"]) for w in ct.run_status(path)["waits"]],
                         [("a-impl.md", "reading-busy: b-impl"), ("c-impl.md", "host-wait: 120s")])

    def test_run_stats_counts_the_host_waits(self):
        path = self.journal(["a-spec.md"], plans=[_t2_plan("a-spec.md", writing="running")])
        self.marks(path, host_errors=[_host_record("a-impl", "writing", 60),
                                      _host_record("a-impl", "writing", 120, attempt=2, total=180),
                                      _host_record("b-impl", "writing", 300)])
        stages = ct.run_stats(path, None)["plans"][0]["stages"]
        self.assertEqual((stages["writing"]["host_waits"], stages["writing"]["host_waited_seconds"]), (2, 180))
        self.assertEqual((stages["audit"]["host_waits"], stages["audit"]["host_waited_seconds"]), (0, 0))
        plan = os.path.join(self.tmp, "a-impl.md")
        with open(plan, "w", encoding="utf-8") as fh:
            fh.write("# P\n\n### Task 1: One\n")
        self.assertIsNone(ct.run_stats(None, plan)["plans"][0]["stages"]["writing"]["host_waits"])
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest skills/plan-chain-runner/tests/test_chain_tool.py -k HostStatusTest -q`
Expected: FAIL — `waits` пуст; `KeyError: 'host_waits'`.

- [ ] **Step 3: Implement**

В `run_status` заменить

```python
             if item["reason"] in ("stage-failed: stop", "not-confirmed: stop", "model: stop") or item["reason"].startswith("code-busy: ")]
```

на

```python
             if item["reason"] in ("stage-failed: stop", "not-confirmed: stop", "model: stop")
             or item["reason"].startswith(("code-busy: ", "reading-busy: ", "host-wait: "))]
```

и в его докстринге `model: stop, code-busy)` заменить на `model: stop, code-busy, reading-busy, host-wait)`.

В `_journal_stats` после строки `    models = runner.get("models") or {}` добавить

```python
    marks = [item for item in runner.get("host_errors") or [] if item.get("plan") == plan_id]
```

и строку `                         "actual_source": artifacts.get("cost_source")}` заменить на

```python
                         "actual_source": artifacts.get("cost_source"),
                         "host_waits": sum(1 for item in marks if item.get("stage") == stage and item.get("wait_seconds")),
                         "host_waited_seconds": sum(item.get("wait_seconds") or 0 for item in marks
                                                    if item.get("stage") == stage)}
```

В докстринге `_journal_stats` после `the actual cost the runner recorded (artifacts cost_tokens/cost_source)` дописать `, the host waits of runner.host_errors (host_waits, host_waited_seconds)`. В `_plan_stats` после строки `            item.setdefault("minutes", None)` добавить

```python
            item.setdefault("host_waits", None)
            item.setdefault("host_waited_seconds", None)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest skills/plan-chain-runner/tests/test_chain_tool.py -k "HostStatusTest or RunStatusTest or RunStats or JournalStatsTest" -q`
Expected: PASS

## Гейт splitter и отчёт о диффе

### Task 13: silent_verdict в гейте splitter

**Files:**
- Modify: `skills/plan-splitter/scripts/splitter_tool.py:628-660` (сейчас: `gate_verdict` отдаёт `verdict` `keep | split | borderline` / новое поле `silent_verdict` / не переименовывать и не менять `gate_verdict`, `GATE_THRESHOLDS`, `verdict`)
- Modify: `skills/plan-splitter/scripts/splitter_tool.py:57-61` (сейчас: докстринг команды `gate` / называет `silent_verdict` / сохранить остальное)
- Test: `skills/plan-splitter/tests/test_splitter_tool.py`

**Preconditions:**
- `GATE_THRESHOLDS` (`splitter_tool.py:131`): `split_tasks` 40 и `split_bytes` 150000 равны `SIZE_BUDGET` (контрактный тест `plan-writing/tests`).

**Postconditions:**
- `silent_verdict` = `verdict` для `keep` и `split`; для `borderline` — `keep`, если `task_count` ≤ `split_tasks` и `plan_bytes` ≤ `split_bytes`, иначе `split`. Команда `gate` печатает его тем же JSON.

- [ ] **Step 1: Write the failing test**

В классе `TestGateVerdict` после метода `test_split_and_borderline` добавить:

```python
    def test_silent_verdict(self):  # spec plan-refactoring-03: a run without a confirmation channel
        silent = lambda text: self.mod.gate_verdict(self.plan(text))["silent_verdict"]
        self.assertEqual(self.mod.gate_verdict(FIXTURE)["silent_verdict"], "keep")
        self.assertEqual(silent(_gate_plan(45, 4)), "split")
        self.assertEqual(silent(_gate_plan(30, 2)), "keep")
        self.assertEqual(silent(_gate_plan(45, 2)), "split")
        self.assertEqual(silent(_gate_plan(30, 2) + "\n" + "x" * 150001 + "\n"), "split")
        self.assertEqual(self.mod.gate_verdict(self.plan(_gate_plan(30, 2)))["verdict"], "borderline")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest skills/plan-splitter/tests/test_splitter_tool.py -k test_silent_verdict -q`
Expected: FAIL with `KeyError: 'silent_verdict'`

- [ ] **Step 3: Implement**

В `gate_verdict` после строк

```python
    else:
        verdict = "borderline"
```

вставить

```python
    # Without a confirmation channel nobody decides a borderline plan: the size budget does (spec plan-refactoring-03).
    within = count <= limits["split_tasks"] and size <= limits["split_bytes"]
    silent = verdict if verdict != "borderline" else ("keep" if within else "split")
```

и строку `    return {"ok": True, "plan": plan_path, "verdict": verdict, "factors": factors, "thresholds": limits,` заменить на

```python
    return {"ok": True, "plan": plan_path, "verdict": verdict, "silent_verdict": silent, "factors": factors,
            "thresholds": limits,
```

В докстринге `gate_verdict` после `otherwise borderline.` дописать ` silent_verdict decides borderline without a confirmation channel: keep within split_tasks and split_bytes, else split.` В докстринге модуля строку `      verdict keep | split | borderline with reasons and thresholds. Exit 1 no-tasks; exit 2 for an` заменить на

```text
      verdict keep | split | borderline with reasons and thresholds, and silent_verdict (borderline decided by the
      budget: keep within --split-tasks and --split-bytes, else split). Exit 1 no-tasks; exit 2 for an
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest skills/plan-splitter/tests -q`
Expected: PASS

### Task 14: Раннер пропускает split на borderline-keep

**Files:**
- Modify: `skills/plan-chain-runner/scripts/chain_tool.py:285-287` (сейчас: `_gate_why(factors)` пишет только `gate: keep (…)` / принимает весь ответ гейта и пишет для borderline `gate: borderline → keep (…; budget 40 tasks / 150 KB)` / сохранить текст для `keep`)
- Modify: `skills/plan-chain-runner/scripts/chain_tool.py:1024-1028` (сейчас: пропуск без агента только при `verdict == "keep"` / при `silent_verdict` `keep`, со старым splitter — по `verdict` / сохранить `gate-unavailable`)
- Test: `skills/plan-chain-runner/tests/test_chain_tool.py`

**Preconditions:**
- Task 13 (`silent_verdict`).

**Postconditions:**
- `split=auto` и borderline в бюджете → `skip` без агента с причиной из чисел и бюджета; borderline над бюджетом → `run` splitter; `keep` — прежняя причина (`SplitGateTest.test_keep_is_a_skip_without_an_agent` проходит без правок).

- [ ] **Step 1: Write the failing test**

В класс `SplitGateTest` добавить:

```python
    BORDERLINE = "# P\n\n" + "".join(f"### Task {n}: t{n}\n\n**Files:**\n- Modify: `m{n % 2}/s/f{n}.py`\n\n"
                                     for n in range(1, 31))

    def test_borderline_within_the_budget_is_kept_without_an_agent(self):  # spec plan-refactoring-03
        step = self.step(self.BORDERLINE)
        self.assertEqual(step["kind"], "skip")
        self.assertTrue(step["why"].startswith("gate: borderline → keep (30 tasks, "), step["why"])
        self.assertTrue(step["why"].endswith(" KB, 2 modules, linear; budget 40 tasks / 150 KB)"), step["why"])
        over = self.BORDERLINE + "".join(f"### Task {n}: t{n}\n\n**Files:**\n- Modify: `m{n % 2}/s/f{n}.py`\n\n"
                                         for n in range(31, 46))
        self.assertEqual(self.step(over)["kind"], "run")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest skills/plan-chain-runner/tests/test_chain_tool.py -k test_borderline_within_the_budget -q`
Expected: FAIL — `step["kind"]` равен `run`.

- [ ] **Step 3: Implement**

Заменить `_gate_why`:

```python
def _gate_why(factors: Dict[str, Any]) -> str:
    return (f"gate: keep ({factors['task_count']} tasks, {round(factors['plan_bytes'] / 1000)} KB, "
            f"{factors['modules']} modules, {factors['dependency_shape']})")
```

на

```python
def _gate_why(gate: Dict[str, Any]) -> str:
    """The skip reason of a plan the gate keeps whole: its numbers, and for a borderline plan the budget that
    decided it (silent_verdict, spec plan-refactoring-03)."""
    factors = gate["factors"]
    numbers = (f"{factors['task_count']} tasks, {round(factors['plan_bytes'] / 1000)} KB, "
               f"{factors['modules']} modules, {factors['dependency_shape']}")
    if gate["verdict"] == "keep":
        return f"gate: keep ({numbers})"
    limits = gate["thresholds"]
    return (f"gate: borderline → keep ({numbers}; budget {limits['split_tasks']} tasks / "
            f"{round(limits['split_bytes'] / 1000)} KB)")
```

В `_stage_step` заменить

```python
        if verdict is not None and verdict["verdict"] == "keep":
            return dict(where, kind="skip", why=_gate_why(verdict["factors"]))
```

на

```python
        if verdict is not None and verdict.get("silent_verdict", verdict["verdict"]) == "keep":
            return dict(where, kind="skip", why=_gate_why(verdict))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest skills/plan-chain-runner/tests/test_chain_tool.py -k "SplitGate" -q`
Expected: PASS

### Task 15: Каноническое имя отчёта о диффе: diffs_path

**Files:**
- Modify: `skills/plan-executor/scripts/executor_tool.py:1626-1632` (сейчас: `_plan_id` отрезает `.md` и `-roadmap.md` / после неё `diffs_path` / сохранить `_plan_id`)
- Test: `skills/plan-executor/tests/test_run_diff_markdown.py`

**Preconditions:**
- `ROADMAP_SUFFIX = "-roadmap.md"` (`executor_tool.py:23`).

**Postconditions:**
- `diffs_path(plan_path)` даёт `<папка плана>/<X>-diffs.md`: для `<X>-impl.md` и для его `<X>-impl-roadmap.md` — один файл; для плана без `-impl` — имя без `.md`.

- [ ] **Step 1: Write the failing test**

Перед `class TestRunDiffNoGit(RunDiffCase):` в `test_run_diff_markdown.py`:

```python
class TestDiffsPath(unittest.TestCase):
    """Spec plan-refactoring-03: one diff report per master plan, the same for its roadmap."""

    def test_one_report_per_master_plan(self):
        tool = load_tool()
        folder = Path(tempfile.gettempdir()).resolve() / "plans"
        for name in ("p1-impl.md", "p1-impl-roadmap.md", "p1.md"):
            self.assertEqual(tool.diffs_path(str(folder / name)), str(folder / "p1-diffs.md"), name)
        self.assertEqual(tool.diffs_path(str(folder / "notes-impl.md")), str(folder / "notes-diffs.md"))
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest skills/plan-executor/tests/test_run_diff_markdown.py -k TestDiffsPath -q`
Expected: FAIL with `AttributeError: module 'executor_tool' has no attribute 'diffs_path'`

- [ ] **Step 3: Implement**

После функции `_plan_id` (её последняя строка `    return name[:-3] if name.endswith(".md") else name`) вставить:

```python


def diffs_path(plan_path):
    """The run's one diff report (spec plan-refactoring-03): `<X>-diffs.md` next to the master plan, X being its file
    name without `-impl.md` (else without `.md`); a roadmap `<X>-impl-roadmap.md` names its source plan `<X>-impl.md`,
    so a split plan and a whole one have the same report. FINALIZE and COMMIT write and record this file."""
    base = _plan_id(plan_path)
    if base.endswith("-impl"):
        base = base[: -len("-impl")]
    return str(Path(plan_path).resolve().parent / f"{base}-diffs.md")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest skills/plan-executor/tests/test_run_diff_markdown.py -q`
Expected: PASS

### Task 16: run-diff --markdown пишет только канонический файл

**Files:**
- Modify: `skills/plan-executor/scripts/executor_tool.py:1673-1719` (сейчас: `run_diff_markdown(exec_dir, out_path, journal=None)` пишет любой путь / без пути — `diffs_path(plan_path)`, чужой путь — exit 2 `diffs-path-mismatch`, поле `markdown` в ответе / сохранить содержимое отчёта и прочие поля)
- Modify: `skills/plan-executor/scripts/executor_tool.py:2445-2458` (сейчас: `--markdown FILE` обязателен со значением / `--markdown` без значения допустим; `--include-fixes` по-прежнему только с ним / сохранить `include-fixes-needs-markdown`)
- Test: `skills/plan-executor/tests/test_run_diff_markdown.py`
- Test: `skills/plan-executor/tests/test_commit_run.py`

**Preconditions:**
- Task 15 (`diffs_path`); `ledger_path` (`executor_tool.py:403`), `_load` (`:486`), `ToolError(message, code, **details)` (`:63`).

**Postconditions:**
- `run-diff <exec_dir> --markdown` пишет `diffs_path(plan_path леджера)` и возвращает путь полем `markdown` (и `path`); явный путь, не равный каноническому, → exit 2 `diffs-path-mismatch`, ничего не пишется; `no-git` по-прежнему проверяется первым.
- Отчёт FINALIZE и отчёт COMMIT (с `--include-fixes`) — один и тот же файл, и для roadmap-леджера тоже.

- [ ] **Step 1: Write the failing test**

Перед `class TestRunDiffCli(RunDiffCase):` в `test_run_diff_markdown.py`:

```python
@unittest.skipUnless(shutil.which("git"), "git required")
class TestCanonicalDiffsPath(RunDiffCase):
    """Spec plan-refactoring-03: run-diff --markdown writes the one canonical report and names it."""

    def setUp(self):
        super().setUp()
        self.init_repo({"app.py": "x = 1\n"})
        self.start()
        self.unit("task-1", {"app.py": "x = 2\n"})
        self.canonical = (self.repo / "docs" / "plans" / "p1-diffs.md").resolve()

    def test_without_a_path_the_canonical_file(self):
        result = self.tool.run_diff_markdown(self.exec_dir)
        self.assertEqual((result["markdown"], result["path"]), (str(self.canonical), str(self.canonical)))
        self.assertTrue(self.canonical.is_file())

    def test_another_path_is_refused_and_nothing_is_written(self):
        wrong = self.repo / "docs" / "plans" / "p1-impl-diffs.md"
        with self.assertRaises(ValueError) as ctx:
            self.tool.run_diff_markdown(self.exec_dir, str(wrong))
        self.assertEqual(ctx.exception.code, 2)
        self.assertTrue(str(ctx.exception).startswith("diffs-path-mismatch: "))
        self.assertFalse(wrong.exists() or self.canonical.exists())

    def test_a_roadmap_run_writes_the_same_file(self):
        roadmap = self.write("docs/plans/p1-impl-roadmap.md", "# Roadmap\n")
        state = self.tool.ledger_path(self.exec_dir)
        led = json.loads(state.read_text(encoding="utf-8"))
        led["plan_path"] = str(roadmap.resolve())
        state.write_text(json.dumps(led), encoding="utf-8")
        self.assertEqual(self.tool.run_diff_markdown(self.exec_dir)["markdown"], str(self.canonical))

    def test_cli_markdown_without_a_value(self):
        code, data = run_cli("run-diff", self.exec_dir, "--markdown")
        self.assertEqual((code, data["markdown"]), (0, str(self.canonical)))
        code, data = run_cli("run-diff", self.exec_dir, "--markdown", str(self.base / "elsewhere-diffs.md"))
        self.assertEqual((code, data["errors"][0].startswith("diffs-path-mismatch: ")), (2, True))
```

Перед `if __name__ == "__main__":` в `test_commit_run.py`:

```python
class TestOneDiffReport(CommitCase):
    def test_finalize_and_commit_share_one_report(self):  # spec plan-refactoring-03
        self.commit_all()
        self.run_plan({"app.py": "x = 2\n"})
        finalize = self.tool.run_diff_markdown(self.exec_dir)["markdown"]
        self.assertTrue(self.commit()["ok"])
        self.assertEqual(self.tool.run_diff_markdown(self.exec_dir)["markdown"], finalize)
        self.assertEqual(sorted(path.name for path in (self.repo / "docs").glob("*-diffs.md")), ["plan01-diffs.md"])
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest skills/plan-executor/tests/test_run_diff_markdown.py skills/plan-executor/tests/test_commit_run.py -k "TestCanonicalDiffsPath or TestOneDiffReport" -q`
Expected: FAIL with `TypeError: run_diff_markdown() missing 1 required positional argument: 'out_path'`

- [ ] **Step 3: Implement**

В `run_diff_markdown` заменить

```python
def run_diff_markdown(exec_dir, out_path, journal=None):
```

на

```python
def run_diff_markdown(exec_dir, out_path=None, journal=None):
```

в докстринге после `The report file is overwritten (derived artifact).` дописать ` Its path is diffs_path of the ledger's plan_path: `out_path` None takes it, another path is diffs-path-mismatch (exit 2) after the git checks, and nothing is written.`, а после строки `    led = _load(exec_dir)` вставить:

```python
    canonical = diffs_path(led["plan_path"])
    if out_path is None:
        out_path = canonical
    elif os.path.normcase(os.path.realpath(out_path)) != os.path.normcase(os.path.realpath(canonical)):
        raise ToolError(f"diffs-path-mismatch: {out_path} is not the run's diff report {canonical}", 2,
                        markdown=canonical)
```

Строку `    return {"ok": True, "path": str(Path(out_path).resolve()), "lang": lang, "baseline": baseline,` заменить на

```python
    return {"ok": True, "path": str(Path(out_path).resolve()), "markdown": str(Path(out_path).resolve()),
            "lang": lang, "baseline": baseline,
```

`cmd_run_diff` и `_configure_run_diff` заменить целиком:

```python
def cmd_run_diff(args):
    if args.include_fixes and args.markdown is None:
        raise ToolError("include-fixes-needs-markdown: --include-fixes works with --markdown FILE", 2)
    if args.markdown is not None:
        return run_diff_markdown(args.exec_dir, args.markdown or None, journal=args.include_fixes)
    return run_diff(args.exec_dir)


def _configure_run_diff(parser):
    parser.add_argument("exec_dir")
    parser.add_argument("--markdown", nargs="?", const="", metavar="FILE",
                        help="write the diff report to the run's one path, <X>-diffs.md next to the master plan "
                             "(returned as markdown); a FILE other than that path is refused (diffs-path-mismatch)")
    parser.add_argument("--include-fixes", metavar="JOURNAL",
                        help="chain journal: add the audit's fix files, diffed up to the working tree")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest skills/plan-executor/tests -q`
Expected: PASS (в том числе прежние `TestRunDiffMarkdown`, `TestRunDiffCli`: их пути уже канонические, а `test_no_git_with_markdown_writes_nothing` по-прежнему получает `no-git`).

### Task 17: Checkpoint — тесты всех изменённых скриптов

- [ ] **Step 1: Run the smoke check**

Run: `python -m pytest skills/plan-brainstorming/tests skills/plan-chain-runner/tests skills/plan-splitter/tests skills/plan-executor/tests skills/plan-writing/tests -q`
Expected: все тесты проходят, 0 failed (контрактные `test_journal_contract.py` и `test_shared_paragraphs.py` — без правок).

**Done when:** команда завершилась с кодом 0 и строкой `passed` без `failed`.

## Инструкции раннера

### Task 18: LOOP.md: reading-busy, ошибка хоста, writing-resume, конец прогона

**Files:**
- Modify: `skills/plan-chain-runner/references/LOOP.md:18-24` (сейчас: §1 без borderline-skip, без `reading-busy` и без ожидания хоста / причины `gate: borderline → keep`, зеркальное правило, абзац **Host wait** / сохранить строку `the revision and the split of every other plan wait too`)
- Modify: `skills/plan-chain-runner/references/LOOP.md:56-57` (сейчас: §3 п. 2–3 — повтор после `failed` и правило not-confirmed / п. 3 начинается правилом ошибки хоста / сохранить текст not-confirmed с `--spec`)
- Modify: `skills/plan-chain-runner/references/LOOP.md:73` (сейчас: §4 — продолжение писателя только при `running` / `running`, `failed`, `stopped`, `writing-resume` перед перезапуском, застой / сохранить `resume: true`)
- Modify: `skills/plan-chain-runner/references/LOOP.md:96-101` (сейчас: §7 без ожидания хоста, без пауз в строке объёма и без `reading-busy` / дополнены / сохранить ровно две фразы `one push line (PROFILES.md, Notifications and questions)`)
- Modify: `skills/plan-chain-runner/references/LOOP.md:55` (сейчас: §3 п. 1 снимает любую пару из набора запущенных / пара в паузе хоста остаётся)
- Modify: `skills/plan-chain-runner/references/LOOP.md:132` (сейчас: Status называет `waits` без пояснения / `reading-busy`, `host-wait` кончаются сами)
- Modify: `skills/plan-chain-runner/references/DISCUSS.md:10` (сейчас: п. 4 снимает любое ожидание запуском стадии вручную / `reading-busy`, `host-wait` не остановки)

**Preconditions:**
- Tasks 6–12 (команды и причины, которые описывает текст).

**Postconditions:**
- LOOP.md описывает `host-wait` только для ошибки вызова агента, ожидание пары в полёте (пара остаётся в наборе запущенных), `writing-resume`, `reading-busy`, новые `waits` и push; DISCUSS.md и Status не велят снимать их вручную; тесты документов проходят.

- [ ] **Step 1: Apply the edits**

1. §1, строка 18: `(`why: gate: keep (<tasks> tasks, <KB> KB, <modules> modules, <shape>)`): record it` заменить на:

```markdown
(`why: gate: keep (<tasks> tasks, <KB> KB, <modules> modules, <shape>)`, or for a borderline plan within the budget `why: gate: borderline → keep (…; budget 40 tasks / 150 KB)`): record it
```

2. §1, строка 22: после `the revision's diff guard would take those changes for a violation; writing does not wait.` вставить предложение:

```markdown
 The first plan that would take free code stages does not take them while another plan's revision or split is `running` or has an agent in flight: it waits with `reading-busy: <that plan id>`, and meanwhile no new revision or split of another plan starts (`code-busy: <the waiting plan id>`), so the readers cannot starve it; a running reader goes on, and a plan that already holds the code stages is not affected.
```

3. §1, строка 24: `it feeds the progress lines, it needs no action. After `skip`, `ask` and `answer` call `run-next` again before launching anything: the answer may change.` заменить на:

```markdown
it feeds the progress lines, it needs no action, except `host-wait: <N>s` (Host wait). After `skip`, `ask` and `answer` call `run-next` again before launching anything: the answer may change.

**Host wait.** A pair waiting with `host-wait: <N>s` waits out a host error of its agent call (After the agents, 3): keep it in the in-flight set, so it counts toward `parallel`; wait `<N>` seconds the profile's way (PROFILES.md, Host errors), heartbeating (6); then call `run-next` without that pair: it comes back as the same action, launched with the same brief, without `writing-resume` (4) and without stage events. While such a wait runs, `blocked` is `false` and an empty `actions` is not the End (7). An `ask` of `stage-failed:` that carries `host_error` (`attempt`, `waited_total`, `error`) comes after an hour of host errors: its explanation names the stage, the plan, the attempts, the minutes waited and the last error text. After the answer `retry` the pauses start again from the first one.
```

4. §3 п. 2: `` `run-next` repeats it once and asks `stage-failed:` the second time.`` заменить на `` `run-next` repeats it once and asks `stage-failed:` the second time, at once after an exhausted host wait (3).``

5. §3 п. 3: начало `3. Whatever the agent did — said it finished,` заменить на:

```markdown
3. **Host error first.** The tool that launched the agent returned an error (PROFILES.md, Host errors: an API error such as 529 or 429, a dropped connection, the tool's time-out; never the agent's own final text) → `C host-wait <journal> --plan <plan id> --stage <stage> --error "<the tool's error text>"` before the rule below. `host_error: true`, `exhausted: false` → no repeat now and no question: the pair waits `wait_seconds` (1, Host wait), and the 60-minute rule below does not count during the wait. `exhausted: true` → the stage is `failed`, and the next `run-next` asks `stage-failed:` at once, with no automatic repeat. `host_error: false` → the rule below. Exit `1` `stage-not-open` → the stage is `done` or `skipped`: go to 2, but for an action with `reason` (a `done` stage entered again) the rule below applies. Exit `1` `open-questions` → the plan waits on its question; name the error in the stop report. Otherwise, whatever the agent did — said it finished,
```

6. §4, второй абзац (`A writer agent may run out of context too. …` до `A `running` writing without the marker is not confirmed (3).`) заменить целиком на:

```markdown
A writer agent may run out of context too. plan-writing writes the plan task by task with the marker `> Writing: in progress (spec sha256 <12 hex>)` as the file's last line and removes it after the last task. While `writing` is `running`, `failed` or `stopped` (`stopped`: once its question is answered) and the plan file carries the marker, `run-next` returns the stage with `resume: true`: first `C writing-resume <journal> --plan <plan id>` (it records the plan's task count and sha256; not before a relaunch that ends a host wait, 1), then a new writer agent with the same brief; it continues after the last task in the file, or writes the plan anew when the spec changed since the marker was written. `writing-resume` exit `1` `no-marker` → the marker is gone: launch as a plain `run`. Three records in a row with the same task count and sha256 (since the last `retry` of `stage-failed: writing`) mean the writer makes no progress: `run-next` returns `ask` `stage-failed: writing` instead of a fourth relaunch; `retry` starts the count again. Repeat until the stage is `done` or the plan waits on a question. A `running` writing without the marker is not confirmed (3).
```

7. §7: строку `` `actions` is empty:`` заменить на `` `actions` is empty and no pair waits with `host-wait:` (1, Host wait):``; в п. 2 `and `totals.minutes`; `run-stats` fails` заменить на ``and `totals.minutes`, then, when the run's plans (`outside_run: false`) have host waits, "host waits: <N>, <M> min" from the sums of `host_waits` and `host_waited_seconds` over their stages; `run-stats` fails``; в п. 4 `` run that stage by hand, then `continue`), and ends with the hint`` заменить на `` run that stage by hand, then `continue`; `reading-busy: <plan id>` needs nothing: the plan starts when that revision or split ends), and ends with the hint``, а `e.g. "<goal>: stopped, 2 questions — discuss", and` — на `e.g. "<goal>: stopped, 2 questions — discuss" (a `stage-failed:` after an exhausted host wait is named in it: "<goal>: stopped, host errors for an hour — discuss"), and`.

8. §3, п. 1: после `remove its pair from the in-flight set` вставить ` (a pair that waits out a host error stays in it, 3)`.

9. Status (строка 132): после ``the waits without a question (`waits`)`` вставить `; `reading-busy` and `host-wait` end by themselves: name the reason only`.

10. `skills/plan-chain-runner/references/DISCUSS.md`, п. 4: после `the runner does not ask about it again.` дописать ` `reading-busy: <plan id>` and `host-wait: <N>s` are no stops: name the reason, no way out by hand.`

- [ ] **Step 2: Verify**

Run: `python -m pytest skills/plan-chain-runner/tests/test_chain_tool.py -k "Docs" -q`
Expected: PASS (`RunnerDocsTest`, `RoadmapDocsTest`, `Spec2RunnerDocsTest`, `LightDocsTest`)

Run: `grep -c "host-wait\|writing-resume\|reading-busy" skills/plan-chain-runner/references/LOOP.md`
Expected: число ≥ 7 (строки с именами: §1 дважды, абзац Host wait, §3 п. 3, §4, §7 дважды, Status; сворачивание двух строк в одну не должно ронять проверку)

**Done when:** обе команды дали ожидаемое.

### Task 19: PROFILES.md: что такое ошибка хоста и как ждать

**Files:**
- Modify: `skills/plan-chain-runner/references/PROFILES.md:48-50` (сейчас: за `## Notifications and questions` сразу `## Models and effort` / между ними раздел `## Host errors` / сохранить порядок `Notifications and questions` раньше `Models and effort`)

**Preconditions:**
- Task 18 (LOOP.md ссылается на «PROFILES.md, Host errors»).

**Postconditions:**
- Раздел называет для `claude-code`, `github-copilot`, `fallback` ошибку вызова агента и способ ожидания; хост без ожидания — сразу вопрос `stage-failed:`.

- [ ] **Step 1: Apply the edit**

Перед строкой `## Models and effort` вставить:

```markdown
## Host errors

A host error is an error of the tool that launched the agent, not the agent's answer: an API error (529 overloaded, 429 rate limit, a 5xx), a dropped connection, the tool's own time-out. Its text goes to `C host-wait` (LOOP.md, After the agents, 3); the agent's final text never does, even when it names an error.

| Profile | A host error is | How the runner waits `wait_seconds` |
|---|---|---|
| `claude-code` | the `Agent` tool's result marked as an error (`API Error: …`, a dropped stream, the tool's time-out), not the subagent's final text | a background `sleep <wait_seconds>` (Bash with `run_in_background`), heartbeating meanwhile (LOOP.md, Session mark); on its completion notice, `run-next` |
| `github-copilot` | the `task` tool's error result (Unverified) | `sleep` in pieces of at most 600 s, `C run-session <journal> --heartbeat --id <id>` between them |
| `fallback` | the failure of the `Skill` call itself (Unverified) | as `github-copilot` |

A host with no way to wait (no shell, no `sleep`) treats the first host error as exhausted: no `host-wait`, at once `J journal-question <journal> --skill plan-chain-runner --plan <plan> --spec <spec> --stage <stage> --text "stage-failed: <stage> host error, this host cannot wait: <error text>" --option retry --option stop`.

```

- [ ] **Step 2: Verify**

Run: `python -m pytest skills/plan-chain-runner/tests/test_chain_tool.py -k "Docs" -q`
Expected: PASS (`test_push_and_question_tools` проверяет порядок разделов)

**Done when:** тесты документов проходят, в PROFILES.md есть `## Host errors` перед `## Models and effort`.

### Task 20: SKILL.md и USAGE.md раннера

**Files:**
- Modify: `skills/plan-chain-runner/SKILL.md:37-60` (сейчас: коды выхода, таблица Tool и п. 3 цикла без новых команд / `stage-not-open`, `no-marker`, строки `host-wait` и `writing-resume`, ошибка хоста в п. 3 / сохранить прочие строки таблицы)
- Modify: `skills/plan-chain-runner/USAGE.md:62-93` (сейчас: What Happens, п. 2 и Common Errors без пауз хоста, застоя и `reading-busy` / дополнены / сохранить строку `the revision and split of the others wait`)

**Preconditions:**
- Tasks 6, 9 (команды).

**Postconditions:**
- Таблица Tool называет `host-wait` и `writing-resume` с их выходами; USAGE.md объясняет паузы хоста, застой писателя и `reading-busy`.

- [ ] **Step 1: Apply the edits**

SKILL.md, строка 37: `` `runner-missing`, `no-model`).`` заменить на `` `runner-missing`, `no-model`, `stage-not-open`, `no-marker`).``. Строку таблицы `` | `C run-next <journal> [--parallel N] [--in-flight PLAN:STAGE]...` | the actions to launch now (not the in-flight pairs, which still count), the waiting plans, `done`, `blocked` |`` заменить на:

```markdown
| `C run-next <journal> [--parallel N] [--in-flight PLAN:STAGE]...` | the actions to launch now (not the in-flight pairs, which still count), the waiting plans (among the reasons `host-wait: <N>s` and `reading-busy: <plan id>`), `done`, `blocked` (`false` during a host wait) |
| `C host-wait <journal> --plan P --stage S --error TEXT` | after the launch tool's error, never the agent's reply: `host_error: false` → the not-confirmed rule; else the pause (`attempt`, `wait_seconds`, `waited_total`, `wait_until`) or `exhausted: true` (the stage is `failed`, `run-next` asks `stage-failed:` at once); exit `1` `stage-not-open` for a `done` or `skipped` stage ([LOOP.md](references/LOOP.md), After the agents, 3) |
| `C writing-resume <journal> --plan P` | before each relaunch of a writer with `resume: true`, not after a host wait: records the plan's task count and sha256; three equal records in a row make `run-next` ask `stage-failed: writing`; exit `1` `no-marker`, `2` without the plan file ([LOOP.md](references/LOOP.md), 4) |
```

П. 3 цикла: `` a stage the journal does not confirm after the agent returned`` заменить на `` a launch tool's error goes to `C host-wait` first (a pause, then the same action; after an hour `stage-failed:`); a stage the journal does not confirm after the agent returned``.

USAGE.md, п. 2 What Happens: после `like the execution of a large plan.` дописать:

```markdown
 It does so after `failed` too, and after the answer to a `stopped` writing's question; three relaunches in a row without a new task or a changed byte stop it with a `stage-failed: writing` question. A host error of an agent call (overload, rate limit, a dropped connection, a time-out) is waited out — 1, 2, 5, 10, 10… minutes, an hour at most — and the stage repeats without a question; after an hour it fails with one `stage-failed:` question. While another plan's revision or split still reads the code, the next plan does not start its execution (`reading-busy`).
```

Common Errors: после строки `` | Stage "not confirmed" | …`` вставить:

```markdown
| A `stage-failed:` question after host errors | The host refused the agent calls (529, 429, a dropped connection) for an hour | `discuss`: `retry` when the host is back, or `stop` |
| A `stage-failed: writing` question while the plan has the marker | Three relaunches of the writer in a row added no task and changed no byte | Look at the plan's last task; `discuss`: `retry` or `stop` |
| `status` shows `reading-busy: <plan>` | Another plan's revision or split still reads the code | Nothing: the plan starts when that stage ends |
```

- [ ] **Step 2: Verify**

Run: `python -m pytest skills/plan-chain-runner/tests/test_chain_tool.py -k "Docs" -q`
Expected: PASS

Run: `grep -c "host-wait\|writing-resume" skills/plan-chain-runner/SKILL.md`
Expected: число ≥ 3

**Done when:** обе команды дали ожидаемое.

### Task 21: Сценарии раннера: пауза хоста, застой писателя, reading-busy

**Files:**
- Modify: `skills/plan-chain-runner/tests/eval-scenarios.md:298-308` (сейчас: последний — Scenario 23 / в конец Scenario 24–26 / сохранить Scenario 22 и 23, их проверяет `test_eval_scenarios`)

**Preconditions:**
- Tasks 18–20.

**Postconditions:**
- Три сценария в формате файла (Setup, Trigger, Expected, Red flags) описывают поведение агента, которое тесты не ловят.

- [ ] **Step 1: Apply the edit**

В конец файла дописать:

```markdown

## Scenario 24: A host error is waited out, then the stage repeats

- **Setup:** Profile `claude-code`; the writer of plan A was launched; the `Agent` tool returns an error result
  `API Error: 529 {"type":"overloaded_error"}`; the journal still shows `writing` `running`.
- **Trigger:** The runner handles the return (LOOP.md, After the agents, 3), and later the host keeps failing for an hour.
- **Expected (PASS):** `C host-wait <journal> --plan a-impl --stage writing --error "API Error: 529 …"` → `wait_seconds: 60`;
  no `not-confirmed:` question; the pair stays in the in-flight set; a background `sleep 60` with heartbeats; then
  `run-next` without the pair returns the same action, launched with the same brief, without `writing-resume`; the
  runner writes no stage event. After an hour `exhausted: true`: `run-next` returns `ask` `stage-failed: writing` with
  `host_error`, the question names the stage, the plan, the attempts, the minutes and the error.
- **Red flags (FAIL):** `host-wait` with the agent's own final text; a `not-confirmed:` question during the pause; a
  relaunch before `wait_until`; the End or `run-session --end` during a host wait; a stage event written by the runner
  while waiting.

## Scenario 25: A writer without progress stops on a question

- **Setup:** Plan A's `writing` is `failed`; its plan file carries the marker; `run-next` returns `writing` with
  `resume: true`. Each relaunched writer is cut off before it adds a task.
- **Trigger:** The loop relaunches the writer.
- **Expected (PASS):** `C writing-resume <journal> --plan a-impl` before every relaunch; after the third equal record
  `run-next` returns `ask` `stage-failed: writing`, recorded with `J journal-question … --spec <spec>`; no fourth
  relaunch; after `retry` in `discuss` and `continue` the writer is relaunched with `writing-resume` again.
- **Red flags (FAIL):** A relaunch without `writing-resume`; `writing-resume` after a host wait; a fourth relaunch on
  the same plan bytes; the plan edited by the runner.

## Scenario 26: Execution waits for another plan's revision

- **Setup:** Three plans. A reached `execution`; B's revision agent is in flight; C's revision has not started.
- **Trigger:** `run-next` after B's launch, and again after B's revision ends.
- **Expected (PASS):** First A waits with `reading-busy: b-impl`, C with `code-busy: a-impl`, B goes on. After B's
  revision ends, A's execution starts, and C's revision starts after A's commit; `status` lists `reading-busy` as a
  wait that needs no action.
- **Red flags (FAIL):** A's execution launched while B's revision runs; C's revision started before A takes the code
  stages; `reading-busy` reported as a stop with a way out by hand.
```

- [ ] **Step 2: Verify**

Run: `python -m pytest skills/plan-chain-runner/tests/test_chain_tool.py -k "test_eval_scenarios" -q`
Expected: PASS

Run: `grep -c "^## Scenario 2[4-6]:" skills/plan-chain-runner/tests/eval-scenarios.md`
Expected: `3`

**Done when:** обе команды дали ожидаемое.

## Инструкции splitter, plan-writing, executor и writing-skills

### Task 22: splitter без вопросов в тихом прогоне

**Files:**
- Modify: `skills/plan-splitter/SKILL.md:108` (сейчас: borderline решает модель по `plan-tasks` / без канала подтверждения — `G.silent_verdict`, без вопроса / сохранить решение модели в диалоге)
- Modify: `skills/plan-splitter/SKILL.md:117-121` (сейчас: шаг 4 всегда показывает таблицу и ждёт подтверждения / без канала подтверждения `parts.json` сразу в `split-write`; «Never generate without explicit confirmation» — только для диалога / диалог не меняется)
- Modify: `skills/plan-splitter/SKILL.md:193-195` (сейчас: событие **Split done** без таблицы частей / `--artifact parts_table=…` одной строкой / сохранить `roadmap`, `parts[]`, `split_method=script`)
- Modify: `skills/plan-splitter/references/GATE-DECISION.md:9-38` (сейчас: раннер пропускает только `keep`, borderline решает модель / `silent_verdict` / сохранить таблицу Rule)
- Modify: `skills/plan-splitter/USAGE.md:42-45` (сейчас: п. 2 и 4 «What Happens» без тихого прогона / `silent_verdict`, таблица не показывается)

**Preconditions:**
- Tasks 13–14 (`silent_verdict`, пропуск borderline-keep раннером).

**Postconditions:**
- Без канала подтверждения splitter не задаёт вопросов о гейте и таблице частей и пишет `parts_table`; диалоговый режим прежний.

- [ ] **Step 1: Apply the edits**

SKILL.md, шаг 2: строку `     borderline      → decide from T (step 3) alone, never from the plan text; "keep" as above.` заменить на:

```text
     borderline      → with a confirmation channel decide from T (step 3) alone, never from the plan
                       text; without one take G.silent_verdict (keep within 40 tasks / 150 000 bytes,
                       else split), no question; "keep" as above.
```

Шаг 4 (`4. DRAFT & CONFIRM` и четыре строки после него до `Never generate without explicit confirmation.` включительно) заменить на:

```text
4. DRAFT & CONFIRM
   Write the boundaries as parts.json (references/STAGE-FORMAT.md §6) in a temp folder outside
   the repository. In a dialogue show the split table (id, title, tasks, depends, group, weight);
   on rejection with feedback retry step 3 once; on a second rejection exit without files.
   In a dialogue never generate without explicit confirmation. Without a confirmation channel
   (a chain run, a subagent call) there is nothing to confirm: no table, no question; parts.json
   goes straight to step 5, and the table reaches the journal as `parts_table` (Split done).
```

Событие **Split done**: `--artifact parts[]=<BASE>-b.md ... --artifact split_method=script`` заменить на `--artifact parts[]=<BASE>-b.md ... --artifact split_method=script --artifact "parts_table=<id>: <title> — tasks <ids>; depends <ids>; group <g>; weight <w> | …"``, а `that the stage read the task list, not the plan). The batch` — на `that the stage read the task list, not the plan; `parts_table` is the split table of step 4 as one string, the parts separated by ` | ` and `depends —` for none: each event replaces it, so a new split after drift leaves no row of the old one). The batch`.

GATE-DECISION.md: `launches the splitter and skips the stage without an agent on `keep`.` заменить на `launches the splitter and skips the stage without an agent on `keep`, and on `borderline` when `silent_verdict` is `keep`.`; после абзаца, который кончается `split when they fall into groups that each fit one agent pass.`, вставить абзац:

```markdown
Without a confirmation channel (a chain run, a subagent call) the model does not decide `borderline`:
`silent_verdict` does — `keep` when `task_count` ≤ 40 and `plan_bytes` ≤ 150 000 (`--split-tasks`,
`--split-bytes`), else `split`; for `keep` and `split` it equals `verdict`. Nobody is asked about it.
```

USAGE.md, «What Happens»: в п. 2 после `"keep" is a normal outcome` вставить `; without a confirmation channel `silent_verdict` decides borderline`; в п. 4 `you approve the split table (one retry)` заменить на `in a dialogue you approve the split table (one retry); without a confirmation channel nothing is shown or asked, and the table goes to the journal as `parts_table``.

- [ ] **Step 2: Verify**

Run: `grep -n "silent_verdict\|parts_table" skills/plan-splitter/SKILL.md skills/plan-splitter/references/GATE-DECISION.md skills/plan-splitter/USAGE.md`
Expected: строки шагов 2 и 4, события **Split done**, обоих мест GATE-DECISION.md и пунктов 2 и 4 USAGE.md.

Run: `python -m pytest skills/plan-splitter/tests -q`
Expected: PASS

**Done when:** обе команды дали ожидаемое.

### Task 23: Сценарий splitter: тихий прогон без вопросов

**Files:**
- Modify: `skills/plan-splitter/tests/eval-scenarios.md:44-52` (сейчас: последний — Scenario 4, интерактивный borderline / после него Scenario 5 / сохранить раздел How To Run в конце)

**Preconditions:**
- Task 22.

**Postconditions:**
- Сценарий проверяет, что splitter без канала подтверждения не спрашивает о гейте и таблице, а `parts_table` — одна строка.

- [ ] **Step 1: Apply the edit**

Перед строкой `## How To Run` вставить:

```markdown
## Scenario 5: A silent run asks nothing

- **Setup:** A plan of 45 tasks in 2 modules with a linear chain (`gate` gives `borderline`, `silent_verdict: split`),
  a chain journal, `split=auto`, run without a confirmation channel (as a chain agent).
- **Trigger:** `/plan-splitter <plan>`.
- **Expected (PASS):** The decision is `silent_verdict`; no `journal-question` about the gate or the split table; the
  agent writes `parts.json` from `plan-tasks` and calls `split-write` at once; `split: done` carries `roadmap`, the
  `parts[]`, `split_method=script` and one `parts_table` string with the parts separated by ` | `.
- **Red flags (FAIL):** A question "split or keep?" or "confirm the table?"; the stage left `stopped`; `parts_table[]`
  as a list; the plan file read whole.

```

- [ ] **Step 2: Verify**

Run: `grep -c "^## Scenario 5: A silent run asks nothing" skills/plan-splitter/tests/eval-scenarios.md`
Expected: `1`

**Done when:** команда вывела `1`.

### Task 24: plan-writing продолжает по маркеру после failed и stopped

**Files:**
- Modify: `skills/plan-writing/SKILL.md:86-87` (сейчас: Continuation — при `running` или `failed` / ещё при `stopped` после ответа на вопрос / сохранить сверку `marker_spec_sha` и остальной абзац)

**Preconditions:**
- Task 10 (раннер возвращает `resume: true` при `failed` и `stopped`).

**Postconditions:**
- Раздел Chain journal писателя продолжает план по маркеру при `running`, `failed` и `stopped`; общие абзацы Language не тронуты (`test_shared_paragraphs.py` проходит).

- [ ] **Step 1: Apply the edit**

Строки

```markdown
- **Continuation**, right after the `running` event of Start when the stage was `running` or `failed` and the plan
  file exists:
```

заменить на

```markdown
- **Continuation**, right after the `running` event of Start when the stage was `running`, `failed` or `stopped`
  (`stopped`: after its questions were answered and applied) and the plan file exists:
```

- [ ] **Step 2: Verify**

Run: `python -m pytest skills/plan-writing/tests -q`
Expected: PASS

Run: `grep -n "running\`, \`failed\` or \`stopped\`" skills/plan-writing/SKILL.md`
Expected: одна строка — абзац Continuation.

**Done when:** обе команды дали ожидаемое.

### Task 25: Путь отчёта о диффе в инструкциях executor

**Files:**
- Modify: `skills/plan-executor/references/WORKFLOW.md:87-108` (сейчас: FINALIZE и COMMIT строят `<diffs>` формулой / путь, который вернул `run-diff` полем `markdown` / сохранить порядок событий `diffs`)
- Modify: `skills/plan-executor/SKILL.md:37-65` (сейчас: `--markdown <file>`, `<plan dir>/<base>-diffs.md` / `--markdown` без пути и поле `markdown` / сохранить остальное)
- Modify: `skills/plan-executor/USAGE.md:54-126` (сейчас: `<base>-diffs.md`, `<plan base>-diffs.md` / `<X>-diffs.md`, путь из `run-diff` / сохранить таблицы)
- Modify: `skills/plan-executor/references/RESOLVER-PROPOSAL.md:18` (сейчас: `<plan base>-diffs.md` / путь, который вернул `run-diff --markdown` / сохранить список)
- Modify: `skills/plan-executor/tests/eval-scenarios.md:102` (сейчас: «rebuilds `<base>-diffs.md` with» / каноническое имя)

**Preconditions:**
- Task 16 (`run-diff --markdown` без пути, поле `markdown`).

**Postconditions:**
- Ни один документ executor не строит имя отчёта формулой: FINALIZE и COMMIT вызывают `run-diff <exec_dir> --markdown` и записывают в артефакт `diffs` путь из ответа.

- [ ] **Step 1: Apply the edits**

WORKFLOW.md, FINALIZE п. 2: `2. Diff report. `<diffs>` = `<dir of P>/<file name of P without -impl.md, else without .md>-diffs.md` (for a roadmap `P` is the source plan, so a split plan has one report). Stage` заменить на `2. Diff report. Stage`, а `Then `run-diff <exec_dir> --markdown <diffs>`; it compares` — на:

```markdown
Then `run-diff <exec_dir> --markdown`, without a path: the script writes the plan's one report, `<X>-diffs.md` next to the master plan (a plan and its roadmap alike), and returns its path as `markdown`; `<diffs>` below is that path, never one you build (another path is refused with exit `2` `diffs-path-mismatch`). It compares
```

COMMIT п. 1: `` `<diffs>` is built from `P`)`` заменить на `` `<diffs>` comes from `run-diff`, step 3)``. П. 3: `` `run-diff <exec_dir> --markdown <diffs> --include-fixes <journal>` (`<diffs>` as in FINALIZE), then record it`` заменить на `` `run-diff <exec_dir> --markdown --include-fixes <journal>` rewrites the same file as FINALIZE (`<diffs>` = its `markdown`; the `diffs` artifact does not change), then record it``.

SKILL.md, строка 37: `[--markdown <file> [--include-fixes <journal>]]   # what this run changed: baseline vs last unit snapshot; --markdown writes the diff report` заменить на `[--markdown [<file>] [--include-fixes <journal>]]   # what this run changed: baseline vs last unit snapshot; --markdown writes the diff report to its one path (field markdown)`. Строка 65: `` write the diff report `run-diff <exec_dir> --markdown <plan dir>/<base>-diffs.md` (the run's own changes`` заменить на `` write the diff report `run-diff <exec_dir> --markdown`, at the path it returns as `markdown` (`<X>-diffs.md` next to the master plan; the run's own changes``.

USAGE.md: `FINALIZE:   <base>-diffs.md (what this run changed)` → `FINALIZE:   <X>-diffs.md at the path run-diff returns (what this run changed)`; `` - `<plan base>-diffs.md` next to the plan — the diff report`` → `` - `<X>-diffs.md` next to the master plan `<X>-impl.md`, one for the plan and its roadmap (the path `run-diff --markdown` returns) — the diff report``; `` Commit by hand; `<plan base>-diffs.md` lists the files`` → `` Commit by hand; the diff report `<X>-diffs.md` lists the files``.

RESOLVER-PROPOSAL.md: `` - the diff report `<plan base>-diffs.md`, and`` → `` - the diff report at the path `run-diff --markdown` returned (`markdown`: `<X>-diffs.md` next to the master plan), and``.

`tests/eval-scenarios.md` (строка 102): `` rebuilds `<base>-diffs.md` with`` → `` rewrites the run's one diff report (`<X>-diffs.md`) with``.

- [ ] **Step 2: Verify**

Run: `grep -rnE "<(plan )?base>-diffs|without \.md>-diffs|--markdown <diffs>" skills/plan-executor`
Expected: пустой вывод (код выхода 1)

**Done when:** grep ничего не нашёл.

### Task 26: TOOLING.md и бриф light: commit-failed, run-diff, heredoc

**Files:**
- Modify: `skills/plan-executor/references/TOOLING.md:8-9` (сейчас: в exit 1 `delegate-check` «with … a failed hook (`commit-failed`)», в exit 2 нет `diffs-path-mismatch` / `commit-failed` — провал хука в `commit-run`; `diffs-path-mismatch` / сохранить прочие коды)
- Modify: `skills/plan-executor/references/TOOLING.md:11-13` (сейчас: за абзацем `Errors print …` идёт `## Loop Commands` / между ними раздел `## Editing code` с правилом heredoc / сохранить таблицы)
- Modify: `skills/plan-executor/references/TOOLING.md:23` (сейчас: строка `run-diff` с `--markdown FILE` / `--markdown [FILE]`, канонический путь, поле `markdown`, `diffs-path-mismatch` / сохранить описание исключений)
- Modify: `skills/plan-executor/references/EXECUTION-STRATEGY.md:32` (сейчас: п. 3 брифа субагента light (раздел Delegation, `:22`) без правила heredoc / с ним / сохранить «in this order and nothing more»)

**Preconditions:**
- Task 16.

**Postconditions:**
- Строка кодов выхода TOOLING.md не приписывает `commit-failed` команде `delegate-check`; правило heredoc есть в TOOLING.md и в брифе роли light.

- [ ] **Step 1: Apply the edits**

TOOLING.md: `` `delegate-check` with `no-git` or a failed hook (`commit-failed`), git failure.`` заменить на `` `delegate-check` with `no-git`, a hook that failed in `commit-run` (`commit-failed`; the index is restored), git failure.``; после `` `ledger-path` with `ledger-ambiguous` (both the plan's and its roadmap's ledger exist; the error names both paths),`` вставить `` `run-diff --markdown FILE` with a path other than the run's diff report (`diffs-path-mismatch`; nothing is written),``. Перед строкой `## Loop Commands` вставить:

```markdown
## Editing code

Code that holds `\n`, `\\` or regular expressions is changed only with the Edit or Write tool or through a script file, never through a bash heredoc (`cat <<EOF > file`, `python - <<EOF`): the shell folds the backslashes, and the file differs from the change intended. The same holds for a delegated unit (EXECUTION-STRATEGY.md, Delegation).

```

В строке `run-diff`: `` | `run-diff <exec_dir> [--markdown FILE [--include-fixes JOURNAL]]` | Files and `--stat` of what the run changed: baseline snapshot vs last unit snapshot. `--markdown` writes the diff report `FILE` (summary table`` заменить на:

```markdown
| `run-diff <exec_dir> [--markdown [FILE] [--include-fixes JOURNAL]]` | Files and `--stat` of what the run changed: baseline snapshot vs last unit snapshot. `--markdown` writes the diff report to the run's one path, `<X>-diffs.md` next to the master plan (`diffs_path` of the ledger's `plan_path`; a roadmap `<X>-impl-roadmap.md` names its source plan `<X>-impl.md`), returned as `markdown`; a `FILE` other than that path → `diffs-path-mismatch`, nothing written (summary table
```

и в той же строке `` returns `path`, `files`, `excluded`, `fix_files`, `ignored` `` заменить на `` returns `path`, `markdown`, `files`, `excluded`, `fix_files`, `ignored` ``.

EXECUTION-STRATEGY.md, п. 3 брифа: после `run the commands of the steps and keep their output.` дописать ` Edit code that holds `\n`, `\\` or regular expressions only with the Edit or Write tool or a script file, never through a bash heredoc, which folds the backslashes.`

- [ ] **Step 2: Verify**

Run: `grep -n "commit-failed\|diffs-path-mismatch\|heredoc" skills/plan-executor/references/TOOLING.md skills/plan-executor/references/EXECUTION-STRATEGY.md`
Expected: `commit-failed` только рядом с `commit-run`; `diffs-path-mismatch` в кодах выхода и в строке `run-diff`; `heredoc` в `## Editing code` и в п. 3 брифа.

Run: `python -m pytest skills/plan-executor/tests -q`
Expected: PASS

**Done when:** обе команды дали ожидаемое.

### Task 27: writing-skills: правило heredoc

**Files:**
- Modify: `skills/writing-skills/SKILL.md:402` (сейчас: раздел Code Examples кончается `You're good at porting - one great example is enough.` / после него абзац о правке кода / сохранить разделы)

**Preconditions:**
- нет

**Postconditions:**
- `skills/writing-skills/SKILL.md` требует править код с `\n`, `\\` и регулярными выражениями только через Edit, Write или файл-скрипт.

- [ ] **Step 1: Apply the edit**

После строки `You're good at porting - one great example is enough.` вставить:

```markdown

**Editing code and scripts:** change code that holds `\n`, `\\` or regular expressions only with the Edit or Write tool or a script file, never through a bash heredoc (`cat <<EOF > file`, `python - <<EOF`): the shell folds the backslashes, and the file differs from what you wrote.
```

- [ ] **Step 2: Verify**

Run: `grep -n "bash heredoc" skills/writing-skills/SKILL.md`
Expected: одна строка — новый абзац.

**Done when:** команда вывела эту строку.

## Документация

### Task 28: docs/HELPER-CLIS.md: новые команды, поле, флаг, коды и причины

**Files:**
- Modify: `docs/HELPER-CLIS.md:11` (сейчас: абзац `executor_tool.py`, `run-diff … --markdown FILE`, `<base>-diffs.md` / `--markdown [FILE]`, `<X>-diffs.md`, `diffs_path`, `markdown`, `diffs-path-mismatch` / сохранить остальное)
- Modify: `docs/HELPER-CLIS.md:12` (сейчас: абзац `splitter_tool.py` без `silent_verdict` / дополнен / сохранить остальное)
- Modify: `docs/HELPER-CLIS.md:16` (сейчас: абзац `brainstorm_tool.py` без новых списков `runner` / дополнен / сохранить остальное)
- Modify: `docs/HELPER-CLIS.md:17` (сейчас: абзац `chain_tool.py` кончается правилом `resume: true` только для `running` / `host-wait`, `writing-resume`, `reading-busy`, borderline-skip, `waits`, `host_waits` / сохранить остальное)

**Preconditions:**
- Tasks 1–16.

**Postconditions:**
- `docs/HELPER-CLIS.md` называет каждую новую команду, поле, флаг, код выхода и причину ожидания; `CLAUDE.md` не меняется (структурного события нет).

- [ ] **Step 1: Apply the edits**

Строка 11: `` `run-diff <exec_dir> --markdown FILE [--include-fixes JOURNAL]` writes it as the `<base>-diffs.md` report`` заменить на `` `run-diff <exec_dir> --markdown [FILE] [--include-fixes JOURNAL]` writes it as the `<X>-diffs.md` report``; после `` `ledger-init` refuses a whole plan that still carries plan-writing's writing marker with exit 1 `plan-incomplete`.`` дописать:

```markdown
 `run-diff --markdown` without a value writes the report to `diffs_path` of the ledger's `plan_path` (`<X>-diffs.md` next to the master plan; a roadmap `<X>-impl-roadmap.md` names `<X>-impl.md`) and returns it as `markdown` (and `path`); another `FILE` is exit 2 `diffs-path-mismatch` (field `markdown`; after `no-git` and `run-diff-unavailable`), nothing written; FINALIZE and COMMIT write the same file.
```

Строка 12: после `` `preflight <dir> <base>` exits 1 with `error: plan-incomplete: …` when the plan `<base>.md` in `<dir>` still carries plan-writing's writing marker.`` дописать:

```markdown
 `gate` and `gate_verdict` also return `silent_verdict`, the decision without a confirmation channel: `verdict` for `keep` and `split`; for `borderline` `keep` within `split_tasks` and `split_bytes`, else `split`. Without a confirmation channel no table is shown: `parts.json` goes straight to `split-write`, and the `done` event carries the table as one artifact string `parts_table` (parts separated by ` | `, replaced on every write).
```

Строка 16: после `` `journal-reconcile` does not take a plan with the marker as evidence of `writing`.`` дописать:

```markdown
 `journal-validate` checks the optional `runner.host_errors` and `runner.writing_resumes` (`_runner_marks_errors`: every key of the `RUNNER_*_KEYS` tuples, `exhausted_for`, journal times, `sha256` 64 hex; errors `'<key>' missing or invalid`, `'exhausted_for' invalid`).
```

Строка 17: `` `run-next` gives a `running` writing whose plan carries the writing marker `resume: true`.`` заменить на:

```markdown
`host-wait <journal> --plan P --stage S --error TEXT` classifies the error of an agent call by `HOST_ERROR_RE` (529/overloaded, 429/rate limit, a 5xx of the API, a dropped connection, a time-out): no match → `host_error: false`, nothing written; a match appends `{plan, stage, at, error, attempt, wait_seconds, wait_until, waited_total, at_event}` to `runner.host_errors` with the pauses `HOST_WAITS` 60, 120, 300, 600, then 600 until the series has waited `HOST_WAIT_TOTAL` 3600 s (the last pause cut to fit) and answers with `attempt`, `wait_seconds`, `waited_total`, `wait_until`, `exhausted`; a series starts again after a `stage-start`/`stage-end` of the stage or a `retry` answer to its `stage-failed:` question; the exhausting call moves the stage to `failed` through `journal_event` with `--skill plan-chain-runner` and `data {"why": "host-error"}` (from `pending`/`stopped`/`failed` via `running`) and writes `exhausted_for {plan, stage, attempt, event}`; exit 1 `stage-not-open` for a `done` or `skipped` stage and the journal's `open-questions` for a `stopped` stage with open questions, exit 2 `unknown-plan`, `unknown-stage`. `run-next` keeps such a pair in `waiting` with `host-wait: <N>s` until `wait_until` (in flight or not; `blocked` stays `false`), and while `exhausted_for` names the stage's last move returns `ask` `stage-failed: <stage>` at once with `host_error` (`attempt`, `waited_total`, `error`). `writing-resume <journal> --plan P` appends `{plan, tasks, bytes, sha256, at_event}` of the plan file (`parse_plan_tasks`) to `runner.writing_resumes`; exit 2 `plan-missing`, exit 1 `no-marker`. `run-next` gives `resume: true` to a writing `running`, `failed` or `stopped` whose plan carries the writing marker; three records in a row with the same `tasks` and `sha256` since the last `retry` of `stage-failed: writing` turn it into `ask` `stage-failed: writing`. The plan that would take free code stages waits with `reading-busy: <plan id>` while another plan's revision or split is `running` or in flight, and meanwhile new revisions, splits and code stages of other plans wait as `code-busy: <the waiting plan>`. With `split=auto` a `borderline` plan whose `silent_verdict` is `keep` is skipped without an agent too (`why: gate: borderline → keep (…; budget 40 tasks / 150 KB)`). `run-status` `waits` adds `reading-busy:` and `host-wait:`; `run-stats` gives every stage `host_waits` and `host_waited_seconds` (`null` with `--plan`); `run-init` keeps `runner.host_errors` and `runner.writing_resumes`.
```

- [ ] **Step 2: Verify**

Run: `grep -c "host-wait\|writing-resume\|reading-busy\|silent_verdict\|diffs-path-mismatch\|host_errors" docs/HELPER-CLIS.md`
Expected: число ≥ 4 (каждая из четырёх строк-абзацев содержит хотя бы одно имя)

**Done when:** команда вывела число ≥ 4 и строка `run-next gives a running writing … resume: true` больше не утверждает «только running».

### Task 29: TECHNOLOGIES.md и USERGUIDE.md: паузы хоста и застой писателя

**Files:**
- Modify: `docs/TECHNOLOGIES.md:180` (сейчас: таблица plan-chain-runner без приёма о паузах хоста / новая строка перед `| Trust, but verify agent reports |` / сохранить остальные строки)
- Modify: `docs/USERGUIDE.md:363` (сейчас: абзац **Scheduling.** раннера без `reading-busy`, пауз хоста и застоя / дополнен / сохранить текст абзаца)

**Preconditions:**
- Tasks 7–14.

**Postconditions:**
- В TECHNOLOGIES.md есть строка о повторе с нарастающей паузой и застое писателя; в USERGUIDE.md — предложения о `reading-busy`, паузах хоста и застое писателя.

- [ ] **Step 1: Apply the edits**

В `docs/TECHNOLOGIES.md` перед строкой, начинающейся `| Trust, but verify agent reports |`, вставить:

```markdown
| Backoff on transient host errors | Exponential backoff (Ethernet, Metcalfe & Boggs, 1976); retry budgets (Google SRE, 2016) | `host-wait` classifies the error of an agent call (529, 429, a 5xx, a dropped connection, a time-out) and repeats the stage after 60, 120, 300, 600… s until an hour is spent, then fails it with one `stage-failed:` question; a series follows the journal's events, not the clock; a writer relaunched three times without a new task or byte stops on `stage-failed: writing` |
```

В `docs/USERGUIDE.md` после `With `split=auto` the splitter's gate runs before the split stage: a plan it keeps whole skips the stage without an agent.` дописать:

```markdown
 A borderline plan within the budget (40 tasks, 150 KB) is kept whole the same way. The plan that would start its execution next waits while another plan's revision or split still reads the code (`reading-busy`), and no new revision or split starts meanwhile. A host error of an agent call (overload, rate limit, a dropped connection, a time-out) is waited out with growing pauses (1, 2, 5, 10, 10… minutes, an hour at most) and the stage repeated without a question; after an hour it fails with one `stage-failed:` question. A writer relaunched three times without a new task or byte stops on `stage-failed: writing`.
```

- [ ] **Step 2: Verify**

Run: `grep -c "Backoff on transient host errors" docs/TECHNOLOGIES.md`
Expected: `1`

Run: `grep -c "reading-busy" docs/USERGUIDE.md`
Expected: число ≥ 1

**Done when:** обе команды дали ожидаемое.

### Task 30: Checkpoint — весь набор тестов

- [ ] **Step 1: Run the smoke check**

Run: `python -m pytest skills -q`
Expected: 0 failed; число passed больше базовых 1295 на новые тесты (5 skipped, как в baseline); `test_journal_contract.py` и `test_shared_paragraphs.py` проходят без правок.

**Done when:** команда завершилась с кодом 0 без `failed`.
