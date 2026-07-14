"""Explicit, read-only reader migrations for the project store (Plan 00 Task 4).

Canonical records are append-only and written strictly at the *current* schema
version. Readers, however, may encounter documented older records. This module
holds a bounded, explicit ``(record_kind, from_version) -> migrator`` registry
that steps such a record forward — one version at a time — until it matches the
current model, which then validates it strictly.

Migrations run *only on read* and never mutate their input. The registry is
empty today (schema version 1 is the first version); future versions add one
entry each. Anything the registry cannot resolve — an older version with no
registered migrator, or a migrator that fails to advance the version — fails
closed with a stable :class:`~kinocut.errors.MCPVideoError`.
"""

from __future__ import annotations

import copy
import logging
from collections.abc import Callable
from typing import Any

from kinocut.contracts._errors import INVALID_RECORD, contract_error
from kinocut.errors import MCPVideoError

_LOGGER = logging.getLogger(__name__)

#: The schema version every record is written at today.
CURRENT_SCHEMA_VERSION = 1

#: Explicit reader migrations. Each maps ``(record_kind, from_version)`` to a
#: pure function returning the next-version raw dict. Empty until a v2 lands.
MIGRATIONS: dict[tuple[str, int], Callable[[dict[str, Any]], dict[str, Any]]] = {}


def migrate_raw(record_kind: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Return ``raw`` migrated up to the current schema version (read-only).

    The caller's dict is never mutated. A record already at (or above) the
    current version is returned as a copy for the strict model to accept or
    reject. An older version is stepped forward through the explicit registry;
    a missing migrator, or a migrator that does not advance the version, fails
    closed with ``invalid_record``.
    """

    current = copy.deepcopy(raw)  # deep copy: nested structures never leak back
    version = current.get("schema_version")
    if not isinstance(version, int) or isinstance(version, bool):
        return current  # malformed version — let the strict model reject it

    while version < CURRENT_SCHEMA_VERSION:
        migrator = MIGRATIONS.get((record_kind, version))
        if migrator is None:
            raise contract_error(
                f"no reader migration for {record_kind!r} schema_version {version}",
                INVALID_RECORD,
            )
        current = _apply_migrator(migrator, current, record_kind, version)
        next_version = current.get("schema_version")
        if not isinstance(next_version, int) or isinstance(next_version, bool) or next_version <= version:
            raise contract_error("reader migration did not advance schema_version", INVALID_RECORD)
        version = next_version
    return current


def _apply_migrator(
    migrator: Callable[[dict[str, Any]], dict[str, Any]],
    current: dict[str, Any],
    record_kind: str,
    version: int,
) -> dict[str, Any]:
    """Run one migrator on a deep copy, isolating and validating its result.

    The migrator receives a deep copy (a nested mutation cannot reach the caller)
    and its result is deep-copied too. A non-dict result, or any non-contract
    exception, is mapped to a privacy-safe ``invalid_record`` error; an existing
    :class:`MCPVideoError` propagates unchanged.
    """

    try:
        result = migrator(copy.deepcopy(current))
    except MCPVideoError:
        raise
    except Exception as exc:  # any migrator fault maps to a stable, privacy-safe error
        # Log the record kind, version, and exception *type* only — never the raw
        # exception text, which could carry a host path or record data.
        _LOGGER.warning(
            "reader migration failed for record_kind=%s schema_version=%s: %s",
            record_kind,
            version,
            type(exc).__name__,
        )
        raise contract_error(
            f"reader migration for {record_kind!r} schema_version {version} failed", INVALID_RECORD
        ) from exc
    if not isinstance(result, dict):
        raise contract_error("reader migration must return a JSON object", INVALID_RECORD)
    return copy.deepcopy(result)
