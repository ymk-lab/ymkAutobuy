#!/usr/bin/env python3
"""Audit Structure Gate v11 paper fills line-by-line.

Reads examples/data/structure_gate_v11_paper (or QRESEARCH_SG_PAPER_OUT):
  latest_signal.json / latest_run.json / account_live.json / fills_ledger.jsonl

Prints preview vs fill vs position reconcile and writes latest_fill_audit.json.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from qresearch.paper.fill_audit import audit_from_out_dir, write_audit  # noqa: E402


def main() -> int:
    base = Path(os.getenv("QRESEARCH_SG_PAPER_OUT", str(ROOT / "examples/data/structure_gate_v11_paper")))
    if not base.is_dir():
        print(f"out dir missing: {base}", file=sys.stderr)
        return 2

    audit = audit_from_out_dir(base)
    path = write_audit(base, audit)

    print(f"out={base}")
    print(f"status={audit.get('status')} ok={audit.get('ok')} asof={audit.get('asof')}")
    print(f"preview={audit.get('n_preview')} fills={audit.get('n_fills')} issues={audit.get('n_issues')}")
    print(f"sources={json.dumps(audit.get('sources') or {}, ensure_ascii=False)}")
    print("--- lines ---")
    for line in audit.get("lines") or []:
        print(
            f"[{line.get('status'):12}] {line.get('side'):4} "
            f"{line.get('symbol'):8} "
            f"preview_qty={line.get('preview_qty')} fill_qty={line.get('fill_qty')} "
            f"px_prev={line.get('preview_price')} px_fill={line.get('fill_price')} "
            f"bps={line.get('price_bps')}"
        )
    if audit.get("positions"):
        print("--- positions ---")
        for p in audit["positions"]:
            print(
                f"{p.get('symbol'):8} before={p.get('before')} "
                f"expected={p.get('expected_after')} after={p.get('after')} ok={p.get('ok')}"
            )
    if audit.get("issues"):
        print("--- issues ---")
        for issue in audit["issues"]:
            print(f"!! {issue}")
    print(f"wrote {path}")
    return 0 if audit.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
