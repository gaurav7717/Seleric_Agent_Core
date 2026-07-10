#!/usr/bin/env bash
# Reconcile Cube MCP KPIs against gold.fct_daily_pnl (dbt source of truth in ClickHouse).
# Usage: ./scripts/reconcile_cube_gold_dbt.sh 2026-05-21 [brand_id]
#
# Requires: semantic_layer_serve/.env with CUBEJS_API_SECRET and ClickHouse creds.
# Optional: CUBE_URL=http://127.0.0.1:4000/cubejs-api/v1 (skip docker exec)

set -euo pipefail
DATE="${1:-$(TZ=Asia/Kolkata date -d '2 days ago' +%Y-%m-%d 2>/dev/null || TZ=Asia/Kolkata date +%Y-%m-%d)}"
BRAND_ID="${2:-}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${ROOT}/.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing ${ENV_FILE}" >&2
  exit 1
fi

# shellcheck disable=SC1090
set -a
source <(grep -E '^(CUBEJS_API_SECRET|CUBEJS_DB_HOST|CUBEJS_DB_PORT|CUBEJS_DB_USER|CUBEJS_DB_PASS)=' "$ENV_FILE" | sed 's/^/export /')
set +a

BRAND_SQL=""
if [[ -n "$BRAND_ID" ]]; then
  BRAND_SQL="AND brand_id = '${BRAND_ID}'"
fi

cube_load() {
  local payload="$1"
  if [[ -n "${CUBE_URL:-}" ]]; then
    local token
    token=$(python3 -c "import jwt, time; print(jwt.encode({}, '${CUBEJS_API_SECRET}', algorithm='HS256', headers={'exp': int(time.time())+3600}))" 2>/dev/null || true)
    curl -s "${CUBE_URL}/load" \
      -H "Authorization: ${token:-${CUBEJS_API_SECRET}}" \
      -H "Content-Type: application/json" \
      -d "{\"query\":${payload},\"timezone\":\"Asia/Kolkata\"}"
    return
  fi
  (cd "${ROOT}/.." && docker compose exec -T \
    -e CUBEJS_API_SECRET="${CUBEJS_API_SECRET}" mcp-serve node -e "
const jwt = require('jsonwebtoken');
const payload = ${payload};
const token = jwt.sign({}, process.env.CUBEJS_API_SECRET, { expiresIn: '1h' });
fetch('http://cube-serve:4000/cubejs-api/v1/load', {
  method: 'POST',
  headers: { Authorization: token, 'Content-Type': 'application/json' },
  body: JSON.stringify({ query: payload, timezone: 'Asia/Kolkata' })
}).then((r) => r.text()).then((t) => process.stdout.write(t));
")
}

ch_query() {
  local sql="$1"
  curl -s "http://${CUBEJS_DB_HOST}:${CUBEJS_DB_PORT}/" \
    --user "${CUBEJS_DB_USER}:${CUBEJS_DB_PASS}" \
    --data-binary "${sql} FORMAT JSONEachRow"
}

echo "=== Reconcile canonical P&L: Cube vs gold.fct_daily_pnl (${DATE}) brand=${BRAND_ID:-all} ==="

CANONICAL_MEASURES=(
  gross_revenue
  gross_sales_excl_tax
  net_revenue_excl_tax
  product_cost
  total_ad_spend
  meta_spend
  google_spend
  gross_profit
  contribution_margin
  net_profit
  total_orders
  active_orders
  cancelled_orders
  mer
)

MEASURE_JSON=$(printf '"canonical_pnl.%s",' "${CANONICAL_MEASURES[@]}" | sed 's/,$//')
BRAND_FILTER=""
if [[ -n "$BRAND_ID" ]]; then
  BRAND_FILTER=", \"filters\": [{\"member\": \"canonical_pnl.brand_id\", \"operator\": \"equals\", \"values\": [\"${BRAND_ID}\"]}]"
fi

CUBE_RESP_FILE=$(mktemp)
trap 'rm -f "$CUBE_RESP_FILE"' EXIT
cube_load "$(cat <<EOF
{
  "measures": [${MEASURE_JSON}],
  "timeDimensions": [{
    "dimension": "canonical_pnl.report_date",
    "dateRange": ["${DATE}", "${DATE}"]
  }]${BRAND_FILTER}
}
EOF
)" >"$CUBE_RESP_FILE"

python3 - "$CUBE_RESP_FILE" "$DATE" "$BRAND_ID" <<'PY'
import json, sys, urllib.request, os, base64

with open(sys.argv[1], encoding="utf-8") as f:
    cube_raw = json.load(f)
date = sys.argv[2]
brand_id = sys.argv[3]

if cube_raw.get("error"):
    print("Cube error:", cube_raw["error"][:800], file=sys.stderr)
    sys.exit(1)

cube_row = (cube_raw.get("data") or [{}])[0]

host = os.environ["CUBEJS_DB_HOST"]
port = os.environ["CUBEJS_DB_PORT"]
user = os.environ["CUBEJS_DB_USER"]
passwd = os.environ["CUBEJS_DB_PASS"]
brand_sql = f"AND brand_id = '{brand_id}'" if brand_id else ""

