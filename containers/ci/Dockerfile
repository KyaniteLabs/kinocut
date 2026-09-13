# syntax=docker/dockerfile:1.27

FROM python:3.14.7-slim-bookworm@sha256:9ab8d9c8514b44f90cf0029dd42fdd7e9e211e639c8b995304cc04568dee900f AS python

FROM node:24.21.0-bookworm-slim@sha256:2fe369e969550cde8e867afc3fe370b260140cab4a23d467074295b42163d553

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
