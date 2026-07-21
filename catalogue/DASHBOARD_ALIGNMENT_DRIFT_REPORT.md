# Dashboard Alignment Drift Report — Catalogue vs. Node-Backend

**Status: DRAFT FOR REVIEW — no production files modified.** This report is the
output of a full audit of all 190 metrics in `catalogue/metrics/*.yaml` (and by
extension the auto-generated `catalogue/openmetadata/metrics.yaml` crosswalk, which
mirrors `cube_mapping` without independent verification) against what
`Seleric_Dashboard/Node-Backend` actually computes and serves to the live dashboard.

## Why Node-Backend, not the Cube semantic layer

Every catalogue metric declares a `cube_mapping` pointing at `Base_Agent/cube/model/`
(a Cube.js semantic layer over ClickHouse). Per instruction, this audit treats
**Node-Backend's own calculation code as the source of truth** instead, because that
is what actually renders on the dashboard end users see. A repo-wide grep confirms
Node-Backend never queries the Cube layer (zero references to "cube" in its `src/`) —
it runs independent ClickHouse/Postgres queries in `src/integrations/*/analytics*.js`
and `src/services/*.js`. **This means the Cube semantic layer and the live dashboard
are two independently-maintained, already-diverged implementations**, and the
catalogue today documents the Cube side, not the dashboard side.

## Method

5 parallel audits, one per catalogue category grouping, each reading every metric's
`formula.human_readable` / `cube_mapping` / `aggregation` / `grain` /
`supported_dimensions` / `supported_filters`, then tracing Node-Backend to find (or
fail to find) the equivalent live calculation, comparing formula shape, filters,
grain, and scope claims. Verdicts:

- **MATCH** — dashboard computes the same thing the catalogue describes.
- **DRIFT** — something with that name/purpose exists in the dashboard, but computes
  a materially different number (different formula, filter, scope, or basis).
- **NOT_FOUND_IN_DASHBOARD** — no dashboard code computes this at all; it may be a
  Cube-only / aspirational metric, or dead/unwired code.
- **UNCLEAR** — partial evidence, needs a human call.

## Executive summary

| Category | Metrics | MATCH | DRIFT | NOT_FOUND | UNCLEAR |
|---|---|---|---|---|---|
| paid_media (+diagnostic) | 53 | 15 | 6 | 26 | 5 |
| commerce | 34 | 25 | 7 | 1 | 1 |
| finance | 28 | 10 | 12 | 4 | 2 |
| attribution | 27 | 16 | 2 | 9 | 0 |
| customer / product / web_analytics / operations | 48 | 0 | 21 | 26 | 1 |
| **Total** | **190** | **~66** | **~48** | **~66** | **~9** |

Roughly **two-thirds of the catalogue is not a clean match** to the live dashboard.
The catalogue is not randomly wrong — it looks like a well-intentioned, internally
consistent description of the **intended/Cube-layer design**, which the dashboard
implementation has since drifted away from (or, in the `customer`/`product`
categories, largely never implemented at all).

## Cross-cutting findings (fix these patterns first — they explain most of the drift)

1. **CTR is a unit mismatch across all 3 ad platforms.** `amazon_ads_ctr`,
   `google_ctr`, `meta_ctr` catalogue formula is `SUM(clicks)/SUM(impressions)`
   (`unit: ratio`). The dashboard multiplies by 100 everywhere (e.g.
   `historicalAnalytics/analyticsClickhouse.js:1015`). Every catalogued CTR's
   `validation_tests` would fail by exactly 100x against real dashboard output.

2. **Finance metrics are mislabeled "Shopify-only."** Nearly every finance metric's
   description says Amazon is excluded. In reality `pnlService.js` and
   `lineItemHistoricalSql.js` blend Amazon into `net_sales`, `net_cogs`,
   `total_ad_spend`, `net_profit`, `gross_roas`, `net_roas`, and `taxes_on_net_sales`
   on the primary `/api/v1/dashboard/summary` endpoint — confirmed by an explicit code
   comment (`pnlService.js:207`): *"Total Operating Cost == Historical Analytics 'Net
   COGS' (Shopify + Amazon)."* A second, genuinely Shopify-only implementation of some
   of the same formulas exists but only feeds the separate per-platform Attribution
   routes (`attributionPnLHelpers.js`), not the main dashboard. The catalogue picked
   the wrong one to describe for ~11 metrics.

