#!/usr/bin/env python3
"""Generate machine-readable gold semantic catalog from Cube YAML + sync registry."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import yaml

ROOT = Path(__file__).resolve().parents[1]
CUBES_DIR = ROOT / "model" / "cubes"
VIEWS_FILES = [
    ROOT / "model" / "views" / "serve_views.yml",
    ROOT / "model" / "views" / "chart_views.yml",
    ROOT / "model" / "views" / "gold_full_views.yml",
]
CATALOG_DIR = ROOT / "catalog"
MAGE_AI = ROOT.parent.parent / "mage-ai"
SYNC_FILE = MAGE_AI / "utils" / "trino_to_clickhouse.py"
GLOSSARY = MAGE_AI / "docs" / "FINANCE_DEFINITIONS.md"

# Grain keys from ICEBERG_GOLD_TO_CLICKHOUSE (keep in sync with mage-ai)
GOLD_GRAINS: Dict[str, List[str]] = {
    "dim_campaign": ["brand_id", "campaign_key"],
    "dim_adset": ["brand_id", "adset_key"],
    "dim_ad": ["brand_id", "ad_key"],
    "dim_customers": ["brand_id", "customer_id"],
    "fct_orders": ["brand_id", "order_id"],
    "fct_order_items": ["brand_id", "order_id", "line_item_id"],
    "fct_payments": ["brand_id", "transaction_id"],
    "fct_product_variant_cost": ["brand_id", "variant_id"],
    "fct_product_variant_cost_history": ["brand_id", "variant_id", "effective_from"],
    "fct_meta_ads_daily": ["brand_id", "report_date", "account_id", "campaign_id", "adset_id", "ad_id"],
    "fct_meta_ads_breakdown_daily": [
        "brand_id", "report_date", "breakdown_type", "breakdown_dimension_1",
        "breakdown_dimension_2", "ad_id",
    ],
    "fct_google_ads_daily": [
        "brand_id", "report_date", "campaign_id", "adset_id", "ad_id",
        "segment_device", "segment_ad_network_type",
    ],
    "fct_google_campaigns_hourly": [
        "brand_id", "report_date", "hour_of_day", "campaign_id",
        "segment_device", "segment_ad_network_type",
    ],
    "fct_meta_ads_hourly": [
        "brand_id", "report_date", "hour_of_day", "account_id",
        "campaign_id", "adset_id", "ad_id",
    ],
    "fct_meta_ads_status_history": ["brand_id", "entity_type", "entity_id", "changed_at"],
    "fct_google_ads_status_history": ["brand_id", "entity_type", "entity_id", "changed_at"],
    "fct_daily_pnl": ["brand_id", "report_date"],
    "fct_order_attribution": ["brand_id", "order_id"],
    "fct_session_funnel": ["brand_id", "session_id"],
    "dim_neurohack": ["tag_code"],
    "dim_ad_neurohack_map": ["brand_id", "ad_key", "tag_code", "tag_position"],
    "mart_meta_ad_daily_performance": [
        "brand_id", "report_date", "account_id", "campaign_id", "adset_id", "ad_id",
    ],
    "mart_meta_ad_daily_attribution": [
        "brand_id", "report_date", "campaign_id", "adset_id", "ad_id",
    ],
    "mart_meta_ad_neurotag_daily": ["brand_id", "report_date", "ad_id", "tag_code"],
}

DOMAIN_MAP = {
    "fct_orders": "shopify",
    "fct_order_items": "shopify",
    "fct_payments": "shopify",
    "dim_customers": "shopify",
    "fct_product_variant_cost": "shopify",
    "fct_product_variant_cost_history": "shopify",
    "fct_meta_ads_daily": "meta",
    "fct_meta_ads_hourly": "meta",
    "fct_meta_ads_breakdown_daily": "meta",
    "fct_meta_ads_status_history": "meta",
    "fct_google_ads_daily": "google",
    "fct_google_campaigns_hourly": "google",
    "fct_google_ads_status_history": "google",
    "fct_order_attribution": "attribution",
    "fct_session_funnel": "attribution",
    "fct_daily_pnl": "cross_platform",
    "dim_campaign": "cross_platform",
    "dim_adset": "cross_platform",
    "dim_ad": "cross_platform",
    "dim_neurohack": "creative_taxonomy",
    "dim_ad_neurohack_map": "creative_taxonomy",
    "mart_meta_ad_daily_performance": "meta",
    "mart_meta_ad_daily_attribution": "attribution",
    "mart_meta_ad_neurotag_daily": "creative_taxonomy",
}

VIEW_TOOLS = {
    "daily_pnl": ["cube_daily_pnl", "cube_pnl_waterfall", "cube_pnl_today_yesterday"],
    "channel_pnl": ["cube_channel_pnl"],
    "marketing_performance": ["cube_meta_ads"],
    "ad_performance": ["cube_query"],
    "dw_meta_ads_attribution": ["cube_query"],
    "shopify_orders": ["cube_commerce_orders"],
    "shopify_order_line_items": ["cube_line_economics"],
    "canonical_pnl": ["cube_canonical_pnl", "cube_pnl_today_yesterday"],
    "commerce_orders": ["cube_commerce_orders"],
    "product_performance": ["cube_product_performance"],
    "customer_ltv": ["cube_customer_ltv"],
    "payment_cashflow": ["cube_payment_cashflow"],
    "meta_ad_performance": ["cube_meta_ads"],
    "google_ad_performance": ["cube_google_ads"],
    "google_ad_hourly": ["cube_google_ads_hourly"],
    "meta_ad_hourly": ["cube_meta_ads_hourly"],
    "meta_ad_breakdown": ["cube_meta_ads_breakdown"],
    "order_attribution": ["cube_order_attribution"],
    "session_funnel": ["cube_session_funnel"],
    "variant_economics": ["cube_variant_economics"],
    "meta_ad_status_changes": ["cube_query"],
    "google_ad_status_changes": ["cube_query"],
    "neurohack_catalog": ["cube_neurohack_catalog"],
    "ad_neurohack_map": ["cube_ad_neurohack"],
    "meta_neurohack_performance": ["cube_meta_neurohack"],
    "meta_neurotag_analysis": ["cube_meta_neurotag"],
    "campaign_product_performance": ["cube_campaign_product"],
    "customer_acquisition_ltv": ["cube_customer_acquisition_ltv"],
    "neurohack_attribution": ["cube_neurohack_attribution"],
    "daily_performance": ["cube_daily_performance"],
    "refund_events": ["cube_refund_events"],
    "payment_method_pnl": ["cube_payment_method_pnl"],
    "hourly_commerce": ["cube_hourly_commerce"],
}

BRIDGE_VIEWS = [
    "campaign_product_performance",
    "customer_acquisition_ltv",
    "neurohack_attribution",
    "daily_performance",
    "refund_events",
    "payment_method_pnl",
    "hourly_commerce",
]
for _view in BRIDGE_VIEWS:
    VIEW_TOOLS[f"gold__{_view}"] = ["cube_query"]

# gold__{table} full-column views (auto-generated)
for _table in GOLD_GRAINS:
    VIEW_TOOLS[f"gold__{_table}"] = ["cube_query"]

ANTI_PATTERNS = {
    "fct_session_funnel": [
        "Do not sum purchase_revenue for P&L — use fct_order_attribution.",
        "Session grain may double-count orders reached by multiple sessions.",
    ],
    "fct_order_attribution": [
        "Not for company net profit totals — use fct_daily_pnl / canonical_pnl.",
    ],
    "fct_orders": [
        "Always filter is_test = false for published KPIs.",
        "order-level net_revenue differs from daily P&L net_revenue.",
    ],
    "fct_daily_pnl": [
        "Sum daily report_date rows for period rollups — do not re-aggregate from orders.",
        "Placement vs refund-event date axes differ by metric.",
    ],
    "fct_meta_ads_breakdown_daily": [
        "Always filter to exactly ONE breakdown_type before summing spend — mixing types multi-counts the same ad spend (~8×).",
        "For total Meta spend, impressions, or ROAS use fct_meta_ads_daily / meta_ad_performance — not this table.",
        "Typed columns (gender, publisher_platform, country, etc.) are sparse — only populated for their breakdown_type.",
    ],
    "dim_ad_neurohack_map": [
        "One ad may map to multiple tag_codes — spend fans out on join to meta ads.",
        "Do not sum spend by tag without understanding multi-tag ad duplication.",
    ],
    "mart_meta_ad_neurotag_daily": [
        "Use spend_sc / net_revenue_sc for tag-level rollups — spend_fc duplicates across tags on multi-tag ads.",
        "Use spend_fc only when filtering to a single tag_code per ad or grouping by ad_id.",
        "Untagged ads appear as tag_code = __untagged__.",
    ],
}


def _table_from_cube(cube: Dict[str, Any]) -> str | None:
    sql_table = cube.get("sql_table") or ""
    if sql_table.startswith("gold."):
        return sql_table.split(".", 1)[1]
    return None


def _load_gold_cubes() -> List[Dict[str, Any]]:
    cubes: List[Dict[str, Any]] = []
    for path in sorted(CUBES_DIR.glob("gold_*.yml")):
        doc = yaml.safe_load(path.read_text()) or {}
        for cube in doc.get("cubes") or []:
            table = _table_from_cube(cube)
            if table:
                cubes.append({"file": path.name, "table": table, **cube})
    return cubes


def _load_views() -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for views_file in VIEWS_FILES:
        if not views_file.exists():
            continue
        doc = yaml.safe_load(views_file.read_text()) or {}
        for view in doc.get("views") or []:
            name = view.get("name")
            if name:
                out[name] = view
    return out


def build_catalog() -> Dict[str, Any]:
    cubes = _load_gold_cubes()
    views = _load_views()
    entities: List[Dict[str, Any]] = []

    for cube in cubes:
        table = cube["table"]
        measures = [
            {
                "name": m.get("name"),
                "type": m.get("type"),
                "format": m.get("format"),
                "description": (m.get("description") or "").strip() or None,
                "sql": m.get("sql") if m.get("sql") != m.get("name") else None,
            }
            for m in (cube.get("measures") or [])
            if m.get("name")
        ]
        dimensions = [
            {
                "name": d.get("name"),
                "type": d.get("type"),
                "title": d.get("title"),
                "description": (d.get("description") or "").strip() or None,
            }
            for d in (cube.get("dimensions") or [])
            if d.get("name")
        ]
        view_names = [
            vname
            for vname, vdef in views.items()
            if any(
                (inc.get("join_path") or "").startswith(cube.get("name", ""))
                for inc in (vdef.get("cubes") or [])
            )
        ]
        entities.append({
            "id": f"gold.{table}",
            "cube": cube.get("name"),
            "domain": DOMAIN_MAP.get(table, "general"),
            "grain": GOLD_GRAINS.get(table, ["brand_id"]),
            "timezone": "Asia/Kolkata",
            "description": (cube.get("description") or "").strip() or None,
            "measures": measures,
            "dimensions": dimensions,
            "views": view_names,
            "mcp_tools": sorted({t for v in view_names for t in VIEW_TOOLS.get(v, ["cube_query"])}),
            "anti_patterns": ANTI_PATTERNS.get(table, []),
        })

    return {
        "catalog_name": "seleric_gold_semantic_catalog",
        "version": "2.0.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "clickhouse_gold_only",
        "timezone": "Asia/Kolkata",
        "entity_count": len(entities),
        "views": [
            {
                "name": name,
                "title": v.get("title"),
                "description": (v.get("description") or "").strip() or None,
                "mcp_tools": VIEW_TOOLS.get(name, ["cube_query"]),
            }
            for name, v in views.items()
        ],
        "entities": entities,
        "glossary_ref": str(GLOSSARY.relative_to(MAGE_AI.parent)) if GLOSSARY.exists() else None,
    }


def main() -> None:
    catalog = build_catalog()
    CATALOG_DIR.mkdir(parents=True, exist_ok=True)
    json_path = CATALOG_DIR / "gold_semantic_catalog.json"
    yaml_path = CATALOG_DIR / "gold_semantic_catalog.yaml"
    json_path.write_text(json.dumps(catalog, indent=2, default=str) + "\n")
    yaml_path.write_text(yaml.dump(catalog, sort_keys=False, allow_unicode=True, default_flow_style=False))
    print(f"Wrote {json_path} ({catalog['entity_count']} entities)")
    print(f"Wrote {yaml_path}")


if __name__ == "__main__":
    main()
