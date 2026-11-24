"""Build ffprobe frame measurements using a lavfi movie input."""

from __future__ import annotations


def movie_source(path: str, tail: str, limit: float | None) -> str:
    """Escape the movie options, then quote them for the outer filtergraph."""
    movie_path = "".join("\\" + char if char in "\\':[],;=" else char for char in path)
    quoted_path = "'" + movie_path.replace("'", "'\\''") + "'"
    source = f"movie={quoted_path}"
    if limit and limit > 0:
        source += f",trim=duration={float(limit):.3f},setpts=PTS-STARTPTS"
    return f"{source},{tail}"


def frame_tags_command(source: str, tags: str) -> list[str]:
    """Read frame tags along with the metadata needed for range conversion."""
    return [
        "ffprobe",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        source,
        "-show_entries",
        f"frame=pix_fmt,color_range,color_transfer:frame_tags={tags}",
        "-of",
        "json",
    ]
