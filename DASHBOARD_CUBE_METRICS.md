# Dashboard (Gold) ↔ Cube Metric Audit

**Gold query = source of truth.** Every formula, field and Cube definition below is copied from code. Nothing is inferred.

## Scope

The audited dashboard is the **Reports/Historical Analytics dashboard** — the 14 cards defined in
`Seleric_Dashboard/fe-dashboard/src/components/DashboardWithDateRange.jsx:284-425`.

Data path (verified):

| Layer | Path |
|---|---|
| Card list | `fe-dashboard/src/components/DashboardWithDateRange.jsx:284-425` |
| Card math | `fe-dashboard/src/lib/metrics/buildDashboardStats.js:86-341` |
| Backend assembly | `Node-Backend/src/integrations/historicalAnalytics/analyticsClickhouse.js:416-565` |
| Gold SQL (headline totals) | `Node-Backend/src/integrations/historicalAnalytics/lineItemHistoricalSql.js:552-712` |
| Shared SQL expressions | `Node-Backend/src/integrations/historicalAnalytics/historicalQueryHelpers.js:17-107` |
| Amazon SP SQL | `Node-Backend/src/integrations/amazonShared/amazonSpOrderTotals.js:302-432` |

The `liveDashboard` bundle (`liveDashboardBundle.js`) calls the Shopify/Meta/Google **platform APIs**, not Gold. It is out of scope.

Cube path (verified):

| Layer | Path |
|---|---|
| Serve view | `Base_Agent/cube/model/views/serve_views.yml:2-92` (`canonical_pnl`), `:94-146` (`commerce_orders`) |
| Cube | `Base_Agent/cube/model/cubes/gold_fct_daily_pnl.yml`, `gold_fct_orders.yml` |
| Cube's Gold source | `data_platform/mage-ai/dbt/models/iceberg/cross_platform/int_finance_daily_rollups.sql` |
| Agent metric surface | `Base_Agent/catalogue/metrics/*.yaml` |
| Agent → Cube binding | `Base_Agent/src/seleric_mcp/app/query_planner.py:244-253` |

**Agent surface constraint (verified).** `query_planner.py:244-253` builds the Cube query exclusively from `metric.cube_mapping.measure`. The agent can therefore only reach the **56 metric ids** in `catalogue/metrics/`. A Cube measure that exists but has no catalogue entry is **unreachable by the agent** — reported below as `Missing`.

Only **8** catalogue metrics map to `canonical_pnl`: `net_revenue`, `net_profit`, `gross_profit`, `total_cogs`, `total_ad_spend`, `contribution_margin`, `mer`, `blended_roas`.

---

## Cross-cutting root cause

The two systems compute the same P&L from **two different Gold engines**:

* **Dashboard** composes `gold.fct_orders` (order grain, deduped by `argMax(..., _loaded_at)`) + `gold.fct_order_items` (line grain, event-date arms) + `gold.fct_amazon_sp_orders` / `fct_amazon_sp_order_pnl` at query time.
* **Cube** reads the pre-aggregated `gold.int_finance_daily_rollups`, which is built from `int_finance_order_lines` (line grain) + `fct_amazon_order_items` + `fct_amazon_sp_order_pnl`.

Consequences that recur in nearly every metric below:

1. **Shopify revenue grain.** Dashboard derives gross/net from **order-level** `fct_orders` fields (`gross_revenue`, `net_revenue`, `total_tax`, `total_discounts`) with a proportional GST strip. Cube's basis sums **line-level** `net_pre_refund_excl_gst` / `discount_excl_gst`.
2. **Adjustment refunds.** Cube's revenue base subtracts `adjustment_refund_excl_gst`; the dashboard does not. (`int_finance_daily_rollups.sql:360-366`)
3. **Amazon basis.** Dashboard filters SP orders by `order_status NOT IN ('cancelled','canceled')`; Gold rollup filters by `payout_basis != 'NONE'` / `pnl_refund_status`.

---

### `Net Profit`

* **Dashboard label:** `Net Profit` — `DashboardWithDateRange.jsx:287`
* **Gold query:** `analyticsClickhouse.js:469` → `netProfit = netSales - totalAdSpend - totalCogs`; SQL form `lineItemHistoricalSql.js:697` → `round(r.net_sales - r.net_cogs - r.total_ad_spend, 2)`
* **Frontend recompute:** `buildDashboardStats.js:104-105` → `netProfit = netSales - adSpend - netCogs`
* **Gold tables/fields:** `fct_orders`, `fct_order_items`, `fct_meta_ads_daily`/`fct_meta_ads_hourly`, `fct_google_ads_daily`/`fct_google_campaigns_hourly`, `fct_amazon_ads_campaigns_daily.cost`, `fct_amazon_sp_orders`, `fct_amazon_sp_order_pnl`
* **Formula:** `net_sales − net_cogs − total_ad_spend`
* **Aggregation:** additive over daily buckets (`sumBuckets`, `lineItemHistoricalSql.js:801-830`)
* **Date logic:** sales/orders on placement date (`order_date`); returns/cancels/COGS on **event date in IST** (`toDate(toTimeZone(..., 'Asia/Kolkata'))`)
* **Rounding:** `round(..., 2)` per bucket, then summed
* **Cube model:** `gold_fct_daily_pnl` → view `canonical_pnl`
* **Cube measure:** `canonical_pnl.net_profit`
* **Cube SQL:** `sum({CUBE}.net_revenue_excl_tax) - sum({CUBE}.net_cogs) - {total_ad_spend}` — `gold_fct_daily_pnl.yml:458-461`
* **Agent usage:** `catalogue/metrics/net_profit.yaml` → `canonical_pnl.net_profit`
* **Status:** `Mismatch`
* **Confirmed difference:** The **formula shape is identical**. The **inputs are not**: `net_revenue_excl_tax` additionally subtracts `adjustment_refund_excl_gst`, and both `net_revenue_excl_tax` and `net_cogs` use different Amazon and Shopify bases (see `Net Sales` and `Net COGS` below). Net Profit inherits every one of those deltas.

