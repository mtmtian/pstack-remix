import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import process from "node:process";

const imports = (text, dir) =>
  [...text.matchAll(/\b(?:from|import)\s*\(?\s*["'](\.{1,2}\/[^"']+)["']/g)].map((m) =>
    path.resolve(dir, m[1]),
  );

const DEPENDENCIES = {
  ".tla": (text, dir) =>
    [
      ...text
        .replace(/\(\*[^]*?\*\)/g, " ")
        .replace(/\\\*.*/g, " ")
        .matchAll(/\b(?:EXTENDS|INSTANCE)\s+(\w+(?:\s*,\s*\w+)*)/g),
    ].flatMap((m) => m[1].split(/\s*,\s*/).map((name) => path.join(dir, `${name}.tla`))),
  ".mjs": imports,
  ".js": imports,
};

export const copyPath = (root, file, paths = path) => {
  const absolute = paths.resolve(file);
  const pathRoot = paths.parse(absolute).root;
  return paths.join(root, pathRoot.replace(/\W+/g, ""), paths.relative(pathRoot, absolute));
};

const contentOf = (file) => {
  try {
    return fs.readFileSync(file, "base64");
  } catch {
    return null;
  }
};

// The specs and configs in a folder. TLC's trace files do not count.
const specFiles = (dir) => {
  try {
    return fs
      .readdirSync(dir)
      .filter((f) => /\.(tla|cfg)$/.test(f) && !f.includes("_TTrace_"))
      .sort();
  } catch {
    return null;
  }
};

export class Inputs {
  #root = fs.mkdtempSync(path.join(os.tmpdir(), "statechart-inputs-"));
  #files = new Set();
  #folders = new Map();

  constructor() {
    process.on("exit", () => fs.rmSync(this.#root, { recursive: true, force: true }));
  }

  add(files) {
    for (const file of files) if (file) this.#take(path.resolve(file), true);
    return this;
  }

  copyOf(file) {
    return copyPath(this.#root, file);
  }

  // The specs and configs in a folder as the run first listed them, each one an input. A spec or
  // config that appears there or goes later changes the folder.
  specsIn(dir) {
    const folder = path.resolve(dir);
    if (!this.#folders.has(folder)) {
      const files = specFiles(folder);
      this.#folders.set(folder, files);
      this.add((files ?? []).map((f) => path.join(folder, f)));
    }
    return this.#folders.get(folder) ?? [];
  }

  changed() {
    for (const [folder, files] of this.#folders)
      if (String(specFiles(folder)) !== String(files)) return folder;
    return [...this.#files].find((file) => contentOf(file) !== contentOf(this.copyOf(file)));
  }

  #take(file, listed) {
    if (this.#files.has(file)) return;
    let content;
    try {
      content = fs.readFileSync(file);
    } catch {
      if (listed) this.#files.add(file);
      return;
    }
    this.#files.add(file);
    const copy = this.copyOf(file);
    fs.mkdirSync(path.dirname(copy), { recursive: true });
    fs.writeFileSync(copy, content);
    const found = DEPENDENCIES[path.extname(file)]?.(content.toString("utf8"), path.dirname(file));
    for (const dependency of found ?? []) this.#take(dependency, false);
  }
}
