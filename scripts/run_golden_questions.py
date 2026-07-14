#!/usr/bin/env python3
"""Golden-question resolution suite — Commerce.CommercePerformance.

Validates the CATALOGUE-RESOLUTION level of each golden question: the expected
metric ids must be reachable from the question text via CatalogueService
keyword search, ambiguous questions must NOT auto-resolve to a single metric,
and unsupported questions must not resolve to a commerce metric at all. This
is the deterministic layer under the agent; full agent-behavior evals live in
run_business_query_suite.py (requires the live chat service).

  uv run python scripts/run_golden_questions.py
  uv run python scripts/run_golden_questions.py --file <golden_questions.yml>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

DEFAULT_FILE = (
    PROJECT_ROOT.parent
    / "data_platform"
    / "mage-ai"
    / "serve"
    / "evaluations"
    / "golden_questions.yml"
)


def main() -> int:
    from seleric_mcp.catalogue_service.loader import load_catalogue
    from seleric_mcp.catalogue_service.service import CatalogueService

    p = argparse.ArgumentParser()
    p.add_argument("--file", type=Path, default=DEFAULT_FILE)
    args = p.parse_args()

    doc = yaml.safe_load(args.file.read_text(encoding="utf-8"))
    svc = CatalogueService(load_catalogue(PROJECT_ROOT / "catalogue"))

    failures: list[str] = []
    for item in doc["questions"]:
        q = item["question"]
        exp = item["expected"]
        intent = exp.get("intent", "metric_total")
        expected_metrics = exp.get("metrics") or ([exp["metric"]] if exp.get("metric") else [])

        matches = [m.id for m in svc.search(q).matches]

        if intent in ("metric_total", "metric_breakdown", "metric_compare"):
            missing = [m for m in expected_metrics if m not in matches]
            if missing:
                failures.append(f"{q!r}: expected {missing} in search matches, got {matches[:8]}")
                continue
            for dim in exp.get("dimensions", []):
                if svc.cat.dimensions.get(dim) is None:
                    failures.append(f"{q!r}: expected dimension '{dim}' not in catalogue")
        elif intent == "ambiguous":
            resolved = svc.resolve_term(q)
            if getattr(resolved, "kind", "") == "resolved" and not getattr(
                resolved, "auto_resolved", False
            ):
                failures.append(
                    f"{q!r}: must require clarification but resolved exactly to "
                    f"{resolved.metric_id}"
                )
            candidates = exp.get("candidates", [])
            missing = [m for m in candidates if m not in matches]
            if missing:
                failures.append(f"{q!r}: ambiguity candidates {missing} not surfaced ({matches[:8]})")
        elif intent == "unsupported":
            resolved = svc.resolve_term(q)
            if getattr(resolved, "kind", "") == "resolved":
                failures.append(
                    f"{q!r}: unsupported question must not resolve, got {resolved.metric_id}"
                )
        else:
            failures.append(f"{q!r}: unknown expected intent {intent!r}")

        status = "FAIL" if failures and failures[-1].startswith(repr(q)) else "OK  "
        print(f"{status} [{intent}] {q}")

    print(f"\n{len(doc['questions']) - len(failures)}/{len(doc['questions'])} passed")
    for f in failures:
        print(f"  FAIL {f}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
