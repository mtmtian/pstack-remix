#!/usr/bin/env python3
"""Verify current source with a fresh Python cache, deadline and process-group cleanup."""
import argparse
from contextlib import suppress
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile


def run_check(command, cwd, timeout=30, env=None):
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("verification timeout must be positive and finite")
    # -B prevents writes but still reads old .pyc files. Each verification needs
    # an empty cache namespace so timestamp/size collisions cannot hide edits.
    with tempfile.TemporaryDirectory(prefix="pstack-verify-pyc-") as cache:
        check_env = dict(os.environ if env is None else env)
        check_env.update(PYTHONPYCACHEPREFIX=cache, PYTHONDONTWRITEBYTECODE="1")
        try:
            process = subprocess.Popen(
                command, cwd=cwd, env=check_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace", start_new_session=True,
            )
        except OSError as error:
            return subprocess.CompletedProcess(command, 127, "", f"{error}\n")

        def signal_group(signum):
            process.poll()
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signum)

        timed_out = False
        try:
            try:
                stdout, stderr = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                signal_group(signal.SIGTERM)
                try:
                    stdout, stderr = process.communicate(timeout=1)
                except subprocess.TimeoutExpired:
                    signal_group(signal.SIGKILL)
                    try:
                        stdout, stderr = process.communicate(timeout=1)
                    except subprocess.TimeoutExpired as error:
                        stdout = (error.output or b"").decode("utf-8", errors="replace")
                        stderr = (error.stderr or b"").decode("utf-8", errors="replace")
                        stderr += "\nOutput pipes remained open after process-group termination.\n"
                        process.stdout.close()
                        process.stderr.close()
        finally:
            signal_group(signal.SIGKILL)
            process.wait()
        if timed_out:
            stderr += f"\nVerification timed out after {timeout:g} seconds.\n"
        return subprocess.CompletedProcess(command, 124 if timed_out else process.returncode, stdout, stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--cwd", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    options = parser.parse_args()
    command = options.command[1:] if options.command[:1] == ["--"] else options.command
    if not command:
        parser.error("a verification command is required")
    if not math.isfinite(options.timeout) or options.timeout <= 0:
        parser.error("timeout must be positive and finite")
    result = run_check(command, options.cwd, options.timeout)
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    return result.returncode if result.returncode >= 0 else 128 - result.returncode


if __name__ == "__main__":
    sys.exit(main())
