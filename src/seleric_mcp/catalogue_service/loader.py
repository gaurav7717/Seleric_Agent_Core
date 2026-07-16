"""Load the versioned YAML catalogue into typed in-memory definitions.

The YAML files under catalogue/ are the authoritative registry (reviewed like
code). catalogue_version is a short content hash so every response can pin the
exact registry it was answered from.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


class Formula(BaseModel):
    human_readable: str
    authoritative_source: Literal["cube"] = "cube"


class CubeMapping(BaseModel):
    view: str
    measure: str
    measure_pct: str | None = None
    # Fully-qualified time dimension (e.g. "commerce_orders.event_date") that
    # date-range filters must apply to for THIS metric, overriding the view's
    # default date_dimension. Event-axis metrics (returns/cancels) declare it;
    # placement-axis metrics leave it unset.
    time_dimension: str | None = None


class RatioComponents(BaseModel):
    numerator: str
    denominator: str


class AccessPolicy(BaseModel):
    roles_allowed: list[str] = Field(default_factory=list)
    scopes: list[str] = Field(default_factory=lambda: ["metrics:read"])


class Freshness(BaseModel):
    source: str
    expected_cadence: str


class MetricDef(BaseModel):
    id: str
    display_name: str
    category: str
    status: Literal["approved", "certified", "draft", "broken"] = "approved"

    @property
    def is_queryable(self) -> bool:
        return self.status in ("approved", "certified")
    description: str
    formula: Formula
    cube_mapping: CubeMapping
    aggregation: Literal["additive", "ratio"]
    ratio_components: RatioComponents | None = None
    companion_measures: list[str] = Field(default_factory=list)
    unit: str
    currency_default: str | None = None
    grain: str
    supported_dimensions: list[str] = Field(default_factory=list)
    supported_filters: list[str] = Field(default_factory=list)
    data_owner: str
    access_policy: AccessPolicy = Field(default_factory=AccessPolicy)
    examples: list[dict] = Field(default_factory=list)
    validation_tests: list[str] = Field(default_factory=list)
    deprecated_aliases: list[str] = Field(default_factory=list)


class DimensionDef(BaseModel):
    id: str
    display_name: str
    description: str = ""
    is_time: bool = False
    views: dict[str, str]  # view name -> qualified cube member
    allowed_values: list[str] | None = None  # declared only for small, stable
    # enum-like dimensions (verified against source SQL, not guessed) — lets
    # equals/notEquals filters be case/typo-corrected instead of silently
    # matching zero rows. None means "no known enum" — filter values pass
    # through unvalidated, exactly as before this field existed.


class GlossaryTerm(BaseModel):
    term: str
    canonical_id: str | None = None
    definition: str | None = None


class ViewDef(BaseModel):
    name: str
    title: str
    date_dimension: str | None = None
    freshness: Freshness


class BusinessRule(BaseModel):
    id: str
    description: str
    blocking: bool


class ActionContractDef(BaseModel):
    id: str
    display_name: str
    domain: str
    status: Literal["approved", "draft"] = "approved"
    description: str
    executor: Literal["pipeboard", "backend_api"]
    executor_action_type: str
    payload_schema: str
    scopes_required: list[str]
    risk_level: Literal["low", "medium", "high"]
    confirmation_ttl_seconds: int = 300
    business_rules: list[BusinessRule] = Field(default_factory=list)
    preview: dict = Field(default_factory=dict)
    data_owner: str


class Deprecation(BaseModel):
    old: str
    new: str
    reason: str


class OpenMetadataDataProduct(BaseModel):
    name: str
    domain: str
    owner_team: str
    primary_serve_table: str
    contract: str
    cube_views: list[str] = Field(default_factory=list)
    notes: str | None = None


class OpenMetadataViewLink(BaseModel):
    data_product: str
    serve_table: str
    gold_inputs: list[str] = Field(default_factory=list)
    contract: str | None = None


class OpenMetadataMetricLink(BaseModel):
    om_name: str | None = None
    glossary: list[str] = Field(default_factory=list)
    category: str | None = None
    cube_view: str | None = None
    contract: str | None = None


class OpenMetadataContract(BaseModel):
    serve_table: str
    data_product: str
    domain: str
    grain: list[str] = Field(default_factory=list)
    time_dimension: str | None = None
    currency: str = "INR"
    required_columns: list[str] = Field(default_factory=list)
    quality_tests: list[str] = Field(default_factory=list)
    attribution_boundary: str | None = None
    notes: str | None = None
    program: str | None = None


class OpenMetadataOntology(BaseModel):
    domains: dict = Field(default_factory=dict)
    entity_clusters: dict = Field(default_factory=dict)
    attribution_boundary: dict = Field(default_factory=dict)


class OpenMetadataRegistry(BaseModel):
    instance: dict = Field(default_factory=dict)
    agent_ready_tag: str = "DataProduct.AgentReady"
    release_status_tag: str = "ReleaseStatus.Certified"
    currency: str = "INR"
    data_products: list[OpenMetadataDataProduct] = Field(default_factory=list)
    views: dict[str, OpenMetadataViewLink] = Field(default_factory=dict)
    metrics: dict[str, OpenMetadataMetricLink] = Field(default_factory=list)
    contracts: dict[str, OpenMetadataContract] = Field(default_factory=dict)
    ontology: OpenMetadataOntology | None = None
    glossaries: list[dict] = Field(default_factory=list)


class Catalogue(BaseModel):
    version: str
    metrics: dict[str, MetricDef]
    dimensions: dict[str, DimensionDef]
    glossary: list[GlossaryTerm]
    views: dict[str, ViewDef]
    actions: dict[str, ActionContractDef]
    deprecations: list[Deprecation]
    openmetadata: OpenMetadataRegistry | None = None


def _read_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_catalogue(catalogue_dir: Path) -> Catalogue:
    hasher = hashlib.sha256()
    yaml_files = sorted(catalogue_dir.rglob("*.yaml"))
    if not yaml_files:
        raise FileNotFoundError(f"No catalogue YAML found under {catalogue_dir}")
    for p in yaml_files:
        hasher.update(p.read_bytes())
    version = hasher.hexdigest()[:12]

    metrics: dict[str, MetricDef] = {}
    for p in sorted((catalogue_dir / "metrics").glob("*.yaml")):
        m = MetricDef.model_validate(_read_yaml(p))
        metrics[m.id] = m

    dimensions: dict[str, DimensionDef] = {}
    for p in sorted((catalogue_dir / "dimensions").glob("*.yaml")):
        for raw in _read_yaml(p).get("dimensions", []):
            d = DimensionDef.model_validate(raw)
            dimensions[d.id] = d

    glossary = [
        GlossaryTerm.model_validate(raw)
        for raw in _read_yaml(catalogue_dir / "glossary" / "terms.yaml").get("terms", [])
    ]

    views: dict[str, ViewDef] = {}
    for raw in _read_yaml(catalogue_dir / "views.yaml").get("views", []):
        v = ViewDef.model_validate(raw)
        views[v.name] = v

    actions: dict[str, ActionContractDef] = {}
    actions_dir = catalogue_dir / "actions"
    if actions_dir.exists():
        for p in sorted(actions_dir.glob("*.yaml")):
            a = ActionContractDef.model_validate(_read_yaml(p))
            actions[a.id] = a

    deprecations = [
        Deprecation.model_validate(raw)
        for raw in _read_yaml(catalogue_dir / "deprecations.yaml").get("deprecations", [])
    ]

    om_registry: OpenMetadataRegistry | None = None
    om_path = catalogue_dir / "openmetadata" / "registry.yaml"
    if om_path.exists():
        om_raw = _read_yaml(om_path)
        metrics_path = catalogue_dir / "openmetadata" / "metrics.yaml"
        if metrics_path.exists():
            metrics_doc = _read_yaml(metrics_path)
            om_raw["metrics"] = metrics_doc.get("metrics", {})
        contracts_path = catalogue_dir / "openmetadata" / "contracts.yaml"
        if contracts_path.exists():
            om_raw["contracts"] = _read_yaml(contracts_path).get("contracts", {})
        ontology_path = catalogue_dir / "openmetadata" / "ontology.yaml"
        if ontology_path.exists():
            om_raw["ontology"] = _read_yaml(ontology_path)
        om_registry = OpenMetadataRegistry.model_validate(om_raw)

    cat = Catalogue(
        version=version,
        metrics=metrics,
        dimensions=dimensions,
        glossary=glossary,
        views=views,
        actions=actions,
        deprecations=deprecations,
        openmetadata=om_registry,
    )
    _check_integrity(cat)
    return cat


def _check_integrity(cat: Catalogue) -> None:
    """Fail fast on internal inconsistencies (bad refs between YAML files)."""
    problems: list[str] = []
    for m in cat.metrics.values():
        if m.cube_mapping.view not in cat.views:
            problems.append(f"metric {m.id}: unknown view {m.cube_mapping.view}")
        if m.cube_mapping.time_dimension and not m.cube_mapping.time_dimension.startswith(
            f"{m.cube_mapping.view}."
        ):
            problems.append(
                f"metric {m.id}: time_dimension {m.cube_mapping.time_dimension} "
                f"is not on view {m.cube_mapping.view}"
            )
        for dim_id in m.supported_dimensions:
            dim = cat.dimensions.get(dim_id)
            if dim is None:
                problems.append(f"metric {m.id}: unknown dimension {dim_id}")
            elif m.cube_mapping.view not in dim.views:
                problems.append(
                    f"metric {m.id}: dimension {dim_id} has no mapping for view {m.cube_mapping.view}"
                )
    for t in cat.glossary:
        if t.canonical_id is not None and t.canonical_id not in cat.metrics:
            problems.append(f"glossary term '{t.term}': unknown canonical_id {t.canonical_id}")
    if cat.openmetadata:
        for view_name, link in cat.openmetadata.views.items():
            if view_name not in cat.views:
                problems.append(f"openmetadata.views.{view_name}: unknown catalogue view")
            if link.data_product not in {dp.name for dp in cat.openmetadata.data_products}:
                problems.append(
                    f"openmetadata.views.{view_name}: unknown data_product {link.data_product}"
                )
        for metric_id in cat.openmetadata.metrics:
            if metric_id not in cat.metrics:
                problems.append(f"openmetadata.metrics.{metric_id}: unknown catalogue metric")
        if len(cat.openmetadata.metrics) != len(cat.metrics):
            problems.append(
                f"openmetadata.metrics: expected {len(cat.metrics)} entries, "
                f"got {len(cat.openmetadata.metrics)}"
            )
        for contract_id, dp_names in _contract_dp_refs(cat).items():
            if contract_id not in cat.openmetadata.contracts:
                problems.append(f"openmetadata: missing contract definition for {contract_id}")
            elif cat.openmetadata.contracts[contract_id].data_product not in dp_names:
                problems.append(
                    f"openmetadata.contracts.{contract_id}: data_product mismatch"
                )
    if problems:
        raise ValueError("Catalogue integrity check failed:\n" + "\n".join(problems))


def _contract_dp_refs(cat: Catalogue) -> dict[str, set[str]]:
    refs: dict[str, set[str]] = {}
    for dp in cat.openmetadata.data_products:  # type: ignore[union-attr]
        refs.setdefault(dp.contract, set()).add(dp.name)
    for link in cat.openmetadata.views.values():  # type: ignore[union-attr]
        if link.contract:
            dp = link.data_product
            refs.setdefault(link.contract, set()).add(dp)
    return refs
