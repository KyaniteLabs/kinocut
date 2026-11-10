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

| Mode (`KINOCUT_TOOLS`) | Tools | Input-schema bytes (pinned) | Full `tools/list` JSON |
| --- | --- | --- | --- |
| default / `core` (unset) | 18 | 14,759 | 21,771 |
| `all` | 206 | 119,053 | 177,842 |
| `profile:editor` | 115 | 81,259 | 121,119 |

The fixture pins input-schema bytes. The last column is the whole `tools/list`
payload (names, descriptions, annotations and schemas) in the same compact
serialization: what a client actually loads into context. It is not pinned;
`--regenerate-baseline` prints it.

The default surface is the 8-tool hot path plus ten compact-surface tools: eight
typed operation families, `list_operations` and `describe_operation` (see
[MCP_TOOL_FAMILIES.md](MCP_TOOL_FAMILIES.md)). `all` lists the 206 registry tools
by name and hides the families.

### How the numbers moved

- Published 1.16.5 (2cf76e98): default 20 tools / 13,947 schema bytes; `all` 205.
- Family layer: default 30 tools, every registry operation reachable.
- Hot-path diet (#655): direct core 20 → 8 tools; default 18 tools.
- Schema titles dropped, `Args` help moved onto parameters (#719), shorter family
  and `overwrite` descriptions, read-only tools stop offering `overwrite`, longest
  texts trimmed: default `tools/list` 26,264 → 21,722 B.
- `video_review_card` (#723) added one operation: default 21,761 B, `all` 206, editor 115.
- `search_tools` and `video_info_detailed` stop offering `overwrite` (#747).

The test docstring in `tests/test_tool_surface_baseline.py` keeps the
step-by-step byte history.

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
3. the declarative tables in `kinocut/tool_registry.py` (206 names across 25
   modules, one module per tool, core tags matching the default surface).

The headline numbers (18/14,759, 206/119,053, 115/81,259) are also asserted
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
A capture of the released 1.16.5 package matched its default surface
byte-for-byte (20 tools / 13,947 bytes) — that surface predates the compact
family layer in this checkout.

Registrations counts computed from `kinocut.tool_registry` (like the table
above) describe this repository's surface. They are not measurements of any
particular host or client configuration — measure the real integration with
the capture command before quoting numbers for it.
