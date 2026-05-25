"""Tests for layout grid and split screen guardrails."""

import pytest



class TestLayoutGridGuardrails:
    @pytest.mark.skip("Requires multiple video fixtures with probing")
    def test_excess_clips_warns(self):
        pass


class TestSplitScreenGuardrails:
    @pytest.mark.skip("Requires two video fixtures with different durations")
    def test_duration_mismatch_warns(self):
        pass