3. **`channel_attribution` (channel_gross_revenue / channel_net_revenue /
   channel_orders) doesn't exist.** The catalogued 5-way channel split
   (meta/google/organic_shopify/amazon/organic_amazon) and its `channel_attribution_daily`
   source have zero references anywhere in Node-Backend. The nearest real endpoint
   uses a different channel definition, excludes cancelled orders (opposite of every
   other attribution metric's rule), and never merges in Amazon.

4. **`meta_breakdown_*` (10 metrics) is an aspirational Cube-only concept.** No
   `breakdown_type` gating, no single-select filter, nothing resembling this cube view
   exists in Node-Backend. The nearest real feature (`getAudienceInsights`) returns
   several breakdowns simultaneously with different dimension names and is a live
   Graph API call, not the ClickHouse-backed metric the catalogue describes.

5. **Most Meta video/engagement metrics (thruplays, hook rate, hold rate, 3s/30s
   views, cost-per-thruplay, link clicks) are simply not fetched by Node-Backend at
   all** — confirmed by grep (e.g. "thruplay" has zero occurrences in `src/`).
   `meta_reach` is explicitly hardcoded to `0` with a comment saying it needs a
   separate API call that was never added.

6. **There is no customer-master or lifetime-aggregation layer.** All 16 `customer`
   metrics assume a lifetime, all-time-history grain. Node-Backend has no customer
   table and no lifetime rollup — only two windowed/sampled Shopify REST functions
   (30/90-day defaults, one capped at 100 customers/request). None of the 16 customer
   metrics are a clean match; most (12) don't exist at all.

7. **There is no all-channel product/SKU rollup.** The only product-grain query in
   the entire backend (`buildAttributedProductPerformanceSql`) only runs inside
   single-platform attribution payloads, never as a standalone metric — and none of
   the 4 "ad spend by product" metrics exist anywhere (`pnlService.js:359` explicitly
   documents ad spend as channel-level only, no SKU dimension).

8. **Two dead-code CTEs silently produce wrong `operations` numbers.**
   `return_recovered_cogs`'s matching logic (`buildCostReversalsCte`, summing
   `fct_refund_line_items`) is built but never joined into the live query; what
   actually feeds `net_cogs` **adds** return cost rather than subtracting recovered
   cost — the opposite operation. `refund_lines`/`refund_count` have the same
   dead-CTE problem — only an order-grain count ships, never a line/event-grain count.

9. **`bounce_rate`, `funnel_purchases`, `funnel_revenue`, `funnel_conversion_rate`
   are internally inconsistent on the dashboard itself**, not just vs. the catalogue —
   e.g. bounce rate deliberately overrides the funnel-derived formula the catalogue
   describes with a native `is_bounce` flag, and the catalogue's own
   `funnel_conversion_rate == funnel_purchases / web_sessions` validation test can't
   hold because the two metrics are attributed on different bases (order-grain
   last-touch vs. session-grain).

---

## Category detail

### paid_media (53 metrics)

