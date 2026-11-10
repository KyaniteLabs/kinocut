# MCP tool-surface baseline

This page documents the byte-level regression baseline that protects the
published MCP tool surface, and the exact procedure that reproduces it.
It exists so that any change to the advertised tools — names, parameters, or
schema bytes — is a conscious, reviewed edit rather than silent drift.

## What is pinned

`tests/fixtures/mcp_tool_surface_baseline.json` captures the surface of the
repository server for the three supported selector modes, launched exactly
the way registries and clients launch it (`python -m kinocut --mcp` over
stdio, MCP initialize + tools/list):

| Mode (`KINOCUT_TOOLS`) | Tools | Input-schema bytes (UTF-8) |
| --- | --- | --- |
| default / `core` (unset) | 18 | 15,603 |
| `all` | 205 | 119,112 |
| `profile:editor` | 114 | 81,812 |

The default surface is the 8-tool hot-path core plus the ten compact-surface
tools (eight typed operation families + `list_operations` +
`describe_operation`, see `docs/MCP_TOOL_FAMILIES.md`). It was captured at
2cf76e98 (published 1.16.5) as 20 tools / 13,947 bytes and regenerated after
the compact surface landed; the **`all` mode rows are byte-identical** across
that regeneration (205 tools, 126,776 bytes, unchanged per-tool digests) —
the legacy full-catalog compatibility proof. `profile:editor` moved
108 / 71,413 → 118 / 81,747 with the same ten additions. #679 then added an
optional `profile` input to `video_quality_check` and `video_release_checkpoint`
(default 24,281 → 24,347; `all` 126,776 → 126,908; editor 81,747 → 81,813).
The hot-path diet (#655) then cut the direct core from 20 tools to 8; the
twelve dropped tools stay reachable as family operations, through
`KINOCUT_TOOLS=all`, and (where their profile carries them) through
`profile:<name>` (default 30 / 24,347 → 18 / 17,429; editor 118 / 81,813 →
114 / 80,152; `all` unchanged). Dropping the titles pydantic derives from
property names ("input_path" -> "Input Path") and the "<name>Arguments"
schema title then cut every mode without changing a property, type or
validation rule (default 17,429 → 15,335; `all` 126,908 → 98,000; editor
80,152 → 63,857). Moving each docstring's Args help onto its parameter
(#719) then grew the schemas (default 15,335 → 17,021; `all` 98,000 →
128,297; editor 63,857 → 87,550) while the default tools/list response
shrank, because the same text no longer appears in both the description and
the schema (default tools/list 26,264 → 26,153 B). Shorter family dispatcher
descriptions then cut default tools/list to 24,649 B (schemas 17,021 →
16,373; editor 87,550 → 86,902; `all` unchanged). A shorter `overwrite`
description then cut default tools/list to 23,839 B (schemas 16,373 →
15,563; `all` 128,297 → 119,072; editor 86,902 → 81,772). Dropping
the direct tools' "Pass X as …" sentences, which repeated their parameter
descriptions, cut default tools/list to 22,716 B.

Per tool, the fixture records the name, the UTF-8 byte length and SHA-256 of
the canonical input-schema JSON, the sorted property names, the required
parameters, and the registry module and profile tags. The mode total is the
sum of the per-tool byte lengths.

Serialization contract (must stay identical everywhere it is computed):

```python
len(json.dumps(input_schema, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
```

This was verified byte-identical between the mcp SDK's internal FastMCP
`parameters` and the wire `inputSchema`, and across mcp SDK 1.28.1 and
1.30.0 (the pinned range is `mcp>=1.28.1,<2`).

## How it is enforced

`tests/test_tool_surface_baseline.py` re-derives the surface three ways and
compares each against the fixture:

1. in-process registration (`configure_tool_surface` + `mcp.list_tools`),
2. a cold stdio subprocess handshake — the bytes a real client sees,
3. the declarative tables in `kinocut/tool_registry.py` (205 names across 25
   modules, one module per tool, core tags matching the default surface).

The headline numbers (18/15,603, 205/119,112, 114/81,812) are also asserted
literally so a fixture edit cannot pass unnoticed.

`tests/test_tool_surface_compat.py` protects the behaviors around the
surface: deterministic `search_tools` discovery that never invents names and
never leaks hidden tools into the registered surface, legacy facade imports
(`from kinocut.server import <hidden tool>`) that keep working with unchanged
parameters and outcomes while the wire stays fail-closed for hidden tools,
and cold-process mode isolation (default == core, `all` == registry,
profiles additive on core, unknown profile aborts startup).

## Regenerating after an intentional change

```bash
python scripts/mcp_surface_baseline.py --regenerate-baseline
```

The script rewrites the fixture deterministically (no timestamps; the git
commit, source version, and SDK version are recorded for provenance). Review
the diff — every per-tool byte or hash change must be explainable — and land
it in the same PR as the schema change that caused it.

Committed provenance is portable: `launch.cwd` is the repo-relative root
(`.`), never an absolute checkout path, and the script refuses
(`assert_portable_provenance`) to write a baseline whose content embeds
operator home-directory paths (POSIX and macOS user-root prefixes are both
checked), so regeneration on any machine produces identical bytes. Exact host
paths belong only in private, uncommitted capture evidence.
`test_baseline_fixture_provenance_is_portable` guards the committed fixture
against regressions.

The regression tests are hermetic against the ambient environment: they pin
or strip `KINOCUT_TOOLS` internally and pass identically when the suite runs
with the variable unset, `all`, or `profile:editor` exported. That
no-argument configuration *honors* `KINOCUT_TOOLS` at call time remains the
production contract and is asserted explicitly in
`test_no_argument_calls_honor_the_controlled_environment`.

## Measuring other integrations

The same script captures what an already-configured integration actually
advertises, without touching its configuration:

```bash
python scripts/mcp_surface_baseline.py \
  --command <exact launcher command> \
  --arg <arg> --env K=V \
  --out capture.json
```

The capture records the server-reported version from the MCP handshake, the
tool count, and the schema bytes under the serialization contract above.
Note that the handshake reports the *installed distribution* version, which
can differ from a source checkout actually launched; the script records both.
A `uvx kinocut==1.16.5` capture matches the released 1.16.5 default surface
byte-for-byte (20 tools / 13,947 bytes) — that surface predates the compact
family layer in this checkout.

Registrations counts computed from `kinocut.tool_registry` (like the table
above) describe this repository's surface. They are not measurements of any
particular host or client configuration — measure the real integration with
the capture command before quoting numbers for it.
