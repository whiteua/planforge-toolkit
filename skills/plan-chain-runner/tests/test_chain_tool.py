"""Tests for chain_tool.py of the plan-chain-runner skill.

Run: python -m pytest skills/plan-chain-runner/tests/test_chain_tool.py -q
"""
import argparse
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


TOOL = Path(__file__).resolve().parents[1] / "scripts" / "chain_tool.py"
BRAINSTORM = Path(__file__).resolve().parents[2] / "plan-brainstorming" / "scripts" / "brainstorm_tool.py"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ct = _load("chain_tool", TOOL)


class SkeletonTest(unittest.TestCase):
    def test_roles_and_profiles_match_the_journal(self):
        bt = _load("brainstorm_tool_for_chain_test", BRAINSTORM)
        self.assertEqual(ct.ROLES, bt.ROLES)
        self.assertEqual(ct.PROFILES, bt.RUNNER_PROFILES)

    def test_home_is_planforge_home_else_dot_planforge(self):
        with mock.patch.dict(os.environ, {"PLANFORGE_HOME": "/tmp/pf-home"}):
            self.assertEqual(ct._home(), "/tmp/pf-home")
        with mock.patch.dict(os.environ, {"PLANFORGE_HOME": ""}):
            self.assertEqual(ct._home(), os.path.join(os.path.expanduser("~"), ".planforge"))


