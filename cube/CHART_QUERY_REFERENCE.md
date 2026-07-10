# Seleric Query Reference — All 29 Charts

> **Stack:** ClickHouse `gold.*` only · MCP `seleric-cube-serve` · port **3012**  
> **Catalog:** `cube_schema_catalog` · **Timezone:** `Asia/Kolkata` on every query  
> **Returns:** RETURNED + IN_PROGRESS only (where return metrics apply)

All queries use `cube_query` format. Views are defined in `model/views/chart_views.yml` — every view maps to dbt gold tables synced from Iceberg. No `serve.*` or Postgres proxies.

**MCP tools:** `cube_pnl_waterfall` · `cube_daily_pnl` · `cube_pnl_today_yesterday` · `cube_channel_pnl` · `cube_meta_ads` · `cube_commerce_orders` · `cube_product_performance` · `cube_line_economics` · `cube_schema_catalog` · `cube_query`

---

## Net profit — canonical P&L waterfall (gold.fct_daily_pnl)

**MCP:** `cube_pnl_waterfall` · `cube_daily_pnl` · `cube_pnl_today_yesterday`

| Step | Measure | Formula |
|------|---------|---------|
| 1. Revenue (ex-GST) | `daily_pnl.total_sales_ex_gst` | `net_revenue_excl_tax` |
| 2. − COGS | `daily_pnl.total_cogs` | `product_cost` |
| 3. = Gross profit | `daily_pnl.gross_profit` | step 1 − step 2 |
| 4. − Ad spend | `daily_pnl.total_ad_spend` | `meta_spend + google_spend` |
| 5. = Contribution | `daily_pnl.contribution_margin` | gross_profit − ad spend |
| 6. − Ops costs | packaging + shipping + gateway + RTO | see measures below |
| 7. = **Net profit** | `daily_pnl.net_profit` | contribution − ops costs |

Ops cost measures: `daily_pnl.packaging_cost`, `shipping_cost`, `payment_gateway_fees`, `rto_cost`  
Alias: `daily_pnl.simplified_net_profit` = `contribution_margin` (before ops costs)

Never compute net_profit as `shopify_orders.gross_revenue − dw_meta_ads_attribution.ad_spend`. Always use `daily_pnl.net_profit`.

---

## Full gold column access

Every ClickHouse `gold.*` column is synced into cubes and exposed via `gold__{table}` views (e.g. `gold__fct_orders`, `gold__fct_daily_pnl`). Use `cube_schema_catalog` to list all members, then `cube_query`.

```bash
python3 scripts/sync_gold_cube_columns.py   # sync CH → cube YAML
python3 scripts/generate_semantic_catalog.py
```

---

## Cube quick reference

| Cube | Gold source | Primary use |
|------|-------------|-------------|
| `daily_pnl` | `int_finance_daily_rollups` + line-item split + ad spend | Company P&L — canonical `net_profit` (rebuilt; `total_cogs` = net_cogs) |
| `channel_pnl` | `gold_channel_pnl` (attribution + COGS + spend) | Meta / Google / Organic breakdown |
| `marketing_performance` | `gold.fct_meta_ads_daily` | Meta ROAS, CPC, CTR, funnel |
| `ad_performance` | `gold.fct_meta_ads_hourly` | Hour-of-day spend (`hourly_window`) |
| `dw_meta_ads_attribution` | `gold_meta_campaign_attribution` | Campaign-level attribution |
| `shopify_orders` | `gold.fct_orders` | Orders, AOV, geo, UTM |
| `shopify_order_line_items` | `gold.fct_order_items` | Discounts, basket size |
| `product_performance` | `gold.fct_order_items` | SKU revenue, margin, returns |
| `neurohack_catalog` | `gold.dim_neurohack` | Creative taxonomy tags (550 tags) |
| `ad_neurohack_map` | `gold.dim_ad_neurohack_map` × catalog | Ad → tag mappings |
| `meta_neurohack_performance` | Meta ads × tag map (deprecated SQL bridge) | Spend/ROAS by Neurohack tag |
| `meta_neurotag_analysis` | `gold.mart_meta_ad_neurotag_daily` | Tag analysis with full-credit + split-credit + attribution |

For full P&L waterfall use `daily_pnl` view / `cube_pnl_waterfall`. For every raw column use `gold__fct_daily_pnl` via `cube_query`.

---

## Main dashboard — executive overview

### #01 — P&L KPI strip

**Chart type:** Metric cards · Today vs yesterday  
**Cube:** `daily_pnl`  
**Formula:** `net_profit = total_sales_ex_gst − total_cogs − total_ad_spend` · `gross_margin_pct = gross_profit / total_sales_ex_gst`

Use `cube_pnl_today_yesterday` for today/yesterday comparison — handles IST timezone automatically.

