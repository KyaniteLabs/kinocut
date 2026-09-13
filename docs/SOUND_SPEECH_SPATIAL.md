# Distance processing for real caption speech

`SoundDubRequestV2` adds a required `spatial_profile` to the existing real
caption/eSpeak request. Use the same Python `sound_voice_batch`, CLI and MCP
operation with `request` and `project_root`. Import the model from
`kinocut_sound.public`.

```json
{
  "schema_version": 2,
  "spatial_profile": "off_screen_distance",
  "source": {"path": "captions.srt", "sha256": "sha256:<caption-file-hash>"},
  "target_lang": "es",
  "output_path": "speech.zip"
}
```

Supply the actual caption-file hash. The two profiles are:

- `close_mic_dry`: retain each generated cue byte-for-byte; no FFmpeg required.
- `off_screen_distance`: apply the existing distance adapter's 100% distance
  formula—a -6 dB high-frequency shelf at 4 kHz/Q0.7 and -6 dB overall gain.
  This requires FFmpeg and never falls back to dry audio after failure.

The shared DSP compiler is used by both the post adapter and this public path.
There are no arbitrary filter or numeric-profile options. Unsupported room/hall
profiles fail before processing. This feature affects real eSpeak output; the
separate plan-only tone demo and `Line.spatial_preset` metadata are unchanged.

## Timing, evidence and handoff

Each generated cue is validated before processing and again before acceptance.
Output remains non-silent mono PCM16 at 22050 Hz with exactly the same frame count.
No tail, trimming, padding, time stretch or overflow concealment is applied. An
utterance that exceeds its caption window fails before the effect can run.

V2 receipts add `schema_version: 2`, `request_schema_version: 2`, and a separate
`spatial` section. It records the selected profile, bounded FFmpeg version/settings
and distance parameters when used, plus ordered cue dry/processed hashes, frame
counts and applied/bypass flags. Results add `spatial_profile` and `spatial_sha256`
over that public section. Private paths and effect filenames are excluded.

Retained cue files, `dialogue.wav` and `mix-request.json` bind the processed speech.
The manifest remains directly usable with `sound_mix_render`. V1 request identity,
audio and archive layout are preserved; V2 dry audio equals V1 on the same speech
installation. Backend-dependent output is not claimed identical across installations.

## Ownership and limits

Synthesis and effects run sequentially under the existing overall dub deadline.
Effects use bounded direct-child sync/async execution, raw-output and diagnostic
limits, and one decoder/filter thread. Cancellation finishes owned-child cleanup.
Private workspace cleanup and complete receipt/result preparation precede exclusive
publication. Existing output files are not overwritten.

Before each effect, admission accounts for the assembled timeline, previously
retained clips, fourfold dry/processed buffer allowances, and policy reservations
of 16 MiB native workspace, 1 MiB metadata and 1 MiB I/O. It retains the existing
128 MiB dub memory estimate and cumulative WAV/text/cue limits. These allowances
are not measured or hard RSS guarantees. Failed admission or processing leaves
no final ZIP. The existing POSIX filesystem boundary remains.

Stock-voice, no-translation and human-listening limitations still apply. This is
not mastering, room convolution, scene scheduling or execution of all spatial
metadata in a SoundPlan.
