# Independent review: audio normalization, audio-only inspection and encoded sound QA

Reviewed local diffs and surface integration for GitHub issues #584, #582 and #580. No runtime edits by reviewer; repairs requested from reliability owner.

## Concrete findings and repairs

1. Normalization originally published the staged output before `_build_edit_result` constructed the result. A final result-probe failure could therefore replace an existing destination and still raise. Owner moved result creation and typed receipt construction inside staging and remaps the path after publication. Added failure injection proving existing bytes survive final result-construction failure.
2. Moving the result probe into staging initially caused the shared self-overwrite guard to classify the staging path as an input. Independent actual-media test reproduced the rejection after 4 passing audio-only cases. Owner now declares `_validate_output_path(staged)` before result probing; final actual WAV/M4A regressions pass.
3. Encoded async QA initially used synchronous FFprobe on the event loop before asynchronous metering. It could stall cancellation for the FFprobe deadline. Owner now awaits the existing bounded, cancellation-owned meter process runner for FFprobe as well as metering, keeping the same temporary source lifetime around all children.

## Verified boundaries

- Original source identity is retained: shared safe descriptor-relative read checks dev/inode/size/mtime_ns/ctime_ns before/after the read and verifies the expected SHA; unchanged encoded bytes are written to a private temporary file. Encoded receipts hash these original bytes, not decoded/re-encoded approximations. Changed source tests fail safely.
- Real EBU R128 integrated loudness, intersample true peak and LRA use the shared existing meter/parser. Compliance reuses the supplied DeliveryPolicy evaluator, including the stricter of its two true-peak ceilings; no unconditional success or synthetic fallback on an invalid encoded request.
- Unsupported text/playlist signatures are rejected before probing. Measuring encoded content selects primary audio, disables video decoding, uses local file/pipe protocol whitelist, applies resource-bound input reading, duration validation and existing bounded diagnostic/deadline runner. Error messages and public receipts contain no host source path.
- WAV normalization chooses PCM16; M4A chooses AAC; actual codec/format inspected and complete decode performed before publication. Actual stereo rate/channels/duration and measured LUFS/peak controls pass. Source remains unchanged; failed postflight and failed result construction preserve previous output.
- Audio-only waveform accepts mono/stereo WAV/MP3; silence is measured rather than synthesized. Preflight composes the existing loudness/decode engines and reports color checks inapplicable for audio, without inventing visual acceptance.
- CLI, Client and MCP encoded-source parity tests pass for M4A/MP3/MP4. Demo/bytes standalone contracts remain delegated to existing implementation.

## Independent validation after repairs

- `tests/test_audio_input_kinds.py tests/test_sound_loudness_encoded.py`: **18 passed in 20.63s**.
- `tests/test_sound_meter_process.py`: **26 passed in 5.74s**, including actual child ownership, timeout, diagnostic bounds and repeated-cancellation/reap controls for the shared runner now also used by encoded async FFprobe.
- Ruff passes for normalization/output/waveform/host adapter. All reviewed modules under800LOC and all functions at most80LOC.

No unresolved concrete defect found in this reviewed scope. Root owns final full-suite validation. The host adapter cancellation test mocks the runner to verify workspace lifetime; real process ownership/reaping evidence comes from the shared runner's actual child tests, not that mocked test alone. This review does not claim universal normalization perceptual quality or platform portability beyond tested contracts.
