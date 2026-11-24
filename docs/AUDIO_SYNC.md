# Audio sync and mix audition

`kinocut.audio_sync` is a Python API for placing sound effects against a drum stem,
building sample-aligned hits, and comparing premixed alternatives against one picture.
It adds no Python dependencies. Audio decoding uses Python for matching-rate PCM WAV
and FFmpeg for other formats or sample rates; audition export requires FFmpeg.

## Place effects against a drum stem

```python
from kinocut.audio_sync import detect_onsets, place_events_with_stem

onsets = detect_onsets("drums.wav")
events = [
    {"id": "typing", "time_s": 0.100, "mode": "pocket_lock"},
    {"id": "click", "time_s": 0.300, "mode": "both"},
    {"id": "downbeat", "time_s": 1.000, "mode": "avoid_masking", "fixed": True},
]
placed, receipt = place_events_with_stem(events, onsets, fine_grid_step_ms=2)
```

- `detect_onsets` returns sorted `Onset(time_s, band, strength, confidence)` records.
  It measures rising energy on a 1 ms grid in kick (40–150 Hz), snare (180–2000 Hz),
  and hat (5–14 kHz) bands. Strength is band RMS; confidence is a heuristic in
  `[0, 1]`, not a probability. Use a drum stem rather than a full mix. Closely
  spaced attacks in the same band can merge (30 ms minimum separation).
- `pocket_lock` chooses the nearest qualifying hat within ±25 ms by default;
  equal-distance hits favor the earlier one. The default minimum confidence is
  0.35. If the optional fine-grid point would exceed the movement budget, the
  matching onset is used instead. Unmatched events stay put and are listed by index.
- `nudge_off_transients` defaults to a 12 ms clearance from each kick or snare and
  a 15 ms movement budget. Exact clearance is allowed. `early` and `late` prefer
  that side when feasible and otherwise try the other side. `nearest` takes the
  closer clear point (earlier on ties). Fixed or blocked events are reported under
  `unresolved_overlaps` if still overlapping.
- `place_events_with_stem` accepts either a stem path or detected onsets. It runs
  pocket lock **before** masking for `both` (the default). Masking may therefore move
  a snapped event off its onset or fine grid. Each pass enforces its own budget from
  that pass's starting time. `fixed=True` prevents both moves; if masking is enabled
  for the event, it still checks for overlap.

Placement functions return `(copied_events, receipt)` without changing caller
dictionaries. Receipts use input order, include every original and final time, and
identify matching or triggering onsets where applicable.

## Align layered hits to a cut

```python
from kinocut.audio_sync import align_hit_stack

receipt = align_hit_stack(["kick.wav", "sub.wav", "impact.wav"], "stack.wav")
```

Inputs are decoded to mono at the requested sample rate (48 kHz by default). The
detector finds the first sample within 60 dB of the layer's peak, subject to a small
absolute floor. Use dry hits with clean lead-ins; a noisy or reverberant file may
trigger before the intended attack. Silent layers are rejected. Each hit is trimmed
to its detected onset, so place sample zero of the rendered WAV at the event time
using an audio sample offset, not a frame-rounded video offset.

Polarity is tested in input order against the sum so far, using a cascaded low-pass
at 250 Hz. A layer is inverted only if it increases that low-band energy. The receipt
records the original onset, signed offset, inversion, pre-gain peak in dBFS (`null`
for complete cancellation), and applied gain. Output is 16-bit PCM; the default
−0.5 dBFS sample peak limit attenuates the whole stack as needed. Specify
`on_clip="fail"` to refuse publication instead.

## Compare alternate mixes

```python
from kinocut.audio_sync import build_ab_audition

mixes = [
    {"label": "Straight", "audio_path": "straight.wav"},
    {"label": "Pocket locked", "audio_path": "pocket.wav"},
]
receipt = build_ab_audition("picture.mp4", mixes, "comparison.mkv", blind=True)
build_ab_audition(
    "picture.mp4", mixes, "review", mode="review_page", blind=True,
    loop_start_s=2.5, loop_end_s=9.0,
)
```

Export all mixes from the same picture zero point; the builder does not infer
offsets or extend a short mix. Loudness matching defaults to −16 LUFS using
FFmpeg's integrated measurement and a constant gain. For very short or ungated
audio it falls back to RMS dBFS as a rough estimate, reporting the measurement
method and value separately; silence receives no gain. This is not a limiter:
use a lower target or prepare mixes with headroom if gain would clip.

- **Multi-audio:** MKV or MP4 with one stream-copied picture and one AAC stream per
  mix. Switch tracks in the player. The first is selected by default. Loop times
  are receipt metadata in this mode; track switching and looping depend on the player.
- **Review page:** Open `index.html` directly from the new folder and click
  **Enable audio and play**. Use a picture format the browser already supports.
  The page mutes the picture's own sound and schedules all mixes on a shared audio
  clock. Selecting another mix changes gains without restarting the audio or
  seeking the video. Supply both loop endpoints to enable the loop toggle.
  The video is copied once. The folder includes both WAVs and embedded copies of
  their bytes for playback without a server or local-file fetch permissions; use
  short comparison clips to keep browser memory and package size manageable.

In blind mode the player shows `Mix A`, `Mix B`, and so on. The returned receipt
(also saved as `receipt.json` in review mode) contains real labels and source paths;
keep it away from reviewers until the reveal. Blind mode is not anonymization of
the picture or the audio contents. Outputs are published atomically; for review
mode use a fresh destination folder.
