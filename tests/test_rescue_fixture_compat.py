"""Compatibility regressions for rescue acceptance-test fixtures."""

from pathlib import Path

from tests import rescue_fixtures


def test_rotation_fixture_uses_ffmpeg_5_compatible_stream_metadata(tmp_path, monkeypatch):
    commands: list[list[str]] = []

    def capture_run(command: list[str]) -> None:
        commands.append(command)
        Path(command[-1]).touch()

    monkeypatch.setattr(rescue_fixtures, "_run", capture_run)

    rescue_fixtures.make_rescue_fixture(tmp_path, rotation=90)

    rotation_command = commands[-1]
    assert "-display_rotation" not in rotation_command
    metadata_index = rotation_command.index("-metadata:s:v:0")
    assert rotation_command[metadata_index + 1] == "rotate=90"
