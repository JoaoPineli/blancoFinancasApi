"""Wallet repository implementation."""

from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.wallet import Wallet
from app.infrastructure.db.models import WalletModel


class WalletRepository:
    """Repository for Wallet entity persistence."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize repository with database session."""
        self._session = session

    async def get_by_id(self, wallet_id: UUID) -> Optional[Wallet]:
        """Get wallet by ID."""
        result = await self._session.execute(
            select(WalletModel).where(WalletModel.id == wallet_id)
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def get_by_user_id(self, user_id: UUID) -> Optional[Wallet]:
        """Get wallet by user ID."""
        result = await self._session.execute(
            select(WalletModel).where(WalletModel.user_id == user_id)
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def save(self, wallet: Wallet) -> Wallet:
        """Save wallet (create or update)."""
        model = self._to_model(wallet)
        merged = await self._session.merge(model)
        await self._session.flush()
        return self._to_entity(merged)

    async def delete(self, wallet_id: UUID) -> bool:
        """Delete wallet by ID."""
        result = await self._session.execute(
            select(WalletModel).where(WalletModel.id == wallet_id)
        )
        model = result.scalar_one_or_none()
        if model:
            await self._session.delete(model)
            return True
        return False

    def _to_entity(self, model: WalletModel) -> Wallet:
        """Map ORM model to domain entity."""
        return Wallet(
            id=model.id,
            user_id=model.user_id,
            balance_cents=model.balance_cents,
            total_invested_cents=model.total_invested_cents,
            total_yield_cents=model.total_yield_cents,
            fundo_garantidor_cents=model.fundo_garantidor_cents,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    def _to_model(self, entity: Wallet) -> WalletModel:
        """Map domain entity to ORM model."""
        return WalletModel(
            id=entity.id,
            user_id=entity.user_id,
            balance_cents=entity.balance_cents,
            total_invested_cents=entity.total_invested_cents,
            total_yield_cents=entity.total_yield_cents,
            fundo_garantidor_cents=entity.fundo_garantidor_cents,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )
