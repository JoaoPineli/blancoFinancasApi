"""Pix gateway adapter — Mercado Pago Orders API integration.

Replaces the local BR Code generator with real Mercado Pago Checkout API Orders (Pix).
All HTTP calls are async via httpx.AsyncClient.
All monetary values are handled via Decimal (no float).
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional
from uuid import UUID, uuid4

import httpx


@dataclass
class PixPayload:
    """Pix payment payload returned by Mercado Pago Orders API."""

    transaction_id: str         # MP order_id → stored as pix_transaction_id
    qr_code_data: str           # MP qr_code (Pix copia-e-cola)
    expiration_minutes: int
    qr_code_base64: Optional[str] = None
    ticket_url: Optional[str] = None
    e2e_id: Optional[str] = None


class PixGatewayAdapter:
    """Adapter for Mercado Pago Orders API (Pix payments).

    Provides create_payment and get_order as async methods.
    Tokens are read from settings and never logged.
    """

    def __init__(self) -> None:
        from app.infrastructure.config import get_settings
        self._settings = get_settings()

    async def create_payment(
        self,
        internal_transaction_id: UUID,
        amount_cents: int,
        description: str,
        payer_email: str = "",
    ) -> PixPayload:
        """Create a Pix payment order via Mercado Pago Orders API.

        Args:
            internal_transaction_id: Internal transaction UUID; used as external_reference (hex)
            amount_cents: Amount in cents (integer — no float arithmetic)
            description: Payment description
            payer_email: Payer email. In sandbox, must be a test user email registered in MP.
                         Falls back to MERCADOPAGO_TEST_PAYER_EMAIL from settings if empty.

        Returns:
            PixPayload with real QR code data and MP order_id as transaction_id
        """
        access_token = self._settings.mercadopago_access_token.get_secret_value()
        base_url = self._settings.mercadopago_api_base_url

        # In sandbox, mercadopago_test_payer_email overrides any real user email.
        # In production this setting is empty, so the real email is used.
        is_development = self._settings.environment == "development"
        test_email = "test@testuser.com"
        if is_development:
            payer_email = test_email
        elif not payer_email:
            payer_email = ""
        idempotency_key = str(uuid4())
        external_reference = internal_transaction_id.hex

        # Convert cents → "500.00" string via Decimal — never float
        amount_str = str(
            (Decimal(amount_cents) / Decimal(100)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        )

        payer: dict = {"email": payer_email}
        if is_development:
            # "APRO" as first_name triggers automatic payment approval in MP sandbox.
            payer["first_name"] = "APRO"

        body: dict = {
            "type": "online",
            "external_reference": external_reference,
            "total_amount": amount_str,
            "payer": payer,
            "transactions": {
                "payments": [
                    {
                        "amount": amount_str,
                        "payment_method": {
                            "id": "pix",
                            "type": "bank_transfer",
                        },
                    }
                ]
            },
            "expiration_time": "PT30M",  # ISO 8601 duration for 30 minutes
        }
        async with httpx.AsyncClient() as http:
            response = await http.post(
                f"{base_url}/v1/orders",
                json=body,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "X-Idempotency-Key": idempotency_key,
                    "Content-Type": "application/json",
                },
                timeout=30.0,
            )
            if response.status_code >= 400:
                import logging
                logging.getLogger(__name__).error(
                    "MP create_order error %s — body sent: %s — response: %s",
                    response.status_code,
                    body,
                    response.text,
                )
            response.raise_for_status()
            data = response.json()

        return self._parse_order_response(data)

    async def get_order(self, order_id: str) -> dict:
        """Fetch a full order from Mercado Pago for reconciliation.

        Args:
            order_id: Mercado Pago order ID

        Returns:
            Raw order response dict (contains status, total_amount, transactions, etc.)
        """
        access_token = self._settings.mercadopago_access_token.get_secret_value()
        base_url = self._settings.mercadopago_api_base_url

        async with httpx.AsyncClient() as http:
            response = await http.get(
                f"{base_url}/v1/orders/{order_id}",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=30.0,
            )
            response.raise_for_status()
            return response.json()

    def _parse_order_response(self, data: dict) -> PixPayload:
        """Extract PixPayload from a Mercado Pago order response dict."""
        order_id = str(data["id"])

        payments = data.get("transactions", {}).get("payments", [])
        payment = payments[0] if payments else {}
        payment_method = payment.get("payment_method", {})

        qr_code = payment_method.get("qr_code", "")
        qr_code_base64 = payment_method.get("qr_code_base64")
        ticket_url = payment_method.get("ticket_url")
        e2e_id = payment_method.get("e2e_id")

        return PixPayload(
            transaction_id=order_id,
            qr_code_data=qr_code,
            expiration_minutes=30,
            qr_code_base64=qr_code_base64,
            ticket_url=ticket_url,
            e2e_id=e2e_id,
        )
