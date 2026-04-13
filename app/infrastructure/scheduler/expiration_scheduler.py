"""Stale Pix payment expiration scheduler.

Runs expire_all_stale_payments every 5 minutes to batch-expire pending Pix
payments whose 30-minute window has passed without confirmation.

Without this job, stale payments are only expired lazily — when a user
explicitly queries their payment list or detail endpoint.  The scheduler
ensures the database stays consistent even when users never return to check.
"""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.domain.entities.transaction import TransactionType
from app.infrastructure.db.repositories.transaction_repository import TransactionRepository
from app.infrastructure.db.session import async_session_factory

log = logging.getLogger("expiration_scheduler")

_INTERVAL_MINUTES = 5

_PAYMENT_TYPES = [
    TransactionType.SUBSCRIPTION_INSTALLMENT_PAYMENT,
    TransactionType.SUBSCRIPTION_ACTIVATION_PAYMENT,
]


async def _run_expiration_job() -> None:
    """Expire all globally stale pending Pix payments."""
    count = 0
    try:
        async with async_session_factory() as session:
            repo = TransactionRepository(session)
            count = await repo.expire_all_stale_payments(transaction_types=_PAYMENT_TYPES)
            if count:
                await session.commit()
    except Exception:
        log.exception("Expiration job failed with unexpected error")
        return

    if count:
        log.info("Expiration job: %d payment(s) expired.", count)
    else:
        log.debug("Expiration job: no stale payments found.")


class ExpirationScheduler:
    """Wrapper around APScheduler that manages the stale payment expiration job.

    Usage (in FastAPI lifespan):

        scheduler = ExpirationScheduler()
        await scheduler.start()
        ...
        await scheduler.stop()
    """

    def __init__(self) -> None:
        self._scheduler = AsyncIOScheduler()

    async def start(self) -> None:
        """Start the interval scheduler."""
        self._scheduler.add_job(
            _run_expiration_job,
            trigger=IntervalTrigger(minutes=_INTERVAL_MINUTES),
            id="expire_stale_payments",
            name="Pix payments — stale expiration",
            replace_existing=True,
            misfire_grace_time=300,
        )
        self._scheduler.start()
        log.info(
            "Expiration scheduler started — interval=%d minutes.",
            _INTERVAL_MINUTES,
        )

    async def stop(self) -> None:
        """Shut down the scheduler gracefully."""
        self._scheduler.shutdown(wait=False)
        log.info("Expiration scheduler stopped.")
