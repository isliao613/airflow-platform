"""Shared helpers for the ``project2`` project's pipelines.

Each project folder here is its own Python package with its OWN ``common/``
subpackage -- the projects are fully independent and never import one
another's helpers, so ``project2`` owns this copy outright and may change it
without touching ``demo`` or ``project1``. The parent of the project folders
is on ``sys.path`` and this project's package is ``project2``, so
``from project2.common.greetings import ...`` resolves from any pipeline in
the project.

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
