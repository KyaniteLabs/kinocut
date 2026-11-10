# MCP typed operation families

The default (and profile) MCP surfaces expose a **compact family layer**: a
small set of typed dispatch tools that reach **every registry operation**
without advertising one schema per operation. The full direct surface remains
available with `KINOCUT_TOOLS=all`.

## Why

The 1.16.5 tool diet pinned the default surface at 20 direct tools / 13,947
input-schema bytes, and the full catalog is 205 tools / 126,776 bytes — too
large to advertise to a model, and the diet left 185 operations unreachable
over the wire in default mode. The family layer closes that gap: the default
surface was **30 tools / 24,347 bytes** (≤ 40 tools and ≤ 25% of the
full-catalog bytes, the accepted design budget) while reaching all 204
operations plus `search_tools`. The hot-path diet (#655) then cut the direct
core from 20 tools to 8, because every dropped tool is already a family
operation: the default is now **18 tools / 17,429 bytes**.

## The surface

Default mode registers the 8-tool hot path (`video_info`, `video_trim`,
`video_merge`, `video_add_text`, `video_add_audio`, `video_extract_frame`,
`video_shorts`, `video_doctor`) **plus**:

| Tool | Operations | Registry modules |
| --- | --- | --- |
| `video_edit_ops` | 43 | basic, advanced, media |
| `video_effects_ops` | 28 | effects, glitch, glitch_shader |
| `audio_ops` | 17 | audio, sound |
| `video_ai_ops` | 15 | ai, aivideo |
| `image_ops` | 8 | image |
| `video_qc_ops` | 15 | inspection, doctor, guardrails, motion_acceptance, release |
| `video_plan_ops` | 51 | intent, creation, postrescue, repurpose, rescue, workflow |
| `platform_ops` | 27 | hyperframes, revideo, shorts |
| `list_operations` | — | on-demand discovery (families, verbs, required params, annotations) |
| `describe_operation` | — | on-demand full inputSchema + callability for one operation |

Every family tool takes `operation` (a closed enum of its member operation
names — typos and cross-family mistakes fail validation), `params` (the
operation's exact arguments), and the standard strict-boolean `overwrite`
consent every Kinocut handler exposes. Profiles are additive on the compact
surface: `profile:editor` is 114 tools / 81,772 bytes.

`KINOCUT_TOOLS=all` is the **legacy full-catalog surface** and stays exactly
the 205-name registry, byte-identical to the pre-family baseline (all
per-tool schema digests unchanged); the family tools are hidden there, where
every operation already has its direct tool.

## Dispatch semantics

A family call runs the *exact registered FastMCP tool object* of the target
operation, after the same wire-path argument validation
(`kinocut.server_tool_contracts.validate_tool_arguments`) the direct call
runs. Therefore:

* **Success payloads are identical** to the direct call, byte for byte.
* **Handler error cores are identical** (same `success/error` shapes, same
  codes, same message text); the retry *hint* at the end of a message is
  retargeted to the family surface (below).
* **Argument rejections produce the same structured rejection** with
  family-specific guidance: `Invalid MCP tool parameters for operation
  '<operation>'. Use describe_operation to inspect its accepted parameters.`
* The strict `overwrite` consent is **forwarded explicitly**: a family-level
  `overwrite=true` reaches the operation whenever `params` does not carry its
  own `overwrite` (the inner SDK argument model materializes a default that
  would otherwise silently reset it). An explicit `overwrite` inside `params`
  takes precedence for that operation; non-media files stay protected either
  way.
* Policy booleans (`video_mix_audio.keep_source`,
  `video_repurpose.include_release_checkpoint` / `start_job`) are enforced
  identically.

Transport-level differences inherent to dispatching through a wrapper tool
are asserted in `tests/test_tool_families.py` rather than hidden: a rejected
*family-level* argument (unknown `operation`, non-object `params`) sets
`isError=true` exactly like the direct wire path, while a rejected *inner*
argument reports the identical structured payload without the `isError` flag.

### Retry hints name what you can actually call

Errors raised under family dispatch append a retry invocation that names the
family tool with the selected operation, e.g. `retry with call
video_ai_ops(operation="video_ai_remove_silence", params={...}) with
corrected parameters (MCP) / run kino video-ai-remove-silence with corrected
flags (CLI)`. CLI routes are **derived from the selected operation and
verified against the real `kino` parser** — a family tool never invents a
`kino` subcommand, and an operation without a CLI route gets an MCP-only
hint. Tool-independent guidance (`overwrite=true (MCP) / --overwrite (CLI)`,
`a new output_path`) is valid under the family surface and passes through
unchanged. The discovery tools (`list_operations`, `describe_operation`) are
MCP-only, so their hints never mention a CLI route.

## Discovery and verbs

`list_operations(family=None, query=None)` loads the catalog lazily (like
`search_tools`) and restores the selected surface afterwards. Each operation
row reports:

* `family` and `verb` — the verb is the operation's registry name with its
  domain prefix stripped (`video_ai_transcribe` → `ai_transcribe`),
  deterministic and total over the catalog;
* `required_params` and the first-line description;
* `annotations` — **only the side-effect hints the operation's registration
  actually declares** (today: the nine media/edit operations `video_add_audio`,
  `video_convert`, `video_crop`, `video_export`, `video_fade`, `video_merge`,
  `video_rotate`, `video_speed`, `video_watermark`). Undeclared operations
  report `null`; nothing is guessed;
* `intent_verbs` / `intent_mutates_media` — links to the canonical
  `video_intent` verb table where one routes to the operation.

`describe_operation(operation="<name>")` then returns that operation's
**complete `inputSchema`** — every optional argument with its type, default
and nested definitions, byte-for-byte the schema its direct tool advertises
in `all` mode — plus `required_params`, declared annotations, the `call`
block naming the family tool that dispatches it, and the verified CLI route
when one exists. A hidden operation's full contract is therefore always one
discovery call away, while the advertised surface stays compact.

Family tools themselves carry conservative **worst-case** MCP annotations
(`readOnlyHint=false`, `destructiveHint=true`, `idempotentHint=false`)
because every family contains operations that write rendered artifacts.
`openWorldHint` follows the audited `FAMILY_OPEN_WORLD` table
(`kinocut/tool_families.py`): `video_ai_ops`, `image_ops`,
`video_plan_ops`, `video_qc_ops` and `platform_ops` are open-world —
`video_analyze` downloads HTTP(S)/yt-dlp sources, `video_ai_upscale` and
`hyperframes_remove_background` fetch model weights,
`image_analyze_product(use_ai=true)` calls a configured vision endpoint,
`video_qc_vision` under the supported explicit remote configuration
(`KINOCUT_VISION_MODE=remote` + `KINOCUT_VISION_MODEL` + `ANTHROPIC_API_KEY`)
POSTs sampled keyframes to the fixed Anthropic origin, `video_doctor` can
invoke the `npx --yes hyperframes --version` package launcher (a hyperframes
CLI on PATH or the supported `MCP_VIDEO_HYPERFRAMES_COMMAND` prefix — npx may
fetch a missing package from the npm registry before executing it), and the
revideo paths run `npm ci` — while the remaining three families are closed
with configuration-audited evidence (local-only engines and local
availability probes; `kinocut_sound`'s ASR copies only digest-verified
*cached* Whisper models and refuses uncached ones). The provider policy and
its off default are unchanged: unset/off makes zero provider attempts, and
with no hyperframes on PATH and no configured command doctor performs zero
launcher calls. `list_operations` and `describe_operation` are annotated
read-only/idempotent/closed.

## Guardrails

* The family partition is declared over registry modules and fails closed at
  import time if it ever stops covering the registry exactly once, and every
  family must carry an audited open-world verdict
  (`kinocut/tool_families.py`).
* Hidden direct names stay fail-closed on the wire in default mode —
  `video_filter` remains an import error over MCP while
  `video_effects_ops(operation="video_filter", ...)` works.
* The byte-level regression fixture and headline numbers
  (`docs/MCP_TOOL_SURFACE_BASELINE.md`) pin all three modes; the `all`-mode
  rows double as the legacy-compatibility proof.
