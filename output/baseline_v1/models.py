"""Structured vendor recommendation and per-run dependencies."""
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ConfigDict


class Recommendation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    vendor: str | None = Field(description='Vendor name stated in the document, or null if unknown')
    sku: str | None = Field(description='Campus Customs SKU, or null if unknown')
    unit_price: float | None = Field(ge=0, description='Quoted unit price in USD, or null if unknown')
    lead_time_days: int | None = Field(ge=0, description='Quoted number of days; retain business-day qualifier in reason when relevant; null if unknown')
    minimum_order: int | None = Field(ge=0, description='Minimum order in units, or null if unknown')
    decision: Literal['recommend', 'do_not_recommend']
    reason: str = Field(min_length=1, description='One sentence explaining the deciding handbook purchasing checks')


@dataclass
class RunDeps:
    run_id: str
    document: Path
    output: Path