```json
{
  "measures": [
    "daily_pnl.net_profit",
    "daily_pnl.gross_profit",
    "daily_pnl.total_sales_ex_gst",
    "daily_pnl.total_cogs",
    "daily_pnl.total_ad_spend",
    "daily_pnl.total_orders",
    "daily_pnl.gross_margin_pct"
  ],
  "timeDimensions": [{
    "dimension": "daily_pnl.report_date",
    "dateRange": "today"
  }],
  "timezone": "Asia/Kolkata"
}
```

### #02 — Net profit over time

**Chart type:** Line chart · 30d / 90d daily trend  
**Cube:** `daily_pnl`

```json
{
  "measures": [
    "daily_pnl.net_profit",
    "daily_pnl.gross_profit"
  ],
  "timeDimensions": [{
    "dimension": "daily_pnl.report_date",
    "granularity": "day",
    "dateRange": "last 30 days"
  }],
  "order": { "daily_pnl.report_date": "asc" },
  "timezone": "Asia/Kolkata"
}
```

### #03 — Revenue vs ad spend vs COGS

**Chart type:** Grouped bar chart · Daily  
**Cube:** `daily_pnl`  
**Formula:** `gross_profit = total_sales_ex_gst − total_cogs` · `net_profit = gross_profit − total_ad_spend`

```json
{
  "measures": [
    "daily_pnl.total_sales_ex_gst",
    "daily_pnl.total_cogs",
    "daily_pnl.total_ad_spend",
    "daily_pnl.net_profit"
  ],
  "timeDimensions": [{
    "dimension": "daily_pnl.report_date",
    "granularity": "day",
    "dateRange": "last 30 days"
  }],
  "order": { "daily_pnl.report_date": "asc" },
  "timezone": "Asia/Kolkata"
}
```

### #04 — Revenue by channel

**Chart type:** Donut chart · Meta / Google / Organic  
**Cube:** `channel_pnl`  
**Formula:** `attributed_revenue_ex_gst = Meta + Google + Organic revenue ex-GST`

```json
{
  "measures": [
    "channel_pnl.meta_attributed_revenue_ex_gst",
    "channel_pnl.google_attributed_revenue_ex_gst",
    "channel_pnl.organic_attributed_revenue_ex_gst",
    "channel_pnl.meta_attributed_orders",
    "channel_pnl.google_attributed_orders",
    "channel_pnl.organic_attributed_orders"
  ],
  "timeDimensions": [{
    "dimension": "channel_pnl.date_start",
    "dateRange": "last 30 days"
  }],
  "timezone": "Asia/Kolkata"
}
```

### #05 — Net profit by channel (daily)

**Chart type:** Stacked bar · Meta / Google / Organic  
**Cube:** `channel_pnl`  
**Formula:** `meta_net_profit = Meta revenue ex-GST − Meta COGS − Meta ad_spend` (same for Google / Organic)

```json
{
  "measures": [
    "channel_pnl.meta_net_profit",
    "channel_pnl.google_net_profit",
    "channel_pnl.organic_net_profit"
  ],
  "timeDimensions": [{
    "dimension": "channel_pnl.date_start",
    "granularity": "day",
    "dateRange": "last 30 days"
  }],
  "order": { "channel_pnl.date_start": "asc" },
  "timezone": "Asia/Kolkata"
}
```

### #06 — Orders & AOV trend

**Chart type:** Dual-axis line · Orders (left) + AOV (right)  
**Cube:** `shopify_orders`  
**Formula:** `aov = gross_revenue / orders` · `net_orders = non-cancelled orders`

Always use `created_at_ist` (IST), never UTC `order_date` for dashboard parity.

```json
{
  "measures": [
    "shopify_orders.net_orders",
    "shopify_orders.aov",
    "shopify_orders.gross_revenue"
  ],
  "timeDimensions": [{
    "dimension": "shopify_orders.created_at_ist",
    "granularity": "day",
    "dateRange": "last 30 days"
  }],
  "order": { "shopify_orders.created_at_ist": "asc" },
  "timezone": "Asia/Kolkata"
}
```

### #07 — ROAS by channel (daily)

**Chart type:** Bar chart · Meta vs Google  
**Cube:** `channel_pnl`  
**Formula:** `meta_roas = meta_attributed_revenue / meta_ad_spend` · `google_roas = google_attributed_revenue / google_ad_spend`

```json
{
  "measures": [
    "channel_pnl.meta_roas",
    "channel_pnl.google_roas",
    "channel_pnl.meta_ad_spend",
    "channel_pnl.google_ad_spend"
  ],
  "timeDimensions": [{
    "dimension": "channel_pnl.date_start",
    "granularity": "day",
    "dateRange": "last 30 days"
  }],
  "order": { "channel_pnl.date_start": "asc" },
  "timezone": "Asia/Kolkata"
}
```

### #08 — Gross margin % trend

