#!/usr/bin/env bash
# Read-only worktree prune audit. Classifies every git worktree by size, merge
# state, uncommitted work, and remote/PR state. Codex does not expose a stable
# transcript registry to this script, so LAST_CHAT is explicitly unknown.
# Emits a table sorted by size with a suggested bucket. Never deletes anything;
# deletion stays a human-gated step in the playbook.
#
# Usage: worktree-audit.sh [repo-path]   (defaults to the current repo)
set -u

repo="${1:-$(git rev-parse --show-toplevel 2>/dev/null)}"
[ -z "$repo" ] && { echo "not in a git repo; pass a repo path" >&2; exit 1; }
cd "$repo" || exit 1

# Main worktree is the first entry; everything else is a candidate.
main_wt=$(git worktree list --porcelain | sed -n 's/^worktree //p' | head -1)

# Use an explicit base when supplied, otherwise an already configured origin
# HEAD. Fetching would mutate the checkout, which violates this audit's
# read-only contract.
base_ref="${WORKTREE_AUDIT_BASE:-}"
if [ -z "$base_ref" ]; then
	base_ref=$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null || echo "")
fi
if [ -z "$base_ref" ]; then
	echo "warn: no local base ref is available; merged column is unknown" >&2
fi

# PR state by branch, queried once. An unavailable forge is unknown, never an
# empty result that could make a candidate look safe.
prs=$(mktemp)
trap 'rm -f "$prs"' EXIT INT TERM
gh_ok=yes
origin_url=$(git remote get-url origin 2>/dev/null || echo "")
repo_slug=""
case "$origin_url" in
    https://github.com/*) repo_slug="${origin_url#https://github.com/}" ;;
    git@github.com:*) repo_slug="${origin_url#git@github.com:}" ;;
    *) gh_ok=no ;;
esac
repo_slug="${repo_slug%.git}"
if ! printf '%s' "$repo_slug" | LC_ALL=C grep -Eq '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$'; then
    gh_ok=no
fi
if [ "$gh_ok" = yes ] && ! gh pr list --repo "$repo_slug" --state all --limit 1000 \
	--json number,state,headRefName,headRepositoryOwner,headRepository 2>/dev/null > "$prs"; then
	gh_ok=no
	: > "$prs"
fi

now=$(date +%s)

printf "SIZE\tAGE\tMERGED\tDIRTY\tREMOTE\tPR\tLAST_CHAT\tBUCKET\tWORKTREE\n"

git worktree list --porcelain | sed -n 's/^worktree //p' | while IFS= read -r wt; do
	[ "$wt" = "$main_wt" ] && continue

	size=$(du -sh "$wt" 2>/dev/null | awk '{print $1}')
	head=$(git -C "$wt" rev-parse HEAD 2>/dev/null)
	head_ts=$(git -C "$wt" log -1 --format='%ct' HEAD 2>/dev/null || echo 0)
	age=$([ "$head_ts" -gt 0 ] 2>/dev/null && echo "$(( (now - head_ts) / 86400 ))d" || echo "?")

	# Squash-merged branches are not ancestors of main, so PR state is the
	# real signal; merge-base only catches fast-forward/rebase merges.
	if [ -n "$base_ref" ]; then
		if git merge-base --is-ancestor "$head" "$base_ref" 2>/dev/null; then
			merged=YES
		else
			merge_code=$?
			[ "$merge_code" = 1 ] && merged=no || merged=unknown
		fi
	else
		merged=unknown
	fi

	# Distinguish tracked edits from untracked files; preserve both.
	if ! porcelain=$(git -C "$wt" status --porcelain 2>/dev/null); then
		dirty=unknown
	elif [ -z "$porcelain" ]; then dirty=clean
	elif printf '%s\n' "$porcelain" | grep -qv '^??'; then
		dirty="wip:$(printf '%s\n' "$porcelain" | grep -cv '^??')"
	else dirty="scratch:$(printf '%s\n' "$porcelain" | grep -c '^??')"; fi

	branch=$(git -C "$wt" symbolic-ref --quiet --short HEAD 2>/dev/null || echo "")
	if [ -z "$branch" ]; then
		remote=detached
	else
		upstream=$(git -C "$wt" rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null || echo "")
		if [ -z "$upstream" ]; then
			remote=unknown
		else
			counts=$(git -C "$wt" rev-list --left-right --count "$upstream...HEAD" 2>/dev/null || echo "")
			behind=$(printf '%s' "$counts" | awk '{print $1}')
			ahead=$(printf '%s' "$counts" | awk '{print $2}')
			if [ -z "$behind" ] || [ -z "$ahead" ]; then remote=unknown
			elif [ "$behind" = 0 ] && [ "$ahead" = 0 ]; then remote=pushed
			else remote="ahead${ahead}/behind${behind}"; fi
		fi
	fi

	if [ "$gh_ok" = no ]; then
		pr="unknown"
	elif [ -n "$branch" ]; then
		matches=$(jq -r --arg b "$branch" --arg repo "$repo_slug" \
			'[.[] | select(.headRefName==$b and ((.headRepository.nameWithOwner // "") == $repo))] | if length == 1 then .[0] | "#\(.number)/\(.state)" elif length > 1 then "ambiguous" else "-" end' "$prs" 2>/dev/null || echo "unknown")
		pr=${matches:-unknown}
	else
		pr="-"
	fi

	# Codex has no supported, repository-scoped chat transcript registry here.
	# Never infer liveness from an IDE history directory or filesystem mtime.
	last="unknown"
	recent=no

	case "$dirty" in
		unknown) bucket=hold-unknown ;;
		wip:*) bucket=hold-wip ;;
		scratch:*) bucket=hold-scratch ;;
		*)
			case "$pr" in
				*OPEN*) bucket=hold-open-pr ;;
				*MERGED*) [ "$merged" = YES ] && bucket=cleanup-candidate-needs-review || bucket=review ;;
				*CLOSED*) bucket=review-closed-pr ;;
				unknown) bucket=review-unknown-pr ;;
				-*) [ "$merged" = YES ] && bucket=review-merged || bucket=review ;;
				*) bucket=review ;;
			esac ;;
	esac

	printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n" \
		"$size" "$age" "$merged" "$dirty" "$remote" "$pr" "$last" "$bucket" "$wt"
done | sort -t$'\t' -k1,1 -rh

rm -f "$prs"
