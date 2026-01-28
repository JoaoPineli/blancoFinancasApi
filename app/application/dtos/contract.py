"""Contract DTOs."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from uuid import UUID


@dataclass
class ContractDTO:
    """Contract data transfer object."""

    id: UUID
    user_id: UUID
    plan_id: UUID
    status: str
    pdf_storage_path: Optional[str]
    accepted_at: Optional[datetime]
    start_date: Optional[datetime]
    end_date: Optional[datetime]
    created_at: datetime


@dataclass
class CreateContractInput:
    """Input for creating a contract."""

    user_id: UUID
    plan_id: UUID


@dataclass
class AcceptContractInput:
    """Input for accepting a contract."""

    contract_id: UUID
    user_id: UUID
