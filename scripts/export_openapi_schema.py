"""Export FastAPI OpenAPI schema to a deterministic JSON file."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from agent_vis.api.app import app


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: uv run python scripts/export_openapi_schema.py <output_path>")
        return 1

    output_path = Path(sys.argv[1]).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    schema = app.openapi()
    output_path.write_text(
        json.dumps(schema, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote OpenAPI schema to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
