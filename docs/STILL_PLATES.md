# Still / plate editor

Kinocut can treat multi-still packages as first-class media — not by becoming a
Photoshop clone, but by enforcing the same safety posture as video rescue:
**plan → receipt → fail-closed gate**, and **edit before paid re-gen**.

## Order of operations

Always:

1. **Establish** — pick one hero plate (world + light).
2. **Edit beats** — free establish-locked **mean-RGB match** toward that reference
   (`image-edit`). See [Intent policy](#intent-policy).
3. **Sequence match** — one shared RGB gain triple mapping package mean toward
   hero mean (`still-match`). Gains already include exposure (no second luma scale).
4. **Grade** — ordered neutralize (gray-world) → match → optional look LUT last
   (`still-grade`). This is a package cohesion grade, not a full color-science suite.
5. **Gate** — cohesion metrics + contact sheet; fail closed (`still-gate`).

Or one shot: `still-package` runs 2–5.

Do **not** freestyle per-frame auto-WB + tint + cinematic LUT as package authority.
That produces teal fog on dark plates and breaks reel cohesion.

## Install

```bash
pip install "kinocut[image]"
kino doctor   # check still_plates capability
```

Doctor reports:

- image stack present/missing (Pillow)
- free edit backend (`free_establish_match`) vs unavailable
- paid gen backend is **not claimed** until configured

## Commands / tools

| CLI | MCP / Client | Role |
|-----|--------------|------|
| `still-match` | `still_match` | Shared WB/exposure match to hero |
| `still-grade` | `still_grade` | Ordered grade; optional `.cube` last |
| `still-gate` | `still_gate` | Luma spread + shadow green/cyan; contact sheet |
| `image-edit` | `image_edit` | Establish mean-RGB match + plan/receipt (intent is metadata) |
| `still-package` | `still_package` | Full package job graph |

## Intent policy

`image-edit --intent "..."` is **required audit metadata** for agents and humans
(what you meant to do). **v1 pixel path ignores natural language:** it always runs
`free_establish_match` (shared mean-RGB gains toward the reference plate).

Receipts record this honestly:

- `plan.intent_policy`: `"metadata_only"`
- `plan.pixel_ops`: `["establish_mean_rgb_match"]`
- `plan.intent`: the text you passed (for review / learning)

Do not claim that intent drives generative or semantic edits until a backend
exists and `intent_policy` changes. Paid gen remains `prefer=gen` +
`allow_paid_gen=true` and is **unavailable** until configured.

### CLI examples

```bash
# Match package to hero
kino still-match --hero establish.png --inputs a.png b.png c.png --output-dir out/matched

# Ordered grade (signal LUT last — not film cosplay)
kino still-grade --inputs out/matched/*.png --hero establish.png \
  --output-dir out/graded --lut path/to/signal.cube --signal-mode

# Fail-closed cohesion gate
kino still-gate --inputs out/graded/*.png --output-dir out/gate

# Establish match with audit intent (dry-run plan first; intent is metadata)
kino image-edit --source beat.png --reference establish.png \
  --intent "match establish world and light" --output-dir out/edit --dry-run

# Full package
kino still-package --establish establish.png --beats a.png b.png \
  --output-dir out/package
```

### Python client

```python
from kinocut import Client

c = Client()
c.still_match(hero="establish.png", inputs=["a.png", "b.png"], output_dir="out/m")
c.still_gate(inputs=["out/m/a_matched.png", "out/m/b_matched.png"], output_dir="out/g")
```

## Signal LUTs vs film looks

- **Signal-alignment LUTs** (lane LEDs, triad lock): leave near-black / near-white /
  neutrals alone. Pass `--signal-mode` and your `.cube` path.
- **Film-emulation packs** are not the default for still packages and must not be
  sold as cohesion authority.

## Cohesion metrics (gate)

| Metric | Meaning | Default fail |
|--------|---------|--------------|
| `luma_spread` | max−min mean luma across package | > 0.18 |
| `shadow_green_cyan_fraction` | shadow pixels with green/cyan wash | max > 0.22 |

Failed gates name the metric and (when applicable) the worst frame. Re-edit or
re-match; do not claim pass on vibes.

## Cost policy

- Default `prefer=edit`, `allow_paid_gen=false`.
- Paid generative still edit is **unavailable until configured** — agents get a
  typed error, not a silent spend.

## Receipts

Every tool writes a JSON receipt under the output directory with hashes, gains,
stages, and paths. Paths under the user home directory are sanitized to `~` form
so receipts stay shareable.

## Related

- Spec / epic: Forgejo still-plates map (#267) and tickets #270–#276
- Doctor: `kino doctor` → `still_plates` check
- Image palette tools remain separate (`image-extract-colors`, etc.)
