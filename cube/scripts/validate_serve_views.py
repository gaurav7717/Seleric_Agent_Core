#!/usr/bin/env python3
"""Smoke-query each serve view with one measure + one time dimension."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SERVE_VIEWS = ROOT / "model" / "views" / "serve_views.yml"
ENV = ROOT / ".env"

TIME_DIMS = {
    "report_date",
    "order_date",
    "transaction_date",
    "session_date",
    "changed_at",
    "first_order_at",
    "last_order_at",
    "date_start",
}


def load_secret() -> str:
    for line in ENV.read_text().splitlines():
        if line.startswith("CUBEJS_API_SECRET="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("CUBEJS_API_SECRET not found")


def cube_load(query: dict, secret: str) -> dict:
    payload = json.dumps({"query": query})
    node_script = f"""
const jwt = require('jsonwebtoken');
const token = jwt.sign({{}}, {json.dumps(secret)}, {{ expiresIn: '1h' }});
fetch('http://cube-serve:4000/cubejs-api/v1/load', {{
  method: 'POST',
  headers: {{ Authorization: token, 'Content-Type': 'application/json' }},
  body: JSON.stringify({payload})
}}).then(r => r.text()).then(t => {{ console.log(t); process.exit(0); }}).catch(e => {{ console.error(e); process.exit(1); }});
"""
    raw = subprocess.check_output(
        ["docker", "exec", "mcp-serve-mcp-serve-1", "node", "-e", node_script],
        text=True,
    )
    return json.loads(raw)


def pick_members(view: dict) -> tuple[str | None, str | None]:
    prefix = view["name"]
    includes = view["cubes"][0].get("includes") or []
    names: list[str] = []
    for item in includes:
        if isinstance(item, str):
            names.append(item)
        elif isinstance(item, dict):
            names.append(item.get("name") or item.get("alias") or "")
    measure = next((n for n in names if n not in TIME_DIMS and n != "brand_id"), None)
    time_dim = next((n for n in names if n in TIME_DIMS), None)
    if measure:
        return f"{prefix}.{measure}", f"{prefix}.{time_dim}" if time_dim else None
    return None, None


def main() -> int:
    secret = load_secret()
    doc = yaml.safe_load(SERVE_VIEWS.read_text()) or {}
    views = doc.get("views") or []
    failed = 0
    print(f"Smoke-testing {len(views)} serve views...\n")
    for view in views:
        name = view["name"]
        measure, time_dim = pick_members(view)
        if not measure:
            print(f"  SKIP {name}: no measure found")
            continue
        query: dict = {
            "measures": [measure],
            "limit": 1,
            "timezone": "Asia/Kolkata",
        }
        if time_dim:
            query["timeDimensions"] = [{"dimension": time_dim, "dateRange": "last 7 days"}]
        try:
            data = cube_load(query, secret)
            if data.get("error"):
                print(f"  FAIL {name}: {data['error']}")
                failed += 1
            else:
                rows = len(data.get("data") or [])
                print(f"  OK   {name} ({rows} row(s))")
        except Exception as exc:
            print(f"  FAIL {name}: {exc}")
            failed += 1

    print(f"\nResults: {len(views) - failed}/{len(views)} serve views OK")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
