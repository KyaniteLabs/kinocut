"""Project-level AI-video facades over the shipped engines and project store.

This package composes the already-shipped, hardened primitives (the
content-addressed project store, contracts, probes) into task-level facades. It
adds **no parallel store** — every durable byte and record still lives in the
one private ``.kinocut/`` project store.

Public surface (Plan 01 Wave 2):

* :func:`ingest_project_asset` — content-addressed ingest of an immutable
  original with strict generation lineage and a rights posture.
"""

from __future__ import annotations

from kinocut.aivideo.ingest import ingest_project_asset

__all__ = ["ingest_project_asset"]
