# 360 dual-cam assembly

Turn one **stitched equirectangular 360 MP4** into a normal 16:9 or 9:16
two-cam edit. Camera-agnostic: Insta360 X2–X5, Ricoh Theta, GoPro MAX,
DJI Osmo 360, or any other 2:1 / spherical-tagged export. Kinocut treats
the sphere as **virtual cameras**, writes a reviewable `360_assembly_plan`,
waits for approve/reject, then extracts with FFmpeg `v360`.

X4 is one example, not a requirement. No vendor SDK. One ffprobe, no extra
decode until you approve a render.

**Published in Kinocut 1.14.0** (`pip install kinocut`).
No new MCP or CLI name — still **196 / 167**.
Not an optimized-AI-director claim. The model never writes pixels.

Design/PRD: [2026-08-13-x4-360-assembly-design.md](superpowers/specs/2026-08-13-x4-360-assembly-design.md) ·
[2026-08-13-x4-360-assembly-prd.md](superpowers/specs/2026-08-13-x4-360-assembly-prd.md)

## What you need

1. Export a **stitched equirectangular MP4** from the camera's own app
   (Insta360 Studio/app, GoPro Player, Ricoh Theta, DJI, etc.).
2. FFmpeg with `v360` on `PATH` (`kino doctor`).
3. A goal that mentions 360 / equirect / spherical / Theta / Insta360 /
   GoPro Max / Osmo 360 / desk+screens / table+tarot, **or** an explicit Client call.

**Rejected (suffix only, no decode):** `.insv` (`not_insv_export`), GoPro `.360` (`not_raw_360`).
Phone clips and other non-2:1 sources without spherical tags (`not_360_equirect`).
Kinocut does **not** stitch dual-fisheye, cubemap, or vendor RAW.

## Surfaces

| Step | MCP | Python `Client` | CLI |
| --- | --- | --- | --- |
| Propose | `video_intent` with `goal=` + `source=` | `propose_360_assembly` | No 360 flag. `kino intent` only routes verbs. |
| Storyboard stills | same propose path, or Client | `storyboard_360_assembly` | — |
| Approve / reject | `video_review_decide` on the `360_assembly_plan` | `decide_360_assembly` | `kino review-decide` is the watching floor only — it does **not** approve a sphere plan. |
| Render | `video_review_decide` with `output_path` after approve | `render_360_assembly` | — |

Default agent path: do **not** list 196 tools. Call `video_intent`.

## Propose → approve → render

### MCP (agents)

```text
video_intent(
  verb="reformat_vertical",
  goal="desk 360 split 9:16",
  source="/abs/path/x4-export.mp4",
)
```

A 360/desk/table goal attaches `sphere_plan` (`artifact_kind: 360_assembly_plan`)
and sets `next_action` to `review_then_sphere_render`. Inspect cameras, layout,
and any storyboard stills. Then:

```text
video_review_decide(
  review_run=<that 360_assembly_plan>,
  decision="approve",   # or accept / reject
  output_path="/abs/path/desk-split.mp4",
)
```

Approve without `output_path` only marks the plan `approved`.
Reject never renders. Render without approve fails closed (`human_apply_required`).

### Python

```python
from kinocut import Client

video = Client()
plan = video.propose_360_assembly(
    "/abs/path/x4-export.mp4",
    goal="desk 360 split 9:16",
    storyboard_dir="/abs/path/360-board",
)
# Show plan["stills"] and plan["cameras"] before deciding.
approved = video.decide_360_assembly(plan, "approve")  # or reject
receipt = video.render_360_assembly(approved, "/abs/path/desk-split.mp4")
```

`goal` infers preset / layout / aspect when those kwargs are omitted.
You can also pass `preset=`, `layout=`, `aspect=` explicitly.

## Presets and layouts

| Preset | Virtual cameras | Default layout | When inferred |
| --- | --- | --- | --- |
| `front_back` | `front` (yaw 0) + `back` (yaw 180) | `split` | Generic 360 goal with no desk/table cue |
| `desk` | `talent` (yaw 0) + `screens` (yaw 180) | `split` | desk / screens / code |
| `table` | `talent` (yaw 0) + `table` (yaw 180, pitched down) | `switch` | table / tarot / cards |

Layouts: `split` · `switch` · `pip` · `single`.
Aspects: `16:9` (1920×1080) or `9:16` (1080×1920).

Goal tokens (case-insensitive):

- Sphere: `360`, `equirect`, `spherical`, `insta360`, `theta`, `x2`–`x5`, `gopro max`, `osmo 360`
- Desk: `desk` plus `screen` / `split` / `pip` / `code`
- Table: `table` plus `tarot` / `card` / `switch` / `split`
- Vertical: `9:16`, `vertical`, `short`, `reel`

## Director plug (optional)

Heuristic cameras are the default. A director may **propose** a plan only.
Render always uses the approved JSON.

| Kind | IDs |
| --- | --- |
| Local | `ollama`, `lmstudio`, `openai_compat` |
| Cloud (opt-in) | `openai`, `anthropic`, `gemini`, `openrouter` |

```bash
export KINOCUT_360_DIRECTOR=ollama
export KINOCUT_360_DIRECTOR_MODEL=qwen-vl
# optional: KINOCUT_360_DIRECTOR_BASE_URL=http://127.0.0.1:11434
```

Cloud requires `allow_cloud=True` or `KINOCUT_360_DIRECTOR_ALLOW_CLOUD=1`.
Without opt-in: `cloud_execution_denied`.
Bad director JSON falls back to heuristic (`unavailable: true`) or
`capability_unavailable`. `kino doctor` reports `sphere_director` (probe only, no network).

Pass `director=`, `model=`, `base_url=`, `allow_cloud=` on `propose_360_assembly`,
or inject `propose=` for tests / custom adapters.

## Fail-closed codes

| Code | Meaning |
| --- | --- |
| `not_insv_export` | `.insv` — export a stitched equirect MP4 first |
| `not_raw_360` | Other raw 360 containers (e.g. GoPro `.360`) |
| `not_360_equirect` | Not ~2:1 and no spherical metadata |
| `invalid_sphere_preset` | Use `desk` or `table` |
| `invalid_sphere_layout` | Use `single`, `split`, `pip`, or `switch` |
| `invalid_sphere_aspect` | Use `16:9` or `9:16` |
| `invalid_sphere_decision` | Use `approve`, `accept`, or `reject` |
| `human_apply_required` | Render called before approve |
| `cloud_execution_denied` | Cloud director without opt-in |
| `capability_unavailable` | Director returned unusable JSON |

Quality gate after render uses the same score-80 ship seam as other exports
unless `allow_fail=True`. Synthetic fixtures can score low; that is a gate, not a silent pass.

## Not in v1

- Insta360 Studio / SDK stitch
- Continuous auto-steer or face-orbit around the sphere
- A dedicated `video_360_*` MCP tool or `kino 360` CLI
- Claiming a published PyPI version until the next release cut
