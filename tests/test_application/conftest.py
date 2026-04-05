"""Shared fixtures for application service tests.

Auto-mocks PixGatewayAdapter.create_payment so tests don't require real
Mercado Pago credentials.  The fake payload uses a deterministic ID so
tests can assert on pix_transaction_id values.
"""

import pytest
from unittest.mock import AsyncMock, patch

from app.infrastructure.payment.pix_gateway import PixPayload


_FAKE_PAYLOAD = PixPayload(
    transaction_id="MOCK-MP-ORDER-ID",
    qr_code_data="00020101021226mock-qr-code",
    expiration_minutes=30,
)


@pytest.fixture(autouse=True)
def mock_mp_gateway_create():
    """Patch PixGatewayAdapter.create_payment to return a fake PixPayload.

    Avoids real HTTP calls to Mercado Pago in unit/integration service tests.
    Tests that need a specific order_id can override with their own patch.
    """
    with patch(
        "app.infrastructure.payment.pix_gateway.PixGatewayAdapter.create_payment",
        new_callable=AsyncMock,
        return_value=_FAKE_PAYLOAD,
    ):
        yield _FAKE_PAYLOAD
