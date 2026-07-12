# Kinocut `kinocut_sound` — Sonic World Audio-Play Production Design

**Status:** Proposed / review-ready design expanding goal `G016-implement-first-class-sound-design-a`
("Implement first-class Sound Design and Sound Mixing") to cover the full
`SONIC-WORLD-WISHLIST.md` capability set.

**Scope:** Design one standalone-capable, in-repository `kinocut_sound` deep module
that turns a generated Witnessed Fate episode JSON into a production-quality audio play:
distinct per-character voices, a repeatable restoration/spatial post chain, script-to-audio
assembly, ambient world-building, voice consistency, and deterministic QA — all local-first,
CLI-first, and MCP-exposable, with cloud providers strictly optional.

**Current sizing evidence:** The design remains decomposed into the 15 bounded leaves below. For the
corrected expanded full-program DAG, the latest installed/published Epoch 0.2.0 receipt
`c183364c-b9e1-4245-a64e-c3972d56a81d` identifies **231.16 productive hours** on the
pre-human-gate dependency path; one-worker total effort is **373.74 hours**. The zero-slack chain is
`Task6→B22→B23→V2→C31→D41→L1→L2→L3→(L5 and L7 join)→L9→L11→L12→L13→L14→L15→H81→H82→V8→J101→J102→V10`;
optional B24 has 26.97 days of slack. A 100,000-trial **fixed-chain sensitivity**, not a
resource-constrained full-DAG confidence forecast, produced pre-gate P10 217.84h, P50 236.35h,
P80 249.04h, and P95 261.12h (`38d80358-c110-41ff-bbcd-c96919ce71ee`). Conditional engineering
after explicit human release authorization produced P10 246.08h, P50 266.01h, P80 279.44h, and
P95 292.48h (`a2ed2450-9aaf-40bb-b295-c40d64ee904b`); its deterministic conditional expected
effort is 258.50h = 231.16h + 27.34h. Human authorization wait is unbounded and excluded from all
elapsed figures. No percentile or deterministic effort figure is an authoritative multi-worker
calendar commitment without a resource-constrained model. The corrected DAG must be rerun with the
latest installed and registry-published Epoch before any figures are cited after a dependency or
duration change; every story likewise requires a latest-Epoch estimate before work and an actual
duration receipt afterward.

This document authors design only. It edits no source, tests, or git history.
Implementation of any story below remains gated on separate approval and stops
before release, matching the standing G016 "stop before release" constraint.

## Outcome

A caller can run one command against a Witnessed Fate episode JSON and receive a finished,
loudness-compliant, stems-separated audio-play episode plus a receipt and QA report — with no
raw FFmpeg workaround required for voice generation, restoration, spatialization, assembly,
ambience, or delivery. Every intermediate capability (a single voice, a single processed clip,
one ambient bed, one QA check) is independently invocable via Python, flat CLI, namespaced CLI,
and MCP. The module preserves the existing D41 bed/audition and D42 voice-metric ownership,
runs core render/assembly/QC locally and deterministically, and never selects a cloud provider
or downloads a model implicitly.

## Architecture Decision (preserved, not re-litigated)

The consensus architecture for G016 is preserved exactly:

- **Same repository and package lifecycle initially.** `kinocut_sound` ships inside the Kinocut
  repository and package. No separate repository, no daemon, and no independent release cadence
  are created by this design. A later extraction is a named non-goal with explicit criteria
  (see *Packaging and Extraction Criteria*).
- **Independent Python and CLI operation.** The module runs fully standalone from Python and
  from the command line without Kinocut's video surfaces loaded. Kinocut, Witnessed Fate, and
  MCP are *adapters over* the module, not prerequisites for it.
- **Kinocut and Witnessed Fate adapters.** Kinocut integration wraps the primitives; the
  Witnessed Fate adapter maps episode JSON onto the SoundPlan contract.
- **No daemon, no separate repo yet.** Batch throughput is achieved with a local process pool,
  not a resident service.
- **Sidecar-capable means hostable, not independently deployed.** Kinocut may invoke the standalone
  Python/CLI module through its typed M7 adapter as a bounded child process, but there is no socket
  daemon, dynamic code loading, separate package, or separate release authority.

The module is a set of deep modules behind small interfaces: each stage exposes a narrow typed
contract and hides its DSP, provider, and file-layout complexity. Nothing in a stage's public
surface leaks FFmpeg filter strings, provider SDK types, model file paths, or absolute source
locations.

## Reconciled Conflicts (authoritative rulings)

The wishlist and prior surfaces contain apparent conflicts. Each is reconciled here and these
rulings govern the requirement matrix.

1. **"Plugin architecture" means typed, allowlisted adapter registration** for TTS engines,
   processors, spatializers, asset search/generation, and analyzers — registered by name against
   a typed capability interface. It is **not** arbitrary VST/AU/LV2 hosting nor loading of
   executables or shared libraries. Registration is data-declared and capability-gated; an
   unknown or unlisted adapter is a validation error, never a dynamic load.
2. **Core render, assembly, and QC are local and deterministic.** Cloud providers (ElevenLabs,
   Stable Audio, Adobe Podcast, Auphonic, etc.) are optional, explicit, capability-gated, and
   disclose cost, data-retention, and region before use. A cloud provider is never selected
   silently; absence of a local capability yields an explicit unavailable result, not an
   implicit remote call.
3. **Voice cloning and blending require explicit subject authorization.** Every clone/blend
   requires a recorded consent/right-to-clone grant with reference and transcript provenance,
   intended-use scope, revocation support, an audit trail, and watermark/provenance stamping
   where the provider supports it. Authorization is **fail-closed at every protected lifecycle
   boundary**, not only export: a generated asset whose lineage traces to a missing, expired, or
   revoked grant cannot be ingested, transmitted, generated, reused, assembled, committed, or
   exported. There is no unauthorized impersonation workflow.
