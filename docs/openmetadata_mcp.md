# OpenMetadata MCP — metadata context for Seleric agents

Seleric MCP (`seleric-mcp`) executes **numbers via Cube**. OpenMetadata MCP is a
separate metadata sidecar for discovery and trust signals.

## Boundary

| Concern | System |
|---------|--------|
| Metric values, filters, time series | Cube → Seleric MCP |
| Owners, tier, release status, glossary | OpenMetadata MCP |
| Lineage, contracts, DQ health | OpenMetadata MCP |
| Write actions (ads, etc.) | Seleric MCP / Pipeboard |

Never compute business metrics from OpenMetadata.

## Enable (Cursor / MCP client)

Add an MCP server entry pointing at your OpenMetadata instance (requires OM MCP
enabled on the server — see [OM MCP docs](https://docs.open-metadata.org/latest/how-to-guides/mcp)):

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

Replace auth with a personal access token or JWT from OM Settings → Bots / Users.

## Suggested agent prompts

- “Who owns `serve.commerce_orders` and is it AgentReady?”
- “What is the freshness SLA and latest DQ status for CommercePerformance?”
- “Show upstream lineage for `product_performance`.”

## Catalogue sync (later)

Optional: read-only sync of ownership/glossary labels from OM into
`Seleric_Agent_Core/catalogue/` YAML so local catalogue fields stay aligned.
Do **not** dual-write measure formulas from OM into Cube.
