"""Private bounded-consumption helpers for sound public boundaries."""

from __future__ import annotations

from collections.abc import Mapping
from itertools import islice
from typing import TypeVar

from pydantic import BaseModel

from kinocut_sound._model_boundary import dump_revalidate_model
from kinocut_sound.limits import MAX_SCRIPT_ACTORS, MAX_SCRIPT_NAME_LENGTH_CHARS

ModelT = TypeVar("ModelT", bound=BaseModel)


def bounded_model_iterable(
    values: object,
    model_type: type[ModelT],
    maximum: int,
) -> tuple[ModelT, ...]:
    """Consume at most max+1 values before model traversal and revalidation."""
    iterator = iter(values)
    collected = tuple(islice(iterator, maximum + 1))
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


def validate_wf_routes(value: object) -> dict[str, str]:
    """Bound route count before validating and copying route entries."""
    if not isinstance(value, Mapping):
        raise TypeError("WF routes must be a mapping")
    if len(value) > MAX_SCRIPT_ACTORS:
        raise ValueError("WF route mapping exceeds the actor ceiling")
    return {validate_wf_name(character): validate_wf_name(actor_id) for character, actor_id in value.items()}
