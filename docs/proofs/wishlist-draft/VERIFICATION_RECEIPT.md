# Wishlist draft verification receipt

**Receipt state:** G006 closeout checkpoint — merge-ready bounded checkpoint

**Implementation/security-review tip:** `7d16d525121f5bf8e9e427798304e89057844051`

**Hygiene tip:** `47731e9`

**Latest G006 remediation checkpoint:** `7d16d525121f5bf8e9e427798304e89057844051` (reviewed implementation tip); hygiene closeout `47731e9`

**Release state:** prohibited — not release-ready, publish-ready, or deploy-ready

This receipt records the G006 closeout evidence on the reviewed implementation tip
`7d16d525121f5bf8e9e427798304e89057844051` and the hygiene tip `47731e9`. The G006
evidence-integrity blockers are closed; the whole-gate checklist is complete and merge-ready as a
bounded checkpoint. This does **not** authorize release, tag, package, deploy, or announcement.

## Checks recorded by this documentation unit

| Gate | Command | Result |
| --- | --- | --- |
| Markdown diff hygiene | `git diff --check` | pass |
| Public-surface contract | `python3 -m pytest tests/test_public_surface.py -q --tb=short` | pass: 25 tests |
| Canonical import alias | `python3 -c "import kinocut, mcp_video; assert kinocut.Client is mcp_video.Client"` | pass |
| Forbidden artifacts | `python3 .github/scripts/check-forbidden-artifacts.py` | pass |
| Repository readiness | `python3 scripts/repo-readiness-audit.py` | pass with expected uncommitted/unpublished-branch warnings |
| Professional/leak audit | `./scripts/git-professional-audit.sh` | expected pre-push failure: isolated branch has no upstream; integrity and branch checks pass |

The professional audit must be rerun after the publication branch is committed and its upstream is
configured. The current failure is recorded rather than hidden; it is not a content or leak finding.

## Whole-gate evidence on the reviewed implementation tip

The following gates ran on the reviewed implementation tip
`7d16d525121f5bf8e9e427798304e89057844051`:

| Gate | Result |
| --- | --- |
| Full repository suite | `3088 passed, 18 skipped, 8 warnings, 552.04s` |
| Architecture focused suite | `279 passed` — APPROVE |
| Security focused suite | `102 + 57 passed` — CLEAR |
| Body-swap focused tests | `22` (not 24) |
| Ruff | pass |
| Canonical and compatibility imports | pass |
| Diff hygiene | pass |
| Forbidden tracked artifacts | pass |
| Repository readiness | pass with expected uncommitted/unpublished-branch warnings |
| Gitleaks working-tree scan | pass; no leaks found |
| Public documentation metadata scan | pass |

The import/diff/forbidden/readiness/leak gates are recorded as pass on the reviewed tip. The
repository-readiness warnings are expected for an unmerged feature branch and are not content or
leak findings.

## G006 remediation checkpoint — closed

The G006 evidence-integrity blockers are closed on `codex/niko-close-open-loops`. The four
remediation commits in integration order:

1. `c80c579` — `trim_audio` proof binds output audio to a bounded prefix of the approved source.
2. `a3b51fc` — region-crop, still-frame, and full freeze-prefix/tail/extension origin checks bind
   the entire salvage frame range to the descriptor. `BACKGROUND_ONLY` uses the existing 3-frame
   `_crop_origin_check` (start/mid/end), noted as a defense-in-depth limitation — only three
   representative frames are verified, not every frame — without reopening the scoped G006 blocker.
3. `345c2dc` — `mutation_fingerprint` and `authorization_decision_ids` persisted in v2
   salvage-lineage manifest; replay rejects tampered, stale, or superseded authorization.
4. `7d16d52` — salvage authorization resolver unified with the protection gate so `target_ref`
   binding is enforced identically on initial render and lineage replay.

### Exact-tip gates on `7d16d525121f5bf8e9e427798304e89057844051`

| Gate | Result |
| --- | --- |
| Architecture focused suite | `279 passed` — APPROVE |
| Security focused suite | `102 + 57 passed` — CLEAR |
| Body-swap focused tests | `22` (not 24) |
| Whole repository suite | `3088 passed, 18 skipped, 8 warnings, 552.04s` |
| Ruff | pass |
| Canonical and compatibility imports | pass |
| Diff hygiene | pass |
| Forbidden tracked artifacts | pass |
| Repository readiness | pass with expected uncommitted/unpublished-branch warnings |
| Gitleaks working-tree scan | pass; no leaks found |

The architecture review is APPROVE. The security review is CLEAR. All three original blockers
(freeze-prefix/region-crop/still-frame origin, `trim_audio` approved-source proof, and persisted
mutation/authorization evidence in salvage lineage) are resolved. The whole repository suite ran to
completion on the reviewed implementation tip.

This is a merge-ready bounded checkpoint for Wave 3. It is **not** release-ready, publish-ready, or
deploy-ready. The stop-before-release gate remains in force: no tag, package, deploy, announcement,
or release creation. Human visual/audio review of generated media is a separate required decision.

## Whole-gate checklist — complete on reviewed tip

The following gates ran on the reviewed implementation tip
`7d16d525121f5bf8e9e427798304e89057844051` and are recorded above:

- [x] Full repository suite — `3088 passed, 18 skipped, 8 warnings, 552.04s`
- [x] Architecture focused suite — `279 passed` — APPROVE
- [x] Security focused suite — `102 + 57 passed` — CLEAR
- [x] Canonical and compatibility imports — pass
- [x] Diff hygiene — pass
- [x] Forbidden tracked artifacts — pass
- [x] Repository readiness — pass with expected branch warnings
- [x] Gitleaks working-tree scan — pass; no leaks found

The whole-gate checklist is complete and merge-ready as a bounded checkpoint. The publication
controller must still rerun the full gate on any future publication commit and report the result;
this receipt must not be represented as proof for a different tree.

## Human review gate

No automated receipt makes generated media publishable. Release artifacts still require explicit
human visual and audio review bound to their exact hashes. This repository-level receipt also does
not authorize a release action. The stop-before-release gate remains in force: no tag, package,
deploy, announcement, or release creation until explicit release authority is granted.