---

### `Net Sales`

* **Dashboard label:** `Net Sales` — `DashboardWithDateRange.jsx:297`
* **Gold query:** `lineItemHistoricalSql.js:597-601`
* **Gold tables and fields:**
  * `fct_orders` (via `orders_dedup_inline`, `lineItemHistoricalSql.js:136-159`): `gross_revenue`, `gross_revenue_excl_tax`, `net_revenue`, `net_revenue_excl_tax`, `total_discounts`, `total_tax`, `is_test`, `is_revenue_adjustment`, `order_date`
  * `fct_order_items`: `returned_revenue_excl_gst`, `cancelled_revenue_excl_gst`, `net_pre_refund_excl_gst`, `discount_excl_gst`, `returned_at`, `cancelled_at`, `voided_at`, `pnl_refund_class`
  * `fct_amazon_sp_orders` + `fct_amazon_sp_order_pnl`
* **Formula:**
  ```
  (por.gross_sales − re.returned_revenue_excl − ca.cancelled_revenue_excl − por.discounts)
    + amzd.amazon_net_revenue
  ```
  where (`lineItemHistoricalSql.js:162-193`)
  ```
  por.gross_sales = sum( GROSS_EXCL_TAX_O(od) + DISCOUNT_EXCL_TAX_O(od) )
  por.discounts   = sum( DISCOUNT_EXCL_TAX_O(od) )
  ```
  and (`historicalQueryHelpers.js:27-36`)
  ```
  GROSS_EXCL_TAX_O   = if(net_revenue > 0,
                          gross_revenue − (gross_revenue * (net_revenue − net_revenue_excl_tax) / net_revenue),
                          gross_revenue_excl_tax)
  DISCOUNT_EXCL_TAX_O= if(total_tax > 0 AND gross_revenue > 0,
                          total_discounts * ((gross_revenue − total_tax) / gross_revenue),
                          total_discounts)
  ```
* **Aggregation:** `sum` per day, summed across buckets
* **Filters and joins:** `is_test = 0 AND is_revenue_adjustment = 0` on the order CTE; `is_gift_card = 0` on line items; `LEFT JOIN` from a date spine to `placement_order_revenue`, `cancelled`, `returned`, `amazon_daily`
* **Date logic:** placement on `od.order_date`; returns on `coalesce(returned_at, refunded_at-fallback)` in IST; cancels on `coalesce(cancelled_at, voided_at)` in IST
* **Null/zero handling:** every join arm wrapped in `coalesce(..., 0)`
* **Rounding:** `round(r.net_sales, 2)` — `lineItemHistoricalSql.js:678`
* **Cube model:** `gold_fct_daily_pnl`
* **Cube measure:** `canonical_pnl.net_revenue_excl_tax`
* **Cube SQL:** `gold_fct_daily_pnl.yml:127-129`
  ```
  net_sales_excl_tax_mgmt_with_adj + amazon_gross_revenue + amazon_refunds
  ```
  where (`int_finance_daily_rollups.sql:360-366`)
  ```
  net_sales_excl_tax_mgmt_with_adj =
      gross_sales_excl_tax
    − discounts_excl_gst
    − cancelled_revenue_excl_tax
    − returns_excl_tax
    − adjustment_refund_excl_gst
  ```
* **Agent usage:** `catalogue/metrics/net_revenue.yaml` → `canonical_pnl.net_revenue_excl_tax`
* **Status:** `Mismatch`
* **Confirmed difference:**
  1. **Cube subtracts `adjustment_refund_excl_gst`; the dashboard does not.** Gold rollup defines it as refunds with `pnl_refund_class = 'ADJUSTMENT'` on the `refunded_date` axis (`int_finance_daily_rollups.sql:225-237`). No term in `lineItemHistoricalSql.js:597-601` corresponds to it.
  2. **Gross base grain.** Dashboard: order-level `fct_orders` with proportional GST strip. Cube: `sum(net_pre_refund_excl_gst)` at line level filtered on `is_placement_gross_eligible` (`int_finance_daily_rollups.sql:38-40`).
  3. **Return/cancel deduction.** Dashboard uses a fallback expression — `if(returned_revenue_excl_gst > 0, returned_revenue_excl_gst, net_pre_refund_excl_gst + discount_excl_gst)` (`lineItemHistoricalSql.js:59-69`). Gold rollup sums `returned_revenue_excl_gst` / `cancelled_revenue_excl_gst` with **no fallback** (`int_finance_daily_rollups.sql:184, 198`).
  4. **Amazon net revenue.** Dashboard: active SP orders only (`order_status NOT IN ('cancelled','canceled')`), refunds via the coalesce chain `effective_refunds → estimated_refunds → −abs(total_refund_amount) → −abs(refund_principal)` (`amazonSpOrderTotals.js:303-321`). Cube: `payout_basis != 'NONE'`, refunds = `sum(total_refund_amount)` (`int_finance_daily_rollups.sql:137-139`).

---

### `Total Ad Spend`

* **Dashboard label:** `Total Ad Spend` — `DashboardWithDateRange.jsx:307`
* **Gold query:** `historicalQueryHelpers.js:348-411` (`fetchTotalAdSpend`), consumed at `analyticsClickhouse.js:467`
* **Gold tables and fields:**
  * multi-day: `fct_meta_ads_daily.spend`, `fct_google_ads_daily.spend`
  * single-day: `fct_meta_ads_hourly.spend`, `fct_google_campaigns_hourly.spend` (`historicalQueryHelpers.js:352-374`)
  * Amazon: `fct_amazon_ads_campaigns_daily.cost` (`amazonHistoricalHelpers.js:354`)
