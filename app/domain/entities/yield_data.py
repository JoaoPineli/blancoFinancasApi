"""Yield Data entity - Domain model for BCB yield data storage."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID, uuid4


class SGSSeries(Enum):
    """BCB SGS Series for poupança yield.

    SGS 25: Depósitos de poupança (até 03/05/2012)
    SGS 195: Depósitos de poupança (a partir de 04/05/2012)
    """

    PRE_2012 = 25  # SGS 25
    POST_2012 = 195  # SGS 195


@dataclass
class YieldData:
    """Yield data entity for BCB poupança rates.

    Stores fetched BCB data for deterministic recalculation.
    All yield data used in calculations MUST be persisted locally.
    """

    id: UUID
    series_id: SGSSeries
    reference_date: date
    rate: Decimal  # Rate as decimal (e.g., 0.005 for 0.5%)
    fetched_at: datetime = field(default_factory=datetime.utcnow)

    @classmethod
    def create(
        cls,
        series_id: SGSSeries,
        reference_date: date,
        rate: Decimal,
    ) -> YieldData:
        """Factory method to create yield data entry."""
        return cls(
            id=uuid4(),
            series_id=series_id,
            reference_date=reference_date,
            rate=rate,
            fetched_at=datetime.utcnow(),
        )

    @classmethod
    def get_series_for_date(cls, reference_date: date) -> SGSSeries:
        """Get the appropriate SGS series for a given date.

        Series switching (pre/post 2012) is explicit.

        Args:
            reference_date: Date to determine series

        Returns:
            Appropriate SGS series
        """
        cutoff_date = date(2012, 5, 4)
        if reference_date < cutoff_date:
            return SGSSeries.PRE_2012
        return SGSSeries.POST_2012
