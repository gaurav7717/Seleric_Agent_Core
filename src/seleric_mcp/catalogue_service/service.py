"""Catalogue query API: keyword search, term resolution, metric/dimension
lookup, freshness. Structured metadata is authoritative — no vector index.

Term resolution is confidence-banded: an exact normalized match (spacing/
underscores/case) or a near-exact fuzzy match above AUTO_RESOLVE_THRESHOLD
resolves deterministically with a stated confidence; a middle band returns
`ambiguous` with ranked candidates for the host LLM/user to choose; anything
below returns `unknown`. The server never silently picks a weak match.
"""

from __future__ import annotations

import difflib
import re
from typing import Literal

from pydantic import BaseModel

from .loader import Catalogue, DimensionDef, MetricDef

# Fuzzy-resolution band fallbacks (SequenceMatcher ratio on normalized
# strings). Runtime values come from Settings (env-overridable); these only
# apply when CatalogueService is constructed without explicit thresholds.
AUTO_RESOLVE_THRESHOLD = 0.85   # >= this and a clear winner -> resolved
AMBIGUOUS_THRESHOLD = 0.60      # >= this -> ambiguous with candidates
RUNNER_UP_MARGIN = 0.05         # winner must beat #2 by this to auto-resolve


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


class MetricSummary(BaseModel):
    id: str
    display_name: str
    category: str
    description: str
    aggregation: str
    view: str
    supported_dimensions: list[str]
    matched_on: str  # which field/synonym matched


class SearchResult(BaseModel):
    matches: list[MetricSummary]
    suggestions: list[str]
    catalogue_version: str


class ResolvedTerm(BaseModel):
    kind: Literal["resolved"] = "resolved"
    term: str
    metric_id: str
    confidence: float = 1.0
    auto_resolved: bool = False  # true when resolved via fuzzy match, not exact
    matched_via: str | None = None  # e.g. "metric_id", "display_name", "glossary:topline"
    definition: str | None = None
    deprecation_notice: str | None = None


class DefinitionOnlyTerm(BaseModel):
    kind: Literal["definition_only"] = "definition_only"
    term: str
    definition: str


class TermCandidate(BaseModel):
    metric_id: str
    display_name: str
    confidence: float
    matched_via: str


class AmbiguousTerm(BaseModel):
    kind: Literal["ambiguous"] = "ambiguous"
    term: str
    candidates: list[TermCandidate]
    guidance: str = (
        "Several catalogue metrics plausibly match. Pick the candidate that "
        "clearly fits the user's intent and state the substitution, or ask "
        "the user to choose if none obviously fits."
    )


class UnknownTerm(BaseModel):
    kind: Literal["unknown"] = "unknown"
    term: str
    suggestions: list[str]
    guidance: str = (
        "Term not in the catalogue. Do not guess a metric — ask the user to "
        "clarify, or pick from the suggestions if one clearly matches."
    )


