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

## Runner image

Build the image locally from the pinned base-image digests:

```bash
docker build --pull --tag kinocut-ci:1.11.1 containers/ci
docker run --rm kinocut-ci:1.11.1 sh -ceu \
  'python3 --version; node --version; ffmpeg -version | head -1; ffprobe -version | head -1; git --version'
```

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
