# syntax=docker/dockerfile:1.7

FROM python:3.13.5-slim-bookworm@sha256:4c2cf9917bd1cbacc5e9b07320025bdb7cdf2df7b0ceaccb55e9dd7e30987419 AS python

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