class CatalogueService:
    def __init__(
        self,
        catalogue: Catalogue,
        *,
        auto_threshold: float = AUTO_RESOLVE_THRESHOLD,
        ambiguous_threshold: float = AMBIGUOUS_THRESHOLD,
        runner_up_margin: float = RUNNER_UP_MARGIN,
    ):
        self.cat = catalogue
        self.auto_threshold = auto_threshold
        self.ambiguous_threshold = ambiguous_threshold
        self.runner_up_margin = runner_up_margin
        # term (lowercased) -> GlossaryTerm
        self._glossary_index = {t.term.lower(): t for t in catalogue.glossary}
        # alias (lowercased) -> metric id
        self._alias_index: dict[str, str] = {}
        for m in catalogue.metrics.values():
            for alias in m.deprecated_aliases:
                self._alias_index[alias.lower()] = m.id

    @property
    def version(self) -> str:
        return self.cat.version

    def _searchable_metrics(self) -> list[MetricDef]:
        return [m for m in self.cat.metrics.values() if m.status == "approved"]

    def _vocab_entries(self) -> list[tuple[str, str, str]]:
        """(normalized_form, metric_id, matched_via) for every resolvable name."""
        entries: list[tuple[str, str, str]] = []
        approved = {m.id for m in self._searchable_metrics()}
        for m in self._searchable_metrics():
            entries.append((_normalize(m.id), m.id, "metric_id"))
            entries.append((_normalize(m.display_name), m.id, "display_name"))
        for term, entry in self._glossary_index.items():
            if entry.canonical_id and entry.canonical_id in approved:
                entries.append((_normalize(term), entry.canonical_id, f"glossary:{term}"))
        return entries

    def _vocabulary(self) -> list[str]:
        vocab = list(self._glossary_index.keys())
        for m in self._searchable_metrics():
            vocab.append(m.id)
            vocab.append(m.display_name.lower())
        return vocab

    def search(self, query: str) -> SearchResult:
        q = _normalize(query)
        matches: dict[str, MetricSummary] = {}

        def add(m: MetricDef, matched_on: str) -> None:
            if m.status != "approved" or m.id in matches:
                return
            matches[m.id] = MetricSummary(
                id=m.id,
                display_name=m.display_name,
                category=m.category,
                description=m.description.strip(),
                aggregation=m.aggregation,
                view=m.cube_mapping.view,
                supported_dimensions=m.supported_dimensions,
                matched_on=matched_on,
            )

        # 1. Exact glossary hits rank first (the query may contain several terms).
        for term, entry in self._glossary_index.items():
            if term in q and entry.canonical_id:
                m = self.cat.metrics.get(entry.canonical_id)
                if m:
                    add(m, f"glossary:{term}")

        # 2. Token overlap on id / display_name / description.
        q_tokens = set(q.replace(",", " ").split())
        for m in self._searchable_metrics():
            hay_id = set(m.id.lower().replace("_", " ").split())
            hay_name = set(m.display_name.lower().split())
            if q_tokens & hay_id or q_tokens & hay_name:
                add(m, "name")
            elif any(tok in m.description.lower() for tok in q_tokens if len(tok) > 3):
                add(m, "description")

        suggestions: list[str] = []
        if not matches:
            suggestions = difflib.get_close_matches(q, self._vocabulary(), n=5, cutoff=0.5)
        return SearchResult(
            matches=list(matches.values()),
            suggestions=suggestions,
            catalogue_version=self.version,
        )

    def resolve_term(
        self, text: str
    ) -> ResolvedTerm | DefinitionOnlyTerm | AmbiguousTerm | UnknownTerm:
        t = text.strip().lower()

        # 1. Exact lookups (raw form): glossary, metric id, deprecated alias.
        entry = self._glossary_index.get(t)
        if entry is not None:
            if entry.canonical_id:
                return ResolvedTerm(
                    term=text, metric_id=entry.canonical_id,
                    matched_via=f"glossary:{t}", definition=entry.definition,
                )
            return DefinitionOnlyTerm(term=text, definition=entry.definition or "")
        if t in self.cat.metrics and self.cat.metrics[t].status == "approved":
            return ResolvedTerm(term=text, metric_id=t, matched_via="metric_id")
        alias_target = self._alias_index.get(t)
        if alias_target:
            return ResolvedTerm(
                term=text,
                metric_id=alias_target,
                matched_via="deprecated_alias",
                deprecation_notice=(
                    f"'{text}' is a deprecated name; the canonical metric is "
                    f"'{alias_target}'."
                ),
            )

        # 2. Exact match after normalization ("net profit" == net_profit).
        norm = _normalize(text)
        entries = self._vocab_entries()
        for form, metric_id, via in entries:
            if form == norm:
                return ResolvedTerm(term=text, metric_id=metric_id, matched_via=via)

        # 3. Fuzzy, confidence-banded. Score the best form per metric.
        best_per_metric: dict[str, tuple[float, str]] = {}
        for form, metric_id, via in entries:
            ratio = difflib.SequenceMatcher(None, norm, form).ratio()
            if metric_id not in best_per_metric or ratio > best_per_metric[metric_id][0]:
                best_per_metric[metric_id] = (ratio, via)
        ranked = sorted(
            (
                TermCandidate(
                    metric_id=mid,
                    display_name=self.cat.metrics[mid].display_name,
                    confidence=round(score, 2),
                    matched_via=via,
                )
                for mid, (score, via) in best_per_metric.items()
            ),
            key=lambda c: c.confidence,
            reverse=True,
        )
        if ranked and ranked[0].confidence >= self.auto_threshold:
            clear_winner = (
                len(ranked) == 1
                or ranked[0].confidence - ranked[1].confidence >= self.runner_up_margin
            )
            if clear_winner:
                top = ranked[0]
                return ResolvedTerm(
                    term=text,
                    metric_id=top.metric_id,
                    confidence=top.confidence,
                    auto_resolved=True,
                    matched_via=top.matched_via,
                )
        contenders = [c for c in ranked if c.confidence >= self.ambiguous_threshold][:5]
        if contenders:
            return AmbiguousTerm(term=text, candidates=contenders)
        return UnknownTerm(
            term=text,
            suggestions=difflib.get_close_matches(norm, self._vocabulary(), n=5, cutoff=0.5),
        )

    def get_metric(self, metric_id: str) -> MetricDef | None:
        return self.cat.metrics.get(metric_id)

    def list_dimensions(self, view: str) -> list[DimensionDef]:
        return [d for d in self.cat.dimensions.values() if view in d.views]

    def freshness(self, view: str) -> dict | None:
        v = self.cat.views.get(view)
        return v.freshness.model_dump() if v else None

    def mark_broken(self, metric_id: str) -> None:
        m = self.cat.metrics.get(metric_id)
        if m:
            m.status = "broken"
