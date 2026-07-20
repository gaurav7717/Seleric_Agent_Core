from seleric_mcp.catalogue_service.service import (
    AmbiguousTerm,
    ResolvedTerm,
    UnknownTerm,
)


def test_loads_seed(catalogue):
    # Commerce + Product + Paid Media certified surfaces — pin to baseline minimum.
    assert len(catalogue.cat.metrics) >= 23
    assert "commerce_net_revenue" in catalogue.cat.metrics
    assert "product_net_revenue" in catalogue.cat.metrics
    assert "meta_spend" in catalogue.cat.metrics
    assert "google_spend" in catalogue.cat.metrics
    assert "amazon_ads_spend" in catalogue.cat.metrics
    assert catalogue.version
    assert catalogue.cat.openmetadata is not None
    # Keep in step with openmetadata/product_registry.yml and
    # catalogue/openmetadata/registry.yaml — includes AmazonCommerce,
    # AmazonAccounts, ChannelAttribution, CustomerData, SessionFunnel,
    # EventStream plus CanonicalPnl / ReturnsRefunds.
    assert len(catalogue.cat.openmetadata.data_products) == 15
    assert len(catalogue.cat.openmetadata.metrics) == len(catalogue.cat.metrics)
    assert catalogue.cat.openmetadata.contracts
    assert catalogue.cat.openmetadata.ontology is not None
    assert catalogue.cat.brands is not None
    assert catalogue.cat.brands.default_brand_id == "20"
    assert any(b.id == "26" and "sniff" in b.name.lower() for b in catalogue.cat.brands.brands)


def test_resolve_brand_default_and_named(catalogue):
    from seleric_mcp.catalogue_service.service import ResolvedBrand

    th = catalogue.resolve_brand("Tilting Heads")
    assert isinstance(th, ResolvedBrand)
    assert th.brand_id == "20"
    sniff = catalogue.resolve_brand("sniff theory")
    assert isinstance(sniff, ResolvedBrand)
    assert sniff.brand_id == "26"
    urth = catalogue.resolve_brand("Urthend")
    assert isinstance(urth, ResolvedBrand)
    assert urth.brand_id == "25"


def test_openmetadata_orders_om_name(catalogue):
    link = catalogue.cat.openmetadata.metrics["orders"]
    assert link.om_name == "orders"
    assert "Commerce.TotalOrders" in link.glossary


def test_search_paid_media_glossary(catalogue):
    result = catalogue.search("meta spend")
    assert result.matches
    assert result.matches[0].id == "meta_spend"


def test_search_glossary_term(catalogue):
    result = catalogue.search("topline")
    assert result.matches
    assert result.matches[0].id == "commerce_net_revenue_daily"
    assert result.matches[0].matched_on.startswith("glossary")


def test_search_unknown_returns_suggestions_not_guesses(catalogue):
    result = catalogue.search("zzzz frobnicator")
    assert result.matches == []
    assert isinstance(result.suggestions, list)


def test_resolve_term_asp(catalogue):
    r = catalogue.resolve_term("ASP")
    assert isinstance(r, ResolvedTerm)
    assert r.metric_id == "average_selling_price"


def test_resolve_deprecated_alias(catalogue):
    # refunded_orders declares deprecated_aliases: [returned_orders]
    r = catalogue.resolve_term("returned_orders")
    assert isinstance(r, ResolvedTerm)
    assert r.metric_id == "refunded_orders"
    assert r.deprecation_notice


def test_resolve_total_orders_all_channels(catalogue):
    for term in ("Total Orders", "order count", "orders"):
        r = catalogue.resolve_term(term)
        assert isinstance(r, ResolvedTerm), term
        assert r.metric_id == "total_orders", term
    r = catalogue.resolve_term("shopify orders")
    assert isinstance(r, ResolvedTerm)
    assert r.metric_id == "orders"


def test_resolve_pnl_metrics_glossary(catalogue):
    cases = {
        "Gross Sales (Ex-GST)": "gross_sales",
        "Returns": "return_revenue",
        "Cancelled": "cancel_revenue",
        "Net Sales (Ex-GST)": "commerce_net_revenue_daily",
        "Taxes (18% on Shopify Net)": "taxes_on_net_sales",
        "Product Cost": "product_cost_all_channels",
        "Amazon Platform Fees": "amazon_platform_fees",
        "Shipping Cost (Courier)": "shipping_cost",
        "RTO Logistics Cost": "rto_cost",
        "Total Operating Cost": "total_operating_cost_all_channels",
        "Total Sales (Including GST)": "total_sales_all_channels",
        "Total Performance Marketing": "total_ad_spend",
        "Total Ad Spend (all platforms)": "total_ad_spend",
        "Total Ad Spend": "total_ad_spend",
        "Meta Ads": "meta_spend",
        "Google Ads": "google_spend",
        "Amazon Ads": "amazon_ads_spend",
        "P&L Net Profit": "net_profit_all_channels",
        "Net Profit (all channels)": "net_profit_all_channels",
        "Shopify-only Net Profit": "net_profit",
        "shopify only net profit": "net_profit",
        "Historical all channels Net Profit": "net_profit_incl_amazon",
    }
    for term, expected in cases.items():
        r = catalogue.resolve_term(term)
        assert isinstance(r, ResolvedTerm), f"{term} -> {r}"
        assert r.metric_id == expected, f"{term}: got {r.metric_id}"


