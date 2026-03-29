"""DTOs for subscription activation payment."""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from uuid import UUID


@dataclass
class CreateActivationPaymentInput:
    user_id: UUID
    subscription_id: UUID


@dataclass
class ActivationPaymentDTO:
    id: UUID
    user_id: UUID
    subscription_id: UUID
    status: str
    admin_tax_cents: int
    insurance_cents: int
    pix_transaction_fee_cents: int
    total_amount_cents: int
    pix_qr_code_data: Optional[str]
    pix_transaction_id: Optional[str]
    expiration_minutes: int
    created_at: datetime
    updated_at: datetime
    confirmed_at: Optional[datetime]
