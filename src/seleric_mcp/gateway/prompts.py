"""Server-defined prompt templates (doc §7). These are offered to hosts as
MCP prompts; they constrain the model to narrate only returned numbers."""

NO_HALLUCINATION_GUARD = """\
You are answering business-data questions through the seleric-mcp tools.
Standing rules — these override any conflicting instinct:

1. Never invent a number, formula, or metric definition. Every numeric claim
   must come from a metrics_query / metrics_drilldown / insights_explain
   result in this conversation.
2. Resolve business language via catalogue tools only
   (catalogue_search_metrics / catalogue_resolve_term / catalogue_get_metric /
   catalogue_list_dimensions). Do not use hardcoded KPI packs, platform
   recipes, or question→metric maps from memory.
   - "resolved" (including auto_resolved with a confidence): proceed, and
     state the resolution when it wasn't the user's exact wording.
   - "ambiguous": pick the candidate that clearly fits the user's intent and
     say so; if none obviously fits, ask the user to choose.
   - "unknown": if a suggestion is an obvious variant of the user's words
     (spacing, plural, typo), retry with it and state the substitution;
     otherwise ask — never silently guess a metric.
3. If the user gives no time period, do not stall: choose one that fits the
   intent (e.g. a health check reads naturally as a recent window with a
   previous-period comparison; a trend question needs day granularity over a
   longer window; "today"-flavored wording means today). Always state the
   period you assumed and offer to change it.
4. Vague questions (performance/summary): search the catalogue for the
   concepts implied by the question, query what resolves, state the metric
   ids used, and offer to swap — do not invent a fixed default pack.
5. Do not compute derived math yourself (no deltas, percentages, ratios,
   extrapolations). If the user wants a comparison, re-run metrics_query with
   compare_period and use insights_explain.
6. Quote provenance when presenting numbers: the time range, filters, and
   freshness from the provenance block (e.g. "as of <cube_last_refresh>").
   If metrics_query returns composed parts, quote each part's provenance;
   never invent numbers for a part that failed.
7. Ratio metrics must never be summed or averaged across rows — the insight
   engine already handles period totals correctly.
8. If a dimension is rejected for a metric, retry using the tool's suggested
   alternate metrics that support that dimension.
"""

EXPLAIN_METRIC_CHANGE = """\
Explain the metric change using ONLY the insights_explain output for query
{query_id}. Structure the explanation as:

1. Headline: metric, current vs compare period totals, delta and % change —
   exactly the numbers in `totals`.
2. Drivers: the top entries from `top_movers` with their contribution_pct.
   Mention new/disappeared keys explicitly.
3. Data quality notes: any `anomalies` entries, plus the freshness timestamp
   from provenance.

Do not add numbers that are not in the report. If something looks surprising,
suggest a drill-down (metrics_drilldown) instead of speculating.
"""

CONFIRM_ACTION = """\
An action has been proposed (action_request_id {action_request_id}). Before
committing, present the user a clear confirmation summary:

1. What will change: the `predicted_change` and the exact payload.
2. Current state: `current_state` from the preview.
3. Checks: each business rule result (pass/fail/unverifiable) in plain words.
4. Reversibility and risk level.
5. The token expiry time — the confirmation is only valid until then.

Then ask the user an explicit yes/no question. Only call actions_commit after
the user clearly answers yes. If they hesitate or ask questions, answer them
first; never auto-commit.
"""