4. **Witnessed Fate's narrator is text-only and stays that way.** Per DECISIONS.md D2, the WF
   narrator seat is a text chapter card with no voiceover. The general `kinocut_sound` tool may
   synthesize narration for other projects by routing narration through an explicit narrator
   `VoiceProfile`; the acceptance fixture uses the named medium-room spatial preset. The **WF adapter
   must not invent narrator voiceover** — it emits chapter-card structural metadata, never a
   narrator TTS line.
5. **Loudness defaults and named presets.** The new SoundPlan default is **-14 LUFS ±1 LU,
   -1 dBTP**. Named delivery presets provide **-16 LUFS podcast**, **-23 LUFS EBU R128**,
   **-24 LKFS ATSC A/85**, and the -14 streaming target. The legacy `wf-voice-process.sh`
   values (-16 default, TP -1.5) are materialized by a compatibility adapter, not by changing
   the new default.
6. **`wf-voice-process.sh` is characterization evidence, not a complete post chain.** It uses
   `aecho` algorithmic echo (not convolution IR), suppresses stderr (`2>/dev/null`), and hard-codes
   a single filter graph. It documents the *intended* denoise→de-ess→EQ→compress→space→loudness
   order and is preserved as a golden-reference fixture, but the post chain requires real
   convolution IR reverb and surfaced, bounded errors.
7. **SoundPlan duration is authoritative.** Assembly never terminates on the shortest stream.
   Every rendered episode preserves declared outro/tail; a post-render probe proves output
   duration matches the SoundPlan timeline within tolerance, and a mismatch is a processing
   failure, not a warning. This directly reuses the field-wishlist `keep_video`/duration-verify
   discipline for the audio timeline.
8. **The 30-minute full-episode target is a hard acceptance gate.** A versioned representative
   fixture containing 50–80 clips and fixed required-capability manifest must complete in under
   30 minutes, cold and warm, on each approved benchmark class: an Apple-silicon workstation
   (32 GB+) and a compact x86 Linux host. An unavailable environment yields
   `external_host_unavailable` and leaves S14/S15 incomplete;
   it is never converted into a pass. Advisory capability deferrals are reported, but no required
   stage may be skipped. Host identity and baseline hardware/software fingerprints are captured at
   run time rather than hardcoded.
9. **Broadcast presets remain standards-specific.** `broadcast_ebu_r128` targets -23 LUFS; a
   distinct `broadcast_atsc_a85` preset targets -24 LKFS. Neither is an alias for the other.

## Deep Module Decomposition

Each module is a deep module: a small interface over hidden complexity. Modules communicate only
through typed contracts (SoundPlan, ProfileRef, ConsentGrant, Receipt, CapabilityResult,
QAReport). Modules stay at or below the repository's 800-line/module and 80-line/function limits;
oversized concerns split into focused submodules.

- **M0 — Foundation & Contracts.** Backend-neutral SoundPlan, timeline, mix-policy, routing,
  delivery, render/QC, receipt, and provenance contracts. Its D41/D42 integration points are typed
  ports only; M0–M6 import no Kinocut implementation module. Authorization/lineage, static adapter
  registration, configuration, presets, and render fingerprints are separate focused submodules,
  not one foundation change unit.
- **M1 — Voice Generation & Provider Adapters.** Typed TTS provider adapters; 15+ distinct voice
  roster; zero-shot cloning; voice blending/compositing; per-character prosody; parametric emotion
  direction; pronunciation dictionary; script batch generation.
- **M2 — Post-Processing & Spatial Chain.** FFT and optional neural denoise; de-ess; 5-band
  parametric EQ; dynamics; convolution-IR room spaces; distance simulation; humanization; loudness
  and true-peak; batch processing with per-clip overrides.
- **M3 — Script Parser & Episode Assembly.** Structured screenplay/WF JSON parsing; per-line voice
  and spatial routing; pacing; crossfades; designed silence; ambient beds and ducking; stems; one-
  command episode render honoring authoritative SoundPlan duration.
- **M4 — Ambience & Foley.** Ambient bed generation from text; layer management; seamless looping
  and scene crossfades; Foley triggering at script moments; per-location presets; per-deck sonic
  texture.
- **M5 — Voice Registry & Consistency.** Profile library; consistency/identity checking; A/B
  comparison; drift detection and re-alignment; batch re-generation; cross-character
  distinctiveness.
- **M6 — QA & Metadata.** Loudness/true-peak/LRA compliance; ASR verification; artifact detection;
  spectral analysis; distribution metadata (title, duration, chapter markers, credits, ISRC);
  season batch reports.
- **M7 — Integration & Migration.** Python/CLI/MCP transport adapters; Kinocut adapter; Witnessed
  Fate adapter (text-only narrator preserved); migration from `audio_engine`, `wf-voice-process.sh`,
  and field-wishlist audio surfaces. Existing D41/D42 implementations bind to M0 ports here only.
- **M8 — Acceptance, Performance & Security Gate.** End-to-end episode acceptance; cold/warm
  benchmark; consent/export fail-closed and privacy/security gate; season QA rollup.

## Core Contracts

### SoundPlan (authoritative timeline)

`SoundPlan` is the single source of truth for an episode's audio. It is a validated document,
not a rendering side effect:

- `schema_version`, `plan_kind: "episode"`, project id, and content hash.
- `timeline`: ordered cues, each with cue id, start, duration, kind (`line` | `silence` |
  `foley` | `bed` | `chapter_marker`), and source reference. Duration is authoritative; the
  timeline total defines the required output duration and tail.
- `lines`: character id, text, `ProfileRef`, prosody/emotion parameters, spatial preset,
  pronunciation overrides, and target loudness inheritance.
- `beds` and `layers`: ambient/Foley references with gain, ducking, loop, crossfade, license,
  provenance, and processing-chain references.
- `buses` and `routing`: typed source/track/bus ids, gain, pan law and pan automation, mute/solo
  semantics, send/return routing, ducking sidechains, sample-accurate automation envelopes, and
  latency-compensation policy.
- `format`: typed channel layout, channel order, sample rate, sample format, time base, and allowed
  conversion/dither policy for every input, bus, stem, and master.
