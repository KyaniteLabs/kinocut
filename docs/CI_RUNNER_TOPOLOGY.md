# CI runner topology (Forgejo #110)

**Date:** 2026-08-07

## Goal

Reduce Kyan contention by using an image with FFmpeg preinstalled and clear
label routing for heavy vs light jobs.

## Image

- Local/CI Dockerfile: [`Dockerfile.ci`](../Dockerfile.ci)
- App runtime Dockerfile (slim): [`Dockerfile`](../Dockerfile)

```bash
docker build -f Dockerfile.ci -t kinocut-ci:local .
```

## Suggested labels

| Label | Workload |
| --- | --- |
| `light` | lint, public surface, unit-only |
| `heavy` | full pytest, ffmpeg matrix, hyperframes |
| `publish` | release publish only |

## Live workflows

See `.github/workflows/ci.yml` for current job routing. Prefer installing from
`Dockerfile.ci` on self-hosted runners instead of `apt-get install ffmpeg` per job
when the runner pool supports custom images.
