# Canonical Data Model — Proposed Design

**Status: §§1–10 IMPLEMENTED (2026-07-11); §11's remaining items are follow-up
work, listed at the end.** Companion docs: `CUBE_SEMANTIC_AUDIT.md` (findings this
design responds to) and `QUERY_COVERAGE_REPORT.md` (630 query patterns scored
against this design).

## 0. Correction: the query executor is in this repo, not out of scope

Sections §6, §8, §9 below were originally written assuming "the query executor"
was an external black box outside `cube/` and `catalogue/`. That was wrong —
`Base_Agent/src/seleric_mcp/` **is** a real, tested Python query executor living in
this same repo, with its own pytest suite (`tests/`). It already implements most of
what those sections proposed as future work:

| What this design proposed (§6/§8/§9, as originally written) | Already implemented in `src/seleric_mcp/` |
|---|---|
| Date-range/comparison composition | `app/query_planner.py::resolve_time_range` / `derive_compare_range` — presets, previous-period, previous-year, all IST-normalized |
| Provenance envelope | `app/provenance.py::build_provenance` — query_id, filters, time range, comparison period, freshness, catalogue_version, generated_at |
| Record drill-down | `app/query_planner.py::QueryPlanner.drilldown` — **same-view only**: inherits the parent's metrics/view, adds dimensions/filters, never widens. This is *narrower* than this design's original `drilldown_path` proposal (which implied drilling to a *different* view) — the actual mechanism for cross-view drill-down (e.g. an aggregate on `order_attribution` down to record detail) is a **separate top-level query against `order_records`/`order_item_records`** with the same filters, not a `drilldown()` call. §3 below is unaffected by this correction — the two new views are still the right fix — but the `drilldown_path` metadata field proposed in §5.1 does not correspond to anything the executor currently reads; it was aspirational, not implemented in this pass. |
| Fan-out guard for a specific view | `app/query_planner.py::_guard_breakdown` + `BREAKDOWN_VIEWS = {"meta_ad_breakdown"}` — hardcoded per-view, not the data-driven `required_filters`/`fanout_dimension` metadata this design proposed. `campaign_product_performance`'s SKU fan-out (audit §3) is **not guarded here either**, but is also not currently reachable — it has no catalogue metric mapped to it, so the query planner's single-view/catalogue-gated path can't be used to trigger it. Low priority until/unless a metric is added against that view. |
| Term/metric resolution with confidence bands | `catalogue_service/service.py::CatalogueService.resolve_term` — exact match, deprecated-alias match, then fuzzy match with auto-resolve/ambiguous/unknown bands. This is exactly the mechanism that produced the `"kind": "resolved"` / `"suggestions"` responses seen live in this session. |
| Catalogue integrity enforcement | `catalogue_service/loader.py::_check_integrity` — **fail-fast at load time** if a metric references an unregistered view or a dimension with no mapping for that view. Every catalogue addition in this implementation pass had to satisfy this or the entire catalogue fails to load. |
| Live-schema drift detection | `catalogue_service/validate.py::validate_against_cube` — checks every catalogued metric's Cube members against a **live** Cube `/v1/meta` and marks missing ones `status="broken"`. Exercised during this implementation (see §11 note on `cube_mcp` drift below). |

This significantly changes the risk profile of "refactoring the catalogue mappings":
it isn't just YAML — `_check_integrity` means a malformed addition breaks the whole
catalogue for every consumer. Every change in this pass was verified against the
real loader via `uv run pytest tests/ -m "not live"`, not just eyeballed.

All YAML in this document is **illustrative** — it shows the shape of the proposed
change, not a diff to apply verbatim. Nothing here has been written to
`cube/model/` or `catalogue/` yet.

---

## 1. Design principles

1. **One fact per real-world event, one dimension per real-world entity.** No new
   fact is created if an existing one already carries the grain (this ruled out,
   for example, adding a new "order with attribution" *fact* — it's a *view*
   composition of two existing facts, §3).
2. **Views are the only public surface.** Already true as of `CUBE_AUDIT_REPORT.md`
   (all 38 cubes `public: false`). This design adds new views, not new public cubes.
3. **Declarative joins over inline SQL wherever the grain allows it.** New bridge
   views should compose existing `joins:` relationships (engine-verified, §3 of the
   semantic audit) rather than add more hand-written `sql:` bridge cubes (unverified,
   same section). The two new views proposed below (§3) need **zero new SQL** — they
   only recombine `includes:` from already-joined cubes.
