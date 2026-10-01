#!/usr/bin/env python3
"""Black-box xagent regressions. Vendor CLIs are replaced, Git and processes are real."""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
XAGENT = Path(os.environ.get("XAGENT_UNDER_TEST", ROOT / "bin/xagent"))
STUB = r'''#!/usr/bin/env python3
import json, os, pathlib, signal, socket, subprocess, sys, time
agent = pathlib.Path(sys.argv[0]).name
case = os.environ.get('XAGENT_TEST_CASE', 'pass')
if agent == 'grok': os.chdir(sys.argv[sys.argv.index('--cwd')+1])
if agent == 'codex': os.chdir(sys.argv[sys.argv.index('-C')+1])
reply = 'Completed.\nSTATUS: PASS\n'
invalid_json = {'json_null': None, 'json_array': [], 'json_number': 42, 'json_null_changed': None}
def git(*args): subprocess.run(['git', *args], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
if case == 'nonfinal': reply = 'STATUS: PASS\nThe review is not completed.\n'
if case == 'quoted': reply = 'An example:\n> STATUS: PASS\n'
if case == 'fenced': reply = 'Example:\n```text\nSTATUS: PASS\n```\n'
if case == 'unclosed_fence': reply = 'Example:\n```text\nSTATUS: PASS\n'
if case == 'indented': reply = 'Example:\n\n    STATUS: PASS\n'
if case == 'tab': reply = 'Example:\n\n\tSTATUS: PASS\n'
if case == 'untracked': pathlib.Path('draft.txt').write_text('reader changed draft\n')
if case == 'json_null_changed': pathlib.Path('reader-change.txt').write_text('reader changed checkout\n')
if case == 'python_read': subprocess.run([sys.executable, '-c', 'import fixture_module'], check=True)
if case in ('staged', 'commit'):
    pathlib.Path('tracked.txt').write_text('reader changed tracked\n')
    git('add', 'tracked.txt')
    if case == 'commit': git('-c','user.name=fixture','-c','user.email=fixture@local','-c','commit.gpgsign=false','commit','-qm','reader changed')
if case == 'wait':
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    with socket.socket(socket.AF_UNIX) as s:
        s.connect(os.environ['XAGENT_TEST_SOCKET'])
        s.sendall(json.dumps({'pid':os.getpid()}).encode())
    time.sleep(30)
if agent == 'claude': print(json.dumps(invalid_json[case]) if case in invalid_json else json.dumps({'result':reply}))
elif agent == 'grok': print(json.dumps(invalid_json[case]) if case in invalid_json else json.dumps({'text':reply}))
elif agent == 'codex': pathlib.Path(sys.argv[sys.argv.index('-o')+1]).write_text(reply)
else: print(reply)
'''


class XAgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="xagent-test-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.work = self.base / "work"
        self.work.mkdir()
        self.binaries = self.base / "bin"
        self.binaries.mkdir()
        for name in ("claude", "codex", "grok", "agy", "pi"):
            executable = self.binaries / name
            executable.write_text(STUB)
            executable.chmod(0o755)
        self.brief = self.base / "brief.md"
        self.brief.write_text("Review this fixture without changing it.\n")
        (self.work / "tracked.txt").write_text("original\n")
        self.git("init", "-q")
        self.git("add", ".")
        self.git("-c", "user.name=fixture", "-c", "user.email=fixture@local", "-c", "commit.gpgsign=false", "commit", "-qm", "fixture")
        self.env = {**os.environ, "PATH": str(self.binaries) + os.pathsep + os.environ["PATH"]}
        self.env.pop("XAGENT_DEPTH", None)

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.work), *args], check=True, capture_output=True)

    def args(self, out, agent="grok", work=None, timeout="10"):
        return [str(XAGENT), agent, "ro", str(work or self.work), str(self.brief), str(out), timeout]

    def run_case(self, case, agent="grok", work=None, out=None):
        out = out or self.base / (case + "-" + agent)
        result = subprocess.run(self.args(out, agent, work), env={**self.env, "XAGENT_TEST_CASE": case}, capture_output=True, text=True, timeout=15)
        self.assertTrue((out / "meta.json").exists(), result.stderr)
        return result, json.loads((out / "meta.json").read_text())

    def test_given_each_adapter_when_it_finishes_then_a_final_verdict_is_collected(self):
        for agent in ("claude", "codex", "grok", "gemini", "pi"):
            with self.subTest(agent=agent):
                result, meta = self.run_case("pass", agent)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(meta["status"], "PASS")
                self.assertIs(meta["changed_workdir"], False)
                self.assertRegex(meta["snapshot_before"], r"^[a-f0-9]{64}$")
                self.assertEqual(meta["snapshot_before"], meta["snapshot_after"])

    def test_given_no_valid_terminal_verdict_then_result_is_dropout(self):
        for case in ("nonfinal", "quoted", "fenced", "unclosed_fence", "indented", "tab"):
            with self.subTest(case=case):
                result, meta = self.run_case(case)
                self.assertEqual(meta["status"], "DROPOUT")
                self.assertEqual(result.returncode, 3)

    def test_given_json_stdout_has_a_non_object_top_level_then_it_finishes_as_execution_dropout(self):
        for agent in ("claude", "grok"):
            for case in ("json_null", "json_array", "json_number"):
                with self.subTest(agent=agent, case=case):
                    result, meta = self.run_case(case, agent=agent)
                    self.assertEqual(result.returncode, 3, result.stderr)
                    self.assertEqual(meta["status"], "DROPOUT")
                    self.assertEqual(meta["reason"], "execution_error")
                    self.assertIs(meta["completed"], True)
                    self.assertRegex(meta["snapshot_after"], r"^[a-f0-9]{64}$")
                    self.assertEqual(meta["snapshot_before"], meta["snapshot_after"])

    def test_given_json_shape_error_and_readonly_change_then_dropout_keeps_final_snapshot(self):
        result, meta = self.run_case("json_null_changed", agent="grok")
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertEqual(meta["status"], "DROPOUT")
        self.assertEqual(meta["reason"], "execution_error")
        self.assertIs(meta["completed"], True)
        self.assertIs(meta["changed_workdir"], True)
        self.assertNotEqual(meta["snapshot_before"], meta["snapshot_after"])

    def test_given_a_reader_changes_untracked_content_then_it_cannot_pass(self):
        (self.work / "draft.txt").write_text("original draft\n")
        _, meta = self.run_case("untracked")
        self.assertIs(meta["changed_workdir"], True)
        self.assertNotEqual(meta["status"], "PASS")

    def test_given_existing_staged_content_when_reader_restages_then_change_is_detected(self):
        (self.work / "tracked.txt").write_text("staged before\n")
        self.git("add", "tracked.txt")
        _, meta = self.run_case("staged")
        self.assertIs(meta["changed_workdir"], True)
        self.assertNotEqual(meta["status"], "PASS")

    def test_given_clean_checkout_when_reader_commits_then_head_change_is_detected(self):
        _, meta = self.run_case("commit")
        self.assertIs(meta["changed_workdir"], True)
        self.assertNotEqual(meta["status"], "PASS")

    def test_given_no_git_snapshot_then_unchanged_is_never_claimed(self):
        work = self.base / "no-git"
        work.mkdir()
        _, meta = self.run_case("pass", work=work)
        self.assertIsNone(meta["changed_workdir"])
        self.assertEqual(meta["status"], "BLOCKED")

    def test_given_nested_output_then_runner_artifacts_are_excluded_from_snapshot(self):
        _, meta = self.run_case("pass", out=self.work / "evidence")
        self.assertIs(meta["changed_workdir"], False)

    def test_given_readonly_python_inspection_then_it_creates_no_bytecode_cache(self):
        (self.work / "fixture_module.py").write_text("VALUE = 1\n")
        _, meta = self.run_case("python_read")
        self.assertEqual(meta["status"], "PASS")
        self.assertIs(meta["changed_workdir"], False)
        self.assertFalse((self.work / "__pycache__").exists())

    def wait_case(self, cancel):
        out = self.base / "wait-out"
        with socket.socket(socket.AF_UNIX) as server:
            server.bind(str(self.base / "ready.sock"))
            server.listen(1)
            server.settimeout(5)
            env = {**self.env, "XAGENT_TEST_CASE": "wait", "XAGENT_TEST_SOCKET": str(self.base / "ready.sock")}
            process = subprocess.Popen(self.args(out, agent="pi", timeout="10" if cancel else "1"), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
            pid = None
            try:
                conn, _ = server.accept()
                with conn:
                    pid = json.loads(conn.recv(4096))["pid"]
                if cancel:
                    process.send_signal(signal.SIGTERM)
                stdout, stderr = process.communicate(timeout=5)
                self.assertEqual(process.returncode, 3, stdout + stderr)
                meta = json.loads((out / "meta.json").read_text())
                self.assertEqual(meta["status"], "DROPOUT")
                self.assertIs(meta["timed_out"], not cancel)
                if cancel:
                    self.assertIs(meta["cancelled"], True)
                state = subprocess.run(["ps", "-p", str(pid), "-o", "stat="], capture_output=True, text=True).stdout.strip()
                self.assertTrue(not state or state.startswith("Z"), state)
            finally:
                if pid is not None:
                    try: os.kill(pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                if process.poll() is None:
                    try: os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                process.communicate(timeout=5)

    def test_given_worker_ignores_term_when_deadline_expires_then_it_is_killed_and_recorded(self):
        self.wait_case(cancel=False)

    def test_given_worker_ignores_term_when_parent_is_cancelled_then_it_is_killed_and_recorded(self):
        self.wait_case(cancel=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
