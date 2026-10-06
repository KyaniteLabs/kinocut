#!/usr/bin/env bash
set -euo pipefail

# Professional Git hygiene audit for local clones.
# Usage: ./scripts/git-professional-audit.sh

red='\033[0;31m'
green='\033[0;32m'
yellow='\033[1;33m'
reset='\033[0m'

failures=0
warnings=0

pass() {
  printf "${green}PASS${reset} %s\n" "$1"
}

warn() {
  warnings=$((warnings + 1))
  printf "${yellow}WARN${reset} %s\n" "$1"
}

fail() {
  failures=$((failures + 1))
  printf "${red}FAIL${reset} %s\n" "$1"
}

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Not inside a Git repository." >&2
  exit 2
fi

current_branch="$(git rev-parse --abbrev-ref HEAD)"

if [[ "$current_branch" == "HEAD" ]]; then
  fail "Detached HEAD detected. Create/switch to a named branch before committing."
else
  pass "Current branch is '$current_branch'."
fi

if [[ -z "$(git status --porcelain)" ]]; then
  pass "Working tree is clean."
else
  warn "Working tree has uncommitted changes."
fi

if git rev-parse --abbrev-ref --symbolic-full-name '@{u}' >/dev/null 2>&1; then
  upstream="$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}')"
  pass "Upstream is configured: $upstream"

  read -r behind ahead < <(git rev-list --left-right --count "${upstream}...HEAD")
  if [[ "$ahead" -eq 0 && "$behind" -eq 0 ]]; then
    pass "Branch is in sync with upstream."
  elif [[ "$behind" -gt 0 && "$ahead" -eq 0 ]]; then
    warn "Branch is behind upstream by $behind commit(s)."
  elif [[ "$ahead" -gt 0 && "$behind" -eq 0 ]]; then
    warn "Branch is ahead of upstream by $ahead commit(s)."
  else
    warn "Branch has diverged from upstream (ahead $ahead / behind $behind)."
  fi
else
  if git remote | grep -q .; then
    fail "No upstream branch configured. Use: git push -u <remote> <branch>"
  else
    warn "No remotes configured; upstream checks skipped for local-only clone."
  fi
fi

worktree_count="$(git worktree list --porcelain | awk '$1=="worktree"{count++} END{print count+0}')"
if [[ "$worktree_count" -ge 1 ]]; then
  pass "Detected $worktree_count registered worktree(s); registration does not establish an active writer."
else
  fail "No active worktree detected (unexpected repository state)."
fi

if git fsck --full >/dev/null 2>&1; then
  pass "Repository integrity check passed (git fsck --full)."
else
  fail "Repository integrity check failed. Run: git fsck --full"
fi

stale_count="$(git branch -vv | awk '/: gone]/{count++} END{print count+0}')"
if [[ "$stale_count" -eq 0 ]]; then
  pass "No local branches tracking deleted remotes."
else
  warn "$stale_count branch(es) track deleted remotes. Inspect current refs and ownership before any authorized cleanup."
fi

if git config --get init.defaultBranch >/dev/null 2>&1; then
  pass "init.defaultBranch is set to '$(git config --get init.defaultBranch)'."
else
  warn "init.defaultBranch is not set globally/local."
fi

if [[ "$failures" -gt 0 ]]; then
  echo
  echo "Audit complete: $failures failure(s), $warnings warning(s)."
  exit 1
fi

echo
echo "Audit complete: 0 failures, $warnings warning(s)."
