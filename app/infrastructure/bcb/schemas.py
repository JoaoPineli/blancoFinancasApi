"""BCB API response schemas."""

from datetime import date
from decimal import Decimal
from typing import List

from pydantic import BaseModel, Field


class SGSDataPoint(BaseModel):
    """Single data point from SGS API."""

    data: str = Field(..., description="Date in DD/MM/YYYY format")
    valor: str = Field(..., description="Value as string")

    @property
    def reference_date(self) -> date:
        """Parse date from BCB format."""
        day, month, year = self.data.split("/")
        return date(int(year), int(month), int(day))

    @property
    def rate(self) -> Decimal:
        """Parse rate value."""
        return Decimal(self.valor.replace(",", "."))


class SGSResponse(BaseModel):
    """Response from BCB SGS API."""

    data_points: List[SGSDataPoint]

    @classmethod
    def from_json(cls, data: List[dict]) -> "SGSResponse":
        """Parse JSON response from BCB API."""
        points = [SGSDataPoint(**item) for item in data]
        return cls(data_points=points)
