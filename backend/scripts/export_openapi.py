"""Write the API's OpenAPI schema to backend/openapi.json, the contract the frontend client is
generated from. Run from backend/: `uv run python scripts/export_openapi.py`."""

import json
from pathlib import Path

from hubnisio.main import app

OUTPUT = Path(__file__).parents[1] / "openapi.json"

OUTPUT.write_text(json.dumps(app.openapi(), indent=2) + "\n", encoding="utf-8", newline="\n")
print(f"Wrote {OUTPUT}")
