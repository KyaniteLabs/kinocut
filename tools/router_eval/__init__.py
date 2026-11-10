"""Router evaluation harness for kinocut operation routing.

The harness scores a model arm against a frozen, private request set. The set
itself is never committed to this repository: real user requests are user
content. See README.md for the contract and the reproduce commands.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "1.0.0"
