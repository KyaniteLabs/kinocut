# Plain-file audio mixing

These APIs are published 1.16.0 additions; see
[the changelog](../CHANGELOG.md). Python `mix_audio` and `duck_audio` share their engines with MCP `video_mix_audio` / `video_duck_audio` and CLI `mix-audio` / `duck-audio`. Track descriptions are bounded to 65,536 UTF-8 bytes and 64 tracks.
Both methods accept `input_path` and `output_path` aliases for `video` and
`output`; ducking also accepts `music_path` for `music`. Conflicting canonical and
alias arguments are rejected. FFmpeg is required. Use them for local files when a governed projectstore audio-bed
receipt is not required.

## Mix several sounds in one encode

`Client.mix_audio(video, tracks, output=None, keep_source=True, *, audio_bitrate="256k")`
adds timed tracks in one FFmpeg filter graph, encodes the resulting AAC soundtrack
once as stereo 48 kHz AAC and stream-copies the picture. A separate bounded
audio-only decode checks the staged soundtrack before publication; one audio
encode does not mean one FFmpeg invocation. This avoids repeatedly calling
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

The primary picture stream determines the output origin and duration, including
when the container has a longer audio tail. Retained source audio preserves its
timing relative to the picture start, rather than moving delayed speech to time
zero. Short tracks end normally; long tracks are clipped at the picture end.
Fades apply to the audible, clipped segment. Set
`keep_source=False` to omit the original soundtrack.

Tracks sum at unity without automatic attenuation or loudness normalization; the
returned warning identifies clipping risk. Reduce gains and listen before publishing.
The mixer validates a staged output, including a bounded audio decode, before replacing
its destination. This operation does not produce the governed audio-bed receipt.

Picture timing uses bounded presentation-packet measurements even when stream
duration is populated: reordered frames can extend beyond that metadata value.
The packet producer is limited to 1,000,001 packets, including an overflow sentinel;
more than 1,000,000 timeline packets are rejected. Metadata is written to a private
temporary file and rejected if it exceeds 64 MiB. This byte-size check occurs after
writing and is not a hard guarantee on transient metadata-file size. The packet
and execution-time limits bound extraction; video is not decoded to obtain it.
Tracks use their selected first audio stream's actual extent. When stream duration
is unavailable, bounded audio-frame decoding adds a separate measurement pass.
These correctness checks add work; there is no universal latency-reduction claim.

## Duck music under existing speech

`Client.duck_audio(video, music, output=None, music_volume=0.6, threshold=0.05,
ratio=8.0, attack=20, release=300)` exposes the existing plain-file sidechain mixer.
Attack and release are milliseconds. It reduces the music in response to the video's
audio; it does not transcribe speech or certify intelligibility.

```python
result = video.duck_audio("interview.mp4", "music.wav", output="ducked.mp4")
```

This method does not normalize delivery loudness or emit a governed audio-bed receipt.
Primary source audio must exist and be nonempty; measured silence is accepted.
Attachment and ducking validate the staged AAC soundtrack with an error-sensitive
full audio decode before publishing, preserving existing output on failure.
When those guarantees are required, use the existing `audio_bed` workflow with verified
projectstore snapshots; see [the MCP audio tools](TOOLS.md#audio-synthesis-9-tools).

## Loop one added track

`Client.add_audio(..., mix=True, duration_policy="loop_audio")` loops the added audio
with bounded input/output duration while retaining the original soundtrack and video
length. `pad_audio` remains unsupported with `mix=True`; it raises
`unsupported_duration_policy_for_mix`. Use `keep_video`, `loop_audio`, `trim_audio` or
`shortest` according to the existing duration contract. For many independent sounds,
prefer one `mix_audio` call.

Added-audio fades include the source's native timestamp offset and requested
placement delay. Leading gaps stay audible as silence; fades stop at the selected
sound or picture boundary. A looped track fades at the final output window rather
than restarting its fade on every repeat. Listen to placement and loop seams
before acceptance.
