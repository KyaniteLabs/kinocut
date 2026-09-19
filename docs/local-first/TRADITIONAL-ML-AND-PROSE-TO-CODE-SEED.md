# Traditional-ML + prose→code seed lists (workstreams A & B)

Seed lists, NOT exhaustive audits — each row names the candidate and the
enforcement/conversion it implies; the full passes (per CEO acceptance criteria
3-4) verify, implement, and number these. File references at commit `e593881`.

## Part A — traditional-ML conversion candidates (workstream A)

Goal state per CEO word: core editing + QC workflows run FULLY local, zero
model calls; AI extras become optional accelerators, never dependencies.

| # | Analyzer (current) | Today | Classical replacement candidate | Feasibility |
|---|---|---|---|---|
| A1 | Scene detection `kinocut/ai_engine/scene.py` | ffmpeg `select` filtergraph (already classical) | verify + pin: histogram/edge/frame-diff variants exposed as explicit `method=` options with quality receipts per method | already there — pin + receipt |
| A2 | Silence/VAD `kinocut/ai_engine/silence.py` | ffmpeg `silencedetect` (energy-based, already classical) | energy-threshold receipts (dBFS + duration) vs a librosa/energy cross-check on the same fixtures | already there — cross-check + pin |
| A3 | Color analysis `kinocut/ai_engine/color.py` | ffmpeg/ffprobe signal stats (classical) | histogram/moments (mean/var/skew per channel) receipts | already there — extend metrics |
| A4 | Aesthetic scoring `kinocut/aesthetic/` (NIMA, torch) | neural, local | classical QC bundle: Laplacian-variance sharpness, exposure/clipping histograms, contrast metrics, edge density — as `method=classical` alongside NIMA; quality receipts comparing both where both exist | feasible — build |
| A5 | Smart thumbnail `kinocut/aesthetic/smart_thumbnail.py` | NIMA with deterministic fallback (`_default_timestamp`) | rank candidates by the A4 classical bundle when NIMA absent — replace "midpoint fallback" with "classical-ranked fallback" (still honest about which ran) | feasible — build |
| A6 | Upscale `kinocut/ai_engine/upscale.py` (FSRCNN/OpenCV DNN) | neural, local weights | classical scaler path: ffmpeg `scale=lanczos` (and `sws_flags`) as an explicit `method=classical` option; receipts compare sharpness/PSNR vs FSRCNN | feasible — build |
| A7 | Spatial checks `kinocut/ai_engine/spatial.py` | classical (ffmpeg geometry) | verify + pin | already there |
| A8 | Object matte `kinocut/object_matte/` | neural, local weights | partial: color-key/background-subtraction for the subset of inputs it fits; document the boundary for the rest | partial — boundary doc required |
| A9 | Image description `kinocut/image_engine.py` (Claude Vision) | cloud, opt-in | already has local default (structural/EXIF); classical frame-stats summary as the receipt-bearing offline description | already there (default) — pin |
| A10 | ASR (whisper) `ai_engine/transcribe.py` | neural, local library | **honesty boundary: no classical ASR exists** — caption stays a local-model extra; the receipt must say `model: whisper-<size>` and the pipeline must never hard-require it (fail-closed already) | boundary — document, don't fake |
| A11 | Stem separation (demucs) `ai_engine/stem.py` | neural, local | **honesty boundary: classical source separation is not feasible** — stays a model extra with duration caps | boundary — document |

Core-workflow claim to prove (acceptance 3): ingest → trim → caption-optional →
repurpose → quality-gate → receipt with **model calls = 0**, receipt-stamped.
A1-A3, A7 are already classical; A4-A6 add the classical lane; A10-A11 carry
explicit why-not lines.

## Part B — load-bearing prose → code enforcement (workstream B)

Every prose rule enforced only by reading becomes a failing test, a guarded
command, or a CI gate; what cannot be coded gets an explicit why-not line.

| # | Prose source | Load-bearing rule | Enforcement it implies | Status today |
|---|---|---|---|---|
| B1 | `docs/AI_VIDEO_REVIEW_AND_SALVAGE.md` | the safe operating sequence (inspect → salvage → verify, no skips) | a guided runner: one `kino` command that walks the sequence and REFUSES skips (state machine over `aivideo/salvage*` + `review.py`); contract tests pin refusal cases | salvage engine exists; the no-skip sequence-enforcer is the gap |
| B2 | `PLAN-video-guardrails.md` | typed tools, no invented ffmpeg flags, fail-closed verdicts, Video Receipts | these are already largely coded (typed tool registry, receipt contracts, `verdict.py`); remaining prose lines → named tests (the "claim-gate pattern") | mostly coded — gap-list the untested prose lines |
| B3 | `SECURITY.md` | secret hygiene + dependency posture | CI gates: **secret-scan + dep-audit landed this burst** (`.forgejo/workflows/ci.yml`, card F5); remaining SECURITY.md claims → contract tests | first gates LANDED 2026-09-18; claims-tests follow |
| B4 | `README.md` claims | published surface/version claims | extend the existing claims-oracle (`scripts/verify_published_claims_live.py` + `docs/public_claims.json`) into a pinned contract test for every checkable claim | oracle exists, one known red (GitHub release tag, CEO-gated) |
| B5 | `ROADMAP.md` | promises with dates/status | each promise tagged `shipped / planned / exploratory`; shipped rows must have a claim-gate row or link to tests; exploratory rows cannot claim shipped behavior | seed conversion |
| B6 | `GOVERNANCE.md` | merge/land policy (Forgejo-first, CI-gated, mirror sync) | contract tests: workflow guards (pattern exists in `tests/test_forgejo_workflows.py`, `test_public_surface.py::test_forgejo_is_a_ci_gated_fast_forward_downstream`); extend to unenforced governance lines | partially coded — extend |
| B7 | `CONTRIBUTING.md` | function-size law, lint rules, commit conventions | 80-line law + ruff already CI-enforced; commit-secret hygiene enforced by the fleet pre-commit hook + now the repo secret-scan gate; remaining prose (commit message shape) → why-not or checker | mostly coded |
| B8 | `docs/faq.md`, `docs/status/USER_PROGRAM_RUNBOOK.md` | version references | drift-check test against `public_claims.json` (known stale rows already identified at the desk) | gap — fold into B4 fix PR |

Why-not ledger (started): none yet — every row above has a codeable
enforcement; honesty lines land when a full-pass row proves otherwise.

*KINOCUT-PM seed pass, 2026-09-18. Full A/B passes are Lead-sequenced bursts
with numbers per CEO acceptance criteria 3-4.*
