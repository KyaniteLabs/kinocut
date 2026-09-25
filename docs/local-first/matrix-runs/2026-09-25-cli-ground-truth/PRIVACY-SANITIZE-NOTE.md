# PRIVACY SANITIZATION NOTE — 2026-09-25 (PR #438 defect-fix mission)

The committed artifacts quality-gate.json and repurpose/repurpose_manifest.json
originally embedded ABSOLUTE repo-root paths (leaked the operator home directory;
test_receipt_privacy red: 1 failed / 1817 passed). This note records the honest
evidence-chain change: both files were rewritten to workspace-relative paths
(same targets, prefix stripped). steps.jsonl is append-only and was NOT touched —
its artifact_sha256 entries for the pre-sanitize content remain the record of what
the CLI originally produced:

- quality-gate.json        pre-sanitize sha256: ce791a9f41b3…  post-sanitize: a0bc262d5b0c…
- repurpose_manifest.json  pre-sanitize sha256: 78996e4d46d8…  post-sanitize: 172cb8002176…

Root cause closed in the harness (same commit): matrix_harness.py sanitizes
artifact text at record time (sanitize_artifact_text / sanitize_artifact_tree),
BEFORE receipt hashes are computed, so future runs pin committable content
natively. Regression pin: tests/test_compat_matrix_skeleton.py::test_artifacts_are_workspace_relative.
