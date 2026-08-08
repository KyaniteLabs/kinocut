# syntax=docker/dockerfile:1.26

FROM python:3.14.7-slim-bookworm@sha256:23c59390fc717bf09f9336908199a0ae75d9c4264bf296123f94ad772fea3b52 AS python

FROM node:22.23.1-bookworm-slim@sha256:6c74791e557ce11fc957704f6d4fe134a7bc8d6f5ca4403205b2966bd488f6b3

COPY --from=python /usr/local /usr/local

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install --yes --no-install-recommends \
        ca-certificates \
        curl \
        ffmpeg \
        git \
        xz-utils \
    && rm -rf /var/lib/apt/lists/* \
    && python3 --version \
    && node --version \
    && ffmpeg -version >/dev/null \
    && ffprobe -version >/dev/null \
    && git --version

LABEL org.opencontainers.image.title="Kinocut Forgejo CI runner"
LABEL org.opencontainers.image.description="Pinned Python 3.13 and Node 22 runner image with FFmpeg and git preinstalled"
LABEL org.opencontainers.image.source="https://git.kyanitelabs.tech/KyaniteLabs/kinocut"