| id | verdict | evidence file:line | note |
|---|---|---|---|
| amazon_ads_clicks | MATCH | `historicalAnalytics/analyticsClickhouse.js:1012` | `SUM(clicks)` from `fct_amazon_ads_campaigns_daily` |
| amazon_ads_impressions | MATCH | `historicalAnalytics/analyticsClickhouse.js:1011` | `SUM(impressions)` |
| amazon_ads_spend | MATCH | `historicalAnalytics/amazonHistoricalHelpers.js:372-380` | `SUM(cost)` |
| amazon_ads_cpc | MATCH | `historicalAnalytics/analyticsClickhouse.js:1013` | `sum(cost)/sum(clicks)` |
| amazon_ads_cpm | MATCH | `historicalAnalytics/analyticsClickhouse.js:1014` | `(sum(cost)/sum(impressions))*1000` |
| amazon_ads_ctr | **DRIFT** | `historicalAnalytics/analyticsClickhouse.js:1015` | ×100 percentage vs. catalogue's bare ratio — see cross-cutting #1 |
| google_clicks | MATCH | `historicalAnalytics/analyticsClickhouse.js:898` | `SUM(clicks)` |
| google_impressions | MATCH | `historicalAnalytics/analyticsClickhouse.js:897` | `SUM(impressions)` |
| google_spend | MATCH | `historicalAnalytics/analyticsClickhouse.js:896` | `SUM(spend)` |
| google_cpc | MATCH | `historicalAnalytics/analyticsClickhouse.js:913` | `sum(spend)/sum(clicks)` |
| google_cpm | MATCH | `historicalAnalytics/analyticsClickhouse.js:914` | `(sum(spend)/sum(impressions))*1000` |
| google_ctr | **DRIFT** | `historicalAnalytics/analyticsClickhouse.js:915` | ×100 percentage — see cross-cutting #1 |
| google_interactions | NOT_FOUND | — | field never fetched anywhere |
| google_interaction_rate | NOT_FOUND | — | depends on google_interactions |
| meta_clicks | MATCH | `historicalAnalytics/analyticsClickhouse.js:763` | `SUM(clicks)` |
| meta_impressions | MATCH | `historicalAnalytics/analyticsClickhouse.js:762` | `SUM(impressions)` |
| meta_spend | MATCH | `historicalAnalytics/analyticsClickhouse.js:761` | `SUM(spend)` |
| meta_cpc | MATCH | `historicalAnalytics/analyticsClickhouse.js:778` | `sum(spend)/sum(clicks)` |
| meta_cpm | MATCH | `historicalAnalytics/analyticsClickhouse.js:779` | `(sum(spend)/sum(impressions))*1000` |
| meta_ctr | **DRIFT** | `historicalAnalytics/analyticsClickhouse.js:780` | ×100 percentage — see cross-cutting #1 |
| meta_reach | NOT_FOUND | `meta/analytics.js:322` | hardcoded to `0`, comment says "requires separate API call; not aggregated here" |
| meta_frequency | NOT_FOUND | — | requested from Graph API field list but never extracted downstream |
| meta_hook_rate | NOT_FOUND | — | no 3-second-view field fetched anywhere |
| meta_hold_rate_15s | NOT_FOUND | — | depends on thruplays, which don't exist |
| meta_thruplays | NOT_FOUND | — | zero occurrences of "thruplay" in Node-Backend |
| meta_cost_per_thruplay | NOT_FOUND | — | depends on meta_thruplays |
| meta_video_3s_views | NOT_FOUND | — | field never fetched |
| meta_video_30s_views | NOT_FOUND | — | field never fetched |
| meta_video_95_pct_views | NOT_FOUND | — | only p25/p50/p75/p100 exist |
| meta_video_25_pct_rate | NOT_FOUND | — | needs 3s-views denominator, which doesn't exist |
| meta_video_50_pct_rate | NOT_FOUND | — | same |
| meta_video_75_pct_rate | NOT_FOUND | — | same |
| meta_video_completion_rate | **DRIFT** | `meta/analytics.js:1838` | uses `video_play_actions` as denominator, not 3s views; percentage not ratio; per-ad only, no aggregate |
| meta_video_25_pct_views | UNCLEAR | `meta/analytics.js:1811,1834` | value exists per-ad but never summed to a dashboard total |
| meta_video_50_pct_views | UNCLEAR | `meta/analytics.js:1812,1835` | same |
| meta_video_75_pct_views | UNCLEAR | `meta/analytics.js:1813,1836` | same |
| meta_video_100_pct_views | UNCLEAR | `meta/analytics.js:1814,1837` | same |
| meta_video_plays | UNCLEAR | `meta/analytics.js:1810,1833` | per-ad only, no aggregate |
| meta_link_clicks | NOT_FOUND | — | no code extracts a `link_click` action specifically |
| meta_cost_per_link_click | NOT_FOUND | — | depends on meta_link_clicks |
| meta_landing_page_views | **DRIFT** | `meta/analytics.js:773` | account-level Graph API call only, no campaign/adset/ad/creative breakdown as catalogued; different code path than ClickHouse spend/clicks |
| meta_cost_per_landing_page_view | **DRIFT** | `meta/analytics.js:773,782` | same grain caveat |
| meta_breakdown_* (10 ids: clicks, cpc, cpm, ctr, impressions, spend, hook_rate, thruplays, landing_page_views, link_clicks, video_completion_rate) | NOT_FOUND | — | entire `meta_ad_breakdown_performance` cube view has no dashboard analog — see cross-cutting #4 |

