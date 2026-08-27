"""Shared helpers imported by the demo pipelines.

Lives in ``common/`` next to the pipeline files. The folder that holds those
files is on ``sys.path``, so ``from common.greetings import ...`` resolves
from any of them. If this import ever breaks, every importer shows up in the
processor's import-error list -- which is the point: the pipelines exercise
this shared module on every parse, so a broken shared import fails loudly
instead of silently.

No framework imports here and the words that trigger safe-mode parsing are
avoided, so the processor does not try to treat this file as a pipeline
definition; it is only ever imported.
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
