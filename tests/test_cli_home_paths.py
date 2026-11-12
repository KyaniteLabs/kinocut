"""Human CLI text never shows the user's home directory; JSON keeps absolute paths (#761)."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from kinocut.cli import formatting, rescue_formatting
from kinocut.cli.common import output_json
from kinocut.cli.home_paths import collapse_home


@pytest.fixture
def home(tmp_path, monkeypatch):
    fake_home = tmp_path / "someuser"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    return str(fake_home)


def test_collapse_home_rewrites_only_the_home_prefix(home):
    assert collapse_home(f"{home}/clips/a.mp4") == "~/clips/a.mp4"
    assert collapse_home(f"saved to {home}.") == "saved to ~."
    assert collapse_home(f"'{home}'") == "'~'"
    assert collapse_home(f"{home}-other/a.mp4") == f"{home}-other/a.mp4"
    assert collapse_home("/srv/clips/a.mp4") == "/srv/clips/a.mp4"


def test_human_output_hides_home(home, capsys):
    cut = f"{home}/clips/final_cut.mp4"
    formatting._format_path_panel("Trimmed", {"output_path": cut})
    formatting._format_edit_text({"output_path": cut, "duration": 3.0, "resolution": "1920x1080"})
    formatting.err_console.print(f"Could not read {cut}")
    rescue_formatting.console.print(f"Rescued into {cut}")

    out, err = capsys.readouterr()
    for text in (out, err):
        assert home not in text
    assert "~/clips/final_cut.mp4" in out
    assert "~/clips/final_cut.mp4" in err


def test_json_output_keeps_absolute_paths(home, capsys):
    cut = f"{home}/clips/final_cut.mp4"
    output_json({"output_path": cut})
    assert json.loads(capsys.readouterr().out)["output_path"] == cut


def test_direct_human_output_collapses_home_but_json_preserves_it(home, capsys):
    from kinocut.cli.handlers_direct import handle_direct_command

    cut = f"{home}/clips/final_cut.mp4"
    args = SimpleNamespace(
        command="direct",
        input=f"{home}/clips/source.mp4",
        direction="louder",
        output=cut,
        apply=False,
        overwrite=False,
    )
    plan = {
        "input_path": args.input,
        "output_path": cut,
        "steps": [],
        "assumptions": [],
        "question": None,
        "unrecognized": [],
        "estimate": {"step_count": 0},
    }
    result = {"success": True, "plan": plan, "assumptions": [], "question": None, "plan_id": "fixture"}
    with patch("kinocut.server_tools_direct.video_direct", return_value=result):
        handle_direct_command(args, use_json=False)
        human = capsys.readouterr().out
        handle_direct_command(args, use_json=True)
        machine = capsys.readouterr().out

    assert home not in human
    assert json.loads(human)["plan"]["output_path"] == "~" + cut[len(home) :]
    assert json.loads(machine)["plan"]["output_path"] == cut


@pytest.mark.parametrize(
    "home",
    ["/synthetic/rené", r"C:\Users\josé"],
)
def test_direct_human_output_hides_non_ascii_and_windows_home_paths(home, monkeypatch, capsys):
    from kinocut.cli.handlers_direct import handle_direct_command

    monkeypatch.setenv("HOME", home)
    monkeypatch.setenv("USERPROFILE", home)
    cut = home + r"\clips\final_cut.mp4" if "\\" in home else home + "/clips/final_cut.mp4"
    args = SimpleNamespace(
        command="direct",
        input="fixture.mp4",
        direction="louder",
        output=cut,
        apply=False,
        overwrite=False,
    )
    result = {"success": True, "plan": {"output_path": cut}, "question": None}
    with patch("kinocut.server_tools_direct.video_direct", return_value=result):
        handle_direct_command(args, use_json=False)
        human = capsys.readouterr().out
        handle_direct_command(args, use_json=True)
        machine = capsys.readouterr().out

    assert home not in human
    assert json.loads(human)["plan"]["output_path"] == "~" + cut[len(home) :]
    assert json.loads(machine)["plan"]["output_path"] == cut