* **Formula:** `metaSpend + googleSpend + amazonTotal` — `historicalQueryHelpers.js:408`
* **Aggregation:** `sum(toFloat64(spend))` / `sum(toFloat64(cost))`
* **Filters:** `brand_id`, `report_date BETWEEN startDate AND endDate`
* **Date logic:** `report_date` (no timezone conversion — the ads facts are already report-date keyed)
* **Null/zero handling:** `coalesce(sum(...), 0)`
* **Cube model:** `gold_fct_daily_pnl`
* **Cube measure:** `canonical_pnl.total_ad_spend`
* **Cube SQL:** `meta_spend + google_spend + amazon_spend` — `gold_fct_daily_pnl.yml:385-388`; source CTE `gold_fct_daily_pnl.yml:86-100`:
  * meta: `gold.fct_meta_ads_daily.spend`
  * google: `gold.fct_google_ads_daily.spend`
  * amazon: `gold.fct_amazon_ads_campaigns_daily` → **`coalesce(spend, cost)`**
* **Agent usage:** `catalogue/metrics/total_ad_spend.yaml` → `canonical_pnl.total_ad_spend`
* **Status:** `Mismatch`
* **Confirmed difference:**
  1. **Amazon field.** Dashboard reads `cost`. Cube reads `coalesce(spend, cost)` (`gold_fct_daily_pnl.yml:97`). These agree only where `spend` is NULL; where `spend` is populated and differs from `cost`, the two diverge.
  2. **Single-day source.** For `startDate == endDate` the dashboard sums the **hourly** facts (`fct_meta_ads_hourly`, `fct_google_campaigns_hourly`); the Cube always sums the **daily** facts. Any hourly/daily reconciliation gap surfaces only on single-day ranges.

---

### `Net COGS`

* **Dashboard label:** `Net COGS` — `DashboardWithDateRange.jsx:317` (card key `totalCOGS`)
* **Gold query:** `lineItemHistoricalSql.js:623-628` (`net_cogs`), consumed at `analyticsClickhouse.js:465`
* **Gold tables and fields:** `fct_order_items` — `total_cost`, `placed_shipping_cost`, `placed_packaging_cost`, `placed_gateway_fee`, `rto_cost`, `gross_cogs`, `pnl_refund_class`, `is_placement_gross_eligible`, `is_gift_card`; plus `amazon_daily` from `fct_amazon_sp_orders`/`fct_amazon_sp_order_pnl`
* **Formula:**
  ```
    pl.product_cost + pl.shipping_cost + pl.packaging_cost + pl.payment_gateway_fees
  + cc.cancel_gateway_fees
  + rc.return_rto_cost + rc.return_shipping_cost + rc.return_packaging_cost + rc.return_gateway_fees
  + amzd.amazon_net_cogs
  ```
  ACTIVE arm (`lineItemHistoricalSql.js:119-122`) — all with `pnl_refund_class = 'ACTIVE'`:
  ```
  product_cost         = sumIf(total_cost)
  shipping_cost        = sumIf(coalesce(placed_shipping_cost, 0))
  packaging_cost       = sumIf(coalesce(placed_packaging_cost, 0))
  payment_gateway_fees = sumIf(coalesce(placed_gateway_fee, 0), ... AND onlinePaymentFilter)
  ```
  Amazon arm (`amazonSpOrderTotals.js:420`): `amazon_net_cogs = sum(platform_fees + product_cost)` over **active** SP orders.
* **Aggregation:** additive
* **Filters:** `is_gift_card = 0`; ACTIVE arm also `is_placement_gross_eligible = 1`; gateway fees only for online payments
* **Date logic:** ACTIVE arm on `created_at` (IST); cancel arm on `coalesce(cancelled_at, voided_at)` (IST); return arm on `coalesce(returned_at, refunded_at-fallback)` (IST)
* **Rounding:** `round(r.net_cogs, 2)` — `lineItemHistoricalSql.js:681`
* **Cube model:** `gold_fct_daily_pnl`
* **Cube measure:** `canonical_pnl.net_cogs` (alias `total_cogs`, `total_operating_cost`)
* **Cube SQL:** `gold_fct_daily_pnl.yml:152` → `toFloat64(coalesce(f.net_cogs_by_axis, 0))`, where (`int_finance_daily_rollups.sql:324-331`)
  ```
  net_cogs_by_axis =
      gross_cogs_all_placed
    + cogs_cancelled
    + cogs_returned
    + amazon_product_cost_net
    + amazon_platform_fees
    − amazon_return_platform_fees
    + amazon_return_net_payout
  ```
* **Agent usage:** `catalogue/metrics/total_cogs.yaml` → `canonical_pnl.net_cogs`
* **Status:** `Mismatch`
* **Confirmed difference:**
  1. **ACTIVE arm.** Dashboard sums four component columns (`total_cost` + `placed_shipping_cost` + `placed_packaging_cost` + online `placed_gateway_fee`). Gold rollup uses the **precomputed `gross_cogs` column**, additionally filtered on `is_cost_set AND NOT is_revenue_adjustment` (`int_finance_daily_rollups.sql:70-72`). The dashboard applies **no `is_cost_set` and no `is_revenue_adjustment` filter** on this arm.
  2. **Amazon arm.** Dashboard: `product_cost + platform_fees` for **active** SP orders. Cube: `amazon_product_cost_net` (excludes both `CANCELLATION` **and** `RETURN` statuses, `int_finance_daily_rollups.sql:121-123`) `+ amazon_platform_fees − amazon_return_platform_fees + amazon_return_net_payout`. The Cube carries two Amazon return-adjustment terms that have **no counterpart** in the dashboard.
  3. Note: the Cube exposes `product_cost`, `packaging_cost`, `shipping_cost`, `payment_gateway_fees`, `rto_cost` from its own `li_costs` CTE (`gold_fct_daily_pnl.yml:33-78`), which **does** mirror the dashboard's arm structure — but the headline `net_cogs` measure does **not** use `li_costs`; it uses `net_cogs_by_axis`. The components and the total therefore come from different code paths.

