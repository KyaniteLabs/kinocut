"""Shared historical mono and explicit stereo source-window projection."""

from dataclasses import asdict


def source_window_receipts(windows, channels):
    if channels == 1:
        return [asdict(window) for window in windows]
    return [
        {
            "cue_id": window.cue_id,
            "in_frame": window.in_sample,
            "out_frame": window.out_sample,
            "frame_count": window.sample_count,
            "sample_rate_hz": window.sample_rate_hz,
            "channel_count": channels,
            "interleaved_sample_count": window.sample_count * channels,
        }
        for window in windows
    ]
