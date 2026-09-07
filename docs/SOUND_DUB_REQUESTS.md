# Local caption speech

`sound_voice_batch` accepts a `SoundDubRequest` to synthesize supplied plain SRT
captions with an installed **eSpeak NG** engine. It retains real speech audio and
a request for the supplied-media mixer. Python, CLI and MCP use the same request.
The existing `plan` argument remains a synthetic tone demonstration; its receipt
is labelled `demo: true`, `synthesis_kind: deterministic_tone`, `audio_retained: false`.

This adapter uses stock formant voices. It does not translate captions, clone a
voice, promise neural voice quality, synchronize lips, or apply mastering. The
caption text must already be in the desired language. Listening review remains
required. Generative and legacy TTS plans remain non-executable records; they
direct callers to this separate hashed request rather than treating discovery
or credentials as execution.

## Request and public surfaces

```python
import hashlib
from pathlib import Path
from kinocut import Client

root = Path(".").resolve()
caption_hash = "sha256:" + hashlib.sha256((root / "captions.srt").read_bytes()).hexdigest()
request = {
    "schema_version": 1,
    "source": {"path": "captions.srt", "sha256": caption_hash},
    "target_lang": "es",
    "output_path": "speech.zip",
}
result = Client().sound_voice_batch(request=request, project_root=str(root))
```

Save that request as JSON for the CLI:

```sh
kino --format json sound-voice-batch --request-json request.json --project-root .
```

The MCP operation is `sound_voice_batch(request=..., project_root=...)`.
`target_lang` supports `en` and `es`, selecting native `en-us` and `es` voices.
An optional `voice` must match that mapping. Unknown fields, malformed requests,
partial real-input arguments and mixed `plan`/`request` modes fail; they do not
select the demonstration fallback.

## Caption timing and limits

Every SRT block must contain an exact timestamp line and nonempty body. Optional
indices must be sequential. Windows must be positive, ordered and nonoverlapping.
Markup, eSpeak `[[...]]` phoneme instructions and control characters other than
newline/tab are rejected. Input is UTF-8; CRLF and a UTF-8 BOM are accepted.

Milliseconds are quantized by integer floor at 22,050 Hz. Each utterance, including
the engine's leading/trailing pauses, must fit its exact sample window. Overflow
fails with `dub_slot_overflow`; audio is not truncated or silently stretched.
The dialogue preserves leading silence, inter-cue gaps and padding through the
last cue's end. The exported mix timeline uses its exact sample count/rate.

Limits are 1 MiB request JSON, 256 KiB captions, 200 cues, 4,000 characters per cue,
40,000 total characters, 600 seconds timeline and 32 MiB cumulative generated WAV.
The assembly memory estimate is capped at 128 MiB. Each engine call has a
10-second timeout inside a 120-second overall deadline checked through parsing,
synthesis and publication preparation. This estimate is not an OS memory sandbox.
Engine diagnostics spool to private temporary files and enter memory through
bounded reads; the adapter does not impose an OS temporary-disk quota.

## Retained files and mixing

The new ZIP contains `dialogue.wav`, `clips/cue-NNNN.wav`, `receipt.json` and
`mix-request.json`. Receipts bind the caption/request hashes, actual media hashes,
engine version, stock voice, settings and sample windows. They omit caption text,
absolute source paths and the installed engine's data directory. Deterministic
mode is qualified to the same installation; a different engine or voice-data
installation may produce a different waveform.

Copy the generated `dialogue.wav` and read `mix-request.json` into a chosen project
directory, preserving any existing files. Then pass that manifest to
`Client().sound_mix_render(manifest, project_root)` or the corresponding CLI/MCP
operation. [Supplied-media mixing](SOUND_MIX_REQUESTS.md) validates the generated
dialogue hash and produces the master/stem bundle. It reports mastering unapplied.

## Availability and interruption

No model is downloaded and no paid or network provider is called. eSpeak NG must
already be on PATH. Version probing is bounded; actual synthesis, exit status,
WAV decoding and sample checks establish success. A PATH match alone does not.
The [upstream command documentation](https://github.com/espeak-ng/espeak-ng/blob/master/src/espeak-ng.1.ronn)
describes the native voice, deterministic mode and stdin/WAV options used here.

Real output publication requires the same descriptor-relative filesystem
capabilities as supplied-media mixing, currently the supported macOS/Linux path.
Input hashes and held-directory reads reject unsafe paths or changed captions;
an existing output is never overwritten. Each invocation owns its private speech
workspace and direct engine child. Timeout or cancellation kills and reaps that
child before cleanup, including repeated async cancellation. Publication is the
final exclusive link: a cancellation after that commit cannot undo a completed
artifact. Abrupt OS termination and a hostile process with the same OS identity
are outside the cleanup guarantee. Legacy synthetic mode remains available on
hosts without the real-publication capability.
