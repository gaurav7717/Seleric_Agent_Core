from seleric_mcp.catalogue_service.service import (
    AmbiguousTerm,
    DefinitionOnlyTerm,
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
    assert len(catalogue.cat.openmetadata.data_products) == 9
    assert len(catalogue.cat.openmetadata.metrics) == len(catalogue.cat.metrics)
    assert catalogue.cat.openmetadata.contracts
    assert catalogue.cat.openmetadata.ontology is not None


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


def test_resolve_definition_only_term(catalogue):
    r = catalogue.resolve_term("RTO")
    assert isinstance(r, DefinitionOnlyTerm)
    assert "Return to Origin" in r.definition


def test_resolve_unknown(catalogue):
    r = catalogue.resolve_term("quantum flux")
    assert isinstance(r, UnknownTerm)


def test_resolve_normalized_exact_match(catalogue):
    # "total sales" (space) must resolve to total_sales (underscore) — same
    # failure class as the chat-transcript miss that motivated
    # confidence-banded resolution.
    for variant in ("total sales", "Total Sales", "TOTAL-SALES"):
        r = catalogue.resolve_term(variant)
        assert isinstance(r, ResolvedTerm), variant
        assert r.metric_id == "total_sales"
        assert r.confidence == 1.0
        assert r.auto_resolved is False


def test_resolve_typo_auto_resolves_with_confidence(catalogue):
    r = catalogue.resolve_term("total salez")
    assert isinstance(r, ResolvedTerm)
    assert r.metric_id == "total_sales"
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
    assert "payment_method" not in product  # commerce-only dimension
    commerce = {d.id for d in catalogue.list_dimensions("commerce_orders")}
    assert "payment_method" in commerce


def test_freshness(catalogue):
    f = catalogue.freshness("product_performance")
    assert "serve.product_performance" in f["source"]


def test_ratio_metrics_have_flag(catalogue):
    for mid in ("aov", "units_per_order", "product_gross_margin_pct", "average_selling_price"):
        assert catalogue.get_metric(mid).aggregation == "ratio"
