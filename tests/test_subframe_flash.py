import pytest

from kinocut.bounded_process import run_bounded
from kinocut.subframe_flash import compute_subframe_flash_split, render_subframe_flash, render_subframe_flash_strip


def _pixels(path):
    proc = run_bounded(
        ["ffmpeg", "-v", "error", "-i", str(path), "-pix_fmt", "gray", "-threads", "1", "-f", "rawvideo", "pipe:1"],
        text=False,
        timeout=20,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


@pytest.mark.parametrize(("offset", "pair"), [(0, (255, 0)), (0.25, (191, 64)), (0.5, (128, 128)), (0.75, (64, 191))])
def test_decoded_flash(tmp_path, offset, pair):
    path = tmp_path / "flash.mp4"
    onset = (4 + offset) * 100
    assert compute_subframe_flash_split(onset, 10) == {4: 1 - offset, 5: offset}
    render_subframe_flash(path, fps=10, width=13, height=9, target_onset_ms=onset)
    assert _pixels(path) == b"".join(bytes([value]) * (13 * 9) for value in [0] * 4 + list(pair) + [0] * 4)


def test_strip_decoded_in_order(tmp_path):
    path = tmp_path / "strip.mkv"
    render_subframe_flash_strip(path, fps=4, width=8, height=8, peak_brightness=0.8)
    expected = [0, 0, 204, 0, 0, 0, 153, 51, 0, 0, 102, 102, 0, 0, 51, 153]
    assert _pixels(path) == b"".join(bytes([value]) * 64 for value in expected)


def test_split_cannot_be_truncated(tmp_path):
    path = tmp_path / "truncated.mp4"
    with pytest.raises(ValueError, match="beyond the clip"):
        render_subframe_flash(path, fps=10, target_onset_ms=950)
    assert not path.exists()
