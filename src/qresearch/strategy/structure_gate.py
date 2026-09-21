"""Structure Gate v13 production engine loader.

The real engine lives in structure_gate.v13.part{0-3}.b64 (preferred)
or structure_gate.v13.gz.b64. This file only assembles that payload.
"""
from __future__ import annotations

import base64
import gzip
from pathlib import Path

_DIR = Path(__file__).resolve().parent


def _payload() -> str:
    parts: list[str] = []
    for i in range(4):
        path = _DIR / f"structure_gate.v13.part{i}.b64"
        if path.is_file():
            parts.append("".join(path.read_text().split()))
    if len(parts) == 4 and all(parts):
        return "".join(parts)
    sidecar = _DIR / "structure_gate.v13.gz.b64"
    if sidecar.is_file():
        text = "".join(sidecar.read_text().split())
        if text and "PLACEHOLDER" not in text:
            return text
    raise ImportError(
        "v13 engine payload missing. Need structure_gate.v13.part0-3.b64 "
        "or a complete structure_gate.v13.gz.b64. "
        "Restore from branch cursor/structure-gate-v13-600b."
    )


exec(
    compile(gzip.decompress(base64.b64decode(_payload())), __file__, "exec"),
    globals(),
)