**Chart type:** Area chart · Daily  
**Cube:** `daily_pnl`  
**Formula:** `gross_margin_pct = gross_profit / total_sales_ex_gst × 100`

```json
{
  "measures": [
    "daily_pnl.gross_margin_pct",
    "daily_pnl.gross_profit",
    "daily_pnl.total_sales_ex_gst"
  ],
  "timeDimensions": [{
    "dimension": "daily_pnl.report_date",
    "granularity": "day",
    "dateRange": "last 30 days"
  }],
  "order": { "daily_pnl.report_date": "asc" },
  "timezone": "Asia/Kolkata"
}
```

### #09 — Return rate trend

**Chart type:** Line chart · Daily  
**Cube:** `shopify_orders`  
**Formula:** `return_rate = returned_orders / net_orders` · `returned_orders = return_status IN ('RETURNED', 'IN_PROGRESS') AND returned_at IS NOT NULL`

Do **not** use `IS NOT NULL` on `return_status` — Shopify sets it to `NO_RETURN` on ~98% of normal orders.

**Time axis:** Use `returned_at_ist` when counting *when returns happened*; use `created_at_ist` only for *cohort* return rate (orders placed that day that eventually returned).

```json
{
  "measures": [
    "shopify_orders.returned_orders"
  ],
  "timeDimensions": [{
    "dimension": "shopify_orders.returned_at_ist",
    "granularity": "day",
    "dateRange": "last 30 days"
  }],
  "order": { "shopify_orders.returned_at_ist": "asc" },
  "timezone": "Asia/Kolkata"
}
```

### #10 — P&L waterfall (revenue → profit)

**Chart type:** Waterfall / stepped bar · Period total  
**Cube:** `daily_pnl` · **MCP:** `cube_pnl_waterfall`

No granularity = period aggregate (single waterfall for the whole range).

```json
{
  "measures": [
    "daily_pnl.total_sales_ex_gst",
    "daily_pnl.total_cogs",
    "daily_pnl.gross_profit",
    "daily_pnl.meta_spend",
    "daily_pnl.google_spend",
    "daily_pnl.total_ad_spend",
    "daily_pnl.contribution_margin",
    "daily_pnl.packaging_cost",
    "daily_pnl.shipping_cost",
    "daily_pnl.payment_gateway_fees",
    "daily_pnl.rto_cost",
    "daily_pnl.net_profit"
  ],
  "timeDimensions": [{
    "dimension": "daily_pnl.report_date",
    "dateRange": "last 30 days"
  }],
  "timezone": "Asia/Kolkata"
}
```

---

## Meta ads — ad performance & attribution

### #11 — Ad spend + ROAS daily

**Chart type:** Dual-axis line · Spend (₹) left, ROAS right  
**Cube:** `marketing_performance`  
**Formula:** `roas = purchase_value / ad_spend`

```json
{
  "measures": [
    "marketing_performance.ad_spend",
    "marketing_performance.roas",
    "marketing_performance.purchase_value",
    "marketing_performance.purchases"
  ],
  "timeDimensions": [{
    "dimension": "marketing_performance.date_start",
    "granularity": "day",
    "dateRange": "last 30 days"
  }],
  "order": { "marketing_performance.date_start": "asc" },
  "timezone": "Asia/Kolkata"
}
```

### #12 — Impressions vs clicks vs CTR

**Chart type:** Grouped bar (impressions + clicks) + line (CTR)  
**Cube:** `marketing_performance`  
**Formula:** `ctr = clicks / impressions` · `cpc = ad_spend / clicks`

`ctr` and `cpc` are pre-calculated weighted averages — use directly, do not recompute from raw sums.

```json
{
  "measures": [
    "marketing_performance.impressions",
    "marketing_performance.clicks",
    "marketing_performance.ctr",
    "marketing_performance.cpc"
  ],
  "timeDimensions": [{
    "dimension": "marketing_performance.date_start",
    "granularity": "day",
    "dateRange": "last 30 days"
  }],
  "order": { "marketing_performance.date_start": "asc" },
  "timezone": "Asia/Kolkata"
}
```

### #13 — CPC · CPM · CPA — metric cards

**Chart type:** KPI strip · Period vs prior period  
**Cube:** `marketing_performance`  
**Formula:** `cpc = ad_spend / clicks` · `cpm = (ad_spend / impressions) × 1000` · `cpa = ad_spend / purchases` (compute in app)

CPA is not a pre-built measure — derive in the app as `ad_spend / purchases`.

```json
{
  "measures": [
    "marketing_performance.cpc",
    "marketing_performance.cpm",
    "marketing_performance.ad_spend",
    "marketing_performance.purchases",
    "marketing_performance.conversion_rate"
  ],
  "timeDimensions": [{
    "dimension": "marketing_performance.date_start",
    "dateRange": "last 30 days"
  }],
  "timezone": "Asia/Kolkata"
}
```

### #14 — Top campaigns by ROAS

