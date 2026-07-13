"""Private bounded-consumption helpers for sound public boundaries."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from itertools import islice
import logging
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from kinocut_sound._model_boundary import dump_revalidate_model
from kinocut_sound.limits import MAX_SCRIPT_ACTORS, MAX_SCRIPT_NAME_LENGTH_CHARS

logger = logging.getLogger(__name__)

ModelT = TypeVar("ModelT", bound=BaseModel)
ValueT = TypeVar("ValueT")
ErrorT = TypeVar("ErrorT", bound=Exception)


def bounded_model_iterable(
    values: object,
    model_type: type[ModelT],
    maximum: int,
) -> tuple[ModelT, ...]:
    """Consume at most max+1 values before model traversal and revalidation."""
    collected = normalize_ingress(
        lambda: tuple(islice(iter(values), maximum + 1)),
        lambda _: ValueError("model collection traversal failed"),
    )
    if len(collected) > maximum:
        raise ValueError("model collection exceeds its resource ceiling")
    return tuple(dump_revalidate_model(value, model_type) for value in collected)


def validate_wf_name(value: object) -> str:
    """Return one bounded, nonblank WF name without control characters."""
    if not isinstance(value, str):
        raise TypeError("WF name must be a string")
    if not value.strip() or len(value) > MAX_SCRIPT_NAME_LENGTH_CHARS or any(ord(char) < 0x20 for char in value):
        raise ValueError("WF name is invalid")
    return value


def script_validation_code(error: ValidationError) -> str:
    """Classify a structural script validation failure without its raw values."""
    locations = tuple(part for item in error.errors() for part in item["loc"])
    if "lines" in locations or "text" in locations:
        return "invalid_line"
    if "scene_id" in locations:
        return "invalid_scene"
    return "invalid_script"


def validate_wf_routes(value: object) -> dict[str, str]:
    """Bound route count before validating and copying route entries."""
    if not isinstance(value, Mapping):
        raise TypeError("WF routes must be a mapping")
    entries = normalize_ingress(
        lambda: tuple(islice(value.items(), MAX_SCRIPT_ACTORS + 1)),
        lambda _: ValueError("WF route traversal failed"),
    )
    if len(entries) > MAX_SCRIPT_ACTORS:
        raise ValueError("WF route mapping exceeds the actor ceiling")
    return {validate_wf_name(character): validate_wf_name(actor_id) for character, actor_id in entries}


def normalize_ingress(
    action: Callable[[], ValueT],
    error_factory: Callable[[Exception], ErrorT],
) -> ValueT:
    """Translate ordinary caller traversal failures without chaining raw input."""
    failure: ErrorT | None = None
    try:
        return action()
    except Exception as error:
        logger.warning("normalized caller traversal failure")
        failure = error_factory(error)
    raise failure from None
