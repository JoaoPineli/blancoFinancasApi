"""Domain-level constants shared across the application."""
from decimal import Decimal, ROUND_HALF_UP

# Single source of truth for Pix transaction fee.
# Applied on top of every Pix payment: total = base + fee
PIX_TRANSACTION_FEE_PERCENT = Decimal("0.0099")  # 0.99%


def calculate_pix_fee(base_cents: int) -> int:
    """Compute the Pix transaction fee for a given base amount.

    Fee = base * 0.99%, rounded HALF_UP to the nearest cent.

    Args:
        base_cents: Base payment amount in cents (positive integer).

    Returns:
        Fee amount in cents (>= 0).
    """
    if base_cents <= 0:
        return 0
    fee = Decimal(base_cents) * PIX_TRANSACTION_FEE_PERCENT
    return int(fee.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