4. **A metric is defined once, in one `catalogue/metrics/<id>.yaml` file, in the
   extended schema (§5).** No metric is ever computed by two independently-written
   SQL expressions if one can reference the other (e.g. `total_cogs` is currently
   `= net_cogs` on `canonical_pnl` and MUST stay that way, not be recomputed
   elsewhere).
5. **Every canonical fact/view states its own fan-out risk and required filters
   explicitly** — not just in a code comment, but in a field the query executor can
   read (`required_filters`, §5) and reject on.
6. **Grain-unsafe requests are rejected, not silently approximated.** If a query
   asks for a metric at a grain the canonical model can't provide safely (e.g.
   product-level ad spend, §6 of the audit), the correct behavior is an explicit
   "unsupported — missing source data" response (requirement 9/11), never a
   best-effort join that could double-count or misattribute.

---

## 2. Canonical facts and dimensions

This is a *renaming/organizing* pass over the existing 38 cubes, not new tables.
Every fact below already exists; this section states its canonical role so future
model additions have one obvious place to attach to instead of spawning a parallel
cube (the failure mode `CUBE_AUDIT_REPORT.md` fixed once already).

### Facts

| Canonical fact | Cube(s) | Grain | Status |
|---|---|---|---|
| Order (Shopify) | `gold_fct_orders` | brand × order_id | ✅ existing, canonical |
| Order (Amazon) | `gold_fct_amazon_sp_orders` | brand × amazon_order_id | ✅ existing, canonical — kept platform-separate (§4) |
| Order Item (Shopify) | `gold_fct_order_items` | brand × order_id × line_item_id | ✅ existing, canonical |
| Order Item (Amazon) | `gold_fct_amazon_order_items` | brand × amazon_order_id × order_item_id | ✅ existing, canonical |
| Order Attribution (last-touch, Shopify) | `gold_fct_order_attribution` | brand × order_id (1:1 with Order) | ✅ existing; **first-touch does not exist in source data** — see audit §6 |
| Order-level P&L (Amazon settlement) | `gold_fct_amazon_sp_order_pnl` | brand × amazon_order_id (1:1) | ✅ existing, canonical |
| Payment Transaction | `gold_fct_payments` | brand × transaction_id | ✅ existing, canonical |
| Refund Event (Shopify) | `gold_refund_events` | brand × refund_line_item | ✅ existing, canonical |
| Return Reconciliation (Amazon) | `gold_int_amazon_return_reconciliation` | record_id | ✅ existing, canonical |
| Ad Performance — Meta | `gold_fct_meta_ads_daily` / `_hourly` / `_breakdown_daily` | date(×hour)(×breakdown) × account × campaign × adset × ad | ✅ existing, canonical, distinct grains legitimate |
| Ad Performance — Google | `gold_fct_google_ads_daily` / `_campaigns_hourly` | date(×hour) × campaign × adset × ad × device × network | ✅ existing, canonical |
| Ad Performance — Amazon | `gold_fct_amazon_ads_campaigns_daily` | brand × campaign × date | ✅ existing, canonical |
| Ad Change Event | `gold_fct_meta_ads_status_history` / `gold_fct_google_ads_status_history` | brand × entity_type × entity_id × changed_at | ✅ existing, canonical |
| Company P&L rollup | `gold_fct_daily_pnl` | brand × report_date | ✅ existing, canonical |
| Channel P&L rollup | `gold_channel_pnl` | brand × report_date × platform | ✅ existing, canonical |
| Payment-method P&L rollup | `gold_payment_method_pnl` | brand × report_date × payment_method | ✅ existing, canonical |
| Session (funnel) | `gold_fct_session_funnel` | brand × session_id | ✅ existing, canonical |
| Product Variant Cost (current / history) | `gold_fct_product_variant_cost` / `_history` | brand × variant_id (×effective_from) | ✅ existing, canonical |
| Campaign × Product attribution rollup | `gold_campaign_product_performance` | brand × report_date × platform × campaign × sku | ✅ existing; fan-out warning needs surfacing (§4 of audit) |
| Creative tag catalog / mapping | `gold_dim_neurohack`, `gold_ad_neurohack_enriched` | tag_code / brand×ad×tag | ✅ existing, canonical |

### Dimensions

