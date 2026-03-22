"""Tests for reading streak computation functions."""

from datetime import date, timedelta

from app.routers.books import _compute_longest_streak, _compute_streak

# ---------------------------------------------------------------------------
# _compute_streak
# ---------------------------------------------------------------------------


class TestComputeStreak:
    def test_empty_dates(self):
        assert _compute_streak([], date(2026, 3, 22)) == 0

    def test_read_today_only(self):
        today = date(2026, 3, 22)
        assert _compute_streak([today], today) == 1

    def test_read_today_and_yesterday(self):
        today = date(2026, 3, 22)
        dates = [today, today - timedelta(days=1)]
        assert _compute_streak(dates, today) == 2

    def test_consecutive_days_ending_today(self):
        today = date(2026, 3, 22)
        dates = [today - timedelta(days=i) for i in range(5)]
        assert _compute_streak(dates, today) == 5

    def test_grace_period_not_read_today(self):
        """Duolingo-style: streak survives if you haven't read today yet."""
        today = date(2026, 3, 22)
        yesterday = today - timedelta(days=1)
        dates = [
            yesterday,
            yesterday - timedelta(days=1),
            yesterday - timedelta(days=2),
        ]
        assert _compute_streak(dates, today) == 3

    def test_grace_period_gap_breaks_streak(self):
        """Grace only applies to today. A gap before yesterday breaks the streak."""
        today = date(2026, 3, 22)
        # Read 2 days ago but not yesterday — streak should be 0
        dates = [today - timedelta(days=2)]
        assert _compute_streak(dates, today) == 0

    def test_streak_with_gap_in_middle(self):
        today = date(2026, 3, 22)
        # Today, yesterday, then gap, then 3 days ago
        dates = [today, today - timedelta(days=1), today - timedelta(days=3)]
        assert _compute_streak(dates, today) == 2

    def test_single_day_yesterday_grace(self):
        today = date(2026, 3, 22)
        dates = [today - timedelta(days=1)]
        assert _compute_streak(dates, today) == 1

    def test_old_data_no_recent_reading(self):
        """Reading only 10 days ago — no streak."""
        today = date(2026, 3, 22)
        dates = [today - timedelta(days=10)]
        assert _compute_streak(dates, today) == 0


# ---------------------------------------------------------------------------
# _compute_longest_streak
# ---------------------------------------------------------------------------


class TestComputeLongestStreak:
    def test_empty_dates(self):
        assert _compute_longest_streak([]) == 0

    def test_single_day(self):
        assert _compute_longest_streak([date(2026, 3, 22)]) == 1

    def test_consecutive_days(self):
        dates = [date(2026, 3, 22) - timedelta(days=i) for i in range(7)]
        assert _compute_longest_streak(dates) == 7

    def test_two_streaks_returns_longest(self):
        # Streak of 3 (Mar 22,21,20) then gap, then streak of 5 (Mar 15-11)
        dates = [
            date(2026, 3, 22),
            date(2026, 3, 21),
            date(2026, 3, 20),
            # gap
            date(2026, 3, 15),
            date(2026, 3, 14),
            date(2026, 3, 13),
            date(2026, 3, 12),
            date(2026, 3, 11),
        ]
        assert _compute_longest_streak(dates) == 5

    def test_all_isolated_days(self):
        dates = [
            date(2026, 3, 22),
            date(2026, 3, 20),
            date(2026, 3, 18),
        ]
        assert _compute_longest_streak(dates) == 1

    def test_longest_streak_equals_current(self):
        """When current streak IS the longest."""
        dates = [date(2026, 3, 22) - timedelta(days=i) for i in range(10)]
        assert _compute_longest_streak(dates) == 10
