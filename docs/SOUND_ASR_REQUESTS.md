# Supplied-audio ASR verification

`sound_qa_asr` recognizes hashed local audio and compares its actual words with a
separate hashed UTF-8 reference. It uses an installed OpenAI Whisper runtime and
cached `base.en` or `base` checkpoint. Missing dependencies fail without downloads.
The recognizer never receives the reference text.

```json
{
  "schema_version": 1,
  "source": {"path": "dialogue.wav", "sha256": "sha256:<64 hex digits>"},
  "reference": {"path": "script.txt", "sha256": "sha256:<64 hex digits>"},
  "language": "en",
  "model": "base.en",
  "output_path": "recognition.zip"
}
```

Supply `project_root` explicitly. Paths are relative and output must be new.
Input is mono PCM16 WAV, 3–120 seconds, 8–48 kHz. The reference is plain text,
not SRT, bounded to 32 KiB and 2,048 normalized words. Spanish requires `es` and
`base`; `base.en` supports English only.

```python
result = client.sound_qa_asr(request=request, project_root=project_directory)
```

```sh
kinocut --format json sound qa-asr --request-json request.json --project-root ./episode
```

The flat command is `sound-qa-asr`; MCP uses `sound_qa_asr` with the same request
and root. Real requests reject legacy hash/duration intent. Python/MCP defaults
`script_hashes=None` and duration `1.0` count as omitted; CLI rejects explicitly
supplied legacy flags. Legacy-only calls remain labelled `demo=true` and
`verification_status=simulated`; they do not recognize or verify audio.

The ZIP retains actual text and timed segments in `transcript.json`, plus a
receipt binding input, reference, request, transcript and model identities,
backend version, exact decoding settings and comparison. Public results contain
metrics and archive identity; transcript text stays in the local artifact.

Comparison uses Unicode NFKC, casefolding and alphanumeric words. It records the
Unicode version and deterministic word Levenshtein substitutions, deletions and
insertions. WER divides total edits by reference words and may exceed 1. Only
exact normalized matches set `ok=true`. Valid mismatches, including empty
recognition, retain evidence with `ok=false`; execution/validation failures
publish nothing. A match does not establish pronunciation, speaker identity,
timing or listening quality. Human acceptance remains required.

Recognition uses CPU float32, two Torch threads, fixed decoding settings and
linear interpolation to 16 kHz, without spawning a media decoder. Discovery tries
the current Python environment, then a regular installed Whisper launcher with
a single absolute Python shebang. The executable target is inspected while the
virtual-environment entry path is preserved. Installed software and its registry
are trusted local dependencies, not independently authenticated.

Cached checkpoints are bounded to 160 MiB and copied through a held regular file
with identity, digest and deadline checks. Private staging is bounded to 192 MiB;
the 1 GiB working-memory estimate is not an OS memory limit. The total deadline is
180 seconds, diagnostics 64 KiB and retained output 1 MiB. Cancellation and timeout
reap the owned process and remove private files and unpublished staging. An
async checkpoint precedes exclusive publication. Unsupported descriptor-relative
filesystem operations fail closed; this is not a Windows portability claim.
