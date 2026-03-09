"""Tests for DueDateService - pure domain logic."""

from datetime import date

import pytest

from app.domain.services.due_date_service import DueDateService


class TestComputeNextDueDate:
    """Tests for compute_next_due_date."""

    def test_same_day_returns_today(self):
        """If today IS the deposit day, due date is today."""
        today = date(2026, 3, 10)
        result = DueDateService.compute_next_due_date(10, today)
        assert result == date(2026, 3, 10)

    def test_day_still_ahead_this_month(self):
        """If deposit day hasn't passed yet, return this month."""
        today = date(2026, 3, 3)
        result = DueDateService.compute_next_due_date(15, today)
        assert result == date(2026, 3, 15)

    def test_day_already_passed_rolls_to_next_month(self):
        """If deposit day already passed, roll to next month."""
        today = date(2026, 3, 16)
        result = DueDateService.compute_next_due_date(15, today)
        assert result == date(2026, 4, 15)

    def test_december_rolls_to_january(self):
        """Year rollover from December to January."""
        today = date(2026, 12, 26)
        result = DueDateService.compute_next_due_date(25, today)
        assert result == date(2027, 1, 25)

    def test_first_of_month(self):
        """Day 1, on the 1st of the month -> returns today."""
        today = date(2026, 6, 1)
        result = DueDateService.compute_next_due_date(1, today)
        assert result == date(2026, 6, 1)

    def test_first_day_past_rolls_to_next(self):
        """Day 1, on the 2nd -> rolls to next month."""
        today = date(2026, 6, 2)
        result = DueDateService.compute_next_due_date(1, today)
        assert result == date(2026, 7, 1)

    def test_day_25_february(self):
        """Day 25 in February (valid because <= 25)."""
        today = date(2026, 2, 20)
        result = DueDateService.compute_next_due_date(25, today)
        assert result == date(2026, 2, 25)

    def test_day_25_after_february(self):
        """Day 25 when today is Feb 26 -> rolls to March."""
        today = date(2026, 2, 26)
        result = DueDateService.compute_next_due_date(25, today)
        assert result == date(2026, 3, 25)


class TestAdvanceDueDate:
    """Tests for advance_due_date (always goes to next month)."""

    def test_advance_normal_month(self):
        """Standard month advance."""
        current = date(2026, 3, 10)
        result = DueDateService.advance_due_date(10, current)
        assert result == date(2026, 4, 10)

    def test_advance_december_to_january(self):
        """Year rollover."""
        current = date(2026, 12, 5)
        result = DueDateService.advance_due_date(5, current)
        assert result == date(2027, 1, 5)

    def test_advance_january_to_february(self):
        """Advance into February with day 25 (always valid)."""
        current = date(2026, 1, 25)
        result = DueDateService.advance_due_date(25, current)
        assert result == date(2026, 2, 25)

    def test_advance_multiple_months_sequentially(self):
        """Simulate advancing month by month."""
        current = date(2026, 10, 1)
        for expected_month in [11, 12]:
            current = DueDateService.advance_due_date(1, current)
            assert current == date(2026, expected_month, 1)
        current = DueDateService.advance_due_date(1, current)
        assert current == date(2027, 1, 1)
