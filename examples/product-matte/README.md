# Product matte → shop plate

Generic recipe for any catalog SKU: cut the object, then composite it onto a
studio plate with existing `composite-layers`.

Do **not** put absolute paths (`/tmp/...`, home directories) in `layers.json`.
Every `src` must live **in this directory** next to the spec.

Relative compositor `-o` and `--save-layer-plan` values are joined to this
directory. Run the commands from here (or pass bare filenames).

## 1. Cut the product

```bash
pip install "kinocut[object-matte]"
kino --format json hyperframes-remove-background --info

cd examples/product-matte
kino hyperframes-remove-background /abs/path/to/turntable.mp4 \
  --model birefnet-general \
  --mask-interval 3 \
  -o sku-cutout.webm \
  --background-output sku-hole.webm
```

Copy or render your brand plate into `studio-plate.png` (or replace the
filename in `layers.json`). Media is gitignored; this folder only ships the spec.

## 2. Dry-run the stack

From this directory:

```bash
kino composite-layers --spec layers.json \
  --dry-run --save-layer-plan layer-plan.json
```

Inspect the layer plan (source hashes, filtergraph, timing). Render only after
it looks right:

```bash
kino composite-layers --spec layers.json \
  -o pdp.mp4 --save-layer-plan layer-plan.json
kino video-quality-check pdp.mp4
```

Human look before a shop publish.

## Works for

Jewelry on a motorized turntable, shoes on a sweep, bottles on a lightbox,
phones on a table, ceramics on a banding wheel, boxed SKUs on a kitchen table.
The command does not care which shop you run.

Guide: [docs/PRODUCT_MATTE.md](../../docs/PRODUCT_MATTE.md).