**Dimension/grain caveats (not separately scored, but real):** Amazon's catalogued
`campaign_type`/`campaign_status`/`targeting_type` dims don't match the live query
(groups only by `campaign_id`); Google's catalogued `customer_account_id` dim has
zero hits in Node-Backend; Meta's catalogued `campaign_status`/`campaign_objective`/
`creative_id`/`creative_type` dims aren't present in the live `fct_meta_ads_daily`
query (`analyticsClickhouse.js:739-771`).

### commerce (34 metrics)

| id | verdict | evidence file:line | note |
|---|---|---|---|
| active_orders | NOT_FOUND | — | no standalone active-orders count anywhere |
| amazon_cancelled_orders | MATCH | `amazonShared/amazonSpOrderTotals.js:364-370` | matches catalogue's exclusion logic |
| amazon_gross_revenue | MATCH | `amazonSpOrderTotals.js:429,471` | |
| amazon_gross_sales | MATCH | `amazonAttribution/buildAmazonAttributionPayload.js:131-133` | |
| amazon_marketplace_fees | UNCLEAR | `amazonSpOrderTotals.js:478-479` | catalogue's stated composition (incl. shipping) actually matches what code calls `amazon_platform_fees`, not `amazon_marketplace_fees` |
| amazon_net_payout | MATCH | `amazonShared/amazonOrderPnl.js:98-99` | |
| amazon_net_sales | **DRIFT** | `amazonShared/amazonOrderPnl.js:6-9` | catalogue says incl-GST; code's own header comment says `revenue_principal`/`refund_principal` are ex-tax |
| amazon_orders | MATCH | `amazonSpOrderTotals.js:469` | |
| amazon_return_revenue | **DRIFT** | `amazonSpOrderTotals.js:393,430,472` | catalogued fallback chain (`effective_refunds`→`estimated_refunds`→...) is unreachable dead code; live path only ever uses `refund_principal` |
| amazon_returned_orders | **DRIFT** | `amazonSpOrderTotals.js:473` | same root cause as amazon_return_revenue |
| amazon_returns_cancels | MATCH | `amazonSpOrderTotals.js:318-324` | |
| amazon_total_sales | **DRIFT** | `amazonSpOrderTotals.js:470` | catalogue says canceled orders included at order_total; code zeroes them out |
| aov | **DRIFT** | `services/dashboardService.js:141` | catalogue says Shopify-only Total Sales ÷ Orders; live dashboard uses blended net_sales/orders; a 3rd unrelated implementation also exists in `shopify/analytics.js:1278-1322` |
| cancel_revenue | MATCH | `historicalAnalytics/lineItemHistoricalSql.js:279-305` | |
| cancelled_orders | MATCH | `lineItemHistoricalSql.js:279-305` | |
| cod_orders | MATCH | `lineItemHistoricalSql.js:424-467` | |
| commerce_net_revenue | MATCH | `historicalAnalytics/historicalQueryHelpers.js:72-78` | |
| commerce_net_revenue_daily | MATCH | `lineItemHistoricalSql.js:604-611` | |
| discounts | MATCH | `historicalQueryHelpers.js:36-37,63-64` | |
| event_cancel_revenue | MATCH | `lineItemHistoricalSql.js:279-305` | |
| event_return_revenue | MATCH | `lineItemHistoricalSql.js:307-333` | |
| gross_sales | MATCH | `historicalQueryHelpers.js:28-29,57-58` | |
| gross_sales_all_channels | MATCH | `lineItemHistoricalSql.js:586` | |
| net_sales_all_channels | **DRIFT** | `amazonOrderPnl.js:6-9` | inherits amazon_net_sales tax-basis issue |
| new_customer_orders | MATCH | `historicalAnalytics/analyticsClickhouse.js:309-345` | |
| orders | MATCH | `lineItemHistoricalSql.js:186-190` | |
| prepaid_orders | MATCH | `lineItemHistoricalSql.js:445-456` | |
| refunded_orders | MATCH | `lineItemHistoricalSql.js:307-333` | |
| return_cancel_revenue | MATCH | `lineItemHistoricalSql.js:294,322` | |
| return_revenue | MATCH | `lineItemHistoricalSql.js:307-333` | |
| returns_cancels | MATCH | `lineItemHistoricalSql.js:998-1021` | |
| total_orders | MATCH | `lineItemHistoricalSql.js:613` | |
| total_sales | MATCH | `historicalQueryHelpers.js:90` | |
| total_sales_all_channels | **DRIFT** | `amazonSpOrderTotals.js:470` | same root cause as amazon_total_sales |