sql = f"""
SELECT
  sum(gross_revenue) AS gross_revenue,
  sum(gross_sales_excl_tax) AS gross_sales_excl_tax,
  sum(net_revenue_excl_tax) AS net_revenue_excl_tax,
  sum(product_cost) AS product_cost,
  sum(total_ad_spend) AS total_ad_spend,
  sum(meta_spend) AS meta_spend,
  sum(google_spend) AS google_spend,
  sum(gross_profit) AS gross_profit,
  sum(contribution_margin) AS contribution_margin,
  sum(net_profit) AS net_profit,
  sum(total_orders) AS total_orders,
  sum(active_orders) AS active_orders,
  sum(cancelled_orders) AS cancelled_orders
FROM gold.fct_daily_pnl
WHERE report_date = toDate('{date}')
{brand_sql}
FORMAT JSONEachRow
""".strip()

auth = base64.b64encode(f"{user}:{passwd}".encode()).decode()
req = urllib.request.Request(
    f"http://{host}:{port}/",
    data=sql.encode(),
    headers={"Authorization": f"Basic {auth}"},
)
with urllib.request.urlopen(req, timeout=120) as resp:
    ch_line = resp.read().decode().strip().splitlines()[-1]
ch_row = json.loads(ch_line) if ch_line else {}

metrics = [
    "gross_revenue", "gross_sales_excl_tax", "net_revenue_excl_tax", "product_cost",
    "total_ad_spend", "meta_spend", "google_spend", "gross_profit", "contribution_margin",
    "net_profit", "total_orders", "active_orders", "cancelled_orders", "mer",
]

print(f"{'metric':<28} {'cube':>16} {'gold_ch':>16} {'delta':>12} {'ok':>4}")
print("-" * 80)
fail = 0
for m in metrics:
    ck = f"canonical_pnl.{m}"
    if m == "mer":
        cv = float(cube_row.get("canonical_pnl.mer") or 0)
        gv = float(ch_row.get("net_revenue_excl_tax") or 0) / (float(ch_row.get("total_ad_spend") or 0) or float("nan"))
        if gv != gv:
            gv = 0.0
    else:
        cv = float(cube_row.get(ck) or 0)
        gv = float(ch_row.get(m) or 0)
    delta = cv - gv
    tol = max(1.0, abs(gv) * 0.001)
    ok = abs(delta) <= tol
    if not ok:
        fail += 1
    print(f"{m:<28} {cv:>16.2f} {gv:>16.2f} {delta:>12.2f} {'yes' if ok else 'NO':>4}")

sys.exit(1 if fail else 0)
PY

echo ""
echo "=== Reconcile commerce orders: Cube vs gold.fct_orders (${DATE}) ==="
COMMERCE_RESP=$(mktemp)
trap 'rm -f "$CUBE_RESP_FILE" "$COMMERCE_RESP"' EXIT
COMMERCE_BRAND_FILTER=""
if [[ -n "$BRAND_ID" ]]; then
  COMMERCE_BRAND_FILTER=", \"filters\": [{\"member\": \"commerce_orders.brand_id\", \"operator\": \"equals\", \"values\": [\"${BRAND_ID}\"]}]"
fi
cube_load "$(cat <<EOF
{
  "measures": ["commerce_orders.orders", "commerce_orders.net_revenue"],
  "timeDimensions": [{
    "dimension": "commerce_orders.order_date",
    "dateRange": ["${DATE}", "${DATE}"]
  }]${COMMERCE_BRAND_FILTER}
}
EOF
)" >"$COMMERCE_RESP"
python3 - "$COMMERCE_RESP" "$DATE" "$BRAND_ID" <<'PY2'
import json, sys, urllib.request, os, base64
cube_raw = json.load(open(sys.argv[1]))
date, brand_id = sys.argv[2], sys.argv[3]
row = (cube_raw.get("data") or [{}])[0]
brand_sql = f"AND brand_id = '{brand_id}'" if brand_id else ""
sql = f"SELECT count(*) AS orders, sum(net_revenue) AS net_revenue FROM gold.fct_orders WHERE is_test = 0 AND order_date = toDate('{date}') {brand_sql} FORMAT JSONEachRow"
auth = base64.b64encode(f"{os.environ['CUBEJS_DB_USER']}:{os.environ['CUBEJS_DB_PASS']}".encode()).decode()
req = urllib.request.Request(f"http://{os.environ['CUBEJS_DB_HOST']}:{os.environ['CUBEJS_DB_PORT']}/", data=sql.encode(), headers={"Authorization": f"Basic {auth}"})
ch = json.loads(urllib.request.urlopen(req, timeout=120).read().decode().strip().splitlines()[-1])
co = float(row.get("commerce_orders.orders") or 0)
cr = float(row.get("commerce_orders.net_revenue") or 0)
ho, hn = float(ch.get("orders") or 0), float(ch.get("net_revenue") or 0)
print(f"orders cube={co:.0f} gold={ho:.0f} delta={co-ho:.0f}")
print(f"net_revenue cube={cr:.2f} gold={hn:.2f} delta={cr-hn:.2f}")
PY2

echo ""
echo "=== Catalog freshness ==="
CATALOG="${ROOT}/catalog/gold_semantic_catalog.json"
if [[ -f "$CATALOG" ]]; then
  ENTITIES=$(python3 -c "import json; print(json.load(open('$CATALOG'))['entity_count'])")
  echo "gold_semantic_catalog.json: ${ENTITIES} entities"
else
  echo "WARN: missing ${CATALOG} — run scripts/generate_semantic_catalog.py"
fi

echo ""
echo "=== No serve.* DB references ==="
python3 "${ROOT}/scripts/validate_no_serve_db.py"
