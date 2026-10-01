# Quality evidence and capability limits

These contracts describe the development checkout. Unreleased changes are recorded
in [CHANGELOG.md](../CHANGELOG.md); the published package may retain earlier behavior.
Technical measurements, frame preparation and semantic assessment are separate
results. A successful tool call does not establish that every requested quality
property was evaluated.

## Audio waveform

MCP `video_audio_waveform`, Python `Client.audio_waveform(video, bins=50)` and CLI
`audio-waveform` analyze the first audio stream in at most the requested 1–1000
windows in video or audio-only files (including WAV). Video decoding is disabled.
Missing audio is an error.

Each `peaks` entry contains the bin center in source seconds and its measured RMS
level in dBFS. The field name is retained for compatibility: it is not a sample-peak
or true-peak measurement. `mean_level` combines duration-weighted linear power;
`max_level` and `min_level` describe the bin RMS levels. Digital silence uses a finite
-120 dBFS floor. Silence regions use a -50 dBFS threshold and bin boundaries.

The analysis retains audio offsets and gaps relative to the media origin, includes
leading/trailing silence and compensates padding in the final partial window.
Stereo channels are measured without downmixing opposite-phase audio into silence.
Aggregation uses bounded audio frames and produces bounded metadata.

A retained compatibility fallback for unavailable metadata returns
`synthetic=true`, with synthetic -20 dBFS values. Treat that result as unavailable
measurement, never proof of level or silence. Valid analyzed media returns
`synthetic=false`. A decode error or timeout raises a processing error.

## Loudness and audio-only preflight

Hash-bound `sound_qa_loudness` host requests measure the first audio stream of
supported local audio/video containers with the existing EBU R128/true-peak meter.
They bind the original source bytes and apply the same delivery policy; encoded
media support does not change the standalone PCM or bytes API. `within_tolerance`
is measured audio-policy compliance, not visual acceptance or a listening pass.
See [the meter request and bounds](SOUND_LOUDNESS_REQUESTS.md).

Project preflight accepts audio-only assets and performs actual loudness/decode
checks. Their color result has `applicable=false` and `analyzed=false`, rather than
inventing video color evidence.

Voice-batch receipts do not measure an assembled master. They return
`loudness=null`, `loudness_assessment_status="not_evaluated"`, and a warning;
they do not certify fixed LUFS/true-peak values. Consumers requiring measured
loudness must meter the final assembled output. Other measured receipts retain
their numerical evidence. Their default `"measured"` status is implicit in the
serialized legacy shape, preserving existing canonical hashes.

`normalize_audio` writes PCM16 for WAV and AAC for supported M4A/video containers,
preserving source sample rate and channels. Its result reports the observed
`audio_codec` and FFprobe `format`; the latter may name a container family. It
validates a staged result, including expected codec and full error-free audio
decode, before replacing the destination. Two-pass normalization and fade/default
peak behavior retain their existing contracts; measure the final output to verify
policy compliance.

| Output extension | Audio codec |
| --- | --- |
| `.wav` | PCM16 little-endian |
| `.aif`, `.aiff` | PCM16 big-endian |
| `.m4a`, `.aac`, `.mp4`, `.mov`, `.mkv` | AAC |
| `.mp3` | MP3 |
| `.flac` | FLAC |
| `.ogg` | Vorbis |
| `.opus` | Opus |

Audio containers discard picture; MP4/MOV/MKV retain the video stream. Unsupported
output extensions fail before rendering.

## Visual sampling and semantic assessment

`video_qc_vision` prepares retained keyframes. `sampling_status` describes extraction;
`assessment_status` describes inference. Complete extraction without a scorer is
`verdict="not_evaluated"`; incomplete extraction is `"inconclusive"`. Requiring a
VLM with `require_vlm=true` returns `verdict="fail"` and `blocked=true` while the
executor is unavailable. An installed provider SDK is not an executable scorer.

Set `KINOCUT_VISION_MODEL` and provide `ANTHROPIC_API_KEY` through environment
settings to explicitly enable one paid Anthropic request. No default model is
selected. Up to twelve finite timestamps produce width-bounded frames; request
bytes, image bytes and response bytes are capped. A separate owned process enforces
a 60-second deadline across import and network execution. Redirects and compressed
responses are refused; error bodies are closed without buffering. A semantic
result covers sampled frames only. Provider availability and fixture tests do not
establish accuracy, a whole-film viewing pass, or a calibrated quality threshold.