---

### `Discounts`

* **Dashboard label:** `Discounts` — `DashboardWithDateRange.jsx:327`
* **Gold query:** `analyticsClickhouse.js:187-203` (`getDiscounts`), consumed at `analyticsClickhouse.js:464`
* **Gold tables and fields:** `fct_orders` (deduped) — `total_discounts`, `total_tax`, `gross_revenue`, `is_test`, `is_revenue_adjustment`
* **Formula:** `DISCOUNT_EXCL_TAX_SUM` (`historicalQueryHelpers.js:62-63`)
  ```
  sumIf(
    if(total_tax > 0 AND gross_revenue > 0,
       total_discounts * ((gross_revenue − total_tax) / gross_revenue),
       total_discounts),
    coalesce(is_revenue_adjustment, 0) = 0
  )
  ```
* **Aggregation:** `sumIf`
* **Filters:** `order_date BETWEEN startDate AND endDate`, `is_test = 0` (ORDER_BASE_FILTER), `is_revenue_adjustment = 0` inside the `sumIf`
* **Date logic:** placement `order_date`
* **Null/zero handling:** `coalesce(..., 0)` on every field; `coalesce(row, 0)` on the result
* **Cube model:** `gold_fct_daily_pnl`
* **Cube measure:** `canonical_pnl.total_discounts_excl_tax` — **exists but has no catalogue metric**
* **Cube SQL:** `gold_fct_daily_pnl.yml:122` → `toFloat64(coalesce(f.discounts_excl_gst, 0))`, where `discounts_excl_gst = sum(CASE WHEN is_placement_gross_eligible THEN discount_excl_gst ELSE 0 END)` (`int_finance_daily_rollups.sql:41-43`)
* **Agent usage:** **none** — no file in `catalogue/metrics/` maps to this measure
* **Status:** `Missing`
* **Confirmed difference:** Two separate problems. (a) The agent **cannot query Discounts at all** — no catalogue metric exists, so `query_planner.py:244` can never emit `canonical_pnl.total_discounts_excl_tax`. (b) Even if exposed, the definitions differ: the dashboard computes a **proportional GST strip on order-level** `total_discounts`; the Cube sums a **line-level** `discount_excl_gst` column gated on `is_placement_gross_eligible`.

---

### `Gross Sales`

* **Dashboard label:** `Gross Sales` — `DashboardWithDateRange.jsx:337`
* **Gold query:** `lineItemHistoricalSql.js:586`, consumed at `analyticsClickhouse.js:461`
* **Gold tables and fields:** `fct_orders` (deduped) + `amazon_daily`
* **Formula:** `por.gross_sales + amzd.amazon_gross_revenue`, where
  `por.gross_sales = sum( GROSS_EXCL_TAX_O + DISCOUNT_EXCL_TAX_O )` (pre-discount, excl. GST, **including** cancelled and voided placement orders) — `lineItemHistoricalSql.js:165, 183`
* **Aggregation:** `sum`
* **Filters:** `is_test = 0 AND is_revenue_adjustment = 0`
* **Date logic:** placement `order_date`
* **Rounding:** `round(r.gross_sales, 2)` — `lineItemHistoricalSql.js:669`
* **Cube model:** `gold_fct_daily_pnl`
* **Cube measure:** `canonical_pnl.gross_sales_excl_tax` — **exists but has no catalogue metric**
* **Cube SQL:** `gold_fct_daily_pnl.yml:120-121` → `gross_sales_excl_tax + amazon_gross_revenue`, where `gross_sales_excl_tax = sum(CASE WHEN is_placement_gross_eligible THEN net_pre_refund_excl_gst ELSE 0 END)` (`int_finance_daily_rollups.sql:38-40`)
* **Agent usage:** **none**
* **Status:** `Missing`
* **Confirmed difference:** (a) No catalogue metric → unreachable by the agent. (b) Shopify component grain differs (order-level derived vs line-level `net_pre_refund_excl_gst`). (c) Amazon component: dashboard `amzd.amazon_gross_revenue` = `sum(effective_gross_revenue)` for **active** SP orders (`amazonSpOrderTotals.js:367, 419`); Cube `f.amazon_gross_revenue` = `sum(effective_gross_revenue)` where **`payout_basis != 'NONE'`** (`int_finance_daily_rollups.sql:134-136`).

---

### `Total Sales`

* **Dashboard label:** `Total Sales` — `DashboardWithDateRange.jsx:347`
* **Gold query:** `lineItemHistoricalSql.js:585`, consumed at `analyticsClickhouse.js:460`
* **Gold tables and fields:** `fct_orders.gross_revenue`, `fct_orders.total_discounts`; `fct_amazon_sp_orders.order_total`
* **Formula:** `por.total_sales + amzd.amazon_total_sales`, where
  * `por.total_sales = sum( gross_revenue + total_discounts )` — pre-discount total **incl. GST** (`lineItemHistoricalSql.js:166-167, 182`)
  * `amzd.amazon_total_sales = sum(order_total)` over active SP orders (`amazonSpOrderTotals.js:418`)
