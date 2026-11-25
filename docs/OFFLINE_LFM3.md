# Run Kinocut offline with LFM3

Stage packages and model files before going offline. Set `KINOCUT_OFFLINE=1`
in the environment that starts `kino` or the MCP server. Model providers must
be on loopback (`127.0.0.1`, `::1`, or `localhost`). Kinocut does not discover
servers, try other ports, follow provider redirects, or use proxies for local
requests. Offline mode governs Kinocut's model adapters, not other programs or
servers; run the configured servers offline too.

## Vision and 360 director

Start a local llama.cpp server with the LFM3-VL-2B GGUF and matching `mmproj`.
Use the actual address, port and model alias you configured on that server:

```bash
export KINOCUT_OFFLINE=1
export KINOCUT_VISION_MODE=local
export KINOCUT_VISION_API_STYLE=openai
export KINOCUT_VISION_BASE_URL="http://127.0.0.1:${VISION_PORT}/v1/chat/completions"
export KINOCUT_VISION_MODEL=LFM3-VL-2B
export KINOCUT_360_DIRECTOR=openai_compat
export KINOCUT_360_DIRECTOR_BASE_URL="http://127.0.0.1:${DIRECTOR_PORT}/v1"
export KINOCUT_360_DIRECTOR_MODEL=LFM3-1.7B
```

`VISION_PORT` and `DIRECTOR_PORT` must already be set. The director uses the
server serving the LFM3-1.7B text model; this can be the same endpoint only if
it serves both model aliases. `LFM3_VL_URL` is a fallback for the vision URL.
A loopback `/v1/chat/completions` URL selects the OpenAI shape even when the
style variable is unset. Legacy Anthropic-compatible loopback endpoints still
work for product descriptions; semantic QC uses the OpenAI-compatible route.
Use `KINOCUT_VISION_MODE=off` to disable both routes. Vision QC only assesses
the sampled frames; it is not export approval.

## Transcription and local weights

- **Whisper:** Install `kinocut[transcribe]==2.2.0` and stage the requested `<model>.pt`
  in `${XDG_CACHE_HOME:-$HOME/.cache}/whisper/`. Single-pass, long-form and rescue
  use local paths when offline. Rescue remains pinned to Whisper `base`.
- **LFM3-Audio-2B:** Install `kinocut[lfm3-audio]==2.2.0` and copy a complete, trusted
  `LiquidAI/LFM3-Audio-2B` safetensors snapshot (including its bundled Python
  model code and `audio_tokenizer/`) to a local directory. Set
  `KINOCUT_LFM3_AUDIO_DIR` to that directory and `KINOCUT_ASR_BACKEND=lfm3-audio`,
  or pass `backend="lfm3-audio"` to the Python `ai_transcribe` helper. The loader
  runs the snapshot's Python code; don't use an untrusted snapshot. This backend
  emits one coarse subtitle segment per 30-second audio chunk with speech;
  use Whisper for word timings or the dedicated long-form planning workflow.
- **Upscale:** Stage `FSRCNN_x2.pb` and/or `FSRCNN_x4.pb` in the model cache and
  install `kinocut[upscale]==2.2.0`. Offline upscale uses OpenCV FSRCNN, not the
  automatic Real-ESRGAN loader.
- **Object matte:** Stage the pinned BiRefNet-general ONNX file in the same
  model cache and install `kinocut[object-matte]==2.2.0`.
- **Fonts and NIMA:** Supply a local font path or install a system font. Copy
  NIMA weights to the exact path reported by the scorer if weights are missing.

URL-based media import and the automatic Demucs loader are disabled offline;
use local video and pre-separated WAVs instead.

The model cache is `${KINOCUT_DATA_DIR}/cache/models/` when the data directory
is configured, otherwise `~/.cache/mcp-video/models/`. Missing weight errors
name the exact expected file. `kino doctor` reports readiness and the model
for each feature; use `kino doctor --json` for the `offline_readiness` details.
Doctor checks local configuration and files, not server reachability or model
inference.