**Chart type:** Horizontal ranked bar · Top 10  
**Cube:** `marketing_performance`

```json
{
  "measures": [
    "marketing_performance.roas",
    "marketing_performance.ad_spend",
    "marketing_performance.purchase_value",
    "marketing_performance.purchases",
    "marketing_performance.cpc"
  ],
  "dimensions": ["marketing_performance.campaign_name"],
  "timeDimensions": [{
    "dimension": "marketing_performance.date_start",
    "dateRange": "last 30 days"
  }],
  "order": { "marketing_performance.roas": "desc" },
  "limit": 10,
  "timezone": "Asia/Kolkata"
}
```

### #15 — Adset performance table

**Chart type:** Sortable data table · Campaign × Adset  
**Cube:** `marketing_performance`

```json
{
  "measures": [
    "marketing_performance.ad_spend",
    "marketing_performance.roas",
    "marketing_performance.ctr",
    "marketing_performance.cpc",
    "marketing_performance.cpm",
    "marketing_performance.purchases",
    "marketing_performance.purchase_value",
    "marketing_performance.impressions",
    "marketing_performance.clicks",
    "marketing_performance.conversion_rate"
  ],
  "dimensions": [
    "marketing_performance.campaign_name",
    "marketing_performance.adset_name"
  ],
  "timeDimensions": [{
    "dimension": "marketing_performance.date_start",
    "dateRange": "last 30 days"
  }],
  "order": { "marketing_performance.ad_spend": "desc" },
  "limit": 50,
  "timezone": "Asia/Kolkata"
}
```

### #16 — Purchase funnel

**Chart type:** Funnel chart · Period aggregate  
**Cube:** `marketing_performance`  
**Formula:** impressions → link_clicks → landing_page_views → add_to_carts → initiated_checkouts → purchases

Use `link_clicks` (not `clicks`) as the top-of-funnel step after impressions.

```json
{
  "measures": [
    "marketing_performance.impressions",
    "marketing_performance.link_clicks",
    "marketing_performance.landing_page_views",
    "marketing_performance.add_to_carts",
    "marketing_performance.initiated_checkouts",
    "marketing_performance.purchases"
  ],
  "timeDimensions": [{
    "dimension": "marketing_performance.date_start",
    "dateRange": "last 30 days"
  }],
  "timezone": "Asia/Kolkata"
}
```

### #17 — Spend & ROAS by hour of day

**Chart type:** Heatmap / bar · 24 hourly windows  
**Cube:** `ad_performance`

Use `ad_performance` (not `marketing_performance`) — only cube with `hourly_window`.

**Note:** Gold hourly table has delivery metrics only (spend, impressions, clicks). Purchases and ROAS are on `marketing_performance` (daily).

```json
{
  "measures": [
    "ad_performance.ad_spend",
    "ad_performance.impressions",
    "ad_performance.clicks"
  ],
  "dimensions": ["ad_performance.hourly_window"],
  "timeDimensions": [{
    "dimension": "ad_performance.date_start",
    "dateRange": "last 30 days"
  }],
  "order": { "ad_performance.hourly_window": "asc" },
  "timezone": "Asia/Kolkata"
}
```

### #18 — Attribution vs actual spend

**Chart type:** Side-by-side bar · Campaign level  
**Cube:** `dw_meta_ads_attribution`  
**Formula:** `attributed_gross_profit = attributed_revenue − attributed_cogs` · `roas = attributed_revenue / ad_spend`

`dw_meta_ads_attribution.ad_spend` is attribution-table spend — for company-level total ad spend always use `daily_pnl.total_ad_spend`.

```json
{
  "measures": [
    "dw_meta_ads_attribution.attributed_revenue",
    "dw_meta_ads_attribution.attributed_orders",
    "dw_meta_ads_attribution.attributed_cogs",
    "dw_meta_ads_attribution.attributed_gross_profit",
    "dw_meta_ads_attribution.roas"
  ],
  "dimensions": ["dw_meta_ads_attribution.campaign_name"],
  "timeDimensions": [{
    "dimension": "dw_meta_ads_attribution.date_start",
    "dateRange": "last 30 days"
  }],
  "order": { "dw_meta_ads_attribution.attributed_revenue": "desc" },
  "limit": 15,
  "timezone": "Asia/Kolkata"
}
```

### #19 — Video & engagement KPIs

**Chart type:** Metric cards + trend lines  
**Cube:** `marketing_performance`

```json
{
  "measures": [
    "marketing_performance.video_views",
    "marketing_performance.post_engagements",
    "marketing_performance.link_clicks",
    "marketing_performance.landing_page_views",
    "marketing_performance.add_to_carts"
  ],
  "timeDimensions": [{
    "dimension": "marketing_performance.date_start",
    "granularity": "day",
    "dateRange": "last 30 days"
  }],
  "order": { "marketing_performance.date_start": "asc" },
  "timezone": "Asia/Kolkata"
}
```

