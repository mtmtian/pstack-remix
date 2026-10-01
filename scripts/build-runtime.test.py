#!/usr/bin/env python3
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ("orch.mjs", "watch-pr.mjs", "COMMANDER-LICENSE.txt", "source-hashes.json")


class RuntimeBuildTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="pstack-build-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "checkout"
        self.root.mkdir()
        source = Path("skills/poteto-mode/scripts")
        shutil.copytree(ROOT / source, self.root / source, ignore=shutil.ignore_patterns("node_modules"))
        (self.root / source / "node_modules").symlink_to(ROOT / source / "node_modules", target_is_directory=True)
        (self.root / "scripts").mkdir()
        shutil.copyfile(ROOT / "scripts/build-runtime.py", self.root / "scripts/build-runtime.py")
        version = ROOT / ".bun-version"
        if version.exists():
            shutil.copyfile(version, self.root / version.name)

    def run_build(self, *args, cwd=None):
        return subprocess.run(
            [sys.executable, str(self.root / "scripts/build-runtime.py"), *args],
            cwd=cwd or self.root, capture_output=True, text=True, timeout=30,
        )

    def build(self):
        result = self.run_build()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def artifacts(self):
        return {name: (self.root / "bin" / name).read_bytes() for name in ARTIFACTS}

    def test_build_is_identical_across_working_and_temporary_directories(self):
        self.build()
        first = self.artifacts()
        result = self.run_build(cwd=self.root.parent)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.artifacts(), first)

    def test_check_accepts_fresh_uncommitted_artifacts_without_writing(self):
        self.build()
        before = self.artifacts()
        times = {name: (self.root / "bin" / name).stat().st_mtime_ns for name in ARTIFACTS}
        result = self.run_build("--check")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.artifacts(), before)
        self.assertEqual({name: (self.root / "bin" / name).stat().st_mtime_ns for name in ARTIFACTS}, times)

    def test_check_rejects_source_drift_without_rewriting_artifacts(self):
        self.build()
        before = self.artifacts()
        source = self.root / "skills/poteto-mode/scripts/watch-pr/render.ts"
        source.write_text(source.read_text() + "\n")
        result = self.run_build("--check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("source-hashes.json", result.stdout + result.stderr)
        self.assertEqual(self.artifacts(), before)

    def test_check_rejects_tampered_and_missing_bundles_without_repairing_them(self):
        self.build()
        bundle = self.root / "bin/orch.mjs"
        bundle.write_bytes(bundle.read_bytes() + b"\n")
        tampered = bundle.read_bytes()
        result = self.run_build("--check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("orch.mjs", result.stdout + result.stderr)
        self.assertEqual(bundle.read_bytes(), tampered)
        bundle.unlink()
        result = self.run_build("--check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("orch.mjs", result.stdout + result.stderr)
        self.assertFalse(bundle.exists())

    def test_check_rejects_a_bundle_that_lost_execute_permission(self):
        self.build()
        bundle = self.root / "bin/orch.mjs"
        bundle.chmod(0o644)
        result = self.run_build("--check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("orch.mjs", result.stdout + result.stderr)
        self.assertEqual(bundle.stat().st_mode & 0o111, 0)

    def test_local_logs_and_caches_do_not_change_build_inputs(self):
        self.build()
        before = self.artifacts()
        source = self.root / "skills/poteto-mode/scripts"
        for name in (".DS_Store", "watch-pr/debug.log", "watch-pr/tsconfig.tsbuildinfo"):
            (source / name).write_text("local cache\n")
        result = self.run_build("--check")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.artifacts(), before)


if __name__ == "__main__":
    unittest.main()
