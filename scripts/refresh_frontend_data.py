#!/usr/bin/env python3
"""Copy the newest entities export into the frontend's data directory.

The static frontend fetches ``frontend/data/entities.json``; this picks the
most recent ``output/berlin_techno_entities_*.json`` and writes it there so
the deployed site reflects the latest run. No third-party dependencies.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"
TARGET = ROOT / "frontend" / "data" / "entities.json"


def newest_export() -> Path | None:
    candidates = sorted(OUTPUT_DIR.glob("berlin_techno_entities_*.json"))
    return candidates[-1] if candidates else None


def main() -> int:
    source = newest_export()
    if source is None:
        print("No entities export found in output/.", file=sys.stderr)
        return 1
    # Validate it is parseable JSON before copying.
    try:
        json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Cannot read {source}: {exc}", file=sys.stderr)
        return 1
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, TARGET)
    print(f"Copied {source.name} -> {TARGET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