- `delivery`: loudness preset (`stream_-14` default, `podcast_-16`, `broadcast_ebu_r128_-23`,
  `broadcast_atsc_a85_-24`), true-peak ceiling, typed stem layout, deterministic stem-recombination
  policy, and metadata fields.
- `provenance`: consent-grant, asset-license, processing-preset, model, prompt-hash, and
  transcript-hash references; raw prompts and transcripts are not embedded in plans or receipts.

Rendering reads a SoundPlan and declares one determinism class: `byte_deterministic` when the full
render fingerprint and container permit byte identity; `signal_equivalent` when decoded PCM must stay
within the configured numeric tolerance; or `non_reproducible` for a provider that cannot replay
exactly. No stage may extend or shorten the timeline implicitly; a shortest-stream mix is prohibited.

### VoiceProfile (versioned)

A named, versioned entity: profile id, version, roster slot, reference clip hash(es), transcript
provenance, prosody/emotion defaults, processing-chain preset ref, spatial preset ref, spectral
fingerprint (for consistency/distinctiveness), consent grant ref (for cloned/blended profiles),
and created/updated timestamps. Updating a profile mints a new version; prior versions remain
addressable so batch re-generation is deterministic and auditable.

### ConsentGrant (right-to-clone)

Subject identity, rightsholder, grant scope (projects, characters, operations, provider classes),
territory, reference and transcript evidence hashes, intended-use text, reviewer identity,
watermark/provenance policy, issue/expiry timestamps, revocation state, biometric-retention policy,
and an append-only audit log. A blend records per-source authorization; one broad grant cannot stand
in for another source. An explicit cloud-egress grant names the provider, data classes, territory,
retention ceiling, and expiry before any reference audio, embedding, prompt, or transcript leaves the
host.

Authorization is checked before reference ingest, embedding, upload/egress, generation, cache reuse,
assembly, and export. Lineage is transitive through clips, stems, mixes, derivatives, caches, and
review artifacts. Revocation uses compare-before-replace state transitions and a generation lease:
revocation blocks new leases, waits for or cancels in-flight work, rechecks before commit, quarantines
all reachable derivatives, and applies the grant's deletion/retention policy. A revoked, expired, or
missing grant can never be bypassed by a cache hit. The ledger records quarantine/deletion outcomes
without serializing biometric source material or subject PII.

Biometric references, embeddings, and consent evidence are stored at rest in a private directory
with mode `0700` and files with mode `0600`, using atomic write-then-verify replacement; a stronger
encrypted store may replace those minimums. Creation, verification, or preservation of these
permissions is fail-closed: permission failures reject the operation rather than falling back to a
broader mode. Hostile permission fixtures cover permissive parents, permissive existing files,
symlink replacement, failed chmod, and interrupted atomic writes.

### Capability & Adapter Registry

Typed interfaces — `TtsAdapter`, `ProcessorAdapter`, `SpatializerAdapter`, `AssetAdapter`,
`AnalyzerAdapter` — each with a declared name, locality (`local` | `cloud`), capability probe,
cost/retention/region disclosure (cloud only), and a fail-closed `unavailable` result. A static,
code-owned map resolves identifiers to typed constructors. Project/config data may select only an
identifier already compiled into that map; it can never provide an import/class path, command,
executable, URL, shared library, plugin binary, or arbitrary environment mutation.
A requested adapter that is unlisted or unavailable yields an explicit CapabilityResult, and — when
the caller demanded a render — a validation error rather than a silent fallback or remote call.

Every provider runs under a typed execution policy: egress hostname/region allowlist; credential
handle rather than credential value; declared payload/data classes; input/output byte and duration
limits; connect/read/total timeouts; cancellation; bounded retries only for classified transient,
idempotent requests; idempotency key; concurrency/rate ceilings; retention/cost confirmation; and
redacted structured errors. Redirects or provider-requested destinations outside the allowlist fail
closed. Local subprocess adapters use validated paths, fixed argv construction, bounded resources,
and the repository timeout/error helpers—never a shell string.

### Receipt & Provenance

Every render/assembly/QA op that produces an artifact accepts an optional `save_receipt` path and
returns a structured receipt reusing the repository's edit-receipt v1 shape: schema version,
operation and normalized parameters, ordered inputs with safe display name/role/SHA-256/duration,
output hash and stream metadata, toolchain fingerprint and Kinocut version, warning codes, review-
artifact references, `human_review_required`, and — for sound — SoundPlan hash, profile versions
used, consent grant references, and loudness/true-peak verification. Absolute source locations are
never serialized. Prompts and transcripts are represented by hashes and controlled artifact refs,
never raw text. Consent refs are opaque ids; subject identity and biometric material remain in the
access-controlled ledger/store rather than receipts.

### RenderFingerprint & numeric mix policy

The render fingerprint covers the normalized SoundPlan; every source/reference/IR/bed/model byte
hash; profile, preset, adapter-code, model, and consent-state versions; executable/library/container
versions; FFmpeg/SoX build; codec and mux settings; channel/sample/time-base conversions; seed;
locale; hardware/backend; concurrency ordering policy; and required-capability manifest. A cache key
is the hash of this complete fingerprint plus the stage/cue id. It is invalid whenever authorization,
bytes, code, toolchain, configuration, or required capabilities change.

All numeric thresholds are named defaults in `defaults.py` and overrideable through validated
delivery policy: integrated loudness target tolerance ±1.0 LU; true peak ceiling -1.0 dBTP for
stream/podcast and -2.0 dBTP for EBU/ATSC broadcast; cue/master sync tolerance ±10 ms; latency
compensation residual ≤1 sample; ducking defaults of **9 dB attenuation, 80 ms attack, and 350 ms
release**, with recovery within 500 ms; decoded-PCM equivalence peak absolute error ≤1 LSB at 24-bit
and aligned sample-count equality; stem recombination versus master peak absolute error ≤1 LSB at
24-bit after declared master-only processing is bypassed. Channel conversion never upmixes
implicitly; downmix occurs only when the SoundPlan explicitly names a supported standards-based
downmix preset, such as ITU-R BS.775 5.1-to-stereo. Every other channel-count conversion is a
validation error. If master-only limiting is enabled, the plan must also request a pre-master
reference and recombination is compared to that reference.

