"""Ordered, additive verifier composition for rescue extensions."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from ..models import VerificationCheck
from ..verifier import CHECK_IDS

VerifierCallable = Callable[[Any], VerificationCheck]


def _unbound_mandatory(_: Any) -> VerificationCheck:
    raise RuntimeError("mandatory rescue checks run through verify_package")


@dataclass(frozen=True, slots=True)
class VerifierDefinition:
    id: str
    run: VerifierCallable
    gating: bool = True


class VerifierRegistry:
    def __init__(self, definitions: Iterable[VerifierDefinition] = ()) -> None:
        indexed: dict[str, VerifierDefinition] = {}
        for definition in definitions:
            if definition.id in CHECK_IDS:
                raise ValueError(f"feature cannot override mandatory rescue verifier: {definition.id}")
            if definition.id in indexed:
                raise ValueError(f"duplicate feature verifier: {definition.id}")
            indexed[definition.id] = definition
        self._definitions = indexed

    def resolve_with_mandatory(self, feature_ids: tuple[str, ...]) -> tuple[VerifierDefinition, ...]:
        mandatory = tuple(
            VerifierDefinition(id=check_id, run=_unbound_mandatory, gating=True) for check_id in CHECK_IDS
        )
        try:
            feature = tuple(self._definitions[check_id] for check_id in feature_ids)
        except KeyError as exc:
            raise KeyError(f"unknown feature verifier: {exc.args[0]}") from exc
        return (*mandatory, *feature)
