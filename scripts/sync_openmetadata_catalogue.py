#!/usr/bin/env python3
"""Generate catalogue/openmetadata/metrics.yaml from catalogue/metrics/*.yaml.

Crosswalks every agent catalogue metric to OpenMetadata entity names and
glossary FQNs. Run after adding metrics or when mage-ai governance changes:

  py scripts/sync_openmetadata_catalogue.py
  py -m pytest tests/test_catalogue.py -q
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
METRICS_DIR = ROOT / "catalogue" / "metrics"
OUT = ROOT / "catalogue" / "openmetadata" / "metrics.yaml"

# catalogue metric id -> (om_name, [glossary FQNs])
# OM names from mage-ai/infra/openmetadata/apply_governance.py + metric_authority.yml
HAND_MAP: dict[str, tuple[str | None, list[str]]] = {
    # Commerce
    "commerce_net_revenue": ("commerceNetRevenue", ["Commerce.NetSales"]),
    "total_sales": ("totalSales", ["Commerce.TotalSales"]),
    "gross_sales": ("grossSales", ["Commerce.GrossSales"]),
    "discounts": ("discounts", ["Commerce.Discounts"]),
    "orders": ("orders", ["Commerce.TotalOrders"]),
    "aov": ("aov", ["Commerce.AverageOrderValue"]),
    "cancelled_orders": ("cancelledOrders", ["Commerce.CancelledOrder"]),
    "refunded_orders": ("returnedOrders", ["Commerce.ReturnedOrder"]),
    "returns_cancels": ("returnsCancels", ["Commerce.returnsCancels"]),
    "return_cancel_revenue": ("returnCancelRevenue", ["Commerce.ReturnCancelRevenue"]),
    "cod_orders": ("codOrders", ["Commerce.CashonDelivery"]),
    "prepaid_orders": ("prepaidOrders", ["Commerce.PrepaidOrder"]),
    "active_orders": (None, ["Commerce.ActiveOrder"]),
    "new_customer_orders": (None, ["Commerce.CommerceOrder"]),
    # Product
    "units_sold": ("unitsSold", ["Product.UnitsSold"]),
    "gross_units_ordered": ("grossUnitsOrdered", ["Product.GrossUnitsOrdered"]),
    "product_orders": ("productOrders", ["Product.ProductOrder"]),
    "product_net_revenue": ("productNetRevenue", ["Product.ProductNetRevenue"]),
    "product_cogs": ("productCogs", ["Product.ProductCOGS"]),
    "product_gross_profit": ("productGrossProfit", ["Product.ProductGrossProfit"]),
    "product_gross_margin_pct": ("productGrossMarginPct", ["Product.ProductGrossMargin"]),
    "average_selling_price": ("averageSellingPrice", ["Product.AverageSellingPrice"]),
    "units_per_order": ("unitsPerOrder", ["Product.AverageUnitsperOrder"]),
    # Paid Media — Meta
    "meta_spend": ("metaSpend", ["Paid Media.Spend"]),
    "meta_impressions": ("metaImpressions", ["Paid Media.Spend"]),
    "meta_clicks": ("metaClicks", ["Paid Media.CTR"]),
    "meta_link_clicks": ("metaLinkClicks", ["Paid Media.CTR"]),
    "meta_landing_page_views": ("metaLandingPageViews", ["Paid Media.CTR"]),
    "meta_ctr": ("metaCtr", ["Paid Media.CTR"]),
    "meta_cpc": ("metaCpc", ["Paid Media.CPC"]),
    "meta_cpm": ("metaCpm", ["Paid Media.CPM"]),
    "meta_thruplays": ("metaThruplays", ["Paid Media.ThruPlay"]),
    "meta_hook_rate": ("metaHookRate", ["Paid Media.HookRate(Meta)"]),
    "meta_video_completion_rate": ("metaVideoCompletionRate", ["Paid Media.HoldRate(Meta)"]),
    "meta_hold_rate_15s": (None, ["Paid Media.HoldRate(Meta)"]),
    "meta_video_3s_views": (None, ["Paid Media.HookRate(Meta)"]),
    "meta_video_100_pct_views": (None, ["Paid Media.HoldRate(Meta)"]),
    # Google
    "google_spend": ("googleSpend", ["Paid Media.Spend"]),
    "google_impressions": ("googleImpressions", ["Paid Media.Spend"]),
    "google_clicks": ("googleClicks", ["Paid Media.CTR"]),
    "google_interactions": ("googleInteractions", ["Paid Media.CTR"]),
    "google_ctr": ("googleCtr", ["Paid Media.CTR"]),
    "google_cpc": ("googleCpc", ["Paid Media.CPC"]),
    "google_cpm": ("googleCpm", ["Paid Media.CPM"]),
    "google_interaction_rate": ("googleInteractionRate", ["Paid Media.CTR"]),
    # Amazon
    "amazon_ads_spend": ("amazonAdsSpend", ["Paid Media.Spend", "Paid Media.SponsoredProducts(SP)"]),
    "amazon_ads_impressions": ("amazonAdsImpressions", ["Paid Media.SponsoredProducts(SP)"]),
    "amazon_ads_clicks": ("amazonAdsClicks", ["Paid Media.SponsoredProducts(SP)"]),
    "amazon_ads_ctr": ("amazonAdsCtr", ["Paid Media.CTR"]),
    "amazon_ads_cpc": ("amazonAdsCpc", ["Paid Media.CPC"]),
    "amazon_ads_cpm": ("amazonAdsCpm", ["Paid Media.CPM"]),
}

CONTRACT_BY_VIEW = {
    "commerce_orders": "commerce_performance_contract_v1",
    "commerce_performance": "commerce_performance_contract_v1",
    "product_performance": "product_performance_contract_v1",
    "meta_ad_performance": "paid_media_meta_contract_v1",
    "meta_ad_breakdown_performance": "paid_media_meta_breakdown_contract_v1",
    "google_ad_performance": "paid_media_google_contract_v1",
    "amazon_ad_performance": "paid_media_amazon_contract_v1",
}


def snake_to_camel(name: str) -> str:
    parts = name.split("_")
    return parts[0] + "".join(p.title() for p in parts[1:])


def infer_glossary(metric_id: str, category: str) -> list[str]:
    if category == "commerce":
        return ["Commerce.CommerceOrder"]
    if category == "product":
        return ["Product.Product"]
    if category.startswith("paid_media"):
        return ["Paid Media.Spend"]
    return []


def main() -> None:
    entries: dict[str, dict] = {}
    for path in sorted(METRICS_DIR.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        mid = raw["id"]
        category = raw.get("category", "")
        view = raw["cube_mapping"]["view"]
        om_name, gloss = HAND_MAP.get(mid, (None, []))
        if om_name is None and mid not in HAND_MAP:
            om_name = snake_to_camel(mid)
        if not gloss:
            gloss = infer_glossary(mid, category)
        entry: dict = {
            "category": category,
            "cube_view": view,
            "contract": CONTRACT_BY_VIEW.get(view),
            "glossary": gloss,
        }
        if om_name:
            entry["om_name"] = om_name
        entries[mid] = entry

    doc = {
        "generated_by": "scripts/sync_openmetadata_catalogue.py",
        "count": len(entries),
        "metrics": entries,
    }
    header = (
        "# Auto-generated metric crosswalk (catalogue id -> OM entity + glossary).\n"
        "# Regenerate: py scripts/sync_openmetadata_catalogue.py\n\n"
    )
    OUT.write_text(header + yaml.dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
    print(f"wrote {OUT} ({len(entries)} metrics)")


if __name__ == "__main__":
    main()