### finance (28 metrics)

| id | verdict | evidence file:line | note |
|---|---|---|---|
| amazon_platform_fees | **DRIFT** | `amazonShared/amazonOrderPnl.js:47-60` | `abs(sum(total_amazon_fees))` used instead of `sum(abs(component))` per component — mathematically different whenever signs differ within an order |
| be_roas | MATCH | `integrations/attributionPnLHelpers.js:195-196` | |
| contribution_margin | MATCH | `attributionPnLHelpers.js:195` | correct but only an internal var, not a returned field |
| contribution_margin_pct | NOT_FOUND | — | no percent-of-sales field anywhere |
| cost_coverage_pct | NOT_FOUND | — | no "coverage" concept exists (catalogue itself marks draft) |
| gross_margin_pct | **DRIFT** | `services/pnlService.js:127` | computed from blended Shopify+Amazon totals, not Shopify-only as catalogued — see cross-cutting #2 |
| gross_profit | **DRIFT** | `historicalAnalytics/analyticsClickhouse.js:543` | no dashboard code computes catalogue's exact `net_sales - net_cogs` in the claimed Shopify-only scope |
| gross_roas | **DRIFT** | `services/dashboardService.js:142` | uses blended (Amazon-inclusive) figures on the primary dashboard summary — see cross-cutting #2 |
| mer | NOT_FOUND | — | no media-efficiency-ratio field anywhere |
| net_cogs | **DRIFT** | `services/pnlService.js:207`; `lineItemHistoricalSql.js:634-639` | code comment explicitly: "Net COGS (Shopify + Amazon)" — catalogue says Amazon excluded |
| net_margin_pct | **DRIFT** | `services/pnlService.js:137` | same blended-basis issue as gross_margin_pct |
| net_profit | **DRIFT** | `services/dashboardService.js:132,136` | fully blended; no code path computes the catalogue's claimed Shopify-only-minus-Meta/Google-spend formula |
| net_profit_all_channels | UNCLEAR | `services/pnlService.js:136,222-227` | formula shape is plausible but the catalogued `/1.18` GST adjustment for Amazon revenue doesn't appear in code |
| net_profit_blended | **DRIFT** | `services/pnlService.js:207,227` | catalogue claims only ad-spend is blended; in reality sales/COGS are already blended too |
| net_profit_incl_amazon | NOT_FOUND | — | no field/computation of this name; actual `net_profit` is already Amazon-inclusive, so this formula would double-count if built literally |
| net_roas | **DRIFT** | `services/dashboardService.js:143` | same blended-basis issue |
| operating_cost | MATCH | `lineItemHistoricalSql.js:616-621` | genuinely Shopify-only, correctly matches |
| packaging_cost | MATCH | `lineItemHistoricalSql.js:617` | |
| payment_gateway_fees | MATCH | `lineItemHistoricalSql.js:618-620` | |
| product_cost | **DRIFT** | `lineItemHistoricalSql.js:615,639` | value itself correct, but catalogue's own validation_test (`product_cost+shipping+packaging+gateway+rto=net_cogs`) is falsified since net_cogs also includes Amazon |
| product_cost_all_channels | MATCH | `services/pnlService.js:212-218` | |
| rto_cost | MATCH | `lineItemHistoricalSql.js:621` | |
| shipping_cost | MATCH | `lineItemHistoricalSql.js:616` | |
| shopify_ad_spend | MATCH | `lineItemHistoricalSql.js:647-648` | |
| taxes_on_net_sales | **DRIFT** | `services/pnlService.js:222-225` | catalogue: flat 18% of net_sales; code: subtracts Amazon out first, then adds Amazon's *actual* tax back — different formula, confirms blended-basis issue |
| total_ad_spend | MATCH | `historicalAnalytics/historicalQueryHelpers.js:369-370` | |
| total_operating_cost | **DRIFT** | (same as net_cogs) | same blended-basis drift |
| total_operating_cost_all_channels | UNCLEAR | `services/pnlService.js:208` | end value plausibly matches but is a single pre-blended field, not composed the way the catalogue's formula literally states (risk of double-counting if implemented literally) |

