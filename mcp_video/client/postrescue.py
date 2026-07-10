"""Python client methods for post-rescue planning capabilities."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from ..postrescue import call_post_rescue

Request = Mapping[str, Any]


class ClientPostRescueMixin:
    """Build inspectable plans without rendering media or contacting providers."""

    @staticmethod
    def _post_rescue(function: Callable[[Request], dict[str, Any]], request: Request) -> dict[str, Any]:
        return call_post_rescue(function, request)

    def semantic_timeline(self, request: Request) -> dict[str, Any]:
        from ..postrescue import semantic_timeline

        return self._post_rescue(semantic_timeline, request)

    def semantic_query(self, request: Request) -> dict[str, Any]:
        from ..postrescue import semantic_query

        return self._post_rescue(semantic_query, request)

    def timeline_edit_plan(self, request: Request) -> dict[str, Any]:
        from ..postrescue import timeline_edit_plan

        return self._post_rescue(timeline_edit_plan, request)

    def visual_transform_plan(self, request: Request) -> dict[str, Any]:
        from ..postrescue import visual_transform_plan

        return self._post_rescue(visual_transform_plan, request)

    def restoration_plan(self, request: Request) -> dict[str, Any]:
        from ..postrescue import restoration_plan

        return self._post_rescue(restoration_plan, request)

    def composition_plan(self, request: Request) -> dict[str, Any]:
        from ..postrescue import composition_plan

        return self._post_rescue(composition_plan, request)

    def creative_autopilot_plan(self, request: Request) -> dict[str, Any]:
        from ..postrescue import creative_autopilot_plan

        return self._post_rescue(creative_autopilot_plan, request)

    def remote_egress_plan(self, request: Request) -> dict[str, Any]:
        from ..postrescue import remote_egress_plan

        return self._post_rescue(remote_egress_plan, request)
