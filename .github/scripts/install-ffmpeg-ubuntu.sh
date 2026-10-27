#!/usr/bin/env bash
# Keep the runner's signed Ubuntu packages; avoid the degraded Azure mirror.
set -euo pipefail

if command -v ffmpeg >/dev/null && command -v ffprobe >/dev/null; then
  echo "FFmpeg already on PATH; skipping apt install."
  ffmpeg -version
  ffprobe -version
  exit 0
fi

shopt -s nullglob
for source_file in /etc/apt/sources.list /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources; do
  if [[ -f "$source_file" ]]; then
    sudo sed -E -i \
      's#https?://azure\.archive\.ubuntu\.com/ubuntu#https://archive.ubuntu.com/ubuntu#g' \
      "$source_file"
  fi
done

# Socket timeouts do not bound a slow but progressing download. Bound each
# entire command as well, leaving time for the real validation jobs to run.
# 2026-10-27: a single 360s/540s install still 124'd on archive.ubuntu.com
# stalls (Staged MCPB). Kill hung attempts early and retry so a slow mirror
# node does not consume the whole job.
apt_options=(-o Acquire::Retries=2 -o Acquire::http::Timeout=15 -o Acquire::https::Timeout=15)
attempt=1
max_attempts=3
until sudo timeout --kill-after=15s 90s apt-get "${apt_options[@]}" update \
  && sudo timeout --kill-after=15s 180s apt-get "${apt_options[@]}" install \
    --yes --no-install-recommends ffmpeg; do
  if (( attempt >= max_attempts )); then
    echo "FFmpeg apt install failed after ${max_attempts} attempts." >&2
    exit 1
  fi
  echo "apt attempt ${attempt} failed; retrying..." >&2
  attempt=$((attempt + 1))
  sleep 5
done
ffmpeg -version
ffprobe -version