## Data Flow & Signal Order

1. **Authorize and ingest.** Validate grants and licenses before reading protected references. The
   generic screenplay parser supports tagged dialogue, action-line narration, and voiceover;
   generic narration resolves through a narrator `VoiceProfile` and is exercised with the
   medium-room fixture, while the WF adapter parses episode JSON → SoundPlan but maps its narrator
   seat to chapter-card metadata only. Validation rejects unknown characters, missing profiles, or
   lines lacking a resolvable voice.
2. **Generate.** Reauthorize immediately before local processing or cloud egress. M1 renders each
   line via the routed TTS adapter with prosody/emotion/pronunciation,
   in parallel where adapters are independent, emitting raw clips + per-line provenance.
3. **Restore & spatialize.** M2 applies the fixed signal order per clip:
   **denoise (FFT, optional neural) → de-ess → 5-band parametric EQ → dynamics/compression →
   convolution-IR room space → distance simulation → humanization → loudness/true-peak.** Per-clip
   overrides (e.g. confessional → close-mic dry; institutional → hall) apply within this order.
4. **Assemble.** M3 places clips on the SoundPlan timeline with pacing, crossfades, designed
   silence, ambient beds (M4) with automatic ducking, and Foley triggers; renders stems and the
   mixed episode; a post-render probe verifies output duration against the authoritative timeline.
5. **QA & metadata.** M6 measures loudness/TP/LRA, runs ASR-vs-script diff, artifact and spectral
   analysis, and emits distribution metadata and chapter markers.
6. **Consistency.** M5 fingerprints generated lines against profiles, flags drift and near-
   collisions, and can trigger targeted or batch regeneration.
7. **Deliver.** Reauthorize the complete transitive lineage before commit/export. Receipts, QA
   report, stems, and mixed episode are returned only if no grant/license changed during the lease.

## Requirement Traceability Matrix

Every wishlist bullet (`W*`) and every prior G016 capability (`G*`) maps to an owning module/stage,
acceptance evidence, and the durable story that delivers it. Nothing is deduplicated away: where a
wishlist bullet and a G016 capability overlap (e.g. loudness QC), both rows are retained and cross-
referenced so no obligation is silently merged out of existence.

### Voice synthesis (wishlist §1)

| ID | Capability | Owning module/stage | Acceptance evidence | Story |
|----|-----------|--------------------|--------------------|-------|
| W1.1 | 15+ genuinely distinct voices | M1 roster | Distinctiveness metric (M5) shows all roster pairs above collision threshold | S5/S10 |
| W1.2 | Zero-shot cloning from 10–15 s clip + transcript | M1 clone + M0 ConsentGrant | Clone renders new text; export fails closed without a live grant | S6 |
| W1.3 | Voice blending/compositing (2–3 sources, per-source EQ) | M1 blend | Composite profile renders; lineage records every source-specific grant | S6 |
| W1.4 | Per-character prosody (temp/speed/pitch/emphasis/pause), evolving per scene | M1 prosody | Two scenes of one character render with distinct, plan-declared prosody | S5 |
| W1.5 | Batch generation from parsed script | M1 batch ← M3 SoundPlan | One call generates all lines with correct per-line voice | S4/S5/S9 |
| W1.6 | Parametric emotion/performance direction | M1 emotion | Intensity/parametric direction produces measurably different renders | S5 |
| W1.7 | Pronunciation dictionary (project terms) | M1 + M0 project config | Project term renders per dictionary; default renders differently | S3/S5 |

### Post-processing chain (wishlist §2)

| ID | Capability | Owning module/stage | Acceptance evidence | Story |
|----|-----------|--------------------|--------------------|-------|
| W2.1 | Noise reduction (FFT + optional neural) | M2 denoise | FFT denoise deterministic; neural is capability-gated, explicit-unavailable when absent | S7 |
| W2.2 | De-essing | M2 de-ess | Sibilant energy reduced in target band vs input | S7 |
| W2.3 | 5+ band parametric EQ, per-character presets | M2 EQ | Named per-character EQ preset applied and reloadable | S7 |
| W2.4 | Dynamic compression (threshold/ratio/attack/release) | M2 dynamics | LRA reduced; parameters honored | S7 |
| W2.5 | Convolution-IR room reverb, swappable IRs, preset library | M2 spatial | Convolution IR used (not `aecho`); small-room/hall/outdoor/close presets | S7 |
| W2.6 | Distance simulation (far/close) | M2 distance | Far = HF rolloff + wetter + quieter; close = dry full-band | S7 |
| W2.7 | Loudness normalization EBU R128 -23 / ATSC A/85 -24, podcast -16, stream -14, true-peak limit | M2 loudness / M6 QC | Measured LUFS/LKFS and TP within named-preset tolerance | S7/S11 |
| W2.8 | Humanization (breaths, micro-pauses, jitter), parametric 0–100% | M2 humanize | 0% ≈ passthrough; higher settings add measurable micro-variation | S7 |
| W2.9 | Batch processing with per-clip overrides | M2 batch | One command processes a clip set; per-clip preset overrides applied | S7/S14 |

### Script-to-audio assembly (wishlist §3)

