# MCPB Runtime Supply Chain

Kinocut's native MCPB work is tracked as an internal native-runtime workstream (historically referenced as issue #125).
This document defines the evidence required before a self-contained bundle can be
published. It does not authorize a release.

## Selected Runtime Lines

| Component | Selected line | Provenance rule |
| --- | --- | --- |
| Node.js | 22.23.1 Jod LTS | Use versioned archives from `nodejs.org`, pinned to the signed `SHASUMS256.txt` digest, and retain Node's license notices. |
| Python | CPython 3.12.13 from `python-build-standalone` release `20260623` | Pin the stripped runtime and matching full metadata archive by digest. Copy CPython, pip, linked-library, and distribution notices into the bundle. |
| Kinocut | Wheel built from the checked-out commit | Record the commit, wheel digest, and core-only dependency lock. Do not install optional model stacks. |
| FFmpeg | Blocked | No binary is accepted until the build, licensing, corresponding source, and four-platform provenance requirements below are closed. |

Primary references:

- [Node.js 22.23.1 release](https://nodejs.org/en/blog/release/v22.23.1)
- [`python-build-standalone` release `20260623`](https://github.com/astral-sh/python-build-standalone/releases/tag/20260623)
- [FFmpeg 8.1.2 downloads and signed source](https://ffmpeg.org/download.html)
- [FFmpeg licensing and compliance checklist](https://ffmpeg.org/legal.html)

## Immutable Lock Contract

Every downloaded artifact must declare all of the following in the committed runtime
lock:

- component name and exact version;
- target OS and architecture;
- versioned HTTPS asset URL with no floating `latest` or `current` path;
- SHA-256 digest;
- archive format and normalized layout;
- expected executable paths;
- maximum download and expanded sizes;
- license identifier and notice paths; and
- immutable corresponding-source URL and SHA-256 digest.

The builder must download to a temporary file, enforce the byte limit while streaming,
verify the digest, and only then atomically move the artifact into its cache. Offline
mode may use an existing cache entry only after repeating the digest check.

Archive extraction fails closed on absolute paths, traversal, duplicate entries,
devices, escaping links, undeclared expansion, or unsupported member types. Extracted
executables must remain inside the staged bundle after real-path resolution.

## FFmpeg Publication Blocker

FFmpeg publishes signed source releases and links to third-party binary providers; it
does not publish a four-platform binary set itself. The reviewed third-party sets do
not currently provide one immutable, source-matched, notice-complete build family for
Apple Silicon, Intel macOS, Linux x64, and Windows x64.

Kinocut's core render paths currently select `libx264`. An LGPL-only FFmpeg build omits
that encoder, while a GPL build changes the redistribution obligations. Do not silently
swap the encoder, mix unrelated provider builds, or describe a partial binary set as a
portable Kinocut runtime.

Before FFmpeg can enter the runtime lock, one reviewed strategy must provide:

1. the same pinned FFmpeg release and declared capability floor on all four targets;
2. reproducible build definitions and toolchains;
3. exact configure receipts and changes;
4. matching binary digests, SBOMs, licenses, and third-party notices;
5. exact corresponding source hosted alongside the binary delivery; and
6. explicit review of the GPL, patent, and source-delivery consequences.

Until then, native MCPB artifacts remain non-publishable.

## Bundle Evidence

Each target artifact must contain:

- `runtime/runtime-metadata.json` with target, component versions, source URLs, and
  digests;
- `licenses/THIRD_PARTY_NOTICES.md` plus component license files;
- `sbom.spdx.json` covering binary and Python components; and
- `SHA256SUMS` matching the final archive inventory.

The launcher resolves runtimes relative to its own bundle, rejects platform or
architecture mismatches and symlink escapes, starts Python in isolated mode, and never
falls back to host Python, Node, FFmpeg, Hyperframes, C2PA, or model dependencies.

Self-contained does not mean sandboxed. MCPB provides no OS filesystem sandbox, and the
bundle must not claim one.

## Release Gate

No tag, upload, directory submission, or release proceeds until every target passes the
native clean-machine matrix, official MCPB validation and packing, archive/SBOM/notices
reconciliation, platform signing checks, and human review.
