# Release ritual (on-domain marketing)

Minimum marketing steps when cutting a public Kinocut release. Engineering release process remains in CI/publish workflows.

**For the 1.8.0 cutover** use the ordered checklist and automation:

- [`RELEASE_1.8_CHECKLIST.md`](RELEASE_1.8_CHECKLIST.md)
- [`scripts/apply_public_release_cutover.py`](../scripts/apply_public_release_cutover.py)
- Draft bullets: [`status/2026-07-14-1.8-release-notes-draft.md`](status/2026-07-14-1.8-release-notes-draft.md)

## 1. Freeze claims

Update [`public_claims.json`](public_claims.json):

- `published_version`, `published_date`
- `published_mcp_tools`, `published_cli_commands` (from public surface tests on the release tag)
- Keep `development_*` equal to published at tag time, or leave tip higher only on post-release master

## 2. Verify

```bash
pytest tests/test_public_claims.py tests/test_public_surface.py -q
python scripts/golden_path.py
```

## 3. Ship package + registry

Follow existing publish workflow (PyPI, MCP Registry recovery if needed).

## 4. Three agent-facing bullets

Write exactly three bullets for:

- GitHub Release body  
- kinocut.dev `/changelog.html` (or site changelog page)  
- Social / directories  

Format:

1. What agents can do now  
2. What got safer (guardrail/receipt/doctor)  
3. Compat note (if any)

## 5. Proof link

If golden path or a demo pack was re-run, link `docs/GOLDEN_PATH.md` or a dated proof under `docs/proofs/`.

## 6. Directories

Walk [DIRECTORY_STATUS.md](DIRECTORY_STATUS.md) board; open/refresh tickets.

## 7. Site

If version messaging on kinocut.dev is hardcoded, bump to match `published_version` (facts strip, JSON-LD, llms.txt).
