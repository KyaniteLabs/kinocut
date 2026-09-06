"""Escaping rules for paths embedded in FFmpeg filter option values.

Regression cover for two historical bugs, both verified against a real
``subtitles=`` burn-in (ffmpeg 7.x):

1. The Windows subtitle failure: an unquoted filter option value is unescaped
   twice, so a single-pass escape leaves the drive-letter colon acting as an
   option separator and lets the backslashes be eaten as escape characters.
2. The POSIX regressions of the first fix: unconditional backslash
   normalisation corrupted legal POSIX filenames (``/tmp/a\\b.ass`` opened as
   ``/tmp/a/b.ass``), and the filtergraph metacharacters ``, ; [ ] =`` passed
   through raw, splitting the filtergraph.
"""

from kinocut.ffmpeg_helpers import _escape_ffmpeg_filter_path, _escape_ffmpeg_filter_value


class TestWindowsPaths:
    def test_windows_path_survives_both_unescaping_passes(self):
        # Unquoted with a double-escaped colon and forward-slashed separators:
        # quoting does not protect a colon from the option parser.
        assert _escape_ffmpeg_filter_path(r"C:\kctest\subs.ass") == "C\\\\:/kctest/subs.ass"

    def test_windows_unc_path_is_normalised(self):
        assert _escape_ffmpeg_filter_path(r"\\server\share\subs.ass") == "//server/share/subs.ass"

    def test_single_pass_escape_is_not_enough_for_a_windows_path(self):
        # Documents the original bug: this is what the value helper produces,
        # and FFmpeg reads the filename as "C" plus an original_size option.
        assert _escape_ffmpeg_filter_value(r"C:\kctest\subs.ass") == "C\\:\\\\kctest\\\\subs.ass"


class TestPosixPaths:
    def test_plain_posix_path_is_quoted(self):
        assert _escape_ffmpeg_filter_path("/tmp/kinocut/subs.ass") == "'/tmp/kinocut/subs.ass'"

    def test_relative_path_is_quoted(self):
        assert _escape_ffmpeg_filter_path("subs.ass") == "'subs.ass'"

    def test_literal_backslash_is_preserved_not_eaten(self):
        # Regression: the unquoted form corrupted /tmp/a\b.ass into /tmp/a/b.ass.
        # The quoted single-pass form lets the backslash reach the filter.
        assert _escape_ffmpeg_filter_path("/tmp/a\\b.ass") == "'/tmp/a\\\\b.ass'"

    def test_filtergraph_metacharacters_are_escaped(self):
        # Regression: , ; [ ] = passed through raw and split the filtergraph.
        assert _escape_ffmpeg_filter_path("x,y.ass") == "'x\\,y.ass'"
        assert _escape_ffmpeg_filter_path("x;y.ass") == "'x\\;y.ass'"
        assert _escape_ffmpeg_filter_path("x[y].ass") == "'x\\[y\\].ass'"
        assert _escape_ffmpeg_filter_path("a=b.ass") == "'a\\=b.ass'"

    def test_posix_path_with_a_colon_is_escaped(self):
        assert _escape_ffmpeg_filter_path("/tmp/a:b/subs.ass") == "'/tmp/a\\:b/subs.ass'"

    def test_apostrophe_documented_limitation(self):
        # Filenames with apostrophes fail under EVERY strategy we tested
        # (quoted, unquoted, every doubling) — including the historical ones.
        # This documents the output shape; ffmpeg itself cannot open the file.
        assert _escape_ffmpeg_filter_path("it's.ass") == "'it'\\''s.ass'"


def test_value_helper_still_used_for_scalars():
    # Numbers, colours and font *names* keep the single-pass helper, unquoted.
    assert _escape_ffmpeg_filter_value("15.0") == "15.0"
    assert _escape_ffmpeg_filter_value("white") == "white"