* **Aggregation:** `sum`
* **Filters:** `is_test = 0 AND is_revenue_adjustment = 0`
* **Date logic:** placement `order_date`
* **Rounding:** `round(r.total_sales, 2)` — `lineItemHistoricalSql.js:668`
* **Cube model:** `gold_fct_daily_pnl`
* **Cube measure:** `canonical_pnl.total_sales_incl_tax` — **exists but has no catalogue metric**
* **Cube SQL:** `gold_fct_daily_pnl.yml:133-134` → `catalog_gross_incl_gst + amazon_gross_revenue`
* **Agent usage:** **none**
* **Status:** `Missing`
* **Confirmed difference:** (a) No catalogue metric → unreachable by the agent. (b) **Amazon component uses a different table and column**: dashboard = `fct_amazon_sp_orders.order_total`; Cube = `fct_amazon_sp_order_pnl.effective_gross_revenue`. These are different quantities (order total vs P&L effective gross revenue), not two names for one field.

---

### `Total Orders`

* **Dashboard label:** `Total Orders` — `DashboardWithDateRange.jsx:357`
* **Gold query:** `analyticsClickhouse.js:471-475`
  ```js
  const amazonOrderCount   = parseInt(amazonSales.active_order_count ?? amazonSales.orders ?? 0, 10);
  const lineItemAmazonOrders = parseInt(lineItemTotalsResolved.amazon_orders || 0, 10);
  const shopifyOrders = parseInt(lineItemTotalsResolved.total_orders || 0, 10) - lineItemAmazonOrders;
  const totalOrders   = shopifyOrders + amazonOrderCount;
  ```
  `shopifyOrders` resolves to `por.total_orders` = `count()` over `orders_dedup_inline` (`lineItemHistoricalSql.js:181, 603`)
* **Gold tables and fields:** `fct_orders` (`order_id`, `order_date`, `is_test`, `is_revenue_adjustment`); `fct_amazon_sp_orders.order_status`
* **Formula:** `count(fct_orders rows)` + `count(active Amazon SP orders)`
* **Aggregation:** `count()` (one row per order after `argMax` dedup by `_loaded_at`)
* **Filters:** `is_test = 0 AND is_revenue_adjustment = 0`; Amazon `order_status NOT IN ('cancelled','canceled')`. **Cancelled and voided Shopify orders ARE counted.**
* **Date logic:** placement `order_date`
* **Cube model:** `gold_fct_daily_pnl` (`canonical_pnl.total_orders`) / `gold_fct_orders` (`commerce_orders.orders`)
* **Cube measure (agent actually uses):** `commerce_orders.orders`
* **Cube SQL:** `gold_fct_orders.yml:27-29`
  ```
  sql: CASE WHEN {CUBE}.is_test = 0 THEN {CUBE}.order_id END
  type: count_distinct
  ```
  The nearest Cube equivalent, `canonical_pnl.total_orders` (`gold_fct_daily_pnl.yml:507-509`), is `total_orders + amazon_orders` = `gmv_orders + amazon_orders`, where `gmv_orders = count(DISTINCT CASE WHEN is_placement_gross_eligible THEN order_id END)` (`int_finance_daily_rollups.sql:25-26`) and `amazon_orders = count(DISTINCT CASE WHEN pnl_refund_status != 'CANCELLATION' THEN amazon_order_id END)` from `fct_amazon_order_items` (`int_finance_daily_rollups.sql:116-117`).
* **Agent usage:** `catalogue/metrics/orders.yaml` → **`commerce_orders.orders`**
* **Status:** `Mismatch`
* **Confirmed difference:**
  1. **The agent is bound to the wrong measure.** `orders.yaml` maps to `commerce_orders.orders`, which filters **only** `is_test = 0`. The dashboard additionally excludes `is_revenue_adjustment = 1` and **adds Amazon orders**. `commerce_orders.orders` is therefore Shopify-only and includes revenue-adjustment orders.
  2. Even `canonical_pnl.total_orders` (which the agent does not use) does not match: its Shopify leg is `count(DISTINCT order_id)` at **line grain** gated on `is_placement_gross_eligible`, not `count()` of order rows; its Amazon leg counts `fct_amazon_order_items` by `pnl_refund_status != 'CANCELLATION'`, not `fct_amazon_sp_orders` by `order_status`.

---

### `Returns / Cancels`

* **Dashboard label:** `Returns / Cancels` — `DashboardWithDateRange.jsx:367`
* **Gold query:** `lineItemHistoricalSql.js:930-953` (`fetchPlacementReturnsCancels`) → `buildEventDateReturnsTotalsSql()` at `:974-1010`; card math `buildDashboardStats.js:294-304` → `refunded + cancelled`
* **Gold tables and fields:** `fct_order_items` — `order_id`, `pnl_refund_class`, `returned_at`, `refunded_at`, `refunded_quantity`, `return_status`, `cancelled_at`, `voided_at`, `order_status`, `is_gift_card`; plus Amazon SP returns/cancels (`fetchAmazonSpReturnsCancels`)
* **Formula:**
  ```
  cancelled_orders = uniqExactIf(order_id, CANCEL_BUCKET_LINE_FILTER AND cancel_event IS NOT NULL AND cancel_event_date IN range)
  returned_orders  = uniqExactIf(order_id, RETURN_BUCKET_LINE_FILTER AND return_event IS NOT NULL AND return_event_date IN range)
  card value       = cancelled_orders + returned_orders   (Shopify merged with Amazon)
  ```
  where `CANCEL_EVENT_OI = coalesce(cancelled_at, if(order_status = 'voided', voided_at, NULL))` (`lineItemHistoricalSql.js:37`) and `RETURN_EVENT_OI = coalesce(returned_at, if(order_status IN ('refunded','partially_refunded') AND return_status = 'NO_RETURN' AND refunded_quantity > 0, refunded_at, NULL))` (`lineItemHistoricalSql.js:42-51`)
