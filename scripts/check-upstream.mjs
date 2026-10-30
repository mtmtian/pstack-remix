#!/usr/bin/env node
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {readPin} from './check-fork.mjs';

const pinned = readPin(path.join(import.meta.dirname, '..'));
const repo = new URL(pinned.repository).pathname.slice(1);
const api = path => JSON.parse(execFileSync('gh', ['api', path], {encoding: 'utf8', maxBuffer: 8 * 1024 * 1024}));
const PAGE = 100;
const metadata = api(`repos/${repo}`);
const pathCommits = (sha, page) => api(`repos/${repo}/commits?path=${encodeURIComponent(pinned.path)}&sha=${sha}&per_page=${PAGE}&page=${page}`);
const first = pathCommits(metadata.default_branch, 1);
const latest = first[0]?.sha;
if (!latest) throw new Error('No upstream commit found for the tracked path');
const manifest = api(`repos/${repo}/contents/${pinned.path}/.cursor-plugin/plugin.json?ref=${latest}`);
const version = JSON.parse(Buffer.from(manifest.content, 'base64').toString()).version;

// The compare endpoint lists at most 300 files for the whole monorepo, so walk the tracked path's own commits back to the pin instead.
const commits = [];
for (let page = 1; ; page++) {
  const batch = page === 1 ? first : pathCommits(latest, page);
  const at = batch.findIndex(c => c.sha === pinned.commit);
  commits.push(...(at < 0 ? batch : batch.slice(0, at)).map(c => ({sha: c.sha, subject: c.commit.message.split('\n')[0]})));
  if (at >= 0) break;
  if (batch.length < PAGE) throw new Error('The pinned commit is not in the tracked path history');
}
const changed = new Set();
for (const {sha} of commits) {
  let listed = 0;
  for (let page = 1; ; page++) {
    const {files} = api(`repos/${repo}/commits/${sha}?per_page=${PAGE}&page=${page}`);
    for (const f of files) for (const name of [f.filename, f.previous_filename]) if (name?.startsWith(pinned.path + '/')) changed.add(name);
    listed += files.length;
    if (files.length < PAGE) break;
  }
  // GitHub lists at most 3000 files for one commit.
  if (listed >= 3000) throw new Error(`Upstream commit ${sha} may change more files than GitHub lists; diff it with git instead`);
}
console.log(JSON.stringify({
  checkedAt: new Date().toISOString(), repository: metadata.full_name,
  fork: metadata.fork, parent: metadata.parent?.full_name ?? null, source: metadata.source?.full_name ?? null,
  pushedAt: metadata.pushed_at, pinnedCommit: pinned.commit, latestCommit: latest,
  pinnedVersion: pinned.version, latestVersion: version,
  status: latest === pinned.commit ? 'up-to-date' : 'review-required',
  commits, changedFiles: [...changed].sort(),
  instructions: 'Read-only check. Review the upstream diff against the shared source and both host adapters before changing the pin.'
}, null, 2));
