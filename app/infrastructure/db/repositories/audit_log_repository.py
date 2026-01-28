"""Audit log repository implementation."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.audit_log import AuditAction, AuditLog
from app.infrastructure.db.models import AuditLogModel


class AuditLogRepository:
    """Repository for AuditLog entity persistence."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize repository with database session."""
        self._session = session

    async def get_by_id(self, audit_id: UUID) -> Optional[AuditLog]:
        """Get audit log by ID."""
        result = await self._session.execute(
            select(AuditLogModel).where(AuditLogModel.id == audit_id)
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def get_by_actor(
        self,
        actor_id: UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> List[AuditLog]:
        """Get audit logs by actor."""
        result = await self._session.execute(
            select(AuditLogModel)
            .where(AuditLogModel.actor_id == actor_id)
            .order_by(AuditLogModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        models = result.scalars().all()
        return [self._to_entity(model) for model in models]

    async def get_by_target(
        self,
        target_id: UUID,
        target_type: Optional[str] = None,
    ) -> List[AuditLog]:
        """Get audit logs by target entity."""
        query = select(AuditLogModel).where(AuditLogModel.target_id == target_id)

        if target_type:
            query = query.where(AuditLogModel.target_type == target_type)

        query = query.order_by(AuditLogModel.created_at.desc())
        result = await self._session.execute(query)
        models = result.scalars().all()
        return [self._to_entity(model) for model in models]

    async def get_by_action(
        self,
        action: AuditAction,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[AuditLog]:
        """Get audit logs by action type."""
        query = select(AuditLogModel).where(AuditLogModel.action == action.value)

        if start_date:
            query = query.where(AuditLogModel.created_at >= start_date)
        if end_date:
            query = query.where(AuditLogModel.created_at <= end_date)

        query = query.order_by(AuditLogModel.created_at.desc()).limit(limit)
        result = await self._session.execute(query)
        models = result.scalars().all()
        return [self._to_entity(model) for model in models]

    async def save(self, audit_log: AuditLog) -> AuditLog:
        """Save audit log entry."""
        model = self._to_model(audit_log)
        self._session.add(model)
        await self._session.flush()
        return self._to_entity(model)

    def _to_entity(self, model: AuditLogModel) -> AuditLog:
        """Map ORM model to domain entity."""
        return AuditLog(
            id=model.id,
            action=AuditAction(model.action),
            actor_id=model.actor_id,
            target_id=model.target_id,
            target_type=model.target_type,
            details=model.details,
            ip_address=model.ip_address,
            created_at=model.created_at,
        )

    def _to_model(self, entity: AuditLog) -> AuditLogModel:
        """Map domain entity to ORM model."""
        return AuditLogModel(
            id=entity.id,
            action=entity.action.value,
            actor_id=entity.actor_id,
            target_id=entity.target_id,
            target_type=entity.target_type,
            details=entity.details,
            ip_address=entity.ip_address,
            created_at=entity.created_at,
        )
