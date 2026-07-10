"""Editing templates for common video formats."""

from __future__ import annotations

from typing import Any


def tiktok_template(
    video_path: str,
    caption: str | None = None,
    music_path: str | None = None,
    output_path: str | None = None,
) -> dict[str, Any]:
    """Generate a timeline for TikTok (9:16, 1080x1920).

    Args:
        video_path: Path to the source video.
        caption: Optional caption text at the bottom.
        music_path: Optional background music.
        output_path: Where to save the final video.
    """
    timeline: dict[str, Any] = {
        "width": 1080,
        "height": 1920,
        "tracks": [
            {
                "type": "video",
                "clips": [
                    {"source": video_path, "start": 0},
                ],
            }
        ],
        "export": {"format": "mp4", "quality": "high"},
    }

    if caption:
        timeline["tracks"].append(
            {
                "type": "text",
                "elements": [
                    {
                        "text": caption,
                        "start": 0,
                        "position": "bottom-center",
                        "style": {"size": 36, "color": "white", "shadow": True},
                    }
                ],
            }
        )

    if music_path:
        timeline["tracks"].append(
            {
                "type": "audio",
                "clips": [
                    {"source": music_path, "start": 0, "volume": 0.5, "fade_in": 1.0, "fade_out": 2.0},
                ],
            }
        )

    return timeline


def youtube_shorts_template(
    video_path: str,
    title: str | None = None,
    music_path: str | None = None,
    output_path: str | None = None,
) -> dict[str, Any]:
    """Generate a timeline for YouTube Shorts (9:16, 1080x1920)."""
    timeline = tiktok_template(video_path, caption=title, music_path=music_path, output_path=output_path)

    # YouTube Shorts uses same format as TikTok but with a different title position
    if title:
        for track in timeline["tracks"]:
            if track["type"] == "text":
                track["elements"][0]["position"] = "top-center"
                track["elements"][0]["style"]["size"] = 42

    return timeline


def instagram_reel_template(
    video_path: str,
    caption: str | None = None,
    music_path: str | None = None,
    output_path: str | None = None,
) -> dict[str, Any]:
    """Generate a timeline for Instagram Reels (9:16, 1080x1920)."""
    return tiktok_template(video_path, caption=caption, music_path=music_path, output_path=output_path)


def youtube_video_template(
    video_path: str,
    title: str | None = None,
    outro_path: str | None = None,
    music_path: str | None = None,
    output_path: str | None = None,
) -> dict[str, Any]:
    """Generate a timeline for standard YouTube video (16:9, 1920x1080).

    Args:
        video_path: Path to the main video content.
        title: Optional title card text (shown for first 3 seconds).
        outro_path: Optional outro clip appended at the end.
        music_path: Optional background music.
        output_path: Where to save the final video.
    """
    clips: list[dict[str, Any]] = [{"source": video_path, "start": 0}]

    if outro_path:
        clips.append({"source": outro_path, "start": 0})

    timeline: dict[str, Any] = {
        "width": 1920,
        "height": 1080,
        "tracks": [
            {
                "type": "video",
                "clips": clips,
            }
        ],
        "export": {"format": "mp4", "quality": "high"},
    }

    if title:
        timeline["tracks"].append(
            {
                "type": "text",
                "elements": [
                    {
                        "text": title,
                        "start": 0,
                        "duration": 3,
                        "position": "top-center",
                        "style": {"size": 48, "color": "white", "shadow": True},
                    }
                ],
            }
        )

    if music_path:
        timeline["tracks"].append(
            {
                "type": "audio",
                "clips": [
                    {"source": music_path, "start": 0, "volume": 0.3, "fade_in": 2.0, "fade_out": 3.0},
                ],
            }
        )

    return timeline


