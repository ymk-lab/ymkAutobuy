#!/usr/bin/env python3
"""Export Structure Gate v13 resolved params + print verify-prompt path.

Usage::

    PYTHONPATH=src python examples/export_structure_gate_v13_prompt_bundle.py
"""

from __future__ import annotations

import json
import sys
from dataclasses import fields
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from qresearch.strategy.structure_gate import (  # noqa: E402
    StructureGateConfig,
    V13_BOOK_WEIGHTS,
)

OUT_DIR = ROOT / "examples" / "prompts"
PARAMS_JSON = OUT_DIR / "structure_gate_v13_params.json"
PROMPT_MD = OUT_DIR / "structure_gate_v13_verify_prompt.md"


def main() -> int:
    cfg = StructureGateConfig.v13()
    base = StructureGateConfig()
    resolved = {f.name: getattr(cfg, f.name) for f in fields(cfg) if f.name != "ers_config"}
    overrides = {
        k: resolved[k]
        for k in resolved
        if getattr(base, k) != resolved[k]
    }
    payload = {
        "preset": "StructureGateConfig.v13",
        "book_weights": dict(V13_BOOK_WEIGHTS),
        "dual_trail": {
            "short_leadership_trail_days": cfg.leadership_trail_days,
            "long_sticky_trail_days": cfg.sticky_trail_days,
            "note": (
                "sticky_require_above50 uses SMA50 price filter; "
                "it is not the long trail window"
            ),
        },
        "v13_overrides_vs_v8_defaults": overrides,
        "resolved": resolved,
        "source": "src/qresearch/strategy/structure_gate.py",
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    PARAMS_JSON.write_text(json.dumps(payload, indent=2, default=str) + "\n")
    print(f"wrote {PARAMS_JSON}")
    print(f"verify prompt: {PROMPT_MD}")
    print("Paste the fenced block inside the markdown file to another AI.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