### attribution (27 metrics)

| id | verdict | evidence file:line | note |
|---|---|---|---|
| attributed_orders | MATCH | `historicalAnalytics/analyticsClickhouse.js:347-377` | |
| attributed_gross_revenue | MATCH | `integrations/attributionPnLHelpers.js:104-236` | |
| attributed_net_revenue | MATCH | `attributionPnLHelpers.js:158-167` | |
| attributed_new_customer_orders | MATCH | `historicalAnalytics/analyticsClickhouse.js:309-345` | |
| attributed_aov | MATCH | `attributionPnLHelpers.js:220,236` | derived client-side from matching components |
| attributed_refund_amount | **DRIFT** | — | `total_refund_amount` only used by Amazon modules; Shopify/meta/google attribution instead tracks separate return/cancel count+value pairs on event date, not one refund-amount column |
| attribution_rate | NOT_FOUND | — | no `attribution_method` field / "unattributed" bucket exists — every order is exhaustively bucketed meta/google/organic/other |
| avg_attribution_confidence | NOT_FOUND | — | no confidence-scoring field anywhere |
| touch_attributed_orders | NOT_FOUND | — | depends on attribution_method, which doesn't exist |
| channel_gross_revenue | NOT_FOUND | — | see cross-cutting #3 |
| channel_net_revenue | NOT_FOUND | — | see cross-cutting #3 |
| channel_orders | NOT_FOUND | — | see cross-cutting #3 |
| google_attribution_gross_sales | MATCH | `googleAttribution/analyticsClickhouse.js:783-793` | |
| google_attribution_net_sales | MATCH | same call chain | |
| google_attribution_orders | MATCH | same call chain | |
| google_attribution_total_sales | MATCH | same call chain | |
| meta_attribution_gross_sales | MATCH | `metaAttribution/analyticsClickhouse.js:626-637` | |
| meta_attribution_net_sales | MATCH | same call chain | |
| meta_attribution_orders | MATCH | same call chain | |
| meta_attribution_total_sales | MATCH | same call chain | |
| meta_attr_orders | MATCH | `metaAttribution/buildMetaAttributionPayload.js:408` | |
| meta_attr_net_revenue | MATCH | `buildMetaAttributionPayload.js:409` | |
| meta_attr_aov | MATCH | derived from matching components | |
| meta_attr_gross_revenue | **DRIFT** | `buildMetaAttributionPayload.js:401-418` | no ex-GST gross-revenue field broken out at ad/adset/campaign grain — only whole-summary `gross_sales` exists (assigned to a different metric) |
| meta_attr_refund_amount | NOT_FOUND | — | same root cause as attributed_refund_amount |
| meta_attr_new_customer_orders | NOT_FOUND | — | `is_new_customer` attached per-order but never summed to this grain |
| meta_attr_new_customer_revenue | NOT_FOUND | — | same |

