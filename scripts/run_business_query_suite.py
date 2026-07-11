"""Run the fixed business analytics query suite against live chat_web SSE.

Usage (from Base_Agent, with chat_web already on :8766):

    .\\.venv\\Scripts\\python.exe scripts\\run_business_query_suite.py
    .\\.venv\\Scripts\\python.exe scripts\\run_business_query_suite.py --ids B09,B05,B35,B44
    .\\.venv\\Scripts\\python.exe scripts\\run_business_query_suite.py --start 0 --limit 10

Writes JSONL + summary markdown under var/query_suite_results/.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHAT_BASE = "http://127.0.0.1:8766"
OUT_DIR = ROOT / "var" / "query_suite_results"

# Exact suite from coordinating agent (B01–B53 + G01–G05). Do not re-extract.
SUITE: list[dict] = [
    {"id": "B01", "cat": "revenue", "q": "Show net revenue and orders for the last 7 days.", "expect": "S"},
    {"id": "B02", "cat": "comparison", "q": "Compare the last 7 days with the preceding 7 days for revenue and orders.", "expect": "S"},
    {"id": "B03", "cat": "comparison", "q": "Show sales this month versus last month.", "expect": "S"},
    {"id": "B04", "cat": "time", "q": "Show orders and revenue by hour for yesterday.", "expect": "S"},
    {"id": "B05", "cat": "executive", "q": "Give me the last 7 days' business summary: revenue, orders, units, AOV, gross margin, ad spend, ROAS, and CAC.", "expect": "S"},
    {"id": "B06", "cat": "executive", "q": "Show business performance by brand for the last 30 days.", "expect": "S"},
    {"id": "B07", "cat": "executive", "q": "Show business performance by new versus returning customers for the last 30 days.", "expect": "S"},
    {"id": "B08", "cat": "insight", "q": "Show the biggest positive and negative changes in revenue versus the previous period, with contributing dimensions.", "expect": "S"},
    {"id": "B09", "cat": "revenue", "q": "What is net revenue for the last 30 days?", "expect": "S"},
    {"id": "B10", "cat": "revenue", "q": "What are valid, cancelled, refunded, prepaid, and COD order counts for the last 30 days?", "expect": "S"},
    {"id": "B11", "cat": "revenue", "q": "What is average order value and average units per order for the last 30 days?", "expect": "S"},
    {"id": "B12", "cat": "revenue", "q": "Show net revenue by payment method for the last 30 days.", "expect": "S"},
    {"id": "B13", "cat": "revenue", "q": "Show net revenue by country and by city for the last 30 days.", "expect": "S"},
    {"id": "B14", "cat": "product", "q": "Show net revenue by product and by SKU for the last 30 days.", "expect": "S"},
    {"id": "B15", "cat": "orders", "q": "List orders for the last 7 days with order ID, date, status, net revenue, customer type, city, and channel.", "expect": "S"},
    {"id": "B16", "cat": "attribution", "q": "For campaign TH-383-SUSPENDER-20JUNE, list attributed orders in the last 7 days with shipping city and state, then summarize orders and revenue by city.", "expect": "S"},
    {"id": "B17", "cat": "attribution", "q": "Show attributed orders by campaign and city for the last 7 days.", "expect": "S"},
    {"id": "B18", "cat": "orders", "q": "List order items for a recent high-value order, including SKU, quantity, price, discount, cost, and margin.", "expect": "S"},
    {"id": "B19", "cat": "orders", "q": "List orders containing SKU TH-SUSPENDER-BLK in the last 30 days.", "expect": "S"},
    {"id": "B20", "cat": "product", "q": "Show top 10 products by revenue and by gross profit for the last 30 days.", "expect": "S"},
    {"id": "B21", "cat": "product", "q": "Show bottom products by gross margin for the last 30 days.", "expect": "S"},
    {"id": "B22", "cat": "product", "q": "Show products with high refund or cancellation rates for the last 90 days.", "expect": "S"},
    {"id": "B23", "cat": "product", "q": "Show SKU-level unit economics and products with missing cost data.", "expect": "S"},
    {"id": "B24", "cat": "pnl", "q": "Show gross profit, gross margin %, contribution margin after ad spend, and net profit for the last 30 days.", "expect": "S"},
    {"id": "B25", "cat": "pnl", "q": "Show P&L by channel for the last 30 days.", "expect": "S"},
    {"id": "B26", "cat": "pnl", "q": "Show net revenue and gross margin by country for the last 90 days, compared with the previous 90 days.", "expect": "S"},
    {"id": "B27", "cat": "pnl", "q": "Identify channels with high revenue but poor profitability for the last 30 days.", "expect": "S"},
    {"id": "B28", "cat": "customers", "q": "How many unique, new, and returning customers purchased in the last 30 days, and what % of revenue is new vs returning?", "expect": "S"},
    {"id": "B29", "cat": "customers", "q": "What is customer LTV and LTV:CAC?", "expect": "S"},
    {"id": "B30", "cat": "customers", "q": "Show high-value and dormant customers.", "expect": "S"},
    {"id": "B31", "cat": "attribution", "q": "Show attributed revenue and attributed orders by campaign for the last 30 days.", "expect": "S"},
    {"id": "B32", "cat": "attribution", "q": "Show unattributed orders and revenue, and attribution coverage rate, for the last 30 days.", "expect": "S"},
    {"id": "B33", "cat": "attribution", "q": "Compare platform-reported purchases with backend attributed orders for Meta and Google over the last 30 days.", "expect": "S"},
    {"id": "B34", "cat": "attribution", "q": "Show last-touch attributed revenue by platform and UTM source/medium for the last 30 days.", "expect": "S"},
    {"id": "B35", "cat": "meta", "q": "Show Meta Ads spend, impressions, clicks, CTR, CPC, purchases, CPA, purchase value, and ROAS for the last 7 days by campaign.", "expect": "S"},
    {"id": "B36", "cat": "meta", "q": "Show campaigns spending without purchases, and campaigns with high CTR but low ROAS, for the last 14 days.", "expect": "S"},
    {"id": "B37", "cat": "meta", "q": "Show campaigns where platform ROAS and backend ROAS differ materially for the last 30 days.", "expect": "S"},
    {"id": "B38", "cat": "meta", "q": "Show hourly Meta spend and performance for yesterday; which hours are strongest?", "expect": "S"},
    {"id": "B39", "cat": "google", "q": "Show Google Ads spend, conversions, conversion value, CPA, and ROAS by campaign for the last 30 days.", "expect": "S"},
    {"id": "B40", "cat": "google", "q": "Compare Google-reported conversions with backend attributed Google orders for the last 30 days.", "expect": "S"},
    {"id": "B41", "cat": "cross_channel", "q": "Show total marketing spend, blended ROAS, MER, and spend/revenue by platform for the last 30 days.", "expect": "S"},
    {"id": "B42", "cat": "cross_channel", "q": "Compare Meta versus Google performance for the last 30 days.", "expect": "S"},
    {"id": "B43", "cat": "cross_channel", "q": "Compare paid versus organic attributed revenue for the last 30 days.", "expect": "S"},
    {"id": "B44", "cat": "funnel", "q": "Show sessions, product views, add-to-carts, checkouts, purchases, and conversion rate for the last 30 days.", "expect": "S"},
    {"id": "B45", "cat": "funnel", "q": "Show funnel conversion by channel and by campaign for the last 30 days.", "expect": "S"},
    {"id": "B46", "cat": "funnel", "q": "Show cart and checkout abandonment rates, and the largest funnel drop-off, for the last 30 days.", "expect": "S"},
    {"id": "B47", "cat": "fulfilment", "q": "Show fulfilled, unfulfilled, cancelled, and returned order counts for the last 30 days.", "expect": "S"},
    {"id": "B48", "cat": "fulfilment", "q": "Show RTO rate by city, product, and payment method for the last 90 days.", "expect": "S"},
    {"id": "B49", "cat": "marketplace", "q": "Compare D2C (Shopify) versus Amazon marketplace sales, orders, fees, and profit for the last 30 days.", "expect": "S"},
    {"id": "B50", "cat": "marketplace", "q": "Show Amazon ad spend and attributed sales by campaign type (SP/SB/SD) for the last 30 days.", "expect": "S"},
    {"id": "B51", "cat": "discounts", "q": "Show discount amount and discount rate, and full-price versus discounted sales, for the last 30 days.", "expect": "S"},
    {"id": "B52", "cat": "payments", "q": "Show sales by payment method and prepaid versus COD mix for the last 30 days.", "expect": "S"},
    {"id": "B53", "cat": "payments", "q": "Show payment gateway fees and refunds issued for the last 30 days.", "expect": "S"},
    {"id": "G01", "cat": "gap", "q": "Show current inventory by SKU and low-stock / out-of-stock items.", "expect": "U"},
    {"id": "G02", "cat": "gap", "q": "Show net revenue by discount code for the last 30 days.", "expect": "U"},
    {"id": "G03", "cat": "gap", "q": "What is median order value for the last 30 days?", "expect": "U"},
    {"id": "G04", "cat": "gap", "q": "Show first-touch attribution by campaign for the last 30 days.", "expect": "U"},
    {"id": "G05", "cat": "gap", "q": "Show Google search-term and keyword performance for the last 30 days.", "expect": "U"},
]


@dataclass
class Result:
    id: str
    cat: str
    question: str
    expect: str
    status: str
    failure_category: str | None
    summary: str
    tools: list[str]
    elapsed_s: float
    assistant_text: str


def _reset() -> None:
    req = urllib.request.Request(
        CHAT_BASE + "/reset",
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        resp.read()


def _chat_sse(message: str, timeout: float = 420) -> tuple[list[dict], float]:
    req = urllib.request.Request(
        CHAT_BASE + "/chat",
        data=json.dumps({"message": message}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.time()
    events: list[dict] = []
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        buf = ""
        while True:
            chunk = resp.read(4096)
            if not chunk:
                break
            buf += chunk.decode("utf-8", errors="replace")
            while "\n\n" in buf:
                block, buf = buf.split("\n\n", 1)
                for line in block.splitlines():
                    if line.startswith("data: "):
                        events.append(json.loads(line[6:]))
    return events, time.time() - t0


def _snip(s: str, n: int = 220) -> str:
    s = re.sub(r"\s+", " ", (s or "").strip())
    return s[:n] + ("…" if len(s) > n else "")


def _classify(expect: str, events: list[dict], assistant: str) -> tuple[str, str | None, str]:
    errors = [e.get("text", "") for e in events if e.get("type") == "error"]
    tools = [e.get("tool", "") for e in events if e.get("type") == "tool_call"]
    tool_previews = " ".join(e.get("preview", "") for e in events if e.get("type") == "tool_result")
    text = (assistant or "").lower()
    combined = (text + " " + tool_previews.lower())

    if errors and not assistant:
        return "error", "agent_runtime", _snip(errors[0])

    refuse_markers = [
        "not available", "not supported", "unsupported", "no inventory",
        "don't have", "do not have", "cannot answer", "can't answer",
        "no data model", "not in the catalogue", "not in the catalog",
        "no metric", "unable to", "not currently", "missing source",
        "first-touch", "discount code", "search term", "keyword", "median",
        "honestly refuse", "out of scope",
    ]

    if expect == "U":
        if any(m in combined for m in refuse_markers):
            return "pass", None, "Honest refusal for unsupported capability"
        if "metrics_query" in tools and ("error" in combined or "plan" in combined):
            return "pass", None, "Tool refused unsupported path"
        if re.search(r"\b\d[\d,]+\.?\d*\b", assistant or "") and "metrics_query" in tools:
            return "fail", "false_support", "Expected refusal but returned numeric answer"
        return "partial", "unclear_refusal", "Unsupported query — refusal not clearly evidenced"

    if "llm error" in combined:
        return "error", "llm", _snip(assistant)

    has_numbers = bool(re.search(r"\b\d[\d,]+\.?\d*\b", assistant or ""))
    used_query = "metrics_query" in tools
    used_explain = "insights_explain" in tools
    tool_err = (
        '"error"' in tool_previews.lower()
        or "planerror" in tool_previews.lower()
        or "plan_error" in combined
        or '"ok": false' in tool_previews.lower()
    )

    if used_query and tool_err:
        if "fan-out" in combined or "fan_out" in combined:
            return "fail", "fan_out_guard", _snip(tool_previews)
        if "same view" in combined or "multiple views" in combined or "must live on one view" in combined:
            return "fail", "cross_view", _snip(tool_previews)
        if "dimension" in combined and ("unsupported" in combined or "not available" in combined):
            return "fail", "schema_dimension", _snip(tool_previews)
        if "unknown metric" in combined or "not found" in combined:
            return "fail", "missing_measure", _snip(tool_previews)
        return "fail", "cube_or_plan", _snip(tool_previews)

    if (used_query or used_explain) and has_numbers:
        return "pass", None, _snip(assistant, 280)
    if used_query and not has_numbers:
        if "0 row" in combined or "no rows" in combined or "no data" in combined or "couldn't find" in combined:
            return "partial", "empty_result", _snip(assistant, 280)
        return "partial", "no_numeric_narration", _snip(assistant, 280)
    if has_numbers and not used_query and not used_explain:
        return "fail", "possible_hallucination", "Numbers without metrics_query"
    if any(m in text for m in ["not available", "cannot", "can't", "unsupported", "don't have", "which metric"]):
        return "fail", "false_refusal", _snip(assistant, 280)
    return "fail", "agent_reasoning", _snip(assistant or "no assistant text", 280)


def run_one(item: dict) -> Result:
    _reset()
    time.sleep(0.2)
    events, elapsed = _chat_sse(item["q"])
    assistant = ""
    tools: list[str] = []
    for e in events:
        if e.get("type") == "tool_call":
            tools.append(e.get("tool", ""))
        if e.get("type") == "assistant":
            assistant = e.get("text", "") or assistant
        if e.get("type") == "error" and not assistant:
            assistant = e.get("text", "")
    status, fail_cat, summary = _classify(item["expect"], events, assistant)
    return Result(
        id=item["id"],
        cat=item["cat"],
        question=item["q"],
        expect=item["expect"],
        status=status,
        failure_category=fail_cat,
        summary=summary,
        tools=tools,
        elapsed_s=round(elapsed, 1),
        assistant_text=assistant,
    )


def main() -> int:
    global CHAT_BASE
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--ids", type=str, default="")
    ap.add_argument("--base", type=str, default="")
    args = ap.parse_args()
    if args.base:
        CHAT_BASE = args.base.rstrip("/")

    items = SUITE
    if args.ids:
        want = {x.strip() for x in args.ids.split(",") if x.strip()}
        # preserve suite order
        items = [x for x in SUITE if x["id"] in want]
    else:
        items = SUITE[args.start :]
        if args.limit:
            items = items[: args.limit]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    jsonl = OUT_DIR / f"results_{stamp}.jsonl"
    md = OUT_DIR / f"summary_{stamp}.md"

    print(f"Running {len(items)} queries against {CHAT_BASE}", flush=True)
    results: list[Result] = []
    with jsonl.open("w", encoding="utf-8") as f:
        for i, item in enumerate(items, 1):
            qprev = item["q"][:70].encode("ascii", "replace").decode("ascii")
            print(f"[{i}/{len(items)}] {item['id']} {qprev}...", flush=True)
            try:
                r = run_one(item)
            except Exception as exc:
                r = Result(
                    id=item["id"], cat=item["cat"], question=item["q"], expect=item["expect"],
                    status="error", failure_category="runner", summary=str(exc)[:300],
                    tools=[], elapsed_s=0, assistant_text="",
                )
            results.append(r)
            f.write(json.dumps(asdict(r), ensure_ascii=False) + "\n")
            f.flush()
            safe = r.summary[:120].encode("ascii", "replace").decode("ascii")
            print(f"  -> {r.status} ({r.failure_category}) {r.elapsed_s}s | {safe}", flush=True)

    counts: dict[str, int] = {}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    lines = [
        f"# Business query suite results ({stamp})",
        "",
        f"Base: `{CHAT_BASE}`",
        f"Counts: {counts}",
        "",
        "| ID | Cat | Expect | Status | Fail cat | Sec | Summary |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| {r.id} | {r.cat} | {r.expect} | **{r.status}** | {r.failure_category or ''} | {r.elapsed_s} | {r.summary.replace('|', '/')} |"
        )
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nWrote {jsonl}\nWrote {md}\nCounts: {counts}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