---

## Shopify — store & product analytics

### #20 — Revenue & orders daily

**Chart type:** Line + bar combo · Daily  
**Cube:** `shopify_orders`

```json
{
  "measures": [
    "shopify_orders.gross_revenue",
    "shopify_orders.net_sales_ex_gst",
    "shopify_orders.net_orders",
    "shopify_orders.aov"
  ],
  "timeDimensions": [{
    "dimension": "shopify_orders.created_at_ist",
    "granularity": "day",
    "dateRange": "last 30 days"
  }],
  "order": { "shopify_orders.created_at_ist": "asc" },
  "timezone": "Asia/Kolkata"
}
```

### #21 — Top products by revenue

**Chart type:** Horizontal ranked bar · Top 15  
**Cube:** `product_performance`  
**Formula:** `gross_profit_ex_gst = net_line_revenue_ex_gst − total_cogs`

Sort by `net_line_revenue_ex_gst` (excludes returns), not `gross_line_revenue_ex_gst`.

```json
{
  "measures": [
    "product_performance.gross_line_revenue_ex_gst",
    "product_performance.net_line_revenue_ex_gst",
    "product_performance.total_quantity",
    "product_performance.gross_profit_ex_gst",
    "product_performance.total_cogs"
  ],
  "dimensions": ["product_performance.product_title"],
  "timeDimensions": [{
    "dimension": "product_performance.created_at_ist",
    "dateRange": "last 30 days"
  }],
  "order": { "product_performance.net_line_revenue_ex_gst": "desc" },
  "limit": 15,
  "timezone": "Asia/Kolkata"
}
```

### #22 — Return & cancel analysis by product

**Chart type:** Stacked bar · returned vs cancelled vs fulfilled  
**Cube:** `product_performance`

`returned_units` is pre-filtered to RETURNED + IN_PROGRESS. Do **not** add an extra `return_status` filter.

```json
{
  "measures": [
    "product_performance.returned_units",
    "product_performance.cancelled_units",
    "product_performance.total_quantity",
    "product_performance.total_line_discounts"
  ],
  "dimensions": ["product_performance.product_title"],
  "timeDimensions": [{
    "dimension": "product_performance.created_at_ist",
    "dateRange": "last 30 days"
  }],
  "order": { "product_performance.returned_units": "desc" },
  "limit": 20,
  "timezone": "Asia/Kolkata"
}
```

### #23 — Revenue by geography

**Chart type:** Choropleth / ranked list · Country & province  
**Cube:** `shopify_orders`

Geo comes from `gold.dim_customers` join (`default_country` / `default_province`). Remove `ship_province` for country-level only.

```json
{
  "measures": [
    "shopify_orders.gross_revenue",
    "shopify_orders.net_orders",
    "shopify_orders.aov"
  ],
  "dimensions": [
    "shopify_orders.ship_country",
    "shopify_orders.ship_province"
  ],
  "timeDimensions": [{
    "dimension": "shopify_orders.created_at_ist",
    "dateRange": "last 30 days"
  }],
  "order": { "shopify_orders.gross_revenue": "desc" },
  "limit": 50,
  "timezone": "Asia/Kolkata"
}
```

### #24 — UTM source breakdown

**Chart type:** Donut + ranked table  
**Cube:** `shopify_orders`

Remove `utm_medium` and `utm_campaign` for a cleaner source-only donut.

```json
{
  "measures": [
    "shopify_orders.gross_revenue",
    "shopify_orders.net_orders",
    "shopify_orders.aov"
  ],
  "dimensions": [
    "shopify_orders.utm_source",
    "shopify_orders.utm_medium",
    "shopify_orders.utm_campaign"
  ],
  "timeDimensions": [{
    "dimension": "shopify_orders.created_at_ist",
    "dateRange": "last 30 days"
  }],
  "order": { "shopify_orders.gross_revenue": "desc" },
  "limit": 30,
  "timezone": "Asia/Kolkata"
}
```

### #25 — Discount impact

**Chart type:** Bar chart · Daily discounts vs net revenue  
**Cube:** `shopify_order_line_items`

```json
{
  "measures": [
    "shopify_order_line_items.total_line_discounts",
    "shopify_order_line_items.net_line_revenue_ex_gst",
    "shopify_order_line_items.gross_profit_ex_gst",
    "shopify_order_line_items.total_cogs",
    "shopify_order_line_items.avg_unit_price",
    "shopify_order_line_items.avg_discounted_unit_price"
  ],
  "timeDimensions": [{
    "dimension": "shopify_order_line_items.created_at_ist",
    "granularity": "day",
    "dateRange": "last 30 days"
  }],
  "order": { "shopify_order_line_items.created_at_ist": "asc" },
  "timezone": "Asia/Kolkata"
}
```

### #26 — Units per order & AOV

