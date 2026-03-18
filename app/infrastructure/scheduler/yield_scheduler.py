"""Automatic poupança yield scheduler.

Runs process_all_yields daily at 00:05 BRT (03:05 UTC) directly
within the FastAPI process via APScheduler's AsyncIOScheduler.

Startup behaviour
-----------------
On every server start the scheduler immediately checks whether any
principal_deposit record has last_yield_run_date < today.  If so, it
means a previous run was missed (server was down, BCB was unavailable,
etc.) and process_all_yields is executed right away as a catch-up.
Because process_all_yields is fully idempotent the same date can be
submitted multiple times with no side-effects.
"""

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.application.services.yield_service import YieldService
from app.infrastructure.bcb.exceptions import BCBUnavailableError
from app.infrastructure.db.repositories.principal_deposit_repository import (
    PrincipalDepositRepository,
)
from app.infrastructure.db.session import async_session_factory

log = logging.getLogger("yield_scheduler")

# 00:05 BRT = 03:05 UTC (Brazil abolished DST in 2019, always UTC-3).
_CRON_HOUR_UTC = 3
_CRON_MINUTE_UTC = 5


async def _run_yield_job() -> None:
    """Execute process_all_yields for today and log the outcome."""
    today = datetime.now(timezone.utc).date()
    log.info("Yield job started | calculation_date=%s", today)

    async with async_session_factory() as session:
        service = YieldService(session)
        try:
            result = await service.process_all_yields(calculation_date=today)
        except BCBUnavailableError as exc:
            log.error("Yield job aborted — BCB unavailable: %s", exc.message)
            return
        except Exception:
            log.exception("Yield job failed with unexpected error")
            return

    log.info(
        "Yield job finished | evaluated=%d credited=%d total_R$=%.2f",
        result.deposits_evaluated,
        result.deposits_credited,
        result.total_yield_cents / 100,
    )


async def _startup_catchup() -> None:
    """On startup, run a catch-up job if any deposits are still pending.

    A deposit is considered pending when last_yield_run_date < today,
    meaning no successful run has been recorded for today yet.
    Running process_all_yields is safe even if the daily job already
    ran — the call will evaluate all deposits and credit nothing (delta = 0).
    """
    today = datetime.now(timezone.utc).date()

    async with async_session_factory() as session:
        repo = PrincipalDepositRepository(session)
        pending = await repo.get_pending_yield_processing(before_date=today)

    if not pending:
        log.info("Startup check: all deposits up-to-date, no catch-up needed.")
        return

    log.info(
        "Startup check: %d deposit(s) pending as of %s — running catch-up now.",
        len(pending),
        today,
    )
    await _run_yield_job()


class YieldScheduler:
    """Wrapper around APScheduler that manages the yield cron job lifecycle.

    Usage (in FastAPI lifespan):

        scheduler = YieldScheduler()
        await scheduler.start()   # registers job + runs catch-up
        ...
        await scheduler.stop()    # graceful shutdown
    """

    def __init__(self) -> None:
        self._scheduler = AsyncIOScheduler()

    async def start(self) -> None:
        """Start the scheduler and perform startup catch-up check."""
        self._scheduler.add_job(
            _run_yield_job,
            trigger=CronTrigger(hour=_CRON_HOUR_UTC, minute=_CRON_MINUTE_UTC, timezone="UTC"),
            id="process_yields_daily",
            name="Poupança yield — daily processing",
            replace_existing=True,
            misfire_grace_time=3600,  # tolerate up to 1-hour server delay
        )
        self._scheduler.start()
        log.info(
            "Yield scheduler started — daily job at %02d:%02d UTC (00:%02d BRT).",
            _CRON_HOUR_UTC,
            _CRON_MINUTE_UTC,
            _CRON_MINUTE_UTC,
        )

        # Perform catch-up check without blocking the startup path.
        await _startup_catchup()

    async def stop(self) -> None:
        """Shut down the scheduler gracefully."""
        self._scheduler.shutdown(wait=False)
        log.info("Yield scheduler stopped.")
