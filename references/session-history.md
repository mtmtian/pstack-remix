# Prior sessions

Read this when a skill needs earlier sessions on this repository.

For history, follow the host adapter; restrict local transcript candidates by repository/cwd, session, and time before reading content. `node <plugin-root>/bin/transcripts.mjs --host <claude|codex> --cwd <checkout> [--since <date>] [--until <date>] [--json]` applies the cwd and time restriction (default: the current directory and the last 7 days) and lists the candidates newest first by modification time; read only listed files, and only the parts the task needs. A linked worktree records its own cwd, so pass every checkout in scope (`git worktree list`) as another `--cwd`.
