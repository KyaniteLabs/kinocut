# Product and object matte

Cut a **product** (or any non-person object) out of a still or a turntable
video, keep alpha, and drop it on a shop plate. Same public command as the
existing people cutout. No new MCP or CLI name.

Default `hyperframes-remove-background` is **people**
(`u2net_human_seg`). A bottle, shoe, ring, mug, phone, or boxed SKU is not a
person. Pass `--model birefnet-general` for objects.

**Not in published 1.15.0.** Tip ships `kinocut[object-matte]` with a known
frame-count gate, streaming rawvideo decode, scratch-byte caps, stalled-decode
timeouts, and an optional studio-equipment intersection gate. Until the extra
is installed, the object model fails closed. It never falls through to the
people model.

No new MCP/CLI name — still **196 / 167**.

## Who this is for

- Product photographers shooting catalog stills and 360 turntables
- Shop operators compositing SKUs onto a brand plate (Shopify, Woo, custom PDP)
- UGC and marketplace sellers isolating a thing on a kitchen table or sweep
- Studio pipelines that already call Kinocut from an agent, a script, or CI

It is **not** a portrait / talking-head feature. For people, omit `--model`.

## What you need

1. A still (PNG/JPEG) or a video of **one subject** on a reasonably even
   background. Motorized turntables, lightbox sweeps, and tabletop shots are
   the intended inputs.
2. `pip install "kinocut[object-matte]"` for ONNX Runtime. The extra is on
   tip, not in published pip **1.15.0**. The ~1 GB pinned birefnet-general
   ONNX is fetched into `~/.cache/mcp-video/models/` on first object-model
   use, never by `kino doctor`.
3. FFmpeg on `PATH`. `kino doctor` reports an optional `object_matte` check
   (runtime + cached weights + sha256). It never downloads.
4. Optional: a plate image next to your `composite-layers` spec so the cutout
   can be dropped onto a shop background.

**Rejected without falling back:** unknown `--model`, missing extra, missing or
hash-mismatched weights, object-only flags on the people path.

## Surfaces

| Step | MCP | Python `Client` | CLI |
| --- | --- | --- | --- |
| List models (no download) | `hyperframes_remove_background(info=True)` | same | `kino --format json hyperframes-remove-background --info` |
| People cutout (default) | `hyperframes_remove_background(input_path=…)` | same | `kino hyperframes-remove-background SUBJECT.mp4 -o cutout.webm` |
| Product / object cutout | `model="birefnet-general"` | same | `--model birefnet-general` |
| Hole-cut plate | `background_output_path=` | `background_output=` | `--background-output hole.webm` |
| Composite onto a plate | `video_composite_layers` | `composite_layers` | `kino composite-layers --spec layers.json` |

Default agent path: do **not** invent a `video_product_matte` tool. Call the
existing remove-background command with the object model.

## Pick a model

| Model | Subject | Backend | Extra |
| --- | --- | --- | --- |
| `u2net_human_seg` (default) | People, talking heads | Hyperframes | none |
| `birefnet-general` | Products and other objects | Kinocut ONNX | `kinocut[object-matte]` |

`--info` JSON names both models, their subjects, backends, cache flags, and
this guide. It never downloads weights and never shells Hyperframes.

## Cut a product

### CLI

```bash
# See what this install can run (no file, no download)
kino --format json hyperframes-remove-background --info

# Product / object cutout
kino hyperframes-remove-background turntable.mp4 \
  --model birefnet-general \
  --mask-interval 3 \
  -o sku-cutout.webm \
  --background-output sku-hole.webm

# People (unchanged)
kino hyperframes-remove-background interview.mp4 -o speaker.webm
```

`--mask-interval 3` is the recommended setting for product video (infer every
third frame, median window 3). Default is `1` (every frame). Values `> 1` are
object-backend only.

### Python

```python
from kinocut import Client

video = Client()
info = video.hyperframes_remove_background(info=True)
# info["models"]["birefnet-general"]["subject"] == "products-and-objects"

cut = video.hyperframes_remove_background(
    "turntable.mp4",
    output="sku-cutout.webm",
    background_output="sku-hole.webm",
    model="birefnet-general",
    mask_interval=3,
)
```

### MCP (agents)

