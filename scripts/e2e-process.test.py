import json
import os
from pathlib import Path
import py_compile
import runpy
import signal
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
run_check = runpy.run_path(str(ROOT / "scripts/e2e-process.py"))["run_check"]


class BoundedVerificationTest(unittest.TestCase):
    def test_given_stale_bytecode_when_source_changes_in_same_second_then_current_source_is_checked(self):
        with tempfile.TemporaryDirectory(prefix="pstack-stale-bytecode-") as directory:
            source = Path(directory) / "stats.py"
            good = "def mean(xs):\n    return sum(xs) / len(xs)\n"
            bad = good.replace(" / ", " * ")
            for _ in range(5):
                source.write_text(good)
                py_compile.compile(str(source), doraise=True, invalidation_mode=py_compile.PycInvalidationMode.TIMESTAMP)
                before = source.stat()
                source.write_text(bad)
                after = source.stat()
                if int(before.st_mtime) == int(after.st_mtime):
                    break
            self.assertEqual(int(before.st_mtime), int(after.st_mtime))
            self.assertEqual(before.st_size, after.st_size)
            command = [sys.executable, "-B", "-c", "from stats import mean; assert mean([2,4,6]) == 4"]
            stale = subprocess.run(command, cwd=directory, capture_output=True, text=True, timeout=5)
            self.assertEqual(stale.returncode, 0, "-B alone still reads the old passing bytecode")
            current = {}
            exec(compile(source.read_text(), str(source), "exec"), current)
            self.assertEqual(current["mean"]([2, 4, 6]), 36)

            checked = run_check(command, directory, timeout=2)

            self.assertNotEqual(checked.returncode, 0, checked.stdout)
            self.assertIn("AssertionError", checked.stderr)

    def test_given_a_failing_check_when_run_then_output_and_exit_are_preserved(self):
        result = run_check(
            [sys.executable, "-c", "import sys; print('evidence'); print('failure', file=sys.stderr); sys.exit(7)"],
            ROOT, timeout=2,
        )
        self.assertEqual(result.returncode, 7)
        self.assertEqual(result.stdout, "evidence\n")
        self.assertEqual(result.stderr, "failure\n")

    def test_given_a_missing_executable_when_run_then_failure_is_returned(self):
        result = run_check(["/nonexistent/pstack-e2e-command"], ROOT, timeout=1)
        self.assertEqual(result.returncode, 127)
        self.assertIn("No such file", result.stderr)

    def assert_not_running(self, pid):
        state = subprocess.run(["ps", "-p", str(pid), "-o", "stat="], capture_output=True, text=True).stdout.strip()
        self.assertTrue(not state or state.startswith("Z"), f"process {pid} is still running: {state}")

    def test_given_term_ignoring_check_and_child_when_deadline_expires_then_group_is_stopped(self):
        program = '''import os, signal
signal.signal(signal.SIGTERM, signal.SIG_IGN)
reader, writer = os.pipe()
child = os.fork()
if child == 0:
    os.close(reader)
    os.write(writer, b"ready")
    os.close(writer)
    signal.pause()
else:
    os.close(writer)
    os.read(reader, 5)
    os.close(reader)
    print(f"ready {os.getpid()} {child}", flush=True)
    signal.pause()
'''
        started = time.monotonic()
        result = run_check([sys.executable, "-c", program], ROOT, timeout=0.5)
        self.assertEqual(result.returncode, 124, result.stderr)
        self.assertIn("timed out", result.stderr)
        self.assertLess(time.monotonic() - started, 5)
        marker, leader, child = result.stdout.split()
        self.assertEqual(marker, "ready")
        self.assert_not_running(int(leader))
        self.assert_not_running(int(child))

    def test_given_successful_leader_with_background_child_then_no_child_is_left_running(self):
        program = '''import os, signal
reader, writer = os.pipe()
child = os.fork()
if child == 0:
    os.close(reader)
    null = os.open(os.devnull, os.O_WRONLY)
    os.dup2(null, 1)
    os.dup2(null, 2)
    os.write(writer, b"ready")
    os.close(writer)
    signal.pause()
else:
    os.close(writer)
    os.read(reader, 5)
    os.close(reader)
    print(child, flush=True)
'''
        result = run_check([sys.executable, "-c", program], ROOT, timeout=2)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_not_running(int(result.stdout))

    def test_given_cli_invocation_then_cwd_output_and_failure_reach_the_caller(self):
        with tempfile.TemporaryDirectory(prefix="pstack-check-cli-") as directory:
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts/e2e-process.py"), "--timeout", "2", "--cwd", directory,
                 "--", sys.executable, "-c", "import os,sys; print(os.getcwd()); sys.exit(6)"],
                capture_output=True, text=True, timeout=5,
            )
        self.assertEqual(result.returncode, 6, result.stderr)
        self.assertEqual(Path(result.stdout.strip()).resolve(), Path(directory).resolve())

    def test_given_detached_child_keeps_output_open_then_verification_still_returns_by_deadline(self):
        with tempfile.TemporaryDirectory(prefix="pstack-detached-check-") as directory:
            pid_file = Path(directory) / "child.pid"
            program = '''import os, signal, sys
from pathlib import Path
reader, writer = os.pipe()
child = os.fork()
if child == 0:
    os.close(reader)
    os.setsid()
    Path(sys.argv[1]).write_text(str(os.getpid()))
    os.write(writer, b"ready")
    os.close(writer)
    signal.pause()
else:
    os.close(writer)
    os.read(reader, 5)
    os.close(reader)
    print("evidence before timeout", flush=True)
    signal.pause()
'''
            runner = (
                "import json,runpy,sys;"
                "h=runpy.run_path(sys.argv[1]);"
                "r=h['run_check']([sys.executable,'-c',sys.argv[2],sys.argv[3]],sys.argv[4],0.3);"
                "print(json.dumps({'code':r.returncode,'stdout':r.stdout,'stderr':r.stderr}))"
            )
            process = subprocess.Popen(
                [sys.executable, "-B", "-c", runner, str(ROOT / "scripts/e2e-process.py"), program, str(pid_file), directory],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True,
            )
            try:
                stdout, stderr = process.communicate(timeout=6)
                self.assertEqual(process.returncode, 0, stderr)
                receipt = json.loads(stdout)
                self.assertEqual(receipt["code"], 124)
                self.assertIn("evidence before timeout", receipt["stdout"])
                self.assertIn("timed out", receipt["stderr"])
            finally:
                if pid_file.exists():
                    try:
                        os.kill(int(pid_file.read_text()), signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                process.communicate(timeout=5)


if __name__ == "__main__":
    unittest.main()
