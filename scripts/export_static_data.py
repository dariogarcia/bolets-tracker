"""Export the curated zone dataset to static/data/zones.json.

The client-side engine (static/engine.js) used by the GitHub Pages build
loads the same 844-sector dataset the FastAPI backend serves from
app/zones.py. Run this after any change to the dataset:

    uv run python scripts/export_static_data.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.zones import ZONES

STATIC_DATA = Path(__file__).resolve().parent.parent / "static" / "data"


def main() -> None:
    STATIC_DATA.mkdir(parents=True, exist_ok=True)
    out = STATIC_DATA / "zones.json"
    payload = [z.model_dump() for z in ZONES]
    out.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"wrote {len(payload)} zones to {out} ({out.stat().st_size / 1024:.0f} KiB)")


if __name__ == "__main__":
    main()
