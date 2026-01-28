"""User DTOs."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from uuid import UUID


@dataclass
class UserDTO:
    """User data transfer object."""

    id: UUID
    cpf: str
    email: str
    name: str
    role: str
    status: str
    phone: Optional[str]
    created_at: datetime
    updated_at: datetime


@dataclass
class UserListDTO:
    """User list data transfer object."""

    users: list[UserDTO]
    total: int
    page: int
    page_size: int
