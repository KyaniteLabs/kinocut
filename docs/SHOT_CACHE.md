# Render only changed shots

Use this Python API for a film made of video-only shots. Renderers may run in parallel; the list order, not completion order, determines the cut.

```python
from kinocut.shot_cache import ShotSpec, render_shot_plan

shots = [
    ShotSpec("opening", source_path="intro.mp4", start_frame=24, frame_count=48),
    ShotSpec("title", command=("python", "cards.py", "{params}", "{frame_count}", "{output}"),
             params={"text": "Interlude", "renderer_version": 1}, frame_count=72),
]
receipt = render_shot_plan(shots, "cut-v1.mp4", ".shot-cache", max_workers=2, pin_cpus=True)
print(receipt["rebuilt"], receipt["reused"], receipt["total_frames"])
```

A trusted command takes literal argv, not shell syntax. Tokens replace **whole arguments**: `{output}` (required, private MP4), `{source}`, `{params}` (JSON), `{start_frame}`, `{frame_count}`, `{warmup_frames}`, and `{dep:ID}` (a cached clip named in `dependencies`). The renderer must discard its warm-up and write exactly `frame_count` presentation frames, starting at zero in its output. With only `source_path`, Kinocut decodes and trims the requested frame interval, encoding a video-only lossless H.264 shot. Match that stream format when mixing producers.

The key hashes the shot ID, source contents, command argv, parameters, frame range, warm-up and named upstream digests. Declare renderer or environment revisions in `params` if they can change output: Kinocut does not infer files read by a program. Treat sources and render settings as immutable during a run. Cache reuse requires a matching JSON record and SHA-256 of the actual clip. Clip and metadata publish together. Keep the cache dedicated to Kinocut. CPU pinning is best effort; each worker inherits one allowed CPU for its child processes where supported.

Before assembly, every clip must have one video stream and matching codec, pixel format, frame rate, time base, width and height. FFprobe counts decoded frames; a mismatch raises `concat_stream_mismatch` naming the property. FFmpeg splices with `-c copy`; there is no re-encode fallback. The staged output's decoded frame count is checked before publication. The receipt also contains `digests` by shot ID and `output_path`. Use a fresh output filename or the normal explicit `publication.output_operation(overwrite=True)` policy to replace an existing cut.
## Cutfile CLI

A JSON Cutfile can declare a `cached_shots` operation in place of its ordinary workflow ops:

```json
{"name":"trailer","sources":[{"id":"intro","path":"intro.mp4"}],
 "ops":[{"op":"cached_shots","cache_dir":"shot-cache","shots":[
   {"shot_id":"opening","src":"intro","start_frame":24,"frame_count":48}
 ]}]}
```

Run `kino cutfile-render Cutfile.json`. The sole operation splices shots in declaration order; `src` refers to a Cutfile source, and cache, source and output locations stay inside the workspace. A shot can also declare `command` (an argv array). Only pass `--allow-external-producers` after reviewing those programs: they run with your account's permissions. The CLI and saved receipt both expose `shot_plan.rebuilt`, `shot_plan.reused`, digests and frame count. Use distinct output and receipt filenames for a second run without overwrite consent.

The key includes the probed FFmpeg build identity (or the Python API's explicit `encoder_id`) and the source argument supplied to external commands. Splicing checks rational sample aspect ratio and both nominal and average frame rate before running FFmpeg.
