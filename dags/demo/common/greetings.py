"""Shared helpers for the ``demo`` project's pipelines.

Each project folder here is its own Python package (an ``__init__.py`` plus a
``common/`` subpackage) and the projects are fully independent -- they never
import one another's helpers, so ``demo`` owns this copy outright. The parent
of the project folders is on ``sys.path`` and this project's package is
``demo``, so ``from demo.common.greetings import ...`` resolves from any
pipeline in the project. If this import ever breaks, every importer shows up
in the processor's import-error list -- which is the point: the pipelines
exercise this shared module on every parse, so a broken shared import fails
loudly instead of silently.

No framework imports here and the tokens that trigger safe-mode parsing are
avoided, so the processor never treats this file as a pipeline definition; it
is only ever imported.
"""

from __future__ import annotations

import socket


def where(label: str) -> str:
    """Print and return ``"<label> on host=<hostname>"``."""
    message = f"{label} on host={socket.gethostname()}"
    print(message)
    return message


def fail(reason: str = "designed to fail") -> None:
    """Raise ``RuntimeError(reason)`` unconditionally."""
    raise RuntimeError(reason)
