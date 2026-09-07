# Explicit sound crossfades

The Python mix renderer accepts `CrossfadeTransition` entries. Each entry
permits the outgoing dialogue source's real post-roll to overlap the start
of the adjacent incoming dialogue cue. Cue starts, nominal durations,
incoming source alignment, and the authoritative episode duration stay fixed.

```python
from kinocut_sound.mix import CrossfadeTransition, MixRenderer

result = MixRenderer().render(
    timeline=timeline,
    clips=clips,
    transitions=(CrossfadeTransition("outgoing", "incoming", 0.02),),
)
```

For a 20 ms transition, the outgoing WAV must contain at least 20 ms of real
audio after its nominal cue duration. The incoming WAV must contain at least
20 ms within its cue. Both sources must use the renderer's sample rate and
the same stem. Source WAVs start at their respective cue's first sample.
The transition applies the existing linear crossfade curve over the incoming
cue's first 20 ms, quantized to whole samples. It does not shift later audio,
repeat source samples to fabricate handles, or shorten the episode.

Transitions across gaps, silence, chapter markers, incompatible stems, and
missing handles fail with `mix_crossfade_invalid`. An incoming cue may have
only one transition. Chained transitions use original source handles and
produce the same output regardless of request ordering. Seam reports describe
only blends actually applied, with the quantized duration.

The legacy nonzero `crossfade_seconds` argument previously emitted a receipt
without blending audio. It now fails with a migration message; replace it
with explicit transitions and supply the required source handles. Zero keeps
ordinary mixing unchanged. This API does not modify persisted SoundPlan
records or extend the separate synthetic public adapter demo.
