#!/usr/bin/env python3
"""Bundle the CLI helpers for Node without install-time or runtime downloads."""

from pathlib import Path
import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="compare a temporary build with bin/ without writing it")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    source = root / "skills/poteto-mode/scripts"
    dependencies = source / "node_modules"
    if not (dependencies / "commander/package.json").is_file():
        raise SystemExit(f"Install build dependencies first: cd {source} && bun install --frozen-lockfile")
    bun = shutil.which("bun")
    if not bun:
        raise SystemExit("Bun is required for building. Installed runtime bundles need only Node.")
    expected_version = (root / ".bun-version").read_text().strip()
    version = subprocess.check_output([bun, "--version"], text=True).strip()
    if version != expected_version:
        raise SystemExit(f"Use Bun {expected_version} from .bun-version for reproducible builds; found {version}.")
    with tempfile.TemporaryDirectory(prefix="pstack-runtime-build-") as temporary:
        output = Path(temporary) / "output"
        output.mkdir()
        tree = Path(temporary) / "source"
        shutil.copytree(source, tree, ignore=shutil.ignore_patterns("node_modules", "*.log", ".DS_Store", "*.tsbuildinfo"))
        hashes = {
            str(source.relative_to(root) / file.relative_to(tree)): hashlib.sha256(file.read_bytes()).hexdigest()
            for file in sorted(tree.rglob("*")) if file.is_file()
        }
        shutil.copytree(dependencies / "commander", tree / "node_modules/commander")
        orch = tree / "orch/orch.ts"
        body = orch.read_text()
        replacements = {
            'import { ensureDependenciesInstalled } from "../bootstrap.ts";': "",
            "ensureDependenciesInstalled();": "",
            'if (import.meta.main) {\n  process.exitCode = await main(process.argv.slice(2));\n}': "",
        }
        for old, new in replacements.items():
            if body.count(old) != 1:
                raise SystemExit(f"Upstream entry changed; review the runtime adapter: {old}")
            body = body.replace(old, new)
        orch.write_text(body)
        for name, module in (("orch", "./orch/orch.ts"), ("watch-pr", "./watch-pr/cli.ts")):
            entry = tree / f"{name}-entry.ts"
            entry.write_text(f'import {{ main }} from "{module}";\nprocess.exitCode = await main(process.argv.slice(2));\n')
            target = output / f"{name}.mjs"
            subprocess.run([bun, "build", entry.name, "--target=node", "--format=esm", "--outfile", str(target)], cwd=tree, check=True)
            target.write_text("#!/usr/bin/env node\n" + target.read_text())
            target.chmod(0o755)
        shutil.copyfile(dependencies / "commander/LICENSE", output / "COMMANDER-LICENSE.txt")
        (output / "source-hashes.json").write_text(json.dumps(hashes, indent=2) + "\n")
        destination = root / "bin"
        if args.check:
            stale = [file.name for file in sorted(output.iterdir())
                     if not (destination / file.name).is_file()
                     or file.read_bytes() != (destination / file.name).read_bytes()
                     or bool(file.stat().st_mode & 0o111) != bool((destination / file.name).stat().st_mode & 0o111)]
            if stale:
                raise SystemExit("Stale runtime artifacts: " + ", ".join(stale)
                                 + ". Run python3 scripts/build-runtime.py with Bun " + version + ".")
            print(f"Runtime artifacts match source (Bun {version}).")
        else:
            destination.mkdir(exist_ok=True)
            for file in output.iterdir():
                shutil.copy2(file, destination / file.name)
            print(f"Built Node runtime helpers in {destination}")


if __name__ == "__main__":
    main()
