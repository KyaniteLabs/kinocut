# Plain-file audio mixing

These Python APIs are development-checkout additions; see
[Unreleased changes](../CHANGELOG.md). They do not add MCP tools or CLI commands.
Both methods accept `input_path` and `output_path` aliases for `video` and
`output`; ducking also accepts `music_path` for `music`. Conflicting canonical and
alias arguments are rejected. FFmpeg is required. Use them for local files when a governed projectstore audio-bed
receipt is not required.

## Mix several sounds in one encode

`Client.mix_audio(video, tracks, output=None, keep_source=True, *, audio_bitrate="256k")`
adds timed tracks in one FFmpeg filter graph, encodes the resulting AAC soundtrack
once as stereo 48 kHz AAC and stream-copies the picture. This avoids repeatedly calling
`add_audio(mix=True)` and repeatedly encoding an already lossy soundtrack.

```python
from kinocut import Client

video = Client()
result = video.mix_audio(
    "interview.mp4",
    [
        {"path": "music.wav", "volume": 0.15, "fade_in": 0.5, "fade_out": 1.0},
        {"path": "chime.wav", "start": 2.25, "volume": 0.4},
    ],
    output="mixed.mp4",
)
print(result.output_path, result.warnings)
```

Each track requires `path`. Optional `start`, `fade_in` and `fade_out` are seconds;
`volume` is linear gain, default 1.0, within 0–4. Starts must precede the video end.
There are at most 64 tracks; unknown fields, nonfinite numbers and booleans supplied
as numbers are rejected. The bitrate is an integer-kilobit string within `8k`–`512k`.

The video duration is preserved. Short tracks end normally; long tracks are clipped
at the video end. Fades apply to the audible, clipped segment. Set
`keep_source=False` to omit the original soundtrack.

Tracks sum at unity without automatic attenuation or loudness normalization; the
returned warning identifies clipping risk. Reduce gains and listen before publishing.
The mixer validates a staged output, including a bounded audio decode, before replacing
its destination. This operation does not produce the governed audio-bed receipt.

## Duck music under existing speech

`Client.duck_audio(video, music, output=None, music_volume=0.6, threshold=0.05,
ratio=8.0, attack=20, release=300)` exposes the existing plain-file sidechain mixer.
Attack and release are milliseconds. It reduces the music in response to the video's
audio; it does not transcribe speech or certify intelligibility.

```python
result = video.duck_audio("interview.mp4", "music.wav", output="ducked.mp4")
```

This method does not normalize delivery loudness or emit a governed audio-bed receipt.
When those guarantees are required, use the existing `audio_bed` workflow with verified
projectstore snapshots; see [the MCP audio tools](TOOLS.md#audio-synthesis-9-tools).

## Loop one added track

`Client.add_audio(..., mix=True, duration_policy="loop_audio")` loops the added audio
with bounded input/output duration while retaining the original soundtrack and video
length. `pad_audio` remains unsupported with `mix=True`; it raises
`unsupported_duration_policy_for_mix`. Use `keep_video`, `loop_audio`, `trim_audio` or
`shortest` according to the existing duration contract. For many independent sounds,
prefer one `mix_audio` call.
