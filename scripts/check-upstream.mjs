#!/usr/bin/env node
import {readFileSync} from 'node:fs';
import {execFileSync} from 'node:child_process';

const pinned = JSON.parse(readFileSync(new URL('../UPSTREAM.json', import.meta.url), 'utf8'));
const match = /^https:\/\/github\.com\/([\w.-]+\/[\w.-]+)$/.exec(pinned.repository);
if (!match || !/^[a-f0-9]{40}$/.test(pinned.commit) || !/^[\w/-]+$/.test(pinned.path) || pinned.path.includes('..')) {
  throw new Error('Invalid UPSTREAM.json repository, commit, or path');
}
const repo = match[1];
const api = path => JSON.parse(execFileSync('gh', ['api', path], {encoding: 'utf8', maxBuffer: 8 * 1024 * 1024}));
const metadata = api(`repos/${repo}`);
const commits = api(`repos/${repo}/commits?path=${encodeURIComponent(pinned.path)}&per_page=1`);
if (!commits.length) throw new Error('No upstream commit found for the tracked path');
const latest = commits[0].sha;
const manifest = api(`repos/${repo}/contents/${pinned.path}/.cursor-plugin/plugin.json?ref=${latest}`);
const version = JSON.parse(Buffer.from(manifest.content, 'base64').toString()).version;
let comparison = null;
if (latest !== pinned.commit) comparison = api(`repos/${repo}/compare/${pinned.commit}...${latest}`);
const files = comparison?.files ?? [];
const truncated = files.length >= 300;
console.log(JSON.stringify({
  checkedAt: new Date().toISOString(), repository: metadata.full_name,
  fork: metadata.fork, parent: metadata.parent?.full_name ?? null, source: metadata.source?.full_name ?? null,
  pushedAt: metadata.pushed_at, pinnedCommit: pinned.commit, latestCommit: latest,
  pinnedVersion: pinned.version, latestVersion: version,
  status: latest === pinned.commit ? 'up-to-date' : 'review-required',
  comparisonStatus: comparison?.status ?? 'identical', changedFiles: files.filter(f => f.filename.startsWith(pinned.path + '/')).map(f => f.filename),
  comparisonMayBeTruncated: truncated,
  instructions: 'Read-only check. Review the upstream diff against the shared source and both host adapters before changing the pin.'
}, null, 2));
