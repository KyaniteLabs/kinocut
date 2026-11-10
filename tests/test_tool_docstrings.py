"""Docstring Args blocks move into parameter schemas without losing help."""

import asyncio

from kinocut.tool_docstrings import fold_args


def _schema(*names, described=()):
    return {
        "type": "object",
        "properties": {
            n: ({"type": "string", "description": "own"} if n in described else {"type": "string"}) for n in names
        },
    }


def test_args_move_to_properties_and_leave_the_description():
    schema = _schema("input_path", "accurate")
    doc = """Trim a clip.

    Args:
        input_path: Absolute path to the input video.
        accurate: Frame-accurate seeking (slower).  Default False uses fast
            input seeking which may land on the nearest keyframe.
    """
    assert fold_args(doc, schema) == "Trim a clip."
    assert schema["properties"]["input_path"]["description"] == "Absolute path to the input video."
    assert schema["properties"]["accurate"]["description"] == (
        "Frame-accurate seeking (slower). Default False uses fast input seeking which may land on the nearest keyframe."
    )


def test_existing_property_description_wins():
    schema = _schema("clips", described=("clips",))
    assert fold_args("Merge.\n\nArgs:\n    clips: docstring text\n", schema) == "Merge."
    assert schema["properties"]["clips"]["description"] == "own"


def test_sections_after_args_are_kept():
    schema = _schema("a")
    doc = "Check.\n\nArgs:\n    a: thing\n\nReturns:\n    dict with warnings.\n"
    assert fold_args(doc, schema) == "Check.\n\nReturns:\n    dict with warnings."


def test_unknown_parameter_leaves_everything_untouched():
    schema = _schema("a")
    doc = "Do.\n\nArgs:\n    a: thing\n    ghost: not a parameter\n"
    assert fold_args(doc, schema) == doc.strip()
    assert "description" not in schema["properties"]["a"]


def test_unparseable_block_leaves_everything_untouched():
    schema = _schema("a")
    doc = "Do.\n\nArgs:\n    free prose that is not an entry\n"
    assert fold_args(doc, schema) == doc.strip()


def test_no_registered_tool_still_advertises_an_args_block():
    from kinocut.server import mcp  # conftest registers the full surface

    tools = asyncio.run(mcp.list_tools())
    assert len(tools) > 100
    assert [t.name for t in tools if "Args:" in (t.description or "")] == []
    trim = next(t for t in tools if t.name == "video_trim")
    assert "frame-accurate" in trim.inputSchema["properties"]["accurate"]["description"]
