#!/usr/bin/env bash
# Keep the runner's signed Ubuntu packages; avoid the degraded Azure mirror.
set -euo pipefail

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
# 2026-10-27: archive.ubuntu.com stalls ran the install into its 360s bound
# twice in one day (Staged MCPB exit 124); raise the bounds and retry count
# so a slow mirror node recovers instead of killing the job.
apt_options=(-o Acquire::Retries=3 -o Acquire::http::Timeout=15 -o Acquire::https::Timeout=15)
sudo timeout --kill-after=15s 240s apt-get "${apt_options[@]}" update
sudo timeout --kill-after=15s 540s apt-get "${apt_options[@]}" install \
  --yes --no-install-recommends ffmpeg
ffmpeg -version
ffprobe -version
