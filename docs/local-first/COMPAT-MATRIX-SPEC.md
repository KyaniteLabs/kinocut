# Compat-matrix instrument — DESIGN SPEC (DIR-0003; no build this burst)

Status: design only. This document specifies the three-tier model compat-matrix
runner the local-first hardening program (workstream C) will build. It is the
instrument behind CEO acceptance criterion 1 ("canonical scenario green on all
three matrix tiers, offline-cloud-free, receipts stored").

## Purpose

Answer, with receipts instead of vibes: **can a small/old local model actually
drive kinocut's MCP surface end-to-end, and where exactly does it break?** The
output is a per-tier, per-step pass/fail matrix that the small-driver-profile
work (manifest subsetting, guidance) reacts to.

## Tiers

| Tier | Class | Concrete driver | Host (compute law) |
|---|---|---|---|
| T1 | org heavy | Qwen3.8-27B via org-engines (nucbox Air `:8817` / mini `:8788` OpenAI-compatible endpoint) | nucbox / Mac mini |
| T2 | old 7-8B | Llama-3-8B / Qwen-7B / Mistral-7B (free pulls, owned hardware only — DIR-0010) | Mac mini or G2 |
| T3 | tiny 3-4B | Qwen3-4B-class tiny model, same endpoint shape | Mac mini or G2 |

All tiers expose an OpenAI-compatible `/v1/chat/completions` endpoint; the
harness never embeds a cloud API and sets no cloud env keys (offline-cloud-free
assertion is part of every receipt).

## Canonical scenario (fixed, receipt-bearing at every step)

`ingest → trim → caption (local whisper) → repurpose → quality-gate → receipt`
as defined by the CEO word. Concretely, one scripted input clip drives:

1. **ingest** — `video_ingest`/probe tool: metadata + validation receipt.
2. **trim** — cut on model-chosen boundaries (SAD/EDL semantics): the model must
   emit a valid plan (typed tool args), not free prose.
3. **caption** — local whisper transcription + SRT; model reviews/edits cue
   text only.
4. **repurpose** — 16:9 → 9:16/1:1 re-plan via the repurpose tools
   (`server_tools_ai.py` repurpose family), model-driven plan.
5. **quality-gate** — `assert_quality` / release-review path; model reacts to
   gate findings with a bounded retry (max 1).
6. **receipt** — render receipt + per-step matrix row stored.

## How a model drives the MCP surface (mcp client harness)

- The harness speaks MCP (the same server the `kino` CLI/`mcp_video.py`
  exposes), NOT a bespoke API: every step is a real MCP tool call issued by an
  agent loop wrapping the tier's chat endpoint.
- **Token accounting is first-class**: prompt/completion tokens per step,
  total per run, and tool-manifest bytes sent at handshake. The manifest-size
  question ("does the 196-tool surface overwhelm small drivers?") is answered
  with numbers from this harness, not argued.
- **Determinism**: temperature 0, fixed seeds/prompts, pinned scenario file
  (input clip + expected artifacts hashed). The `kino` CLI is the deterministic
  fallback path: every step also runs once via CLI to produce the
  ground-truth artifact the model-driven run is compared against.
- **Loop budget**: max N tool calls per step (N=5 initially); exceeding budget
  = step FAIL (`driver_loop_exhausted`), not hang.

## Receipt format (per step, per tier)

```json
{
  "tier": "T2", "model": "llama-3-8b", "endpoint": "http://mini:8788/v1",
  "step": "trim", "attempt": 1, "tool_call": "video_trim",
  "tool_args_valid": true,
  "outcome": "pass | fail",
  "fail_reason": "schema_violation | wrong_arg | loop_exhausted | timeout | render_error | null",
  "tokens": {"prompt": 0, "completion": 0, "manifest_bytes": 0},
  "latency_ms": 0,
  "artifact_sha256": "…",
  "ground_truth_diff": "identical | acceptable | divergent",
  "cloud_keys_present": false,
  "timestamp_utc": "…"
}
```

Run-level receipt aggregates the six steps + total tokens/latency. Receipts are
the evidence of record for acceptance criterion 1; store under
`docs/local-first/matrix-runs/<date>-<tier>/` (in-repo, PR-reviewed).

## Pass/fail semantics per step

- **pass** — valid typed tool call, step artifact renders, and artifact matches
  the CLI ground truth within the step's declared tolerance (trim: exact;
  caption: CER threshold; repurpose: plan-validity + render success;
  quality-gate: gate green without retry-loop abuse; receipt: present+hashed).
- **fail** — any of: invalid tool args, loop exhausted, timeout, render error,
  artifact divergent beyond tolerance. `fail_reason` is mandatory on fail
  (honest receipts law).
- **Tier verdict** = AND over steps; the MATRIX (3 tiers × 6 steps) is the
  deliverable, not a single boolean. A T3 failure with a clean fail_reason is
  a USEFUL result — it names exactly where the small-driver profile must
  compensate (manifest subset, guidance text, arg simplification).

## Build order (when the program funds it)

1. Harness skeleton: MCP client + endpoint config + receipt writer (CLI
   ground-truth mode first, no model).
2. T1 wiring (org-engines) — proves the harness against the known-good tier.
3. T2/T3 free pulls on mini/G2 (never the MBA — compute law).
4. Matrix sweep + first small-driver-profile recommendation, numbers attached.

## Constraints

Zero spend (DIR-0010: free pulls + owned hardware only) · heavy runs on
mini/G2, never the MBA · no cloud keys anywhere in the harness · receipts
append-only · guardrail laws (Video Receipts, typed tools, fail-closed
verdicts) untouched — the harness consumes them, never bypasses them.

*KINOCUT-PM design note, 2026-09-18. Build is a separate, Lead-sequenced burst.*
