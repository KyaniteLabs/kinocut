"""Op allowlist + engine binding for the agent workflow engine.

Two distinct things are kept explicit and separate here:

1. A tiny input/output BINDING map (which ``inputs``/``output`` key wires to
   which engine positional arg). This is a small wiring table, not a
   re-implementation of param semantics.
2. Tunable params DERIVED from each engine's real signature via introspection
   (``inspect.signature``). There is no hand-maintained parallel param schema,
   so an adapter can never advertise a param the engine does not accept — a
   drift-guard test asserts ``accepted_params ⊆ engine signature`` per op.
"""

from __future__ import annotations

import functools
import inspect
import types
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Union, get_args, get_origin, get_type_hints

from ..engine import add_text, convert, merge, probe, resize, trim
from ..engine_composite_layers import composite_layers
from ._errors import INVALID_WORKFLOW_PARAMS, workflow_error


@dataclass(frozen=True)
class OpAdapter:
    """Binds an allowlisted workflow op to an existing vetted engine function."""

    name: str
    engine_fn: Callable[..., Any]
    input_key: str  # inputs key the spec must use: "src" (single) or "srcs" (list)
    engine_input_param: str  # engine positional param that receives the resolved input
    multi_input: bool = False  # True => srcs is a list of refs (e.g. merge -> clips)
    has_output: bool = True  # False => inspection op with no output file (e.g. probe)
    excluded_params: frozenset[str] = field(default_factory=frozenset)  # spec-unsafe params withheld this release

    def accepted_params(self) -> frozenset[str]:
        """Tunable params for this op, derived from the engine signature.

        Everything the engine accepts EXCEPT the input-bound param, the output
        path, variadics, non-JSON callable params (e.g. ``on_progress``), and any
        param explicitly withheld via ``excluded_params`` (e.g. path-typed
        ``font``, an existence oracle — see C2).
        """
        excluded = {self.engine_input_param, "output_path"} | set(self.excluded_params)
        accepted: set[str] = set()
        for pname, param in inspect.signature(self.engine_fn).parameters.items():
            if pname in excluded:
                continue
            if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
                continue
            if "Callable" in _annotation_text(param.annotation):
                continue
            accepted.add(pname)
        return frozenset(accepted)

    def validate_param_values(self, params: dict[str, Any], step_id: str) -> None:
        """Fail closed when a param VALUE does not match the engine's type.

        Names are checked elsewhere (``accepted_params``); this rejects a value
        whose JSON type cannot satisfy the engine parameter's annotation (e.g.
        ``width="20000"`` for ``int``, ``size="24,drawtext=…"`` for ``int``,
        ``start=[1,2]`` for ``str | float``). Non-scalar annotations (dict
        positions, unresolved aliases) are passed through to the engine, which
        owns their semantic validation.
        """
        hints = _engine_type_hints(self.engine_fn)
        for name, value in params.items():
            hint = hints.get(name)
            if hint is None:
                continue
            kinds = _scalar_kinds(hint)
            if kinds is None:  # non-scalar annotation => engine validates the value
                continue
            if not _value_matches(value, kinds):
                expected = " | ".join(sorted(kinds))
                raise workflow_error(
                    f"step {step_id!r} ({self.name}) param {name!r} must be {expected}, "
                    f"got {type(value).__name__}",
                    INVALID_WORKFLOW_PARAMS,
                )


class CompositeOpAdapter(OpAdapter):
    """Bespoke adapter for the multi-layer ``composite_layers`` op.

    Unlike the simple ops, composite consumes a NESTED layer spec (not a single
    ``src``/``srcs`` → engine-arg binding), so the generic signature-derived param
    handling does not apply: the only tunable param is ``canvas``, which the workflow
    layer writes into a SYNTHESIZED spec (see ``workflow/composite.py``), never passing
    it to the engine signature. Input handling (per-layer @ref confinement + hashing)
    and execution (spec synthesis) live in ``workflow/composite.py``; the validator and
    executor branch on ``isinstance(adapter, CompositeOpAdapter)``.
    """

    def accepted_params(self) -> frozenset[str]:
        return frozenset({"canvas"})

    def validate_param_values(self, params: dict[str, Any], step_id: str) -> None:
        canvas = params.get("canvas")
        if canvas is not None and not isinstance(canvas, dict):
            raise workflow_error(
                f"step {step_id!r} (composite_layers) param 'canvas' must be an object",
                INVALID_WORKFLOW_PARAMS,
            )


