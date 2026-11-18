from datetime import date, time

import pandas as pd
import pytest

from trading_agent.intraday import (
    FinalPeriodError,
    filter_to_regular_session,
    guard_final_period,
)


def test_guard_refuses_unseen_final_period():
    with pytest.raises(FinalPeriodError):
        guard_final_period(date(2025, 1, 1), allow_final_period=False)


def test_guard_allows_final_period_with_flag():
    guard_final_period(date(2025, 1, 1), allow_final_period=True)


def test_guard_allows_development_period():
    guard_final_period(date(2024, 12, 31), allow_final_period=False)


def test_filter_to_regular_session_excludes_bars_at_or_after_close():
    tz = "America/New_York"
    bar_times = ["09:30", "12:50", "12:55", "13:00", "13:05", "15:55"]
    df = pd.DataFrame(
        {
            "timestamp": [
                pd.Timestamp(f"2022-11-25 {t}", tz=tz) for t in bar_times
            ],
            "volume": [1] * len(bar_times),
            "high": [2] * len(bar_times),
            "low": [1] * len(bar_times),
        }
    )
    calendar = pd.DataFrame(
        {
            "date": [date(2022, 11, 25)],
            "open_time": [time(9, 30)],
            "close_time": [time(13, 0)],
        }
    )

    result = filter_to_regular_session(df, calendar)

    assert (result["timestamp"].dt.time < time(13, 0)).all()
    assert pd.Timestamp("2022-11-25 12:55", tz=tz) in set(result["timestamp"])
    assert result["early_close"].all()
    assert len(result) == 3
