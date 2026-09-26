#!/usr/bin/env python3
"""Bundle the CLI helpers for Node without install-time or runtime downloads."""

from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import tempfile


def main():
    root = Path(__file__).resolve().parents[1]
    source = root / "skills/poteto-mode/scripts"
    dependencies = source / "node_modules"
    if not (dependencies / "commander/package.json").is_file():
        raise SystemExit(f"Install build dependencies first: cd {source} && bun install --frozen-lockfile")
    bun = shutil.which("bun")
    if not bun:
        raise SystemExit("Bun is required for building. Installed runtime bundles need only Node.")
    output = root / "bin"
    output.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pstack-runtime-build-") as temporary:
        tree = Path(temporary) / "source"
        shutil.copytree(source, tree, ignore=shutil.ignore_patterns("node_modules", "*.log"))
        (tree / "node_modules").symlink_to(dependencies, target_is_directory=True)
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
            subprocess.run([bun, "build", str(entry), "--target=node", "--format=esm", "--outfile", str(target)], check=True)
            target.write_text("#!/usr/bin/env node\n" + target.read_text())
            target.chmod(0o755)
    license_file = dependencies / "commander/LICENSE"
    shutil.copyfile(license_file, output / "COMMANDER-LICENSE.txt")
    hashes = {}
    for file in sorted(source.rglob("*")):
        if file.is_file() and "node_modules" not in file.parts:
            hashes[str(file.relative_to(root))] = hashlib.sha256(file.read_bytes()).hexdigest()
    (output / "source-hashes.json").write_text(json.dumps(hashes, indent=2) + "\n")
    print(f"Built Node runtime helpers in {output}")


if __name__ == "__main__":
    main()
