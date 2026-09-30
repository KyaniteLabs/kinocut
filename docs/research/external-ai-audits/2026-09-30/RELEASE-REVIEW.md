# Verified release-discovery refresh — 2026-09-30

Canonical docs/public_claims.json now records published kinocut 1.15.3 on 2026-09-25. Candidate/source versions and counts remain unchanged: 1.15.3, 201 MCP / 173 CLI. No package versions, dependency pins, remote release metadata, tags, publications or historical changelog sections were modified.

Primary evidence: saved PyPI JSON `/tmp/kinocut-audit-pypi-kinocut.json` and `/tmp/kinocut-audit-pypi-mcp-video.json`. All four artifacts were downloaded as data; each SHA-256 and byte size matches that metadata. Wheel ZIP METADATA was read without importing/installing/executing artifact code. kinocut wheel identifies 1.15.3; mcp-video wheel identifies 1.6.14 and Requires-Dist kinocut==1.15.3 (extras also uniformly pinned). Artifact evidence `/tmp/kinocut-release-artifact-validation.json`:

- kinocut wheel 7dc1a4516bef7f8bd24ad144f45856ba92ed040a00e6b4565903272303d3917d
- kinocut sdist eaa8a1daa460fcf5d08405b971e2902dbf9d2483f9f151141b8bb30d94a56e0d
- shim wheel 12a84fdccbf336bb3e8b34ff92ba3292a2dad9c5f2dd125535f088cfd4491cad
- shim sdist f48dacd217596cc49509c13488f37ed3e10339bef97eaece85a2d501ca73f326

Provider evidence `/tmp/kinocut-provider-audit.json` from root: npm latest1.15.3; GitHub releases/latest1.15.0; MCP Registry403 unknown. Root independently read live kinocut.dev JSON-LD/llms release1.15.3. Docs separate those observations and do not claim every provider is aligned or every site page is visually verified.

Existing cutover script ran dry-run with --version1.15.3 --date2026-09-25 --mcp-tools201 --cli-commands173 --previous-version1.15.2 --keep-dev-ahead, live publication guard enabled. --apply was not used because it also touches package versions/dependencies and other-agent files. Only minimal active documentation references were edited; historical1.15.2 sections and1.8 audit procedure kept intact.

Owned files this iteration: README.md (release/status only; handed back to root for snippet/flags edits), docs/public_claims.json, ROADMAP.md, docs/AI_AGENT_DISCOVERY.md, docs/DIRECTORY_REBRAND_STATUS.md, docs/MCPB.md, mcpb/README.md, docs/RELEASE_1.8_CHECKLIST.md (current overlay only), docs/HUMAN_GATES.md, docs/CLI_REFERENCE.md (one current version label), docs/status/NOW.md, docs/PRODUCT_MATTE.md, docs/README.md, skills/kinocut/SKILL.md (object-matte current version only), tests/test_public_claims.py. Product agent independently owns llms.txt/faq/external-AI audit REPORT; root owns INTEGRATIONS/CHANGELOG/snippets.

Two pre-existing assertions encoded facts contradicted by newly verified publication evidence. Updated README full-notes guard requires exact published-version PyPI URL rather than inventing a GitHub release1.15.3. Site guard now requires live JSON-LD/llms metadata/date plus rendered-page uncertainty and explicit GitHub/MCP drift instead of requiring obsolete production-deployment-pending text. No guards were removed.

Validation: test_public_claims.py **25 passed in .17s**; Ruff passed; scoped git diff --check passed. Global diff check observed unrelated root-owned docs/INTEGRATIONS.md line33 trailing whitespace and root was notified. All edits saved and scope frozen. No commit by this agent.
