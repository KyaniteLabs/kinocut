# Release retro — what the 1.15.1 cut taught us (2026-08-31)

> Written after completing the 1.15.1 version-constellation sweep retroactively
> (PR #472) and a docs staleness audit. The lessons are process rules now.

## What happened

v1.15.1 published 2026-08-31T04:08Z with most of its version sweep skipped.
Clean-master CI was red at publish time: the distribution test's hardcoded
`KINOCUT_VERSION`/`SHIM_VERSION` constants, the entire claims-enforced docs
surface (public_claims.json, README, ROADMAP, llms.txt, MCPB docs,
DIRECTORY_REBRAND_STATUS, RELEASE_1.8_CHECKLIST), and the npm uvx launcher
pin all still said 1.15.0/1.6.11. Master lint was also red (six unformatted
files from the #414 merge). All completed by PR #472.

## Rules

1. **The claims tests are the sweep guide.** `pytest tests/test_public_claims.py
   tests/test_kinocut_distribution.py` walks every version-bearing surface; a
   release is not cut until they pass **in a CI-like environment** (with Node
   available). Locally, the npm/mcpb tests fail confusingly on Node-version
   grounds and can mask real failures — one such failure (the npm launcher
   pin) was misread as environment noise until CI caught it.
2. **`ruff format --check kinocut/ tests/` gates every merge, not just
   releases.** Direct-to-master landings skipped it twice (six files, #414-era).
3. **A release commit must include the CHANGELOG section in the same cut** —
   1.15.1 shipped without one (added by PR #470 alongside the backfilled
   #458/#459 contributor credits).
4. **Credits are release-blocking.** #458/#459 shipped in 1.15.0 uncredited
   because acknowledgement lived in a draft release's living context instead
   of the CHANGELOG; the draft was later deleted and the credit with it.
   Contributor acknowledgements belong in the CHANGELOG section at cut time.

## Related

- Version sweep checklist: `docs/RELEASE_1.8_CHECKLIST.md` (claims-enforced).
- Contributor credit backfills: PRs #470/#471. Sweep completion: PR #472.
