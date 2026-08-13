"""Pluggable 360 director: local first, cloud only with explicit opt-in."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

from kinocut.errors import MCPVideoError
from kinocut.te.sphere_plan import propose_sphere_plan, validate_sphere_plan
from kinocut.validation import SPHERE_CLOUD_DIRECTORS, SPHERE_LOCAL_DIRECTORS

logger = logging.getLogger(__name__)

DirectorFn = Callable[[dict[str, Any]], dict[str, Any]]

ENV_DIRECTOR = "KINOCUT_360_DIRECTOR"
ENV_MODEL = "KINOCUT_360_DIRECTOR_MODEL"
ENV_BASE_URL = "KINOCUT_360_DIRECTOR_BASE_URL"
ENV_ALLOW_CLOUD = "KINOCUT_360_DIRECTOR_ALLOW_CLOUD"


def detect_sphere_director(
    *,
    director: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
) -> dict[str, Any]:
    """Doctor-visible director probe. Does not call a network."""
    chosen = (director or os.environ.get(ENV_DIRECTOR) or "").strip() or None
    resolved_model = (model or os.environ.get(ENV_MODEL) or "").strip() or None
    resolved_url = (base_url or os.environ.get(ENV_BASE_URL) or "").strip() or None
    kind = _director_kind(chosen)
    return {
        "available": bool(chosen),
        "id": chosen,
        "kind": kind,
        "model": resolved_model,
        "base_url": resolved_url,
        "local_ids": sorted(SPHERE_LOCAL_DIRECTORS),
        "cloud_ids": sorted(SPHERE_CLOUD_DIRECTORS),
    }


def apply_director(
    source: str,
    *,
    preset: str = "desk",
    layout: str | None = None,
    aspect: str = "16:9",
    director: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    allow_cloud: bool = False,
    propose: DirectorFn | None = None,
) -> dict[str, Any]:
    """Run a director or fall back to heuristic. Never used at render time."""
    heuristic = propose_sphere_plan(source, preset=preset, layout=layout, aspect=aspect, writer_kind="heuristic")
    detected = detect_sphere_director(director=director, model=model, base_url=base_url)
    if propose is None and not detected["available"]:
        return heuristic
    _assert_cloud_allowed(detected, allow_cloud)
    if propose is None:
        heuristic["writer"] = {
            "kind": "heuristic",
            "provider": detected["id"],
            "model": detected["model"],
            "unavailable": True,
            "reason": "no_injected_director",
        }
        return heuristic
    try:
        raw = propose(heuristic)
        plan = validate_sphere_plan(raw)
    except Exception as exc:
        logger.warning("360 director unavailable: %s", exc)
        heuristic["writer"] = {
            "kind": "heuristic",
            "provider": detected["id"] or "injected",
            "model": detected["model"],
            "unavailable": True,
            "reason": "capability_unavailable",
        }
        return heuristic
    plan["writer"] = {
        "kind": "model",
        "provider": detected["id"] or "injected",
        "model": detected["model"],
        "unavailable": False,
    }
    plan["status"] = "proposed"
    return validate_sphere_plan(plan)


def parse_director_json(payload: str) -> dict[str, Any]:
    """Validate director output is JSON matching the plan schema."""
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise MCPVideoError(
            "Director returned invalid JSON.",
            error_type="validation_error",
            code="capability_unavailable",
        ) from exc
    if not isinstance(data, dict):
        raise MCPVideoError(
            "Director JSON must be an object.",
            error_type="validation_error",
            code="capability_unavailable",
        )
    return validate_sphere_plan(data)


def _director_kind(director: str | None) -> str | None:
    if not director:
        return None
    if director in SPHERE_CLOUD_DIRECTORS:
        return "cloud"
    if director in SPHERE_LOCAL_DIRECTORS:
        return "local"
    if director.startswith("http"):
        host = (urlparse(director).hostname or "").lower()
        return "local" if host in {"localhost", "127.0.0.1", "::1"} else "cloud"
    return "local"


def _assert_cloud_allowed(detected: dict[str, Any], allow_cloud: bool) -> None:
    env_allow = os.environ.get(ENV_ALLOW_CLOUD, "").strip().lower() in {"1", "true", "yes"}
    if detected.get("kind") != "cloud":
        return
    if allow_cloud or env_allow:
        return
    raise MCPVideoError(
        "Cloud 360 director requires explicit allow_cloud opt-in.",
        error_type="validation_error",
        code="cloud_execution_denied",
    )
