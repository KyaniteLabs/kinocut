# Kinocut 1.8.0 — release cutover checklist

**Status:** PREP (not released). Do **not** bump package version, tag, publish, or flip
marketing claims until human go-ahead **and** the freeze gates below pass.

**Authority:** [`public_claims.json`](public_claims.json) · [`RELEASE_RITUAL.md`](RELEASE_RITUAL.md) ·
[`.github/workflows/publish.yml`](../.github/workflows/publish.yml)

**Tip surface (as of prep, 2026-07-14):** 142 MCP tools · 121 CLI commands  
**Current published:** 1.7.0 · 135 MCP / 114 CLI

When 1.8.0 ships, **published counts become the release-tag tip counts** (expected
142 / 121 unless the freeze re-measures different numbers). At tag time set
`development_* == published_*` unless post-tag master already moved.

---

## 0. Freeze gates (must be green before cutover)

| Gate | Check | Owner |
| --- | --- | --- |
| Public surface tests | `pytest tests/test_public_surface.py tests/test_public_claims.py -q` | agent |
| Characterization counts | `list_tools` length == `development_mcp_tools`; CLI == 121 | agent |
| Golden path | `python scripts/golden_path.py` (clone tree) | agent |
| Doctor | `kino doctor` on clean machine notes | agent |
| AI-video program | Wave freeze / acceptance as decided for *this* cut | human |
| Sound S15 | [S13–S15 gate receipt](status/2026-07-14-sound-s13-s15-gate-receipt.md) — S15 was **STOP** at prep; only include sound claims if human re-authorizes | human |
| Independent review | whatever the program STOP requires | human |
| **Human release go-ahead** | explicit | human |

If a gate is open, either drop that feature from 1.8 messaging or delay the tag.

---

## 1. Measure release surface (on the release commit)

```bash
# MCP tools
python3 - <<'PY'
import asyncio
from kinocut.server import mcp
print(len(asyncio.run(mcp.list_tools())))
PY

# CLI (matches tests/test_public_surface.py EXPECTED_CLI_COMMANDS)
pytest tests/test_public_surface.py -q -k 'cli or tools' --tb=line
```

Record: `MCP_N=…` `CLI_N=…` `DATE=YYYY-MM-DD`.

---

## 2. Apply package + claims cutover

**Preferred (dry-run first):**

```bash
# dry-run (default — prints WOULD, writes nothing)
python scripts/apply_public_release_cutover.py \
  --version 1.8.0 \
  --date "$DATE" \
  --mcp-tools "$MCP_N" \
  --cli-commands "$CLI_N"

# write files
python scripts/apply_public_release_cutover.py \
  --version 1.8.0 \
  --date "$DATE" \
  --mcp-tools "$MCP_N" \
  --cli-commands "$CLI_N" \
  --apply
```

The script updates:

| File | What changes |
| --- | --- |
| `docs/public_claims.json` | published + development counts/version/date |
| `pyproject.toml` | `project.version` |
| `kinocut/__init__.py` | `__version__` |
| `server.json` | top-level + package versions |
| `npm/package.json` | version |
| `compat/mcp-video-shim/pyproject.toml` | all `kinocut==…` pins (shim package version stays `1.6.1` unless you intentionally cut a new shim) |
| `mcpb/manifest.json` | version + kinocut pin wording |
| `demo/golden-pack/sample_video_receipt.json` | `kinocut_published_version` |
| `llms.txt` | published line + counts |
| `CHANGELOG.md` | promotes Unreleased → `## 1.8.0 - DATE` (manual review required) |

**Still manual after script:**

- `README.md` — status table, “What's in 1.8”, remove “1.8 is not released” block, FAQ, Spanish blurb, badges if tip==published
- `mcpb/README.md`, `docs/MCPB.md`, `docs/RENAME.md`, `docs/DIRECTORY_*` as needed
- `docs/faq.md` if it pins 1.7.0
- Any hardcoded `135` / `114` as *published* (not historical)
- `tests/` hard-coded expectations already follow `development_*` via public_claims; re-run tests
- Skills under `skills/` if they mention version (usually not)

---

## 3. Marketing honesty rewrite (README / ROADMAP)

Replace “Heading toward 1.8 / not released” with:

1. **What's in 1.8.0 (latest release)** — only what is on the tag  
2. **Compatibility** — still “through at least Kinocut 1.x.x” (extend beyond 1.8 if needed)  
3. **Next** — “toward 1.9” or kernel program (do not invent version numbers without claims)

Three agent-facing bullets (also GitHub Release + site changelog):

1. What agents can do now  
2. What got safer  
3. Compat note  

Draft content lives in [`status/2026-07-14-1.8-release-notes-draft.md`](status/2026-07-14-1.8-release-notes-draft.md).

---

## 4. Verify (product repo)

```bash
pytest tests/test_public_claims.py tests/test_public_surface.py tests/test_kinocut_distribution.py -q
python3 -c "import kinocut, mcp_video; assert kinocut.Client is mcp_video.Client; assert kinocut.__version__ == '1.8.0'"
python scripts/golden_path.py
```

`test_public_claims` forbids claiming a *next* unreleased X.Y.0 in README; after cutover the published version is 1.8.0 and the guard moves to the following minor.

---

## 5. Ship package + registry

1. Merge cutover PR to `master` (Forgejo canonical; GitHub mirror).  
2. Create GitHub Release tag **`v1.8.0`** (triggers [publish.yml](../.github/workflows/publish.yml)).  
3. Confirm PyPI `kinocut==1.8.0`, npm `kinocut@1.8.0`, MCP Registry version, shim still installs (`mcp-video==1.6.1` → `kinocut==1.8.0` after pin update).  
4. Do **not** re-upload immutable artifacts; use registry-only recovery if needed.

---

## 6. kinocut.dev (separate repo)

```bash
cd ../kinocut-site   # or workspaces/kinocut-site
./scripts/bump-published-version.sh 1.8.0 142   # MCP count for display
./scripts/verify-primary-surface.sh https://kinocut.dev/
```

Surfaces to bump (script + manual scan):

- All doc chips `1.7.0 published` → `1.8.0 published`
- `index.html`: JSON-LD `softwareVersion`, facts strip, bay brand sub, body copy “135…1.7.0”, roadmap “published today is 1.7”
- `llms.txt`, `changelog.html`, `faq.html`, `rename.html`
- Keep historical FAQ “was it 1.7 rename?” accurate; add 1.8 as latest

PR + merge **GitHub** (Pages) and **Forgejo**. Run primary-surface gate after deploy.

---

## 7. Directories + proof

- Walk [DIRECTORY_STATUS.md](DIRECTORY_STATUS.md) / [DIRECTORY_REBRAND_STATUS.md](DIRECTORY_REBRAND_STATUS.md)  
- Link golden path / dated proof under `docs/proofs/` if re-run  
- Optional: refresh usage metrics snapshot  

---

## 8. Post-release tip

If master continues after the tag:

- Bump only `development_*` in `public_claims.json` when tip counts change  
- Keep `published_*` frozen until the next release  

---

## Explicit non-goals for this prep

- Do not set `pyproject` to 1.8.0 on master before go-ahead  
- Do not invent social proof or claim sound/S15 shipped if S15 remains STOP  
- Do not treat tool-count-as-only-hero; still lead with gates/receipts  
- Do not open-source private paths or machine hostnames in release notes  
