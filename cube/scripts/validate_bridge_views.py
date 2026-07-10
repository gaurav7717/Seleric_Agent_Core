#!/usr/bin/env python3
"""Smoke-test SQL bridge MCP views with canonical probe measures."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".env"

# view -> primary probe measure(s); all must succeed for LIVE
BRIDGE_PROBES: dict[str, list[str]] = {
    "campaign_product_performance": [
        "campaign_product_performance.attributed_orders",
        "campaign_product_performance.spend",
        "campaign_product_performance.attributed_revenue",
    ],
    "customer_acquisition_ltv": ["customer_acquisition_ltv.customers"],
    "neurohack_attribution": [
        "neurohack_attribution.spend",
        "neurohack_attribution.attributed_net_revenue_ex_gst",
    ],
    "daily_performance": ["daily_performance.net_profit"],
    "refund_events": ["refund_events.refund_amount"],
    "payment_method_pnl": ["payment_method_pnl.net_profit"],
    "hourly_commerce": ["hourly_commerce.orders"],
    "meta_neurotag_analysis": [
        "meta_neurotag_analysis.spend_fc",
        "meta_neurotag_analysis.spend_sc",
        "meta_neurotag_analysis.net_revenue_fc",
        "meta_neurotag_analysis.attributed_orders_fc",
        "meta_neurotag_analysis.video_views_3s_sc",
        "meta_neurotag_analysis.hook_rate",
        "meta_neurotag_analysis.hold_rate_p50",
    ],
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


def main() -> int:
    secret = load_secret()
    failed = 0
    live = 0
    print(f"{'View':<32} {'Status':<10} Detail")
    print("-" * 72)
    for view, measures in BRIDGE_PROBES.items():
        errors: list[str] = []
        for measure in measures:
            query: dict = {
                "measures": [measure],
                "limit": 1,
                "timezone": "Asia/Kolkata",
            }
            try:
                data = cube_load(query, secret)
                if data.get("error"):
                    errors.append(f"{measure.split('.')[-1]}: {data['error']}")
            except Exception as exc:
                errors.append(str(exc))
        if errors:
            failed += 1
            print(f"{view:<32} NOT LIVE   {errors[0][:36]}")
        else:
            live += 1
            print(f"{view:<32} LIVE")
    print("-" * 72)
    print(f"Results: {live}/{len(BRIDGE_PROBES)} bridge views LIVE")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
