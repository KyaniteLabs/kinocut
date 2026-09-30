# Audio PR and issue adaptations — September 30, 2026

Reviewed full PR [#573](https://github.com/KyaniteLabs/kinocut/pull/573), head `c64aa001b2bd9215390addf81fe2980b114a1600`, including every changed file before running contributor tests. No workflow/dependency changes, network calls, credentials, or repository mutation in the contribution. Local reversible adaptations only; no merge, commit, remote comments or issue closure.

Credit: @guillaume-hestia-projekt (`guillaume-hestia-projekt <guillaume@hestia-projekt.com>`), whose one-pass mixer and real hiss/timing tests underpin this adaptation. Preserve this credit if committing later.

## Addressed locally

- **#573 / #572**: Add engine/Client `mix_audio`, one FFmpeg invocation and one AAC encoder for all tracks, picture stream-copied. `tracks` accepts exactly path/start/volume/fade_in/fade_out, max64, volume0–4; source audio retained by default. Stereo48k AAC256k by default; keyword-only bitrate8k–512k. Starts expressed in audio samples, gain summed at unity, explicit potential-clipping warning. Keep video duration with silence padding. Real contributor fixture confirms one mix has at least4dB less high-frequency energy in an untouched passage than10 successive add_audio mixes; this is a fixture-specific lossy-generation regression, not a universal acoustic-quality claim.
- Adaptations improve original PR safety: validate finite numerics, strict keep_source boolean, bounded bitrate; audio-aware input probing (one probe per unique path per call); stage output and postflight before atomic publication; reject aliases including hardlinks to audio tracks; bounded decode duration per added track; reset track PTS; replace areverse whole-track buffering with streaming afade. Fade-out ends at the audible segment boundary clipped to video end. Actual output format reported in EditResult. Engine public export added; no MCP or CLI tool registration added.
- **#555**: `add_audio(..., mix=True, duration_policy="loop_audio")` loops only the added input, bounds that input with input `-t`, caps output at original video duration and retains source audio. Existing signatures preserved. Tests cover normal, silent and multistream sources, positive start offset and a measured late tone. `pad_audio` with mix remains explicitly unsupported.
- **#549**: Expose existing plain-file sidechain engine through `Client.duck_audio(video, music, output=None, music_volume=.6, threshold=.05, ratio=8, attack=20, release=300)`. Docstring states no project store required and no governed receipt/loudness normalization promised. Client.audio_bed docstring now explicitly requires immutable verified source snapshots from a project store and points plain-file callers to duck_audio. User-controlled duck graph values now use shared escaping; defaults centralized without changing values. Actual keyed-voice fixture proves music dips >8dB during voice.

## Validation

- `tests/test_audio_mix.py tests/test_add_audio_duration_policy.py tests/test_tier4_features.py`: **59 passed in31.17s**, including original contributor tests, loop policies and existing MCP duck/progress/LUT compatibility.
- After adding six further hardlink/silent-picture/strict-boolean cases, final `tests/test_audio_mix.py`: **29 passed in20.28s**.
- No failures remain. Two initial authored test-fixture mistakes (ProcessingError constructor arguments and FFmpeg duration `.5` parsing) corrected; runtime assertions then passed.
- Ruff checks/format, canonical+compatibility Client import and `git diff --check` passed. Engine modules187/411LOC, client audio275LOC; no function exceeds80LOC. Root owns required final full suite.

## Documentation coordination

Product agent owns `docs/AUDIO_MIXING.md`, PYTHON_CLIENT/TOOLS links and full CHANGELOG. Engine and Client docstrings updated here. No version/release/merge claims. Remaining limitation: summed gain can clip and callers should choose gains/listen; AAC still introduces one lossy generation. Source media, underlying FFmpeg behavior and target output container compatibility remain real constraints. No claim all older audio writers are transaction-safe; staged publication is specific to new mix_audio.


## Client registry integration follow-up

Final integration caught missing `CLIENT_METHOD_CONTRACTS` entries for the two new APIs. Both now declare media/`EditResult` contracts and input/output aliases; ducking also accepts the music-path alias. Wrapper introspection, parameter-conflict and helpful-error controls, result identity and warnings are covered. The full client/mixer/Tier4 focused run passed **140 tests** after this repair.
