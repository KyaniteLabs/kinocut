# syntax=docker/dockerfile:1.26

FROM python:3.14.7-slim-bookworm@sha256:8e729c1805fb85b93e435f6c0ba67069e1b2cfd1ce4f72a9481f6a737434b46b AS python

FROM node:24.19.0-bookworm-slim@sha256:a9f5f7c91a432850b2a8a7797adf5eadb6c733ceed61167806cee7ea7fbc29df

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