```text
hyperframes_remove_background(info=true)
hyperframes_remove_background(
  input_path="/abs/path/turntable.mp4",
  output_path="/abs/path/sku-cutout.webm",
  background_output_path="/abs/path/sku-hole.webm",
  model="birefnet-general",
  mask_interval=3,
)
```

Receipt `data` names `model`, `backend` (`hyperframes` or `kinocut-onnx`), and
`output`. Human visual review is still required before a shop publish.

## Drop the cutout on a shop plate

Use existing `composite-layers`. Keep every `src` **inside the spec
directory** — absolute paths such as `/tmp/cutout.webm` fail closed.

Worked example: [examples/product-matte/](../examples/product-matte/).

```bash
# Copy sku-cutout.webm and studio-plate.png next to layers.json, then:
cd examples/product-matte
kino composite-layers --spec layers.json --dry-run --save-layer-plan layer-plan.json
kino composite-layers --spec layers.json -o pdp.mp4 --save-layer-plan layer-plan.json
```

Relative `-o` is resolved against the spec directory. Relative
`--save-layer-plan` is resolved against the output directory. From this
folder, bare `pdp.mp4` and `layer-plan.json` both land here. Do not pass
`examples/product-matte/...` as those outputs or they nest.

Do not edit the compositor engine for this feature. The recipe is docs + a
spec.

## Studio equipment (turntable, stand, tripod, sweep)

A product SKU should not ship with the motorized turntable, clamp, tripod,
lightbox frame, or paper sweep still attached to the silhouette.

Object-backend only, **off by default**:

```bash
kino hyperframes-remove-background turntable.mp4 \
  --model birefnet-general \
  --equipment-overlay equipment.png \
  --fail-if-equipment-on-subject \
  -o sku-cutout.webm
```

`--equipment-overlay` writes a diagnostic PNG (static / low-temporal-variance
heuristic). `--fail-if-equipment-on-subject` aborts when that overlay
intersects the subject (`DEFAULT_EQUIPMENT_SUBJECT_INTERSECTION` in
`defaults.py`). Off by default.

This is generic studio gear, not a brand-specific fixture. People-path flags
error instead of being ignored.

## Hardware and time

Object inference is local ONNX. On Apple Silicon, `device=auto` uses CPU in
v1; `device=coreml` asks for the ORT CoreML EP and errors if it is missing.
A 30 fps catalog spin of a few hundred frames is a long job (tens of minutes
on a laptop CPU). Prefer `--mask-interval 3` for turntables. The frame cap is
`MAX_OBJECT_MATTE_FRAMES` (3600). Timeout is `DEFAULT_OBJECT_MATTE_TIMEOUT`.

CoreML on the Hyperframes **people** path is unrelated. Do not assume it
speeds up `birefnet-general`.

## Fail closed

| Ask | Result |
| --- | --- |
| Omit `--model` | People path. Hyperframes `remove-background`. No `--model` on argv. |
| `--model birefnet-general` without extra/weights | `backend_unavailable` or `dependency_error`. No people fallback. |
| `--model nope` | `validation_error`. No inference. |
| `--mask-interval 3` on the people path | `validation_error` |
| `--equipment-overlay` on the people path | `validation_error` |
| `--info` | Kinocut JSON. No Hyperframes. No download. Input path optional. |

## FAQ

### Why is the default still people?

Most existing callers use this command for talking heads. Changing the default
would silently destroy those cutouts. Products opt in with `--model`.

### Can I pass `--model` through to Hyperframes?

Not in v1. Hyperframes 0.7.96 has no `--model` flag. Kinocut owns the object
backend. If Hyperframes later ships `birefnet-general`, Kinocut can retire
the ONNX inferencer behind the same public command.

### Will this invent a 197th tool?

No. Catalog pins stay 196 MCP / 167 CLI.

### Does this generate a new product photo?

No. It mattes the pixels you already shot. No generative fill, no AI imagery
in the shipped cutout.

### What if the subject is a person holding a product?

Use the people model for the person, or shoot the product alone. This v1
object model is a general object segmenter, not a “hold-out the SKU” picker.

## Related

- Landed on tip via Forgejo #413 (extra + equipment) and #414 (stream/scratch). Parent GH #461 closed.
- Compositor: [CLI_REFERENCE.md](CLI_REFERENCE.md) (`composite-layers`)
- Still / plate cohesion after the cut: [STILL_PLATES.md](STILL_PLATES.md)
- Install extras: [INSTALL.md](INSTALL.md)