| Canonical dimension | Cube(s) | Status |
|---|---|---|
| Customer | `gold_dim_customers` | ✅ existing, canonical — acquisition fields authoritative here (ruled in `CUBE_AUDIT_REPORT.md` §7 Q7) |
| Campaign / Adset / Ad (cross-platform master) | `gold_dim_campaign`/`_adset`/`_ad` | ✅ existing, join-only (kept non-public per `CUBE_AUDIT_REPORT.md` §7 Q4 — no browsing use case yet) |
| Date / calendar | *none dedicated* | See §6 — handled at query-execution layer via each fact's own time dimension + `partial_day_policy`, not a shared calendar cube. No gap for standard period math; a gap only for fiscal-calendar features nobody has asked for yet. |

**No new fact or dimension cube is proposed.** Every gap identified in the semantic
audit (§6) is either (a) a missing *view* over existing facts — fixed in §3 below —
or (b) missing *source data* that no amount of Cube modeling can fabricate — listed
honestly in `QUERY_COVERAGE_REPORT.md` as unsupported rather than approximated.

---

## 3. New bridge views (the core of this design)

### 3.1 `order_records` — campaign → order → city

**Directly answers Scenario B and query catalogue #136–153, #256.** This was the
exact capability gap that failed live in this session (`order_attribution.order_id`
/ `shipping_city` both rejected as unknown).

**Why no new cube is needed:** `gold_fct_orders` already declares
`joins: [gold_fct_order_items (1:M), gold_fct_order_attribution (1:1), gold_dim_customers (M:1)]`.
The `1:1` join to attribution means a view rooted at `gold_fct_orders` can safely
pull attribution fields onto the same row with no fan-out risk — Cube resolves `1:1`
joins as a plain join, not a fan-out join. This view is **order grain**
(brand × order_id), matching `gold_fct_orders`'s own primary key.

```yaml
# ILLUSTRATIVE — proposed addition to cube/model/views/serve_views.yml
- name: order_records
  title: Order Records (Gold)
  description: >
    Order-grain record view: one row per order, joining commerce order economics
    (gold_fct_orders) with last-touch attribution (gold_fct_order_attribution, 1:1)
    and customer type (gold_dim_customers, many_to_one). Record-level drill-down
    target for commerce_orders and order_attribution. Safe at order grain — do not
    join order_items onto this view (would fan out order-level revenue).
  cubes:
    - join_path: gold_fct_orders
      includes:
        - order_id
        - order_name
        - order_date
        - order_status
        - return_status
        - net_revenue
        - net_revenue_excl_tax
        - gross_revenue
        - payment_method
        - is_cod
        - is_new_customer
        - is_guest_checkout
        - is_test
        - ship_city
        - ship_province
        - ship_country
        - shipping_pincode
        - brand_id
    - join_path: gold_fct_orders.gold_fct_order_attribution
      includes:
        - lt_platform
        - lt_channel
        - lt_campaign_id
        - lt_campaign_name
        - lt_adset_id
        - lt_adset_name
        - lt_ad_id
        - lt_ad_name
        - attribution_method
        - attribution_confidence
    - join_path: gold_fct_orders.gold_dim_customers
      includes:
        - is_repeat_customer
```

