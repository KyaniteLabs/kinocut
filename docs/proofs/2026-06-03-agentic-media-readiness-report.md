# Agentic Media Workflow Readiness Report - 2026-06-03

## BLUF

mcp-video is ready to be positioned as a trust layer for agentic video workflows, not as a generic AI video platform.

The strongest current wedge is a receipt-backed workflow: generate or accept source media, transform it into a checked vertical clip, create quality/review artifacts, and leave human review pending.

## What Is Proven

| Readiness Area | Current Evidence | Status |
| --- | --- | --- |
| Fresh install | `uvx --from mcp-video mcp-video doctor --json` ran from `/tmp` with required dependencies passing | Proven |
| Basic edit chain | Generated source was trimmed, captioned, resized, and exported | Proven |
| Quality guardrail | Ad hoc path surfaced quiet-audio warning instead of hiding it | Proven |
| Workflow correction | Staged workflow normalized audio and passed quality checks | Proven |
| Release checkpoint | Thumbnail, storyboard, and review instructions were created | Proven |
| Video Receipt | `05-confidence-baseline` writes `output/video_receipt.json` | Proven locally |
| Public repo health | Current CI and integration smoke are green; several open issues are stale pipeline/dashboard residue | Needs cleanup, not product-blocking |

## Current Buyer Story

Technical teams can use mcp-video when they want AI agents to run repeatable media workflows without inventing fragile FFmpeg commands. The product value is not "AI makes a video." The product value is "agents can inspect, edit, verify, and hand off video work with receipts."

## Remaining Risks

| Risk | Why It Matters | Recommended Next Step |
| --- | --- | --- |
| Optional dependency friction | Fresh minimal install works, but advanced AI/audio/image workflows need optional packages | Keep optional capabilities clearly gated in `doctor` and docs. |
| Local project resolver surprise | `uv run --with mcp-video` inside the repo can resolve the local project and hit `audio-all`/`meltysynth` friction | Prefer `uv run --no-project --with mcp-video` for published-package proof commands until metadata is adjusted. |
| Public issue noise | Stale issues make the repo look less healthy than it is | Close/comment stale issues with dated evidence; keep one Dependabot issue open. |
| Human review still manual | Automated quality checks do not prove creative taste or brand fit | Keep human review required in receipts and release checkpoints. |
| External proof missing | No outside install feedback has been captured in this proof set | Send the feedback ask and convert responses into fixes or proof notes. |

## Certification Path

The next credible offer is `agentic-video-certify`:

1. Run the confidence baseline.
2. Run adversarial fixtures for media edge cases.
3. Produce a readiness report with pass/fail, quality warnings, output paths, and human-review status.
4. Deliver a reusable workflow handoff for the team's agent host.

## First External Pilot Shape

Offer:

```text
I will install mcp-video in your agent environment, run one receipt-backed workflow, and hand you a short readiness report showing what passed, what broke, and what needs human review before publishing.
```

Acceptance criteria:

- One clean install attempt recorded.
- One workflow receipt produced or one blocker documented.
- One actionable fix, docs patch, testimonial-style quote, or pilot invite captured.

## Verdict

mcp-video is strong enough to be the application wedge. The work now is not more capability. It is making the trust path visible, repeatable, and testable by someone other than Simon.
