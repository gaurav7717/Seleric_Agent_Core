# Cube Semantic Audit — vs. MCP Query Capability Catalogue

**Status: DRAFT FOR REVIEW — no production files modified.** This audit extends
`CUBE_AUDIT_REPORT.md` (2026-07-11, cube-overlap audit — already implemented) with
analysis specific to this goal: every cube's primary keys, pre-aggregations, and
join-safety, checked against every requirement in `mcp_query_capability_catalogue.md`.
It does not re-derive the base inventory — see `CUBE_AUDIT_REPORT.md` §1 for the full
38-cube table (grain/source/entity/scope), which is still accurate as of this audit.

Companion documents: `CANONICAL_DATA_MODEL.md` (the proposed design) and
`QUERY_COVERAGE_REPORT.md` (630 query patterns mapped to supported / partial /
unsupported / access-blocked).

---

## 1. Pre-aggregations: none exist

Every one of the 38 cubes in `cube/model/cubes/*.yml` was read in full. **Not one
declares a `pre_aggregations:` block.** Every query — from a single-day KPI to a
90-day P&L comparison — executes live against ClickHouse.

Consequences for the query catalogue:
- Query #444 ("Which Cube pre-aggregations are stale or failing?") is currently
  **unsupported by definition** — there is nothing to be stale, because nothing is
  pre-aggregated. This should be answered honestly ("no pre-aggregations are
  configured; all queries are live") rather than fabricated.
- Query #461/#462 ("query latency and cache status," "cached vs. live") — same:
  today the honest answer is always "live," never "cached."
- Not a correctness defect — ClickHouse is fast enough for the current data volumes
  per the existing model — but it is a scale and cost gap the canonical model should
  flag for `daily`/`monthly` grain rollups once qualified (`canonical_pnl`,
  `meta_ad_performance`) if query volume grows. Recommendation in
  `CANONICAL_DATA_MODEL.md` §6.

## 2. Primary keys: 8 of 38 cubes have none declared

Cubes built from `sql_table:` (a real ClickHouse table) consistently declare
`primary_key: true` on their grain-defining dimension(s). Cubes built from an inline
`sql:` block (hand-written bridge/rollup queries) are inconsistent — 8 of them
declare **no primary key at all**:

| Cube | Grain (from header comment / GROUP BY) | PK declared? |
|---|---|---|
| `gold_channel_pnl` | brand × report_date × platform | ❌ none |
| `gold_payment_method_pnl` | brand × report_date × payment_method | ❌ none |
| `gold_hourly_commerce` | brand × report_date × hour_of_day | ❌ none |
| `gold_daily_performance` | brand × report_date | ❌ none |
| `gold_customer_acquisition_ltv` | brand × cohort_month × channel/campaign/platform | ❌ none |
| `gold_campaign_product_performance` | brand × report_date × platform × campaign × sku | ❌ none |
| `gold_meta_campaign_attribution` | brand × report_date × campaign_id | ❌ none |
| `gold_neurohack_attribution` | brand × report_date × tag_code × ad_id | ❌ none |

By contrast, `gold_fct_daily_pnl` (also inline-SQL) does the right thing — it
synthesizes an explicit `pnl_key: concat(brand_id, '|', report_date)` and marks it
`primary_key: true`. `gold_ad_neurohack_enriched` and `gold_meta_neurohack_daily`
(also inline-SQL) also correctly declare composite primary keys.

**Risk:** without a declared primary key, Cube cannot guarantee correct
`count_distinct` / dedup semantics if these cubes are ever joined into by another
cube, and any future consumer has no machine-readable statement of "one row = what."
None of these 8 are currently joined *into* by another cube (confirmed by grep of
every cube's `joins:` block — none reference these 8 by name), so the immediate
correctness blast radius is contained. But it directly blocks requirement 8
("prevent double counting... using explicit primary keys") as a general property of
the model, and blocks query #446 ("show duplicate primary keys") — there is no
primary key to check for duplicates against on these 8 today.

**Fix (proposed in `CANONICAL_DATA_MODEL.md`):** synthesize an explicit composite key
on each, the same way `gold_fct_daily_pnl.pnl_key` already does — e.g.
`gold_channel_pnl.channel_pnl_key = concat(brand_id,'|',report_date,'|',platform)`.
Mechanical, additive, no behavior change to existing measures.

## 3. Join-safety classification: two architectures coexist

The cube layer uses two different mechanisms to combine data, with very different
double-counting guarantees:

**A. Declarative `joins:` blocks** (Cube's join engine, cardinality-checked):
`gold_fct_orders` ⋈ `gold_fct_order_items` (`one_to_many`), ⋈
`gold_fct_order_attribution` (`one_to_one`), ⋈ `gold_dim_customers`
(`many_to_one`); `gold_fct_order_items` ⋈ `gold_fct_product_variant_cost`
(`many_to_one`); `gold_fct_amazon_sp_orders` ⋈ `gold_fct_amazon_sp_order_pnl`
(`one_to_one`); `gold_fct_amazon_order_items` ⋈ `gold_fct_amazon_sp_orders`
(`many_to_one`); the ad dimension chain `gold_dim_campaign` ⋈ `gold_dim_adset` ⋈
`gold_dim_ad` (`one_to_many` each); `gold_fct_meta_ads_daily`/`gold_fct_google_ads_daily`
⋈ their respective dimension cubes (`many_to_one`); `gold_dim_ad_neurohack_map` ⋈
`gold_dim_neurohack` (`many_to_one`). **These are safe by construction** — Cube's
query planner generates correct SQL for any measure/dimension combination reachable
through this graph, and a view can safely compose fields from multiple cubes in this
graph without hand-verification, *as long as the view is rooted at the finer-grained
cube when pulling coarser dimensions, never the reverse with unfiltered measures.*

**B. Inline `sql:` bridge cubes** (hand-written JOIN + GROUP BY, no engine guarantee):
`gold_fct_daily_pnl`, `gold_daily_performance`, `gold_channel_pnl`,
`gold_payment_method_pnl`, `gold_hourly_commerce`, `gold_customer_acquisition_ltv`,
`gold_campaign_product_performance`, `gold_meta_campaign_attribution`,
`gold_neurohack_attribution`, `gold_ad_neurohack_enriched`, `gold_meta_neurohack_daily`
— 11 cubes. Each is pre-aggregated to its target grain inside its own SQL (correctly,
as far as this audit can verify from the SQL text — every one of them ends in an
explicit `GROUP BY` matching its documented grain), but **Cube's engine provides no
independent guarantee for these** — correctness rests entirely on the SQL author
having gotten the grain and join cardinality right, and any future edit to the inline
SQL bypasses Cube's cardinality checking entirely. This is architecturally different
from (A) and should be called out explicitly to anyone extending the model: **adding
a new joined table to an inline-SQL cube's `sql:` block is a manual, unverified
operation; adding a new `joins:` entry to a declarative cube is engine-checked.**

**Explicit fan-out warnings already documented in the model** (confirmed accurate):
- `gold_fct_meta_ads_breakdown_daily`: 8 independent breakdown slices unioned in one
  table; summing `spend` without `WHERE breakdown_type = '<one>'` overcounts ~8×.
  Warning is in the cube's own header comment, `chart_views.yml`'s description, and
  `cube/AGENTS.md`. **Correctly guarded, no action needed.**
- `gold_dim_ad_neurohack_map` / `gold_mart_meta_ad_neurotag_daily`: one ad can carry
  multiple tags; `*_fc` ("full credit") measures duplicate the ad's full spend/revenue
  on every tag row, `*_sc` ("split credit") divides by tag count. Warning is
  documented in the cube, the view, `cube/AGENTS.md`, and
  `cube/scripts/generate_semantic_catalog.py`'s `ANTI_PATTERNS` dict. **Correctly
  guarded, no action needed.**

**Fan-out risk not yet guarded anywhere:** `gold_campaign_product_performance`'s own
header comment admits `spend joins platform ad tables at campaign × day (duplicated
across SKUs in a campaign)` — i.e. if a campaign sold 5 SKUs in a day, that campaign's
ad spend appears once per SKU row, and naively summing `spend` grouped only by
`campaign_id` (dropping the `sku` dimension) overcounts 5×. **This warning exists only
in a code comment — it is not surfaced in the view description, `cube/AGENTS.md`, or
the `ANTI_PATTERNS` dict**, unlike the two patterns above. This is the same class of
risk as the two guarded patterns but currently undocumented for any query-time
consumer (human or LLM) to discover. Flagged as a fix in `CANONICAL_DATA_MODEL.md`.

## 4. Metric-name ambiguity register (requirement 2: duplicate/ambiguous metrics)

The query catalogue explicitly tests for this class of problem (§1 Q25–32: "which
metric should I use for revenue," "difference between gross/net/collected/attributed
revenue," "difference between blended ROAS and platform ROAS," "show all synonyms").
Cross-referencing every measure name across all 38 cubes surfaces real ambiguity that
is **only partly resolved today** by `catalogue/glossary/terms.yaml` and
`catalogue/metrics/*.yaml`:

| Name | Appears on (with different meanings) | Catalogued today? |
|---|---|---|
| `net_revenue` | `gold_fct_orders` (order-grain, incl. GST despite the name), `gold_fct_order_items` (line-grain), `gold_fct_order_attribution` (attribution-scoped), `gold_fct_daily_pnl` (aliased to `net_revenue_excl_tax`, ex-GST), `gold_hourly_commerce`, `gold_mart_meta_ad_neurotag_daily` — **at least 4 genuinely different bases (incl/excl GST, order/line/attribution grain)** | Only `canonical_pnl.net_revenue_excl_tax` is an approved metric id (`net_revenue`) |
| `roas` (and platform variants) | `gold_fct_meta_ads_daily.roas`, `gold_fct_google_ads_daily.roas`, `gold_fct_google_campaigns_hourly.roas`, `gold_meta_neurohack_daily.roas`, `gold_mart_meta_ad_neurotag_daily.roas_fc/roas_sc/platform_roas_fc/sc`, `gold_meta_campaign_attribution.roas`, `gold_channel_pnl.meta_roas/google_roas/channel_roas`, `gold_fct_daily_pnl.meta_roas/google_roas/gross_roas/net_roas/be_roas/blended_roas`, `gold_neurohack_attribution.attributed_roas`, `gold_fct_amazon_ads_campaigns_daily.ads_roas` — **≈14 distinct ROAS definitions across platform-reported vs. business-attributed vs. blended bases** | Only `blended_roas` and `meta_roas` are approved metric ids. `google_roas`, `ads_roas` (Amazon), `channel_roas`, and every `*_fc`/`*_sc` variant are **not catalogued** — asking for "Google ROAS" (query #314) or "Amazon Ads ROAS" (query #411) fails resolution today, the same failure class observed live in this session before this goal was set. |
| `spend` / `ad_spend` | Identical duplicate aliases *within the same cube* on `gold_fct_meta_ads_daily` and `gold_fct_meta_ads_hourly` (harmless redundancy, not ambiguity) — plus genuinely different bases: `gold_fct_daily_pnl.meta_spend/google_spend/amazon_spend/total_ad_spend`, `gold_channel_pnl.spend/meta_ad_spend/google_ad_spend`, `gold_meta_campaign_attribution.ad_spend`, `gold_campaign_product_performance.spend`, `gold_neurohack_attribution.spend`, `gold_mart_meta_ad_neurotag_daily.spend/spend_fc/spend_sc` | Only `meta_spend` and `total_ad_spend` are approved metric ids. `google_spend` and `amazon_spend` exist as measures on `canonical_pnl` but have **no metric-catalogue entry of their own** — query #312 ("Google Ads spend by account and campaign") has no canonical metric id to resolve to. |
| `orders` / order counts | `gold_fct_orders.orders` (test-excluded, all statuses), `gold_fct_order_attribution.placed_orders`/`attributed_orders`, `gold_channel_pnl.placed_orders`, `gold_fct_daily_pnl.total_orders`/`orders_created`/`active_orders`/`realized_orders`, `gold_fct_amazon_sp_orders.order_count` — **at least 5 distinct "order count" bases** (placed vs. active vs. realized vs. attributed vs. Amazon) | `orders` (→ `commerce_orders.orders`) and `attributed_orders` are approved. `active_orders`, `realized_orders`, `cancelled_orders`, `refunded_orders`, `prepaid_orders`, `cod_orders` **exist as measures on `canonical_pnl`/`commerce_orders` but have no metric-catalogue entry** — every one of query catalogue §4's Q100–105 ("valid/cancelled/refunded/partially-refunded/prepaid/COD order count") currently fails resolution the same way. |

**Root cause, not a one-off bug:** `catalogue/metrics/*.yaml` currently registers 16
hand-picked metric ids. Every measure that exists on a cube/view but lacks its own
file in `catalogue/metrics/` is **structurally unresolvable** by
`catalogue_search_metrics` — this is what the live failure earlier in this session
demonstrated (a real, existing Cube measure, rejected because it wasn't a catalogued
metric id). The fix is not case-by-case; it's systemic: every measure a query pattern
in the capability catalogue asks for needs a `catalogue/metrics/<id>.yaml` file. See
`CANONICAL_DATA_MODEL.md` §5 for the full list of P0 metrics currently missing a
catalogue entry.

## 5. Metric-catalogue schema gap vs. capability catalogue §32

The capability catalogue's required metric fields (§32) vs. what
`catalogue/metrics/*.yaml` actually has today:

| Required field (§32) | Present today? | Gap |
|---|---|---|
| `metric_id`, `display_name`, `description`, `formula`, `canonical_cube_view`\*, `canonical_measure`\*, `grain`, `supported_dimensions`, `supported_filters`, `owner`\*, `roles_allowed`\*, `examples`, `validation_tests` | ✅ (\*nested under `cube_mapping`/`data_owner`/`access_policy`) | none — naming differs slightly (`cube_mapping.view`/`.measure` vs. flat `canonical_cube_view`/`canonical_measure`), cosmetic only |
| `business_definition` | ❌ | `description` conflates plain-English and business-rule text; no separate authoritative business-definition field |
| `calculation_service` | ❌ | No field states whether the metric is computed purely in Cube SQL vs. requires post-processing (e.g. period-over-period %, contribution analysis) — needed for requirement 6/10 (runtime composition, provenance) |
| `additivity` | ⚠️ partial | `aggregation: additive/ratio` exists but doesn't distinguish semi-additive (e.g. inventory snapshots, not present yet) from fully additive |
| `required_filters` | ❌ | E.g. `meta_ad_breakdown` *requires* a `breakdown_type` filter to be safe (§3 above) — nothing in the metric schema can express "this filter is mandatory, not optional" |
| `time_dimension` | ⚠️ implicit | Present as a `supported_dimensions` entry, not flagged as *the* canonical time axis distinct from other dimensions |
| `default_timezone` | ❌ | Not per-metric; assumed globally IST (correct today, since all cubes are IST-normalized) but not machine-declared per metric for query #60 ("explain which timezone was applied and why") |
| `comparison_support` | ❌ | Nothing declares which comparison types (period-over-period, YoY, rolling average) are valid for a given metric — needed for query catalogue §2 and §30's canonical query families (#613–614) |
| `drilldown_path` | ❌ | Nothing declares that `attributed_orders` drills to `order_attribution_detail` (the proposed bridge view) or that `net_revenue` drills to `order_records` → `order_item_records` — needed for §5's entire query set and §30 #619–620 |
| `record_entity` | ❌ | No metric declares which record-grain entity it aggregates from — needed for #619 ("drill-down to the lowest approved grain") |
| `source_models` | ⚠️ partial | `freshness.source` (in `catalogue/views.yaml`, not `metrics/`) states the dbt/ClickHouse source, but only for the 8 currently-catalogued views, not per metric |
| `row_level_policy` | ❌ | `access_policy.roles_allowed`/`scopes` exists (who can read the metric at all) but nothing declares row-level filtering (e.g. brand-scoped access) — needed for query §24 |
| `freshness_sla` | ⚠️ misplaced | Exists in `catalogue/views.yaml` per-*view*, not per-*metric* — two metrics on the same view could theoretically have different effective freshness (e.g. a metric depending on a slower-refreshing upstream join) with no way to express that |
| `partial_day_policy` | ❌ | Nothing states whether a metric should be marked "partial" / excluded / flagged when today is incomplete — directly needed for query #61–63, #627, Scenario H |
| `synonyms` | ⚠️ misplaced | Exists in `catalogue/glossary/terms.yaml` as a global term→metric map, not attached to the metric record itself — works for now but doesn't satisfy "show all synonyms for attributed orders" (query #31) as a single-metric lookup without a second file join |
| `deprecated_by` | ⚠️ inverse only | `deprecated_aliases` (old name → this metric) exists; the forward direction (this metric, if deprecated, → its replacement) does not, though no metric is currently deprecated so this hasn't bitten yet |

This is a **schema extension, not a rewrite** — every existing field stays, new
fields are additive. Full proposed schema in `CANONICAL_DATA_MODEL.md` §5.

## 6. Missing dimensions / missing join paths (tied to specific query numbers)

| Gap | Blocks query # | Root cause | Fix class |
|---|---|---|---|
| No view exposes `order_id`/`order_name` + shipping city/state/country + campaign attribution on the same row | #136–153, #256, Scenario B | `order_attribution` view excludes `order_id`; `gold_fct_order_attribution` has no shipping fields at all (only `gold_fct_orders` does); no view spans both despite the cube-level `one_to_one` join already existing | **New view**, zero new SQL — see `CANONICAL_DATA_MODEL.md` §3 `order_records` |
| No view exposes order-item detail (SKU, qty, cost, margin) alongside campaign attribution | #139–143, #154–156 | Same root cause one level deeper (`gold_fct_order_items` → `gold_fct_orders` → `gold_fct_order_attribution`, join chain exists, no view uses it) | **New view** — `order_item_records`, §3 |
| No dedicated `catalogue/dimensions/core.yaml` entries for `utm_campaign`, `ship_city`, `shipping_region` on `commerce_orders` (fields exist on the view already) | #83, #120, #144, #337, #349, #384 (city/region breakdowns generally) | Catalogue governance gap identified live in this session, not yet fixed | Additive `core.yaml` entries, no cube change |
| First-touch attribution | #148, #260 | Source data only has last-touch (`gold_fct_order_attribution.lt_*` fields — "lt" = last-touch by construction; no `ft_*` equivalent anywhere in `gold.*`) | **Unsupported — missing source data.** Not a modeling fix; requires a new upstream attribution model in dbt. State this honestly rather than approximating with last-touch. |
| Discount code as a dimension | #127–128, #414–420 | `total_discounts`/`total_line_discounts` are aggregate amounts on `gold_fct_orders`/`gold_fct_order_items`; no cube exposes a `discount_code` dimension anywhere in the 38 cubes read | **Unsupported — missing source data** |
| Inventory (stock levels, days of cover, dead stock) | All of §14 (#360–377) | No inventory cube exists — `gold_fct_product_variant_cost`/`_history` are cost tables, not stock-level tables | **Unsupported — missing source data** |
| Fulfilment / shipping / delivery / RTO / NDR | All of §15 (#378–400) except return-adjacent measures already in `gold_fct_orders`/`gold_int_amazon_return_reconciliation` | No carrier, tracking, or delivery-SLA cube exists in `gold.*` | **Unsupported — missing source data** (return_status/returned_at *do* exist on `gold_fct_orders`, so return-rate-style queries are partially answerable; RTO cost is on `canonical_pnl.rto_cost`, but RTO by carrier/courier is not) |
| Marketplaces beyond Amazon (Blinkit etc.) | #401–412 (partially) | Only Amazon SP + Amazon Ads modeled; no other marketplace cube exists | **Unsupported — missing source data**, correctly so per query #412 ("clearly state when a marketplace API is not yet integrated") |
| Google Ads keyword / search-term / Shopping item-level data | #313, #315–320, #323–324 | `gold_fct_google_ads_daily` grain is campaign×adset×ad×device×network — no keyword, search-term, or Shopping product-item dimension in any Google cube | **Unsupported — missing source data** |
| Payment gateway settlement / invoice / tax-jurisdiction reconciliation | #429–439 | `gold_fct_payments` is transaction-grain (amount, gateway, method, success/refund flags) but has no settlement-batch, invoice, or jurisdiction-tax fields | **Unsupported — missing source data** beyond what `gold_fct_payments`/`gold_fct_amazon_sp_order_pnl` already cover for Amazon |
| Anomaly detection / forecasting engine | §20, §28 alert triggers, #57 (forecast) | Out of scope for a semantic model — these require a stats/ML layer consuming the canonical metrics, not a new cube | **Out of scope for this refactor** — canonical model should expose clean, reconciled time series so an anomaly engine *can* be built on top, not attempt to be one |
| Actions beyond `pause_meta_ad` (order status update, refund trigger, budget change, AWB generation, etc.) | §25–27 | Only one action (`catalogue/actions/pause_meta_ad.yaml`) exists | **Out of scope for the Cube/data layer** — actions are backend-API contracts, not Cube models; flagged for the action-catalogue owner, not this refactor |

Full section-by-section mapping of all 630 query patterns is in
`QUERY_COVERAGE_REPORT.md`.

## 7. What's already correct (do not re-litigate)

To avoid re-doing settled work: `CUBE_AUDIT_REPORT.md` already resolved cube/view
duplication (all 38 cubes `public: false`, `orders_amazon` renamed,
`customer_acquisition_ltv` retired in favor of `customer_ltv`,
`shopify_order_line_items` merged into `product_performance`,
`meta_campaign_attribution` promoted, `channel_pnl` catalogued,
`marketing_performance`/`ad_performance`/`dw_meta_ads_attribution` deprecated). All
16 existing metrics in `catalogue/metrics/*.yaml` resolve correctly to canonical
views with no ambiguity. `gold_dim_customers.acquisition_channel` is the ruled
authoritative source for customer acquisition (§7 Q7 of that report) — the "customer
→ acquisition source" bridge requirement 7 asks for **already exists** via
`customer_ltv`. This audit builds on top of that state; it does not reopen it.
