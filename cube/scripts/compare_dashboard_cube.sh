#!/usr/bin/env bash
# Compare serve mart KPIs via Cube semantic layer for a single day.
# Usage: ./scripts/compare_dashboard_cube.sh 2026-05-21 [brand_id]

set -euo pipefail
DATE="${1:-$(TZ=Asia/Kolkata date +%Y-%m-%d)}"
BRAND_ID="${2:-}"
ENV_FILE="$(dirname "$0")/../.env"
SECRET=$(grep CUBEJS_API_SECRET "$ENV_FILE" | cut -d= -f2)
CUBE_URL="${CUBE_URL:-}"

BRAND_FILTER=""
if [[ -n "$BRAND_ID" ]]; then
  BRAND_FILTER=", \"filters\": [{\"member\": \"daily_pnl.brand_id\", \"operator\": \"equals\", \"values\": [\"${BRAND_ID}\"]}]"
fi

cube_load() {
  local payload="$1"
  if [[ -n "$CUBE_URL" ]]; then
    curl -s "${CUBE_URL}/load" \
      -H "Authorization: ${SECRET}" \
      -H "Content-Type: application/json" \
      -d "{\"query\":${payload},\"timezone\":\"Asia/Kolkata\"}" \
      | python3 -c "import sys,json; d=json.load(sys.stdin);
import sys
if d.get('error'): print('ERROR:', d['error'][:500], file=sys.stderr); sys.exit(1)
print(json.dumps(d.get('data',[{}])[0], indent=2))"
    return
  fi
  (cd "$(dirname "$0")/../.." && docker compose exec -T \
    -e CUBEJS_API_SECRET="${SECRET}" mcp-serve node -e "
const jwt = require('jsonwebtoken');
const payload = ${payload};
const token = jwt.sign({}, process.env.CUBEJS_API_SECRET, { expiresIn: '1h' });
fetch('http://cube-serve:4000/cubejs-api/v1/load', {
  method: 'POST',
  headers: { Authorization: token, 'Content-Type': 'application/json' },
  body: JSON.stringify({ query: payload, timezone: 'Asia/Kolkata' })
}).then((r) => r.text()).then((t) => process.stdout.write(t));
") \
    | python3 -c "import sys,json; d=json.load(sys.stdin);
import sys
if d.get('error'): print('ERROR:', d['error'][:500], file=sys.stderr); sys.exit(1)
print(json.dumps(d.get('data',[{}])[0], indent=2))"
}

echo "=== Cube gold daily_pnl (${DATE}) brand_id=${BRAND_ID:-all} ==="
cube_load "$(cat <<EOF
{
  "measures": [
    "daily_pnl.gross_sales",
    "daily_pnl.total_sales_ex_gst",
    "daily_pnl.total_cogs",
    "daily_pnl.gross_profit",
    "daily_pnl.total_ad_spend",
    "daily_pnl.net_profit",
    "daily_pnl.total_orders"
  ],
  "timeDimensions": [{
    "dimension": "daily_pnl.report_date",
    "dateRange": ["${DATE}", "${DATE}"]
  }]${BRAND_FILTER}
}
EOF
)"

echo ""
echo "=== Cube channel_pnl by platform (${DATE}) ==="
cube_load "$(cat <<EOF
{
  "measures": [
    "channel_pnl.meta_attributed_revenue",
    "channel_pnl.google_attributed_revenue",
    "channel_pnl.organic_attributed_revenue",
    "channel_pnl.meta_spend",
    "channel_pnl.google_spend",
    "channel_pnl.meta_channel_net_profit",
    "channel_pnl.google_channel_net_profit",
    "channel_pnl.meta_attributed_orders",
    "channel_pnl.google_attributed_orders"
  ],
  "dimensions": ["channel_pnl.platform"],
  "timeDimensions": [{
    "dimension": "channel_pnl.report_date",
    "dateRange": ["${DATE}", "${DATE}"]
  }]${BRAND_FILTER}
}
EOF
)"