| ID | Capability | Owning module/stage | Acceptance evidence | Story |
|----|-----------|--------------------|--------------------|-------|
| W3.1 | Script parser (episode JSON / structured screenplay) | M3 parser | Generic narration and WF `scenes→turns→character/text/confessional` parse correctly; WF narrator remains text-only | S4 |
| W3.2 | Per-line voice routing | M3 routing | Each character maps to assigned profile automatically | S4 |
| W3.3 | Per-line spatial routing (confessional→close, institutional→hall, off-screen→distance) | M3 routing | Line kind selects spatial preset per rules | S4 |
| W3.4 | Automatic TTS generation (no per-line manual calls) | M3 → M1 | One assembly call generates every line | S5/S9 |
| W3.5 | Timing/pacing control (line/scene/beat pauses) | M3 pacing | Configurable pacing changes inter-line gaps | S4/S9 |
| W3.6 | Crossfading (line/scene/bed transitions) | M3 crossfade | Seams crossfaded; seam report timestamps present (see G* seam) | S9 |
| W3.7 | Designed silence (dead / room-tone / held-breath) with duration+quality | M3 silence | Silence cue renders with declared quality and duration | S4/S9 |
| W3.8 | Ambient bed layering with automatic ducking | M3 + M4 | Bed ducks under speech; recovers within configured tolerance | S8/S9 |
| W3.9 | Multi-track stems (dialogue/ambience/confessional/SFX) | M3 stems | Typed stems export and recombine within configured PCM tolerance | S9 |
| W3.10 | Episode-level one-command output (10–20 min) | M3 render | One command → finished episode from JSON; duration authoritative | S9 |

### Ambient generation & management (wishlist §4)

| ID | Capability | Owning module/stage | Acceptance evidence | Story |
|----|-----------|--------------------|--------------------|-------|
| W4.1 | Ambient bed generation from text | M4 generate (AssetAdapter) | Text prompt → bed; cloud generator capability-gated and disclosed | S8 |
| W4.2 | Ambient layer management (independent volume/control) | M4 layers | Multiple layers stack with independent gain | S8 |
| W4.3 | Seamless looping + scene crossfading (10–20 min) | M4 loop | Loop seam crossfaded; no audible repeat boundary in fixture | S8/S9 |
| W4.4 | Foley triggering at script moments | M4 foley ← M3 timeline contract | Named Foley resolves to an S4 cue id and fires during S9 assembly | S4/S8/S9 |
| W4.5 | Per-location ambient presets | M4 presets | Common-room vs memory-care presets differ and reload | S8 |
| W4.6 | Per-deck sonic texture | M4 deck | Deck id adds its declared tonal layer to the bed | S8 |

### Voice management & consistency (wishlist §5)

| ID | Capability | Owning module/stage | Acceptance evidence | Story |
|----|-----------|--------------------|--------------------|-------|
| W5.1 | Versioned voice profile library | M0/M5 store | Named, versioned profile persisted and reloaded | S10 |
| W5.2 | Consistency checking (spectral vs reference, flag drift) | M5 consistency (D42 port) | Per-line similarity vs reference; drift flagged | S10/S13 |
| W5.3 | A/B comparison against reference | M5 ab | Instant A/B reel of new render vs reference | S10 |
| W5.4 | Drift detection across episodes + re-alignment | M5 drift | Cross-episode drift flagged; re-align tool surfaced | S10 |
| W5.5 | Batch re-generation on profile update (all lines/episodes) | M5 + M1 | Updating a profile regenerates all its lines deterministically | S5/S10 |
| W5.6 | Cross-character distinctiveness (spectral distance, flag collisions) | M5 distinct | Near-collision pair flagged below threshold | S10 |

### QA & metadata (wishlist §6)

| ID | Capability | Owning module/stage | Acceptance evidence | Story |
|----|-----------|--------------------|--------------------|-------|
| W6.1 | Loudness compliance check (LUFS/LKFS/TP/LRA; fail=reject) | M6 loudness QC | Non-compliant clip rejected with codes | S11 |
| W6.2 | ASR verification (Whisper diff vs script) | M6 asr (D42 port) | Dropped/garbled words flagged; segments EOF-clamped | S11/S13 |
| W6.3 | Artifact detection (clicks/pops/robotic tones/glitches) | M6 artifact | Injected-artifact fixture flagged | S11 |
| W6.4 | Spectral analysis (visualize) | M6 spectral | Spectral artifact image + descriptor emitted | S11 |
| W6.5 | Metadata export (title/duration/chapters/loudness/credits/ISRC) | M6 metadata | Metadata doc with chapter markers per scene | S11 |
| W6.6 | Batch QA across all episodes → quality report | M6/M8 rollup | Season report aggregates per-episode QA | S11/S15 |

### Non-functional (wishlist §7)

| ID | Capability | Owning module/stage | Acceptance evidence | Story |
|----|-----------|--------------------|--------------------|-------|
| W7.1 | Local-first core; cloud only optional enhancement | M0 registry | Full episode renders with zero cloud adapters registered | S3/S15 |
| W7.2 | Full episode < 30 min on named hardware classes (hard gate) | M8 benchmark | Versioned 50–80-clip fixture passes cold/warm on both approved classes | S14/S15 |
| W7.3 | Parallel generation of independent voices | M1/M3 pool | Bounded concurrent generation is faster than serial without nondeterministic ordering | S5/S14 |
| W7.4 | Reads WF episode JSON directly | M7 WF adapter | Representative episode JSON ingests unmodified; narrator remains chapter metadata | S4/S13 |
| W7.5 | CLI-first (every feature) | M7 CLI | Every primitive has a flat + namespaced command | S12 |
| W7.6 | FFmpeg/SoX backbone (no DSP reinvention) | M2 processors | Filters built via audited FFmpeg helpers | S7/S13 |
| W7.7 | MCP-exposable | M7 MCP | Each primitive exposed as an MCP tool | S12 |
| W7.8 | Plugin architecture (typed allowlisted adapters) | M0 registry | Static code map registers typed adapter by identifier; config cannot load code | S3 |
| W7.9 | Preset system (profiles/chains/spatial/beds) | M0 presets | All four preset kinds saveable/loadable | S1/S3 |
| W7.10 | Per-project configuration | M0 config | Project selects roster/ambience/loudness/spatial within policy | S3 |

### Prior G016 capabilities (preserved, distinctly owned)

