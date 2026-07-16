# OpenMetadata MCP — metadata context for Seleric agents

Seleric MCP (`seleric-mcp`) executes **numbers via Cube**. OpenMetadata MCP is a
separate metadata sidecar for discovery, trust signals, lineage, and contracts.

Local OM: **http://127.0.0.1:8585** (OpenMetadata 1.13.1). Governance specs live in
`mage-ai/openmetadata/`; applier `mage-ai/infra/openmetadata/apply_governance.py`.

## Boundary

| Concern | System |
|---------|--------|
| Metric values, filters, time series | Cube → Seleric MCP |
| Owners, tier, release status, glossary | OpenMetadata MCP |
| Lineage, contracts, DQ health | OpenMetadata MCP |
| Write actions (ads, etc.) | Seleric MCP / Pipeboard |

Never compute business metrics from OpenMetadata. OM metric descriptions are
formulas for governance only — Cube executes.

## Certified data products (9)

| OM data product | Domain | Primary serve table | Cube view(s) |
|-----------------|--------|---------------------|--------------|
| `CommercePerformance` | Commerce | `clickhouse.default.serve.commerce_orders` | `commerce_orders`, `commerce_performance` |
| `ProductPerformance` | Product | `clickhouse.default.serve.product_performance` | `product_performance` |
| `MetaAdsPerformance` | PaidMedia | `clickhouse.default.serve.meta_ads_daily` | `meta_ad_performance`, `meta_ad_breakdown_performance` |
| `GoogleAdsPerformance` | PaidMedia | `clickhouse.default.serve.google_ads_daily` | `google_ad_performance` |
| `AmazonAdsPerformance` | PaidMedia | `clickhouse.default.serve.amazon_ads_daily` | `amazon_ad_performance` |
| `MarketingAttribution` | Attribution | `clickhouse.default.serve.order_attribution` | `order_attribution`, `meta_ad_attribution` |
| `CustomerIntelligence` | Customer | `clickhouse.default.serve.customer_ltv` | `customer_ltv`, `purchase_sequence` |
| `CanonicalPnl` | Finance | `clickhouse.default.serve.canonical_pnl` | `canonical_pnl` |
| `ReturnsRefunds` | Operations | `clickhouse.default.serve.refund_events` | `refund_events`, `return_lifecycle` |

Agent catalogue crosswalk:

| File | Purpose |
|------|---------|
| `catalogue/openmetadata/registry.yaml` | Instance, data products, view→serve FQN |
| `catalogue/openmetadata/metrics.yaml` | All catalogue metrics → OM entity + glossary |
| `catalogue/openmetadata/contracts.yaml` | Grain, required columns, DQ tests |
| `catalogue/openmetadata/ontology.yaml` | Domains, entity clusters, attribution boundary |

Loaded at startup; MCP resources: `catalogue://openmetadata`, `catalogue://contracts`,
`catalogue://ontology`. Regenerate metrics: `py scripts/sync_openmetadata_catalogue.py`.

## Enable (Cursor / MCP client)

1. Generate a JWT (from `mage-ai` repo root):

```powershell
py infra/openmetadata/get_ingestion_jwt.py
# writes mage-ai/infra/openmetadata/.om_ingestion_jwt (do not commit)
```

2. Add to `.env.local`:

```env
OPENMETADATA_BASE_URL=http://127.0.0.1:8585
OM_JWT_OR_PAT=<paste token>
```

3. Wire MCP (when OM MCP is enabled on the server):

```json
{
  "mcpServers": {
    "openmetadata": {
      "url": "http://127.0.0.1:8585/mcp",
      "headers": {
        "Authorization": "Bearer ${OM_JWT_OR_PAT}"
      }
    }
  }
}
```

## Suggested agent prompts

**Commerce / Product**

- “Who owns `serve.commerce_orders` and is it AgentReady?”
- “What is the freshness SLA and latest DQ status for CommercePerformance?”
- “Show upstream lineage for `product_performance`.”

**Paid Media**

- “Is `serve.meta_ads_daily` certified and what contract applies?”
- “What glossary terms apply to `metaSpend` and `amazonAdsSpend`?”
- “Why is platform ROAS excluded from MetaAdsPerformance?” (attribution boundary)

**Customer**

- “Who owns CustomerIntelligence and is `serve.customer_ltv` AgentReady?”
- “What is the PII rule on `customer_ltv_contract_v1`?”
- “Which Cube views and contracts belong to CustomerIntelligence?”

## Attribution boundary (Paid Media)

Certified paid-media products expose **delivery + video engagement** only.
Platform-reported purchases, conversion value, ROAS, and ACOS remain in gold as
diagnostics — see `catalogue/deprecations.yaml` and OM glossary
`Paid Media.Platform-ReportedConversion`.

## Catalogue sync

- **Authoritative for queries:** `catalogue/metrics/*.yaml`, `catalogue/views.yaml`
- **OM crosswalk (read-only):** `catalogue/openmetadata/registry.yaml`
- **Do not** dual-write Cube measure formulas from OM into the agent catalogue.

Re-apply OM governance after schema changes:

```powershell
cd mage-ai
py infra/openmetadata/apply_governance.py --skip-ch
```
