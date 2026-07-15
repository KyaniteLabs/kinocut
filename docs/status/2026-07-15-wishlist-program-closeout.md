# Kinocut remaining-wishlist program — closeout (2026-07-15)

**Canonical master:** `bc39321` (PR #159 — public surfaces). **Prior:** `881c5dd` (PR #156 wishlist engines), `a05b02e` (1.8.0). **No release action taken.**

## BLUF

Implementation is **100% complete and on master**. Twenty-three wishlist nodes shipped via PR #156 (`881c5dd`), CI-green (`lint`, `test`, `test-ffmpeg-matrix` 6/7/8). PR #155 (bounded positioned blends) merged separately and is included. Every named wishlist occurrence has exactly one normalized disposition; nothing is dangling.

**Follow-on (PR #159, `bc39321`, same day):** the 8 highest-value engines from #156 now also have public **MCP + CLI + client** surfaces (`video_review_package`, `video_publish_gate`, `video_review_decision`, `video_learning_report`, `video_cost_ledger`, `video_recipe_capture`, `video_capabilities`, `video_benchmark_run`). The published-1.8.0 count-parity invariant was deliberately broken and re-synced to **150 MCP tools / 129 CLI commands** (3 count tests + 6 doc claims + the `CLIENT_METHOD_CONTRACTS` client registry + the `server.py` thin-facade line cap). The program is implementation-complete and release-ready; the **release gate (1.9.0) remains the explicit human-authorized next step.**

## What shipped this program (PR #156, merge `881c5dd`)

| Area | Items |
|---|---|
| Learning | #40 prompt-outcome, #57 learning-report, #59 recipe-capture, #60 cost-ledger, #44 regeneration-advice, #58 defect-to-prompt-feedback |
| Review/decision | #48 review-decisions, #49 publish-gate, #50 known-limitation-ledger, #51 approval-invalidation, #47 review-package |
| Asset/editorial | #39 duplicate-detection, #42 beat-map, #43 coverage-report, #45 continuity-plan, #19 continuity-assistant |
| Capability/CLI | #54 capability-report, #55 next-action, #56 doctor-migrations, #53 agent-mode output (`--format auto`), #52 namespace resolver |
| Audio | #24 bed-audition (labeled per-section beds) |

All are internal record/query engines or additive opt-in surfaces. At PR #156 the public surface stayed at **142 MCP / 121 CLI** (matching published 1.8.0). **PR #159 then exposed 8 of them publicly → 150 MCP / 129 CLI**, with every parity invariant re-synced.

## Verification

- **CI on master `881c5dd`:** `lint` ✓, `test` ✓, `test-ffmpeg-matrix` (FFmpeg 6/7/8) ✓ all green.
- **New focused tests:** 114+ across the shipped nodes, all RED→GREEN.
- **Sound acceptance (s15):** 572 sound tests pass (authorization/hardening/runtime/consent/S3/joins/benchmark/public + S15 stop-gate).
- **Ruff + architecture guardrails:** clean.

## Typed exclusions (deliberately not in this merge — not dangling)

- **#52 public namespace surface** — the resolver layer shipped; the public `kino aivideo <action>` surface was reverted because it broke published-1.8.0 command-count parity (121). Follow-on PR must sync README badge, ROADMAP, and llms.txt claims (dev tip diverges from 1.8.0 by +1).
- **#21 / #22 / k1 (protected-timeline kernel)** — blocked behind the named external kernel contract + explicit human gate. No substitute kernel.
- **Optional (structured logging, video-edit shortcut)** — not promoted; excluded unless explicitly requested.
- **#35b positioned-blend** — shipped via PR #155 (external), included in this base.

## Remaining human/external gates (not code)

- **Independent adversarial review** of the integrated unit (s15/SV3) — automated verification is green; a genuinely independent reviewer is a separate role.
- **Release authorization** — version bump, tag, PyPI/npm upload, registry submission, deploy, and announcement remain prohibited until explicitly authorized. The program stops here.

## Program provenance

- Reconciliation ledger + resource-constrained schedule: this program's planning artifacts live in `.omx/` (local; gitignored by design). This status page is the durable, repo-resident summary.
- R0 reconciliation: 91 wishlist occurrences → 80 shipped, 3 retired (duplicates), 3 deferred, 2 blocked, 3 remaining (s15 gate + 2 optional).