**Chart type:** Line chart · Basket size over time  
**Cube:** `shopify_order_line_items`

```json
{
  "measures": [
    "shopify_order_line_items.units_per_order",
    "shopify_order_line_items.avg_unit_price",
    "shopify_order_line_items.avg_discounted_unit_price",
    "shopify_order_line_items.unique_products"
  ],
  "timeDimensions": [{
    "dimension": "shopify_order_line_items.created_at_ist",
    "granularity": "day",
    "dateRange": "last 30 days"
  }],
  "order": { "shopify_order_line_items.created_at_ist": "asc" },
  "timezone": "Asia/Kolkata"
}
```

### #27 — Fulfillment status mix

**Chart type:** Donut chart · Period total  
**Cube:** `shopify_orders`

```json
{
  "measures": [
    "shopify_orders.orders",
    "shopify_orders.gross_revenue"
  ],
  "dimensions": ["shopify_orders.fulfillment_status"],
  "timeDimensions": [{
    "dimension": "shopify_orders.created_at_ist",
    "dateRange": "last 30 days"
  }],
  "order": { "shopify_orders.orders": "desc" },
  "timezone": "Asia/Kolkata"
}
```

### #28 — Gross margin by SKU

**Chart type:** Scatter / ranked bar · Top 20 SKUs  
**Cube:** `product_performance`  
**Formula:** `gross_profit_ex_gst = net_line_revenue_ex_gst − total_cogs` · margin% = compute in app

```json
{
  "measures": [
    "product_performance.gross_profit_ex_gst",
    "product_performance.total_cogs",
    "product_performance.net_line_revenue_ex_gst",
    "product_performance.avg_unit_price",
    "product_performance.avg_discounted_unit_price",
    "product_performance.total_quantity"
  ],
  "dimensions": [
    "product_performance.sku",
    "product_performance.product_title"
  ],
  "timeDimensions": [{
    "dimension": "product_performance.created_at_ist",
    "dateRange": "last 30 days"
  }],
  "order": { "product_performance.gross_profit_ex_gst": "desc" },
  "limit": 20,
  "timezone": "Asia/Kolkata"
}
```

### #29 — Shipping revenue contribution

**Chart type:** Stacked area chart · Daily  
**Cube:** `shopify_orders`

```json
{
  "measures": [
    "shopify_orders.gross_revenue",
    "shopify_orders.shipping_revenue",
    "shopify_orders.net_sales_ex_gst",
    "shopify_orders.orders_with_shipping"
  ],
  "timeDimensions": [{
    "dimension": "shopify_orders.created_at_ist",
    "granularity": "day",
    "dateRange": "last 30 days"
  }],
  "order": { "shopify_orders.created_at_ist": "asc" },
  "timezone": "Asia/Kolkata"
}
```

---

## Advanced views (beyond 29 charts)

For ad-hoc gold aggregation, use views in `model/views/serve_views.yml`:

| View | Gold table | MCP tool |
|------|------------|----------|
| `canonical_pnl` | `fct_daily_pnl` | `cube_canonical_pnl` |
| `commerce_orders` | `fct_orders` | `cube_commerce_orders` |
| `meta_ad_performance` | `fct_meta_ads_daily` | `cube_meta_ads` |
| `google_ad_performance` | `fct_google_ads_daily` | `cube_google_ads` |
| `google_ad_hourly` | `fct_google_campaigns_hourly` | `cube_google_ads_hourly` |
| `order_attribution` | `fct_order_attribution` | `cube_order_attribution` |
| `session_funnel` | `fct_session_funnel` | `cube_session_funnel` |
| `customer_ltv` | `dim_customers` | `cube_customer_ltv` |
| `payment_cashflow` | `fct_payments` | `cube_payment_cashflow` |
| `variant_economics` | `fct_product_variant_cost` | `cube_variant_economics` |
| `neurohack_catalog` | `dim_neurohack` | `cube_neurohack_catalog` |
| `ad_neurohack_map` | `dim_ad_neurohack_map` × catalog | `cube_ad_neurohack` |
| `meta_neurohack_performance` | `fct_meta_ads_daily` × tag map (deprecated) | `cube_meta_neurohack` |
| `meta_neurotag_analysis` | `mart_meta_ad_neurotag_daily` | `cube_meta_neurotag` |

### Neurohack creative taxonomy

**Sources:** `gold.dim_neurohack` (tag catalog) · `gold.dim_ad_neurohack_map` (ad name parsing) · `gold.mart_meta_ad_neurotag_daily` (tag analysis mart)

**Important:** Ads with multiple tags **fan out spend** on full-credit (`*_fc`) columns. Use split-credit (`*_sc`) via `meta_neurotag_analysis` for tag rollups, or deduplicate by `ad_id` for account totals.

#### Tag catalog by category

**Chart type:** Table / treemap · Static catalog  
**View:** `neurohack_catalog` · **MCP:** `cube_neurohack_catalog`

