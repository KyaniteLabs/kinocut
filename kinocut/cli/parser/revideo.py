"""CLI argument parsers for the local Revideo bridge."""

from __future__ import annotations

import argparse

from ...defaults import DEFAULT_REVIDEO_INSTALL_TIMEOUT, DEFAULT_REVIDEO_RENDER_TIMEOUT


def add_parsers(subparsers: argparse._SubParsersAction) -> None:
    materialize = subparsers.add_parser("revideo-materialize", help="Materialize a pinned Revideo bridge project")
    materialize.add_argument("dest")
    materialize.add_argument("--job-json", required=True, help="Inline Revideo job JSON object")
    materialize.add_argument("--scene-source")

    install = subparsers.add_parser("revideo-install", help="Install locked Revideo dependencies")
    install.add_argument("project_dir")
    install.add_argument("--timeout", type=float, default=DEFAULT_REVIDEO_INSTALL_TIMEOUT)

    render = subparsers.add_parser("revideo-render", help="Render a materialized Revideo project")
    render.add_argument("project_dir")
    render.add_argument("output_path")
    render.add_argument("--timeout", type=float, default=DEFAULT_REVIDEO_RENDER_TIMEOUT)

    render_job = subparsers.add_parser("revideo-render-job", help="Materialize, install, and render one Revideo job")
    render_job.add_argument("output_path")
    render_job.add_argument("--job-json", required=True, help="Inline Revideo job JSON object")
    render_job.add_argument("--work-dir")
    render_job.add_argument("--scene-source")
    render_job.add_argument("--install-timeout", type=float, default=DEFAULT_REVIDEO_INSTALL_TIMEOUT)
    render_job.add_argument("--render-timeout", type=float, default=DEFAULT_REVIDEO_RENDER_TIMEOUT)
