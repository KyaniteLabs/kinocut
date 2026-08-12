# Forgejo CI runner topology

This document records the repository contract for Kinocut's Forgejo runners.
It is not evidence that a Forgejo administrator has applied the configuration.

**Last agent review:** 2026-08-12 · light routing verified in `.forgejo/workflows/ci.yml`

## Workload routing

| Label | Intended workload | Host rule |
| --- | --- | --- |
| `light` | lint, metadata, and other low-CPU checks | May run at capacity 1; must not carry real-media tests |
| `heavy` | Legacy shared heavy-work label (also Renovate / mirror sync today) | Prefer not for Kinocut test suites; keep for short ops jobs until `light` capacity is proven for them |
| `arm64-heavy` | Python tests, FFmpeg renders, Hyperframes, and FFmpeg matrices | Dedicated ARM64 runner away from the Forgejo application host |
| `kinocut-ci` | Same workload class as `arm64-heavy`, using the prebuilt Kinocut image | Map only after the immutable image digest is published and smoke-tested |

## Light runner topology (contract)

**Goal:** cheap checks never queue behind multi-minute FFmpeg/pytest shards.

| Workflow job | File | `runs-on` | Notes |
| --- | --- | --- | --- |
| Lint / ruff | `.forgejo/workflows/ci.yml` | **`light`** | Must stay on `light`; do not move lint onto `arm64-heavy` |
| Unit / integration / FFmpeg matrix | `.forgejo/workflows/ci.yml` | `arm64-heavy` | Real media + pytest only |
| Renovate | `.forgejo/workflows/renovate.yml` | `heavy` | Containerized; ops job (not pytest) |
| Mirror sync | `.forgejo/workflows/sync-github.yml` | `heavy` | Ops job |

### Admin checklist for light capacity

1. Runner registers labels: `light`, `heavy`, `arm64-heavy` (and optionally `default`).
2. At least one runner claims **`light`** without also being the sole host for concurrent `arm64-heavy` starvation (capacity ≥1 is fine if heavy work is on another label).
3. Spot-check: open a PR that only touches docs → lint job starts without waiting for a long test shard.
4. Do **not** schedule real-media pytest on `light`.
5. If `light` has zero online runners, lint fails fast — that is preferred to silent routing onto an overloaded heavy host.

### Anti-patterns

- Routing FFmpeg matrix or full pytest onto `light`
- Using bare `ubuntu-latest` on Forgejo (self-hosted labels only)
- Mapping `arm64-heavy` onto the Forgejo application VM under load

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
and `arm64-heavy`, all mapped to `docker://ubuntu:24.04`. Docker socket is
native at `/var/run/docker.sock` inside the VM.
Storage recovery on 2026-08-08:

- Persistent application volumes were backed up outside the repository before repair.
- Container storage was unmounted and checked offline with `e2fsck -f`; the next boot
  mounted it read/write without the prior ext4 journal or containerd metadata errors.
- Stale Actions containers, workflow networks, and transient task volumes were removed.
- The runner binary and config moved from volatile `/tmp` paths to
  `/usr/local/bin/forgejo-runner` and `/etc/forgejo-runner/config.yaml`.

Key constraints:

- **Base image is `ubuntu:24.04`** (Python 3.12). Earlier `ubuntu:22.04`
  failed because it ships Python 3.10, below the package's `>=3.11` floor.
- **FFmpeg matrix uses `linuxarm64` static builds** from BtbN/FFmpeg-Builds.
  The `linux64` (x86_64) binaries cannot execute on ARM64 without qemu.
- **Lint runs on `light`** to avoid queuing behind heavy test jobs.
- **Heavy Kinocut jobs run on `arm64-heavy`** so shared legacy labels cannot
  route architecture-sensitive work to stale or incompatible runners.
- **The general PR suite uses four deterministic file shards**, each serial and
  capped at one active shard, so every task stays below the instance timeout.
- **Each FFmpeg matrix leg runs serially and one at a time** because FFmpeg and
  CLI subprocesses contend under xdist on the 4-core runner.
- **Heavy gates do not overlap**: all general shards finish before matrix legs,
  and the slow suite runs after the matrix on master pushes.
- **Node.js 18.19.1 is installed in the PR test job** for MCPB launcher contracts.
- **Manual git clone** replaces `actions/checkout@v4` — the Colima VM cannot
  reach `gitea.com` to download the action. Authenticated clone uses
  `${{ secrets.GITHUB_TOKEN }}` with the known host.
- **Docker network cleanup**: each CI task creates a Docker network; if
  tasks fail, networks accumulate and exhaust address pools. Periodic
  `docker network prune -f` inside the VM is required.
- **Persistence**: Colima auto-starts via launchd plist
  (`tech.kyanitelabs.colima`, `RunAtLoad=true`). The runner binary and config
  live on the VM root filesystem; systemd manages the service (`Restart=always`).
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
4. Confirm `arm64-heavy` and `kinocut-ci` do not execute on the Forgejo application
   host.
5. Change `.forgejo/workflows/ci.yml` jobs from `arm64-heavy` to `kinocut-ci`,
   remove their repeated base dependency installs, and prove one push plus one pull
   request run.
6. Keep the FFmpeg 6/7/8 matrix downloads: those are deliberate portability
   inputs and are not replaced by the default runner FFmpeg.

Registry publication and Forgejo-admin label changes are external operations.
They require an authorized human and are intentionally not performed by the
repository build.
