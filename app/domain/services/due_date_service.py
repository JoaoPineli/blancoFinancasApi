"""Due date service - Pure domain logic for deposit due-date computation.

No I/O, no framework imports. Deterministic and fully testable.
"""

from __future__ import annotations

from datetime import date


class DueDateService:
    """Service for computing and advancing deposit due dates.

    All methods are class methods / static — the service is stateless.
    Days are limited to <= 25, so every month has a valid occurrence.
    """

    @staticmethod
    def compute_next_due_date(day_of_month: int, today: date) -> date:
        """Compute the next occurrence of *day_of_month* on or after *today*.

        If *today* is exactly on *day_of_month*, the due date is today
        (the user still has the whole day to pay).

        Args:
            day_of_month: Target day (1-25).
            today: Reference calendar date (user-local).

        Returns:
            The next due date as a ``date``.
        """
        if today.day <= day_of_month:
            # Still this month (including today)
            return today.replace(day=day_of_month)
        else:
            # Roll to next month
            return DueDateService._next_month(today, day_of_month)

    @staticmethod
    def advance_due_date(day_of_month: int, current_due: date) -> date:
        """Advance *current_due* to the next month's occurrence.

        Used after a payment is recorded to move the due date forward.

        Args:
            day_of_month: Target day (1-25).
            current_due: The current due date.

        Returns:
            The next month's due date.
        """
        return DueDateService._next_month(current_due, day_of_month)

    @staticmethod
    def _next_month(ref: date, day: int) -> date:
        """Return ``date(year, month+1, day)`` handling year rollover.

        Since day <= 25 the date is always valid.
        """
        if ref.month == 12:
            return date(ref.year + 1, 1, day)
        return date(ref.year, ref.month + 1, day)