def test_resolve_unknown(catalogue):
    r = catalogue.resolve_term("quantum flux")
    assert isinstance(r, UnknownTerm)


def test_resolve_normalized_exact_match(catalogue):
    # Bare "total sales" = all channels (Shopify + Amazon) via glossary.
    for variant in ("total sales", "Total Sales"):
        r = catalogue.resolve_term(variant)
        assert isinstance(r, ResolvedTerm), variant
        assert r.metric_id == "total_sales_all_channels"
        assert r.confidence == 1.0
        assert r.auto_resolved is False
    # Hyphen/underscore form matches the Shopify-only metric id exactly.
    r = catalogue.resolve_term("TOTAL-SALES")
    assert isinstance(r, ResolvedTerm)
    assert r.metric_id == "total_sales"


def test_resolve_channel_scoped_sales(catalogue):
    cases = {
        "shopify total sales": "total_sales",
        "shopify only total sales": "total_sales",
        "amazon total sales": "amazon_total_sales",
        "amazon only total sales": "amazon_total_sales",
        "total sales all channels": "total_sales_all_channels",
        "shopify only orders": "orders",
        "amazon only orders": "amazon_orders",
        "amazon net sales": "amazon_net_sales",
        "amazon gross sales": "amazon_gross_sales",
    }
    for term, expected in cases.items():
        r = catalogue.resolve_term(term)
        assert isinstance(r, ResolvedTerm), term
        assert r.metric_id == expected, f"{term} -> {r.metric_id}"


def test_resolve_ad_platform_scope(catalogue):
    cases = {
        "ad spend": "total_ad_spend",
        "total ad spend": "total_ad_spend",
        "total ads": "total_ad_spend",
        "all platforms ad spend": "total_ad_spend",
        "performance marketing": "total_ad_spend",
        "meta only": "meta_spend",
        "meta only spend": "meta_spend",
        "meta only ads": "meta_spend",
        "google only": "google_spend",
        "google only ads": "google_spend",
        "amazon only ads": "amazon_ads_spend",
        "amazon ads only": "amazon_ads_spend",
        "amazon only spend": "amazon_ads_spend",
        "shopify only ad spend": "shopify_ad_spend",
        "shopify only ads": "shopify_ad_spend",
        "meta only impressions": "meta_impressions",
        "google only clicks": "google_clicks",
        "amazon only CTR": "amazon_ads_ctr",
    }
    for term, expected in cases.items():
        r = catalogue.resolve_term(term)
        assert isinstance(r, ResolvedTerm), term
        assert r.metric_id == expected, f"{term} -> {getattr(r, 'metric_id', r)}"


def test_resolve_attribution_scope(catalogue):
    cases = {
        "attributed revenue": "attributed_net_revenue",
        "attributed sales": "attributed_net_revenue",
        "attr sales": "attributed_net_revenue",
        "attr revenue": "attributed_net_revenue",
        "last-touch revenue": "attributed_net_revenue",
        "attributed orders": "attributed_orders",
        "attr orders": "attributed_orders",
        "attributed gross sales": "attributed_gross_revenue",
        "attr aov": "attributed_aov",
        "meta attributed sales": "meta_attr_net_revenue",
        "meta attr sales": "meta_attr_net_revenue",
        "meta attributed orders": "meta_attr_orders",
        "meta attribution net sales": "meta_attribution_net_sales",
        "meta attribution sales": "meta_attribution_net_sales",
        "meta attribution orders": "meta_attribution_orders",
        "google attribution net sales": "google_attribution_net_sales",
        "google attribution orders": "google_attribution_orders",
        "channel attribution daily sales": "channel_net_revenue",
        "channel orders": "channel_orders",
        "channel sales": "channel_net_revenue",
        "sales by channel": "channel_net_revenue",
        "channel gross revenue": "channel_gross_revenue",
        "shopify only net profit": "net_profit",
        "historical all channels net profit": "net_profit_incl_amazon",
    }
    for term, expected in cases.items():
        r = catalogue.resolve_term(term)
        assert isinstance(r, ResolvedTerm), term
        assert r.metric_id == expected, f"{term} -> {getattr(r, 'metric_id', r)}"