def instagram_post_template(
    video_path: str,
    caption: str | None = None,
    output_path: str | None = None,
) -> dict[str, Any]:
    """Generate a timeline for Instagram post (1:1, 1080x1080)."""
    timeline: dict[str, Any] = {
        "width": 1080,
        "height": 1080,
        "tracks": [
            {
                "type": "video",
                "clips": [
                    {"source": video_path, "start": 0},
                ],
            }
        ],
        "export": {"format": "mp4", "quality": "high"},
    }

    if caption:
        timeline["tracks"].append(
            {
                "type": "text",
                "elements": [
                    {
                        "text": caption,
                        "start": 0,
                        "position": "bottom-center",
                        "style": {"size": 32, "color": "white", "shadow": True},
                    }
                ],
            }
        )

    return timeline


def _estimate_size_mb(
    width: int,
    height: int,
    duration: float,
    quality: str,
    fps: float = 30.0,
) -> float:
    """Heuristic size estimate based on resolution, duration, and quality preset."""
    # Base bitrate estimates in Mbps for 1080p@30fps
    quality_bitrate = {
        "low": 2.5,
        "medium": 5.0,
        "high": 8.0,
        "ultra": 15.0,
    }
    bitrate = quality_bitrate.get(quality, 8.0)
    # Scale by pixel count relative to 1080p
    pixel_ratio = (width * height) / (1920 * 1080)
    bitrate *= pixel_ratio
    # Slight fps scaling
    bitrate *= min(fps, 60) / 30.0
    size_mb = (bitrate * duration) / 8.0
    return round(size_mb, 2)


def preview_template(
    template_name: str,
    video_path: str,
    duration: float | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Return a preview of what a template would produce without rendering.

    Returns:
        Dict with ``operations``, ``estimated_duration``, ``resolution``,
        ``format``, ``quality``, and ``estimated_size_mb`` for agent review
        before committing.
    """
    from .errors import MCPVideoError

    tmpl = TEMPLATES.get(template_name)
    if tmpl is None:
        raise MCPVideoError(
            f"Unknown template: {template_name}. Available: {list(TEMPLATES.keys())}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    timeline = tmpl(video_path, **kwargs)
    tracks = timeline.get("tracks", [])
    export = timeline.get("export", {})

    operations: list[dict[str, Any]] = []
    video_clips: list[dict] = []
    for track in tracks:
        ttype = track.get("type")
        if ttype == "video":
            video_clips = track.get("clips", [])
            operations.append({"op": "resize", "width": timeline["width"], "height": timeline["height"]})
            # Add concatenation if multiple clips
            if len(video_clips) > 1:
                operations.append({"op": "concat", "clip_count": len(video_clips)})
        elif ttype == "text":
            for elem in track.get("elements", []):
                operations.append(
                    {
                        "op": "add_text",
                        "text": elem.get("text", ""),
                        "position": elem.get("position", "center"),
                        "duration": elem.get("duration"),
                        "style": elem.get("style", {}),
                    }
                )
        elif ttype == "audio":
            for clip in track.get("clips", []):
                operations.append(
                    {
                        "op": "mix_audio",
                        "source": clip.get("source", ""),
                        "volume": clip.get("volume", 1.0),
                        "fade_in": clip.get("fade_in", 0.0),
                        "fade_out": clip.get("fade_out", 0.0),
                    }
                )

    total_duration = 0.0
    for clip in video_clips:
        dur = clip.get("duration") or clip.get("trim_end")
        if dur is None:
            dur = duration if duration is not None else 10.0
        total_duration += float(dur)

    quality = export.get("quality", "high")
    size_mb = _estimate_size_mb(
        timeline["width"],
        timeline["height"],
        total_duration,
        quality,
    )

    return {
        "success": True,
        "template": template_name,
        "operations": operations,
        "estimated_duration": round(total_duration, 1),
        "estimated_resolution": f"{timeline['width']}x{timeline['height']}",
        "estimated_size_mb": size_mb,
        "format": export.get("format", "mp4"),
        "quality": quality,
        "timeline": timeline,
    }


# Template registry
TEMPLATES: dict[str, Any] = {
    "tiktok": tiktok_template,
    "youtube-shorts": youtube_shorts_template,
    "instagram-reel": instagram_reel_template,
    "youtube": youtube_video_template,
    "instagram-post": instagram_post_template,
}