Resulting capability: filter `lt_campaign_name = 'TH-383-SUSPENDER-20JUNE'` and
`order_date` in the last 7 completed days, return `order_id`, `order_name`,
`order_date`, `net_revenue`, `is_new_customer`, `ship_city`, `ship_province`,
`lt_platform`, `attribution_method` per order (Scenario B's record list), or group by
`ship_city` for the summary — both from **one view, one query shape**, exactly
matching requirement 7's example and the query catalogue's #152/#153/#256.

**Drill-down declaration:** `commerce_orders` and `order_attribution`'s metric
entries should set `drilldown_path: order_records` (§5) so a query executor knows
where "drill from a daily total to records" (#157) or "show the exact records used
to calculate a metric" (#158) should go.

### 3.2 `order_item_records` — campaign → order → order item, SKU → orders

**Answers #139–143, #154–156** ("show all items in a specified order," "list orders
containing a specified SKU," "drill from campaign to orders to order items," "drill
from SKU revenue to individual orders").

**Why no new cube is needed:** the join chain already exists two hops deep —
`gold_fct_order_items` ⋈(M:1) `gold_fct_orders` ⋈(1:1) `gold_fct_order_attribution`.
Rooting the view at `gold_fct_order_items` (the finest grain in the chain) means
pulling order- and attribution-level dimensions onto each line-item row is safe
(many-to-one and 1:1 traversals never fan out); it is item-level measures (already
correctly scoped to their own cube) that stay correctly grained.

```yaml
# ILLUSTRATIVE — proposed addition to cube/model/views/serve_views.yml
- name: order_item_records
  title: Order Item Records (Gold)
  description: >
    Line-item-grain record view: one row per order line item, joining SKU/product/
    cost/margin (gold_fct_order_items) with parent order economics (gold_fct_orders,
    many_to_one) and last-touch attribution (gold_fct_order_attribution, via the
    1:1 order->attribution join). Record-level drill-down target for
    product_performance and campaign_product_performance.
  cubes:
    - join_path: gold_fct_order_items
      includes:
        - line_item_id
        - order_id
        - sku
        - product_title
        - variant_id
        - quantity
        - unit_price
        - total_price
        - total_discount
        - net_revenue
        - total_cost
        - net_cost
        - gross_margin
        - return_status
        - brand_id
        - order_date
    - join_path: gold_fct_order_items.gold_fct_orders
      includes:
        - order_name
        - order_status
        - ship_city
        - ship_province
        - is_new_customer
        - payment_method
    - join_path: gold_fct_order_items.gold_fct_orders.gold_fct_order_attribution
      includes:
        - lt_platform
        - lt_campaign_name
        - lt_adset_name
        - lt_ad_name
        - attribution_method
```

**Fan-out check for this view specifically:** none. Every join traversed
(`order_items → orders`: many-to-one; `orders → attribution`: one-to-one) is
fan-out-safe by Cube's own cardinality resolution. This view must **never** be used
to compute order-level totals like `net_revenue` grouped only by `order_id` if the
intent is to match `gold_fct_orders.net_revenue` exactly — line-item `net_revenue`
sums to the same figure only when no revenue adjustment lines exist; that caveat
already exists on `product_performance` today and carries over unchanged.

### 3.3 Existing bridges already satisfy the other requirement-7 examples

- **"product → ad spend → margin"**: `gold_campaign_product_performance`
  (→ `campaign_product_performance` view) already joins attribution + order items +
  campaign-level ad spend at the SKU × campaign × day grain. **Gap:** ad spend is
  joined at campaign grain and duplicates across SKUs sold under that campaign on
  the same day (documented in the cube's own comment, not surfaced anywhere query
  executors can see it). **Fix:** add `required_filters: []` but
  `fanout_dimension: campaign_id` metadata (§5) and a loud description warning, the
  same treatment already given to `meta_ad_breakdown`. **True SKU-level ad spend**
  (spend attributed to one specific product, not a whole campaign) does not exist in
  any source table — correctly flagged unsupported in `QUERY_COVERAGE_REPORT.md`,
  not approximated.
- **"customer → acquisition source"**: already done — `gold_dim_customers` /
  `customer_ltv` carries `acquisition_channel`/`acquisition_platform`/
  `acquisition_campaign`/`first_order_cohort_month` directly, ruled authoritative in
  `CUBE_AUDIT_REPORT.md` §7 Q7. No new bridge needed.

---

## 4. Why Shopify and Amazon orders stay separate facts (not merged)

Requirement 3 asks for a canonical model "for orders" — this is intentionally **not**
a single unioned order fact. Reasons, re-confirmed from the semantic audit:

- Different primary key namespace (`order_id` vs `amazon_order_id`), different date
  axis (`order_date` vs `purchase_date`), different currency/tax treatment (GST
  handling differs from Amazon's settlement-based fee model), different revenue
  recognition basis (`gross_revenue`/`net_revenue` on Shopify vs.
  `effective_gross_revenue ?? estimated_gross_revenue` on Amazon).
- A unioned *record-grain* view would require a synthetic cross-platform order key
  and a lossy reconciliation of incompatible revenue bases — exactly the kind of
  "invented join" requirement 9 prohibits.
- Blending is already done correctly, at the *only* grain where it's safe: the daily
  P&L rollup (`canonical_pnl.total_orders = total_orders + amazon_orders`,
  `canonical_pnl.net_revenue_excl_tax` includes both). This is preserved unchanged.
- If a genuine business need for order-grain blended browsing emerges later
  (`orders_blended`, floated as an option in `CUBE_AUDIT_REPORT.md` §7 Q2 and
  declined), it should be a **new, explicitly-scoped view** unioning only the
  columns that are genuinely comparable (order_id/amazon_order_id as a tagged union
  key, order_date/purchase_date aliased to one `order_date` dimension,
  platform-tagged revenue), not a blind `UNION ALL`. Not proposed here because no
  query in the capability catalogue requires order-grain (not just P&L-grain)
  cross-platform blending.

---

## 5. Metric registry: extended schema + P0 gap list

### 5.1 Extended schema (additive to the existing 16 files' structure)

```yaml
# ILLUSTRATIVE target shape for catalogue/metrics/<id>.yaml — additive fields only,
# existing fields (id, display_name, category, status, description, formula,
# cube_mapping, aggregation, unit, grain, supported_dimensions, supported_filters,
# data_owner, access_policy, examples, validation_tests, deprecated_aliases) unchanged.
business_definition: >
  One sentence, board-readable, no SQL — distinct from `description`, which may
  carry implementation caveats.
calculation_service: cube            # cube | derived (computed by the query executor
                                      # from >1 cube measure, e.g. period-over-period %)
required_filters: []                 # e.g. [breakdown_type] on meta_ad_breakdown-derived metrics
time_dimension: report_date          # the ONE canonical time axis for this metric
default_timezone: Asia/Kolkata
comparison_support: [previous_period, previous_weekday, yoy, rolling_7d, rolling_30d]
drilldown_path: order_records        # or null if the metric has no record-grain drill-down
record_entity: order                 # order | order_item | ad | session | customer | null
source_models: [gold.fct_orders, gold.fct_order_attribution]
row_level_policy: brand_id           # dimension the access layer must scope by
freshness_sla: "daily, T-1, IST"     # moved here from catalogue/views.yaml (view-level
                                      # freshness stays too, for views with no metric yet)
partial_day_policy: exclude_current_incomplete_day   # or: flag_partial | include_with_warning
synonyms: [attributed revenue, last-touch revenue]   # mirrors glossary/terms.yaml,
                                                      # kept in sync, not a replacement for it
deprecated_by: null                  # forward pointer, for when a metric IS deprecated
fanout_dimension: null               # e.g. sku, breakdown_type — a dimension that MUST
                                      # be filtered to exactly one value before this
                                      # metric can be safely summed across it
```

`glossary/terms.yaml` stays as the free-text-term → metric-id resolver (that's a
different job — fuzzy natural-language matching — from the per-metric `synonyms`
list, which is a fixed, curated set for exact-match/autocomplete use cases). Both
should list the same synonyms for a given metric; this is a sync discipline, not a
schema conflict.

### 5.2 New metric files needed (P0, from audit §4/§5)

Every one of these already exists as a measure on a canonical view; they only need a
`catalogue/metrics/<id>.yaml` file in the schema above — **no cube change**:

| New metric id | View.measure | Why P0 |
|---|---|---|
| `google_spend` | `canonical_pnl.google_spend` (or a new `google_ad_performance.spend` mapping) | Query #312 |
| `amazon_ad_spend` | `canonical_pnl.amazon_spend` / `amazon_ad_performance.spend` | Query #401, #411 |
| `google_roas` | `google_ad_performance.roas` | Query #314 |
| `amazon_ads_roas` | `amazon_ad_performance.ads_roas` | Query #411 |
| `active_orders` | `canonical_pnl.active_orders` / `commerce_orders.active_orders` | Query #100 |
| `cancelled_orders` | `commerce_orders.cancelled_orders` | Query #101 |
| `refunded_orders` | `commerce_orders.refunded_orders` | Query #102 |
| `prepaid_orders` | `commerce_orders.prepaid_orders` | Query #104 |
| `cod_orders` | `commerce_orders.cod_orders` | Query #105 |
| `units_sold` | `product_performance.total_quantity` | Query #108, #161–166 |
| `gross_profit` (SKU grain) | `product_performance.gross_profit_ex_gst` — **note:** a `gross_profit` metric id already exists mapped to `canonical_pnl` (company grain); this needs a distinct id (e.g. `product_gross_profit`) to avoid the exact ambiguity pattern flagged in audit §4 | Query #161, #166 |
| `refund_amount` | `refund_events.refund_amount` / `payment_cashflow.refund_amount` | Query #94, #430 |
| `sessions` / `conversion_rate` | `session_funnel.sessions` / `.overall_conversion_rate` | Query #344, #109 |
| `channel_net_profit` | `channel_pnl.channel_net_profit` | Query #204, #328 |
| `payment_method_net_profit` | `payment_method_pnl.net_profit` | Query #202-ish (P&L by channel/payment) |

This list is illustrative of the *pattern and priority*, not exhaustive — a full
pass should be done against every P0 line item in
`mcp_query_capability_catalogue.md` §33 as an implementation task, using this table's
method (existing measure → new catalogue file, no cube change) as the template.

---

## 6. Runtime composition (requirement 6) — what's a Cube feature vs. a query-executor responsibility

The capability catalogue asks for period comparisons, % change, ranking,
contribution analysis, and record drill-down "at runtime." None of these require new
Cube models; they require the **query executor** (the MCP layer, outside this
repo's `cube/` and `catalogue/` scope) to compose already-declared metric metadata
correctly:

| Capability | Mechanism | New model needed? |
|---|---|---|
| Date ranges, granularity (day/week/month/hour) | Cube's native `timeDimensions[].granularity` | No — every fact cube already has a `type: time` dimension |
| Previous-period / YoY / rolling-N-day comparison | Two Cube queries (current range, comparison range) composed by the executor, using `comparison_support` (§5) to validate the request is meaningful for that metric | No |
| % change, contribution analysis, ranking (top-N/bottom-N) | Post-processing in the executor over one or two Cube result sets — deterministic arithmetic, not Cube SQL, matching requirement 6's "numerical calculations are performed outside the LLM" (capability catalogue §34.7) | No |
| Record drill-down | Executor follows `drilldown_path` (§5) from the aggregate metric to the record-grain view (`order_records`/`order_item_records`, §3), applying the same filters | No — this is exactly why `drilldown_path` needs to exist as metadata |
| "Exclude incomplete current day" | Executor applies `partial_day_policy` (§5) using each metric's `freshness_sla` to decide whether "today" is complete | No — needs the metadata field, not a new cube |

**This section is the answer to "why can't the MCP just join on the fly"** (asked
live in this session): it isn't that Cube *can't* do runtime composition — it's that
composition must be built from **pre-declared, safe building blocks**
(`comparison_support`, `drilldown_path`, `fanout_dimension`, `required_filters`)
rather than improvised per-request, which is exactly what requirement 9 prohibits
("the LLM must not invent SQL, formulas, or joins"). The gap today isn't a missing
Cube capability; it's missing metadata for the executor to compose safely.

---

## 7. Fan-out prevention — formalized rule set

1. A view may pull dimensions from a joined cube reached via `one_to_one` or
   `many_to_one` (from the view's root) with no restriction.
2. A view must **never** pull a measure from a cube reached via `one_to_many` from
   its root without either (a) rooting the view at the many-side instead, or
   (b) explicitly declaring the aggregation is pre-grouped (as `gold_fct_daily_pnl`
   etc. already do in their inline SQL).
3. Any cube/view whose safe use requires filtering to exactly one value of some
   dimension before summing (`gold_fct_meta_ads_breakdown_daily.breakdown_type`,
   `gold_mart_meta_ad_neurotag_daily`'s `*_fc` fields by `tag_code`, and now also
   `gold_campaign_product_performance.spend` by `sku`, per audit §3) must declare
   that dimension in `fanout_dimension` (§5) or `required_filters`, and the warning
   must appear in the view's `description`, not only a code comment.
4. Every inline-SQL bridge cube must declare an explicit composite primary key
   (audit §2's 8-cube gap) — mechanical fix, proposed as:

```yaml
# ILLUSTRATIVE — example for gold_channel_pnl.yml
dimensions:
  - name: channel_pnl_key
    sql: "concat(toString(brand_id),'|',toString(report_date),'|',platform)"
    type: string
    primary_key: true
```
   Applied identically (with the right column list) to all 8 cubes listed in audit
   §2.

---

## 8. Provenance / response contract (requirement 10)

Every query result the executor returns should carry, alongside the data:

```yaml
provenance:
  query_id: <uuid>
  metric_ids: [attributed_orders]
  dimensions: [lt_campaign_name, ship_city]
  filters_applied: [{field: lt_campaign_name, op: equals, value: "TH-383-SUSPENDER-20JUNE"}, {field: order_date, op: last_n_days, value: 7}]
  source_views: [order_records]
  grain: order
  timezone: Asia/Kolkata
  comparison_period: null            # or the comparison range if one was requested
  freshness: {source: gold.fct_orders, expected_cadence: "daily, T-1, IST", as_of: <timestamp>}
  cache_status: live                 # always "live" today — no pre-aggregations (audit §1)
  warnings: []                       # e.g. fanout risk suppressed by required_filters, partial-day exclusion applied
```

This is a **response-envelope contract for the query executor**, not a Cube model
change — listed here because requirement 10 is part of this goal and the contract's
fields map directly onto the metric-schema additions in §5 (nothing in this envelope
requires data the extended schema doesn't already supply).

---

## 9. Access control and rejection rules (requirements 4, 11)

- **Row-level policy** (`row_level_policy: brand_id` on every metric, §5) is a
  declaration for the executor to enforce — Cube itself supports
  `queryRewrite`/security-context row-level filtering at the deployment layer
  (`cube_mcp`, out of scope per your last decision to leave that deployment
  untouched). This design only adds the *metadata* the enforcement layer needs.
- **Sensitive fields** (customer email/phone, order PII) should get a
  `sensitive_classification` on the relevant dimensions (per capability catalogue
  §32's record-entity field list) — today `gold_dim_customers.email`/`.phone` and
  `gold_fct_orders.customer_email` exist as plain dimensions with no such flag. This
  is a **new field on existing dimension declarations**, not a new cube.
- **Rejection responses** (requirement 11) should be generated from the same
  metadata, deterministically:
  - Unsupported dimension → "no such dimension on this metric" + nearest
    `supported_dimensions` suggestion (already partially implemented — this is what
    produced the helpful `"suggestions"` array in the live failure earlier in this
    session; extend the same pattern to metric-id resolution errors, which currently
    return suggestions but not a plain-English explanation).
  - Incompatible grain → compare requested `record_entity`/grain against the
    metric's declared `grain`; reject with the mismatch stated explicitly.
  - Missing join path → if the requested dimension pair has no common view (e.g.
    "campaign + shipping city" before `order_records` existed), respond with
    query #35's exact ask: state the missing model/join required, referencing this
    document.
  - Fan-out risk → if `required_filters`/`fanout_dimension` isn't satisfied, reject
    with the specific dimension that must be filtered (query #526).

---

## 10. What this design deliberately does not do

- Does not merge Shopify and Amazon orders into one fact (§4).
- Does not fabricate inventory, fulfilment/shipping, discount-code, or
  marketplace-beyond-Amazon models — flagged as missing source data in
  `QUERY_COVERAGE_REPORT.md`, not approximated.
- Does not design an anomaly-detection or forecasting engine — out of scope for a
  Cube/catalogue refactor; this design's job is to make the underlying metrics clean
  and reconciled enough that such an engine could be built on top later.
- Does not design new backend actions beyond the existing `pause_meta_ad` — actions
  are backend-API contracts owned elsewhere, not Cube models.
- Does not touch `cube_mcp/` (the live deployment) — per your explicit prior
  decision in this session, changes stay scoped to `Base_Agent`.

---

## 11. Implementation order (once this design is approved)

1. Add composite primary keys to the 8 cubes missing one (§7.4) — mechanical,
   zero behavior change.
2. Add `order_records` and `order_item_records` views (§3) — unlocks Scenario B and
   all of query catalogue §5.
3. Backfill `catalogue/dimensions/core.yaml` with the already-existing-but-
   uncatalogued dimensions (`utm_campaign`, `ship_city`, `shipping_region` on
   `commerce_orders`; `order_id` intentionally stays uncatalogued on
   `order_attribution` now that `order_records` is the record-grain answer).
4. Extend the metric schema (§5.1) on all 16 existing metric files (additive,
   non-breaking), then add the P0 new metric files (§5.2).
5. Surface the `campaign_product_performance` fan-out warning into its view
   description and the `ANTI_PATTERNS` dict (audit §3), matching the treatment
   already given to `meta_ad_breakdown` and the neurotag `*_fc`/`*_sc` pattern.
6. Re-run `cube/scripts/generate_semantic_catalog.py` to pick up the new views.
7. Write reconciliation/grain/join/acceptance tests against
   `QUERY_COVERAGE_REPORT.md`'s "supported" rows (requirement 12).
8. Re-score `QUERY_COVERAGE_REPORT.md` after implementation to confirm the intended
   supported/partial/unsupported movement actually happened.

Each step is additive and independently revertable — no step requires removing or
renaming anything that already works.

## 12. Implementation status (2026-07-11)

| §11 step | Status | Notes |
|---|---|---|
| 1. Composite primary keys on the 8 cubes | ✅ Done | Mechanical `concat(...)` keys added to `gold_channel_pnl`, `gold_payment_method_pnl`, `gold_hourly_commerce`, `gold_daily_performance`, `gold_customer_acquisition_ltv`, `gold_campaign_product_performance`, `gold_meta_campaign_attribution`, `gold_neurohack_attribution`. Verified by `tests/test_canonical_model.py::test_synthesized_keys_present_in_cube_yaml`. |
| 2. `order_records` / `order_item_records` views | ✅ Done | Added to `cube/model/views/serve_views.yml`, zero new SQL, composed from the pre-existing `gold_fct_orders` ⋈ `gold_fct_order_attribution` (1:1) and `gold_fct_order_items` ⋈ `gold_fct_orders` (M:1) joins. Registered in `catalogue/views.yaml`. Two new metrics (`order_record_count`, `order_item_record_count`) so they're reachable through `QueryPlanner`. |
| 3. Backfill `catalogue/dimensions/core.yaml` | ✅ Done (for the views touched this pass) | Added `shipping_city`, `utm_campaign`, `order_id`, `order_name`, `order_status`, `return_status`, `is_new_customer`, `attribution_method`, `sku`, `product_title`, `session_date`, plus view-mappings extending `lt_platform`/`lt_channel`/`lt_campaign_id`/`lt_campaign_name`/`lt_adset_name`/`lt_ad_name`/`payment_method`/`shipping_region`/`campaign_id`/`campaign_name`/`adset_name`/`ad_id`/`ad_name`/`brand_id`/`report_date`/`order_date` onto `order_records`, `order_item_records`, `google_ad_performance`, `product_performance`, `session_funnel`. |
| 4. Extend metric schema (§5.1) + add P0 metrics (§5.2) | ⚠️ Partial, deliberately | **13 new metric files added** (not the full illustrative list in §5.2 — scoped to what could be fully verified in one pass): `order_record_count`, `order_item_record_count`, `active_orders`, `cancelled_orders`, `refunded_orders`, `prepaid_orders`, `cod_orders`, `channel_net_profit`, `google_spend`, `google_roas`, `units_sold`, `sessions`, `session_conversion_rate`. **Not done:** `amazon_ad_spend`/`amazon_ads_roas` (needs `amazon_ad_performance` registered — same pattern, not applied), `refund_amount` (needs `refund_events` registered), `payment_method_net_profit` (needs `payment_method_pnl` registered) — all straightforward follow-ups using the exact same pattern as what was done for `google_ad_performance`/`product_performance`/`session_funnel`. **The §5.1 extended `MetricDef` schema (14 new fields like `drilldown_path`, `partial_day_policy`, `required_filters`) was deliberately NOT implemented** — that requires editing `src/seleric_mcp/catalogue_service/loader.py`'s Pydantic model (real application code behind a passing test suite, not just YAML), which is a different risk class than the additive YAML/cube work done in this pass. Flagged for separate, explicit review rather than bundled in silently. |
| 5. Surface `campaign_product_performance` fan-out warning | ❌ Not done | Still only a code comment. Deferred: no metric is currently catalogued against this view (confirmed via `_check_integrity`'s reachability), so the risk isn't exploitable through the query planner today — lower priority than the items above. |
| 6. Re-run `generate_semantic_catalog.py` | ✅ Done | Regenerated `cube/catalog/gold_semantic_catalog.{json,yaml}`. |
| 7. Reconciliation/grain/join/acceptance tests | ✅ Done | `tests/test_canonical_model.py` — 10 new tests: the Scenario B query pattern end-to-end (campaign + city, one view, one query), order/order-item view separation (grain safety), rejecting cross-grain dimension requests, the previously-uncatalogued commerce status metrics resolving correctly, ratio-component auto-inclusion for `google_roas`, primary-key presence, and the `public: false` invariant across all 38 cubes. All pass; full non-live suite is 63/63 passing (53 pre-existing + 10 new), zero regressions. |
| 8. Re-score `QUERY_COVERAGE_REPORT.md` | ✅ Done | See that document's changelog note at the top. |

**Important caveat discovered during implementation, not before:** this repo
(`Base_Agent`) is a *staging* copy of the Cube model — the actual query executor
(`src/seleric_mcp`) talks to a **live** Cube deployment over HTTP
(`cube_api_url`, default `http://127.0.0.1:4001`, matching the `cube_mcp/`
docker-compose stack). Running the test suite's live drift check
(`uv run pytest -m live`) against a reachable instance found `channel_pnl.report_date`
missing from that live server's schema — i.e. **`cube_mcp`'s deployed copy is
already out of sync with `Base_Agent/cube`**, independent of anything changed in
this session. Every new view/cube/metric added in this implementation is correct
and fully verified *within `Base_Agent`* (offline `_check_integrity` +
`QueryPlanner` tests all pass), but **will show as `status="broken"` by the live
drift check, and won't actually serve data, until someone deploys
`Base_Agent/cube` → `cube_mcp/semantic_layer_serve`** — a deliberate, separate
deploy step outside this session's scope (per your explicit instruction earlier
to leave `cube_mcp` untouched). This is the single most important operational
fact to carry forward: **the design and the offline model are done and tested;
they are not live until deployed.**
