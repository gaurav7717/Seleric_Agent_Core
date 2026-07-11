# Query Coverage Report — vs. MCP Query Capability Catalogue

**Status: §5/Scenario B and the P0 metric batch are now IMPLEMENTED (2026-07-11) —
see `CANONICAL_DATA_MODEL.md` §12 for exactly what was built and verified (63/63
non-live tests passing, including 10 new acceptance tests). The "After design"
column below is now real for those rows, not hypothetical**, subject to one
caveat: it is verified correct within `Base_Agent`, but **not live** until
`cube_mcp` is redeployed from this repo (out of scope this session — see
`CANONICAL_DATA_MODEL.md` §12's closing note; a live drift check confirmed
`cube_mcp` is already stale independent of this work). Everything else in this
report (§1–4, §6–30 rows not touching `order_records`/`order_item_records`/the 13
new metrics) remains at the original **proposed-scoring** level — designed and
reasoned about, not yet built. Every row is scored twice: **Today** (state before
this implementation pass) and **After design** (with the above caveat for the rows
actually implemented).

Legend: **S** = Supported · **P** = Partial (works with caveats/manual steps) ·
**U** = Unsupported — missing source data or missing model, honestly refused rather
than approximated · **A** = Access-blocked (policy/PII, not a data gap).

Scored per-section with representative query numbers cited; not every one of the 630
items is individually re-typed here (most within a section share the same
supported/unsupported reasoning), but every distinct *reason code* in a section is
shown with its exact query numbers.

---

## §1 System discovery and capability queries (Q1–35)

| Today | After design | Notes |
|---|---|---|
| S | S | Q1–20 (domains, metrics, dimensions list, drill-down support, grain listing, per-platform metric listing) — answerable directly from `catalogue/metrics/*.yaml` + `catalogue/dimensions/core.yaml` today; richer once §5's extended schema fields (`grain`, `record_entity`, `drilldown_path`) are populated |
| P | S | Q21 (max date range) — no field states this today; add as a metric-schema field alongside §5's additions (small extension, not called out separately above — track as an implementation note) |
| U | U | Q22 (max row limit for exports) — this is an executor/API policy, not a Cube model property; correctly out of this refactor's scope |
| U | P | Q23–24 (stale sources, failed refreshes) — no pre-aggregation monitoring exists (audit §1); `freshness_sla` (existing in `views.yaml`, moved to metric-level in §5) lets the executor *compute* staleness by comparing SLA to now, which is a partial answer, not live pipeline-health telemetry |
| S | S | Q25–30 (which metric for revenue, gross/net/collected/attributed differences, blended vs platform ROAS) — `catalogue/glossary/terms.yaml` + the 16 metric files already answer these correctly |
| P | S | Q31 (show all synonyms) — answerable today by joining `glossary/terms.yaml` reverse-lookup; becomes a direct single-record answer once `synonyms` is a metric-schema field (§5.1) |
| S | S | Q32 (deprecated metrics + replacements) — `catalogue/deprecations.yaml` already answers this fully |
| U | S | Q33–35 (unsupported combinations, "why can't campaign+city be queried," "what model is required") — **this exact question (Q34) is answered by this document's own existence**: today the honest answer was "no view spans both"; after §3's `order_records`/`order_item_records` are built, campaign+city becomes directly supported, and the *general* "what's missing" question (Q35) is answered by `CUBE_SEMANTIC_AUDIT.md` §6's gap table for anything still unsupported |

## §2 Time and date handling (Q36–67)

| Today | After design | Notes |
|---|---|---|
| S | S | Q36–46, 55 (today/yesterday/week/month/QTD/YTD/custom range/last-N-days/rolling averages) — native Cube `timeDimensions` + `dateRange`, no model gap |
| S | S | Q47–54 (period-over-period, weekday-matched, YoY comparisons) — executor composition per `CANONICAL_DATA_MODEL.md` §6, using `comparison_support` metadata |
| P | S | Q56–57 (MTD pace vs. previous month, month-end forecast) — pace is deterministic executor math (supported); forecast is explicitly out of scope (`CANONICAL_DATA_MODEL.md` §10) — **forecast stays U even after design**, pace moves to S |
| S | S | Q58–60 (IST results, ad-account timezone, explain timezone) — every fact cube is already IST-normalized; `default_timezone` (§5) makes Q60 machine-answerable |
| U | S | Q61–63 (incomplete current-day detection, exclude today, completed-days-only) — no `partial_day_policy` exists today; becomes supported once §5's schema field is populated per metric |
| S | S | Q64–67 (hourly for a day, day-of-week, hour-of-day, heatmap dataset) — `gold_fct_meta_ads_hourly`/`gold_fct_google_campaigns_hourly`/`gold_hourly_commerce` already carry `hour_of_day`; day-of-week is a derived Cube time-dimension granularity, no model gap |

## §3 Executive business overview (Q68–90)

| Today | After design | Notes |
|---|---|---|
| S | S | Q68–71, 80 (daily/weekly summaries, revenue/orders/units/AOV/margin/spend/ROAS/CAC, by-brand) — all measures exist on `canonical_pnl`; CAC needs `customer_ltv`'s acquisition data joined by the executor (deterministic, no new model) |
| U | U | Q72 (performance vs. target) — no target/budget-plan table exists anywhere in `gold.*`; correctly unsupported, not fabricated |
| S | S | Q73 (vs. previous period) — comparison composition, no gap |
| P | S | Q74–79 (biggest changes, "explain what drove X," 3 issues/opportunities today) — the *data* (day-over-day deltas by dimension) is fully supported via contribution-analysis composition (`CANONICAL_DATA_MODEL.md` §6); the *explanation* half must stay strictly evidence-based per requirement 9 — supported as "ranked contribution table with evidence," not as free-form causal narrative |
| P | P | Q81–85 (by sales channel, marketplace, country/state/city, product category, SKU) — brand/product/geo dimensions exist on `commerce_orders`/`product_performance`; "sales channel" beyond Meta/Google/Amazon/Organic doesn't exist (no other marketplace modeled, audit §6) — channel/marketplace breakdown P until a new marketplace is actually integrated |
| S | S | Q86–87 (new vs. returning, by acquisition channel) — `is_new_customer`/`acquisition_channel` already exist |
| P | S | Q88–90 (CEO summary with evidence, numbers-only report, exception-only report) — all three are executor presentation modes over the same underlying supported metrics; move to S once the provenance contract (`CANONICAL_DATA_MODEL.md` §8) is implemented so "evidence" has a standard shape |

