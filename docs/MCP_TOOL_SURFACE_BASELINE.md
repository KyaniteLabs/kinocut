# MCP tool-surface baseline

This page documents the byte-level regression baseline that protects the
published MCP tool surface, and the exact procedure that reproduces it.
It exists so that any change to the advertised tools — names, parameters, or
schema bytes — is a conscious, reviewed edit rather than silent drift.

## What is pinned

`tests/fixtures/mcp_tool_surface_baseline.json` captures the surface of the
repository server at 2cf76e98 (published 1.16.5) for the three supported
selector modes, launched exactly the way registries and clients launch it
(`python -m kinocut --mcp` over stdio, MCP initialize + tools/list):

| Mode (`KINOCUT_TOOLS`) | Tools | Input-schema bytes (UTF-8) |
| --- | --- | --- |
| default / `core` (unset) | 20 | 13,947 |
| `all` | 205 | 126,776 |
| `profile:editor` | 108 | 71,413 |

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

The headline numbers (20/13,947, 205/126,776, 108/71,413) are also asserted
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
A `uvx kinocut==1.16.5` capture matches the default mode byte-for-byte
(20 tools / 13,947 bytes).

Registrations counts computed from `kinocut.tool_registry` (like the table
above) describe this repository's surface. They are not measurements of any
particular host or client configuration — measure the real integration with
the capture command before quoting numbers for it.
