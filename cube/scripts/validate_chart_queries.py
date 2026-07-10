#!/usr/bin/env python3
"""Validate all 29 chart queries from CHART_QUERY_REFERENCE.md against Cube serve."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REF = ROOT / "CHART_QUERY_REFERENCE.md"
ENV = ROOT / ".env"


def load_secret() -> str:
    for line in ENV.read_text().splitlines():
        if line.startswith("CUBEJS_API_SECRET="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("CUBEJS_API_SECRET not found in .env")


def parse_chart_queries() -> list[tuple[str, str, dict]]:
    text = REF.read_text()
    pattern = re.compile(
        r"### (#\d+ — [^\n]+)\n\n(?:.*?\n)*?```json\n(.*?)\n```",
        re.DOTALL,
    )
    out: list[tuple[str, str, dict]] = []
    for m in pattern.finditer(text):
        title = m.group(1).strip()
        chart_id = title.split(" ", 1)[0]
        query = json.loads(m.group(2))
        cube = "unknown"
        for measure in query.get("measures") or []:
            cube = measure.split(".", 1)[0]
            break
        out.append((chart_id, title, query))
    return out


def cube_load(query: dict, secret: str) -> dict:
    token = subprocess.check_output(
        [
            sys.executable,
            "-c",
            "import jwt,sys; print(jwt.encode({}, sys.argv[1], algorithm='HS256'))",
            secret,
        ],
        text=True,
    ).strip()
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


def validate_formula_01(data: dict) -> str | None:
    rows = data.get("data") or []
    if not rows:
        return "no rows returned"
    row = rows[0]
    keys = {
        "sales": "daily_pnl.total_sales_ex_gst",
        "cogs": "daily_pnl.total_cogs",
        "ads": "daily_pnl.total_ad_spend",
        "net": "daily_pnl.net_profit",
        "gross": "daily_pnl.gross_profit",
    }
    try:
        sales = float(row.get(keys["sales"]) or 0)
        cogs = float(row.get(keys["cogs"]) or 0)
        ads = float(row.get(keys["ads"]) or 0)
        net = float(row.get(keys["net"]) or 0)
        gross = float(row.get(keys["gross"]) or 0)
    except (TypeError, ValueError) as e:
        return f"parse error: {e}"
    if abs(gross - (sales - cogs)) > 0.02:
        return f"gross_profit mismatch: {gross} vs {sales - cogs}"
    # Gold net_profit = gross_profit − ad_spend − operating_costs (should be <= gross − ads)
    if net > gross - ads + 0.02:
        return f"net_profit exceeds gross − ads (unexpected): net={net}, gross−ads={gross - ads}"
    return None


def main() -> int:
    secret = load_secret()
    charts = parse_chart_queries()
    if len(charts) != 29:
        print(f"WARN: expected 29 charts, parsed {len(charts)}")

    passed = 0
    failed: list[tuple[str, str, str]] = []
    warnings: list[str] = []

    print(f"Validating {len(charts)} chart queries against Cube serve...\n")
    print(f"{'Chart':<6} {'Status':<8} {'Rows':<6} Detail")
    print("-" * 72)

    for chart_id, title, query in charts:
        try:
            resp = cube_load(query, secret)
            if resp.get("error"):
                err = resp["error"]
                if isinstance(err, dict):
                    msg = err.get("message") or json.dumps(err)[:200]
                else:
                    msg = str(err)[:200]
                failed.append((chart_id, title, msg))
                print(f"{chart_id:<6} FAIL     -      {msg[:60]}")
                continue

            rows = resp.get("data") or []
            row_count = len(rows)

            if chart_id == "#01" and row_count > 0:
                formula_err = validate_formula_01(resp)
                if formula_err:
                    warnings.append(f"{chart_id} formula: {formula_err}")

            if chart_id == "#10" and row_count > 0:
                formula_err = validate_formula_01(resp)
                if formula_err:
                    warnings.append(f"{chart_id} waterfall formula: {formula_err}")

            if row_count == 0:
                warnings.append(f"{chart_id} returned 0 rows (schema OK, may be empty date range)")

            passed += 1
            sample = ""
            if rows:
                first = rows[0]
                non_null = {k: v for k, v in first.items() if v is not None and v != ""}
                sample = json.dumps(non_null)[:80]
            print(f"{chart_id:<6} OK       {row_count:<6} {sample}")

        except subprocess.CalledProcessError as e:
            msg = (e.stderr or e.stdout or str(e))[:200]
            failed.append((chart_id, title, msg))
            print(f"{chart_id:<6} ERROR    -      {msg[:60]}")
        except Exception as e:
            failed.append((chart_id, title, str(e)))
            print(f"{chart_id:<6} ERROR    -      {str(e)[:60]}")

    print("-" * 72)
    print(f"\nResults: {passed}/{len(charts)} queries succeeded")

    if warnings:
        print(f"\nWarnings ({len(warnings)}):")
        for w in warnings:
            print(f"  - {w}")

    if failed:
        print(f"\nFailures ({len(failed)}):")
        for cid, title, msg in failed:
            print(f"  {cid} {title}")
            print(f"    {msg}\n")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