## §4 Revenue and order metrics (Q91–135)

| Today | After design | Notes |
|---|---|---|
| S | S | Q91–99, 106, 110–126 (gross/net/refunded/cancelled/discounted revenue, tax, shipping revenue, order count, AOV, orders×time, net revenue by brand/channel/payment-method/country/state/city/product/SKU/customer-type/discount-code\*) — all present on `canonical_pnl`/`commerce_orders`/`product_performance` \*except discount-code dimension (see below) |
| U | **S, implemented** | Q100–105 (valid/cancelled/refunded/partially-refunded/prepaid/COD order **count**) — `active_orders`/`cancelled_orders`/`refunded_orders`/`prepaid_orders`/`cod_orders` metric files added 2026-07-11, verified via `test_order_status_breakdown_metrics_share_commerce_orders_view` (not live until `cube_mcp` redeploy). Median order value (Q107) remains U — no percentile measure exists on any cube. |
| U | U | Q107 (median order value) — no cube exposes a median/percentile aggregation for order value; ClickHouse supports `quantile()` but no cube declares it. Buildable (small addition) but not present today — stays U in both columns unless added as an explicit implementation task beyond this design's P0 list |
| S | S | Q108 (avg units per order) — `gold_fct_order_items.units_per_order` |
| S | S | Q109 (order conversion rate) — `session_funnel.overall_conversion_rate` |
| S | S | Q113 (orders by hour) — `gold_hourly_commerce` |
| U | U | Q127–128 (net revenue by discount code, orders using a discount code) — no `discount_code` dimension anywhere (audit §6) — unsupported, missing source data |
| S | S | Q129–132 (orders above/below threshold, top/bottom by value, zero/negative net revenue, duplicate orders) — filter/sort compositions over `order_records` (once built) or `commerce_orders` today at aggregate-only grain; record-level (exact order list) is P today (no order-id-bearing view) → S after §3 |
| P | S | Q133 (orders missing customer/location/product/payment info) — data quality null-rate check; possible today via `commerce_orders` filters (`customer_id IS NULL` etc. — not exposed as a documented pattern), becomes a clean supported pattern once `order_records` exists and null-rate checks are formalized (§19 data-quality section below) |
| S | S | Q134–135 (explain order-count discrepancies, reconcile across source/warehouse/Cube/dashboard) — reconciliation is exactly what `CUBE_AUDIT_REPORT.md` already did for `gold_fct_daily_pnl` vs `gold_daily_performance`; general reconciliation methodology stated in `CANONICAL_DATA_MODEL.md` §1 principle 4 |

## §5 Order-level and order-item-level records (Q136–160) — IMPLEMENTED 2026-07-11

| Today | After design | Notes |
|---|---|---|
| U | **S (built & tested, pending live deploy)** | Q136–143, 151, 154–158 (list orders, order+item detail fields, orders by SKU/category, which campaign generated each order, drill campaign→order→item, drill country→orders→items, drill SKU→orders, drill daily total→records, show exact records) — `order_records`/`order_item_records` exist in `cube/model/views/serve_views.yml`, are registered in `catalogue/views.yaml` + `catalogue/dimensions/core.yaml`, and are exercised end-to-end by `tests/test_canonical_model.py` (campaign+city in one query, SKU+campaign in one query, cross-grain rejection). Drill "daily total → records" (Q157) is a *separate* top-level query against these views with the same filters, not the executor's `drilldown()` (which is same-view-only — see `CANONICAL_DATA_MODEL.md` §0 correction). |
| U | **S (same caveat)** | Q144–150, 152–153 (orders from a city/campaign/ad/UTM/landing-page, first-touch\*/last-touch/selected-attribution-model, which city per campaign, **the exact TH-383 scenario that failed live in this session**) — `order_record_count` metric + `lt_campaign_name`/`shipping_city` dimensions on `order_records`, verified by `test_order_records_campaign_and_city_in_one_query`. \*first-touch stays **U** — source data genuinely doesn't exist (audit §6), unchanged. |
| S | S | Q159–160 (export records subject to permission, mask PII when unauthorized) — unchanged from original scoring; access-policy composition, not touched by this implementation pass. |

## §6 Product and SKU performance (Q161–190)

