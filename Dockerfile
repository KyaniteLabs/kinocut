FROM python:3.14-slim@sha256:9aaa474097d094040649f2162a627c0049b408f52138d980916788d80f04802f

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md README-PYPI.md LICENSE ./
COPY kinocut/ kinocut/
COPY kinocut_sound/ kinocut_sound/
COPY mcp_video.py ./

RUN pip install --no-cache-dir .

RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app

USER appuser

ENV MCP_VIDEO_ANALYTICS=0

ENTRYPOINT ["kino"]
