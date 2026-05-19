from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.alpha import AlphaFeatureResponse


class FeatureCatalogItemResponse(BaseModel):
    name: str
    family: str
    description: str
    output_type: str
    timeframes_supported: bool = True


class FeatureCatalogResponse(BaseModel):
    items: list[FeatureCatalogItemResponse] = Field(default_factory=list)
    count: int


class FeatureComputeRequest(BaseModel):
    symbol: str


class FeatureComputeBatchRequest(BaseModel):
    symbols: list[str] = Field(default_factory=list)


class FeatureRunResponse(BaseModel):
    run_id: str
    symbol: str
    source_name: str
    status: str
    generated_at: datetime
    timeframes: list[str] = Field(default_factory=list)
    catalog_version: str
    feature_snapshot: AlphaFeatureResponse | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class FeatureRunListResponse(BaseModel):
    items: list[FeatureRunResponse] = Field(default_factory=list)
    count: int