def _annotation_text(annotation: Any) -> str:
    if annotation is inspect.Parameter.empty:
        return ""
    if isinstance(annotation, str):
        return annotation
    return getattr(annotation, "__name__", str(annotation))


@functools.cache
def _engine_type_hints(engine_fn: Callable[..., Any]) -> dict[str, Any]:
    """Resolved (non-string) type hints for an engine fn; empty on failure.

    On failure the value checks are skipped for that op; the engine still guards
    its own inputs, so this degrades safely rather than erroring.
    """
    try:
        return get_type_hints(engine_fn)
    except Exception:
        return {}


def _scalar_kinds(hint: Any) -> set[str] | None:
    """Accepted scalar kinds for a hint, or None when it is not a scalar.

    Unwraps ``Optional``/unions and ``Literal`` down to the JSON scalar kinds
    (``int``/``float``/``str``/``bool``/``none``). Any non-scalar member (dict,
    unknown class) makes the whole annotation opaque (``None`` => pass through).
    """
    if hint is int:
        return {"int"}
    if hint is float:
        return {"float"}
    if hint is str:
        return {"str"}
    if hint is bool:
        return {"bool"}
    if hint is type(None):
        return {"none"}
    origin = get_origin(hint)
    if origin is Literal:
        kinds: set[str] = set()
        for value in get_args(hint):
            if isinstance(value, bool):
                kinds.add("bool")
            elif isinstance(value, int):
                kinds.add("int")
            elif isinstance(value, float):
                kinds.add("float")
            elif isinstance(value, str):
                kinds.add("str")
            elif value is None:
                kinds.add("none")
            else:
                return None
        return kinds
    if origin is Union or origin is getattr(types, "UnionType", ()):
        combined: set[str] = set()
        for arg in get_args(hint):
            sub = _scalar_kinds(arg)
            if sub is None:
                return None
            combined |= sub
        return combined
    return None


def _value_matches(value: Any, kinds: set[str]) -> bool:
    """True when a JSON value satisfies at least one accepted scalar kind.

    ``bool`` is checked before ``int`` (bool subclasses int in Python); an int
    is accepted for a ``float`` annotation, but not vice versa.
    """
    if isinstance(value, bool):
        return "bool" in kinds
    if isinstance(value, int):
        return "int" in kinds or "float" in kinds
    if isinstance(value, float):
        return "float" in kinds
    if isinstance(value, str):
        return "str" in kinds
    if value is None:
        return "none" in kinds
    return False


# The EXACT MVP allowlist. Anything else fails closed (unsupported_workflow_op).
OP_ADAPTERS: dict[str, OpAdapter] = {
    "probe": OpAdapter("probe", probe, input_key="src", engine_input_param="path", has_output=False),
    "trim": OpAdapter("trim", trim, input_key="src", engine_input_param="input_path"),
    "resize": OpAdapter("resize", resize, input_key="src", engine_input_param="input_path"),
    "convert": OpAdapter("convert", convert, input_key="src", engine_input_param="input_path"),
    "add_text": OpAdapter(
        "add_text",
        add_text,
        input_key="src",
        engine_input_param="input_path",
        # `font` is a spec-controlled arbitrary path (an existence oracle); not tunable via workflow this release.
        excluded_params=frozenset({"font"}),
    ),
    "merge": OpAdapter("merge", merge, input_key="srcs", engine_input_param="clips", multi_input=True),
    # composite rides the existing video_workflow_* surfaces (no new tool/CLI). Its layer
    # sources are workflow @refs synthesized into a workspace-confined spec — see composite.py.
    "composite_layers": CompositeOpAdapter(
        "composite_layers",
        composite_layers,
        input_key="layers",
        engine_input_param="spec_path",
        has_output=True,
    ),
}
