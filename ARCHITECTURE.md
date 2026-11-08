# Kinocut architecture

```text
MCP tools / kino commands / Python client -> typed validation + output policy
 -> Engine or trusted edit-kernel compilation -> FFmpeg/optional integration
 -> artifact + provenance/quality -> explicit human release gate
```

[CONTEXT.md](CONTEXT.md) distinguishes Tool, Engine, FFmpeg Pipeline, Probe, Guardrail and three qualified project types. Facades re-export; `server_tools_*.py` own tools, `engine_*.py` implement operations and `cli/` maps commands. [server_app.py](kinocut/server_app.py) owns FastMCP/result helpers; [tool_registry.py](kinocut/tool_registry.py) selects a compact/profile/all surface and lazy catalog registration. Family dispatch reaches operations without advertising every full schema at once.

[engine_edit.py](kinocut/engine_edit.py) validates trim times and builds FFmpeg work. Shared helpers validate paths, bound processes and stage outputs; [runtime utilities](kinocut/engine_runtime_utils.py) resolve FFmpeg/ffprobe and check optional filters. [output_policy.py](kinocut/output_policy.py) scopes explicit Boolean overwrite consent and per-operation input/write ownership with context variables. Higher-level workflow/review/receipt paths layer durable identity/provenance and approvals over media operations; these were not all executed for this docs change.

## Risk / failure boundaries

- Media writes/cleanup and optional installers can overwrite/delete data or install large dependencies. Keep sources immutable and outputs new; explicit overwrite consent is not a blanket license for non-media or other jobs' paths.
- FFmpeg/optional filter/codec/model availability is host-specific. Missing dependencies and timeouts are operation failures, not proof an integration works from its tool name. Hidden discovery tools are not unavailable features; advertised tools are not capability certificates.
- Optional remote image/voice/translation services can send content off-host, incur spend or raise likeness/consent/licensing issues. Inspect configured provider and approval before any call; no inference was used here.
- Receipts and technical QC bind bounded observations, not aesthetic quality or actual human viewing. A publish-validation result is not upload, release authorization or acceptance; human gates remain explicit.

## Docs proof

Read purpose/domain, manifest, app/registry, edit/output/runtime source. Base install, CLI help, pure time parsing, actual MCP discovery (30 default tools) and CLI metadata probe of a synthetic one-second clip passed. No cleanup-heavy tests, existing media edits, optional engine/model launch, review acceptance or publishing. No creative/operator-side acceptance claimed. Runtime unchanged; revert docs for rollback.
