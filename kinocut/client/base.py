"""mcp-video Python client — clean API for programmatic video editing."""

from __future__ import annotations

import inspect
import re
from functools import wraps
from typing import Any, Self

from ..errors import MCPVideoError
from ..engine import (
    probe as _probe,
)
from ..models import (
    EditResult,
    VideoInfo,
)
from .contracts import CLIENT_METHOD_CONTRACTS, MEDIA_RETURN

DESTRUCTIVE_POLISH_OPS = {"effect_glow", "effect_noise", "effect_vignette", "effect_scanlines"}
QUALITY_GATE_OPS = {"assert_quality", "release_checkpoint", "quality_check"}


class ClientBase:
    """Base client with core lifecycle methods."""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        for name in CLIENT_METHOD_CONTRACTS:
            method = getattr(cls, name, None)
            if callable(method) and not getattr(method, "_mcp_video_guarded", False):
                setattr(cls, name, _guard_client_method(name, method))

    def _normalize_kwargs_for_method(self, method_name: str, method: Any, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Map primary/legacy aliases to the concrete method signature."""
        if not kwargs:
            return kwargs
        params = inspect.signature(method).parameters
        normalized = dict(kwargs)
        aliases = CLIENT_METHOD_CONTRACTS.get(method_name, {}).get("aliases", {})
        for legacy, primary in aliases.items():
            if primary in normalized and primary not in params and legacy in params:
                if legacy in normalized:
                    raise MCPVideoError(
                        f"Use '{primary}=' or '{legacy}=', not both",
                        error_type="validation_error",
                        code="ambiguous_parameter",
                    )
                normalized[legacy] = normalized.pop(primary)
            elif legacy in normalized and legacy not in params and primary in params:
                if primary in normalized:
                    raise MCPVideoError(
                        f"Use '{primary}=' or '{legacy}=', not both",
                        error_type="validation_error",
                        code="ambiguous_parameter",
                    )
                normalized[primary] = normalized.pop(legacy)
        return normalized

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: Any) -> None:
        pass

    def info(self, input_path: str) -> VideoInfo:
        """Get metadata about a video file."""
        return _probe(input_path)

    def _to_edit_result(self, result: Any, operation: str | None = None) -> EditResult:
        """Normalize media-producing client returns to EditResult."""
        if isinstance(result, EditResult):
            if operation and result.operation is None:
                result.operation = operation
            return result
        if isinstance(result, str):
            return EditResult(output_path=result, operation=operation)
        output_path = getattr(result, "output_path", None)
        if output_path:
            return EditResult(output_path=str(output_path), operation=operation)
        if isinstance(result, dict) and result.get("output_path"):
            return EditResult(output_path=str(result["output_path"]), operation=operation)
        raise MCPVideoError(
            f"Expected media operation to return output_path, got {type(result).__name__}",
            error_type="contract_error",
            code="missing_output_path",
        )

    def _raise_helpful_type_error(self, method_name: str, exc: TypeError) -> None:
        message = str(exc)
        match = re.search(r"unexpected keyword argument '([^']+)'", message)
        if match:
            bad = match.group(1)
            contract = CLIENT_METHOD_CONTRACTS.get(method_name, {})
            aliases = contract.get("aliases", {})
            preferred = aliases.get(bad)
            if preferred:
                hint = f"Use '{preferred}=' not '{bad}=' — see Client.{method_name}() signature."
            else:
                signature = self.inspect(method_name)
                hint = (
                    f"Client.{method_name}() does not take '{bad}'. "
                    f"Valid parameters: {', '.join(signature['parameters'])}."
                )
            raise MCPVideoError(hint, error_type="validation_error", code="unexpected_parameter") from exc
        raise exc

    @staticmethod
    def _resolve_alias(primary: str, primary_value: Any, legacy: str, legacy_value: Any) -> Any:
        """Resolve primary/legacy parameter aliases."""
        if primary_value is not None and legacy_value is not None:
            raise MCPVideoError(
                f"Use '{primary}=' or '{legacy}=', not both",
                error_type="validation_error",
                code="ambiguous_parameter",
            )
        return primary_value if primary_value is not None else legacy_value

    def inspect(self, method_name: str) -> dict[str, Any]:
        """Return method signature metadata for agents before calling."""
        method = getattr(self, method_name, None)
        if method is None or not callable(method):
            raise MCPVideoError(f"Unknown client method: {method_name}", error_type="validation_error")
        signature = inspect.signature(method)
        return_type = signature.return_annotation
        contract = CLIENT_METHOD_CONTRACTS.get(method_name, {})
        return {
            "name": method_name,
            "category": contract.get("category", "unknown"),
            "parameters": {
                name: str(param.annotation) if param.annotation is not inspect._empty else "Any"
                for name, param in signature.parameters.items()
                if name != "self" and param.kind is not inspect.Parameter.VAR_KEYWORD
            },
            "aliases": contract.get("aliases", {}),
            "return_type": contract.get("return_type")
            or getattr(return_type, "__name__", str(return_type).replace("'", "")),
        }

    def pipeline(
        self,
        steps: list[dict[str, Any]],
        output_path: str | None = None,
        output: str | None = None,
        cleanup: bool = False,
    ) -> EditResult:
        """Run a simple chained media pipeline with EditResult normalization.

        Args:
            cleanup: Remove intermediate files after the pipeline completes.
                Only the final output and the original input are kept.
        """
        self._validate_pipeline_steps(steps)
        final_output = self._resolve_alias("output_path", output_path, "output", output)
        result, warnings, saw_quality_gate, intermediates = self._run_pipeline_steps(steps, final_output)
        if cleanup and intermediates:
            warnings.extend(self._cleanup_pipeline_intermediates(intermediates))
            result.intermediates = intermediates
        return self._finalize_pipeline_result(result, warnings, saw_quality_gate)

    @staticmethod
    def _validate_pipeline_steps(steps: list[dict[str, Any]]) -> None:
        if not steps:
            raise MCPVideoError("pipeline steps cannot be empty", error_type="validation_error", code="empty_pipeline")

    @staticmethod
    def _finalize_pipeline_result(result: EditResult, warnings: list[str], saw_quality_gate: bool) -> EditResult:
        if not saw_quality_gate:
            warnings.append(
                "Pipeline did not include a release checkpoint; run "
                "assert_quality/release_checkpoint before publishing."
            )
        result.warnings = list(dict.fromkeys(warnings))
        return result

    def _run_pipeline_steps(
        self, steps: list[dict[str, Any]], final_output: str | None
    ) -> tuple[EditResult, list[str], bool, list[str]]:
        """Execute pipeline steps and collect guardrail state."""
        current: str | None = None
        result: EditResult | None = None
        warnings: list[str] = []
        intermediates: list[str] = []
        previous_op: str | None = None
        saw_quality_gate = False
        for index, step in enumerate(steps):
            op, params = self._prepare_pipeline_step(step, current, final_output, index == len(steps) - 1)
            if op in QUALITY_GATE_OPS:
                saw_quality_gate = True
            step_result = self._execute_pipeline_media_step(op, params, previous_op, warnings)
            if step_result is not None:
                if result is not None and result.output_path != final_output:
                    intermediates.append(result.output_path)
                result = step_result
                current = result.output_path
            previous_op = op
        if result is None:
            raise MCPVideoError(
                "pipeline produced no media output", error_type="validation_error", code="no_media_output"
            )
        return result, warnings, saw_quality_gate, intermediates

    @staticmethod
    def _cleanup_pipeline_intermediates(intermediates: list[str]) -> list[str]:
        """Delete intermediate media files and return non-fatal cleanup warnings."""
        import os

        warnings: list[str] = []
        for path in intermediates:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError as exc:
                warnings.append(f"Could not remove pipeline intermediate {path!r}: {exc}")
        return warnings

    def _prepare_pipeline_step(
        self, step: dict[str, Any], current: str | None, final_output: str | None, is_last: bool
    ) -> tuple[str, dict[str, Any]]:
        op = step.get("op")
        if not op:
            raise MCPVideoError("pipeline step missing 'op'", error_type="validation_error", code="missing_op")
        params = {k: v for k, v in step.items() if k != "op"}
        if current and not any(k in params for k in ("input_path", "video", "background", "main")):
            params["input_path"] = current
        if final_output and is_last and not any(k in params for k in ("output_path", "output")):
            params["output_path"] = final_output
        return op, params

    def _execute_pipeline_media_step(
        self, op: str, params: dict[str, Any], previous_op: str | None, warnings: list[str]
    ) -> EditResult | None:
        raw_result = getattr(self, op)(**params)
        if op in QUALITY_GATE_OPS:
            return None
        if op in DESTRUCTIVE_POLISH_OPS and previous_op in DESTRUCTIVE_POLISH_OPS:
            warnings.append("Stacked visual polish effects detected; inspect thumbnail/storyboard before publishing.")
        result = self._to_edit_result(raw_result, operation=op)
        warnings.extend(result.warnings)
        return result

    @staticmethod
    def _validate_choice(name: str, value: str, valid_values: set[str]) -> None:
        if value not in valid_values:
            raise MCPVideoError(
                f"{name} must be one of {sorted(valid_values)}, got {value}",
                error_type="validation_error",
                code="invalid_parameter",
            )


def _guard_client_method(method_name: str, method: Any) -> Any:
    """Wrap public client methods once at class creation time."""

    @wraps(method)
    def guarded_call(self: ClientBase, *args: Any, **kwargs: Any) -> Any:
        try:
            result = method(self, *args, **self._normalize_kwargs_for_method(method_name, method, kwargs))
        except TypeError as exc:
            self._raise_helpful_type_error(method_name, exc)
        if CLIENT_METHOD_CONTRACTS[method_name]["return_type"] == MEDIA_RETURN:
            return self._to_edit_result(result, operation=method_name)
        return result

    guarded_call._mcp_video_guarded = True
    return guarded_call
