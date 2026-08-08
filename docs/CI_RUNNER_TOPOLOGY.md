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
## Active runner: colima-ci-runner

As of 2026-08-08, the CI runner (`colima-ci-runner`, id=15) runs
**inside the Colima VM** as a systemd service (`forgejo-runner.service`,
auto-start on boot, auto-restart on crash). The runner binary is
forgejo-runner v13.0.0 (linux-arm64). Labels: `heavy`, `light`, `default`,
all mapped to `docker://ubuntu:24.04`. Docker socket is native at
`/var/run/docker.sock` inside the VM.

Key constraints:

- **Base image is `ubuntu:24.04`** (Python 3.12). Earlier `ubuntu:22.04`
  failed because it ships Python 3.10, below the package's `>=3.11` floor.
- **FFmpeg matrix uses `linuxarm64` static builds** from BtbN/FFmpeg-Builds.
  The `linux64` (x86_64) binaries cannot execute on ARM64 without qemu.
- **Lint runs on `light`** to avoid queuing behind heavy test jobs.
- **Manual git clone** replaces `actions/checkout@v4` — the Colima VM cannot
  reach `gitea.com` to download the action. Authenticated clone uses
  `${{ secrets.GITHUB_TOKEN }}` with the known host.
- **Docker network cleanup**: each CI task creates a Docker network; if
  tasks fail, networks accumulate and exhaust address pools. Periodic
  `docker network prune -f` inside the VM is required.
- **Persistence**: Colima auto-starts via launchd plist
  (`tech.kyanitelabs.colima`, `RunAtLoad=true`). The forgejo-runner inside
  the VM is managed by systemd (`Restart=always`).
- **macOS act_runner deprecated**: the previous macOS-hosted act_runner
  (launchd plist `tech.kyanitelabs.act-runner`) could not exec into
  containers because the `act` library couldn't find Docker at
  `/var/run/docker.sock` (Colima uses a non-standard path). The Colima VM
  runner solves this by running natively where the socket exists.

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
