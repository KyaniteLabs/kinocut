# Post-Rescue Surface Parity

> **Historical implementation record:** This document describes the MCP Video
> 1.6.0 layout as shipped. The project is now Kinocut; its former names and paths
> remain here as release evidence, not current integration guidance.

**Status:** Implemented for MCP Video 1.6.0. Verification is recorded in the
[release receipt](../../proofs/release-1.6.0/RESCUE_POST_RESCUE_RECEIPT.md).

## Decision

The post-rescue capabilities ship as planning, retrieval, verification, and explicit
adapter surfaces before any new renderer is permitted. MCP, CLI, and Python expose the
same eight capability families:

1. semantic timeline construction;
2. source-backed semantic query;
3. timeline edit planning;
4. visual transform planning;
5. restorative planning;
6. composition planning;
7. creative autopilot planning;
8. remote egress planning.

Each call accepts JSON-compatible evidence or a JSON artifact path, validates it through
strict versioned models, and returns a serializable plan or verification result. Planning
does not mutate media, install or download dependencies, contact a provider, or silently
substitute an executor.

## Naming

| Capability | MCP / Python | CLI |
|---|---|---|
| Semantic timeline | `video_semantic_timeline` / `semantic_timeline` | `semantic-timeline` |
| Semantic query | `video_semantic_query` / `semantic_query` | `semantic-query` |
| Timeline edit | `video_timeline_edit_plan` / `timeline_edit_plan` | `timeline-edit-plan` |
| Visual transform | `video_visual_transform_plan` / `visual_transform_plan` | `visual-transform-plan` |
| Restoration | `video_restoration_plan` / `restoration_plan` | `restoration-plan` |
| Composition | `video_composition_plan` / `composition_plan` | `composition-plan` |
| Creative autopilot | `video_creative_autopilot_plan` / `creative_autopilot_plan` | `creative-autopilot-plan` |
| Remote egress | `video_remote_egress_plan` / `remote_egress_plan` | `remote-egress-plan` |

## Guardrails

- Versioned plan and receipt contracts carry their applicable source hashes, capability or
  policy assumptions, confidence or abstention state, gating checks, and canonical digest.
  Retrieval responses retain source span IDs and times without pretending to be policies.
- Query results cite stable source span IDs and source times. Generated descriptions never
  become source truth.
- Timeline, crop, restoration, composition, and network permissions stay separate.
- Approval is a distinct artifact bound to the exact plan digest and ordered action IDs.
- Remote planning stops before submission. Provider execution requires a separately
  approved egress manifest and adapter call.
- Existing direct editing commands remain compatible and are never selected as an implicit
  fallback by these planning surfaces.
