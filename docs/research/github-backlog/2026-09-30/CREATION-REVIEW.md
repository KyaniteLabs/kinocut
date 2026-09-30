# Local creation / temporal / Hyperframes issue adaptations

Reviewed bodies: `/tmp/kinocut-gh-review/issues-581.md`, `issues-583.md`, `issues-585.md`.
No remote writes, commits, model calls, model downloads, publication, or version bump.

## #581 — fixed generic prompt intent preservation

`kinocut/creation_engine.py` now returns camera/lens and includes nonempty values explicitly as `Camera:` / `Lens:` sections before action + expanded STYLE bodies. Camera-only/lens-only changes survive independently. Provider/model labels remain labels: `prompt_dialect=generic`, `model_dialect_compiled=false`; there is no model-specific compiler or provider generation.

Exact STYLE_/NEG_ headings remain accepted. One nonempty parenthesized annotation, e.g. `## STYLE_TEST (lane: example)`, is accepted without contaminating the body. Unsupported/malformed declared block headings, empty annotations, and duplicate block declarations raise a structured validation error. A normal nonblock `##` heading ends the previous body. Missing referenced blocks still fail.

Tests: existing creation engine plus new `tests/test_creation_prompt_contracts.py` camera-only/lens-only, heading annotation/malformed/duplicate/empty, body-boundary, missing block, and honest dialect metadata controls. No provider required.

Docs requirement: describe generic camera/lens inclusion, one nonempty parenthesized heading annotation, precise validation failures, provider/model passthrough and absent model-dialect compilation. Product agent owns docs/CHANGELOG.

## #583 — implemented bounded chronological image-change QA; broader semantic coherence remains unassessed

New `kinocut/aivideo/inspection/motion_coherence.py` consumes the existing temporal decoder's chronological `TemporalFrameObservation` sequence; it adds no decoder, learned model, provider call, or image sampling pass. Public `video-inspect-temporal` returns additive `motion_coherence`, also included in the existing persisted frame-difference measurement artifact.

Method: time-weighted one-second windows of mean absolute 16×16 grayscale image difference per second. This is a luma-change proxy, NOT optical flow, physical velocity/acceleration, semantic chronology, story continuity, artistic coherence, or a validated film quality score. Windows expose exact measured support. Adjacent-window ratio AND absolute-delta thresholds flag advisory rate lurches; consecutive high-rate windows flag sustained high image change; calm followed by high flags a separate interval. Defaults are named in defaults.py and exposed in the report, but are heuristic starting points requiring project calibration. Deliberate calm stays valid. Steady purposeful low/medium image change remains clear. Isolated large frame differences are reported separately as `isolated_transition_candidate` with `intent_assessed=false`; cuts/flash/physical movement cannot be distinguished conclusively by this metric.

Coverage: observed first/last timestamps, frame count, measured interval duration, decoded media extent and expected end are visible. Intervals above the existing cadence-gap multiplier are excluded from difference-rate coverage, never interpolated. Existing >18000-frame budget rejects rather than silently truncating; report exposes this policy. Direct injected observations say unbound/provided-observations-only. Local-media inspection binds actual source SHA256 and rejects source identity/size/mtime/ctime changes during inspection. One full-file hash read is added for source binding; image decoding infrastructure is reused. No human viewing is invented: `human_viewing_status=not_recorded`, `complete_human_viewing_required=true`, `acceptance=not_granted` regardless of findings.

Tests: `tests/test_motion_coherence.py` calm, steady, repeated abrupt changes, sustained high, calm-to-high, isolated cut candidate, order/FPS invariance, coverage gap, real media hash/decoded coverage/budget disclosure. Existing temporal checks and inspection surface tests preserve all previous defect policies.

Docs requirement: position this as bounded chronological image-change QA within existing temporal inspection, list units/default thresholds/coverage/budget, isolated-transition uncertainty, required human full-watch, and semantic/artistic/physical-motion limitations. Do NOT market as proven whole-film semantic coherence, a universal score, or full-length streaming analysis beyond existing frame budget. Product agent owns docs/CHANGELOG.

## #585 — fixed requested artifact path contract

`kinocut/hyperframes_ops.py::render` resolves requested relative outputs against caller working directory, validates and passes the same absolute path to Hyperframes and final artifact existence/size checks. Default out paths become absolute using that base. Absolute requests keep their base.

`still` validates a requested caller-relative destination before the snapshot call; after actual generated-file verification, it atomically copies the PNG into that destination. Repeated snapshot directory reuse cannot replace that separate requested copy. A request matching the generated path retains that explicit path, and default stills remain snapshot artifacts. Still format remains the upstream PNG; no transcoder is introduced. Missing snapshots raise structured HyperframesRenderError; copy failure raises the same bounded error type.

Render API preserves existing success=false response when expected artifact is absent. CLI handler prints that same JSON then exits 1 so process status agrees; successful actual artifact returns size metadata. Existing PNG sequence behavior preserved.

Tests: `tests/test_hyperframes_output_contracts.py` relative/absolute render caller cwd distinct from project cwd, exact child/result path and file, repeated durable stills, missing still error, false render JSON/nonzero CLI exit. Existing still tests updated to assert requested copies and truthful presence.

Docs requirement: document caller-cwd base for render/still relative -o, durable PNG copies when requested, default snapshot mutability, and nonzero artifact-failure CLI status. Product agent owns docs/CHANGELOG.

## Validation

First combined focused run: 174 passed, 2 optional Hyperframes integration skipped, 26.34 seconds.
Ruff: all changed implementation/test files passed.
Expanded final regression run (CLI handlers + Hyperframes client contracts added) in progress at note creation; parent will run final required complete suite.

Final expanded focused regression: **211 passed, 2 skipped in 25.66s**. Includes all new controls, existing creation/temporal/inspection/Hyperframes tests, Hyperframes client contracts, and CLI handler regressions. Optional upstream integration skips are unchanged. Ruff all changed implementation/tests passed; canonical kinocut/mcp_video Client compatibility import passed; all changed modules <800 LOC and functions <=80 lines. Code frozen; parent owns final complete-suite gate.
