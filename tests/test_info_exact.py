"""Opt-in exact probe: decoded frame count and raw rational frame rates (`kino info --exact`)."""

from __future__ import annotations

import json
import re
import subprocess
import sys

import pytest

from kinocut import Client
from kinocut.engine import probe, probe_exact
from kinocut.engine_probe import _exact_stream_fields, _raw_rational_rate
from kinocut.models import ExactVideoInfo

EXACT_KEYS = {"frame_count", "frame_count_source", "r_frame_rate", "avg_frame_rate"}


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("24/1", "24/1"),
        ("24000/1001", "24000/1001"),
        ("30000/1001", "30000/1001"),
        ("25", "25"),
        ("0/1", None),
        ("0/0", None),
        ("24/0", None),
        ("N/A", None),
        ("", None),
        (None, None),
        (24, None),
    ],
)
def test_raw_rational_rate_is_unchanged_or_none(value, expected):
    assert _raw_rational_rate(value) == expected


def test_exact_stream_fields_without_measurement_are_none():
    fields = _exact_stream_fields({"r_frame_rate": "0/1"})
    assert fields == {
        "frame_count": None,
        "frame_count_source": None,
        "r_frame_rate": None,
        "avg_frame_rate": None,
    }


def test_exact_stream_fields_reject_unparseable_count():
    for raw in ("abc", "-3", "1.5"):
        assert _exact_stream_fields({"nb_read_frames": raw})["frame_count"] is None


def test_exact_stream_fields_accept_decoded_count():
    fields = _exact_stream_fields({"nb_read_frames": "48", "r_frame_rate": "24/1", "avg_frame_rate": "24/1"})
    assert fields["frame_count"] == 48
    assert fields["frame_count_source"] == "decoded"


def test_probe_exact_reports_decoded_count_and_raw_rates(sample_video):
    info = probe_exact(sample_video)
    assert isinstance(info, ExactVideoInfo)
    assert isinstance(info.frame_count, int) and info.frame_count > 0
    assert info.frame_count_source == "decoded"
    assert re.fullmatch(r"\d+/\d+", info.r_frame_rate or "")
    assert re.fullmatch(r"\d+/\d+", info.avg_frame_rate or "")
    # the exact mode is a superset of the default probe
    base = probe(sample_video)
    for key, value in base.model_dump().items():
        assert getattr(info, key) == value


def test_default_probe_is_unchanged(sample_video):
    dumped = probe(sample_video).model_dump()
    assert EXACT_KEYS.isdisjoint(dumped)


def test_client_info_exact_flag(sample_video):
    client = Client()
    assert EXACT_KEYS.isdisjoint(client.info(sample_video).model_dump())
    exact = client.info(sample_video, exact=True)
    assert exact.frame_count == probe_exact(sample_video).frame_count


def test_mcp_video_info_exact_flag(sample_video):
    from kinocut.server_tools_basic import video_info

    default = video_info(sample_video)
    assert default["success"] and EXACT_KEYS.isdisjoint(default["info"])
    exact = video_info(sample_video, exact=True)
    assert exact["success"]
    assert set(exact["info"]) >= EXACT_KEYS
    assert exact["info"]["frame_count_source"] == "decoded"


def test_cli_info_exact_json(sample_video):
    result = subprocess.run(
        [sys.executable, "-m", "kinocut", "--format", "json", "info", sample_video, "--exact"],
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert set(payload["data"]) >= EXACT_KEYS
    plain = subprocess.run(
        [sys.executable, "-m", "kinocut", "--format", "json", "info", sample_video],
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    assert EXACT_KEYS.isdisjoint(json.loads(plain.stdout)["data"])