class HomeCase(unittest.TestCase):
    """A temp dir as PLANFORGE_HOME: no test writes to ~ or to the repository."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.home = os.path.join(self.tmp, "home")
        patcher = mock.patch.dict(os.environ, {"PLANFORGE_HOME": self.home})
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_main(self, *argv):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = ct.main(list(argv))
        return code, json.loads(out.getvalue())

    def run_cli(self, *argv, cwd=None):
        proc = subprocess.run([sys.executable, str(TOOL), *argv], capture_output=True, text=True,
                              encoding="utf-8", cwd=cwd, env=dict(os.environ))
        return proc.returncode, (json.loads(proc.stdout) if proc.stdout.strip() else None)


def _parser_raising(exc):
    parser = argparse.ArgumentParser()
    parser.add_subparsers().add_parser("boom").set_defaults(func=mock.Mock(side_effect=exc))
    return parser


class MainTest(HomeCase):
    def test_iso_now_follows_now(self):
        with mock.patch.object(ct, "_now", return_value=86400.0):
            self.assertEqual(ct._iso_now(), "1970-01-02T00:00:00Z")

    def test_without_command_exits_2(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(ct.main([]), 2)

    def test_errors_map_to_exit_codes(self):
        cases = ((ct.InputError("unknown-profile: x"), 2, {"ok": False, "errors": ["unknown-profile: x"]}),
                 (ct.ChainError("no-model: audit", role="audit"), 1,
                  {"ok": False, "errors": ["no-model: audit"], "role": "audit"}))
        for exc, code, payload in cases:
            with mock.patch.object(ct, "build_parser", lambda exc=exc: _parser_raising(exc)):
                self.assertEqual(self.run_main("boom"), (code, payload))

    def test_cli_help_lists_the_commands(self):
        proc = subprocess.run([sys.executable, str(TOOL), "--help"], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("settings-load", proc.stdout)


class BrainstormLoaderTest(HomeCase):
    def test_loaded_once(self):
        first = ct._brainstorm()
        self.assertIs(ct._brainstorm(), first)
        self.assertTrue(callable(first.journal_update))

    def test_missing_is_an_input_error(self):
        fake = os.path.join(self.tmp, "skills", "plan-chain-runner", "scripts", "chain_tool.py")
        with mock.patch.object(ct, "_BRAINSTORM", None), mock.patch.object(ct, "__file__", fake):
            with self.assertRaises(ct.InputError) as caught:
                ct._brainstorm()
        self.assertTrue(str(caught.exception).startswith("plan-brainstorming not installed alongside: "))

    def test_journal_errors_keep_their_exit_codes(self):
        bt = ct._brainstorm()
        for exc, code in ((bt.JournalError("journal-locked: x.lock"), 1), (bt.InputError("journal-missing: x"), 2)):
            with mock.patch.object(ct, "build_parser", lambda exc=exc: _parser_raising(exc)):
                self.assertEqual(self.run_main("boom"), (code, {"ok": False, "errors": [str(exc)]}))
        with mock.patch.object(ct, "build_parser", lambda: _parser_raising(KeyError("bug"))):
            with self.assertRaises(KeyError):
                self.run_main("boom")


class SettingsErrorsTest(unittest.TestCase):
    def test_builtin_defaults(self):
        claude = ct.BUILTIN_SETTINGS["claude-code"]
        self.assertEqual(claude["parallel"], 3)
        self.assertEqual({r: (e["model"], e["effort"]) for r, e in claude["roles"].items()},
                         {"writing": ("fable", "high"), "revision": ("fable", "high"), "split": ("opus", "medium"),
                          "execution": ("opus", "medium"), "audit": ("fable", "high"), "commit": ("sonnet", "low")})
        copilot = ct.BUILTIN_SETTINGS["github-copilot"]["roles"]
        self.assertEqual(copilot["audit"], {"model": "claude-opus-5.5", "effort": None, "fallback": "gpt-5-mini"})
        self.assertEqual(copilot["execution"]["model"], "claude-sonnet-5.5")
        self.assertEqual(copilot["commit"]["model"], "gpt-5-mini")
        self.assertEqual(ct.BUILTIN_SETTINGS["fallback"]["parallel"], 1)
        for name in ct.PROFILES:
            self.assertEqual(tuple(ct.BUILTIN_SETTINGS[name]["roles"]), ct.ROLES)

    def test_valid_document_has_no_errors(self):
        data = {"profiles": {"claude-code": {"parallel": 2, "roles": {"audit": {"model": "opus", "effort": None}}}}}
        self.assertEqual(ct._settings_errors(data), [])

    def test_errors_are_listed(self):
        data = {"extra": 1, "profiles": {"nope": {}, "fallback": {"parallel": 0},
                                         "claude-code": {"roles": {"design": {}, "audit": {"model": 5, "x": 1}}}}}
        self.assertEqual(ct._settings_errors(data), [
            "settings: unknown key 'extra'", "unknown-profile: nope",
            "profiles.fallback.parallel: must be an integer >= 1", "unknown-role: design",
            "profiles.claude-code.roles.audit: unknown key 'x'",
            "profiles.claude-code.roles.audit.model: must be a non-empty string or null"])
        self.assertEqual(ct._settings_errors([]), ["settings: must be an object"])


class SettingsLoadTest(HomeCase):
    def write_settings(self, data):
        os.makedirs(self.home, exist_ok=True)
        path = os.path.join(self.home, "runner.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(data if isinstance(data, str) else json.dumps(data))
        return path

    def test_no_file_gives_builtin(self):
        code, out = self.run_main("settings-load", "--profile", "claude-code")
        self.assertEqual((code, out["ok"], out["source"], out["parallel"], out["errors"]), (0, True, "builtin", 3, []))
        self.assertEqual(out["roles"]["commit"], {"model": "sonnet", "effort": "low"})
        self.assertEqual(self.run_main("settings-load", "--profile", "fallback")[1]["parallel"], 1)

    def test_partial_file_fills_missing_roles_from_builtin(self):
        self.write_settings({"profiles": {"claude-code": {"roles": {"audit": {"effort": "max"}}}}})
        code, out = self.run_main("settings-load", "--profile", "claude-code")
        self.assertEqual((code, out["source"], out["parallel"]), (0, "file", 3))
        self.assertEqual(out["roles"]["audit"], {"model": "fable", "effort": "max"})
        self.assertEqual(out["roles"]["writing"], {"model": "fable", "effort": "high"})
        self.assertEqual(self.run_main("settings-load", "--profile", "github-copilot")[1]["source"], "builtin")

    def test_pinned_marks_full_model_ids(self):
        out = self.run_main("settings-load", "--profile", "claude-code")[1]
        self.assertEqual(out["pinned"], {role: False for role in ct.ROLES})
        self.assertEqual(self.run_main("settings-load", "--profile", "fallback")[1]["pinned"],
                         {role: False for role in ct.ROLES})
        self.write_settings({"profiles": {"claude-code": {"roles": {"audit": {"model": "claude-sonnet-5-5"}}}}})
        out = self.run_main("settings-load", "--profile", "claude-code")[1]
        self.assertEqual(out["pinned"], dict({role: False for role in ct.ROLES}, audit=True))
        self.assertEqual(out["roles"]["audit"], {"model": "claude-sonnet-5-5", "effort": "high"})

    def test_file_option_wins_over_home(self):
        path = os.path.join(self.tmp, "my.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"profiles": {"fallback": {"parallel": 2}}}, fh)
        self.assertEqual(self.run_main("settings-load", "--file", path, "--profile", "fallback")[1]["parallel"], 2)

    def test_invalid_input_exits_2(self):
        self.write_settings("{broken")
        code, out = self.run_main("settings-load", "--profile", "claude-code")
        self.assertEqual(code, 2)
        self.assertTrue(out["errors"][0].startswith("settings-invalid-json: "))
        self.write_settings({"profiles": {"claude-code": {"roles": {"design": {}}}}})
        code, out = self.run_main("settings-load", "--profile", "claude-code")
        self.assertEqual((code, out["ok"], out["errors"]), (2, False, ["unknown-role: design"]))
        self.assertEqual(self.run_main("settings-load", "--profile", "vscode"),
                         (2, {"ok": False, "errors": ["unknown-profile: vscode"]}))


class SettingsSaveTest(HomeCase):
    def test_creates_home_and_merges_profiles(self):
        roles = json.dumps({"audit": {"model": "opus", "effort": "high"}})
        code, out = self.run_main("settings-save", "--profile", "claude-code", "--roles", roles)
        path = os.path.join(self.home, "runner.json")
        self.assertEqual((code, out), (0, {"ok": True, "path": path}))
        self.run_main("settings-save", "--profile", "fallback", "--roles", '{"commit": {"model": "x"}}')
        self.run_main("settings-save", "--profile", "claude-code", "--roles", '{"split": {"model": "sonnet"}}')
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data["profiles"]["claude-code"]["roles"],
                         {"audit": {"model": "opus", "effort": "high"}, "split": {"model": "sonnet"}})
        self.assertEqual(data["profiles"]["fallback"], {"roles": {"commit": {"model": "x"}}})
        loaded = self.run_main("settings-load", "--profile", "claude-code")[1]
        self.assertEqual(loaded["roles"]["split"], {"model": "sonnet", "effort": "medium"})

    def test_rejects_bad_roles_and_keeps_an_invalid_file(self):
        self.assertEqual(self.run_main("settings-save", "--profile", "claude-code", "--roles", '{"design": {}}'),
                         (2, {"ok": False, "errors": ["unknown-role: design"]}))
        os.makedirs(self.home)
        path = os.path.join(self.home, "runner.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write('{"profiles": {"nope": {}}}')
        code, out = self.run_main("settings-save", "--profile", "claude-code", "--roles", "{}")
        self.assertEqual(code, 2)
        self.assertIn("unknown-profile: nope", out["errors"][0])
        with open(path, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), '{"profiles": {"nope": {}}}')

    def test_failed_replace_leaves_the_old_file(self):
        self.run_main("settings-save", "--profile", "claude-code", "--roles", '{"audit": {"model": "opus"}}')
        path = os.path.join(self.home, "runner.json")
        with open(path, "rb") as fh:
            before = fh.read()
        with mock.patch.object(ct._brainstorm(), "_replace_retrying", side_effect=OSError("disk full")):
            code, out = self.run_main("settings-save", "--profile", "claude-code", "--roles", '{"audit": {"model": "x"}}')
        self.assertEqual((code, out["errors"][0].startswith("cannot write ")), (2, True))
        with open(path, "rb") as fh:
            self.assertEqual(fh.read(), before)
        self.assertEqual(os.listdir(self.home), ["runner.json"])

    @unittest.skipIf(os.name == "nt", "POSIX permission bits")
    def test_keeps_file_mode(self):
        self.run_main("settings-save", "--profile", "claude-code", "--roles", '{"audit": {"model": "opus"}}')
        path = os.path.join(self.home, "runner.json")
        os.chmod(path, 0o600)
        self.run_main("settings-save", "--profile", "claude-code", "--roles", '{"audit": {"model": "x"}}')
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)


class ModelPickTest(HomeCase):
    def pick(self, *argv):
        return self.run_main("model-pick", *argv)

    def test_plain_pick(self):
        self.assertEqual(self.pick("--profile", "claude-code", "--role", "audit"),
                         (0, {"ok": True, "model": "fable", "effort": "high", "fallback_used": False}))
        self.assertEqual(self.pick("--profile", "fallback", "--role", "writing")[1]["model"], None)

    def test_unsupported_uses_the_fallback(self):
        self.assertEqual(self.pick("--profile", "github-copilot", "--role", "audit", "--unsupported", "claude-opus-5.5"),
                         (0, {"ok": True, "model": "gpt-5-mini", "effort": None, "fallback_used": True}))

    def test_no_model_left_exits_1(self):
        code, out = self.pick("--profile", "github-copilot", "--role", "audit",
                              "--unsupported", "claude-opus-5.5", "--unsupported", "gpt-5-mini")
        self.assertEqual((code, out["errors"], out["role"]), (1, ["no-model: audit"], "audit"))
        code, out = self.pick("--profile", "claude-code", "--role", "commit", "--unsupported", "sonnet")
        self.assertEqual((code, out["errors"]), (1, ["no-model: commit"]))

    def test_unknown_role_exits_2(self):
        self.assertEqual(self.pick("--profile", "claude-code", "--role", "design"),
                         (2, {"ok": False, "errors": ["unknown-role: design"]}))


class ExampleSettingsTest(HomeCase):
    EXAMPLE = Path(__file__).resolve().parents[1] / "assets" / "runner.example.json"

    def test_example_loads_with_full_model_ids(self):
        for profile in ("claude-code", "github-copilot"):
            code, out = self.run_main("settings-load", "--file", str(self.EXAMPLE), "--profile", profile)
            self.assertEqual((code, out["source"], out["errors"]), (0, "file", []))
            self.assertEqual(tuple(out["roles"]), ct.ROLES)
            self.assertEqual(out["parallel"], ct.BUILTIN_SETTINGS[profile]["parallel"])
        out = self.run_main("settings-load", "--file", str(self.EXAMPLE), "--profile", "claude-code")[1]
        self.assertEqual(out["pinned"], {role: True for role in ct.ROLES})  # an alias would not pin the version


class RunInitHelpersTest(unittest.TestCase):
    def test_runner_models_keep_fallback_and_check_roles(self):
        models = {"audit": {"model": "claude-opus-5.5", "effort": None, "fallback": "gpt-5-mini"}, "commit": {}}
        self.assertEqual(ct._runner_models(models), {"audit": {"model": "claude-opus-5.5", "effort": None,
                                                               "fallback": "gpt-5-mini"},
                                                     "commit": {"model": None, "effort": None}})
        with self.assertRaises(ct.InputError) as caught:
            ct._runner_models({"design": {"model": "x"}})
        self.assertEqual(str(caught.exception), "unknown-role: design")

    def test_start_commit_forms(self):
        for value in ("a1b2c3d", "0123456789abcdef0123456789abcdef01234567"):
            self.assertTrue(ct.START_COMMIT_RE.match(value))
        for value in ("a1b2c3", "A1B2C3D", "declined!", "xyzxyzx"):
            self.assertFalse(ct.START_COMMIT_RE.match(value))


class JournalCase(HomeCase):
    def make_journal(self, *names):
        """<tmp>/docs/goal-chain.json with the specs `names` registered through brainstorm_tool."""
        folder = os.path.join(self.tmp, "docs")
        os.makedirs(folder, exist_ok=True)
        journal = os.path.join(folder, "goal-chain.json")
        for name in names:
            path = os.path.join(folder, name)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("# Goal\n\nSpec " + name + "\n")
            ct._brainstorm().journal_create(journal, "goal", "en", spec=path)
        return folder, journal

    def init(self, journal, folder, *extra, graph=None, models=None):
        argv = ["run-init", journal, "--profile", "github-copilot", "--spec", os.path.join(folder, "a-spec.md"),
                "--spec", os.path.join(folder, "b-spec.md"), "--graph", json.dumps(graph or {}),
                "--models", json.dumps(models or {"audit": ct.BUILTIN_SETTINGS["github-copilot"]["roles"]["audit"]})]
        return self.run_main(*argv, *extra)


class RunInitTest(JournalCase):
    def test_writes_a_runner_section_that_validates(self):
        folder, journal = self.make_journal("a-spec.md", "b-spec.md")
        a, b = os.path.join(folder, "a-spec.md"), os.path.join(folder, "b-spec.md")
        code, out = self.init(journal, folder, graph={b: [a]})
        self.assertEqual(code, 0)
        self.assertEqual(out["runner"], {
            "version": 1, "profile": "github-copilot", "specs": ["a-spec.md", "b-spec.md"],
            "graph": {"b-spec.md": ["a-spec.md"]},
            "models": {"audit": {"model": "claude-opus-5.5", "effort": None, "fallback": "gpt-5-mini"}},
            "sessions": []})
        self.assertEqual(ct._brainstorm().journal_load(journal)["runner"], out["runner"])
        self.assertEqual(ct._brainstorm().journal_validate(journal), {"ok": True, "errors": []})

    def test_unknown_spec_and_cycle(self):
        folder, journal = self.make_journal("a-spec.md")
        code, out = self.init(journal, folder)
        self.assertEqual((code, out["errors"]), (2, ["unknown-spec: b-spec.md (not registered in the journal)"]))
        self.assertNotIn("runner", ct._brainstorm().journal_load(journal))
        folder, journal = self.make_journal("a-spec.md", "b-spec.md")
        a, b = os.path.join(folder, "a-spec.md"), os.path.join(folder, "b-spec.md")
        code, out = self.init(journal, folder, graph={a: [os.path.join(folder, "c-spec.md")]})
        self.assertEqual((code, out["errors"]), (2, ["unknown-spec: c-spec.md"]))
        code, out = self.init(journal, folder, graph={a: [b], b: [a]})
        self.assertEqual((code, out["cycle"][0], set(out["cycle"])), (1, out["cycle"][-1], {"a-spec.md", "b-spec.md"}))
        self.assertEqual(out["errors"], ["graph-cycle: " + " -> ".join(out["cycle"])])

    def test_reinit_keeps_sessions_and_start_commit(self):
        folder, journal = self.make_journal("a-spec.md", "b-spec.md")
        self.assertEqual(self.init(journal, folder, "--start-commit", "a1b2c3d", "--parallel", "2")[0], 0)
        session = {"id": "s1", "started_at": "2026-10-02T10:00:00Z", "ended_at": None, "end": None}
        ct._brainstorm().journal_update(journal, lambda data: data["runner"]["sessions"].append(session))
        code, out = self.init(journal, folder, "--profile", "fallback")
        self.assertEqual((code, out["runner"]["profile"]), (0, "fallback"))
        self.assertEqual((out["runner"]["sessions"], out["runner"]["start_commit"], out["runner"]["parallel"]),
                         ([session], "a1b2c3d", 2))
        self.assertEqual(self.init(journal, folder, "--start-commit", "HEAD")[1]["errors"],
                         ["start-commit-invalid: HEAD"])
        self.assertEqual(self.init(journal, folder, "--parallel", "0")[1]["errors"],
                         ["--parallel must be at least 1, got 0"])


class RunInitCliTest(JournalCase):
    def test_spec_paths_relative_to_cwd(self):
        folder, journal = self.make_journal("a-spec.md", "b-spec.md")
        code, out = self.run_cli("run-init", os.path.join("docs", "goal-chain.json"), "--profile", "claude-code",
                                 "--spec", "docs/a-spec.md", "--spec", "docs/b-spec.md",
                                 "--graph", '{"docs/b-spec.md": ["docs/a-spec.md"]}',
                                 "--models", json.dumps(ct.BUILTIN_SETTINGS["claude-code"]["roles"]), cwd=self.tmp)
        self.assertEqual(code, 0)
        self.assertEqual((out["runner"]["specs"], out["runner"]["graph"]),
                         (["a-spec.md", "b-spec.md"], {"b-spec.md": ["a-spec.md"]}))
        self.assertTrue(ct._brainstorm().journal_validate(journal)["ok"])

    def test_cli_exit_codes(self):
        folder, journal = self.make_journal("a-spec.md", "b-spec.md")
        base = ["run-init", journal, "--profile", "claude-code", "--spec", os.path.join(folder, "a-spec.md"),
                "--spec", os.path.join(folder, "b-spec.md"), "--models", "{}"]
        a, b = os.path.join(folder, "a-spec.md"), os.path.join(folder, "b-spec.md")
        code, out = self.run_cli(*base, "--graph", json.dumps({a: [b], b: [a]}))
        self.assertEqual((code, len(out["cycle"]), set(out["cycle"])), (1, 3, {"a-spec.md", "b-spec.md"}))
        self.assertEqual(self.run_cli(*base, "--graph", "[1]")[0], 2)
        self.assertEqual(self.run_cli(*base, "--graph", "{")[0], 2)
        code, out = self.run_cli("run-init", os.path.join(folder, "none-chain.json"), "--profile", "claude-code",
                                 "--spec", a, "--graph", "{}", "--models", "{}")
        self.assertEqual(code, 2)
        self.assertTrue(out["errors"][0].startswith("journal-missing: "))


class SessionFileTest(HomeCase):
    def test_mark_lives_in_home_by_sha1_of_the_journal(self):
        journal = os.path.join(self.tmp, "docs", "goal-chain.json")
        path = ct._session_file(journal)
        self.assertEqual(os.path.dirname(path), os.path.join(self.home, "sessions"))
        self.assertEqual(len(os.path.basename(path)), 40 + len(".json"))
        self.assertEqual(ct._session_file(os.path.join(self.tmp, "docs", ".", "goal-chain.json")), path)

    def test_write_read_and_age(self):
        path = ct._session_file(os.path.join(self.tmp, "goal-chain.json"))
        self.assertIsNone(ct._read_session(path))
        ct._write_session(path, {"id": "s1", "heartbeat_at": "1970-01-01T00:00:00Z"})
        mark = ct._read_session(path)
        with mock.patch.object(ct, "_now", return_value=1800.0):
            self.assertEqual(ct._session_age(mark), 1800)
        self.assertIsNone(ct._session_age({"heartbeat_at": "yesterday"}))
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{broken")
        self.assertIsNone(ct._read_session(path))


class SessionBeginTest(JournalCase):
    def setUp(self):
        super().setUp()
        self.folder, self.journal = self.make_journal("a-spec.md", "b-spec.md")

    def sessions(self):
        return ct._brainstorm().journal_load(self.journal)["runner"]["sessions"]

    def test_runner_missing(self):
        with self.assertRaises(ct.ChainError) as caught:
            ct.session_begin(self.journal)
        self.assertTrue(str(caught.exception).startswith("runner-missing: "))

    def test_begin_writes_mark_and_journal_entry(self):
        self.init(self.journal, self.folder)
        with mock.patch.object(ct, "_now", return_value=1_000_000.0):
            out = ct.session_begin(self.journal)
        mark = ct._read_session(out["session_file"])
        self.assertEqual(mark, {"id": out["id"], "host": "github-copilot", "journal": os.path.abspath(self.journal),
                                "heartbeat_at": "1970-01-12T13:46:40Z"})
        self.assertEqual(self.sessions(), [{"id": out["id"], "started_at": "1970-01-12T13:46:40Z",
                                            "ended_at": None, "end": None}])
        self.assertTrue(ct._brainstorm().journal_validate(self.journal)["ok"])
        self.assertIsNone(out["previous"])

    def test_fresh_mark_is_active_unless_takeover_stale_mark_is_abandoned(self):
        self.init(self.journal, self.folder)
        with mock.patch.object(ct, "_now", return_value=1_000_000.0):
            first = ct.session_begin(self.journal, host="laptop")
        with mock.patch.object(ct, "_now", return_value=1_000_000.0 + 1799):
            with self.assertRaises(ct.ChainError) as caught:
                ct.session_begin(self.journal)
            self.assertEqual(caught.exception.details, {"id": first["id"], "host": "laptop", "age_seconds": 1799})
            second = ct.session_begin(self.journal, takeover=True)
        with mock.patch.object(ct, "_now", return_value=1_000_000.0 + 1799 + 1800):
            third = ct.session_begin(self.journal)
        self.assertEqual(third["previous"], {"id": second["id"], "host": "github-copilot", "age_seconds": 1800})
        self.assertEqual([(s["id"], s["end"]) for s in self.sessions()],
                         [(first["id"], "interrupted"), (second["id"], "interrupted"), (third["id"], None)])

    def test_stale_mark_with_a_running_stage_is_not_taken_silently(self):
        self.init(self.journal, self.folder)
        with mock.patch.object(ct, "_now", return_value=1_000_000.0):
            first = ct.session_begin(self.journal)
        ct._brainstorm().journal_event(self.journal, "plan-resolver", os.path.join(self.folder, "a-impl.md"),
                                       "audit", "running")
        with open(self.journal, "rb") as fh:
            before = fh.read()
        with mock.patch.object(ct, "_now", return_value=1_000_000.0 + 1800):
            with self.assertRaises(ct.ChainError) as caught:
                ct.session_begin(self.journal)
            self.assertTrue(str(caught.exception).startswith("session-stale-running: "))
            self.assertEqual(caught.exception.details, {"plan": "a-impl", "stage": "audit", "age_seconds": 1800})
            with open(self.journal, "rb") as fh:
                self.assertEqual(fh.read(), before)
            self.assertEqual(ct._read_session(first["session_file"])["id"], first["id"])
            self.assertNotEqual(ct.session_begin(self.journal, takeover=True)["id"], first["id"])

    def test_a_mark_created_by_another_begin_wins(self):
        self.init(self.journal, self.folder)
        path = ct._session_file(self.journal)
        ct._write_session(path, {"id": "other", "host": "h", "journal": self.journal, "heartbeat_at": "x"})
        with mock.patch.object(ct, "_read_session", return_value=None), \
                mock.patch.object(ct._brainstorm(), "_remove_quiet", return_value=False):
            with self.assertRaises(ct.ChainError) as caught:
                ct.session_begin(self.journal)
        self.assertTrue(str(caught.exception).startswith("session-active: "))
        self.assertEqual((ct._read_session(path)["id"], self.sessions()), ("other", []))


class SessionCliTest(JournalCase):
    def test_begin_heartbeat_end(self):
        folder, journal = self.make_journal("a-spec.md", "b-spec.md")
        self.init(journal, folder)
        code, begun = self.run_main("run-session", journal, "--begin", "--host", "laptop")
        self.assertEqual(code, 0)
        with open(journal, "rb") as fh:
            before = fh.read()
        with mock.patch.object(ct, "_now", return_value=86400.0):
            code, beat = self.run_main("run-session", journal, "--heartbeat", "--id", begun["id"])
        self.assertEqual((code, beat), (0, {"ok": True, "id": begun["id"], "heartbeat_at": "1970-01-02T00:00:00Z"}))
        with open(journal, "rb") as fh:
            self.assertEqual(fh.read(), before)
        self.assertEqual(ct._read_session(begun["session_file"])["heartbeat_at"], "1970-01-02T00:00:00Z")
        code, ended = self.run_main("run-session", journal, "--end", "stopped", "--id", begun["id"])
        self.assertEqual((code, ended["end"], ended["recorded"]), (0, "stopped", True))
        self.assertFalse(os.path.exists(begun["session_file"]))
        entry = ct._brainstorm().journal_load(journal)["runner"]["sessions"][0]
        self.assertEqual((entry["id"], entry["end"]), (begun["id"], "stopped"))
        self.assertTrue(ct._brainstorm().journal_validate(journal)["ok"])

    def test_exit_codes(self):
        folder, journal = self.make_journal("a-spec.md", "b-spec.md")
        code, out = self.run_cli("run-session", journal, "--begin")
        self.assertEqual((code, out["errors"][0].startswith("runner-missing: ")), (1, True))
        code, out = self.run_cli("run-session", journal, "--heartbeat", "--id", "s1")
        self.assertEqual((code, out["errors"][0].startswith("session-taken-over: "), out["mark_id"]), (1, True, None))
        self.init(journal, folder)
        self.assertEqual(self.run_cli("run-session", journal, "--begin")[0], 0)
        code, out = self.run_cli("run-session", journal, "--begin")
        self.assertEqual((code, out["host"], out["age_seconds"] < 60), (1, "github-copilot", True))
        self.assertEqual(self.run_cli("run-session", journal, "--heartbeat", "--takeover", "--id", "s1")[0], 2)
        self.assertEqual(self.run_cli("run-session", journal, "--heartbeat")[0], 2)
        self.assertEqual(self.run_cli("run-session", journal, "--end", "paused", "--id", "s1")[0], 2)

    def test_a_taken_over_session_writes_nothing(self):
        folder, journal = self.make_journal("a-spec.md", "b-spec.md")
        self.init(journal, folder)
        old = self.run_main("run-session", journal, "--begin")[1]
        new = self.run_main("run-session", journal, "--begin", "--takeover")[1]
        mark = ct._read_session(new["session_file"])
        with open(journal, "rb") as fh:
            before = fh.read()
        for argv in (("--heartbeat",), ("--end", "stopped")):
            code, out = self.run_main("run-session", journal, *argv, "--id", old["id"])
            self.assertEqual((code, out["errors"][0].startswith("session-taken-over: "), out["mark_id"]),
                             (1, True, new["id"]))
        with open(journal, "rb") as fh:
            self.assertEqual(fh.read(), before)
        self.assertEqual(ct._read_session(new["session_file"]), mark)
        sessions = ct._brainstorm().journal_load(journal)["runner"]["sessions"]
        self.assertEqual([(s["id"], s["end"]) for s in sessions], [(old["id"], "interrupted"), (new["id"], None)])


class ModelPickJournalTest(JournalCase):
    def test_models_come_from_the_journal(self):
        folder, journal = self.make_journal("a-spec.md", "b-spec.md")
        self.init(journal, folder, models={"audit": {"model": "my-opus", "effort": "high", "fallback": "gpt-5-mini"}})
        os.makedirs(self.home, exist_ok=True)
        with open(os.path.join(self.home, "runner.json"), "w", encoding="utf-8") as fh:
            fh.write("{broken")  # an invalid settings file does not matter with --journal

        def pick(*argv):
            return self.run_main("model-pick", "--journal", journal, "--role", "audit", *argv)
        self.assertEqual(pick(), (0, {"ok": True, "model": "my-opus", "effort": "high", "fallback_used": False}))
        self.assertEqual(pick("--unsupported", "my-opus"),
                         (0, {"ok": True, "model": "gpt-5-mini", "effort": "high", "fallback_used": True}))
        code, out = pick("--unsupported", "my-opus", "--unsupported", "gpt-5-mini")
        self.assertEqual((code, out["errors"]), (1, ["no-model: audit"]))
        self.assertIsNone(self.run_main("model-pick", "--journal", journal, "--role", "commit")[1]["model"])

    def test_profile_or_journal(self):
        folder, journal = self.make_journal("a-spec.md", "b-spec.md")
        self.assertEqual(self.run_main("model-pick", "--role", "audit"),
                         (2, {"ok": False, "errors": ["--profile is required without --journal"]}))
        code, out = self.run_main("model-pick", "--journal", journal, "--role", "audit")
        self.assertEqual((code, out["errors"][0].startswith("runner-missing: ")), (1, True))
        self.init(journal, folder)
        code, out = self.run_main("model-pick", "--journal", journal, "--profile", "claude-code", "--role", "audit")
        self.assertEqual((code, out["model"]), (0, "claude-opus-5.5"))  # the journal's model, not the profile's
        self.assertEqual(self.run_main("model-pick", "--journal", journal, "--file", "x.json", "--role", "audit")[0], 2)


# run-next, run-eta, run-status: synthetic journals with a runner section in temp dirs.
T2_STAGES = ("writing", "revision", "split", "execution", "diffs", "audit", "commit")


def _t2_plan(spec, done=(), **statuses):
    """Plan entry of `spec`: stages in `done` are done a minute apart in stage order; the others take
    their status from `statuses` (pending by default)."""
    plan = spec[:-len("-spec.md")] + "-impl.md"
    stages = {}
    for minute, stage in enumerate(T2_STAGES):
        if stage in done:
            stages[stage] = {"status": "done", "started_at": f"2026-10-02T01:{minute:02d}:00Z",
                             "finished_at": f"2026-10-02T01:{minute:02d}:30Z"}
        else:
            stages[stage] = {"status": statuses.get(stage, "pending")}
    return {"id": plan[:-3], "spec": spec, "plan": plan, "stages": stages}


def _t2_question(qid, plan_id, stage, text, answer=None, at="2026-10-02T02:00:00Z"):
    return {"id": qid, "plan": plan_id, "stage": stage, "skill": "plan-chain-runner", "text": text,
            "options": [], "status": "answered" if answer else "open", "answer": answer,
            "asked_at": at, "answered_at": at if answer else None}


class _T2Case(HomeCase):
    def journal(self, specs, plans=(), questions=(), events=(), graph=None, chains=None, runner=True):
        for spec in specs:
            chain = (chains or {}).get(spec)
            with open(os.path.join(self.tmp, spec), "w", encoding="utf-8") as fh:
                fh.write((f"> Chain: {chain}\n\n" if chain else "") + "# Goal\n\nGoal text.\n")
        data = {"version": 1, "goal": "g", "lang": "en", "created_at": "2026-10-02T00:00:00Z",
                "specs": [{"path": spec, "sha256": "0" * 64} for spec in specs], "plans": list(plans),
                "questions": list(questions), "findings": [], "events": list(events),
                "limits": {"enabled": False, "time_minutes": None, "cost": None}}
        if runner:
            data["runner"] = {"version": 1, "profile": "claude-code", "specs": list(specs), "graph": graph or {},
                              "models": {}, "start_commit": "none", "sessions": []}
        path = os.path.join(self.tmp, "g-chain.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        return path


class RunnerJournalTest(_T2Case):
    def test_runner_section_required(self):
        with self.assertRaisesRegex(ct.ChainError, "^runner-missing: "):
            ct._runner_journal(self.journal(["a-spec.md"], runner=False))

    def test_missing_journal_is_input_error(self):
        with self.assertRaisesRegex(ct.InputError, "^journal-missing: "):
            ct._runner_journal(os.path.join(self.tmp, "none-chain.json"))

    def test_derived_plan_follows_plan_path(self):
        self.assertEqual(ct._derived_plan("docs/a-spec.md"), "docs/a-impl.md")
        self.assertEqual(ct._derived_plan("spec.md"), "impl.md")
        self.assertEqual(ct._derived_plan("notes.md"), "notes-impl.md")


class PlanStatesTest(_T2Case):
    def test_entry_or_pending_plan_with_chain_and_questions(self):
        a = _t2_plan("a-spec.md", done=("writing",))
        path = self.journal(["a-spec.md", "b-spec.md"], plans=[a], chains={"b-spec.md": "split=never"},
                            questions=[_t2_question("Q1", "a-impl", "revision", "why?"),
                                       _t2_question("Q2", "a-impl", "writing", "ok?", answer="yes")])
        data, runner = ct._runner_journal(path)
        first, second = ct._plan_states(path, data, runner)
        self.assertIs(first["entry"], data["plans"][0])
        self.assertEqual([q["id"] for q in first["questions"]], ["Q1", "Q2"])
        self.assertEqual(first["open"], ["Q1"])
        self.assertEqual(second["entry"]["plan"], "b-impl.md")
        self.assertEqual(second["entry"]["id"], "b-impl")
        self.assertEqual({record["status"] for record in second["entry"]["stages"].values()}, {"pending"})
        self.assertEqual(second["chain"]["split"], "never")
        self.assertEqual(first["chain"]["split"], "auto")

    def test_missing_spec_file_is_input_error(self):
        path = self.journal(["a-spec.md"])
        os.remove(os.path.join(self.tmp, "a-spec.md"))
        data, runner = ct._runner_journal(path)
        with self.assertRaises(ct.InputError):
            ct._plan_states(path, data, runner)

    def test_entry_without_spec_is_found_by_plan_id(self):
        b = dict(_t2_plan("b-spec.md", done=("writing",)), spec=None)
        path = self.journal(["a-spec.md", "b-spec.md"], plans=[b])
        data, runner = ct._runner_journal(path)
        first, second = ct._plan_states(path, data, runner)
        self.assertIs(second["entry"], data["plans"][0])
        self.assertEqual(second["entry"]["stages"]["writing"]["status"], "done")
        self.assertEqual((first["entry"]["id"], first["entry"]["spec"]), ("a-impl", "a-spec.md"))

    def test_chain_from_the_plan_header_when_the_plan_exists(self):
        path = self.journal(["a-spec.md"], plans=[_t2_plan("a-spec.md", done=("writing",))])
        with open(os.path.join(self.tmp, "a-impl.md"), "w", encoding="utf-8") as fh:
            fh.write("# Plan\n\n**Spec:** a-spec.md\n\n**Chain:** split=never; resolver=skip\n\n### Task 1: x\n")
        data, runner = ct._runner_journal(path)
        chain = ct._plan_states(path, data, runner)[0]["chain"]
        self.assertEqual((chain["split"], chain["resolver"]), ("never", "skip"))


def _t2_state(entry, questions=(), chain=None, root=None):
    return {"spec": entry["spec"], "entry": entry, "chain": chain or {"split": "auto", "resolver": "audit"},
            "questions": list(questions), "open": [q["id"] for q in questions if q["status"] == "open"],
            "root": root or ""}


class NextStageTest(unittest.TestCase):
    def test_rule7_order_and_skipped(self):
        self.assertEqual(ct._next_stage(_t2_state(_t2_plan("a-spec.md"))), ("writing", None))
        entry = _t2_plan("a-spec.md", done=("writing", "revision"), split="skipped", execution="failed")
        self.assertEqual(ct._next_stage(_t2_state(entry)), ("execution", None))
        self.assertIsNone(ct._next_stage(_t2_state(_t2_plan("a-spec.md", done=T2_STAGES))))

    def test_rule9_stale_stages_drift_and_recommit(self):
        with tempfile.TemporaryDirectory() as root:
            plan = os.path.join(root, "a-impl.md")
            with open(plan, "wb") as fh:
                fh.write(b"plan v2\n")
            entry = _t2_plan("a-spec.md", done=T2_STAGES)
            entry["stages"]["writing"]["finished_at"] = "2026-10-02T03:00:00Z"  # writing ran again
            entry["stages"]["revision"].update(input="a-impl.md", input_sha256="0" * 64)
            self.assertEqual(ct._next_stage(_t2_state(entry, root=root)), ("revision", "drift"))
            keep = _t2_question("Q1", "a-impl", "revision", "drift: revision input changed: a-impl.md",
                                answer="keep", at="2026-10-02T03:10:00Z")
            self.assertIsNone(ct._next_stage(_t2_state(entry, [keep], root=root)))  # keep: current
            entry["stages"]["revision"]["input_sha256"] = ct._brainstorm()._sha256(plan)
            self.assertIsNone(ct._next_stage(_t2_state(entry, root=root)))  # stale by time, same input
            del entry["stages"]["revision"]["input"]
            self.assertIsNone(ct._next_stage(_t2_state(entry, root=root)))  # no stored input: current
        entry = _t2_plan("a-spec.md", done=T2_STAGES)
        entry["stages"]["audit"]["finished_at"] = "2026-10-02T03:00:00Z"
        self.assertEqual(ct._next_stage(_t2_state(entry)), ("commit", "recommit"))
        entry = _t2_plan("a-spec.md", done=T2_STAGES)
        entry["stages"]["execution"]["finished_at"] = "2026-10-02T01:05:00Z"  # after diffs: diffs is not stale
        self.assertIsNone(ct._next_stage(_t2_state(entry)))

    def test_rule9_drift_rewrite_and_keep(self):
        entry = _t2_plan("a-spec.md", done=T2_STAGES)
        rewrite = _t2_question("Q1", "a-impl", "writing", "drift: writing input changed: a-spec.md", answer="rewrite")
        self.assertEqual(ct._next_stage(_t2_state(entry, [rewrite])), ("writing", "drift"))
        self.assertEqual(ct._next_stage(_t2_state(entry, [dict(rewrite, status="applied")])), ("writing", "drift"))
        keep = dict(rewrite, answer="keep")
        self.assertIsNone(ct._next_stage(_t2_state(entry, [keep])))
        entry["stages"]["writing"]["finished_at"] = "2026-10-02T03:00:00Z"  # rewritten after the answer
        self.assertIsNone(ct._next_stage(_t2_state(entry, [rewrite])))  # revision has no stored input: current

    def test_rule9_open_audit_fix(self):
        entry = _t2_plan("a-spec.md", done=T2_STAGES)
        fix = _t2_question("Q1", "a-impl", "audit", "open-audit: a-impl 2 issues", answer="fix")
        self.assertEqual(ct._next_stage(_t2_state(entry, [fix])), ("audit", "audit-open"))
        entry["stages"]["audit"]["finished_at"] = "2026-10-02T03:00:00Z"  # the fix ran
        self.assertEqual(ct._next_stage(_t2_state(entry, [fix])), ("commit", "recommit"))


class RunActionTest(unittest.TestCase):
    def test_skill_args_role_per_stage(self):
        state = _t2_state(_t2_plan("a-spec.md"))
        expected = {"writing": ("plan-writing", ["a-spec.md"], "writing"),
                    "revision": ("plan-iterative-revision", ["a-impl.md"], "revision"),
                    "split": ("plan-splitter", ["a-impl.md"], "split"),
                    "execution": ("plan-executor", ["a-impl.md"], "execution"),
                    "diffs": ("plan-executor", ["a-impl.md"], "execution"),
                    "audit": ("plan-resolver", ["a-impl.md"], "audit"),
                    "commit": ("plan-executor", ["a-impl.md", "commit"], "commit")}
        for stage, (skill, args, role) in expected.items():
            with self.subTest(stage=stage):
                action = ct._run_action(state, stage, None)
                self.assertEqual(action, {"kind": "run", "spec": "a-spec.md", "plan": "a-impl.md", "stage": stage,
                                          "skill": skill, "args": args, "role": role, "reason": None})

    def test_roadmap_auto_and_fix(self):
        entry = _t2_plan("a-spec.md", done=("writing", "revision", "split"))
        entry["stages"]["split"]["artifacts"] = {"roadmap": "a-impl-roadmap.md"}
        state = _t2_state(entry, chain={"split": "auto", "resolver": "auto"})
        self.assertEqual(ct._run_action(state, "execution", None)["args"], ["a-impl-roadmap.md"])
        self.assertEqual(ct._run_action(state, "diffs", None)["args"], ["a-impl-roadmap.md"])
        self.assertEqual(ct._run_action(state, "audit", None)["args"], ["a-impl.md", "auto"])
        fix = ct._run_action(state, "audit", "audit-open")
        self.assertEqual((fix["args"], fix["reason"]), (["a-impl.md", "fix"], "audit-open"))
        entry["stages"]["split"]["status"] = "skipped"
        self.assertEqual(ct._run_action(state, "execution", "drift")["args"], ["a-impl.md"])


def _t2_failed_events(plan_id, stage, count):
    return [{"at": f"2026-10-02T01:3{n}:00Z", "skill": "s", "plan": plan_id, "stage": stage, "kind": "stage-end",
             "data": {"from": "running", "to": "failed"}} for n in range(count)]


class StageStepTest(unittest.TestCase):
    def test_skips_by_chain(self):
        state = _t2_state(_t2_plan("a-spec.md"), chain={"split": "never", "resolver": "skip"})
        self.assertEqual(ct._stage_step({"events": []}, state, "split", None),
                         {"spec": "a-spec.md", "plan": "a-impl.md", "stage": "split", "kind": "skip",
                          "why": "split=never"})
        self.assertEqual(ct._stage_step({"events": []}, state, "audit", None)["why"], "resolver=skip")

    def test_rule8_stopped_without_open_questions_resumes(self):
        state = _t2_state(_t2_plan("a-spec.md", done=("writing",), revision="stopped"))
        step = ct._stage_step({"events": []}, state, "revision", None)
        self.assertEqual((step["kind"], step["skill"], step["args"]), ("run", "plan-iterative-revision", ["a-impl.md"]))

    def test_rule10_one_retry_then_question(self):
        entry = _t2_plan("a-spec.md", done=("writing",), revision="failed")
        entry["stages"]["revision"]["finished_at"] = "2026-10-02T01:31:00Z"
        state = _t2_state(entry)
        self.assertEqual(ct._stage_step({"events": _t2_failed_events("a-impl", "revision", 1)},
                                              state, "revision", None)["kind"], "run")
        data = {"events": _t2_failed_events("a-impl", "revision", 2)}
        ask = ct._stage_step(data, state, "revision", None)
        self.assertEqual((ask["kind"], ask["prefix"], ask["options"]),
                         ("ask", "stage-failed: revision", ["retry", "stop"]))
        retry = _t2_question("Q1", "a-impl", "revision", "stage-failed: revision twice", answer="retry")
        self.assertEqual(ct._stage_step(data, _t2_state(entry, [retry]), "revision", None)["kind"], "run")
        stop = dict(retry, answer="stop", status="applied")  # answered or applied: the same answer
        self.assertEqual(ct._stage_step(data, _t2_state(entry, [stop]), "revision", None),
                         {"spec": "a-spec.md", "plan": "a-impl.md", "stage": "revision", "kind": "wait",
                          "why": "stage-failed: stop"})

    def test_running_audit_started_by_a_fix_resumes_as_fix(self):
        entry = _t2_plan("a-spec.md", done=T2_STAGES[:5], audit="running")
        fix = _t2_question("Q1", "a-impl", "audit", "open-audit: a-impl 2 issues", answer="fix")
        start = {"at": "2026-10-02T02:10:00Z", "skill": "plan-resolver", "plan": "a-impl", "stage": "audit",
                 "kind": "stage-start", "data": {"from": "done", "to": "running", "reason": "audit-open"}}
        step = ct._stage_step({"events": [start]}, _t2_state(entry, [fix]), "audit", None)
        self.assertEqual((step["args"], step["reason"]), (["a-impl.md", "fix"], "audit-open"))
        plain = dict(start, data={"from": "pending", "to": "running"})
        self.assertEqual(ct._stage_step({"events": [plain]}, _t2_state(entry, [fix]), "audit", None)["args"],
                         ["a-impl.md"])

    def test_not_confirmed_stop_waits_until_the_stage_moves(self):
        entry = _t2_plan("a-spec.md", done=("writing",))
        stop = _t2_question("Q1", "a-impl", "revision", "not-confirmed: revision no completion", answer="stop")
        self.assertEqual(ct._stage_step({"events": []}, _t2_state(entry, [stop]), "revision", None)["why"],
                         "not-confirmed: stop")
        model = _t2_question("Q2", "a-impl", "revision", "model: revision fable refused", answer="stop")
        self.assertEqual(ct._stage_step({"events": []}, _t2_state(entry, [model]), "revision", None)["why"],
                         "model: stop")
        retry = dict(model, answer="retry opus")  # answered, not applied yet: the runner's run-init comes first
        self.assertEqual(ct._stage_step({"events": []}, _t2_state(entry, [retry]), "revision", None)["why"],
                         "model: retry")
        self.assertEqual(ct._stage_step({"events": []}, _t2_state(entry, [dict(retry, status="applied")]),
                                        "revision", None)["kind"], "run")
        entry["stages"]["revision"].update(status="running", started_at="2026-10-02T03:00:00Z")
        self.assertEqual(ct._stage_step({"events": []}, _t2_state(entry, [stop]), "revision", None)["kind"],
                         "run")


class DependencyWaitTest(_T2Case):
    def wait(self, a, questions=()):
        path = self.journal(["a-spec.md", "b-spec.md"], plans=[a], questions=questions,
                            graph={"b-spec.md": ["a-spec.md"]})
        data, runner = ct._runner_journal(path)
        states = ct._plan_states(path, data, runner)
        for state in states:
            state["next"] = ct._next_stage(state)
        asks = {}
        why = ct._dependency_wait(runner, {s["spec"]: s for s in states}, states[1], asks)
        return why, asks

    def done_with_audit(self, status):
        a = _t2_plan("a-spec.md", done=T2_STAGES)
        a["stages"]["audit"]["artifacts"] = {"report": "a-impl-report-1.md", "status": status}
        return a

    def test_rule1_waits_for_commit(self):
        a = _t2_plan("a-spec.md", done=T2_STAGES[:-1])
        self.assertEqual(self.wait(a), ("depends-on: a-spec.md", {}))
        a["stages"]["commit"]["status"] = "skipped"
        self.assertEqual(self.wait(a), (None, {}))

    def test_rule1_open_audit_asks_then_accept_frees(self):
        why, asks = self.wait(self.done_with_audit("open"))
        self.assertEqual(why, "open-audit: a-impl")
        self.assertEqual(asks, {"a-spec.md": {"kind": "ask", "spec": "a-spec.md", "plan": "a-impl.md", "stage": "audit",
                                              "prefix": "open-audit: a-impl", "options": ["accept", "fix"]}})
        accept = _t2_question("Q1", "a-impl", "audit", "open-audit: a-impl 2 issues", answer="accept")
        self.assertEqual(self.wait(self.done_with_audit("open"), [accept]), (None, {}))
        applied = dict(accept, status="applied")  # the owner marked it applied: still an accept
        self.assertEqual(self.wait(self.done_with_audit("open"), [applied]), (None, {}))
        self.assertEqual(self.wait(self.done_with_audit("final")), (None, {}))

    def test_rule1_fix_waits_for_the_fix_and_recommit(self):
        fix = _t2_question("Q1", "a-impl", "audit", "open-audit: a-impl 2 issues", answer="fix")
        self.assertEqual(self.wait(self.done_with_audit("open"), [fix]), ("depends-on: a-spec.md", {}))

    def test_rule4_open_question_of_a_dependency_holds(self):
        question = _t2_question("Q1", "a-impl", "commit", "anything")
        self.assertEqual(self.wait(self.done_with_audit("final"), [question]), ("held-by: a-impl", {}))


class CandidatesTest(_T2Case):
    def candidates(self, plans, questions=(), specs=("a-spec.md", "b-spec.md", "c-spec.md")):
        path = self.journal(list(specs), plans=plans, questions=questions)
        data, runner = ct._runner_journal(path)
        states = ct._plan_states(path, data, runner)
        for state in states:
            state["next"] = ct._next_stage(state)
        waiting, asks = [], {}
        steps = ct._candidates(data, runner, states, waiting, asks)
        return [(s["plan"], s["stage"], s["running"]) for s in steps], [(w["plan"], w["reason"]) for w in waiting]

    def test_rule2_one_plan_in_code_stages(self):
        a = _t2_plan("a-spec.md", done=("writing", "revision", "split"), execution="running")
        b = _t2_plan("b-spec.md", done=("writing", "revision", "split"))
        steps, waiting = self.candidates([a, b])
        self.assertEqual(steps, [("a-impl.md", "execution", True), ("c-impl.md", "writing", False)])
        self.assertEqual(waiting, [("b-impl.md", "code-busy: a-impl")])

    def test_rule2_first_plan_takes_free_code_stages(self):
        a = _t2_plan("a-spec.md", done=("writing", "revision", "split"))
        b = _t2_plan("b-spec.md", done=("writing", "revision", "split"))
        steps, waiting = self.candidates([a, b], specs=("a-spec.md", "b-spec.md"))
        self.assertEqual(steps, [("a-impl.md", "execution", False)])
        self.assertEqual(waiting, [("b-impl.md", "code-busy: a-impl")])

    def test_rule4_open_question_holds_its_plan_only(self):
        a = _t2_plan("a-spec.md", done=("writing", "revision", "split"), execution="stopped")
        b = _t2_plan("b-spec.md", done=("writing", "revision", "split"))
        question = _t2_question("Q1", "a-impl", "execution", "write to prod?")
        steps, waiting = self.candidates([a, b], [question])
        self.assertEqual(steps, [("c-impl.md", "writing", False)])
        self.assertEqual(waiting, [("a-impl.md", "open-question: Q1"), ("b-impl.md", "code-busy: a-impl")])

    def test_rule4_open_question_on_done_stage_holds(self):
        a = _t2_plan("a-spec.md", done=("writing",))
        question = _t2_question("Q1", "a-impl", "writing", "drift: writing input changed: a-spec.md")
        steps, waiting = self.candidates([a], [question], specs=("a-spec.md",))
        self.assertEqual((steps, waiting), ([], [("a-impl.md", "open-question: Q1")]))

    def test_in_flight_plan_gets_no_step_and_holds_the_code_stages(self):
        path = self.journal(["a-spec.md", "b-spec.md"],
                            plans=[_t2_plan("a-spec.md", done=("writing", "revision", "split")),
                                   _t2_plan("b-spec.md", done=("writing", "revision", "split"))])
        data, runner = ct._runner_journal(path)
        states = ct._plan_states(path, data, runner)
        for state in states:
            state["next"] = ct._next_stage(state)
        waiting = []
        steps = ct._candidates(data, runner, states[::-1], waiting, {}, {"a-impl": "execution"})
        self.assertEqual((steps, [(w["plan"], w["reason"]) for w in waiting]),
                         ([], [("b-impl.md", "code-busy: a-impl"), ("a-impl.md", "in-flight: execution")]))

    def test_rule9_cascade_drift_questions_become_answers(self):
        a = _t2_plan("a-spec.md", done=("writing", "revision"))
        a["stages"]["writing"]["finished_at"] = "2026-10-02T03:00:00Z"  # rewritten after Q1
        questions = [_t2_question("Q1", "a-impl", "writing", "drift: writing input changed: a-spec.md", answer="rewrite"),
                     _t2_question("Q2", "a-impl", "revision", "drift: revision input changed: a-impl.md",
                                  at="2026-10-02T03:01:00Z")]
        steps, waiting = self.candidates([a], questions, specs=("a-spec.md",))
        self.assertEqual((steps, waiting), ([("a-impl.md", "revision", False), ("a-impl.md", "split", False)], []))
        early = dict(questions[0], answered_at="2026-10-02T01:00:00Z")  # answered before revision finished
        steps, waiting = self.candidates([a], [early, questions[1]], specs=("a-spec.md",))
        self.assertEqual((steps, waiting), ([], [("a-impl.md", "open-question: Q2")]))


class RunNextTest(_T2Case):
    SPECS = ["a-spec.md", "b-spec.md", "c-spec.md"]

    def run_next(self, plans=(), questions=(), parallel=3, specs=None, change=None):
        path = self.journal(specs or self.SPECS, plans=plans, questions=questions)
        if change is not None:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            change(data)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh)
        result = ct.run_next(path, parallel)
        result["pairs"] = [(a["kind"], a["plan"], a["stage"]) for a in result["actions"]]
        result["waits"] = [(w["plan"], w["reason"]) for w in result["waiting"]]
        return result

    def test_rule3_new_audit_starts_alone(self):
        a = _t2_plan("a-spec.md", done=T2_STAGES[:5])
        result = self.run_next([a])
        self.assertEqual(result["pairs"], [("run", "a-impl.md", "audit")])
        self.assertEqual(result["waits"], [("b-impl.md", "audit-alone"), ("c-impl.md", "audit-alone")])

    def test_rule3_running_audit_alone_and_audit_waits_for_running_stage(self):
        a = _t2_plan("a-spec.md", done=T2_STAGES[:5], audit="running")
        b = _t2_plan("b-spec.md", revision="running", done=("writing",))
        self.assertEqual(self.run_next([a, b])["pairs"], [("run", "a-impl.md", "audit")])
        a["stages"]["audit"]["status"] = "pending"
        result = self.run_next([a, b])
        self.assertEqual(result["pairs"], [("run", "b-impl.md", "revision"), ("run", "c-impl.md", "writing")])
        self.assertEqual(result["waits"], [("a-impl.md", "audit-waits")])

    def test_rule5_parallel_width_running_first(self):
        c = _t2_plan("c-spec.md", writing="running")
        result = self.run_next([c], parallel=2)
        self.assertEqual(result["pairs"], [("run", "c-impl.md", "writing"), ("run", "a-impl.md", "writing")])
        self.assertEqual(result["waits"], [("b-impl.md", "parallel-limit")])
        self.assertIsNone(result["actions"][0]["reason"])  # an interrupted stage resumes with its owner
        self.assertNotIn("running", result["actions"][0])

    def test_rule6_limits_are_not_checked(self):
        def limits(data):
            data["limits"] = {"enabled": False, "time_minutes": 0, "cost": 0}
        self.assertEqual(len(self.run_next(change=limits)["actions"]), 3)

    def test_rule11_done_and_blocked(self):
        done = [_t2_plan(spec, done=T2_STAGES) for spec in self.SPECS]
        result = self.run_next(done)
        self.assertEqual((result["actions"], result["done"], result["blocked"]), ([], True, False))
        question = _t2_question("Q1", "a-impl", "writing", "which?")
        held = [_t2_plan("a-spec.md", writing="stopped")]
        result = self.run_next(held, [question], specs=["a-spec.md"])
        self.assertEqual((result["actions"], result["done"], result["blocked"]), ([], False, True))

    def test_parallel_from_the_runner_section_wins_over_the_settings_file(self):
        os.makedirs(self.home, exist_ok=True)
        with open(os.path.join(self.home, "runner.json"), "w", encoding="utf-8") as fh:
            json.dump({"profiles": {"claude-code": {"parallel": 3}}}, fh)

        def one(data):
            data["runner"]["parallel"] = 1
        self.assertEqual(len(self.run_next(parallel=None)["actions"]), 3)
        self.assertEqual(len(self.run_next(change=one, parallel=None)["actions"]), 1)
        self.assertEqual(len(self.run_next(change=one, parallel=2)["actions"]), 2)

    def test_in_flight_agents_count_and_are_not_returned(self):
        path = self.journal(self.SPECS, plans=[_t2_plan("a-spec.md", writing="running")])
        result = ct.run_next(path, 2, ["a-impl:writing"])
        self.assertEqual([(a["plan"], a["stage"]) for a in result["actions"]], [("b-impl.md", "writing")])
        self.assertEqual([(w["plan"], w["reason"]) for w in result["waiting"]],
                         [("a-impl.md", "in-flight: writing"), ("c-impl.md", "parallel-limit")])
        self.assertEqual(ct.run_next(path, 3, ["a-impl:writing", "b-impl:writing", "c-impl:writing"])
                         ["blocked"], False)
        audit = _t2_plan("a-spec.md", done=T2_STAGES[:5])
        path = self.journal(self.SPECS, plans=[audit])
        result = ct.run_next(path, 3, ["b-impl:writing"])
        self.assertEqual([(w["plan"], w["reason"]) for w in result["waiting"]][-1], ("a-impl.md", "audit-waits"))
        result = ct.run_next(path, 3, ["a-impl:audit"])
        self.assertEqual((result["actions"], {w["reason"] for w in result["waiting"]}),
                         ([], {"in-flight: audit", "audit-alone"}))
        with self.assertRaisesRegex(ct.InputError, "--in-flight: expected"):
            ct.run_next(path, 3, ["a-impl"])

    def test_parallel_default_from_profile_and_minimum(self):
        def fallback(data):
            data["runner"]["profile"] = "fallback"
        path = self.journal(self.SPECS)
        self.assertEqual(len(ct.run_next(path)["actions"]), 3)
        self.assertEqual(len(self.run_next(change=fallback, parallel=None)["actions"]), 1)
        with self.assertRaisesRegex(ct.InputError, "--parallel must be at least 1"):
            ct.run_next(path, 0)


class RunNextScenarioTest(_T2Case):
    def test_stopped_a_leaves_b_moving_and_holds_dependent_c(self):
        path = self.journal(["a-spec.md", "b-spec.md", "c-spec.md"],
                            plans=[_t2_plan("a-spec.md", done=("writing",), revision="stopped")],
                            questions=[_t2_question("Q1", "a-impl", "revision", "keep the limit?")],
                            graph={"c-spec.md": ["a-spec.md"]})
        result = ct.run_next(path, 3)
        self.assertEqual([(a["plan"], a["stage"]) for a in result["actions"]], [("b-impl.md", "writing")])
        self.assertEqual([(w["plan"], w["reason"]) for w in result["waiting"]],
                         [("a-impl.md", "open-question: Q1"), ("c-impl.md", "held-by: a-impl")])
        self.assertEqual((result["done"], result["blocked"]), (False, False))

    def test_open_audit_ask_then_accept_frees_dependent(self):
        a = _t2_plan("a-spec.md", done=T2_STAGES)
        a["stages"]["audit"]["artifacts"] = {"status": "open"}
        graph = {"b-spec.md": ["a-spec.md"]}
        path = self.journal(["a-spec.md", "b-spec.md"], plans=[a], graph=graph)
        result = ct.run_next(path, 3)
        self.assertEqual(result["actions"], [{"kind": "ask", "spec": "a-spec.md", "plan": "a-impl.md", "stage": "audit",
                                              "prefix": "open-audit: a-impl", "options": ["accept", "fix"]}])
        accept = _t2_question("Q1", "a-impl", "audit", "open-audit: a-impl 1 issue", answer="accept")
        path = self.journal(["a-spec.md", "b-spec.md"], plans=[a], questions=[accept], graph=graph)
        self.assertEqual([(x["plan"], x["stage"]) for x in ct.run_next(path, 3)["actions"]],
                         [("b-impl.md", "writing")])

    def test_rule7_diffs_pending_after_execution_reruns_executor(self):
        path = self.journal(["a-spec.md"], plans=[_t2_plan("a-spec.md", done=T2_STAGES[:4], diffs="pending")])
        action = ct.run_next(path, 3)["actions"][0]
        self.assertEqual((action["stage"], action["skill"], action["role"]), ("diffs", "plan-executor", "execution"))

    def test_skip_actions(self):
        path = self.journal(["a-spec.md"], plans=[_t2_plan("a-spec.md", done=("writing", "revision"))],
                            chains={"a-spec.md": "split=never; resolver=skip"})
        self.assertEqual(ct.run_next(path, 3)["actions"],
                         [{"kind": "skip", "spec": "a-spec.md", "plan": "a-impl.md", "stage": "split",
                           "why": "split=never"}])

    def test_rule9_cascade_after_rewrite_reruns_without_asking(self):
        a = _t2_plan("a-spec.md", done=T2_STAGES)
        a["stages"]["writing"]["finished_at"] = "2026-10-02T03:00:00Z"  # writing rewritten after Q1
        for stage in ("revision", "execution", "audit"):
            a["stages"][stage].update(input="a-impl.md", input_sha256="0" * 64)
        questions = [_t2_question("Q1", "a-impl", "writing", "drift: writing input changed: a-spec.md", answer="rewrite")]
        questions += [_t2_question(qid, "a-impl", stage, f"drift: {stage} input changed: a-impl.md",
                                   at="2026-10-02T03:01:00Z")  # asked by journal-reconcile
                      for qid, stage in (("Q2", "revision"), ("Q3", "execution"), ("Q4", "audit"))]
        path = self.journal(["a-spec.md"], plans=[a], questions=questions)
        with open(os.path.join(self.tmp, "a-impl.md"), "wb") as fh:
            fh.write(b"rewritten plan\n")
        result = ct.run_next(path, 3)
        self.assertEqual([(x["kind"], x["stage"], x.get("reason") or x.get("qid")) for x in result["actions"]],
                         [("run", "revision", "drift"), ("answer", "revision", "Q2"),
                          ("answer", "execution", "Q3"), ("answer", "audit", "Q4")])
        self.assertEqual(result["actions"][1], {"kind": "answer", "spec": "a-spec.md", "plan": "a-impl.md",
                                                "stage": "revision", "qid": "Q2", "answer": "rewrite"})
        self.assertEqual((result["waiting"], result["blocked"]), ([], False))

    def test_cli_json_and_exit_codes(self):
        path = self.journal(["a-spec.md"])
        code, result = self.run_cli("run-next", path, "--parallel", "1")
        self.assertEqual((code, result["actions"][0]["args"]), (0, ["a-spec.md"]))
        self.assertEqual(result["journal_dir"], os.path.dirname(os.path.abspath(path)))
        code, result = self.run_cli("run-next", path, "--in-flight", "a-impl:writing")
        self.assertEqual((code, result["actions"], result["waiting"][0]["reason"]), (0, [], "in-flight: writing"))
        self.assertEqual(self.run_cli("run-next", path, "--in-flight", "a-impl")[0], 2)
        code, result = self.run_cli("run-next", self.journal(["a-spec.md"], runner=False))
        self.assertEqual((code, result["ok"], result["errors"][0].startswith("runner-missing: ")), (1, False, True))
        code, result = self.run_cli("run-next", os.path.join(self.tmp, "x-chain.json"))
        self.assertEqual((code, result["errors"][0].startswith("journal-missing: ")), (2, True))


def _t2_event(at, plan, stage, kind, **data):
    return {"at": f"2026-10-02T{at}Z", "skill": "s", "plan": plan, "stage": stage, "kind": kind, "data": data}


class RunEtaTest(_T2Case):
    def test_history_average_per_stage(self):
        events = [_t2_event("01:00:00", "old-impl", "revision", "stage-start"),
                  _t2_event("01:10:00", "old-impl", "revision", "stage-end", to="done"),
                  _t2_event("02:00:00", "old-impl", "revision", "stage-start"),
                  _t2_event("02:20:00", "old-impl", "revision", "stage-end", to="stopped")]
        path = self.journal(["a-spec.md"], plans=[_t2_plan("a-spec.md", done=("writing",))], events=events)
        result = ct.run_eta(path)
        self.assertEqual((result["eta_minutes"], result["basis"]), (15, "history"))
        self.assertEqual(result["remaining"][0], {"plan": "a-impl.md", "stage": "revision"})
        self.assertEqual(len(result["remaining"]), 6)

    def test_units_only(self):
        a = _t2_plan("a-spec.md", done=("writing", "revision", "split"), execution="running")
        a["stages"]["execution"]["artifacts"] = {"units_done": "2", "units_total": "5"}
        events = [_t2_event("01:00:00", "a-impl", "execution", "unit-begin", unit="U1"),
                  _t2_event("01:01:00", "a-impl", "execution", "unit-finish", unit="U1"),
                  _t2_event("01:01:00", "a-impl", "execution", "unit-begin", unit="U2"),
                  _t2_event("01:02:30", "a-impl", "execution", "unit-finish", unit="U2")]
        result = ct.run_eta(self.journal(["a-spec.md"], plans=[a], events=events))
        self.assertEqual((result["eta_minutes"], result["basis"]), (4, "units"))

    def test_no_data(self):
        result = ct.run_eta(self.journal(["a-spec.md"]))
        self.assertEqual((result["eta_minutes"], result["basis"]), (None, "none"))
        self.assertEqual([item["stage"] for item in result["remaining"]], list(T2_STAGES))


class RunStatusTest(_T2Case):
    def mark(self, path, heartbeat_at):
        mark = ct._session_file(path)
        os.makedirs(os.path.dirname(mark), exist_ok=True)
        with open(mark, "w", encoding="utf-8") as fh:
            json.dump({"id": "s1", "host": "h", "journal": path, "heartbeat_at": heartbeat_at}, fh)

    def test_plans_questions_and_progress(self):
        a = _t2_plan("a-spec.md", done=("writing", "revision", "split"), execution="running")
        a["stages"]["execution"]["artifacts"] = {"units_done": "3", "units_total": "8"}
        question = _t2_question("Q1", "a-impl", "execution", "write to prod?")
        path = self.journal(["a-spec.md", "b-spec.md"], plans=[a], questions=[question])
        result = ct.run_status(path)
        self.assertEqual((result["goal"], result["profile"], result["session"]), ("g", "claude-code", None))
        first, second = result["plans"]
        self.assertEqual((first["plan"], first["current"], first["progress"]), ("a-impl.md", "execution",
                                                                               {"done": 3, "total": 8}))
        self.assertEqual(first["stages"]["revision"], "done")
        self.assertEqual((second["spec"], second["plan"], second["current"], second["progress"]),
                         ("b-spec.md", "b-impl.md", "writing", None))
        self.assertEqual(result["open_questions"], [{"id": "Q1", "plan": "a-impl", "stage": "execution",
                                                     "text": "write to prod?", "options": []}])
        self.assertIsNone(result["eta_minutes"])

    def test_waits_without_questions(self):
        a = _t2_plan("a-spec.md", done=("writing", "revision", "split"), execution="failed")
        b = _t2_plan("b-spec.md", done=("writing", "revision", "split"))
        stop = _t2_question("Q1", "a-impl", "execution", "stage-failed: execution twice", answer="stop")
        path = self.journal(["a-spec.md", "b-spec.md"], plans=[a, b], questions=[stop])
        result = ct.run_status(path)
        self.assertEqual(result["open_questions"], [])
        self.assertEqual([(w["plan"], w["stage"], w["reason"]) for w in result["waits"]],
                         [("a-impl.md", "execution", "stage-failed: stop"),
                          ("b-impl.md", "execution", "code-busy: a-impl")])

    def test_session_mark_active_and_stale(self):
        path = self.journal(["a-spec.md"])
        self.mark(path, "2026-10-02T01:00:00Z")
        with mock.patch.object(ct, "_now", return_value=ct._parse_iso("2026-10-02T01:10:00Z")):
            self.assertEqual(ct.run_status(path)["session"], {"active": True, "age_seconds": 600})
        with mock.patch.object(ct, "_now", return_value=ct._parse_iso("2026-10-02T01:40:00Z")):
            self.assertEqual(ct.run_status(path)["session"], {"active": False, "age_seconds": 2400})


class RunEtaStatusCliTest(_T2Case):
    def test_cli(self):
        path = self.journal(["a-spec.md"])
        code, result = self.run_cli("run-eta", path)
        self.assertEqual((code, result["basis"]), (0, "none"))
        code, result = self.run_cli("run-status", path)
        self.assertEqual((code, result["plans"][0]["current"]), (0, "writing"))
        bare = self.journal(["a-spec.md"], runner=False)  # the same file, now without a runner section
        for command in ("run-eta", "run-status"):
            with self.subTest(command=command):
                code, result = self.run_cli(command, bare)
                self.assertEqual((code, result["ok"]), (1, False))
                self.assertTrue(result["errors"][0].startswith("runner-missing: "))


# Post-execution gate fixes (b1-b4: sessions and model-pick; c1-c4: scheduler and journal errors).
_REAL_OPEN = open


def _locked_open(path, times):
    """builtins.open that raises PermissionError for `path` the first `times` calls (Windows: a reader
    meets the moment os.replace swaps the file); `calls` counts them."""
    calls = []

    def fake(file, *args, **kwargs):
        if os.path.abspath(str(file)) == os.path.abspath(path) and len(calls) < times:
            calls.append(file)
            raise PermissionError(13, "The process cannot access the file", str(file))
        return _REAL_OPEN(file, *args, **kwargs)
    return fake, calls


class SessionMarkReadTest(JournalCase):
    def test_transient_permission_error_is_retried(self):
        path = ct._session_file(os.path.join(self.tmp, "goal-chain.json"))
        ct._write_session(path, {"id": "s1", "heartbeat_at": "1970-01-01T00:00:00Z"})
        fake, calls = _locked_open(path, 3)
        with mock.patch("builtins.open", side_effect=fake):
            self.assertEqual(ct._read_session(path)["id"], "s1")
        self.assertEqual(len(calls), 3)

    def test_lasting_permission_error_is_not_an_absent_mark(self):
        path = ct._session_file(os.path.join(self.tmp, "goal-chain.json"))
        ct._write_session(path, {"id": "s1", "heartbeat_at": "1970-01-01T00:00:00Z"})
        fake, _ = _locked_open(path, 10 ** 6)
        with mock.patch("builtins.open", side_effect=fake):
            with self.assertRaisesRegex(ct.InputError, "^cannot read "):
                ct._read_session(path)

    def test_begin_does_not_take_a_live_mark_over_on_a_transient_error(self):
        folder, journal = self.make_journal("a-spec.md", "b-spec.md")
        self.init(journal, folder)
        first = ct.session_begin(journal)
        fake, calls = _locked_open(first["session_file"], 2)
        with mock.patch("builtins.open", side_effect=fake):
            with self.assertRaisesRegex(ct.ChainError, "^session-active: "):
                ct.session_begin(journal)
        self.assertEqual((len(calls), ct._read_session(first["session_file"])["id"]), (2, first["id"]))

    def test_heartbeat_survives_a_transient_error(self):
        folder, journal = self.make_journal("a-spec.md", "b-spec.md")
        self.init(journal, folder)
        begun = ct.session_begin(journal)
        fake, _ = _locked_open(begun["session_file"], 2)
        with mock.patch("builtins.open", side_effect=fake):
            self.assertEqual(ct.session_heartbeat(journal, begun["id"])["id"], begun["id"])


class SessionRecheckTest(JournalCase):
    def setUp(self):
        super().setUp()
        self.folder, self.journal = self.make_journal("a-spec.md", "b-spec.md")
        self.init(self.journal, self.folder)
        self.begun = ct.session_begin(self.journal)
        self.ours = ct._read_session(self.begun["session_file"])
        self.other = dict(self.ours, id="other")

    def test_heartbeat_rechecks_the_id_before_writing(self):
        with mock.patch.object(ct, "_read_session", side_effect=[self.ours, self.other]), \
                mock.patch.object(ct, "_write_session") as write:
            with self.assertRaisesRegex(ct.ChainError, "^session-taken-over: "):
                ct.session_heartbeat(self.journal, self.begun["id"])
        write.assert_not_called()

    def test_end_removes_only_its_own_mark_and_writes_nothing_after_a_takeover(self):
        ct._write_session(self.begun["session_file"], self.other)  # another window took the run over
        with open(self.journal, "rb") as fh:
            before = fh.read()
        with mock.patch.object(ct, "_read_session", side_effect=[self.ours, self.other]):
            with self.assertRaisesRegex(ct.ChainError, "^session-taken-over: "):
                ct.session_end(self.journal, "stopped", self.begun["id"])
        with open(self.journal, "rb") as fh:
            self.assertEqual(fh.read(), before)
        self.assertEqual(ct._read_session(self.begun["session_file"])["id"], "other")

    def test_heartbeat_reports_a_takeover_that_came_with_its_write(self):
        with mock.patch.object(ct, "_read_session", side_effect=[self.ours, self.ours, self.other]), \
                mock.patch.object(ct, "_write_session") as write:
            with self.assertRaisesRegex(ct.ChainError, "^session-taken-over: "):
                ct.session_heartbeat(self.journal, self.begun["id"])
        self.assertEqual(write.call_count, 1)

    def test_end_reports_a_mark_it_could_not_remove(self):
        with mock.patch.object(ct._brainstorm(), "_remove_quiet", return_value=False):
            out = ct.session_end(self.journal, "stopped", self.begun["id"])
        self.assertEqual((out["recorded"], out["mark_removed"]), (True, False))

    def test_end_reports_the_removed_mark(self):
        out = ct.session_end(self.journal, "stopped", self.begun["id"])
        self.assertEqual((out["mark_removed"], os.path.exists(self.begun["session_file"])), (True, False))

    def test_begin_rollback_names_a_mark_it_could_not_remove(self):
        ct.session_end(self.journal, "stopped", self.begun["id"])
        bt = ct._brainstorm()
        with mock.patch.object(bt, "_atomic_write_text", side_effect=OSError("disk full")), \
                mock.patch.object(bt, "_remove_quiet", return_value=False):
            with self.assertRaisesRegex(bt.JournalError, "session mark not removed: "):
                ct.session_begin(self.journal)

    def test_begin_removes_its_mark_when_the_journal_write_fails(self):
        ct.session_end(self.journal, "stopped", self.begun["id"])
        with mock.patch.object(ct._brainstorm(), "_atomic_write_text", side_effect=OSError("disk full")):
            with self.assertRaises(ct._brainstorm().JournalError):
                ct.session_begin(self.journal)
        self.assertFalse(os.path.exists(self.begun["session_file"]))


class ModelPickJournalShapeTest(JournalCase):
    def test_malformed_runner_models_is_a_json_error(self):
        folder, journal = self.make_journal("a-spec.md", "b-spec.md")
        self.init(journal, folder)
        with open(journal, encoding="utf-8") as fh:
            data = json.load(fh)
        for models in ("opus", {"audit": "opus"}, ["audit"]):
            with self.subTest(models=models):
                data["runner"]["models"] = models
                with open(journal, "w", encoding="utf-8") as fh:
                    json.dump(data, fh)
                code, out = self.run_main("model-pick", "--journal", journal, "--role", "audit")
                self.assertEqual((code, out["ok"], out["errors"][0].startswith("journal-corrupt: ")), (2, False, True))


class GateSchedulerTest(_T2Case):
    def test_c1_commit_is_stale_after_a_later_execution(self):
        entry = _t2_plan("a-spec.md", done=T2_STAGES)
        entry["stages"]["execution"]["finished_at"] = "2026-10-02T03:00:00Z"  # re-executed, audit kept
        self.assertEqual(ct._next_stage(_t2_state(entry)), ("commit", "recommit"))

    def test_c2_a_rewound_plan_keeps_the_code_stages_until_commit(self):
        a = _t2_plan("a-spec.md", done=T2_STAGES[:6])  # executed and audited, not committed
        b = _t2_plan("b-spec.md", done=("writing", "revision", "split"))
        rewrite = _t2_question("Q1", "a-impl", "writing", "drift: writing input changed: a-spec.md", answer="rewrite")
        steps, waiting = CandidatesTest.candidates(self, [a, b], [rewrite], specs=("a-spec.md", "b-spec.md"))
        self.assertEqual((steps, waiting), ([("a-impl.md", "writing", False)], [("b-impl.md", "code-busy: a-impl")]))
        committed = _t2_plan("a-spec.md", done=T2_STAGES)  # committed: the rewind holds nothing
        rewrite = dict(rewrite, answered_at="2026-10-02T01:07:00Z")
        steps, waiting = CandidatesTest.candidates(self, [committed, b], [rewrite], specs=("a-spec.md", "b-spec.md"))
        self.assertEqual((steps, waiting), ([("a-impl.md", "writing", False), ("b-impl.md", "execution", False)], []))

    def test_m1_uncommitted_work_holds_before_runner_order(self):
        with open(os.path.join(self.tmp, "a-impl.md"), "w", encoding="utf-8") as fh:
            fh.write("# a, rewritten\n")
        a = _t2_plan("a-spec.md", done=T2_STAGES)  # committed, then split again after a drift
        a["stages"]["split"]["finished_at"] = "2026-10-02T03:00:00Z"
        a["stages"]["execution"].update(input="a-impl.md", input_sha256="0" * 64)
        b = _t2_plan("b-spec.md", done=T2_STAGES[:4])  # executed, not committed
        steps, waiting = CandidatesTest.candidates(self, [a, b], specs=("a-spec.md", "b-spec.md"))
        self.assertEqual((steps, waiting), ([("b-impl.md", "diffs", False)], [("a-impl.md", "code-busy: b-impl")]))

    def test_c3_malformed_journal_is_journal_corrupt_not_a_traceback(self):
        def stage_text(data):
            data["plans"][0]["stages"]["revision"] = "done"

        def finished_int(data):
            data["plans"][0]["stages"]["revision"]["finished_at"] = 5
        # stage-text fails the structure checks; finished-int passes them and breaks the scheduler's
        # time comparison (run-eta does not compare finished_at).
        for name, change, commands in (("stage-text", stage_text, ("run-next", "run-eta", "run-status")),
                                       ("finished-int", finished_int, ("run-next", "run-status"))):
            path = self.journal(["a-spec.md"], plans=[_t2_plan("a-spec.md", done=("writing", "revision"))])
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            change(data)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh)
            for command in commands:
                with self.subTest(name=name, command=command):
                    code, out = self.run_main(command, path)
                    self.assertEqual((code, out["ok"], out["errors"][0].startswith("journal-corrupt: ")),
                                     (2, False, True))

    def test_c4_an_answer_in_the_same_second_as_the_stage_end_is_used_once(self):
        entry = _t2_plan("a-spec.md", done=("writing",))
        rewrite = _t2_question("Q1", "a-impl", "writing", "drift: writing input changed: a-spec.md", answer="rewrite",
                               at=entry["stages"]["writing"]["finished_at"])  # rewritten within that second
        self.assertEqual(ct._next_stage(_t2_state(entry, [rewrite])), ("revision", None))
        entry = _t2_plan("a-spec.md", done=T2_STAGES[:6])
        fix = _t2_question("Q1", "a-impl", "audit", "open-audit: a-impl 2 issues", answer="fix",
                           at=entry["stages"]["audit"]["finished_at"])
        self.assertEqual(ct._next_stage(_t2_state(entry, [fix])), ("commit", None))


def _remove_dir_link(link):
    """A directory symlink or junction is removed as a link, never through its target."""
    if os.path.lexists(link):
        os.rmdir(link) if os.name == "nt" else os.unlink(link)


class SessionFileRealPathTest(HomeCase):
    def test_f9_a_journal_through_a_linked_folder_has_the_same_mark(self):
        real = os.path.join(self.tmp, "real")
        os.makedirs(real)
        with open(os.path.join(real, "goal-chain.json"), "w", encoding="utf-8") as fh:
            fh.write("{}\n")
        link = os.path.join(self.tmp, "link")
        try:
            os.symlink(real, link, target_is_directory=True)
        except (OSError, NotImplementedError):
            made = os.name == "nt" and subprocess.run(["cmd", "/c", "mklink", "/J", link, real],
                                                      capture_output=True).returncode == 0
            if not made:
                self.skipTest("cannot create a symlink or a junction here")
        self.addCleanup(_remove_dir_link, link)
        self.assertEqual(ct._session_file(os.path.join(link, "goal-chain.json")),
                         ct._session_file(os.path.join(real, "goal-chain.json")))


class SessionTakeoverRollbackTest(JournalCase):
    def setUp(self):
        super().setUp()
        self.folder, self.journal = self.make_journal("a-spec.md", "b-spec.md")
        self.init(self.journal, self.folder)
        self.begun = ct.session_begin(self.journal)  # the other window's live mark

    def read(self, path):
        with open(path, "rb") as fh:
            return fh.read()

    def test_f11_a_failed_takeover_puts_the_other_mark_back(self):
        mark, journal = self.read(self.begun["session_file"]), self.read(self.journal)
        bt = ct._brainstorm()
        with mock.patch.object(bt, "_atomic_write_text", side_effect=OSError("disk full")):
            with self.assertRaises(bt.JournalError) as caught:
                ct.session_begin(self.journal, takeover=True)
        self.assertNotIn("not restored", str(caught.exception))
        self.assertEqual((self.read(self.begun["session_file"]), self.read(self.journal)), (mark, journal))
        self.assertEqual(ct.session_heartbeat(self.journal, self.begun["id"])["id"], self.begun["id"])

    def test_f11_a_mark_that_cannot_be_put_back_is_named(self):
        bt = ct._brainstorm()
        with mock.patch.object(bt, "_atomic_write_text", side_effect=OSError("disk full")), \
                mock.patch.object(ct, "_restore_mark", return_value=False):
            with self.assertRaisesRegex(bt.JournalError, "; previous session mark not restored: "):
                ct.session_begin(self.journal, takeover=True)

    def test_f11_a_failed_claim_puts_the_other_mark_back(self):
        mark, journal = self.read(self.begun["session_file"]), self.read(self.journal)
        with mock.patch.object(ct, "_claim_mark", side_effect=OSError("disk full")):
            with self.assertRaises(ct._brainstorm().JournalError) as caught:
                ct.session_begin(self.journal, takeover=True)
        self.assertNotIn("not restored", str(caught.exception))
        self.assertEqual((self.read(self.begun["session_file"]), self.read(self.journal)), (mark, journal))

    def test_a_refused_open_does_not_remove_the_mark_of_the_concurrent_winner(self):
        path, real_open = self.begun["session_file"], os.open
        winner = b'{"id": "winner", "host": "x", "heartbeat_at": "2026-10-03T00:00:00Z"}\n'

        def refuse(target, flags, *args, **kwargs):
            if os.path.abspath(target) == os.path.abspath(path) and flags & os.O_EXCL:
                with open(path, "wb") as fh:  # the concurrent --begin created its mark first
                    fh.write(winner)
                raise PermissionError("held by another process")
            return real_open(target, flags, *args, **kwargs)

        with mock.patch.object(ct.os, "open", side_effect=refuse):
            with self.assertRaises(ct._brainstorm().JournalError):
                ct.session_begin(self.journal, takeover=True)
        self.assertEqual(self.read(path), winner)


class JournalTimeFieldsTest(_T2Case):
    def changed(self, change):
        path = self.journal(["a-spec.md"], plans=[_t2_plan("a-spec.md", done=("writing", "revision"))],
                            questions=[_t2_question("Q1", "a-impl", "split", "why?")])
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        change(data)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        return path

    def test_f12_a_time_that_is_not_a_journal_time_is_journal_corrupt_with_its_field(self):
        cases = (("plans[0].stages.revision.finished_at",
                  lambda data: data["plans"][0]["stages"]["revision"].update(finished_at=5)),
                 ("plans[0].stages.writing.started_at",
                  lambda data: data["plans"][0]["stages"]["writing"].update(started_at="yesterday")),
                 ("questions[0].asked_at",
                  lambda data: data["questions"][0].update(asked_at="2026-10-02 02:00")))
        for field, change in cases:
            path = self.changed(change)
            for command in ("run-next", "run-eta", "run-status"):
                with self.subTest(field=field, command=command):
                    code, out = self.run_main(command, path)
                    self.assertEqual((code, out["ok"]), (2, False))
                    self.assertTrue(out["errors"][0].startswith("journal-corrupt: "))
                    self.assertIn(field + ": not a journal time", out["errors"][0])

    def test_f12_journal_times_and_nulls_pass(self):
        path = self.changed(lambda data: data["plans"][0]["stages"]["split"].update(started_at=None))
        for command in ("run-next", "run-eta", "run-status"):
            with self.subTest(command=command):
                self.assertEqual(self.run_main(command, path)[0], 0)


class SchedulerBugTest(_T2Case):
    def test_f12_a_scheduler_error_on_a_sound_journal_is_scheduler_bug(self):
        path = self.journal(["a-spec.md"], plans=[_t2_plan("a-spec.md", done=("writing",))])
        for command, target, exc in (("run-next", "_candidates", KeyError("next")),
                                     ("run-status", "_candidates", AttributeError("'str' object has no attribute 'get'")),
                                     ("run-eta", "_eta", TypeError("unsupported operand")),):
            with self.subTest(command=command), mock.patch.object(ct, target, side_effect=exc):
                code, out = self.run_main(command, path)
                self.assertEqual((code, out), (1, {"ok": False, "errors": [f"scheduler-bug: {type(exc).__name__}: {exc}"]}))


class CascadeStrictTest(unittest.TestCase):
    def test_f13_the_cascade_takes_answers_strictly_after_the_stage_end(self):
        self.assertNotIn("at or after", ct._cascade.__doc__)
        self.assertIn("strictly after", ct._cascade.__doc__)
        entry = _t2_plan("a-spec.md", done=("writing", "revision"))
        later = _t2_question("Q2", "a-impl", "revision", "drift: revision input changed: a-impl.md")
        for answered, expected in ((entry["stages"]["revision"]["finished_at"], []), ("2026-10-02T01:01:31Z", ["Q2"])):
            rewrite = _t2_question("Q1", "a-impl", "writing", "drift: writing input changed: a-spec.md",
                                   answer="rewrite", at=answered)
            with self.subTest(answered=answered):
                self.assertEqual([q["id"] for q in ct._cascade(_t2_state(entry, [rewrite, later]))], expected)


PLAN_TOOL = Path(__file__).resolve().parents[2] / "plan-writing" / "scripts" / "plan_tool.py"


class PlanIdContractTest(HomeCase):
    def tool(self, script, *argv):
        proc = subprocess.run([sys.executable, str(script), *argv], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return json.loads(proc.stdout)

    def test_f10_the_runner_finds_the_plan_entry_plan_writing_registers(self):
        bt = ct._brainstorm()
        for name in ("a-spec.md", "Goal-Spec.md", "spec.md", "notes.md"):
            with self.subTest(spec=name):
                folder = os.path.join(self.tmp, name.replace(".", "_"))
                os.makedirs(folder)
                spec = os.path.join(folder, name)
                with open(spec, "w", encoding="utf-8") as fh:
                    fh.write("# Goal\n\nGoal text.\n")
                plan = self.tool(PLAN_TOOL, "plan-path", spec)["impl_path"]
                with open(plan, "w", encoding="utf-8") as fh:
                    fh.write(f"# Plan\n\n**Spec:** {name}\n\n### Task 1: x\n")
                journal = self.tool(BRAINSTORM, "journal-path", plan, "--create")["journal"]
                entries = [(p["id"], p["spec"]) for p in bt.journal_load(journal)["plans"]]
                self.assertEqual(entries, [(bt._journal_plan_id(ct._derived_plan(name)), name)])


class AskSpecTest(unittest.TestCase):
    def test_stage_failed_ask_names_the_spec_of_the_plan(self):
        entry = _t2_plan("a-spec.md", done=("writing",), revision="failed")
        entry["stages"]["revision"]["finished_at"] = "2026-10-02T01:31:00Z"
        ask = ct._stage_step({"events": _t2_failed_events("a-impl", "revision", 2)}, _t2_state(entry),
                             "revision", None)
        self.assertEqual((ask["kind"], ask["spec"], ask["plan"]), ("ask", "a-spec.md", "a-impl.md"))


class RunnerDocsTest(unittest.TestCase):
    REFS = Path(__file__).resolve().parents[1] / "references"

    def test_every_journal_question_of_the_runner_passes_the_spec(self):
        for name in ("LOOP.md", "START.md"):
            lines = [line for line in (self.REFS / name).read_text(encoding="utf-8").splitlines()
                     if "J journal-question" in line]
            self.assertTrue(lines, name)
            for line in lines:
                self.assertIn("--spec ", line, f"{name}: {line[:100]}")

    def test_profiles_and_start_say_an_alias_does_not_pin_the_version(self):
        for name in ("PROFILES.md", "START.md"):
            text = (self.REFS / name).read_text(encoding="utf-8")
            self.assertIn("does not pin the version", text, name)
            self.assertIn("pinned", text, name)
        self.assertIn("subagent_type: planforge-<role>", (self.REFS / "PROFILES.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