| ID | Capability | Owning module/stage | Acceptance evidence | Story |
|----|-----------|--------------------|--------------------|-------|
| G01 | Stable SoundPlan contract | M0 | Versioned SoundPlan covers typed format, routing, automation, licenses and processing refs | S1 |
| G02 | Render/QC contracts | M0/M3/M6 | Render + QC contracts stable across adapters | S1/S11 |
| G03 | Cue spotting | M3 | Timeline cues derived from script beats | S4 |
| G04 | SFX/ambience catalog, audition, placement, fades, loops | M4 | Catalog search + audition contract + placement | S8/S9 |
| G05 | Immutable asset provenance | M0/M4 | Content hashes and transitive lineage recorded immutably without raw protected text | S2/S8 |
| G06 | Track & bus routing | M3 | Typed dialogue/ambience/confessional/SFX buses | S1/S9 |
| G07 | Gain, pan, EQ, dynamics, limiting, ducking, automation | M2/M3 | Each control exercised against numeric policy in real-FFmpeg test | S7/S9 |
| G08 | Stems | M3 | Typed stems exported, hashed and recombined within PCM tolerance | S1/S9 |
| G09 | Deterministic FFmpeg mixdown | M3 | Declared determinism class verified from complete RenderFingerprint | S3/S9 |
| G10 | Loudness & true-peak QC | M6 | Measured LUFS/LKFS/TP within named preset | S11 |
| G11 | MCP/Python/CLI adapters | M7 | Parity tests across three surfaces | S12 |
| G12 | Capability-gated optional providers | M0 | Static registry; absence → explicit unavailable; no config-driven code | S3 |
| G13 | Independent review, authoritative tests, receipts, cleanup | M8 | Review pass + receipts + clean tree | S15 |
| G14 | Integration into review/learning/benchmark joins | M7/M8 | Named host contracts wired; benchmark receipt joined | S13/S14/S15 |
| G15 | One-shot audio beds (`audio-bed`) — D41 | Existing D41 via M7 binding | Neutral port contract plus preserved field behavior | S1/S13 |
| G16 | Bed-audition reels (`bed-audition`) — D41 | Existing D41 via M7 binding | Neutral port contract plus preserved field behavior | S1/S13 |
| G17 | ASR EOF clamping | Existing D42 via M7 binding | Segments clamped to probed duration; no false pace fail | S11/S13 |
| G18 | Voice style metrics (`voice-style-check`) — D42 | Existing D42 via M7 binding | Loudness/rate deviation flags preserved | S10/S11/S13 |
| G19 | Optional voice identity comparison (`voice-identity-check`) — D42 | Existing D42 via M7 binding | Reference/pair similarity gate preserved, optional | S10/S13 |
| G20 | Timestamped audio seam reports | M3/M6 | Crossfade/join seams reported with timestamps | S9/S11 |
| G21 | Stop before release | M8 | No version bump/tag/publish; human-review checklist | S15 |

**D41 / D42 ownership preservation.** Existing D41 owns one-shot beds/bed-audition and existing D42
owns voice style/identity metrics plus ASR clamping. M0 defines only backend-neutral ports. M4–M6
consume those ports in standalone tests through fakes; M7/S13 alone binds the existing Kinocut
implementations. `kinocut_sound` neither imports them in M0–M6 nor reimplements/re-owns them.

## Provider & Model Capability Behavior

- Each adapter declares `locality`, a `probe()` returning a CapabilityResult, and (cloud only)
  cost/retention/region disclosure surfaced before any call.
- Local TTS (e.g. Kokoro, Qwen3-TTS class), local denoise/EQ/reverb/loudness (FFmpeg/SoX), local
  ASR (faster-whisper class), and local embeddings are the default path.
- Optional cloud/neural capabilities (ElevenLabs voice design/cloning, Stable Audio/AudioLDM SFX,
  Adobe Podcast enhance, Auphonic QA, neural denoise, neural embeddings) are gated: absent →
  explicit unavailable for checks, validation error for demanded renders. No model download or
  remote selection occurs implicitly.
- A render records which adapter and model version produced each artifact for reproducibility.
- Local providers are explicitly installed/configured capabilities; “local-first” never authorizes
  a download. The required-capability manifest for a delivery names which local adapters must probe
  available before work begins and distinguishes them from advisory enhancements.

## Cache, Idempotency & Resume

- Cache key = the complete RenderFingerprint hash + stage/cue id. A candidate hit is reauthorized
  before use; changing content, grant/license state, adapter code, model bytes, toolchain, mix policy,
  or required-capability manifest invalidates affected artifacts.
- Batch generation, processing, and assembly are resumable: completed cues are skipped on re-run;
  a partial episode reports which cues are done, pending, or deferred.
- Stages declare `byte_deterministic`, `signal_equivalent`, or `non_reproducible`; verification matches
  the declared class. Provider seed/version is evidence, not a promise of reproducibility.

## Errors, Privacy & Security

- Validate media/reference/IR/model/receipt/registry paths before any FFmpeg/provider execution;
  reject path traversal and unsafe artifact directories via existing centralized validators.
- Escape every user-controlled FFmpeg filter value with the audited helper; bound all subprocesses;
  never expose raw unbounded stderr (correcting `wf-voice-process.sh`'s `2>/dev/null` suppression by
  translating failures through `ProcessingError`).
- Consent is fail-closed at protected ingest, egress, generation, cache reuse, assembly, commit, and
  export; transitive derivatives of a revoked grant are quarantined or deleted per policy.
- Receipts, reports, and examples never disclose absolute source paths, credentials, subject PII
  beyond the grant's declared scope, or unrelated environment details.
- Watermark/provenance stamping is applied where the provider supports it and recorded when it does
  not, so downstream consumers can distinguish. Absence never weakens the consent requirement.

## Deterministic & Perceptual QA

- **Required deterministic QA** (machine-decidable, must pass): declared loudness/TP/LRA preset,
  duration/tail, cue sync, latency compensation, ducking envelope, stem layout/recombination, channel/
  sample layout, required ASR coverage, required artifact checks, hashes, and consent/license lineage.
  If a required analyzer is unavailable, the delivery is `blocked_capability`, never passed/deferred.
- **Advisory QA** (may defer with an explicit capability result): neural denoise/embedding opinions or
  optional provider analyses not named in the delivery's required-capability manifest. Advisory
  absence cannot remove a required local baseline check.
