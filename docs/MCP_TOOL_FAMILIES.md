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
surface is now **29 tools / 23,588 bytes** (≤ 40 tools and ≤ 25% of the
full-catalog bytes, the accepted design budget) while reaching all 204
operations plus `search_tools`.

## The surface

Default mode registers the unchanged 20-tool core diet **plus**:

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

Every family tool takes `operation` (a closed enum of its member operation
names — typos and cross-family mistakes fail validation), `params` (the
operation's exact arguments), and the standard strict-boolean `overwrite`
consent every Kinocut handler exposes. Profiles are additive on the compact
surface: `profile:editor` is 117 tools / 81,054 bytes.

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
* **Handler errors are identical** (same `success/error` dicts, same codes).
* **Argument rejections produce the same structured payload** — `Invalid MCP
  tool parameters. Use tools/list to inspect the accepted parameters.`
* The strict `overwrite` consent flows from the family call into the
  dispatched operation through the existing output-policy ContextVar; an
  `overwrite` inside `params` takes precedence for that operation.
* Policy booleans (`video_mix_audio.keep_source`,
  `video_repurpose.include_release_checkpoint` / `start_job`) are enforced
  identically.

Two transport-level differences are inherent to dispatching through a
wrapper tool and are asserted in `tests/test_tool_families.py` rather than
hidden: a rejected *family-level* argument (unknown `operation`, non-object
`params`) sets `isError=true` exactly like the direct wire path, while a
rejected *inner* argument reports the identical structured payload without
the `isError` flag; and retry hints name the family tool that was called
(e.g. `retry with call video_edit_ops ...`), which keeps eyes-free retries
working.

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

Family tools themselves carry conservative **worst-case** MCP annotations
(`readOnlyHint=false`, `destructiveHint=true`, `idempotentHint=false`,
`openWorldHint=false`) because every family contains operations that write
rendered artifacts; `list_operations` is annotated read-only/idempotent.

## Guardrails

* The family partition is declared over registry modules and fails closed at
  import time if it ever stops covering the registry exactly once
  (`kinocut/tool_families.py`).
* Hidden direct names stay fail-closed on the wire in default mode —
  `video_filter` remains an import error over MCP while
  `video_effects_ops(operation="video_filter", ...)` works.
* The byte-level regression fixture and headline numbers
  (`docs/MCP_TOOL_SURFACE_BASELINE.md`) pin all three modes; the `all`-mode
  rows double as the legacy-compatibility proof.
