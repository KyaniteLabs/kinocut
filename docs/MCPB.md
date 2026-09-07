# Kinocut MCPB

Kinocut's unsigned MCPB package is a local stdio launcher for Claude Desktop-style hosts that install `.mcpb` files. Its product label is **user-configured-local-access**.

MCPB does not bundle Python, Kinocut, FFmpeg, Node, Hyperframes, or AI model weights. It launches an existing Python environment with `python -m kinocut --mcp`, so the current CLI, MCP tool names, Python package, `mcp-video` compatibility shim, and FFmpeg behavior stay unchanged. Native MCPB bundles are separate future work.

## Runtime Requirements

- Node.js 18 or newer, used only by the MCPB launcher.
- Python 3.11 or newer with `kinocut==1.15.1` installed.
- FFmpeg and ffprobe available on `PATH`, or an executable named `ffmpeg` configured through the installer field with an adjacent `ffprobe`.
- Optional AI features require the matching Kinocut extras and local model dependencies.
- Hyperframes tools require a resolvable Hyperframes command; leave the field blank if you do not use those tools.

## Local Access Boundary

This staged manifest intentionally does not ask for workspace/output fields. Those fields would look like a security boundary, but Kinocut's legacy direct tools can still receive absolute paths from the client.

MCPB has no platform sandbox and is not a sandbox. Kinocut's existing tool and workflow guardrails still validate their own paths, and workflow specs remain workspace-confined, but this package must not be treated as an OS-enforced filesystem permission layer.

## Build And Validate

Build the local artifact without publishing:

```bash
python3 scripts/build-mcpb.py
```

The script validates Kinocut's manifest invariants, audits the exact three regular archive members,
and writes a SHA-256-bound build receipt. The locked official validator runs separately in CI.

```text
dist/kinocut-1.15.1.mcpb
```

Focused validation:

```bash
python3 -m pytest tests/test_kinocut_distribution.py::test_mcpb_distribution_is_truthful_and_buildable -q
node mcpb/server/launcher.js
```

The launcher command should be tested through an MCP client or inspector because it starts a long-running stdio server.

## Staged Release Gates Before External Publication

Staged publication does not depend on native bundle completion. Do not publish this MCPB package externally until these staged gates are closed for one exact source revision and archive digest:

- Pass locked `@anthropic-ai/mcpb@2.1.2` validation for both source and extracted manifests.
- Pass the archive audit and clean hosted macOS, Linux, and Windows MCP runtime matrix without repository-local imports.
- Verify optional AI and Hyperframes behavior with dependencies absent and present.
- Observe compatible desktop-host imports on macOS and Windows, including the unsigned warning and local-access label.
- Record publication and human review independently; CI validation does not mean uploaded, listed, signed, or accepted.

The self-contained native runtime implementation is tracked in
[issue #125](https://git.kyanitelabs.tech/KyaniteLabs/kinocut/issues/125). Its pinned
runtime and licensing contract is documented in
[MCPB_SUPPLY_CHAIN.md](MCPB_SUPPLY_CHAIN.md). The native gates do not describe or
block the staged artifact's separate acceptance contract.
