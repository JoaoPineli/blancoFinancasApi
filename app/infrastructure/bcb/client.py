"""BCB API client for fetching poupança yield data.

CRITICAL: This is the ONLY accepted source for poupança yield data.
Uses Banco Central do Brasil SGS API.

Approved series:
- SGS 25: Depósitos de poupança (até 03/05/2012)
- SGS 195: Depósitos de poupança (a partir de 04/05/2012)
"""

from datetime import date
from decimal import Decimal
from typing import List

import httpx

from app.domain.entities.yield_data import SGSSeries, YieldData
from app.infrastructure.bcb.exceptions import (
    BCBInvalidDateRangeError,
    BCBInvalidSeriesError,
    BCBUnavailableError,
)
from app.infrastructure.bcb.schemas import SGSResponse
from app.infrastructure.config import settings


class BcbClient:
    """HTTP client for BCB SGS API.

    All access to Banco Central data MUST go through this adapter.
    Domain and Application layers must never call httpx directly.
    """

    # Approved SGS series for poupança
    VALID_SERIES = {SGSSeries.PRE_2012.value, SGSSeries.POST_2012.value}

    def __init__(self, timeout: float = 30.0) -> None:
        """Initialize BCB client.

        Args:
            timeout: Request timeout in seconds
        """
        self._base_url = settings.bcb_api_base_url
        self._timeout = timeout

    async def fetch_yield_data(
        self,
        series_id: SGSSeries,
        start_date: date,
        end_date: date,
    ) -> List[YieldData]:
        """Fetch poupança yield data from BCB SGS API.

        Args:
            series_id: SGS series to fetch (25 or 195)
            start_date: Start date of range
            end_date: End date of range

        Returns:
            List of YieldData entities

        Raises:
            BCBInvalidSeriesError: If series is not valid
            BCBInvalidDateRangeError: If date range is invalid
            BCBUnavailableError: If API is unavailable
        """
        # Validate series
        if series_id.value not in self.VALID_SERIES:
            raise BCBInvalidSeriesError(series_id.value)

        # Validate date range
        if end_date < start_date:
            raise BCBInvalidDateRangeError("End date must be after start date")

        # Format dates for BCB API (DD/MM/YYYY)
        start_str = start_date.strftime("%d/%m/%Y")
        end_str = end_date.strftime("%d/%m/%Y")

        # Build URL
        url = (
            f"{self._base_url}.{series_id.value}/dados"
            f"?formato=json&dataInicial={start_str}&dataFinal={end_str}"
        )

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(url)
                response.raise_for_status()

                data = response.json()
                if not data:
                    return []

                sgs_response = SGSResponse.from_json(data)

                # Convert to domain entities
                yield_data = []
                for point in sgs_response.data_points:
                    yield_data.append(
                        YieldData.create(
                            series_id=series_id,
                            reference_date=point.reference_date,
                            rate=point.rate / Decimal(100),  # Convert percentage to decimal
                        )
                    )

                return yield_data

        except httpx.TimeoutException:
            raise BCBUnavailableError("BCB API request timed out")
        except httpx.HTTPStatusError as e:
            # 404 means no data published for the requested date range (normal for
            # future dates or intervals without a rate announcement).  Treat as empty.
            if e.response.status_code == 404:
                return []
            raise BCBUnavailableError(f"BCB API returned error: {e.response.status_code}")
        except httpx.RequestError as e:
            raise BCBUnavailableError(f"BCB API request failed: {str(e)}")
