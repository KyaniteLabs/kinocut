"""Write consent, ownership evidence, and anchored artifact publication."""

from functools import partial

from ._files import anchored_output as anchored_output
from ._operation import (
    _note_operation_write as note_operation_write,
    _owns_operation_output as owns_operation_output,
    _record_operation_input as record_operation_input,
    _reset_operation_inputs as reset_operation_inputs,
    output_operation as output_operation,
    read_only as read_only,
    with_output_policy as with_output_policy,
)
from ._policy import (
    _validate_artifact_location as validate_artifact_location,
    _validate_artifact_path as validate_artifact_path,
    _validate_output_path as validate_output_path,
)
from ._receipts import durable_receipt_ownership as durable_receipt_ownership
from ._staging import open_staged_writer as open_staged_writer
from ._trees import anchored_tree as anchored_tree

__all__ = [
    "anchored_output",
    "anchored_tree",
    "atomic_artifact",
    "atomic_output",
    "durable_receipt_ownership",
    "note_operation_write",
    "open_staged_writer",
    "output_operation",
    "owns_operation_output",
    "read_only",
    "record_operation_input",
    "reset_operation_inputs",
    "validate_artifact_location",
    "validate_artifact_path",
    "validate_output_path",
    "with_output_policy",
]


def atomic_output(path: str):
    """Stage a media file and publish it under the current write policy."""
    return anchored_output(path, validate_output_path)


def atomic_artifact(path: str, *, allow_recorded: bool = False):
    """Stage a structured artifact; replacing it requires ownership evidence."""
    return anchored_output(path, partial(validate_artifact_path, allow_recorded=allow_recorded))
