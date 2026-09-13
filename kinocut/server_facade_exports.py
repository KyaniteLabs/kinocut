"""Closed compatibility exports for the public MCP server facade."""

from .server_tools_rescue import (
    video_rescue_inspect as video_rescue_inspect,
    video_rescue_plan as video_rescue_plan,
    video_rescue_render as video_rescue_render,
)
from .server_tools_postrescue import (
    video_composition_plan as video_composition_plan,
    video_creative_autopilot_plan as video_creative_autopilot_plan,
    video_remote_egress_plan as video_remote_egress_plan,
    video_restoration_plan as video_restoration_plan,
    video_semantic_query as video_semantic_query,
    video_semantic_timeline as video_semantic_timeline,
    video_timeline_edit_plan as video_timeline_edit_plan,
    video_visual_transform_plan as video_visual_transform_plan,
)
from .server_tools_release import (
    video_benchmark_run as video_benchmark_run,
    video_capabilities as video_capabilities,
    video_cost_ledger as video_cost_ledger,
    video_learning_report as video_learning_report,
    video_publish_gate as video_publish_gate,
    video_recipe_capture as video_recipe_capture,
    video_review_decision as video_review_decision,
    video_review_package as video_review_package,
)
from .server_tools_revideo import (
    revideo_install as revideo_install,
    revideo_materialize as revideo_materialize,
    revideo_render as revideo_render,
    revideo_render_job as revideo_render_job,
)

__all__ = (  # noqa: RUF022 - preserve registration-family import order
    "video_rescue_inspect",
    "video_rescue_plan",
    "video_rescue_render",
    "video_composition_plan",
    "video_creative_autopilot_plan",
    "video_remote_egress_plan",
    "video_restoration_plan",
    "video_semantic_query",
    "video_semantic_timeline",
    "video_timeline_edit_plan",
    "video_visual_transform_plan",
    "video_benchmark_run",
    "video_capabilities",
    "video_cost_ledger",
    "video_learning_report",
    "video_publish_gate",
    "video_recipe_capture",
    "video_review_decision",
    "video_review_package",
    "revideo_install",
    "revideo_materialize",
    "revideo_render",
    "revideo_render_job",
)
