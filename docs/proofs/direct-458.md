# Spoken direction implementation evidence (#458)

Creators can pass ordinary words through an agent to a deterministic edit plan,
review its assumptions, and explicitly apply it. Planning performs no render or
plan persistence. Apply validates the complete tool, argument and path chain
before rendering, then returns receipts and stops at the first failure.

Files added:

- `kinocut/direct/__init__.py`, `parser.py`, `planner.py`: pure intent extraction and ordered plans.
- `kinocut/direct_validation.py`: closed tool contracts, bounded arguments and path admission.
- `kinocut/server_tools_direct.py`: MCP planning, optional voice memo transcription and guarded apply.
- `kinocut/cli/handlers_direct.py`: review and explicit apply through the CLI.
- `tests/test_direct.py`, `tests/test_direct_tools.py`: 84 cases, including a 32-phrase corpus, caps, controls, injection, negation, contradictions, unknown requests, tool signatures, edited-plan rejection, strict MCP confirmation, dry runs, mocked voice/captions, failures and a real 1.9-second fixture render to 1080x1920.
- `docs/proofs/direct-458.md`: this evidence record.

Existing files changed:

- `kinocut/server.py`, `kinocut/__main__.py`, `kinocut/cli/parser/core.py`, `kinocut/tool_discovery.py`: registration, CLI routing and discovery.
- `skills/kinocut/SKILL.md`, `plugins/kinocut/skills/kinocut/SKILL.md`: verbatim words, assumptions, one question, then explicit user agreement. The copies already differ; their unrelated differences are preserved. No sync test was found.
- `README.md`, `CHANGELOG.md`, `docs/TOOLS.md`, `docs/AI_AGENT_DISCOVERY.md`, `llms.txt`, `docs/public_claims.json`, `docs/status/NOW.md`: usage and development surface of 208 MCP tools / 178 CLI commands; published counts remain unchanged.
- `tests/public_surface_inventory.py`, `tests/test_public_surface.py`, `tests/test_mcp_argument_contracts.py`, `tests/test_namespace_routing.py`, `tests/test_inspection_surfaces.py`, `tests/test_workflow_variants.py`: pinned names and counts.

Verification: **132 passed**. Exact pytest command:

```bash
uv run --frozen --no-sync pytest tests/test_direct.py tests/test_direct_tools.py tests/test_tool_discovery.py tests/test_public_claims.py tests/test_public_surface.py::test_cli_help_lists_all_commands tests/test_public_surface.py::test_server_tool_registry_keeps_public_tool_names tests/test_mcp_argument_contracts.py::test_all_registered_argument_models_and_schemas_reject_extras tests/test_namespace_routing.py::test_flat_command_set_remains_authoritative tests/test_inspection_surfaces.py::test_public_counts_and_client_contracts tests/test_workflow_variants.py::test_variants_do_not_change_public_surface_counts tests/test_workflow_variants.py::test_variant_flags_do_not_add_cli_commands -x -q -p no:cacheprovider
```

`UV_PROJECT_ENVIRONMENT` selected an existing local environment and
`UV_CACHE_DIR` selected writable temporary storage. Normal frozen synchronization
could not write the default cache or download dependencies because DNS was
unavailable; `--no-sync` kept verification offline. All transcription in tests
was mocked. No model inference, model downloads, full-suite runs or parallel
pytest workers were used.

Ruff and `git diff --check` passed for the changed implementation and tests.
The existing stdio handshake test timed out in separate bounded attempts; a
minimal upstream `FastMCP` server without KinoCut also timed out receiving the
same initialization request. That check remains unverified and is excluded
from the 132 passing cases.

The local commit could not be created: both staging and the requested commit
command failed because the sandbox mounts `.git` read-only (`index.lock`: read-only
file system). All changes remain in the working tree. No pushes, pull requests
or remote changes were made. Complete the commit from a writable checkout with
the requested author and co-author trailer.
