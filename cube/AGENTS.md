# Gold Semantic Layer — Agent Query Guide (MCP v2.0.0)

**Chart queries (all 29):** [CHART_QUERY_REFERENCE.md](./CHART_QUERY_REFERENCE.md)  
**Field catalog (JSON):** [catalog/gold_semantic_catalog.json](./catalog/gold_semantic_catalog.json)  
**Business formulas:** [mage-ai/docs/FINANCE_DEFINITIONS.md](../../mage-ai/docs/FINANCE_DEFINITIONS.md)

Stack: **ClickHouse `gold.*` only** via Cube views. MCP **`seleric-cube-serve`** (port **3012**).

**Terminology:** *Serve layer* = Cube + MCP + `serve_views.yml` (allowed). *Serve DB* = legacy `serve.*` Postgres (forbidden). All cubes read `gold.*` only.

**Gap analysis:** [SEMANTIC_LAYER_GAP_ANALYSIS.md](./SEMANTIC_LAYER_GAP_ANALYSIS.md)
**Cube overlap audit:** [../catalogue/CUBE_AUDIT_REPORT.md](../catalogue/CUBE_AUDIT_REPORT.md)

> **2026-07-11 model change:** every cube in `model/cubes/` is now `public: false`
> — only views (this file's routing table) are queryable. Renamed/retired/added:
> `amazon_sp_orders` → `orders_amazon`; `customer_acquisition_ltv` removed (group
> `customer_ltv` by its acquisition dimensions instead); `shopify_order_line_items`
> merged into `product_performance`; new `meta_campaign_attribution` view added
> (modern name for `dw_meta_ads_attribution`, still present but deprecated);
> `marketing_performance` / `ad_performance` deprecated in favor of
> `meta_ad_performance` / `meta_ad_hourly`. See `catalogue/deprecations.yaml`.

---

## Domain routing

| Need | View | MCP tool |
|------|------|----------|
| Company net profit, MER (full waterfall) | `canonical_pnl` | `cube_canonical_pnl` |
| Dashboard P&L KPI strip (#01–#03, #08, #10) | `daily_pnl` | `cube_daily_pnl`, `cube_pnl_waterfall` |
| Channel revenue / net profit (#04–#05, #07) | `channel_pnl` | `cube_channel_pnl` |
| Order trends, AOV, geo, UTM (#06, #09, #20, #23–#24, #27, #29) | `shopify_orders` | `cube_commerce_orders` |
| Line discounts, basket size (#25–#26); SKU / product performance (#21–#22, #28) | `product_performance` | `cube_product_performance` / `cube_line_economics` |
| Meta ads daily (#11–#16) | `meta_ad_performance` (was `marketing_performance`, deprecated) | `cube_meta_ads` |
| Meta ads hourly (#17) | `meta_ad_hourly` (was `ad_performance`, deprecated) | `cube_query` |
| Meta campaign attribution (#18) | `meta_campaign_attribution` (was `dw_meta_ads_attribution`, deprecated) | `cube_query` |
| Google ads | `google_ad_performance` | `cube_google_ads` |
| Order attribution (raw) | `order_attribution` | `cube_order_attribution` |
| Session funnel | `session_funnel` | `cube_session_funnel` |
| Neurohack tag catalog | `neurohack_catalog` | `cube_neurohack_catalog` |
| Ad → Neurohack tags | `ad_neurohack_map` | `cube_ad_neurohack` |
| Meta × tag analysis (fc/sc + attribution) | `meta_neurotag_analysis` | `cube_meta_neurotag` |
| Meta spend by Neurohack tag (legacy) | `meta_neurohack_performance` | `cube_meta_neurohack` (deprecated) |
| Campaign × SKU attribution | `campaign_product_performance` | `cube_campaign_product` |
| Cohort LTV by acquisition | `customer_ltv` grouped by `acquisition_channel`/`acquisition_campaign`/`acquisition_platform`/`first_order_cohort_month` (was `customer_acquisition_ltv`, removed) | `cube_customer_ltv` |
| Neurohack × attributed revenue | `neurohack_attribution` | `cube_neurohack_attribution` |
| Session CVR + P&L same day | `daily_performance` | `cube_daily_performance` |
| Refund timing / cash-at-risk | `refund_events` | `cube_refund_events` |
| COD vs prepaid P&L | `payment_method_pnl` | `cube_payment_method_pnl` |
| Hourly orders (IST) | `hourly_commerce` | `cube_hourly_commerce` |
| All field definitions | — | `cube_schema_catalog` |
| Custom query | any view | `cube_query` |

---

## Canonical P&L (`canonical_pnl`)

Source (rebuilt 2026-07-10): `gold.int_finance_daily_rollups` (revenue, lifecycle
gross/net COGS by axis, returns/cancels, Amazon slices) + `gold.fct_order_items`
(Shopify cost split on placement + event date axes) + `fct_meta_ads_daily` /
`fct_google_ads_daily` / `fct_amazon_ads_campaigns_daily` (ad spend). Reconciles with
the `/api/v1/historical` and `/api/v1/pnl` dashboards. Sum daily `report_date` rows
for period totals (IST).

> **Do not use `gold.fct_daily_pnl` / `fct_finance_waterfall_daily`.** Both carry a
> broken product-cost basis (negative COGS, `net_profit > net_revenue`) and are no
> longer exposed. The `finance_waterfall` view was removed; statutory / deferred net
> sales are now `canonical_pnl.statutory_net_sales_excl_gst` / `deferred_revenue_excl_gst`.

| Measure | Meaning |
|---------|---------|
| `canonical_pnl.net_profit` | `net_revenue_excl_tax − net_cogs − total_ad_spend` (Shopify + Amazon) |
| `canonical_pnl.net_revenue_excl_tax` | Net sales ex-GST incl Amazon net (P&L revenue base; fixed 2026-07-10 — was Shopify-only while COGS/ad spend were company-wide). Split: `shopify_net_revenue_excl_tax` / `amazon_net_revenue` |
| `canonical_pnl.net_cogs` (= `total_cogs`) | Lifecycle net COGS by axis, incl Amazon |
| `canonical_pnl.gross_cogs` | Lifecycle gross COGS (product retained on cancel/return) |
| `canonical_pnl.mer` | `net_revenue_excl_tax / total_ad_spend` |
| `canonical_pnl.product_cost` | Product COGS only (Shopify ACTIVE lines + Amazon `cogs_product`) |
| `canonical_pnl.total_ad_spend` | `meta_spend + google_spend + amazon_spend` |

## Amazon (Seller-Partner + Ads)

| Need | View | Grain |
|------|------|-------|
| Amazon orders (date axis `purchase_date`; filter `order_attribution_tag = 'ORGANIC'`) | `orders_amazon` (was `amazon_sp_orders`, renamed 2026-07-11) | order |
| Amazon order-level P&L (payout, fees, COGS, profit) | `amazon_sp_order_pnl` | order |
| Amazon SKU / ASIN line economics | `amazon_order_items` | order item |
| Amazon Ads (date axis `report_date`) | `amazon_ad_performance` | campaign × day |
| Amazon pending refunds / label fees (accrual) | `amazon_return_reconciliation` | return record |

`amazon_sp_order_pnl`: `gross_revenue`/`net_payout`/`refunds` = effective ?? estimated;
`amazon_fees` = component sum incl TCS/TDS (never `Math.abs(SUM(total_amazon_fees))`);
`total_cogs` = `amazon_fees + product_cost`. Ads `sales`/`orders` are platform-attributed,
not Shopify truth — use `amazon_ad_performance` only for spend/impressions/clicks/ROAS.

---

## Commerce orders (`commerce_orders`)

Source: `gold.fct_orders`. Cube filters `is_test = false`.

Order buckets: `active_orders + cancelled_orders + refunded_orders` (cancelled takes precedence on refunded).

---

## Product performance (`product_performance`)

Source: `gold.fct_order_items`. Grain: `brand_id × order_id × line_item_id`.

Group by `sku`, `product_title`, or `order_date` for charts #20–#22, #28.

---

## Attribution (`order_attribution`)

Source: `gold.fct_order_attribution`. Grain: order (not session).

- `attributed_orders` = active/partially_refunded only
- Pair with `cube_meta_ads` / `cube_google_ads` for platform ROAS (same date range + brand)
- **Not** for company `net_profit` — use `canonical_pnl`

---

## Session funnel (`session_funnel`)

Source: `gold.fct_session_funnel`. Grain: session.

- Count `sessions`, `converted_sessions`, conversion rates
- **Do not** sum revenue for P&L
- Snowplow coverage may be partial — check date range

---

## Ads

| Platform | View | Grain |
|----------|------|-------|
| Meta totals | `meta_ad_performance` | date × campaign × adset × ad |
| Meta breakdown | `meta_ad_breakdown` | date × ad × **one** `breakdown_type` × segment |
| Google daily | `google_ad_performance` | + device × network |
| Google hourly | `google_ad_hourly` | + hour_of_day |

Platform-reported ROAS uses platform conversion values, not Shopify truth.

### Meta breakdown (`meta_ad_breakdown`)

Source: `gold.fct_meta_ads_breakdown_daily`. Eight independent Meta API slices unioned in one table:

`publisher_platform`, `placement`, `platform_device`, `country`, `region`, `dma`, `age_and_gender`, `demographics_age`

**Anti-patterns**

- Do **not** `SUM(spend)` without `WHERE breakdown_type = '<one type>'` — same ad spend is repeated in every slice (~8× overcount).
- Do **not** use this table for total Meta spend or P&L — use `meta_ad_performance` or `canonical_pnl.meta_spend`.
- Typed columns (`gender`, `publisher_platform`, `country`, …) are sparse; only the columns for the active `breakdown_type` are populated.

**Safe patterns**

```sql
-- Platform mix (one slice)
SELECT publisher_platform, sum(spend)
FROM gold.fct_meta_ads_breakdown_daily
WHERE brand_id = 20 AND breakdown_type = 'publisher_platform'
GROUP BY 1;

-- Total Meta spend (correct table)
SELECT sum(spend) FROM gold.fct_meta_ads_daily WHERE brand_id = 20;
```

---

## Neurohack tag analysis (`meta_neurotag_analysis`)

Source: `gold.mart_meta_ad_neurotag_daily`. Grain: `brand_id × report_date × ad_id × tag_code`.

Combines Meta delivery (from hourly rollup), last-touch Shopify attribution, Neurohack tags, and video metrics (3s views, thruplay, quartile retention) from `fct_meta_ads_daily`.

| MCP param | Values | Effect |
|-----------|--------|--------|
| `credit_mode` | `split` (default) | Uses `*_sc` measures — safe for tag/category rollups |
| `credit_mode` | `full` | Uses `*_fc` measures — ad-level credit; filter `tag_code` when grouping by tag |
| `group_by` | `tag`, `category`, `hack`, `day`, `ad` | Dimension for breakdown |

**Anti-patterns**

- Do **not** `SUM(spend_fc)` grouped only by `category_name` — multi-tag ads count full spend on every tag row.
- Do **use** `spend_sc` / `net_revenue_sc` / `attributed_orders_sc` for tag-level leaderboards.
- Untagged ads appear as `tag_code = __untagged__` — include or exclude explicitly in filters.

**Video metrics (tag × creative analysis)**

| Measure | Meaning |
|---------|---------|
| `video_views_3s_fc/sc` | Hook views (3-second plays) |
| `video_thruplay_15s_fc/sc` | 15-second thruplays |
| `video_p50_views_fc/sc` | Watched to 50% |
| `hook_rate` | `video_views_3s / impressions` (recomputed at query time) |
| `hold_rate_15s` | `thruplay / 3s views` |
| `hold_rate_p50` | `p50 / 3s views` |
| `cost_per_thruplay` | `spend / thruplay` |

Use `*_sc` for tag/category video rollups (same rule as spend).

**Example MCP call**

```
cube_meta_neurotag(start_date="2026-05-01", end_date="2026-05-31", brand_id="20", group_by="category", credit_mode="split")
```

For ad-level video only (no tags): `cube_meta_ads` — includes `video_views_3s`, `hook_rate`, `hold_rate_p50`, `cost_per_thruplay`.

**Legacy:** `cube_meta_neurohack` / `meta_neurohack_performance` — SQL bridge on `fct_meta_ads_daily` × map; no attribution, no split-credit. Prefer `cube_meta_neurotag`.

---

## Conventions

- **Timezone:** `Asia/Kolkata` on all queries
- **brand_id:** Filter when multi-brand data
- **Deprecated serve.* cubes removed** — all chart views read `gold.*` only
- **Legacy view names restored:** `daily_pnl`, `channel_pnl`, `shopify_orders`, etc. — see `chart_views.yml`. Some (`marketing_performance`, `ad_performance`, `dw_meta_ads_attribution`) are now marked `[deprecated]` in favor of a modern-named equivalent; `shopify_order_line_items` and `customer_acquisition_ltv` were retired outright (2026-07-11) — see `catalogue/deprecations.yaml`.

---

## Regenerate catalog

```bash
python3 scripts/validate_no_serve_db.py
python3 scripts/sync_gold_cube_columns.py
python3 scripts/generate_semantic_catalog.py
```

Full-column views: `gold__fct_daily_pnl`, `gold__fct_orders`, bridge views (`gold__campaign_product_performance`, etc.) — query via `cube_query` or dedicated MCP tools.