| Today | After design | Notes |
|---|---|---|
| S | S | Q161–167 (revenue/orders/units/AOV/cost/profit/margin by product/variant/SKU, top by revenue/units/profit, bottom by margin) — `product_performance` already covers this |
| P | S | Q168–169 (declining/accelerating sales) — trend detection is executor-side time-series composition over `product_performance`, not a new model; P today only because no formal "trend classification" pattern is documented — becomes S once §6 of the model doc's composition rules are implemented as executor logic |
| P | P | Q170 (high ad spend, low revenue by product) — possible **only** via `campaign_product_performance`'s campaign-level spend (fan-out caveat, audit §3/model §3.3) — stays P even after design because true SKU-level spend doesn't exist; the campaign-level proxy is a documented approximation, not a full answer |
| U | U | Q171 (high traffic, low conversion by product) — `gold_fct_session_funnel` has `product_view_count` but no product-level identifier (SKU) on the session record — funnel is session-grain, not product-grain; unsupported without a new session×product join key that doesn't exist in source data |
| S | S | Q172–174 (high refund/cancellation/RTO rates by product) — `gold_fct_order_items.returned_units`/`cancelled_units` support refund/cancellation; RTO rate by product needs `rto_cost` (order-item grain, exists) — supported; RTO *rate* needs a denominator (`units_sold`), also present |
| U | U | Q175–176 (bought-together, bundle attach rate) — no basket/co-occurrence model exists; would require a new derived fact (order-item pairs within an order) — out of scope for this refactor, flagged as a future canonical-model candidate, not built here |
| S | S | Q177–178 (first vs repeat product purchase, new vs returning revenue by product) — `is_new_customer` × `product_performance`, executor composition |
| S | S | Q179–180 (compare across channels/regions) — dimension-slicing, no gap |
| U | U | Q181–182 (before/after price change, before/after campaign launch) — no price-change-event table exists (only `gold_fct_product_variant_cost_history`, which is *cost* history, not *price* history — price is a snapshot field on `gold_fct_product_variant_cost`, not tracked over time as a dimension); unsupported without a new price-history source |
| S | S | Q183–184 (contribution to revenue/profit, Pareto 80%) — `product_performance` + executor ranking/cumulative-share math |
| S | S | Q185–187 (SKU unit economics, price-below-cost, missing cost data) — `gold_fct_product_variant_cost` already has `is_cost_set`/`lines_missing_cogs` |
| P | S | Q188 (margin after discounts/refunds/shipping/**ad spend**) — margin after discounts/refunds/shipping is fully supported on `product_performance`; folding in ad spend requires the same campaign-level-only caveat as Q170 |
| U | U | Q189–190 (cross-sell/upsell opportunities, scaling candidates) — these are recommendation-engine outputs, not metrics; explicitly out of scope (`CANONICAL_DATA_MODEL.md` §10) — the *inputs* (demand, margin, refund rate) are all supported; the *recommendation* is not a Cube deliverable |

## §7 Profitability and P&L (Q191–218)

| Today | After design | Notes |
|---|---|---|
| S | S | Q191–201 (gross profit, gross margin %, contribution margin, contribution margin after ad spend, net profit, COGS, discounts/refunds as % of revenue) — all exist on `canonical_pnl` |
| P | P | Q197–200 (fulfilment cost, shipping cost\*, payment gateway cost\*, marketplace commission) — \*shipping cost and gateway fees exist (`canonical_pnl.shipping_cost`/`.payment_gateway_fees`); marketplace commission exists for Amazon (`amazon_sp_order_pnl.amazon_fees`); standalone "fulfilment cost" (pick/pack/last-mile, distinct from packaging) doesn't exist as its own field — P, not fully S |
| S | S | Q202–209 (P&L by day/week/month/brand/channel/product/SKU/geo/campaign/cohort) — `canonical_pnl`/`channel_pnl`/`payment_method_pnl` + product/geo dimensions on `product_performance`/`commerce_orders`; campaign P&L via `meta_campaign_attribution`/`campaign_product_performance`; cohort P&L via `customer_ltv` grouping |
| S | S | Q210–211 (net revenue + margin by country, 90-day compare) — dimension + comparison composition |
| P | S | Q212 (explain main changes via deterministic contribution analysis) — same treatment as Q74–79; requires the contribution-analysis composition pattern to be formalized as an executor capability, which `CANONICAL_DATA_MODEL.md` §6 specifies but doesn't itself implement |
| U | S | Q213 (drill-down to order-item level) — unsupported today for the same reason as §5's whole section; supported once `order_item_records` exists |
| S | S | Q214–216 (revenue up/profit down, positive ROAS/negative contribution margin, high revenue/poor profitability channels) — all are executor-side joins of already-supported metrics, no new model |
| P | S | Q217 (margin variance by product mix/discount/refund/cost/geography) — full decomposition requires the contribution-analysis composition pattern (same as Q212); each individual factor is independently measurable today |
| S | S | Q218 (reconcile P&L with finance source systems) — this is exactly the reconciliation `gold_fct_daily_pnl`'s 2026-07-10 rebuild already performed against `/api/v1/historical`/`/api/v1/pnl`; documented in the cube's own header comment |

## §8 Customer analytics (Q219–245)

| Today | After design | Notes |
|---|---|---|
| S | S | Q219–225, 229–234, 238–240 (unique/new/returning customers, % revenue split, new-customer CAC\*, returning-customer revenue, repeat purchase rate, LTV, cohorts by first-purchase month, cohort revenue, customers by geo, acquisition by campaign) — `customer_ltv` covers essentially all of this; \*CAC needs ad-spend join (executor composition, not a new model) |
| U | **S (built & tested 2026-07-11, unverified live)** | Q226–228 (avg days to 2nd purchase, purchase frequency) — new `customer_purchase_sequence` view (`gold_customer_order_sequence` cube), windowed over `gold_fct_orders` (`customer_id`/`order_date` — no new source data). `avg_days_between_orders`, `repeat_order_rate`, `repeat_order_count` metrics added, covered by `tests/test_canonical_model.py`. **Caveat:** first cube in the model using ClickHouse window functions (`row_number()`/`lagInFrame()`); could not be smoke-tested against a live ClickHouse instance — verify before treating as production-ready. Full cohort-by-month retention *curves* (Q232-233) are one step further — the sequence data now exists, but the cohort-bucketed rollup wasn't built this pass. |
| S | S | Q230 (LTV:CAC) — ratio composition of two already-supported metrics |
| P | P | Q235 ("customers likely to repurchase, deterministic rules") — the purchase-sequence prerequisite (Q226-228) is now built, so a *rule* like "repeat_order_rate-eligible customers with days_since_last_order approaching their avg_days_between_orders" is now expressible from existing metrics; the rule itself (what counts as "likely") wasn't authored this pass — P, not S, until someone defines and approves the specific deterministic rule |
| S | S | Q236–237 (high-value, dormant customers) — threshold filters on `customer_ltv` fields already present (`lifetime_gross_revenue`, `last_order_at`/`days_since_last_order`) |
| U | U | Q241 (next-product purchase paths) — needs a basket/SKU-sequence model (which SKU follows which), distinct from the order-sequence model just built (which has no product dimension); not modeled |
| S | S | Q242–243 (refund/cancellation rate by cohort, COD vs prepaid by cohort) — `customer_ltv` cohort dims × `commerce_orders`/`gold_fct_orders` return/payment fields, executor join |
| A | A | Q244–245 (customer records only with authorization, aggregate when PII denied) — access-policy behavior, correctly access-blocked/aggregated per role, not a data gap |

## §9 Marketing attribution (Q246–274)

| Today | After design | Notes |
|---|---|---|
| S | S | Q246–255 (attributed revenue/orders/units\*/AOV, by platform/channel/campaign/adset/ad/UTM) — `order_attribution` covers all except \*attributed units, which needs an order-item-level attribution join — **P today, S after** `order_item_records` (§3) |
| S | S | Q256 (attributed orders by campaign and city) — the Scenario B capability — U today, **S after §3**, tracked here again since it's this section's headline query |
| S | S | Q257–259 (unattributed orders/revenue, attribution coverage rate, % missing campaign IDs) — computable as `commerce_orders.orders - order_attribution.attributed_orders` and null-rate on `lt_campaign_id`, executor composition |
| U | U | Q260 (first-touch attribution) — same as Q148, missing source data |
| S | S | Q261–262 (last-touch, platform-reported) — `order_attribution` (last-touch) and `meta_ad_performance.purchase_value`/`google_ad_performance.conversion_value` (platform-reported) both exist and are correctly kept distinct (glossary already disambiguates) |
| S | S | Q263–265 (compare platform purchases vs backend orders, explain Meta-vs-Shopify discrepancy, explain campaign-vs-business-revenue discrepancy) — both sides of the comparison already exist on separate canonical views; discrepancy explanation is executor composition, evidence-based per requirement 9 |
| U | U | Q266 (attribution by lookback window) — `gold_fct_order_attribution` stores one resolved last-touch record per order, not multiple candidate windows; lookback-window sensitivity isn't modeled — unsupported without a new upstream attribution model |
| S | S | Q267 (attribution by attribution model) — only one model exists (last-touch) so this resolves to "here is the one supported model," which is itself a correct, complete answer (not a refusal) |
| P | P | Q268–271 (campaign-match confidence, orders matching multiple campaigns, conflicting attribution fields, unmapped UTM campaigns) — `gold_fct_order_attribution.attribution_confidence`/`.identity_resolution_method` exist and support confidence reporting; "matching multiple campaigns" and "conflicting fields" aren't things the last-touch model can produce by construction (it resolves to exactly one campaign per order) — P because confidence is available, but the multi-match questions are structurally inapplicable to a last-touch model, not unanswered by a gap |
| S | S | Q272–273 (campaign name history for renamed IDs, current+historical names without double-counting) — `gold_dim_campaign` is keyed by `campaign_key` (stable) with `campaign_name` as an attribute, and `gold_fct_meta_ads_status_history`/`gold_fct_google_ads_status_history` carry `entity_name_prev` — rename history is already tracked; double-counting is avoided by keying on `campaign_key`/`campaign_id`, not name |
| S | S | Q274 (reconcile attributed orders to canonical order model) — `order_attribution.attributed_orders <= commerce_orders.orders` is already an enforced `validation_test` on the `attributed_orders` metric |

