# Forgejo CI runner topology

This document records the repository contract for Kinocut's Forgejo runners.
It is not evidence that a Forgejo administrator has applied the configuration.

## Workload routing

| Label | Intended workload | Host rule |
| --- | --- | --- |
| `light` | lint, metadata, and other low-CPU checks | May run at capacity 1; must not carry real-media tests |
| `heavy` | Python tests, FFmpeg renders, Hyperframes, and FFmpeg matrices | Run away from the Forgejo application host |
| `kinocut-ci` | Same workload class as `heavy`, using the prebuilt Kinocut image | Map only after the immutable image digest is published and smoke-tested |

The 2026-07-10 incident audit observed `vps-runner-01` on the Forgejo host at
capacity 1 and `nucbox-ci` at capacity 4. Those observations are historical,
not a live inventory. An administrator must re-check runner placement,
capacity, and label mappings before changing production labels. The repository
token does not have `read:admin`, so CI cannot truthfully infer this topology.
## Active runner: mac-m4-ci-runner

As of 2026-08-08, a single local runner (`mac-m4-ci-runner`, Apple Silicon
ARM64) is registered at repo level with `heavy`, `light`, and `default`
labels, all mapped to `docker://ubuntu:24.04`. Docker runtime is provided
by Colima (macOS Virtualization Framework). Capacity is 2.

Key constraints on this runner:

- **Base image is `ubuntu:24.04`** (Python 3.12). Earlier `ubuntu:22.04`
  failed because it ships Python 3.10, below the package's `>=3.11` floor.
- **FFmpeg matrix uses `linuxarm64` static builds** from BtbN/FFmpeg-Builds.
  The `linux64` (x86_64) binaries cannot execute on ARM64 without qemu.
- **Lint runs on `light`** to avoid queuing behind heavy test jobs.
- **Persistence**: act_runner is managed by launchd (`KeepAlive=true`).
  Colima is managed by a separate launchd plist (`RunAtLoad=true`).

## Runner image

Primary image build (when `containers/ci` is present):

```bash
docker build --pull --tag kinocut-ci:1.13.0 containers/ci
docker run --rm kinocut-ci:1.13.0 sh -ceu \
  'python3 --version; node --version; ffmpeg -version | head -1; ffprobe -version | head -1; git --version'
```

Supplemental slim CI Dockerfile at repo root (`Dockerfile.ci`) installs FFmpeg +
editable Kinocut for local smoke; it is **not** a substitute for the pinned
production runner digest until published and smoke-tested.

Before production activation:

1. Publish the image to an approved registry and record its manifest-list
   digest. A floating tag is not an acceptable runner label target.
2. Run the smoke command on the runner architecture.
3. In Forgejo administration, map `kinocut-ci` to
   `docker://REGISTRY/kinocut-ci@sha256:DIGEST`.
4. Confirm `heavy` and `kinocut-ci` do not execute on the Forgejo application
   host.
5. Change `.forgejo/workflows/ci.yml` jobs from `heavy` to `kinocut-ci`, remove
   their repeated base dependency installs, and prove one push plus one pull
   request run.
6. Keep the FFmpeg 6/7/8 matrix downloads: those are deliberate portability
   inputs and are not replaced by the default runner FFmpeg.

Registry publication and Forgejo-admin label changes are external operations.
They require an authorized human and are intentionally not performed by the
repository build.
