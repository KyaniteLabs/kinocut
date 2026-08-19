"""Escaping rules for paths embedded in FFmpeg filter option values.

Regression cover for the Windows subtitle burn-in failure: an unquoted filter option
value is unescaped twice, so a single-pass escape leaves the drive-letter colon acting
as an option separator and lets the backslashes be eaten as escape characters.
"""

from kinocut.ffmpeg_helpers import _escape_ffmpeg_filter_path, _escape_ffmpeg_filter_value


def test_windows_path_survives_both_unescaping_passes():
    # The colon is escaped twice and separators become forward slashes, so neither is
    # consumed by the filtergraph parser before the filter sees the filename.
    assert _escape_ffmpeg_filter_path(r"C:\kctest\subs.ass") == "C\\\\:/kctest/subs.ass"


def test_single_pass_escape_is_not_enough_for_a_windows_path():
    # Documents the bug: this is what the value helper produces, and FFmpeg reads the
    # filename as "C" and the remainder as an original_size option.
    assert _escape_ffmpeg_filter_value(r"C:\kctest\subs.ass") == "C\\:\\\\kctest\\\\subs.ass"


def test_posix_path_is_unchanged():
    assert _escape_ffmpeg_filter_path("/tmp/kinocut/subs.ass") == "/tmp/kinocut/subs.ass"


def test_posix_path_with_a_colon_is_escaped():
    assert _escape_ffmpeg_filter_path("/tmp/a:b/subs.ass") == "/tmp/a\\\\:b/subs.ass"


def test_relative_path_is_unchanged():
    assert _escape_ffmpeg_filter_path("subs.ass") == "subs.ass"


def test_value_helper_still_used_for_scalars():
    # Numbers, colours and font *names* keep the single-pass helper.
    assert _escape_ffmpeg_filter_value("15.0") == "15.0"
    assert _escape_ffmpeg_filter_value("white") == "white"