* **Aggregation:** `uniqExactIf` (distinct orders)
* **Filters:** `is_gift_card = 0`; bucket membership by `pnl_refund_class` (voided reclassified as **cancellation**)
* **Date logic:** **event date in IST**, not placement date
* **Cube model:** `gold_fct_daily_pnl` / `gold_fct_orders`
* **Cube measure (agent uses):** `commerce_orders.cancelled_orders`, `commerce_orders.refunded_orders`
* **Cube SQL:** `gold_fct_orders.yml:96-104`
  ```
  cancelled_orders: CASE WHEN {CUBE}.order_status = 'cancelled' AND {CUBE}.is_test = 0 THEN {CUBE}.order_id END   (count_distinct)
  refunded_orders : CASE WHEN {CUBE}.order_status IN ('refunded','partially_refunded') ... THEN {CUBE}.order_id END (count_distinct)
  ```
  `canonical_pnl` also exposes `cancelled_orders` / `returned_orders` from `int_finance_daily_rollups.sql:183, 197` (event-date, Shopify only) — but no catalogue metric points at them, and there is **no combined Returns/Cancels measure anywhere in Cube**.
* **Agent usage:** `catalogue/metrics/cancelled_orders.yaml`, `catalogue/metrics/refunded_orders.yaml` → `commerce_orders.*`
* **Status:** `Mismatch`
* **Confirmed difference:**
  1. **Axis.** Dashboard counts orders on the **return/cancel event date**. `commerce_orders.cancelled_orders` / `refunded_orders` count orders on the **placement date** (`order_date`) by current `order_status`. These answer different questions and will not agree for any range.
  2. **Classification.** Dashboard buckets by line-level `pnl_refund_class` and explicitly reclassifies `voided` as a cancellation. The Cube measures key off order-level `order_status` only.
  3. **Amazon excluded** from both Cube measures; included in the dashboard card.
  4. No Cube measure sums cancels + returns; the agent would have to add two measures, which `query_planner.py` supports only if both are on the same view.

---

### `Return / Cancel Rev`

* **Dashboard label:** `Return / Cancel Rev` — `DashboardWithDateRange.jsx:377` (card key `cancellations`)
* **Gold query:** `buildEventDateReturnsTotalsSql()` `event_amounts` CTE — `lineItemHistoricalSql.js:1000-1010`; card math `buildDashboardStats.js:305-320` → `-(returnedAmount + cancelledAmount)`
* **Gold tables and fields:** `fct_order_items` — `returned_revenue_excl_gst`, `cancelled_revenue_excl_gst`, `net_pre_refund_excl_gst`, `discount_excl_gst`
* **Formula:** `sumIf(RETURN_DEDUCTION_EXCL_OI, …) + sumIf(CANCEL_DEDUCTION_EXCL_OI, …)`, where (`lineItemHistoricalSql.js:55-69`)
  ```
  PLACEMENT_GROSS_EXCL_OI   = net_pre_refund_excl_gst + discount_excl_gst
  RETURN_DEDUCTION_EXCL_OI  = if(returned_revenue_excl_gst  > 0, returned_revenue_excl_gst,  PLACEMENT_GROSS_EXCL_OI)
  CANCEL_DEDUCTION_EXCL_OI  = if(cancelled_revenue_excl_gst > 0, cancelled_revenue_excl_gst, PLACEMENT_GROSS_EXCL_OI)
  ```
* **Aggregation:** `sumIf`; displayed negated, excl. GST (`amountsExclGst: true`)
* **Date logic:** event date, IST
* **Cube model:** `gold_fct_daily_pnl`
* **Cube measure:** `canonical_pnl.returns_excl_tax`, `canonical_pnl.cancelled_revenue_excl_tax` — **exist but have no catalogue metric**
* **Cube SQL:** `gold_fct_daily_pnl.yml:137, 139` → `f.returns_excl_tax`, `f.cancelled_revenue_excl_tax`; sourced as plain `sum(returned_revenue_excl_gst)` / `sum(cancelled_revenue_excl_gst)` (`int_finance_daily_rollups.sql:184, 198`)
* **Agent usage:** **none**
* **Status:** `Missing`
* **Confirmed difference:** (a) No catalogue metric → unreachable by the agent. (b) The Gold rollup has **no fallback branch**: where `returned_revenue_excl_gst = 0`, the dashboard substitutes `net_pre_refund_excl_gst + discount_excl_gst` and the Cube contributes `0`. (c) Amazon returns/cancels are merged into the dashboard card and absent from the Cube measures.

---

### `Gross ROAS`

* **Dashboard label:** `Gross ROAS` — `DashboardWithDateRange.jsx:387`
* **Gold query:** computed in the frontend — `buildDashboardStats.js:140` → `safeDiv(grossSales, adSpend)`
* **Formula:** `gross_sales / total_ad_spend`
* **Aggregation:** ratio of two period totals (never an average of daily ratios)
* **Null/zero handling:** `safeDiv` returns `null` when `adSpend === 0`; card renders `"0x"` (`buildDashboardStats.js:14-16, 322`)
* **Rounding:** `toFixed(2)` + `"x"` suffix
* **Cube model:** `gold_fct_daily_pnl`
* **Cube measure:** `canonical_pnl.gross_roas` — **exists but has no catalogue metric**
* **Cube SQL:** `sum({CUBE}.gross_sales_excl_tax) / nullIf({total_ad_spend}, 0)` — `gold_fct_daily_pnl.yml:473-476`
* **Agent usage:** **none**
* **Status:** `Missing`
* **Confirmed difference:** No catalogue metric → unreachable by the agent. The **formula shape matches** (gross sales ex-GST ÷ ad spend, guarded against divide-by-zero); the numerator and denominator inherit the `Gross Sales` and `Total Ad Spend` differences above.

---

### `Net ROAS`

