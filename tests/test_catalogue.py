from seleric_mcp.catalogue_service.service import (
    AmbiguousTerm,
    DefinitionOnlyTerm,
    ResolvedTerm,
    UnknownTerm,
)


def test_loads_seed(catalogue):
    assert len(catalogue.cat.metrics) == 16
    assert "net_revenue" in catalogue.cat.metrics
    assert "attributed_revenue" in catalogue.cat.metrics
    assert catalogue.version


def test_search_glossary_term(catalogue):
    result = catalogue.search("topline")
    assert result.matches
    assert result.matches[0].id == "net_revenue"
    assert result.matches[0].matched_on.startswith("glossary")


def test_search_unknown_returns_suggestions_not_guesses(catalogue):
    result = catalogue.search("zzzz frobnicator")
    assert result.matches == []
    assert isinstance(result.suggestions, list)


def test_resolve_term_mer(catalogue):
    r = catalogue.resolve_term("MER")
    assert isinstance(r, ResolvedTerm)
    assert r.metric_id == "mer"


def test_resolve_deprecated_alias(catalogue):
    r = catalogue.resolve_term("daily_pnl.net_profit")
    assert isinstance(r, ResolvedTerm)
    assert r.metric_id == "net_profit"
    assert r.deprecation_notice


def test_resolve_definition_only_term(catalogue):
    r = catalogue.resolve_term("RTO")
    assert isinstance(r, DefinitionOnlyTerm)
    assert "Return to Origin" in r.definition


def test_resolve_unknown(catalogue):
    r = catalogue.resolve_term("quantum flux")
    assert isinstance(r, UnknownTerm)


def test_resolve_normalized_exact_match(catalogue):
    # "net profit" (space) must resolve to net_profit (underscore) — this was
    # the chat-transcript failure that motivated confidence-banded resolution.
    for variant in ("net profit", "Net Profit", "NET-PROFIT"):
        r = catalogue.resolve_term(variant)
        assert isinstance(r, ResolvedTerm), variant
        assert r.metric_id == "net_profit"
        assert r.confidence == 1.0
        assert r.auto_resolved is False


def test_resolve_typo_auto_resolves_with_confidence(catalogue):
    r = catalogue.resolve_term("net profitt")
    assert isinstance(r, ResolvedTerm)
    assert r.metric_id == "net_profit"
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
    r = strict.resolve_term("net profitt")
    assert isinstance(r, AmbiguousTerm)  # 0.95 < 0.99 -> candidates, not a guess


def test_settings_tunables_read_from_env(monkeypatch, tmp_path):
    from seleric_mcp.config import load_settings

    monkeypatch.setenv("SELERIC_RESOLVE_AUTO_THRESHOLD", "0.9")
    monkeypatch.setenv("SELERIC_TOP_MOVERS_LIMIT", "25")
    monkeypatch.setenv("SELERIC_ANOMALY_SIGMA", "2.5")
    s = load_settings()
    assert s.resolve_auto_threshold == 0.9
    assert s.top_movers_limit == 25
    assert s.anomaly_sigma == 2.5
    # unset vars keep dataclass defaults
    assert s.resolve_ambiguous_threshold == 0.60
    assert s.idempotency_window_hours == 24


def test_list_dimensions_scoped_by_view(catalogue):
    dims = {d.id for d in catalogue.list_dimensions("canonical_pnl")}
    assert dims == {"brand_id", "report_date"}
    commerce = {d.id for d in catalogue.list_dimensions("commerce_orders")}
    assert "payment_method" in commerce


def test_freshness(catalogue):
    f = catalogue.freshness("canonical_pnl")
    assert "int_finance_daily_rollups" in f["source"]


def test_ratio_metrics_have_flag(catalogue):
    for mid in ("mer", "blended_roas", "aov", "meta_roas", "avg_ltv"):
        assert catalogue.get_metric(mid).aggregation == "ratio"
