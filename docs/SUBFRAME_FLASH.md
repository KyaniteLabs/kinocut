# Experimental sub-frame flash timing

This is an **untested perceptual hypothesis**. A split changes the brightness of two ordinary frames, not the presentation time of either frame. Whether it feels earlier depends on the display refresh rate and playback conditions. It may just look softer. Importing the dedicated module is the opt-in; normal flashes and timelines do not use it.

```python
from kinocut.subframe_flash import render_subframe_flash_strip, render_subframe_flash

render_subframe_flash_strip("comparison.mkv")
render_subframe_flash("quarter.mp4", target_onset_ms=512.5, fps=20)
```

For `position = target_onset_ms * fps / 1000`, let `N = floor(position)` and `f = position - N`. `compute_subframe_flash_split` returns `{N: (1-f)*peak, N+1: f*peak}`. This preserves total normalized brightness before quantization. A zero offset lights only frame N. In the example, frames 10 and 11 receive 75% and 25%. Rendering uses lossless gray PNG video, writing `round(255 * brightness)` at every pixel; all other frames are black. Independent rounding can change the sum by one code value. Some players may not support PNG video in MP4; use a PNG-capable player or Matroska for review.

The default strip presents offsets `0, 0.25, 0.5, 0.75` in that order. Each segment is `max(3, round(fps))` frames, with its nominal flash at the middle frame. Compare at native speed and note your display's refresh rate. Decoded pixel tests verify the light levels, not a viewer's perception.