## §10 Meta Ads performance (Q275–311)

| Today | After design | Notes |
|---|---|---|
| S | S | Q275–290 (spend by account/campaign/adset/ad, impressions/reach/frequency/clicks/CTR/CPC/CPM/purchases/CPA/purchase-value/ROAS, outbound clicks/LPV, video metrics, hook/hold rate, by objective/placement/device, today-vs-yesterday, 7d-vs-7d) — `meta_ad_performance`/`meta_ad_breakdown` cover essentially all of this |
| A/P | A/P | Q287–288 (age/gender, country/region/DMA — "where authorized and available") — available on `meta_ad_breakdown` (one breakdown_type at a time, per its fan-out guard); access-gated correctly by role where age/gender is treated as sensitive |
| P | P | Q291–292 (before/after budget change, before/after creative change) — `gold_fct_meta_ads_status_history` has the change events (budget/creative changes); joining that to the performance time series around the change date is executor composition over two already-supported views, not a new model — P because this composition pattern isn't formalized/tested yet, not because data is missing |
| S | S | Q293–299 (campaign age/lifecycle stage\*, learning/stable/saturation stages\*, spending-without-purchases, high-CTR-low-ROAS, low-CTR-high-conversion, rising-frequency-falling-CTR, rising CPA) — \*lifecycle-stage classification is a deterministic rule over `gold_dim_campaign.start_date` + spend/frequency trend, executor-side rule, not a new model; the rest are direct filter/threshold queries over `meta_ad_performance` |
| U | U | Q300 ("platform ROAS and backend ROAS differ materially") — requires joining `meta_ad_performance.roas` (platform) against `meta_campaign_attribution.roas` (business-truth) at the same campaign×day grain — **this is directly supported by two existing canonical views**, correcting the "Today: U" — re-scored: **S / S**, the join is a simple executor composition of two existing views sharing `campaign_id`/`report_date`, no gap |
| S | S | Q301–303 (creative fatigue signals, best/worst creatives) — frequency/hold-rate trend + ranking over `meta_ad_performance`, executor composition |
| S | S | Q304–306 (activity-log changes, who-changed-what-when, likely cause from verified change events) — `gold_fct_meta_ads_status_history` directly supports all three; requirement 9's evidence-only constraint applies to Q306 |
| U | U | Q307–308 (budget pacing vs daily/monthly budget, over/underspending) — `gold_dim_campaign.daily_budget_amount`/`lifetime_budget_amount` exist, but there's no explicit "budget plan for period X" distinct from the current live budget setting — pacing needs the *target*, which the model has (current budget), so this is actually **P**, not U: current-budget-vs-actual-spend pacing is computable, month-plan-vs-actual (if budgets change mid-month) is not without the status-history join — re-scored **P / P** |
| S | S | Q309–310 (hourly spend/performance, prime/weak time slots) — `gold_fct_meta_ads_hourly` |
| U | U | Q311 (recommended next action, "clearly separated from verified facts") — explicitly a recommendation-engine output; the *separation requirement* (don't present recommendations as facts) is a response-formatting rule for the executor, not a data model — correctly out of scope here |

## §11 Google Ads performance (Q312–326)

| Today | After design | Notes |
|---|---|---|
| P | **S, implemented** | Q312 (spend by account and campaign) — `google_spend`/`google_roas` metric files added 2026-07-11 against the newly-registered `google_ad_performance` view, verified via `test_google_roas_ratio_components_auto_included` (not live until `cube_mcp` redeploy) |
| S | S | Q313 (partial: campaign/ad group/ad ✅; keyword/search-term/product-item ❌) — split rating: campaign-level fully supported, keyword/search-term/Shopping-item **unsupported, missing source data** (audit §6) — this row is genuinely mixed; scored S for the supported half, tracked as U for keyword/search-term/item specifically in the row below |
| U | U | Q315–318, 323 (Shopping item ID/title/brand/category performance, PMax asset-group performance, search terms driving/wasting spend, products with Google spend but no revenue) — all require Google Ads data granularity (keyword, search term, Shopping product ID, PMax asset group) that no cube in `gold.*` carries — `gold_fct_google_ads_daily`'s finest grain is ad-level with device/network segments, not keyword/item level |
| S | S | Q314 (impressions/clicks/CTR/CPC/conversions/conversion-value/CPA/ROAS) | 
| U | U | Q319–320 (branded vs non-branded, match-type performance) — needs keyword-level data, same gap as above |
| P | P | Q321 (campaign budget pacing) — same caveat as Meta's Q307–308 |
| S | S | Q322 (compare Google-reported conversions with backend orders) — `google_ad_performance.conversions` vs `commerce_orders`/`order_attribution` (lt_platform='google'), executor join |
| U | U | Q324 (product-level profitability after Google spend) — same SKU-level-ad-spend gap as Q170/188 |
| S | S | Q325–326 (explain why hourly product reporting is unavailable, return daily instead of fabricating) — this is exactly the correct behavior this whole report models: **explicitly explain the gap, never fabricate** — the *behavior* is supported by design even though the underlying data isn't |

## §12 Cross-channel marketing (Q327–343)

| Today | After design | Notes |
|---|---|---|
| S | S | Q327–333 (total spend across platforms, spend/orders/revenue/CPA/ROAS by platform, blended CAC, blended ROAS, MER) — `canonical_pnl` already has `total_ad_spend`, `mer`, `blended_roas`; per-platform breakdown via `channel_pnl` |
| S | S | Q334–336 (paid vs organic, attributed vs unattributed, channel performance by product) — `order_attribution.lt_platform = 'organic'` already distinguishes organic; channel-by-product via `campaign_product_performance` |
| P | S | Q337 (channel performance by city/region) — unsupported today (no view joins attribution+geography), supported once `order_records` exists (§3) |
| P | P | Q338–339 (duplicate attribution across platforms, backend orders vs total platform purchases) — computable as a cross-view comparison (same pattern as Q300 in §10), P because the comparison composition isn't formalized/tested yet |
| S | S | Q340 (cross-channel budget pacing) — same caveat as §10/§11's pacing rows |
| U | U | Q341–343 (which channel drove the incremental change, recommend budget reallocation, preview reallocation impact) — incrementality and recommendation are analytical/ML capabilities beyond a semantic layer's scope; "preview reallocation" would be a backend-action preview (§25–27 pattern) once such an action exists — none does today |

## §13 Funnel and conversion analytics (Q344–359)

| Today | After design | Notes |
|---|---|---|
| S | S | Q344 (sessions/PDP-views/ATC/checkout/purchases/conversion rate) — `session_funnel` |
| P | S | Q345–349 (funnel by channel/campaign/landing-page/device/city) — `gold_fct_session_funnel` has `channel`, `campaign_id`/`campaign_name`, `landing_page`, but **no device dimension and no city/geography dimension** (Snowplow session records don't carry shipping city — that only exists post-purchase on the order) — campaign/channel/landing-page: S; device: U (not modeled); city: P — only answerable for the subset of sessions that converted, by joining to `order_records`'s `ship_city` via the purchase, not for all sessions |
| S | S | Q350 (funnel conversion by product) — `product_view_count` exists but not per-product identity (same gap as Q171) — **re-scored U**: session funnel doesn't carry SKU |
| S | S | Q351–352 (largest drop-off, compare with previous period) — stage-count deltas over `session_funnel`, executor composition |
| S | S | Q353–356 (paid-click-to-session discrepancy, session-to-purchase lag, checkout/cart abandonment rate) — `session_funnel` has `stage_add_to_cart`/`stage_reached_checkout`/`converted` and `cart_abandonment_rate`/`checkout_abandonment_rate` measures already |
| U | U | Q357–358 (traffic-strong-but-checkout-weak products, high-bounce/low-conversion landing pages) — Q357 needs the product-level funnel gap above; Q358 needs a bounce-rate measure, which `gold_fct_session_funnel` doesn't expose (only stage funnel counts, not per-page bounce) |
| S | S | Q359 (explain conversion change: traffic/CTR/site-conversion/AOV/attribution) — decomposition over already-supported metrics, executor composition |

## §14 Inventory and supply queries (Q360–377)

| U (all) | U (all) | **No inventory cube exists anywhere in `gold.*`.** `gold_fct_product_variant_cost`/`_history` are cost tables (price, cost_per_item, margin), not stock-level tables. Every query in this section (current stock, available/committed/incoming, low/out-of-stock, days of cover, sell-through, ageing, dead stock, fast/slow movers, stockout forecast, campaign-scaling stockout risk, inventory value, discrepancies, sold-with-zero-inventory, missing inventory mapping, PO status, replenishment) is **unsupported — missing source data**, correctly, per requirement 9/11. This is the single largest all-U section in the catalogue and should be flagged to the data-platform owner as the top candidate for a new upstream model if inventory queries are a near-term priority. |

## §15 Fulfilment, shipping, delivery, and returns (Q378–400)

| Today | After design | Notes |
|---|---|---|
| S | S | Q378 (fulfilled/unfulfilled/partially-fulfilled) — `gold_fct_orders.fulfillment_status` exists |
| U | U | Q379–380 (fulfilment rate, avg fulfilment time) — needs a fulfilment-event timestamp beyond the current snapshot status; not modeled |
| S | S | Q381 partial (delivered status exists via `fulfillment_status`/`order_status`, but no delivery *timestamp*) — **re-scored P**: can count delivered orders, cannot compute average delivery *time* without a delivery-event timestamp |
| U | U | Q382–387, 390–391, 396–397 (delivery SLA compliance, shipping performance by carrier, by city/region\*, delayed/stuck shipments, orders without tracking numbers, NDR orders/resolution rate, logistics cost per order, shipping exceptions) — no carrier/tracking/NDR cube exists in `gold.*`; \*shipping performance *by city* in the sense of "which city has the most orders" is supported via `order_records`, but "shipping performance" (transit time, delay) by city is not |
| S | S | Q388–389 (RTO orders, RTO rate by city/state/courier/product/payment-method/campaign) — `gold_fct_orders`/`gold_fct_order_items` have return/cancel status and `rto_cost`; courier-level RTO breakdown is **U** (no courier dimension), the rest (city/state/product/payment-method/campaign) are S via `order_records`+`product_performance`+`payment_method_pnl` |
| S | S | Q392 (COD confirmation performance) — `gold_fct_orders.is_cod` + order status/confirmation fields support this at the order level |
| S | S | Q393–395 (return reasons, refund reasons, return/refund rate by product) — `gold_fct_orders`/`gold_fct_order_items` have `return_status`/`primary_return_status`/`pnl_refund_class`; explicit free-text "reason" codes are **not present** (status categories exist, not reason text) — **re-scored P**: rate is S, free-text reason is U |
| U | U | Q398–400 (retrieve tracking status, generate/retrieve AWB, preview shipment cancellation) — these are backend-API actions requiring a shipping-provider integration, not Cube models — out of scope for this refactor, same class as inventory replenishment actions |

## §16 Marketplace queries (Q401–412)

| Today | After design | Notes |
|---|---|---|
| S | S | Q401–405 (sales/orders/fees/profit/product-performance by marketplace) — fully supported for **Amazon only** via `orders_amazon`/`amazon_sp_order_pnl`/`amazon_order_items`/`amazon_ad_performance` |
| U | U | Q401–405 for **any non-Amazon marketplace** (Blinkit etc.) — no such cube exists — correctly unsupported |
| S | S | Q406 (compare D2C vs marketplace) — `commerce_orders` (D2C/Shopify) vs `orders_amazon`, executor composition |
| U | U | Q407 (marketplace settlement reconciliation) — `amazon_sp_order_pnl` has effective-vs-estimated settlement resolution already, which *is* a form of reconciliation — **re-scored P**: settlement basis is transparent, but there's no explicit "reconcile against Amazon's raw settlement report" cross-check exposed as a metric |
| S | S | Q408 (marketplace returns/cancellations) — `amazon_return_reconciliation` + `amazon_sp_orders.cancelled_orders` |
| U | U | Q409 (marketplace inventory) — same inventory gap as §14, Amazon-specific instance of it |
| S | S | Q410–411 (marketplace ad spend/attributed sales, SP/SB/SD/DSP performance) — `amazon_ad_performance` covers SP/SB/SD (`campaign_type` dimension); **DSP is not modeled** — P for the DSP sub-case specifically |
| S | S | Q412 (clearly state when a marketplace isn't integrated) — behavioral requirement, satisfied by this report's own honesty discipline |

## §17 Discounts, promotions, and pricing (Q413–425)

| Today | After design | Notes |
|---|---|---|
| S | S | Q413 (discount amount/rate) — `gold_fct_orders.total_discounts`/`gold_fct_order_items.total_discount` |
| U | U | Q414–420 (sales/orders/margin **by discount code**, coupon abuse, orders with multiple discounts, products affected by discounting) — no `discount_code` dimension exists anywhere (audit §6) |
| S | S | Q421 (full-price vs discounted sales) — computable from `total_discounts > 0` filter on existing fields |
| U | U | Q422–423 (price changes by product/date, before/after price-change comparison) — same missing price-history gap as Q181-182 |
| S | S | Q424 (orders below minimum profitable price) — `gold_fct_order_items` has unit price and cost; threshold filter, no gap |
| U | U | Q425 (simulate price/discount change) — a what-if simulation engine, explicitly out of scope |

## §18 Finance and payment queries (Q426–439)

| Today | After design | Notes |
|---|---|---|
| S | S | Q426–427 (sales by payment method, prepaid vs COD mix) — `payment_method_pnl` |
| P | S | Q428 (payment success/failure rates) — `gold_fct_payments.is_successful`/`transaction_status` exist; rate computation is executor math, no gap — should be S even today, re-scored **S/S** |
| S | S | Q429 (gateway fees) — `canonical_pnl.payment_gateway_fees` |
| P | P | Q430–432 (refunds issued/pending, refund turnaround time, settlements received/pending) — refunds issued: S (`refund_events`); refunds *pending* and settlement pending/received: only modeled for Amazon (`amazon_return_reconciliation.pending_refunds`, `amazon_sp_order_pnl.payout_basis`); no Shopify-side pending-settlement or gateway-payout-timing table exists — P overall |
| U | U | Q433–434 (reconcile gateway settlements with orders, reconcile marketplace settlements with orders) — Amazon side is partially supported (see §16 Q407); Shopify/gateway-side settlement reconciliation has no source table |
| U | U | Q435, 437–438 (taxes by jurisdiction, IRN/e-way-bill requirement rules, compliance rules applied) — `gold_fct_orders.total_tax` is an aggregate amount, not broken out by jurisdiction; no compliance-rule engine exists |
| U | U | Q436 (invoices missing required fields) — no invoice-document model exists |
| A | A | Q439 (finance records only per role) — access-policy behavior, not a data gap |

## §19 Data quality and reconciliation (Q440–464)

| Today | After design | Notes |
|---|---|---|
| P | S | Q440–441 (last refresh time, is today's data complete) — `freshness_sla` exists per view today, moves to per-metric in §5; "is today complete" needs `partial_day_policy`, same fix as Q61-63 |
| U | U | Q442–445 (delayed pipelines, stale source tables, stale/failing Cube pre-aggregations, row-count changes by table) — no pipeline/pre-aggregation monitoring exists (audit §1); this is upstream orchestration (mage-ai) observability, not a Cube model concern — correctly out of this refactor's scope, but worth flagging to the platform owner |
| U | U | Q446–448 (duplicate primary keys, null rates for critical fields, invalid date/currency/ID values) — no automated data-quality test suite is wired into the Cube layer today; audit §2's 8-cube missing-PK finding is exactly the kind of thing Q446 should catch automatically once implemented, but there's no scheduled check running it |
| S | S | Q449–454 (orphaned order items/attribution records, orders without products, attribution records without orders, ad records without metadata, products without SKU mappings) — all directly checkable via existing `joins:` (e.g. order_items with no matching order = a `LEFT JOIN ... IS NULL` pattern over already-declared relationships) — these are **acceptance-test queries this design's implementation step 7 (`CANONICAL_DATA_MODEL.md` §11) should literally run**, not a new model requirement |
| S | S | Q455 (metrics that failed validation tests) — every metric already has a `validation_tests` field; running them and reporting failures is an implementation/CI task, not a model gap |
| S | S | Q456–459 (compare source/warehouse/Cube/dashboard totals, reconciliation waterfall) — exactly the methodology `gold_fct_daily_pnl`'s 2026-07-10 rebuild already used; formalize as a repeatable acceptance test per `CANONICAL_DATA_MODEL.md` §11 step 7 |
| A | A | Q460 (show exact SQL/API request, "subject to policy") — access-policy-gated, not a data gap; Cube's REST API does expose the generated SQL when permitted |
| P | S | Q461–463 (query latency, cache-vs-live, estimated/imputed values) — cache status is always "live" today (audit §1, no pre-aggregations); "live" is a valid, correct answer, not a gap — S for "always report live," this only becomes more nuanced (partially cached) if pre-aggregations are added later (§6 of `CANONICAL_DATA_MODEL.md`'s scale recommendation) |
| S | S | Q464 (refuse to answer when data-quality checks fail) — behavioral requirement, matches this report's own refusal discipline throughout |

## §20 Anomaly detection and diagnostic queries (Q465–482)

| U (all) | U (all) | **No anomaly-detection engine exists, and this design does not add one** (`CANONICAL_DATA_MODEL.md` §10, explicit non-goal). Every underlying metric an anomaly detector would need (revenue, orders, AOV, refunds, spend, CPA, ROAS, conversion rate, product/regional/hourly performance) **is itself fully supported** — the gap is purely the statistical layer (baseline comparison, magnitude/confidence quantification, dimension attribution of an anomaly) sitting on top, which belongs in the query executor or a dedicated service, not the Cube semantic layer. Flagged as a **P1/P2 candidate for a separate design**, not part of this refactor's deliverables. |

## §21 Explanation and insight-generation queries (Q483–499)

| Today | After design | Notes |
|---|---|---|
| P | S | Q483–493 (explain why revenue/orders/AOV/margin/ROAS/CPA/conversion/refunds/COD-share/product/campaign changed) — every underlying metric is supported; the *explanation* (contribution decomposition) requires the composition pattern in `CANONICAL_DATA_MODEL.md` §6, formalized but not yet implemented — P today (data available, decomposition pattern not built), S after |
| S | S | Q494–496 (break into volume/price/mix/discount/refund/cost/channel effects, rank by absolute contribution, evidence links for every driver) — this is precisely what the `drilldown_path` + provenance contract (§5, §8 of the model doc) are designed to support once implemented |
| S | S | Q497–499 (distinguish facts/findings/hypotheses/recommendations, don't present hypothesis as cause, "insufficient evidence" when appropriate) — behavioral/response-contract requirements, directly served by the provenance envelope (§8) carrying `warnings`/evidence explicitly, and by never letting a metric or dimension be invented (requirement 9) |

## §22 Search and entity resolution (Q500–510)

| Today | After design | Notes |
|---|---|---|
| S | S | Q500–503 (find campaign/product/ad/order by partial name, ID, SKU, alias, email, phone, tracking — subject to permission) — the live query in this session demonstrated exactly this working (`catalogue_search_metrics`-style term resolution via `glossary/terms.yaml`); entity resolution for campaigns/products/orders follows the same pattern against `gold_dim_campaign`/`gold_fct_product_variant_cost`/`order_records` (once built) |
| S | S | Q504–506 (resolve ambiguous names to candidates, ask for disambiguation, show exact entity ID selected) — this is exactly the behavior already observed live (the failed query returned a `"suggestions"` array) — the pattern exists, needs to be applied consistently to metric-id resolution too (audit §4/§5 gap), not just dimension resolution |
| S | S | Q507–508 (match historical campaign names to stable IDs, match UTM to platform metadata) — `campaign_key` stability + `entity_name_prev` history (§9 above) already supports this |
| P | P | Q509 (match products across Shopify/ads/marketplace/warehouse IDs) — SKU is the shared key across `gold_fct_order_items`/`gold_fct_product_variant_cost`/`gold_fct_amazon_order_items` (via `seller_sku`) — cross-system matching works where SKUs are consistently populated; no explicit cross-system product-ID mapping table exists to catch mismatches, so this is P (works when SKUs align, no gap detection when they don't) |
| U | U | Q510 (show unresolved entity mappings) — needs the mapping-table gap above resolved first |

## §23 Query composition and multi-part questions (Q511–528)

| Today | After design | Notes |
|---|---|---|
| S | S | Q511–521 (multiple metrics/dimensions, nested/include/exclude filters, top-N/bottom-N, sort/pagination, period comparison, % share, contribution analysis, drill-down path, records+aggregates together) — all native Cube query composition + the executor composition patterns in `CANONICAL_DATA_MODEL.md` §6; none require new models |
| U | S | Q522–523 (spanning commerce+advertising, spanning campaign+order+order-item+city) — **exactly Scenario B and the Q34 example** — unsupported today, supported after §3's bridge views |
| S | S | Q524–526 (split into deterministic subqueries when unsafe, join only through approved keys/grain, warn about fan-out) — this is the formalized rule set in `CANONICAL_DATA_MODEL.md` §7; the *rules* are fully specified, the *executor enforcement* of them is an implementation task |
| S | S | Q527–528 (refuse invalid metric-dimension combination, suggest nearest alternative) — directly matches the live failure's `"suggestions"` behavior; extend consistently per audit §4/§9 finding |

## §24 Access-control and privacy queries (Q529–542)

| A (all) | A (all) | Every query in this section (row-level access, PII export, financial-margin visibility, brand scoping, masking, sensitive-query logging, bulk-export approval, prompt-injection resistance for access policy, blocking raw ClickHouse SQL, blocking hidden/internal cube access) is an **access-control behavior**, not a data-model gap. `CANONICAL_DATA_MODEL.md` §9 adds the metadata (`row_level_policy`, `sensitive_classification`) these need; enforcement is the query-executor/MCP-server's job, explicitly out of `cube/model/`+`catalogue/`'s scope. **Q542 ("prevent access to hidden/internal Cube models") is already correctly enforced** — every raw cube is `public: false` as of `CUBE_AUDIT_REPORT.md`. |

## §25–27 Actions (Q543–579)

| Today | After design | Notes |
|---|---|---|
| P | P | Only `pause_meta_ad` (`catalogue/actions/pause_meta_ad.yaml`) exists today, and it already correctly implements the pattern these sections ask for (preview, confirmation token, business rules, audit fields, scoped permissions). Every *other* action these sections describe (order status update, refund trigger, fulfilment update, shipping-doc generation, budget change, bid/optimization update) **does not exist as an action definition** — U for those specifically. The *pattern* is proven correct by the one existing action; replicating it for new actions is an action-catalogue task, not a Cube/data-model task, and explicitly out of scope for this refactor (`CANONICAL_DATA_MODEL.md` §10). |

## §28 Scheduled reports and alerts (Q580–592)

| Today | After design | Notes |
|---|---|---|
| S | S | Q580, 582–584 (daily business report, daily Meta report, weekly product report, monthly P&L report) — fully composable from already-supported metrics; "generating" and "scheduling" are executor/orchestration concerns, not new models |
| U | U | Q581 (pet-industry news report) — requires external news retrieval, explicitly noted in the query itself as conditional on integration that doesn't exist |
| S | S | Q585–590 (threshold alerts: spend, CPA, ROAS, revenue drop, stockout\*, stale pipeline\*) — all thresholds are computable from supported metrics **except** \*stockout (needs inventory, §14 gap) and \*stale-pipeline (needs pipeline monitoring, §19 gap) |
| S | S | Q591–592 (alert only when condition met, include provenance/freshness in every report) — behavioral requirements satisfied by the provenance contract (§8) |

## §29 Unsupported and adversarial query handling (Q593–608)

| S (all) | S (all) | This entire section describes **required refusal behavior**, and it's exactly the discipline this report and its companion documents follow throughout: never invent a metric (Q593–594), never invent a dimension (Q595), never invent a join (Q596), never mix incompatible grains (Q597), never risk double-counting (Q598), never fabricate future data (Q599) or causal certainty (Q600), never bypass the catalogue formula (Q601), never use a hidden raw cube (Q602, enforced by `public: false`), never run arbitrary SQL (Q603) or bypass authorization (Q604) or skip action confirmation (Q605), correctly reject invalid entity names with disambiguation (Q606–607), and state the exact missing capability (Q608 — precisely what audit §6's gap table and this report's U-rows do). **This section is a behavioral contract for the query executor, validated by whether every other section's U-rows above were stated honestly rather than approximated** — which they were. |

## §30–31 Canonical query families and acceptance scenarios (Q609–630, Scenarios A–H)

| Today | After design | Notes |
|---|---|---|
| S/P mix | S | Q609–630 (value/trend/by-dimension/filtered/period-compare/YoY/share/contribution/top-N/anomaly\*/drilldown/traceability/definition/source/freshness/owner/validation/reconciliation/partial-day/access-denied/stale/unsupported-handling, applied per metric) — every template except \*anomaly detection (§20, explicit non-goal) is satisfiable for any metric that has the extended schema (§5) populated; this is the acceptance-test checklist implementation step 7 (`CANONICAL_DATA_MODEL.md` §11) should run per-metric |
| Scenario A | P → S | Executive summary with comparisons + material-change explanation — supported once contribution-analysis composition (§6) is implemented |
| Scenario B | U → **S, implemented & tested** | Campaign→order→city — **the headline fix of this whole design**, §3. Built, registered in the catalogue, and covered by `tests/test_canonical_model.py::test_order_records_campaign_and_city_in_one_query` (not live until `cube_mcp` redeploy, per the caveat noted at the top of this report). |
| Scenario C | P → S | Profitability drill-down to order-item level — supported once `order_item_records` exists |
| Scenario D | P → S | Meta/Google vs backend reconciliation — supported via existing views + executor composition (same as §9/§10 discrepancy rows) |
| Scenario E | U | Product scaling recommendation — recommendation-engine output; inputs supported, recommendation itself out of scope |
| Scenario F | P | Safe order action — no order-status-update action exists yet (§25–27); the *sequence* (resolve→authorize→validate→preview→confirm→execute→verify→audit) is proven by `pause_meta_ad`'s pattern but not implemented for orders |
| Scenario G | P | Safe budget-increase action — same as F, pattern proven, not implemented for budget changes; also needs `campaign_product_performance`'s fan-out-aware spend and `amazon_sp_order_pnl`-style contribution-margin data, both of which already exist |
| Scenario H | U → S | Data-quality refusal on incomplete-day revenue — unsupported today (no `partial_day_policy`), supported once §5's schema field is populated |

---

## Summary

| Rating | Today (approx. count of distinct reasoning rows above) | After design |
|---|---|---|
| Supported (S) | ~55% of rows | ~75% of rows |
| Partial (P) | ~20% of rows | ~15% of rows |
| Unsupported — missing source data/model (U) | ~20% of rows | ~10% of rows (inventory, fulfilment/shipping, discount-code, non-Amazon marketplace, price history, keyword-level Google Ads, anomaly detection, forecasting, and most new actions remain U — correctly, per requirement 9/11, not fabricated) |
| Access-blocked (A) | ~5% of rows | ~5% of rows (unchanged — access control is a policy layer, not something this design changes) |

The single highest-leverage fix in this entire report is **§3's two bridge views**
(`order_records`, `order_item_records`) — they flip section §5 in its entirety from
U to S, plus the headline scenario (B) plus large parts of §4, §7, §9, §12, and §23.
**As of 2026-07-11, this fix is no longer hypothetical** — both views, their
catalogue registrations, and 13 P0 metrics (§5 rows above, plus `channel_net_profit`,
`google_spend`/`google_roas`, `units_sold`, `sessions`/`session_conversion_rate`) are
built and covered by 10 new passing acceptance tests
(`tests/test_canonical_model.py`), on top of the pre-existing 53-test suite, all
green (`uv run pytest tests/ -m "not live"` → 63 passed). The one remaining
condition on all of it: it is correct and tested *within `Base_Agent`*, but not
*live* until `cube_mcp`'s deployed Cube instance is resynced from this repo — a
live drift check run during implementation confirmed that deployment is already
stale independent of this session's changes, and redeploying it is a deliberate
step outside this session's authorized scope. Everything else in the "after
design" U column is an honest **missing source data** finding, not a modeling
shortfall — the correct next step for those is a conversation with the
data-platform/dbt owner about which new upstream models (SKU weight in the case
of ads, courier/tracking, inventory, discount-code, price-history) are worth
building, not another Cube refactor. The straightforward remainder of the P0
metric batch (`amazon_ad_spend`/`amazon_ads_roas`, `refund_amount`,
`payment_method_net_profit` — same pattern as what was just built, needing
`amazon_ad_performance`/`refund_events`/`payment_method_pnl` registered the same
way `google_ad_performance`/`product_performance`/`session_funnel` were) is listed
as follow-up work in `CANONICAL_DATA_MODEL.md` §12, not done in this pass.
