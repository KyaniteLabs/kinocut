"""Source metadata and explicit grayscale policy for quality measurements."""

import logging

from .defaults import DEFAULT_QUALITY_GRAYSCALE_INPUT_FILTER, QUALITY_SIGNALSTATS_CACHE_MAX_ENTRIES
from .errors import ProcessingError
from .ffmpeg_helpers import _run_ffprobe_json

logger = logging.getLogger(__name__)


class QualitySourceMixin:
    """Reuse verified stream metadata while the measurement source is unchanged."""

    def _quality_source_probe(self, video: str) -> dict:
        key = self._signalstats_cache_key(video)
        if not hasattr(self, "_quality_source_cache"):
            self._quality_source_cache = {}
        elif key is not None and key in self._quality_source_cache:
            data = self._quality_source_cache.pop(key)
            self._quality_source_cache[key] = data
            return data
        data = _run_ffprobe_json(video)
        streams = data.get("streams") if isinstance(data, dict) else None
        if not isinstance(streams, list) or not streams or not all(isinstance(stream, dict) for stream in streams):
            raise ProcessingError("ffprobe stream metadata", 1, "No usable source streams")
        for stream in streams:
            if not isinstance(stream.get("codec_type"), str) or not stream["codec_type"]:
                raise ProcessingError("ffprobe stream metadata", 1, "Source stream type unavailable")
            if stream.get("codec_type") == "video" and (
                not isinstance(stream.get("pix_fmt"), str) or not stream["pix_fmt"]
            ):
                raise ProcessingError("ffprobe stream metadata", 1, "Source video pixel format unavailable")
        if key is not None and self._signalstats_cache_key(video) == key:
            self._quality_source_cache[key] = data
            while len(self._quality_source_cache) > QUALITY_SIGNALSTATS_CACHE_MAX_ENTRIES:
                self._quality_source_cache.pop(next(iter(self._quality_source_cache)))
        return data

    def _quality_input_filter(self, video: str, tail: str) -> str:
        """Treat gray samples as full-range before any gray-to-YUV conversion.

        FFmpeg implicitly treats 8-bit gray as full range, even with a TV tag,
        but older converters can interpret higher depths differently. Pin that
        policy for all gray depths; YUV samples retain their native range.
        """
        streams = self._quality_source_probe(video)["streams"]
        formats = [stream["pix_fmt"] for stream in streams if stream.get("codec_type") == "video"]
        if not formats:
            raise ProcessingError("ffprobe stream metadata", 1, "Source video pixel format unavailable")
        grayscale = {pixel_format.startswith("gray") for pixel_format in formats}
        if len(grayscale) > 1:
            raise ProcessingError("ffprobe stream metadata", 1, "Ambiguous mixed grayscale and color video streams")
        return f"{DEFAULT_QUALITY_GRAYSCALE_INPUT_FILTER},{tail}" if True in grayscale else tail

    def _has_audio_stream(self, video: str) -> bool | None:
        """Return whether the source has audio, or None if metadata is unusable."""
        try:
            probe = self._quality_source_probe(video)
        except ProcessingError as exc:
            logger.warning("ffprobe audio stream check failed: %s", type(exc).__name__)
            return None
        return any(stream.get("codec_type") == "audio" for stream in probe["streams"])
