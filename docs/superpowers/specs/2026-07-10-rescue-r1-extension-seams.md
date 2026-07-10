# Rescue R1 Extension Seams

**Status:** Approved for implementation

## Decision

R1 is an additive `mcp_video.rescue.r1` contract layer. It wraps, but never extends,
the strict rescue v1 plan and receipt models. Existing rescue JSON bytes, hashes,
policy decisions, verifier order, and rendering behavior remain unchanged.

## Contracts

- Versioned policy profiles declare timeline, crop, synthesis, network, and source
  overwrite permissions. `local_content_preserving@1` is immutable.
- An intent envelope binds a feature payload and policy reference to an unchanged
  `RescuePlan`. Its digest is independent of `plan_sha256`.
- Feature verifiers may be appended to the mandatory rescue verifier sequence. They
  cannot replace or suppress a mandatory check.
- Executor and model capabilities are additive metadata only. Discovery never
  installs, downloads, or substitutes an implementation.
- Preview diffs are deterministic. Approval binds the exact base plan digest,
  ordered action IDs, and preview diff digest.

## Acceptance

A synthetic `toy_visual_crop@1` profile carries a crop-track payload and adds the
`toy_crop_bounds` verifier. Creating that extension must leave the nested rescue
plan's serialized bytes and canonical digest unchanged, preserve every mandatory
rescue verifier, and produce stable preview and approval digests.
