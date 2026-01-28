"""Yield data repository implementation."""

from datetime import date
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.yield_data import SGSSeries, YieldData
from app.infrastructure.db.models import YieldDataModel


class YieldDataRepository:
    """Repository for YieldData entity persistence.

    All BCB yield data used in calculations MUST be persisted locally.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize repository with database session."""
        self._session = session

    async def get_by_id(self, yield_data_id: UUID) -> Optional[YieldData]:
        """Get yield data by ID."""
        result = await self._session.execute(
            select(YieldDataModel).where(YieldDataModel.id == yield_data_id)
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def get_by_date_and_series(
        self,
        reference_date: date,
        series_id: SGSSeries,
    ) -> Optional[YieldData]:
        """Get yield data for specific date and series."""
        result = await self._session.execute(
            select(YieldDataModel)
            .where(YieldDataModel.reference_date == reference_date)
            .where(YieldDataModel.series_id == series_id.value)
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def get_range(
        self,
        series_id: SGSSeries,
        start_date: date,
        end_date: date,
    ) -> List[YieldData]:
        """Get yield data for a date range.

        Args:
            series_id: SGS series to query
            start_date: Start of range (inclusive)
            end_date: End of range (inclusive)

        Returns:
            List of YieldData for the range
        """
        result = await self._session.execute(
            select(YieldDataModel)
            .where(YieldDataModel.series_id == series_id.value)
            .where(YieldDataModel.reference_date >= start_date)
            .where(YieldDataModel.reference_date <= end_date)
            .order_by(YieldDataModel.reference_date.asc())
        )
        models = result.scalars().all()
        return [self._to_entity(model) for model in models]

    async def save(self, yield_data: YieldData) -> YieldData:
        """Save yield data (create or update)."""
        model = self._to_model(yield_data)
        merged = await self._session.merge(model)
        await self._session.flush()
        return self._to_entity(merged)

    async def save_batch(self, yield_data_list: List[YieldData]) -> List[YieldData]:
        """Save multiple yield data entries."""
        saved = []
        for yield_data in yield_data_list:
            saved.append(await self.save(yield_data))
        return saved

    def _to_entity(self, model: YieldDataModel) -> YieldData:
        """Map ORM model to domain entity."""
        return YieldData(
            id=model.id,
            series_id=SGSSeries(model.series_id),
            reference_date=model.reference_date.date()
            if hasattr(model.reference_date, "date")
            else model.reference_date,
            rate=model.rate,
            fetched_at=model.fetched_at,
        )

    def _to_model(self, entity: YieldData) -> YieldDataModel:
        """Map domain entity to ORM model."""
        from datetime import datetime

        ref_date = entity.reference_date
        if isinstance(ref_date, date) and not isinstance(ref_date, datetime):
            ref_date = datetime.combine(ref_date, datetime.min.time())

        return YieldDataModel(
            id=entity.id,
            series_id=entity.series_id.value,
            reference_date=ref_date,
            rate=entity.rate,
            fetched_at=entity.fetched_at,
        )