```json
{
  "measures": ["neurohack_catalog.tags"],
  "dimensions": [
    "neurohack_catalog.category_code",
    "neurohack_catalog.category_name",
    "neurohack_catalog.hack_name",
    "neurohack_catalog.tag_code"
  ],
  "order": { "neurohack_catalog.category_order": "asc" },
  "timezone": "Asia/Kolkata"
}
```

#### Meta spend by Neurohack category (legacy)

**Chart type:** Ranked bar · Period total  
**View:** `meta_neurohack_performance` · **MCP:** `cube_meta_neurohack`  
**Note:** Deprecated — use `meta_neurotag_analysis` with `spend_sc` for correct tag-level totals.

```json
{
  "measures": [
    "meta_neurohack_performance.spend",
    "meta_neurohack_performance.purchase_value",
    "meta_neurohack_performance.roas",
    "meta_neurohack_performance.purchases"
  ],
  "dimensions": ["meta_neurohack_performance.category_name"],
  "timeDimensions": [{
    "dimension": "meta_neurohack_performance.report_date",
    "dateRange": "last 30 days"
  }],
  "order": { "meta_neurohack_performance.spend": "desc" },
  "limit": 20,
  "timezone": "Asia/Kolkata"
}
```

#### Top hacks by spend (daily trend)

**Chart type:** Multi-line · Daily by hack  
**View:** `meta_neurohack_performance`

```json
{
  "measures": ["meta_neurohack_performance.spend"],
  "dimensions": ["meta_neurohack_performance.hack_name"],
  "timeDimensions": [{
    "dimension": "meta_neurohack_performance.report_date",
    "granularity": "day",
    "dateRange": "last 30 days"
  }],
  "order": { "meta_neurohack_performance.report_date": "asc" },
  "limit": 10,
  "timezone": "Asia/Kolkata"
}
```

#### Ads mapped to a tag

**Chart type:** Data table  
**View:** `ad_neurohack_map` · **MCP:** `cube_ad_neurohack`

```json
{
  "measures": ["ad_neurohack_map.tagged_ads"],
  "dimensions": [
    "ad_neurohack_map.ad_id",
    "ad_neurohack_map.ad_name",
    "ad_neurohack_map.tag_code",
    "ad_neurohack_map.category_name",
    "ad_neurohack_map.hack_name"
  ],
  "filters": [{
    "member": "ad_neurohack_map.tag_code",
    "operator": "equals",
    "values": ["VP032"]
  }],
  "order": { "ad_neurohack_map.ad_name": "asc" },
  "limit": 50,
  "timezone": "Asia/Kolkata"
}
```

#### Neurohack tag analysis — split-credit (recommended)

**Chart type:** Bar / table · Tag or category leaderboard  
**View:** `meta_neurotag_analysis` · **MCP:** `cube_meta_neurotag` (`credit_mode=split`)

Use `*_sc` measures when summing across tags or categories. Split-credit divides each ad's metrics by `tag_count`.

```json
{
  "measures": [
    "meta_neurotag_analysis.spend_sc",
    "meta_neurotag_analysis.net_revenue_sc",
    "meta_neurotag_analysis.attributed_orders_sc",
    "meta_neurotag_analysis.roas_sc"
  ],
  "dimensions": ["meta_neurotag_analysis.category_name"],
  "timeDimensions": [{
    "dimension": "meta_neurotag_analysis.report_date",
    "dateRange": ["2026-05-01", "2026-05-31"]
  }],
  "order": { "meta_neurotag_analysis.spend_sc": "desc" },
  "limit": 20,
  "timezone": "Asia/Kolkata"
}
```

#### Neurohack tag analysis — full-credit (single tag per ad)

**Chart type:** Table · Ad-level drill-down  
**View:** `meta_neurotag_analysis` · **MCP:** `cube_meta_neurotag` (`credit_mode=full`)

Use `*_fc` when listing ads or filtering to one `tag_code`. Do not sum `spend_fc` across multiple tags without grouping by `ad_id`.

```json
{
  "measures": [
    "meta_neurotag_analysis.spend_fc",
    "meta_neurotag_analysis.net_revenue_fc",
    "meta_neurotag_analysis.attributed_orders_fc",
    "meta_neurotag_analysis.roas_fc",
    "meta_neurotag_analysis.ctr",
    "meta_neurotag_analysis.cpa"
  ],
  "dimensions": [
    "meta_neurotag_analysis.ad_id",
    "meta_neurotag_analysis.ad_name",
    "meta_neurotag_analysis.tag_code",
    "meta_neurotag_analysis.hack_name"
  ],
  "filters": [{
    "member": "meta_neurotag_analysis.tag_code",
    "operator": "notEquals",
    "values": ["__untagged__"]
  }],
  "timeDimensions": [{
    "dimension": "meta_neurotag_analysis.report_date",
    "dateRange": "last 30 days"
  }],
  "order": { "meta_neurotag_analysis.spend_fc": "desc" },
  "limit": 50,
  "timezone": "Asia/Kolkata"
}
```

