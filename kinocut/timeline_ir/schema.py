"""Closed, frozen Timeline IR contracts."""

from __future__ import annotations

import re
from fractions import Fraction
from typing import Any, Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from kinocut.contracts._common import ValueObject
from kinocut.errors import MCPVideoError
from kinocut.render_dag import DAG_NODE_KINDS

IR_SCHEMA_VERSION: Literal[1] = 1
IR_KINDS = ("clip", "resize", "crop", "text", "subtitles", "merge", "composite")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def ir_error(message: str, code: str = "invalid_timeline_ir") -> MCPVideoError:
    return MCPVideoError(error_type="validation_error", code=code, message=message)


class RationalTime(ValueObject):
    """Exact non-negative timeline time in declared timebase units."""

    numerator: int = Field(ge=0)
    denominator: int = Field(gt=0)

    @model_validator(mode="after")
    def _canonical(self) -> RationalTime:
        reduced = Fraction(self.numerator, self.denominator)
        if reduced.numerator != self.numerator or reduced.denominator != self.denominator:
            raise ir_error("rational times must be reduced")
        return self

    def seconds(self, timebase: RationalTime) -> float:
        return float(Fraction(self.numerator, self.denominator) * Fraction(timebase.numerator, timebase.denominator))


class IRSource(ValueObject):
    path: str

    @field_validator("path")
    @classmethod
    def _safe_path(cls, value: str) -> str:
        if not value or "\\" in value or "\x00" in value or value.startswith("/"):
            raise ir_error("timeline source path must be confined")
        if any(part in {"", ".", ".."} for part in value.split("/")):
            raise ir_error("timeline source path must not traverse")
        return value


class IROutput(IRSource):
    pass


class IRNode(ValueObject):
    id: str
    kind: Literal["clip", "resize", "crop", "text", "subtitles", "merge", "composite"]
    depends_on: tuple[str, ...] = ()
    inputs: dict[str, Any]
    params: dict[str, Any] = Field(default_factory=dict)
    output: str | None = None

    @field_validator("id")
    @classmethod
    def _valid_id(cls, value: str) -> str:
        if _ID_RE.fullmatch(value) is None:
            raise ir_error("invalid timeline node id")
        return value

    @model_validator(mode="after")
    def _semantics(self) -> IRNode:
        allowed = {
            "clip": {"start", "duration"},
            "resize": {"width", "height"},
            "crop": {"x", "y", "width", "height", "crop_percent"},
            "text": {"text", "position", "size", "color", "start_time", "end_time"},
            "subtitles": {"style"},
            "merge": set(),
            "composite": {"canvas"},
        }[self.kind]
        unknown = set(self.params) - allowed
        if unknown:
            raise ir_error(f"unsupported {self.kind} semantics: {sorted(unknown)}")
        expected_key = {
            "clip": "src",
            "resize": "src",
            "crop": "src",
            "text": "src",
            "subtitles": "srcs",
            "merge": "srcs",
            "composite": "layers",
        }[self.kind]
        if set(self.inputs) != {expected_key}:
            raise ir_error(f"{self.kind} inputs must contain only {expected_key!r}")
        value = self.inputs[expected_key]
        if expected_key == "src" and (not isinstance(value, str) or not value):
            raise ir_error(f"{self.kind} input must be a ref string")
        if expected_key == "srcs" and (
            not isinstance(value, list) or not value or not all(isinstance(ref, str) and ref for ref in value)
        ):
            raise ir_error(f"{self.kind} inputs must be a non-empty ref list")
        if expected_key == "layers" and (not isinstance(value, list) or not value):
            raise ir_error("composite layers must be a non-empty list")
        if self.kind == "clip":
            for name in ("start", "duration"):
                if name in self.params:
                    RationalTime.model_validate(self.params[name])
        return self


class TimelineIR(ValueObject):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    ir_schema_version: Literal[1] = IR_SCHEMA_VERSION
    name: str | None = Field(default=None, max_length=255)
    timebase: RationalTime = Field(
        default=RationalTime(numerator=1, denominator=1),
        description="Exact seconds per timeline tick (the reciprocal of frame rate).",
    )
    sources: dict[str, IRSource]
    nodes: tuple[IRNode, ...]
    outputs: dict[str, IROutput] = Field(default_factory=dict)

    @field_validator("ir_schema_version", mode="before")
    @classmethod
    def _strict_version(cls, value: Any) -> Any:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ir_error("ir_schema_version must be integer 1")
        return value

    @model_validator(mode="after")
    def _graph(self) -> TimelineIR:
        if not self.nodes:
            raise ir_error("TimelineIR requires at least one node")
        ids = [node.id for node in self.nodes]
        if len(ids) != len(set(ids)):
            raise ir_error("duplicate timeline node id")
        known = set(ids)
        for node in self.nodes:
            if any(dep not in known for dep in node.depends_on):
                raise ir_error(f"node {node.id!r} has an unknown dependency")
        return self


DAG_KIND_BY_IR_KIND = {
    "clip": "trim",
    "resize": "resize",
    "crop": "crop",
    "text": "add_text",
    "subtitles": "burn_in",
    "merge": "merge",
    "composite": "composite_layers",
}
if set(DAG_KIND_BY_IR_KIND) != set(IR_KINDS):
    raise RuntimeError("Timeline IR kind declarations drifted")
if not set(DAG_KIND_BY_IR_KIND.values()) <= set(DAG_NODE_KINDS):
    raise RuntimeError("Timeline IR kinds drifted from Render DAG allowlist")
