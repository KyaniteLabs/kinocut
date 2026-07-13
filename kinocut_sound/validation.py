"""Closed validation constants and regex patterns for ``kinocut_sound``.

Single source of truth for every regex pattern and closed validation set used
across the sidecar's contract modules. Centralising them here prevents
divergent copies and makes the validation surface auditable in one place.

Nothing in this module imports from ``kinocut`` runtime or from other
``kinocut_sound`` contract modules, so it is safe to import from any layer.
"""

from __future__ import annotations

import re

# --- Canonical typed-id patterns (strings for Pydantic Field pattern=) ---

SHA256_PATTERN: str = r"^sha256:[0-9a-f]{64}$"

CREATED_BY_PATTERN: str = r"^(human|agent|tool)(:[a-z0-9][a-z0-9_.-]{0,63})?$"

RECORD_KIND_PATTERN: str = r"^[a-z][a-z0-9_]{0,63}$"

# Bounded code regex: letter start, then alnum/underscore/dot/colon/hyphen,
# up to 64 chars. No spaces, slashes, or control characters.
CODE_RE: re.Pattern[str] = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,63}$")

# Scheme detection regex: catches leading ``scheme:`` (http, file, data, ...).
SCHEME_RE: re.Pattern[str] = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")

# --- Domain validation regexes (compiled) ---

# Advisory human text: bounded, no control chars, host paths, URLs, or shell
# metacharacters — spaces and ordinary punctuation are fine. Used by consent
# (intended_use_summary) and capability (remediation).
ADVISORY_RE: re.Pattern[str] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ,.\-_'()]{0,199}$")

# ISO-8601 UTC timestamp: YYYY-MM-DDTHH:MM:SSZ.
ISO8601_RE: re.Pattern[str] = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

# Locale identifier (UN/LIBC-style, e.g. ``en_US``, ``es_ES.UTF-8``).
LOCALE_RE: re.Pattern[str] = re.compile(r"^[A-Za-z][A-Za-z0-9_.@+=-]{0,63}$")

# Cloud region identifier: bounded alphanumeric code, 1-32 chars.
REGION_RE: re.Pattern[str] = re.compile(r"^[A-Za-z0-9_.-]{1,32}$")

# Territory code: short UN M49 / ISO 3166-style, 2-16 alphanumeric chars.
TERRITORY_RE: re.Pattern[str] = re.compile(r"^[A-Za-z0-9]{2,16}$")

# --- Closed validation sets ---

# Closed set of adapter kinds. A requested kind outside this set is a contract
# error, never a dynamic load.
ADAPTER_KINDS: frozenset[str] = frozenset({"tts", "processor", "spatializer", "asset", "analyzer"})

# Closed set of determinism classes. A stage declares exactly one.
DETERMINISM_CLASSES: frozenset[str] = frozenset(
    {"byte_deterministic", "signal_equivalent", "non_reproducible"}
)

# --- Canonical record policy ---

# Fields excluded from the canonical record id by default: informational only.
# This set may never contain a semantic field; excluding one would let two
# logically distinct records collide on the same id.
INFORMATIONAL_FIELDS: frozenset[str] = frozenset({"created_at"})
