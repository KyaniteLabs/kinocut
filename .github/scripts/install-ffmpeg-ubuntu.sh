#!/usr/bin/env bash
# Keep the runner's signed Ubuntu packages; avoid the degraded Azure mirror.
# If apt hangs or the mirror is empty, fall back to a pinned static FFmpeg.
set -euo pipefail

if command -v ffmpeg >/dev/null && command -v ffprobe >/dev/null; then
  echo "FFmpeg already on PATH; skipping install."
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

apt_options=(-o Acquire::Retries=1 -o Acquire::http::Timeout=10 -o Acquire::https::Timeout=10)
attempt=1
max_attempts=2
until sudo timeout --kill-after=10s 45s apt-get "${apt_options[@]}" update \
  && sudo timeout --kill-after=10s 60s apt-get "${apt_options[@]}" install \
    --yes --no-install-recommends ffmpeg; do
  if (( attempt >= max_attempts )); then
    echo "apt FFmpeg install failed after ${max_attempts} attempts; falling back to static build." >&2
    break
  fi
  echo "apt attempt ${attempt} failed; retrying..." >&2
  attempt=$((attempt + 1))
  sleep 2
done

if command -v ffmpeg >/dev/null && command -v ffprobe >/dev/null; then
  ffmpeg -version
  ffprobe -version
  exit 0
fi

# Pinned BtbN static build — same major as the FFmpeg-8 matrix job, immutable tag.
ffmpeg_tag="autobuild-2026-06-30-13-34"
ffmpeg_asset="ffmpeg-n8.1.2-21-gce3c09c101-linux64-gpl-8.1.tar.xz"
url="https://github.com/BtbN/FFmpeg-Builds/releases/download/${ffmpeg_tag}/${ffmpeg_asset}"
# Fresh private directory: never extract over reusable or attacker-influenced
# paths. mktemp -d under the runner temp root is owned by this job only.
dest="$(mktemp -d "${RUNNER_TEMP:-/tmp}/ffmpeg-static.XXXXXX")"
echo "Downloading static FFmpeg from $url"
curl -fsSL --retry 3 --retry-delay 5 "$url" -o "${dest}/ffmpeg.tar.xz"
python3 -c "import tarfile,sys; tarfile.open(sys.argv[1]).extractall(sys.argv[2], filter='data')" \
  "${dest}/ffmpeg.tar.xz" "$dest"
bindir="$(dirname "$(find "$dest" -type f -name ffmpeg | head -1)")"
echo "Static FFmpeg bin dir: $bindir"
if [[ -n "${GITHUB_PATH:-}" ]]; then
  echo "$bindir" >> "$GITHUB_PATH"
fi
export PATH="$bindir:$PATH"
ffmpeg -version
ffprobe -version