#### Neurohack video retention by tag (split-credit)

**Chart type:** Ranked bar · Creative diagnostics  
**View:** `meta_neurotag_analysis` · **MCP:** `cube_meta_neurotag` (`credit_mode=split`)

```json
{
  "measures": [
    "meta_neurotag_analysis.video_views_3s_sc",
    "meta_neurotag_analysis.video_thruplay_15s_sc",
    "meta_neurotag_analysis.video_p50_views_sc",
    "meta_neurotag_analysis.hook_rate",
    "meta_neurotag_analysis.hold_rate_15s",
    "meta_neurotag_analysis.hold_rate_p50",
    "meta_neurotag_analysis.cost_per_thruplay"
  ],
  "dimensions": ["meta_neurotag_analysis.hack_name"],
  "timeDimensions": [{
    "dimension": "meta_neurotag_analysis.report_date",
    "dateRange": "last 30 days"
  }],
  "order": { "meta_neurotag_analysis.hook_rate": "desc" },
  "limit": 15,
  "timezone": "Asia/Kolkata"
}
```

#### Ad-level video funnel (no tags)

**Chart type:** Table  
**View:** `meta_ad_performance` · **MCP:** `cube_meta_ads`

```json
{
  "measures": [
    "meta_ad_performance.spend",
    "meta_ad_performance.impressions",
    "meta_ad_performance.video_views_3s",
    "meta_ad_performance.video_thruplay_15s",
    "meta_ad_performance.video_p50_views",
    "meta_ad_performance.video_p75_views",
    "meta_ad_performance.video_p100_views",
    "meta_ad_performance.hook_rate",
    "meta_ad_performance.hold_rate_15s",
    "meta_ad_performance.hold_rate_p50",
    "meta_ad_performance.cost_per_thruplay"
  ],
  "dimensions": [
    "meta_ad_performance.ad_id",
    "meta_ad_performance.ad_name",
    "meta_ad_performance.creative_video_id"
  ],
  "timeDimensions": [{
    "dimension": "meta_ad_performance.report_date",
    "dateRange": "last 30 days"
  }],
  "order": { "meta_ad_performance.hook_rate": "desc" },
  "limit": 25,
  "timezone": "Asia/Kolkata"
}
```

#### Neurohack attributed ROAS by hack (split-credit)

**Chart type:** Ranked bar  
**View:** `meta_neurotag_analysis` · **MCP:** `cube_meta_neurotag`

```json
{
  "measures": [
    "meta_neurotag_analysis.spend_sc",
    "meta_neurotag_analysis.net_revenue_sc",
    "meta_neurotag_analysis.roas_sc",
    "meta_neurotag_analysis.new_customer_revenue_sc"
  ],
  "dimensions": ["meta_neurotag_analysis.hack_name"],
  "timeDimensions": [{
    "dimension": "meta_neurotag_analysis.report_date",
    "dateRange": "last 30 days"
  }],
  "order": { "meta_neurotag_analysis.roas_sc": "desc" },
  "limit": 15,
  "timezone": "Asia/Kolkata"
}
```

---

## Schema files

| File | Purpose |
|------|---------|
| `model/cubes/gold_*.yml` | Gold cubes — all table columns synced from ClickHouse |
| `model/views/serve_views.yml` | Curated analytical views for MCP (`canonical_pnl`, bridge views) |
| `model/views/chart_views.yml` | 8 chart-aligned views (29 dashboard charts) |
| `model/views/gold_full_views.yml` | Auto-generated `gold__*` full-column views |
| `SEMANTIC_LAYER_GAP_ANALYSIS.md` | Gap inventory, resolved items, anti-patterns |
| `scripts/validate_no_serve_db.py` | Ensures zero `serve.*` DB references in cubes |
| `scripts/validate_serve_views.py` | Smoke-test each serve view |
| `catalog/gold_semantic_catalog.json` | Machine-readable field catalog |

### Serve vs chart naming (same gold table)

| Concept | Serve view | Chart view |
|---------|------------|------------|
| Company P&L | `canonical_pnl.*` | `daily_pnl.*` |
| Orders | `commerce_orders.*` | `shopify_orders.*` |
| Meta ads | `meta_ad_performance.spend` | `marketing_performance.ad_spend` |

Regenerate after schema changes:

```bash
cd /opt/seleric/mcp_stack/semantic_layer_serve
python3 scripts/sync_gold_cube_columns.py
python3 scripts/generate_semantic_catalog.py
docker restart mcp-serve-cube-serve-1
```

---

*Generated from Seleric gold semantic layer · Timezone IST (Asia/Kolkata) · Returns RETURNED + IN_PROGRESS only*
