"""Keep the user's home directory out of text people read.

Human CLI output shows ``~/clips/a.mp4`` instead of ``/home/<user>/clips/a.mp4``
so a screenshot or screen share doesn't reveal the account name. JSON output keeps
absolute paths because machines need them.
"""

from __future__ import annotations

import os
import re
import sys
from typing import Any, TextIO

from rich.console import Console
from rich.text import Text


def collapse_home(text: str) -> str:
    """Replace the home directory prefix of every path in ``text`` with ``~``."""
    home = os.path.expanduser("~").rstrip("/\\")
    if not home or home == "~" or len(home) < 2:
        return text
    return re.sub(re.escape(home) + r"(?=[/\\]|$|[\s'\"\]\),:;]|\.(?:\s|$))", "~", text)


class HomeCollapsingStream:
    """A text stream that collapses home paths before writing to stdout or stderr.

    The target is looked up on every write so pytest's capture and other
    stream swaps keep working.
    """

    def __init__(self, stderr: bool = False) -> None:
        self._stderr = stderr

    @property
    def _target(self) -> TextIO:
        return sys.stderr if self._stderr else sys.stdout

    def write(self, text: str) -> int:
        self._target.write(collapse_home(text))
        return len(text)

    def flush(self) -> None:
        self._target.flush()

    def isatty(self) -> bool:
        return self._target.isatty()

    def fileno(self) -> int:
        return self._target.fileno()

    @property
    def encoding(self) -> str:
        return getattr(self._target, "encoding", None) or "utf-8"


class HomeCollapsingConsole(Console):
    """A Rich console that shows ``~`` for the home directory in human text.

    Strings are collapsed before Rich wraps them, so a long path can't be split
    across lines with the home prefix intact. The stream catches anything that
    reaches the terminal by another route, such as a prebuilt ``Text``.
    """

    def __init__(self, *, stderr: bool = False, **kwargs: Any) -> None:
        super().__init__(file=HomeCollapsingStream(stderr=stderr), stderr=stderr, **kwargs)

    def render_str(self, text: str, **kwargs: Any) -> Text:
        return super().render_str(collapse_home(text), **kwargs)