* **Dashboard label:** `Net ROAS` — `DashboardWithDateRange.jsx:397`
* **Gold query:** frontend — `buildDashboardStats.js:142` → `safeDiv(netSales - cogs, adSpend)`
* **Formula:** `(net_sales − net_cogs) / total_ad_spend`
* **Aggregation:** ratio of period totals
* **Null/zero handling:** `null` when `adSpend === 0` → `"0x"`
* **Cube model:** `gold_fct_daily_pnl`
* **Cube measure:** `canonical_pnl.net_roas` — **exists but has no catalogue metric**
* **Cube SQL:** `({gross_profit}) / nullIf({total_ad_spend}, 0)` — `gold_fct_daily_pnl.yml:477-480`, where `gross_profit = sum(net_revenue_excl_tax) − sum(net_cogs)`
* **Agent usage:** **none**
* **Status:** `Missing`
* **Confirmed difference:** No catalogue metric → unreachable by the agent. The **formula shape matches** — Cube's `net_roas` expands to `(net_revenue_excl_tax − net_cogs) / total_ad_spend`, which is the dashboard's `(netSales − cogs) / adSpend`. Inputs inherit the `Net Sales` / `Net COGS` differences.

---

### `BE ROAS`

* **Dashboard label:** `BE ROAS` — `DashboardWithDateRange.jsx:407`
* **Gold query:** frontend — `buildDashboardStats.js:144-146`
  ```js
  const totalCosts = cogs + adSpend;
  const beRoas = safeDiv(totalCosts, adSpend);
  ```
* **Formula:** `(net_cogs + total_ad_spend) / total_ad_spend`
* **Aggregation:** ratio of period totals
* **Null/zero handling:** `null` when `adSpend === 0` → `"0x"`
* **Cube model:** `gold_fct_daily_pnl`
* **Cube measure:** `canonical_pnl.be_roas` — **exists but has no catalogue metric**
* **Cube SQL:** `(sum({CUBE}.net_cogs) + {total_ad_spend}) / nullIf({total_ad_spend}, 0)` — `gold_fct_daily_pnl.yml:481-484`
* **Agent usage:** **none**
* **Status:** `Missing`
* **Confirmed difference:** No catalogue metric → unreachable by the agent. The **formula matches exactly** — this is the one card whose Cube expression is a literal transcription of the frontend math.
* **Unverified / internal inconsistency (dashboard side):** `lineItemHistoricalSql.js:700` defines a **different** `be_roas` in SQL — `round(r.net_sales / nullIf(r.net_sales - r.net_cogs, 0.0), 4)`. That column is **not** what the BE ROAS card renders (the frontend recomputes from totals at `buildDashboardStats.js:144-146`). The Cube matches the **card**, not the SQL column. Flagging because any consumer reading `be_roas` straight from the Gold SQL will disagree with both the card and the Cube.

---

### `Total payments`

* **Dashboard label:** `Total payments` — `DashboardWithDateRange.jsx:417`
* **Gold query:** `analyticsClickhouse.js:479-496` — sums `payment_method_breakdown` counts across line-item buckets; buckets built by `buildPaymentBreakdownCte` (`lineItemHistoricalSql.js:424-467`)
* **Gold tables and fields:** `fct_orders` — `order_id`, `payment_method`, `payment_gateway`, `is_cod`, `order_created_at`, `is_test`, `is_revenue_adjustment`, `is_draft_order`
* **Formula:** `countDistinctIf(order_id, payment_bucket = …)` for four buckets, where
  ```
  payment_bucket = multiIf(
    lower(coalesce(nullIf(payment_method,''), payment_gateway,'')) LIKE '%paytm card machine%', 'paytm card machine',
    lower(...) = 'manual', 'manual',
    is_cod = 1 OR lower(...) IN ('cod','cash') OR lower(...) LIKE '%cash on delivery%' OR lower(...) LIKE '%(cod)%', 'cod',
    'online')
  ```
* **Aggregation:** `countDistinctIf`; card value = sum of the four bucket counts
* **Filters:** `is_test = 0 AND is_revenue_adjustment = 0 AND is_draft_order = 0`
* **Date logic:** `toDate(toTimeZone(order_created_at, 'Asia/Kolkata'))`
* **Cube model:** `gold_fct_orders` / `gold_fct_daily_pnl`
* **Cube measure:** `commerce_orders.cod_orders`, `commerce_orders.prepaid_orders`
* **Cube SQL:** `gold_fct_orders.yml:130-137`
  ```
  cod_orders    : CASE WHEN {CUBE}.is_cod = 1 AND {CUBE}.is_test = 0 THEN {CUBE}.order_id END  (count_distinct)
  prepaid_orders: CASE WHEN {CUBE}.is_cod = 0 AND {CUBE}.is_test = 0 AND {CUBE}.order_status … (count_distinct)
  ```
* **Agent usage:** `catalogue/metrics/cod_orders.yaml`, `catalogue/metrics/prepaid_orders.yaml` → `commerce_orders.*`
* **Status:** `Mismatch`
* **Confirmed difference:**
  1. **Bucket cardinality.** Dashboard splits payments **four ways** (`online`, `cod`, `paytm card machine`, `manual`) using a `multiIf` over `payment_method`/`payment_gateway` strings. The Cube splits **two ways** on `is_cod` alone. `paytm card machine` and `manual` orders have no Cube representation and are folded into `prepaid_orders`.
  2. **COD detection.** Dashboard treats an order as COD if `is_cod = 1` **OR** the payment string matches `'cod' | 'cash' | '%cash on delivery%' | '%(cod)%'`. The Cube uses `is_cod = 1` only.
  3. **Filters.** Dashboard excludes `is_revenue_adjustment = 1` and `is_draft_order = 1`; `commerce_orders.cod_orders` excludes neither.
  4. **Date axis.** Dashboard keys on `order_created_at` converted to IST; the Cube dimension is `order_date`.