### customer (16 metrics) — 0 clean matches

| id | verdict | evidence file:line | note |
|---|---|---|---|
| avg_days_between_orders | NOT_FOUND | — | no order-interval calc anywhere |
| avg_days_since_last_order | NOT_FOUND | — | no recency field anywhere |
| avg_ltv | NOT_FOUND | — | no lifetime-value calc anywhere |
| avg_orders_per_customer | NOT_FOUND | — | no such ratio surfaced |
| customer_profiles | NOT_FOUND | — | no customer master-data table/endpoint |
| customers | **DRIFT** | `shopify/analytics.js:3442,3596,3608` | 30-day windowed count, not lifetime snapshot |
| first_orders | **DRIFT** | `shopify/analytics.js:3458,3525,3559-3579` | customer-grain, and prior-order check capped at 100 customers/request |
| lifetime_gross_revenue | NOT_FOUND | — | no all-time revenue-per-customer aggregation |
| lifetime_net_revenue | NOT_FOUND | — | same |
| lifetime_orders | NOT_FOUND | — | no all-time order-count-per-customer aggregation |
| repeat_customers | **DRIFT** | `shopify/analytics.js:3459,3566,3576,5098,5110` | windowed/sampled, not a lifetime flag |
| repeat_order_share | NOT_FOUND | — | no purchase-sequence model exists |
| repeat_orders | NOT_FOUND | — | no order-grain "order_seq > 1" flag |
| repeat_purchase_net_revenue | NOT_FOUND | — | no purchase-sequence revenue split |
| repeat_purchase_orders | NOT_FOUND | — | no sequencing model at all |
| repeat_rate | **DRIFT** | `shopify/analytics.js:3611,5169-5173` | inherits windowed/sampled numerator+denominator |

### product (15 metrics) — 0 clean matches

| id | verdict | evidence file:line | note |
|---|---|---|---|
| average_selling_price | NOT_FOUND | — | no revenue/units ratio at product grain |
| gross_units_ordered | NOT_FOUND | — | only net quantity exists |
| product_cancel_revenue | **DRIFT** | `lineItemHistoricalSql.js:1685-1688,1716-1719` | formula matches but query is single-platform-attribution-scoped only, not standalone |
| product_cogs | NOT_FOUND | — | COGS only aggregated at brand×day, never per SKU |
| product_google_ad_spend | NOT_FOUND | — | no SKU-attributed ad spend anywhere |
| product_gross_margin_pct | NOT_FOUND | — | depends on non-existent fields |
| product_gross_profit | NOT_FOUND | `metaFunnelAttributionClickhouse.js:216-217,243` | only a narrow single-ad-scoped "sku_profit" exists |
| product_meta_ad_spend | NOT_FOUND | — | no SKU-attributed ad spend anywhere |
| product_net_revenue | **DRIFT** | `lineItemHistoricalSql.js:1677,1702,1739` | field labeled "net_sales" is actually pre-refund gross, no deduction applied |
| product_orders | **DRIFT** | `lineItemHistoricalSql.js:1697-1700` | logic matches but only exists inside channel-scoped query |
| product_other_ad_spend | NOT_FOUND | — | catalogue itself admits unimplemented |
| product_return_revenue | **DRIFT** | `lineItemHistoricalSql.js:1681-1684,1708-1711` | formula matches but channel-scoped only |
| product_total_ad_spend | NOT_FOUND | — | no SKU-attributed ad spend anywhere |
| units_per_order | **DRIFT** | `shopify/analytics.js:4937-4938` | only exists in legacy gross-incl-GST path, opposite of catalogue's claimed "corrected ex-GST basis" |
| units_sold | **DRIFT** | `lineItemHistoricalSql.js:1676,1701` | basis matches but channel-scoped only, not standalone |

### web_analytics (12 metrics)

