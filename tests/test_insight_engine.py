from seleric_mcp.app import insight_engine as ie


def _metric(catalogue, mid):
    return catalogue.get_metric(mid)


def test_additive_totals_and_delta(catalogue):
    m = _metric(catalogue, "net_revenue")
    cur = [{"canonical_pnl.net_revenue_excl_tax": "100"},
           {"canonical_pnl.net_revenue_excl_tax": "150"}]
    prev = [{"canonical_pnl.net_revenue_excl_tax": "200"}]
    totals = ie.compute_totals(cur, prev, [m])
    t = totals[0]
    assert t["current"]["value"] == 250
    assert t["compare"]["value"] == 200
    assert t["delta"] == 50
    assert t["pct_change"] == 25.0
    assert t["current"]["method"] == "sum"


def test_ratio_recomputed_from_components(catalogue):
    m = _metric(catalogue, "mer")
    rows = [
        {"canonical_pnl.mer": "10", "canonical_pnl.net_revenue_excl_tax": "100",
         "canonical_pnl.total_ad_spend": "20"},
        {"canonical_pnl.mer": "2", "canonical_pnl.net_revenue_excl_tax": "100",
         "canonical_pnl.total_ad_spend": "80"},
    ]
    total = ie.metric_total(rows, m)
    # 200/100 = 2.0, NOT sum(10+2)=12 nor mean=6
    assert total["value"] == 2.0
    assert total["recomputed"] is True


def test_ratio_without_components_flagged_approximation(catalogue):
    m = _metric(catalogue, "blended_roas")  # no ratio_components catalogued
    rows = [{"canonical_pnl.blended_roas": "3"}, {"canonical_pnl.blended_roas": "5"}]
    total = ie.metric_total(rows, m)
    assert total["value"] == 4.0
    assert total["recomputed"] is False
    assert total["method"] == "mean_of_rows_approximation"


def test_top_movers_with_new_and_disappeared(catalogue):
    m = _metric(catalogue, "meta_spend")
    cube_query = {"dimensions": ["meta_ad_performance.campaign_name"]}
    cur = [
        {"meta_ad_performance.campaign_name": "A", "meta_ad_performance.spend": "300"},
        {"meta_ad_performance.campaign_name": "B", "meta_ad_performance.spend": "100"},
    ]
    prev = [
        {"meta_ad_performance.campaign_name": "A", "meta_ad_performance.spend": "100"},
        {"meta_ad_performance.campaign_name": "C", "meta_ad_performance.spend": "50"},
    ]
    movers = ie.compute_top_movers(cur, prev, [m], cube_query)
    by_key = {mv["key"]["meta_ad_performance.campaign_name"]: mv for mv in movers}
    assert by_key["A"]["delta"] == 200 and by_key["A"]["status"] == "existing"
    assert by_key["B"]["status"] == "new"
    assert by_key["C"]["status"] == "disappeared" and by_key["C"]["delta"] == -50
    # delta_total = 400-150 = 250; A contributes 200/250 = 80%
    assert by_key["A"]["contribution_pct"] == 80.0
    # ranked by |delta|
    assert movers[0]["key"]["meta_ad_performance.campaign_name"] == "A"


def test_anomaly_sigma_outlier(catalogue):
    m = _metric(catalogue, "net_revenue")
    cube_query = {
        "timeDimensions": [{"dimension": "canonical_pnl.report_date", "granularity": "day"}]
    }
    rows = [
        {"canonical_pnl.report_date": f"2026-06-{d:02d}", "canonical_pnl.net_revenue_excl_tax": "100"}
        for d in range(1, 21)
    ]
    rows[10]["canonical_pnl.net_revenue_excl_tax"] = "1000"  # spike
    anomalies = ie.compute_anomalies(rows, [m], cube_query)
    assert any(a["type"] == "sigma_outlier" and a["date"] == "2026-06-11" for a in anomalies)


def test_anomaly_flat_zero_run(catalogue):
    m = _metric(catalogue, "net_revenue")
    cube_query = {
        "timeDimensions": [{"dimension": "canonical_pnl.report_date", "granularity": "day"}]
    }
    rows = [
        {"canonical_pnl.report_date": f"2026-06-{d:02d}",
         "canonical_pnl.net_revenue_excl_tax": "0" if 5 <= d <= 8 else "100"}
        for d in range(1, 21)
    ]
    anomalies = ie.compute_anomalies(rows, [m], cube_query)
    assert any(a["type"] == "flat_zero_run" and a["days"] == 4 for a in anomalies)


def test_no_compare_note(catalogue):
    m = _metric(catalogue, "net_revenue")
    report = ie.explain([{"canonical_pnl.net_revenue_excl_tax": "5"}], None, [m], {})
    assert report["top_movers"] == []
    assert "note" in report
