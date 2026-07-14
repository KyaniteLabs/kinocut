# Kinocut MCPB

Kinocut's MCPB package is a local stdio launcher for Claude Desktop-style hosts that install `.mcpb` files.

MCPB does not bundle Python, Kinocut, FFmpeg, Node, Hyperframes, or AI model weights in this staged/local-only package. It launches an existing Python environment with `python -m kinocut --mcp`, so the current CLI, MCP tool names, Python package, `mcp-video` compatibility shim, and FFmpeg behavior stay unchanged. Native MCPB bundles are not published with this release.

## Runtime Requirements

- Node.js 18 or newer, used only by the MCPB launcher.
- Python 3.11 or newer with `kinocut==1.8.0` installed.
- FFmpeg and ffprobe available on `PATH`, or an executable named `ffmpeg` configured through the installer field with an adjacent `ffprobe`.
- Optional AI features require the matching Kinocut extras and local model dependencies.
- Hyperframes tools require a resolvable Hyperframes command; leave the field blank if you do not use those tools.

## Local Access Boundary

This staged manifest intentionally does not ask for workspace/output fields. Those fields would look like a security boundary, but Kinocut's legacy direct tools can still receive absolute paths from the client.

MCPB has no platform sandbox. Kinocut's existing tool and workflow guardrails still validate their own paths, and workflow specs remain workspace-confined, but this package must not be treated as an OS-enforced filesystem permission layer.

## Build And Validate

Build the local artifact without publishing:

```bash
python3 scripts/build-mcpb.py
```

The script validates the v0.4 manifest fields used by this package and writes:

```text
dist/kinocut-1.8.0.mcpb
```

Focused validation:

```bash
python3 -m pytest tests/test_kinocut_distribution.py::test_mcpb_distribution_is_truthful_and_buildable -q
node mcpb/server/launcher.js
```

The launcher command should be tested through an MCP client or inspector because it starts a long-running stdio server.

## Release Gate Before External Publication

Do not publish this MCPB package externally until these gates are closed:

- Validate with the official `@anthropic-ai/mcpb` validator when it is available in CI.
- Test install on clean macOS, Linux, and Windows machines without repository-local imports.
- Decide whether to keep this staged launcher or produce per-platform bundles that include Python, Kinocut, and FFmpeg.
- Add enforced MCPB runtime confinement for direct-tool absolute paths, or keep the package clearly labeled as user-configured local access.
- Verify dependency-driven optional AI and Hyperframes behavior with dependencies absent and present.

The self-contained native runtime implementation is tracked in
[issue #125](https://git.kyanitelabs.tech/KyaniteLabs/kinocut/issues/125). Its pinned
runtime and licensing contract is documented in
[MCPB_SUPPLY_CHAIN.md](MCPB_SUPPLY_CHAIN.md). The staged package on `master` remains
non-publishable until that issue's native build, clean-machine, supply-chain, and human
review gates are complete.
