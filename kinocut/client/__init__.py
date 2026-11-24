"""Kinocut Python client: a clean API for programmatic video editing."""

from __future__ import annotations

from .planning import ClientPlanningMixin
from .projects import ClientProjectsMixin
from .productions import ClientProductionsMixin
from .base import ClientBase
from .media import ClientMediaMixin
from .effects import ClientEffectsMixin
from .audio import ClientAudioMixin
from .ai import ClientAiMixin
from .hyperframes import ClientHyperframesMixin
from .image import ClientImageMixin
from .quality import ClientQualityMixin
from .workflow import ClientWorkflowMixin


class Client(
    ClientBase,
    ClientPlanningMixin,
    ClientProjectsMixin,
    ClientProductionsMixin,
    ClientMediaMixin,
    ClientEffectsMixin,
    ClientAudioMixin,
    ClientAiMixin,
    ClientHyperframesMixin,
    ClientImageMixin,
    ClientQualityMixin,
    ClientWorkflowMixin,
):
    """mcp-video client for programmatic video editing.

    Usage:
        from mcp_video import Client
        editor = Client()

        result = editor.trim("input.mp4", start="00:00:30", duration="00:00:15")
        print(result.output_path)
    """