- **Perceptual QA** (human review required, never auto-passed): voice-identity match, near-collision
  distinctiveness judgment, music/ambience taste, humanization naturalness. These emit review
  artifacts (A/B reels, spectra, seam reports) and set `human_review_required`, matching the
  repository rule that speaker identity, motion quality, and music taste always require human review.

## Fixtures

- A hostile media/cue matrix covering silent audio, mono, stereo, 5.1, sample-rate mismatch,
  VFR/time-base mismatch, malformed cues, clipping, corrupt input, missing input, shortest-stream/
  outro truncation attempts, deterministic decoded-PCM comparison, and stem recombination.
- The preserved `wf-voice-process.sh` output as a golden characterization reference for the post
  chain's documented order (with the noted `aecho`/stderr caveats recorded, not trusted as complete).
- A representative WF episode JSON (`scenes→turns→character/text/confessional`) for parser/assembly.
- A short multi-character SoundPlan with generic narration routed through a narrator `VoiceProfile`
  and medium-room spatial preset for end-to-end assembly, stems, and duration/tail proof; its WF
  variant emits narrator text-card metadata only.
- Injected-artifact and out-of-spec-loudness clips for QA detectors.
- A consent-grant fixture set: live, expired, revoked, and missing — to prove fail-closed export.
- Revocation-race fixtures covering in-flight provider work, cache hits, stems, mixes, review assets,
  quarantine, deletion, and per-source blend grants; cloud-egress fixtures cover provider/territory/
  retention mismatch without transmitting protected data.
- An optional-embedding fixture to exercise the capability-gated identity path.
- A versioned 50–80-clip baseline episode with fixed expected SoundPlan, required capabilities,
  channel/sample layouts, stems, and hardware/toolchain manifest for the under-30-minute hard gate.

## Migration From Current Audio Surfaces

- `kinocut/audio_engine/*` (synthesis, sequencing, presets, integrations) remains a supported
  low-level DSP/generation backend; `kinocut_sound` consumes it rather than duplicating it, and
  `add_generated_audio` semantics are preserved.
- `wf-voice-process.sh` is superseded by the M2 post chain; a compatibility adapter reproduces its
  -16 LUFS / TP -1.5 / space presets so existing callers keep working while the new default is -14.
- M0 declares backend-neutral D41/D42 ports and schedules S1 after the D41 contract is stable; it
  imports no Kinocut implementation. Existing field-wishlist primitives (`audio-bed`,
  `bed-audition`, `voice-style-check`, `voice-identity-check`, `clip-index`) remain authoritative and
  are bound to those ports only by M7/S13. Their receipts, registry, and review-artifact contracts
  remain owned by D41/D42 and are reused rather than reimplemented.
- Existing flat CLI, MCP tool names, and Python methods stay stable; new namespaced commands
  (`kino sound …`) are additive aliases.

## Packaging & Extraction Criteria (non-goal now)

Extraction into a standalone repository/package is explicitly **out of scope** for this design.
It becomes reconsiderable only when all hold: (a) the SoundPlan and adapter contracts have been
stable across at least one full season render; (b) no Kinocut-internal import remains in M0–M6;
(c) an independent-operation test suite passes with Kinocut absent; and (d) a daemon/service need
is demonstrated by measured throughput limits. Until then: same repo, same package, no daemon.

## Non-Goals

- No VST/AU/LV2 hosting or arbitrary plugin-binary loading.
- No WF narrator voiceover (text-only narrator preserved).
- No implicit cloud selection or model download.
- No separate repository, package, or daemon in this iteration.
- No unauthorized voice-impersonation workflow.
- No release action of any kind.
- No re-ownership of D41/D42 primitives.
- No GUI (CLI/MCP-first; GUI is a future, separate design).

## Durable Stories, Dependencies & Parallelism

The former S1–S9 labels remain useful only as sizing epics. The implementation units are the 15
bounded leaves below. Each lands as one independently authored and independently reviewed change
unit with red/green TDD, focused real-media integration where applicable, and an Epoch estimate/
actual receipt. No leaf authorizes implementation merely by appearing in this design.

1. **S1 — Contracts, timeline & mix policy (M0).** Backend-neutral SoundPlan, cue/timeline,
   format, bus/routing, pan/automation, latency, delivery, stems, numeric acceptance, determinism,
   render/QC, and D41/D42 port contracts. *Depends on:* existing D41 contract stability. It imports
   no Kinocut implementation and uses contract fakes.
2. **S2 — Authorization, provenance & privacy (M0).** ConsentGrant/ConsentLedger, licenses,
   per-source blend/cloud-egress grants, generation leases, transitive lineage, receipt privacy,
   revocation race, quarantine/deletion. *Depends on:* S1.
3. **S3 — Static registry, config & provider policy (M0).** Static code-owned constructor map,
   capability probing, presets/project config, local/cloud execution policy, full render fingerprint,
   authorization-aware cache. *Depends on:* S1, S2.
4. **S4 — Generic/WF parser & timeline against fakes (M3/M7 contract adapter).** Generic screenplay
   narration plus WF text-only narrator, cue spotting, pacing, silence, routing intent, Foley cue
   contracts. *Depends on:* S1. No generated clips or concrete D41 binding required.
5. **S5 — Base voice roster, prosody & batch (M1).** Local base-voice adapter, 15+ roster,
   pronunciation, prosody/emotion, deterministic batch against typed plans. *Depends on:* S1, S3, S4.
6. **S6 — Consent-gated cloning & blending (M1).** Zero-shot clone, per-source authorized blend,
   local/cloud egress enforcement and lineage. *Depends on:* S2, S3, S5.
7. **S7 — Post-processing & spatial chain (M2).** FFT/optional neural denoise, de-ess, EQ,
   dynamics, convolution IR, distance, humanization, loudness/TP and per-clip batch overrides.
   *Depends on:* S3. Uses fixed audio fixtures and can run parallel with S4/S5.