---

## Agent metrics on `canonical_pnl` with no dashboard card

### `Gross Profit`

* **Dashboard label:** *(no card on the Reports dashboard)*. The Gold backend nonetheless returns `gross_profit`.
* **Gold query:** `analyticsClickhouse.js:468` → `grossProfit = grossSales - totalAdSpend - grossCogs`; SQL form `lineItemHistoricalSql.js:696` → `round(r.gross_sales - r.gross_cogs - r.total_ad_spend, 2)`
* **Gold tables and fields:** as per `Gross Sales`, `Total Ad Spend`, plus `gross_cogs` (`lineItemHistoricalSql.js:618-621`)
* **Formula:** `gross_sales − gross_cogs − total_ad_spend`
* **Cube model:** `gold_fct_daily_pnl`
* **Cube measure:** `canonical_pnl.gross_profit`
* **Cube SQL:** `sum({CUBE}.net_revenue_excl_tax) - sum({CUBE}.net_cogs)` — `gold_fct_daily_pnl.yml:435-439`
* **Agent usage:** `catalogue/metrics/gross_profit.yaml` → `canonical_pnl.gross_profit`; `formula.human_readable: "Net Revenue (ex-GST) - Net COGS"`
* **Status:** `Mismatch`
* **Confirmed difference:** **The two definitions share no term.** Gold: `gross_sales − gross_cogs − total_ad_spend` (gross revenue basis, gross COGS basis, ad spend **subtracted**). Cube: `net_revenue_excl_tax − net_cogs` (net revenue basis, net COGS basis, ad spend **not** subtracted). The Cube's `gross_profit` is what the Gold engine would call *contribution before marketing*; the Gold engine's `gross_profit` is a different, ad-spend-inclusive figure. An agent answering "what was gross profit?" will return a number that the dashboard's own backend contradicts.

### `MER` / `Blended ROAS` / `Contribution Margin`

* **Dashboard label:** *(no card)*
* **Cube measures:** `canonical_pnl.mer` = `sum(net_revenue_excl_tax) / nullIf(total_ad_spend, 0)` (`gold_fct_daily_pnl.yml:469-472`); `canonical_pnl.blended_roas` — identical expression (`:485-488`); `canonical_pnl.contribution_margin` = `sum(net_revenue_excl_tax) − sum(product_cost) − total_ad_spend` (`:444-448`)
* **Agent usage:** `catalogue/metrics/mer.yaml`, `blended_roas.yaml`, `contribution_margin.yaml`
* **Status:** `Unverified`
* **Confirmed difference:** No Gold dashboard query computes MER, blended ROAS or contribution margin — there is nothing to compare against. Their **inputs** (`net_revenue_excl_tax`, `total_ad_spend`, `product_cost`) carry the differences documented above, so they cannot be assumed to reconcile with any dashboard figure.

---

## Summary

| # | Dashboard card | Cube measure | Agent metric id | Status |
|---|---|---|---|---|
| 1 | Net Profit | `canonical_pnl.net_profit` | `net_profit` | `Mismatch` |
| 2 | Net Sales | `canonical_pnl.net_revenue_excl_tax` | `net_revenue` | `Mismatch` |
| 3 | Total Ad Spend | `canonical_pnl.total_ad_spend` | `total_ad_spend` | `Mismatch` |
| 4 | Net COGS | `canonical_pnl.net_cogs` | `total_cogs` | `Mismatch` |
| 5 | Discounts | `canonical_pnl.total_discounts_excl_tax` | — | `Missing` |
| 6 | Gross Sales | `canonical_pnl.gross_sales_excl_tax` | — | `Missing` |
| 7 | Total Sales | `canonical_pnl.total_sales_incl_tax` | — | `Missing` |
| 8 | Total Orders | `commerce_orders.orders` | `orders` | `Mismatch` |
| 9 | Returns / Cancels | `commerce_orders.cancelled_orders` + `refunded_orders` | `cancelled_orders`, `refunded_orders` | `Mismatch` |
| 10 | Return / Cancel Rev | `canonical_pnl.returns_excl_tax` + `cancelled_revenue_excl_tax` | — | `Missing` |
| 11 | Gross ROAS | `canonical_pnl.gross_roas` | — | `Missing` |
| 12 | Net ROAS | `canonical_pnl.net_roas` | — | `Missing` |
| 13 | BE ROAS | `canonical_pnl.be_roas` | — | `Missing` |
| 14 | Total payments | `commerce_orders.cod_orders` + `prepaid_orders` | `cod_orders`, `prepaid_orders` | `Mismatch` |
| — | *(no card)* Gross Profit | `canonical_pnl.gross_profit` | `gross_profit` | `Mismatch` |
| — | *(no card)* MER / Blended ROAS / Contribution Margin | `canonical_pnl.mer`, `.blended_roas`, `.contribution_margin` | `mer`, `blended_roas`, `contribution_margin` | `Unverified` |

**Zero of the 14 dashboard cards are a confirmed `Match`.**

* **8 cards** have a Cube measure the agent **cannot reach** (no catalogue metric): Discounts, Gross Sales, Total Sales, Return/Cancel Rev, Gross ROAS, Net ROAS, BE ROAS — plus the Total Orders card's correct measure (`canonical_pnl.total_orders`), which is bypassed in favour of `commerce_orders.orders`.
* **6 cards** the agent *can* reach return a **differently-defined number**.
* **BE ROAS** is the only metric whose Cube formula is a literal transcription of the dashboard math; it is nonetheless unreachable by the agent.
* **Gross Profit** is the most severe semantic break: the Cube and Gold definitions share no term.
