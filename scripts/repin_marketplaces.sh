#!/usr/bin/env bash
# Re-pin the Kinocut plugin in the Grok (xAI) and Hermes Agent catalogs to the
# current master commit after a release. Run as the repository owner (uses your
# `gh` login and your forks of both catalogs).
#
#   bash scripts/repin_marketplaces.sh            # pin GitHub master HEAD
#   bash scripts/repin_marketplaces.sh <sha>      # pin a specific commit
#
# Grok: once kinocut is listed, xAI's daily bump-plugin-shas bot advances the
# pin by itself whenever plugins/kinocut/plugin.json changes version. This script
# only updates the still-open submission branch (add-kinocut).
# Hermes: re-pins are reviewed PRs. If kinocut is already in the catalog this
# opens a "bump" PR; while the submission PR is open it updates that branch.
set -euo pipefail

REPO=KyaniteLabs/kinocut
SHA="${1:-$(gh api "repos/$REPO/commits/master" -q .sha)}"
[[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || { echo "bad sha: $SHA" >&2; exit 1; }
VERSION="$(gh api "repos/$REPO/contents/plugins/kinocut/plugin.json?ref=$SHA" -q .content | base64 --decode | python3 -c 'import json,sys;print(json.load(sys.stdin)["version"])')"
ME="$(gh api user -q .login)"
WORK="$(mktemp -d)"
echo "Pinning kinocut $VERSION @ $SHA"

# ---------- Grok (xai-org/plugin-marketplace) ----------
grok() {
  local up=xai-org/plugin-marketplace branch=add-kinocut
  if gh api "repos/$up/contents/.grok-plugin/marketplace.json" -q .content | base64 --decode | grep -q 'KyaniteLabs/kinocut.git'; then
    echo "Grok: kinocut is listed; xAI's daily bot re-pins it. Nothing to do."; return
  fi
  if [ -z "$(gh pr list -R "$up" --head "$branch" --state open --json number -q '.[].number')" ]; then
    echo "Grok: no open submission PR and not listed. Skipping."; return
  fi
  cd "$WORK" && gh repo clone "$ME/plugin-marketplace" grok -- -q --branch "$branch" && cd grok
  python3 - "$SHA" "$VERSION" <<'PY'
import json, re, sys
sha, ver = sys.argv[1:]
p = ".grok-plugin/marketplace.json"
s = open(p).read()
s, n = re.subn(r'("url": "https://github\.com/KyaniteLabs/kinocut\.git",\s*"sha": ")[0-9a-f]{40}', r"\g<1>" + sha, s)
assert n == 1, "kinocut source entry not found"
start = s.index('"url": "https://github.com/KyaniteLabs/kinocut.git"')
end = s.index('"author"', start)
s = s[:start] + re.sub(r'"version": "[^"]+"', f'"version": "{ver}"', s[start:end], count=1) + s[end:]
s = re.sub(r"uvx kinocut==[0-9.]+", f"uvx kinocut=={ver}", s)
json.loads(s)
open(p, "w").write(s)
PY
  python3 scripts/generate-plugin-index.py && python3 scripts/validate-catalog.py && python3 scripts/generate-plugin-index.py --check
  if git diff --quiet; then echo "Grok: already pinned."; return; fi
  git commit -qam "kinocut: pin $VERSION ($SHA)" && git push -q origin "$branch"
  echo "Grok: submission PR updated to $SHA"
}

# ---------- Hermes Agent (NousResearch/hermes-agent) ----------
hermes() {
  local up=NousResearch/hermes-agent sub=plugin-catalog-kinocut branch
  gh repo sync "$ME/hermes-agent" --source "$up" --force >/dev/null 2>&1 || true
  cd "$WORK"
  if gh api "repos/$up/contents/plugin-catalog/kinocut.yaml" >/dev/null 2>&1; then
    branch="kinocut-$VERSION"
    gh repo clone "$ME/hermes-agent" hermes -- -q --depth 1 && cd hermes && git checkout -q -B "$branch"
  elif [ -n "$(gh pr list -R "$up" --head "$sub" --state open --json number -q '.[].number')" ]; then
    branch="$sub"
    gh repo clone "$ME/hermes-agent" hermes -- -q --depth 1 --branch "$branch" --single-branch && cd hermes
  else
    echo "Hermes: not listed and no open submission PR. Skipping."; return
  fi
  sed -i.bak -E \
    -e "s/^sha: .*/sha: $SHA/" \
    -e "s/^version: .*/version: \"$VERSION\"/" \
    -e "s/uvx kinocut==[0-9.]+/uvx kinocut==$VERSION/" plugin-catalog/kinocut.yaml && rm plugin-catalog/kinocut.yaml.bak
  if git diff --quiet; then echo "Hermes: already pinned."; return; fi
  git commit -qam "plugin-catalog: pin kinocut $VERSION"
  if [ "$branch" = "$sub" ]; then
    git push -q origin "$branch"; echo "Hermes: submission PR updated to $SHA"
  else
    git push -q -f -u origin "$branch"
    gh pr create -R "$up" --base main --head "$ME:$branch" \
      --title "plugin-catalog: pin kinocut $VERSION" \
      --body "Re-pins \`kinocut\` to \`$SHA\` (release $VERSION). Submitted by the repository owner (KyaniteLabs). Configuration-only package; the MCP server launches as \`uvx kinocut==$VERSION\` over stdio."
  fi
}

( grok )
( hermes )
echo "Done."
