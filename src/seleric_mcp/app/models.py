"""Shared request/response models for the query path."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator

TimePreset = Literal[
    "today", "yesterday", "last_7d", "last_30d", "last_90d", "this_month", "last_month"
]
Granularity = Literal["day", "week", "month", "none"]
ComparePeriod = Literal["previous_period", "previous_year"]
FilterOperator = Literal[
    "equals", "notEquals", "contains", "gt", "gte", "lt", "lte", "set", "notSet"
]


class TimeRange(BaseModel):
    preset: TimePreset | None = None
    start: date | None = None
    end: date | None = None

    @model_validator(mode="after")
    def _preset_xor_explicit(self) -> "TimeRange":
        explicit = self.start is not None or self.end is not None
        if self.preset and explicit:
            raise ValueError("Provide either preset or start/end, not both")
        if not self.preset and (self.start is None or self.end is None):
            raise ValueError("Provide a preset, or both start and end")
        if self.start and self.end and self.start > self.end:
            raise ValueError("start must be <= end")
        return self


class FilterSpec(BaseModel):
    dimension: str  # catalogue dimension id
    operator: FilterOperator = "equals"
    values: list[str] = Field(default_factory=list)


class SortSpec(BaseModel):
    field: str  # a requested metric id, or a dimension id valid on the query's view
    direction: Literal["asc", "desc"] = "desc"


class QueryRequest(BaseModel):
    measures: list[str] = Field(min_length=1)  # catalogue metric ids
    dimensions: list[str] = Field(default_factory=list)
    filters: list[FilterSpec] = Field(default_factory=list)
    time_range: TimeRange
    granularity: Granularity = "none"
    compare_period: ComparePeriod | None = None
    sort: list[SortSpec] = Field(default_factory=list)  # e.g. top-N: sort by a
    # metric desc + limit=N. Empty means Cube's default order (date ascending
    # when a time dimension with granularity is present, else unordered).
    limit: int = Field(default=500, ge=1, le=5000)


class PlanError(ValueError):
    """Validation failure with guidance the LLM can act on (no guessing)."""

    def __init__(self, message: str, suggestions: list[str] | None = None):
        super().__init__(message)
        self.suggestions = suggestions or []

    def to_payload(self) -> dict:
        return {"error": str(self), "suggestions": self.suggestions}
