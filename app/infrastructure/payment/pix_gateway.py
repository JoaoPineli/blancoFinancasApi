"""Pix gateway adapter for payment processing.

This adapter handles:
- QR Code payload generation
- Payment reconciliation via webhooks
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4


@dataclass
class PixPayload:
    """Pix payment payload for QR Code generation."""

    transaction_id: str
    amount_cents: int
    recipient_key: str
    recipient_name: str
    description: str
    expiration_minutes: int = 30

    @property
    def qr_code_data(self) -> str:
        """Generate BR Code (Pix QR Code) payload.

        Note: This is a simplified implementation.
        Production should use proper EMV QR Code library.
        """
        amount = Decimal(self.amount_cents) / Decimal(100)
        return (
            f"00020126580014br.gov.bcb.pix"
            f"01{len(self.recipient_key):02d}{self.recipient_key}"
            f"52040000"
            f"5303986"
            f"54{len(f'{amount:.2f}'):02d}{amount:.2f}"
            f"5802BR"
            f"59{len(self.recipient_name):02d}{self.recipient_name}"
            f"60{len('SAO PAULO'):02d}SAO PAULO"
            f"62{len(self.transaction_id) + 4:02d}05{len(self.transaction_id):02d}{self.transaction_id}"
            f"6304"
        )


@dataclass
class PixWebhookEvent:
    """Pix webhook event from payment gateway."""

    event_id: str
    pix_transaction_id: str
    amount_cents: int
    status: str  # "confirmed", "failed", "refunded"
    payer_cpf: Optional[str]
    payer_name: Optional[str]
    received_at: datetime


class PixGatewayAdapter:
    """Adapter for Pix payment gateway integration.

    Handles payment creation and webhook reconciliation.
    """

    def __init__(
        self,
        recipient_key: str = "placeholder@pix.blanco.com",
        recipient_name: str = "BLANCO FINANCAS",
    ) -> None:
        """Initialize Pix gateway adapter.

        Args:
            recipient_key: Pix key for receiving payments
            recipient_name: Recipient name for QR Code
        """
        self._recipient_key = recipient_key
        self._recipient_name = recipient_name

    def create_payment(
        self,
        internal_transaction_id: UUID,
        amount_cents: int,
        description: str,
    ) -> PixPayload:
        """Create a Pix payment payload for QR Code generation.

        Args:
            internal_transaction_id: Internal transaction UUID
            amount_cents: Payment amount in cents
            description: Payment description

        Returns:
            PixPayload for QR Code generation
        """
        # Generate unique transaction ID for Pix
        pix_transaction_id = f"BF{internal_transaction_id.hex[:20].upper()}"

        return PixPayload(
            transaction_id=pix_transaction_id,
            amount_cents=amount_cents,
            recipient_key=self._recipient_key,
            recipient_name=self._recipient_name,
            description=description,
        )

    def parse_webhook(self, payload: dict) -> PixWebhookEvent:
        """Parse incoming webhook from Pix gateway.

        Args:
            payload: Raw webhook payload

        Returns:
            Parsed PixWebhookEvent
        """
        return PixWebhookEvent(
            event_id=payload.get("event_id", str(uuid4())),
            pix_transaction_id=payload["pix_id"],
            amount_cents=int(payload["amount"] * 100),
            status=payload["status"],
            payer_cpf=payload.get("payer_cpf"),
            payer_name=payload.get("payer_name"),
            received_at=datetime.fromisoformat(payload["timestamp"]),
        )