8. **S8 — Ambient assets, layers & loops (M4).** Licensed catalog/generation, audition contract,
   layers, seamless loops, location/deck presets, and Foley asset resolution against S4 cue ids.
   *Depends on:* S2, S3, S4. Uses a fake D41 port; concrete D41 binding waits for S13.
9. **S9 — Assembly, mixing & stems (M3).** Clip placement, crossfades, designed silence, buses,
   automation, ducking, latency compensation, deterministic mix, stem layout/recombination, duration/
   tail proof. *Depends on:* S4, S5, S7, S8; clone-derived fixtures additionally require S6.
10. **S10 — Voice consistency (M5).** Versioned profiles, identity/style metrics, A/B, drift,
    re-alignment, cross-character distinctiveness, batch regeneration using a fake D42 port.
    *Depends on:* S5; consent-derived cases depend on S6.
11. **S11 — QA & metadata (M6).** Required/advisory capability policy, loudness/TP/LRA, ASR,
    artifact/spectral checks, sync and stem QC, metadata/chapters/ISRC, season rollup using a fake
    D42 port. *Depends on:* S1, S4, S7, S9.
12. **S12 — Python/CLI/MCP parity join (M7).** Thin adapters over stable S1–S11 use cases, flat and
    namespaced CLI, non-TTY output, privacy/error parity and capability discovery. *Depends on:*
    each implemented use case in S4–S11; adapter slices may be reviewed sequentially in this one
    serialized join after their contracts freeze.
13. **S13 — Kinocut/WF/legacy migration & host joins (M7).** Bind existing D41/D42 implementations
    to the neutral ports; preserve `audio_engine`, flat API and `wf-voice-process.sh` compatibility;
    wire Kinocut review-package, learning/cost, and acceptance-benchmark joins and the WF text-card
    narrator invariant. *Depends on:* S8, S10, S11, S12, the pending G007/D41–D42 owner wave, and
    the host review/learning/benchmark contracts from their owning program waves. S13 cannot infer
    completion or ownership of that external wave.
14. **S14 — Bounded scheduler & named-hardware hard benchmark (M8).** Bounded local process pool,
    cancellation/resume, resource ceilings, versioned 50–80-clip fixture, and cold/warm runs on
    the approved Apple-silicon and x86 Linux classes under 30 minutes with all required
    capabilities. *Depends on:* S5–S13. An unavailable or mismatched benchmark environment leaves
    the gate incomplete.
15. **S15 — Final acceptance, security & release stop (M8).** End-to-end/season acceptance,
    authorization/revocation adversarial suite, deterministic-class proof, leak/privacy audit,
    supported full suite, independent code and architecture reviews, receipts, cleanup, human-review
    checklist, and STOP before release. *Depends on:* S1–S14 and completed host joins.

**Parallelization:** Once S1 lands, S2 and S4 can run concurrently; S3 follows S2 and then unlocks
S7. S5 follows S1/S3/S4; S8 follows S2/S3/S4; S6 follows S5; S9 joins
S4/S5/S7/S8; S10 follows S5; and S11 joins S4/S7/S9. S12 and S13 are serialized public-surface/
host joins, with S13 additionally waiting for the pending G007/D41–D42 owner wave; S14 then proves
bounded performance; S15 is the final serial gate. CLI routing, MCP
registration, public manifests, receipts, capability manifests, docs, and host join files have one
owner at a time and are never edited concurrently.

## Release Stop

No story authorizes a version bump, tag, package upload, directory/Smithery submission, Forgejo
release, or deploy. Implementation stops after S15's acceptance receipt lists change units, test
counts, benchmark cold/warm figures, optional-capability limits, and remaining human-review
requirements, then awaits explicit user direction — consistent with G016's standing "stop before
release" constraint.

## Self-Review

- **Decision-complete.** Every section states a concrete rule. The current 15-leaf decomposition, corrected
  expanded-DAG path analysis, and fixed-chain sensitivity are labeled with their latest Epoch 0.2.0
  receipt ids and statistical limitations; dependency or duration changes require a fresh latest-
  Epoch run, and superseded epic receipts are not assigned to current leaves.
- **No missing wishlist bullet.** All seven wishlist areas are covered: §1 → W1.1–W1.7; §2 →
  W2.1–W2.9; §3 → W3.1–W3.10; §4 → W4.1–W4.6; §5 → W5.1–W5.6; §6 → W6.1–W6.6; §7 → W7.1–W7.10 —
  every sub-bullet in `SONIC-WORLD-WISHLIST.md` has a matrix row with an owning module and
  acceptance evidence. All prior G016 capabilities appear as G01–G21.
- **No silent deduplication.** Overlapping obligations (loudness QC appears as W2.7, W6.1, G10;
  ducking as W3.8, G07; stems as W3.9, G08; ASR as W6.2, G17; beds as W4.x, G15/G16) each retain
  distinct rows with cross-references, so no requirement is merged out of existence.
- **Conflicts reconciled.** The nine rulings define static typed adapters (not VST or config-loaded
  code); explicit local/cloud capability behavior; authorization at every lifecycle boundary; generic
  narration with WF narrator text-only; distinct -14/-16/EBU -23/ATSC -24 presets and legacy
  compatibility; characterization-only legacy shell behavior; authoritative duration; a hard
  under-30-minute named-baseline gate; and standards-specific broadcast policy.
- **No accidental release authority.** "Stop before release" is stated in Scope, Non-Goals, S15, and
  the Release Stop section; no story permits bump/tag/publish/deploy.
- **No interface leakage.** Public contracts (SoundPlan, VoiceProfile, ConsentGrant,
  CapabilityResult, Receipt, QAReport) expose no FFmpeg filter strings, provider SDK types, model
  file paths, or absolute source locations; DSP/provider/file-layout complexity is hidden behind the
  deep-module interfaces, and receipts/reports are privacy-scrubbed.
- **Architecture preserved.** Same repo/package, independent Python+CLI operation, Kinocut+WF
  adapters, no daemon/separate repo — stated in the Architecture Decision section and enforced by
  the Packaging & Extraction non-goal.