| id | verdict | evidence file:line | note |
|---|---|---|---|
| add_to_cart_events | NOT_FOUND | `martFunnelClickhouse.js:30` | only session count (`atc_sessions`) exists, not event count |
| bounce_rate | **DRIFT** | `channelFunnel/sessionDrilldownClickhouse.js:74-94` | dashboard deliberately overrides the catalogued funnel-proxy formula with a native `is_bounce` flag — see cross-cutting #9 |
| collection_views | NOT_FOUND | — | only an enum value inside per-order journey lookups |
| events_per_session | NOT_FOUND | — | zero hits anywhere |
| funnel_conversion_rate | UNCLEAR | `channelFunnel/analytics.js:35-58` vs `martFunnelClickhouse.js:33` | internal basis mismatch — see cross-cutting #9 |
| funnel_purchases | **DRIFT** | `martFunnelClickhouse.js:6-9,33,49` | session-attributed and double-counting per the code's own comment; catalogue explicitly claims it's NOT this |
| funnel_revenue | **DRIFT** | `channelFunnel/spendRoasClickhouse.js:6-11`, `analytics.js:89-100` | same session-mart mismatch, plus a 3rd revenue source override the catalogue doesn't mention |
| product_views | NOT_FOUND | `martFunnelClickhouse.js:29` | only session count (`pdp_sessions`) exists |
| site_search_events | NOT_FOUND | `customerJourneyClickhouse.js:23,139-140` | only inside single-order journey lookups, capped ≤300 rows/order |
| web_events | NOT_FOUND | — | no all-event-types daily rollup exists |
| web_page_views | **DRIFT** | `ga4/analytics.js:93,132,182` | catalogue implies first-party/Snowplow source; real source is GA4 Data API, different grain |
| web_sessions | **DRIFT** | `channelFunnel/sessionDrilldownClickhouse.js:96-132` | core count matches, but catalogued dims (geo_city, browser_family, os_family, exit_page_path) have zero support in the real query |

### operations (5 metrics)

| id | verdict | evidence file:line | note |
|---|---|---|---|
| refund_count | NOT_FOUND | `lineItemHistoricalSql.js:591,685` | only order-grain `returned_orders` exists, not refund-event grain |
| refund_lines | NOT_FOUND | `lineItemHistoricalSql.js:335-361` | `fct_refund_line_items` query exists but its CTE is never joined into output — dead code |
| refunded_amount_excl_tax | **DRIFT** | `lineItemHistoricalSql.js:76,315-332,600-601` | resolves to the identical figure as `returns_excl_tax`; catalogue implies a broader "all refunds" number that doesn't exist |
| return_recovered_cogs | **DRIFT** | `lineItemHistoricalSql.js:335-361` vs `364-393,617-646` | matching CTE is dead code; live logic instead *adds* return cost to COGS — the opposite operation — see cross-cutting #8 |
| returns_excl_tax | **DRIFT** | `lineItemHistoricalSql.js:42-63,315-332,689` | formula/tax logic genuinely matches, but catalogued dims (restock, return_status, geo, payment) have zero support — only brand/date/hour totals produced |

---

## Suggested next step

This report identifies *what's wrong*; it does not yet propose the specific yaml
edits. Given the scale (~124 of 190 metrics need some correction), recommend
tackling in priority order:

1. **Mechanical, high-confidence fixes** (~15 min): CTR unit fix (3 metrics),
   dead-code corrections once confirmed with you (return_recovered_cogs direction).
2. **Finance re-scoping** (~28 metrics): requires you to confirm whether the
   *intended* design is "Shopify-only" (and the dashboard has a bug) or "blended"
   (and the catalogue descriptions are simply stale) — this determines whether we fix
   the catalogue text or file a dashboard bug instead.
3. **Prune vs. keep aspirational metrics**: ~66 NOT_FOUND_IN_DASHBOARD metrics need a
   call on whether to mark them `status: not_implemented` / deprecate them from the
   catalogue, or leave them as roadmap items with a clear "Cube-only, not on
   dashboard" annotation.
4. **customer/product categories**: essentially need to be rewritten as "not
   implemented" wholesale, or scoped down to describe the actual windowed/sampled
   Shopify REST behavior instead of a lifetime grain that doesn't exist.

Awaiting direction on how you'd like to proceed with the actual edits.
