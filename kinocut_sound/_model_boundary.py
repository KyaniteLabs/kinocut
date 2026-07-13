"""Private dump-and-revalidate helpers for public model boundaries."""

from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel

from kinocut_sound.limits import MAX_SCRIPT_ACTORS

ModelT = TypeVar("ModelT", bound=BaseModel)


def dump_revalidate_model(value: object, model_type: type[ModelT]) -> ModelT:
    """Revalidate a model through plain dumped data, including nested values."""
    payload = value.model_dump(mode="python")
    return model_type.model_validate(payload)


def dump_revalidate_tuple(
    values: object,
    model_type: type[ModelT],
) -> tuple[ModelT, ...]:
    """Require a tuple and revalidate every model through dumped data."""
    if not isinstance(values, tuple):
        raise TypeError("model collection must be a tuple")
    return tuple(dump_revalidate_model(value, model_type) for value in values)


def dump_revalidate_index(
    values: object,
    model_type: type[ModelT],
    key: str,
) -> dict[str, ModelT]:
    """Return a unique keyed index of dump-revalidated models."""
    models = dump_revalidate_tuple(values, model_type)
    if len(models) > MAX_SCRIPT_ACTORS:
        raise ValueError("model index exceeds the actor ceiling")
    keys = tuple(getattr(model, key) for model in models)
    if len(keys) != len(set(keys)):
        raise ValueError("model index keys must be unique")
    return dict(zip(keys, models, strict=True))
