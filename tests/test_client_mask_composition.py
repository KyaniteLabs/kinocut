"""The extracted mask family remains a working public Client boundary."""

from pathlib import Path

import pytest

import kinocut
import mcp_video
from kinocut.client.media import ClientMediaMixin
from kinocut.client.masks import ClientMasksMixin
from kinocut.engine_probe import probe


@pytest.mark.parametrize("method", ["apply_mask", "luma_key", "shape_mask"])
def test_client_mask_family_renders_decodable_media(method, sample_video, sample_watermark_png, tmp_path):
    assert kinocut.Client is mcp_video.Client
    assert getattr(ClientMediaMixin, method) is getattr(ClientMasksMixin, method)
    output = tmp_path / f"{method}.mp4"
    params = {"mask": sample_watermark_png} if method == "apply_mask" else {}
    result = getattr(kinocut.Client(), method)(sample_video, output=str(output), **params)
    assert result.output_path == str(output)
    assert Path(result.output_path).is_file()
    media = probe(result.output_path)
    assert media.width > 0 and media.height > 0 and media.duration > 0