The host can inspect the retained frames separately. Human review or an external
model assessment must bind its decision to the actual reviewed artifact; frame
extraction alone does not establish caption legibility or narrative correctness.

## Objective visual measurements

Black coverage follows decoded video presentation intervals, including the last
frame and short black runs. Its denominator is the decoded picture duration, so a
longer audio track does not dilute coverage. Missing, damaged or unverifiable
decode evidence is unavailable, rather than a zero-black result.

Brightness, chroma and related SDR measurements normalize native 8/10/12/16-bit
full/limited-range samples into the units used by existing thresholds. This does
not establish HDR delivery acceptance. Grayscale samples use an explicit full-range
input policy, including TV-tagged gray formats, matching the existing 8-bit behavior
across FFmpeg versions. Native YUV retains its own range. Mixed gray/color video
streams report unavailable evidence when stream selection is ambiguous.

The first standalone visual measurement probes source metadata before conversion.
That metadata is shared with audio-stream checks and reused for an unchanged source;
this correctness check is not a universal latency improvement. Transient caches
bind successful observations to source filesystem identity and analysis settings, retry failures
and bound retained entries. This cache is not a cryptographic integrity boundary.

## Whole-film temporal motion evidence

`video-inspect-temporal` returns and persists `motion_coherence`, bound to the inspected
source SHA-256. It retains chronology and compares 16×16 luma samples over time;
per-window difference rates and advisory lurch/high-rate/calm-to-high candidates are
technical signals, not a determination of intentional transitions, physical motion,
narrative coherence or artistic quality.

The result discloses decoded extent, difference coverage, gaps and the frame budget.
More than 18,000 decoded frames rejects the analysis rather than silently truncating
it. Thresholds are heuristics requiring project calibration; calm footage is valid.
The inspection artifact records `human_viewing_status="not_recorded"` and
`acceptance="not_granted"`. Complete human viewing and separate review evidence
remain required; these advisory observations cannot grant acceptance.

Python `Client.record_motion_acceptance(...)` records that separate review. It
requires the exact source/report hashes, complete decoded evidence, gap-free
watched intervals covering the film, and a disposition for every flagged motion
interval and transition. An unresolved `needs_fix` disposition prevents acceptance.
The receipt records a human attestation; software cannot verify that a person
watched the film. See [the feature acceptance guide](research/debt-closure-feature-acceptance.md).

## Voice identity and style

Default D42 host ports do not have a perceptual speaker-identity or vocal-style
backend. They report unavailable and raise `d42_voice_seam_unavailable` when asked
to evaluate those properties. Supplying FFmpeg or identical content hashes does
not create a speaker analyzer. A calibrated perceptual port is required.

An audio-stream hash can prove exact encoded-stream preservation; it cannot prove
same-speaker identity or similar style across different recordings. This limitation
does not disable independently implemented loudness, mastering or ASR operations.
ASR reference matching also does not establish speaker identity or listening quality;
see [the ASR request contract](SOUND_ASR_REQUESTS.md).

## Publication and review

Conversion stages and validates the result before replacing its destination. An
encoding, callback, timeout or postflight failure preserves an existing destination.
Conversion, the new audio mixer and audio normalization each stage and validate
their own output. Trim and playback-speed edits also stage output and construct
the result before replacement, preserving the destination on render/result
failure. Their staging does not imply the full-decode validation performed by
audio normalization. Trim times reject nonfinite values and numeric overflow
before rendering. Times accept numeric seconds or `MM:SS`/`HH:MM:SS`; booleans,
malformed values and strings longer than 128 characters are rejected. Publication
is a file replacement, without an fsync crash-durability or database-bundle claim.
These guarantees must not be assumed for every writer.

Publication requires exclusive writer ownership of the destination directory.
Owned descriptors, no-follow ancestry checks and final identity checks reject
observed substitutions. A detected failure after replacement returns
`partial_output_publication`; callers must inspect the output and must not assume
the previous destination survived. Composite media and its JSON receipt publish
separately. A receipt publication failure after media commits returns
`partial_artifact_publication` with the committed media identity, without an unsafe
rollback of another writer's files. Concurrent actors with equivalent filesystem
authority can modify an output after publication; this API is not a confinement
or multi-file crash transaction.

Keep human-review decisions distinct from analyzer reports. For exact-asset approval
and protected derivatives, follow [governed AI-video review](AI_VIDEO_REVIEW_AND_SALVAGE.md).
For durable repair, detached job cancellation and resume, see
[projectstore lifecycle](PROJECTSTORE_LIFECYCLE.md).