def test_resolve_typo_auto_resolves_with_confidence(catalogue):
    r = catalogue.resolve_term("ordr volume")
    assert isinstance(r, ResolvedTerm)
    assert r.metric_id == "total_orders"
    assert r.auto_resolved is True
    assert r.confidence >= 0.85


def test_resolve_middle_band_is_ambiguous_not_guessed(catalogue):
    r = catalogue.resolve_term("margin")
    assert isinstance(r, AmbiguousTerm)
    assert r.candidates  # ranked candidates for the host to choose from
    assert all(c.confidence < 0.85 or len(r.candidates) > 1 for c in r.candidates)


def test_resolution_thresholds_are_configurable():
    # Same catalogue, stricter thresholds -> the typo no longer auto-resolves.
    from seleric_mcp.catalogue_service.loader import load_catalogue
    from seleric_mcp.catalogue_service.service import CatalogueService
    from seleric_mcp.config import PROJECT_ROOT

    strict = CatalogueService(
        load_catalogue(PROJECT_ROOT / "catalogue"),
        auto_threshold=0.99,
        ambiguous_threshold=0.60,
        runner_up_margin=0.05,
    )
    r = strict.resolve_term("total salez")
    assert isinstance(r, AmbiguousTerm)  # fuzzy score < 0.99 -> candidates, not a guess


def test_settings_tunables_read_from_env(monkeypatch, tmp_path):
    from seleric_mcp.config import load_settings

    monkeypatch.setenv("SELERIC_RESOLVE_AUTO_THRESHOLD", "0.9")
    monkeypatch.setenv("SELERIC_TOP_MOVERS_LIMIT", "25")
    monkeypatch.setenv("SELERIC_ANOMALY_SIGMA", "2.5")
    s = load_settings()
    assert s.resolve_auto_threshold == 0.9
    assert s.top_movers_limit == 25
    assert s.anomaly_sigma == 2.5
    # unset vars keep config.yaml / dataclass defaults
    assert s.resolve_ambiguous_threshold == 0.60
    assert s.idempotency_window_hours == 24


def test_settings_load_from_config_yaml(tmp_path, monkeypatch):
    from seleric_mcp.config import load_settings

    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        """
cube:
  api_url: http://config.test:4001
gateway:
  write_enabled: true
  scopes: [metrics:read]
storage:
  db_path: var/from_config.db
defaults:
  brand_id: "99"
tunables:
  top_movers_limit: 7
  freshness_enforcement: false
""",
        encoding="utf-8",
    )
    for key in (
        "CUBE_API_URL",
        "WRITE_ENABLED",
        "SELERIC_MCP_SCOPES",
        "SELERIC_MCP_DB",
        "SELERIC_DEFAULT_BRAND_ID",
        "SELERIC_TOP_MOVERS_LIMIT",
        "SELERIC_FRESHNESS_ENFORCEMENT",
    ):
        monkeypatch.delenv(key, raising=False)

    s = load_settings(config_path=cfg)
    assert s.cube_api_url == "http://config.test:4001"
    assert s.write_enabled is True
    assert s.caller_scopes == frozenset({"metrics:read"})
    assert s.db_path.name == "from_config.db"
    assert s.default_brand_id == "99"
    assert s.top_movers_limit == 7
    assert s.freshness_enforcement is False


def test_list_dimensions_scoped_by_view(catalogue):
    product = {d.id for d in catalogue.list_dimensions("product_performance")}
    assert "sku" in product
    assert "payment_method" in product
    assert "payment_bucket" in product
    commerce = {d.id for d in catalogue.list_dimensions("commerce_orders")}
    assert "payment_method" in commerce


def test_resolve_payment_mix_dimensions(catalogue):
    for phrase in ("online", "cod", "prepaid", "payment mix", "payment method"):
        dim = catalogue.resolve_dimension(phrase)
        assert dim is not None, phrase
    assert catalogue.resolve_dimension("online").id == "payment_bucket"
    assert catalogue.resolve_dimension("cod").id == "payment_bucket"
    assert catalogue.resolve_dimension("payment method").id == "payment_method"


def test_freshness(catalogue):
    f = catalogue.freshness("product_performance")
    assert "serve.product_performance" in f["source"]


def test_ratio_metrics_have_flag(catalogue):
    for mid in ("aov", "units_per_order", "product_gross_margin_pct", "average_selling_price"):
        assert catalogue.get_metric(mid).aggregation == "ratio"
