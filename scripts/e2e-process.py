#!/usr/bin/env python3
"""Verify current source with a fresh Python cache, deadline and process-group cleanup."""
import argparse
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile


def signal_group(pgid, signum):
    try:
        os.killpg(pgid, signum)
    except ProcessLookupError:
        pass
    except PermissionError:
        # macOS reports EPERM, not ESRCH, for a group whose members have all
        # exited but are not yet reaped. Only a running member can refuse.
        if group_has_running_member(pgid):
            raise


def group_has_running_member(pgid):
    listing = subprocess.run(["ps", "-A", "-o", "pgid=,stat="], capture_output=True, text=True, check=True).stdout
    for line in listing.splitlines():
        fields = line.split()
        # A leading Z or X is dead; macOS adds E to a process that is still exiting.
        if len(fields) == 2 and fields[0] == str(pgid) and fields[1][0] not in "ZX" and "E" not in fields[1]:
            return True
    return False


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

        def stop(signum):
            process.poll()
            signal_group(process.pid, signum)

        timed_out = False
        try:
            try:
                stdout, stderr = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                stop(signal.SIGTERM)
                try:
                    stdout, stderr = process.communicate(timeout=1)
                except subprocess.TimeoutExpired:
                    stop(signal.SIGKILL)
                    try:
                        stdout, stderr = process.communicate(timeout=1)
                    except subprocess.TimeoutExpired as error:
                        stdout = (error.output or b"").decode("utf-8", errors="replace")
                        stderr = (error.stderr or b"").decode("utf-8", errors="replace")
                        stderr += "\nOutput pipes remained open after process-group termination.\n"
                        process.stdout.close()
                        process.stderr.close()
        finally:
            stop(signal.SIGKILL)
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
