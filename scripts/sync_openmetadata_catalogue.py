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
    "commerce_net_revenue_daily": ("commerceNetRevenueDaily", ["Commerce.NetSales"]),
    "total_sales": ("totalSales", ["Commerce.TotalSales"]),
    "gross_sales": ("grossSales", ["Commerce.GrossSales"]),
    "discounts": ("discounts", ["Commerce.Discounts"]),
    "orders": ("orders", ["Commerce.TotalOrders"]),
    "total_orders": ("totalOrders", ["Commerce.TotalOrders"]),
    "amazon_orders": ("amazonOrders", ["Commerce.TotalOrders"]),
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
    # Finance (canonical_pnl)
    "net_cogs": ("netCogs", ["Finance.NetCogs"]),
    "product_cost": ("productCost", ["Finance.NetCogs"]),
    "taxes_on_net_sales": ("taxesOnNetSales", ["Finance.NetCogs"]),
    "return_revenue": ("returnRevenue", ["Commerce.ReturnCancelRevenue"]),
    "cancel_revenue": ("cancelRevenue", ["Commerce.ReturnCancelRevenue"]),
    "amazon_platform_fees": ("amazonPlatformFees", ["Finance.NetCogs"]),
    "total_operating_cost": ("totalOperatingCost", ["Finance.NetCogs"]),
    "net_profit_blended": ("netProfitBlended", ["Finance.NetProfit"]),
    "shipping_cost": ("shippingCost", ["Finance.NetCogs"]),
    "packaging_cost": ("packagingCost", ["Finance.NetCogs"]),
    "payment_gateway_fees": ("paymentGatewayFees", ["Finance.NetCogs"]),
    "rto_cost": ("rtoCost", ["Finance.NetCogs"]),
    "operating_cost": ("operatingCost", ["Finance.NetCogs"]),
    "total_ad_spend": ("totalAdSpend", ["Finance.NetCogs"]),
    "shopify_ad_spend": ("shopifyAdSpend", ["Finance.NetCogs"]),
    "gross_profit": ("grossProfit", ["Finance.GrossProfit"]),
    "contribution_margin": ("contributionMargin", ["Finance.ContributionMargin"]),
    "net_profit": ("netProfit", ["Finance.NetProfit"]),
    "gross_margin_pct": ("grossMarginPct", ["Finance.GrossProfit"]),
    "contribution_margin_pct": ("contributionMarginPct", ["Finance.ContributionMargin"]),
    "net_margin_pct": ("netMarginPct", ["Finance.NetProfit"]),
    "mer": ("mer", ["Finance.MER"]),
    "net_roas": ("netRoas", ["Finance.NetProfit"]),
    "gross_roas": ("grossRoas", ["Finance.GrossProfit"]),
    "be_roas": ("beRoas", ["Finance.NetProfit"]),
    "cost_coverage_pct": ("costCoveragePct", ["Finance.CostCoverage"]),
    # Attribution (order_attribution)
    "attributed_orders": ("attributedOrders", ["Attribution.AttributedOrder"]),
    "attributed_net_revenue": ("attributedNetRevenue", ["Attribution.AttributedNetRevenue"]),
    "attributed_gross_revenue": ("attributedGrossRevenue", ["Attribution.AttributedNetRevenue"]),
    "attributed_refund_amount": ("attributedRefundAmount", ["Attribution.AttributedNetRevenue"]),
    "attributed_new_customer_orders": ("attributedNewCustomerOrders", ["Attribution.AttributedOrder"]),
    "touch_attributed_orders": ("touchAttributedOrders", ["Attribution.AttributionRate"]),
    "attribution_rate": ("attributionRate", ["Attribution.AttributionRate"]),
    "avg_attribution_confidence": ("avgAttributionConfidence", ["Attribution.LastTouch"]),
    "attributed_aov": ("attributedAov", ["Attribution.AttributedNetRevenue"]),
    "meta_attr_orders": ("metaAttrOrders", ["Attribution.AttributedOrder"]),
    "meta_attr_net_revenue": ("metaAttrNetRevenue", ["Attribution.AttributedNetRevenue"]),
    "meta_attr_gross_revenue": ("metaAttrGrossRevenue", ["Attribution.AttributedNetRevenue"]),
    "meta_attr_refund_amount": ("metaAttrRefundAmount", ["Attribution.AttributedNetRevenue"]),
    "meta_attr_new_customer_orders": ("metaAttrNewCustomerOrders", ["Attribution.AttributedOrder"]),
    "meta_attr_new_customer_revenue": ("metaAttrNewCustomerRevenue", ["Attribution.AttributedNetRevenue"]),
    "meta_attr_aov": ("metaAttrAov", ["Attribution.AttributedNetRevenue"]),
    # Attribution Analysis (platform commerce cohort — not ad-day meta_attr_*)
    "meta_attribution_net_sales": ("metaAttributionNetSales", ["Attribution.AttributedNetRevenue"]),
    "meta_attribution_gross_sales": ("metaAttributionGrossSales", ["Attribution.AttributedNetRevenue"]),
    "meta_attribution_total_sales": ("metaAttributionTotalSales", ["Attribution.AttributedNetRevenue"]),
    "meta_attribution_orders": ("metaAttributionOrders", ["Attribution.AttributedOrder"]),
    "google_attribution_net_sales": ("googleAttributionNetSales", ["Attribution.AttributedNetRevenue"]),
    "google_attribution_gross_sales": ("googleAttributionGrossSales", ["Attribution.AttributedNetRevenue"]),
    "google_attribution_total_sales": ("googleAttributionTotalSales", ["Attribution.AttributedNetRevenue"]),
    "google_attribution_orders": ("googleAttributionOrders", ["Attribution.AttributedOrder"]),
    "product_cost_all_channels": ("productCostAllChannels", ["Finance.NetCogs"]),
    "total_operating_cost_all_channels": ("totalOperatingCostAllChannels", ["Finance.NetCogs"]),
    "net_profit_all_channels": ("netProfitAllChannels", ["Finance.NetProfit"]),
    "net_profit_incl_amazon": ("netProfitInclAmazon", ["Finance.NetProfit"]),
    # Customer (customer_ltv)
    "customers": ("customers", ["Customer.LifetimeValue"]),
    "repeat_customers": ("repeatCustomers", ["Customer.RepeatCustomer"]),
    "lifetime_net_revenue": ("lifetimeNetRevenue", ["Customer.LifetimeValue"]),
    "lifetime_gross_revenue": ("lifetimeGrossRevenue", ["Customer.LifetimeValue"]),
    "lifetime_orders": ("lifetimeOrders", ["Customer.LifetimeValue"]),
    "avg_ltv": ("avgLtv", ["Customer.LifetimeValue"]),
    "repeat_rate": ("repeatRate", ["Customer.RepeatCustomer"]),
    "avg_orders_per_customer": ("avgOrdersPerCustomer", ["Customer.LifetimeValue"]),
    "avg_days_since_last_order": ("avgDaysSinceLastOrder", ["Customer.RepeatCustomer"]),
    # Customer (purchase_sequence)
    "repeat_purchase_orders": ("repeatPurchaseOrders", ["Customer.RepeatCustomer"]),
    "first_orders": ("firstOrders", ["Customer.RepeatCustomer"]),
    "repeat_orders": ("repeatOrders", ["Customer.RepeatCustomer"]),
    "repeat_purchase_net_revenue": ("repeatPurchaseNetRevenue", ["Customer.LifetimeValue"]),
    "repeat_order_share": ("repeatOrderShare", ["Customer.RepeatCustomer"]),
    "avg_days_between_orders": ("avgDaysBetweenOrders", ["Customer.RepeatCustomer"]),
    # Web Analytics (web_events / web_events_daily — EventStream)
    "web_events": ("webEvents", ["Web Analytics.WebEvent"]),
    "web_page_views": ("webPageViews", ["Web Analytics.PageView"]),
    "product_views": ("productViews", ["Web Analytics.ProductView"]),
    "collection_views": ("collectionViews", ["Web Analytics.WebEvent"]),
    "add_to_cart_events": ("addToCartEvents", ["Web Analytics.WebEvent"]),
    "site_search_events": ("siteSearchEvents", ["Web Analytics.SiteSearch"]),
    "events_per_session": ("eventsPerSession", ["Web Analytics.EventsPerSession"]),
}

CONTRACT_BY_VIEW = {
    "commerce_orders": "commerce_performance_contract_v1",
    "commerce_performance": "commerce_performance_contract_v1",
    "product_performance": "product_performance_contract_v1",
    "meta_ad_performance": "paid_media_meta_contract_v1",
    "meta_ad_breakdown_performance": "paid_media_meta_breakdown_contract_v1",
    "google_ad_performance": "paid_media_google_contract_v1",
    "amazon_ad_performance": "paid_media_amazon_contract_v1",
    "order_attribution": "attribution_order_contract_v1",
    "meta_ad_attribution": "attribution_meta_ad_contract_v1",
    "platform_attribution_commerce": "attribution_order_contract_v1",
    "customer_ltv": "customer_ltv_contract_v1",
    "purchase_sequence": "purchase_sequence_contract_v1",
    "canonical_pnl": "canonical_pnl_contract_v1",
    "refund_events": "refund_events_contract_v1",
    "return_lifecycle": "return_lifecycle_contract_v1",
    "session_funnel": "session_funnel_contract_v1",
    "funnel_daily": "funnel_daily_contract_v1",
    "web_events": "web_events_contract_v1",
    "web_events_daily": "web_events_daily_contract_v1",
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
