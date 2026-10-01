# Signal analysis and ASR preprocessing — implementation evidence

Source frozen 2026-10-01, baseline `e9f6cac77cb390c73c919bdcd385b775a6a3c7ef`. Source-bound original package was extracted with `git archive` into a task-owned directory, without a checkout/worktree or executing external PR code. `manifest.json` records original/current source hashes and evidence hashes. Actual backend is Debian FFmpeg/FFprobe **7.1.5-0+deb13u1**, Python **3.12.14**, NumPy **2.4.5**.

## Measured frontend behavior

| Path / identical input | Original parent peak RSS | Fixed parent peak RSS | Fixed child peak RSS | Original wall | Fixed wall |
|---|---:|---:|---:|---:|---:|
| 120 s, 96×64, 240 fps signalstats (28,800 frames) | 94.62 MiB | 42.98 MiB | 42.20 MiB | 12.212 s | 11.580 s |
| 120 s mono PCM16, 48 kHz → 16 kHz | 205.85 MiB | 56.54 MiB | 49.09 MiB | 0.162 s | 0.302 s |
| 120 s mono PCM16, 44.1 kHz → 16 kHz | 193.38 MiB | 55.67 MiB | 48.22 MiB | 0.104 s | 0.413 s |

These are individual fresh-process trials under shared CPU load, not robust latency comparisons. Parent RSS dropped about **55%** for signalstats and **71–73%** for the measured ASR frontend. FFmpeg adds its own process and startup cost; child historical maximum is separate, including process launch, and must not be described as a simultaneous aggregate memory measurement. The signal fixture/hash/window is identical and **all eight returned means match exactly** in this trial. The original JSON capture path was actually run from the archived original package, not estimated.

ASR numbers cover original interpolation expressions vs installed FFmpeg version/conversion, staging, parent exact-length validation and NumPy float32 loading. Optional Torch/Whisper imports, checkpoints, model construction, recognition, reference comparison and archive publication are excluded. This establishes a frontend memory improvement, not a total-inference memory or latency claim. Both 120 s controls produce exactly **1,920,000** float32 samples. Output waveforms intentionally change; no byte-equivalence claim applies.

The deterministic 48 kHz composite 1 kHz + 11 kHz tone control, measured after excluding FIR edges, preserves passband amplitude (0.366221 original vs 0.366213 fixed). The undesired aliased 5 kHz amplitude drops from **0.366212 / −8.73 dBFS** to **0.000002648 / −111.54 dBFS**. This verifies anti-aliasing on this control; there is no speech corpus, listening acceptance or WER claim. Full inputs and exact calculation are in `spectrum.py`/`spectrum.json`.

## Runtime behavior and safety boundaries

- Signalstats uses compact frame output, compensated running means and bounded `array('d')` storage only for legacy sample/median consumers. Cache source identity/window/retry/LRU behavior remains unchanged. FFmpeg fallback streams `metadata=mode=print:file=-` stdout and retains existing 8-bit limited-range filtering/heuristics. HDR remains a scope warning, not HDR acceptance.
- Reader ceilings: 1,000,000 measured frames, 4,096 bytes per line, 512 MiB total stdout, 64 KiB total stderr, and only 4 KiB retained diagnostics. Overflow, malformed output, nonzero exit or deadline cannot return partially successful analysis. Legacy nonfinite numeric values remain skipped as before.
- A single 120 s deadline covers child execution and pipe EOF. POSIX owns an isolated process group, terminates inherited pipe writers and reaps the direct child. An orphan descendant can remain a zombie until the host init reaps it; it cannot continue executing. Repeated interrupts still complete child/reader cleanup.
- Windows anonymous pipes use cancellable `PeekNamedPipe` polling before small reads, so an inherited handle cannot strand reader joins after the deadline. Windows guarantees direct-child reap and bounded reader cleanup; no Windows Job Object/descendant-termination guarantee is claimed. Local tests validate polling cancellation/EOF/split-line control flow with an injected availability seam; the actual WinAPI was not exercised on this Linux host.
- ASR selects an installed FFmpeg through the existing sound binary resolver, resolves an absolute executable path, never downloads a backend, and runs version/conversion through the existing owned synchronous/asynchronous meter runner. Its existing whole-job remaining deadline, bounded diagnostics and cancellation encompass preprocessing. The native 16 kHz path bypasses FFmpeg.
- Public result/receipt keys and private transcript policy remain intact. `backend.resampling` explicitly identifies `ffmpeg-swr-bandlimited-16khz-v1;ffmpeg=<actual version>` or native PCM normalization. Filter parameters are centralized defaults. Output length is independently checked before recognition/publication; nonfinite float32 preprocessing is rejected by the worker.
- ASR source reads are capped at **11,585,536 bytes** (120 s × 48 kHz × mono PCM16 plus 64 KiB metadata). An optional validator on the existing descriptor-safe reader checks only ≤16-byte RIFF/chunk fields and seeks over PCM before allocation. It checks mono PCM16/rate/alignment/declared duration, bounds all metadata/header overhead, and preserves the opened descriptor, resets its position, and retains full-read identity/hash verification. General mix input's 268 MiB policy and publication APIs remain unchanged. Buffers are released before checkpoint/preprocessing stages.

## Verification

Meaningful tests cover actual subprocess overflow/error/timeout/repeated interrupt, POSIX inherited-writer group termination, Windows polling cancellation/EOF, unchanged cache lifecycle, real lossless 8/10/12-bit/full/limited-range equivalence, actual passband/anti-alias behavior, 20 short fractional-ratio output counts, maximum legal duration/odd metadata, sparse oversize rejection before validator/read, hostile/truncated/duplicate/unaligned headers, same-descriptor offset/hash/mutation checks, invalid/truncated/oversized/missing/nonzero preprocessing, preprocessing-specific timeout/repeated async cancellation, explicit missing FFmpeg and native-rate bypass, privacy/exclusive publication, and existing transport/mix compatibility.

Final durable test/exit logs are adjacent. Pinned Ruff **0.15.11** validates all assigned runtime/test files. No source edits, commits, pushes or external messages follow the freeze.
