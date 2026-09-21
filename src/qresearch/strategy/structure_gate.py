"""Structure Gate v13 production engine.

Splits the gzip payload across structure_gate.v13.part{0-3}.b64 so the
engine can be pushed through the GitHub file API.
"""
from __future__ import annotations

import base64
import gzip
from pathlib import Path

_DIR = Path(__file__).resolve().parent
_parts = []
for _i in range(4):
    _p = _DIR / f"structure_gate.v13.part{_i}.b64"
    if not _p.is_file():
        raise ImportError(
            f"missing {_p.name}; restore structure_gate.py from commit "
            "83a247aa8b00175145a5845933fffa65c60e9ec8 if v13 payload is absent"
        )
    _parts.append(_p.read_text().strip())
exec(
    compile(gzip.decompress(base64.b64decode("".join(_parts))), __file__, "exec"),
    globals(),
)
