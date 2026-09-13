"""Dependency-free legacy SRT extraction; callers own strict validation."""

from __future__ import annotations

from kinocut_sound.validation import SRT_CUE_SPLIT_RE as _CUE_SPLIT, SRT_TIMESTAMP_RE as _TS


def _parse_srt(text: str) -> list[tuple[str, str, str]]:
    blocks = [b.strip() for b in _CUE_SPLIT.split(text.strip()) if b.strip()]
    cues: list[tuple[str, str, str]] = []
    for block in blocks:
        lines = block.splitlines()
        # index line optional
        if lines and lines[0].strip().isdigit():
            lines = lines[1:]
        if not lines:
            continue
        m = _TS.search(lines[0])
        if not m:
            continue
        body = "\n".join(lines[1:]).strip()
        cues.append((m.group(1), m.group(2), body))
    return cues
