"""Tests for BcbClient — focusing on HTTP error handling."""

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.domain.entities.yield_data import SGSSeries
from app.infrastructure.bcb.client import BcbClient
from app.infrastructure.bcb.exceptions import BCBUnavailableError


def _make_http_status_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://api.bcb.gov.br/test")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError("error", request=request, response=response)


@pytest.mark.asyncio
async def test_404_returns_empty_list() -> None:
    """BCB 404 means no data published for the range — must return [], not raise."""
    client = BcbClient()
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        mock_client.get.side_effect = _make_http_status_error(404)

        result = await client.fetch_yield_data(
            series_id=SGSSeries.POST_2012,
            start_date=date(2026, 3, 1),
            end_date=date(2026, 3, 18),
        )

    assert result == []


@pytest.mark.asyncio
async def test_500_raises_bcb_unavailable() -> None:
    """Server errors must raise BCBUnavailableError."""
    client = BcbClient()
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        mock_client.get.side_effect = _make_http_status_error(500)

        with pytest.raises(BCBUnavailableError, match="500"):
            await client.fetch_yield_data(
                series_id=SGSSeries.POST_2012,
                start_date=date(2026, 3, 1),
                end_date=date(2026, 3, 18),
            )


@pytest.mark.asyncio
async def test_timeout_raises_bcb_unavailable() -> None:
    """Timeout must raise BCBUnavailableError."""
    client = BcbClient()
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        mock_client.get.side_effect = httpx.TimeoutException("timeout")

        with pytest.raises(BCBUnavailableError, match="timed out"):
            await client.fetch_yield_data(
                series_id=SGSSeries.POST_2012,
                start_date=date(2026, 3, 1),
                end_date=date(2026, 3, 18),
            )
