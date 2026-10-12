"""Generate the public API contract without starting a server or reading secrets."""

import json
from pathlib import Path

from freight.api.app import app

path = Path(__file__).resolve().parents[2] / "apps" / "web" / "openapi.json"
path.write_text(json.dumps(app.openapi(), indent=2), encoding="utf-8")
print(f"Wrote {path.name}")
