from datetime import date, datetime, time, timedelta

import pandas as pd
import pytest

from trading_agent.ict_sweep import (
    Bar,
    detect_and_simulate_day,
    net_r,
    scan_symbol,
    simulate_exit,
)


def test_reclaim_enters_at_next_bars_open():
    pdl, pdh = 99.0, 101.0
    bars = [
        Bar(time(9, 30), open=99.5, high=99.6, low=99.4, close=99.5),  # benign
        Bar(time(9, 35), open=99.0, high=99.1, low=98.90, close=99.0),  # break
        Bar(time(9, 40), open=99.0, high=99.05, low=98.85, close=99.02),  # reclaim
        Bar(time(9, 45), open=99.10, high=99.20, low=99.05, close=99.15),  # entry bar
        Bar(time(9, 50), open=99.15, high=100.0, low=99.3, close=99.9),  # target hit
    ]

    trades = detect_and_simulate_day(bars, "TEST", date(2023, 1, 5), pdl, pdh)

    assert len(trades) == 1
    trade = trades[0]
    assert trade.direction == "bull"
    assert trade.entry_time == time(9, 45)
    assert trade.entry_price == pytest.approx(99.10)


def test_no_reclaim_within_six_bars_produces_no_trade():
    pdl, pdh = 99.0, 200.0
    bars = [
        Bar(time(9, 30), open=99.0, high=99.05, low=98.90, close=98.95),  # break
        Bar(time(9, 35), open=98.95, high=99.0, low=98.90, close=98.96),
        Bar(time(9, 40), open=98.96, high=99.0, low=98.90, close=98.97),
        Bar(time(9, 45), open=98.97, high=99.0, low=98.90, close=98.98),
        Bar(time(9, 50), open=98.98, high=99.0, low=98.90, close=98.99),
        Bar(time(9, 55), open=98.99, high=99.0, low=98.90, close=98.995),  # 6th bar, still no reclaim
    ]

    trades = detect_and_simulate_day(bars, "TEST", date(2023, 1, 6), pdl, pdh)

    assert trades == []


def test_same_bar_stop_and_target_stop_wins():
    bar = Bar(time(9, 35), open=100.0, high=103.0, low=98.0, close=100.5)

    exit_idx, exit_price, reason = simulate_exit(
        [bar], 0, "bull", entry=100.0, stop=99.0, target=102.0, window_close_time=time(15, 55)
    )

    assert reason == "STOP"
    assert exit_price == pytest.approx(99.0)


def test_costs_subtracted_correctly():
    result = net_r(entry=100.0, stop=99.0, exit_price=102.0, direction="bull")

    # raw R = (102 - 100) / 1 = 2.0
    # cost in R = (0.0002*100 + 0.0002*102) / 1 = 0.0404
    assert result == pytest.approx(1.9596)


def test_time_exit_at_window_close():
    cur = datetime(2000, 1, 1, 9, 35)
    end = datetime(2000, 1, 1, 10, 55)
    bars = []
    while cur <= end:
        close = 101.25 if cur == end else 100.5
        bars.append(Bar(cur.time(), open=100.0, high=100.8, low=99.2, close=close))
        cur += timedelta(minutes=5)

    exit_idx, exit_price, reason = simulate_exit(
        bars, 0, "bull", entry=100.0, stop=90.0, target=110.0, window_close_time=time(10, 55)
    )

    assert reason == "TIME"
    assert exit_price == pytest.approx(101.25)
    assert bars[exit_idx].time == time(10, 55)


def test_no_trade_on_early_close_day():
    tz = "America/New_York"
    prev_rows = pd.DataFrame(
        {
            "timestamp": [pd.Timestamp("2023-01-03 09:30", tz=tz)],
            "open": [99.5],
            "high": [101.0],
            "low": [99.0],
            "close": [99.5],
            "early_close": [False],
        }
    )
    day_rows = pd.DataFrame(
        {
            "timestamp": [
                pd.Timestamp(f"2023-01-04 {t}", tz=tz)
                for t in ["09:30", "09:35", "09:40", "09:45", "09:50"]
            ],
            "open": [99.5, 99.0, 99.0, 99.10, 99.15],
            "high": [99.6, 99.1, 99.05, 99.20, 100.0],
            "low": [99.4, 98.90, 98.85, 99.05, 99.3],
            "close": [99.5, 99.0, 99.02, 99.15, 99.9],
            "early_close": [True, True, True, True, True],
        }
    )
    bars = pd.concat([prev_rows, day_rows], ignore_index=True)

    result = scan_symbol(bars, "TEST")

    assert len(result) == 0


def test_entry_gap_through_stop_skips_trade_but_preserves_allowance():
    pdl, pdh = 100.0, 1000.0
    bars = [
        Bar(time(9, 30), open=100.5, high=100.6, low=100.4, close=100.5),  # benign
        Bar(time(9, 35), open=100.0, high=100.05, low=99.80, close=99.90),  # break 1
        Bar(time(9, 40), open=99.97, high=100.05, low=99.96, close=100.05),  # reclaim 1 (low raised to clear break threshold so bar 3 stays a fresh crossing)
        Bar(time(9, 45), open=99.60, high=99.90, low=99.50, close=99.80),  # gapped entry + break 2
        Bar(time(9, 50), open=99.80, high=99.95, low=99.40, close=99.85),  # still below PDL
        Bar(time(9, 55), open=99.85, high=100.10, low=99.60, close=100.05),  # reclaim 2
        Bar(time(10, 0), open=99.90, high=100.00, low=99.85, close=99.95),  # valid entry
        *[
            Bar(time(10, 5 + 5 * k), open=99.90, high=100.05, low=99.85, close=99.95)
            for k in range(10)
        ],
        Bar(time(10, 55), open=99.95, high=100.05, low=99.90, close=100.00),  # time exit
    ]

    trades = detect_and_simulate_day(bars, "TEST", date(2023, 1, 7), pdl, pdh)

    assert len(trades) == 1
    trade = trades[0]
    assert trade.entry_time == time(10, 0)
    assert trade.entry_price == pytest.approx(99.90)
    assert trade.exit_reason == "TIME"
    assert trade.exit_price == pytest.approx(100.00)


def test_price_already_beyond_level_at_open_produces_no_trade():
    pdl, pdh = 100.0, 1000.0
    bars = [
        Bar(time(9, 30), open=99.80, high=99.85, low=99.70, close=99.75),  # already beyond PDL at the open; is_break true but day-open (99.80) is itself beyond the 99.95 threshold, so no fresh crossing
        Bar(time(9, 35), open=99.75, high=99.85, low=99.65, close=99.78),  # still beyond, no reclaim
        Bar(time(9, 40), open=99.78, high=99.88, low=99.70, close=99.80),  # still beyond, no reclaim
    ]

    trades = detect_and_simulate_day(bars, "TEST", date(2023, 1, 8), pdl, pdh)

    assert trades == []


def test_blocked_level_is_not_restarted_by_a_bar_that_stays_beyond_it():
    pdl, pdh = 99.0, 200.0
    bars = [
        Bar(time(9, 30), open=99.0, high=99.05, low=98.90, close=98.95),  # break (day-open=99.0 passes prior-ref gate)
        Bar(time(9, 35), open=98.95, high=99.0, low=98.90, close=98.96),  # no reclaim
        Bar(time(9, 40), open=98.96, high=99.0, low=98.90, close=98.97),  # no reclaim
        Bar(time(9, 45), open=98.97, high=99.0, low=98.90, close=98.98),  # no reclaim
        Bar(time(9, 50), open=98.98, high=99.0, low=98.90, close=98.99),  # no reclaim
        Bar(time(9, 55), open=98.99, high=99.0, low=98.90, close=98.995),  # 6th bar: timeout fires, blocked[bull]=True
        Bar(time(10, 0), open=98.995, high=99.10, low=98.96, close=98.995),  # low recovers above threshold (98.96>=98.9505) but close stays below pdl -> is_reclaim false -> blocked stays True
        Bar(time(10, 5), open=98.995, high=99.0, low=98.90, close=98.97),  # is_break true AND prior bar's low clears threshold -- would wrongly restart if blocked weren't enforced
    ]

    trades = detect_and_simulate_day(bars, "TEST", date(2023, 1, 9), pdl, pdh)

    assert trades == []


def test_fresh_break_after_blocked_level_recovers_produces_a_trade():
    pdl, pdh = 100.0, 1000.0
    bars = [
        Bar(time(9, 30), open=100.0, high=100.05, low=99.80, close=99.85),  # break 1 (day-open=100.0 passes gate)
        Bar(time(9, 35), open=99.85, high=99.90, low=99.75, close=99.80),  # no reclaim
        Bar(time(9, 40), open=99.80, high=99.85, low=99.70, close=99.78),  # no reclaim
        Bar(time(9, 45), open=99.78, high=99.85, low=99.72, close=99.79),  # no reclaim
        Bar(time(9, 50), open=99.79, high=99.85, low=99.74, close=99.80),  # no reclaim
        Bar(time(9, 55), open=99.80, high=99.85, low=99.75, close=99.82),  # 6th bar: timeout, blocked[bull]=True
        Bar(time(10, 0), open=100.00, high=100.10, low=99.96, close=100.05),  # recovery: close clears blocked; low (99.96) gives bar 7 a valid prior-ref
        Bar(time(10, 5), open=100.05, high=100.08, low=99.90, close=99.97),  # break 2 (fresh: prior bar's low 99.96 inside threshold, blocked now clear)
        Bar(time(10, 10), open=99.97, high=100.10, low=99.92, close=100.06),  # reclaim 2
        Bar(time(10, 15), open=99.95, high=100.00, low=99.90, close=99.98),  # entry bar, entry_price=99.95
        Bar(time(10, 20), open=99.98, high=100.15, low=99.95, close=100.10),  # target hit (2R and 1R sensitivity)
        *[
            Bar(time(10, 25 + 5 * k), open=100.05, high=100.10, low=100.00, close=100.05)
            for k in range(6)
        ],
        Bar(time(10, 55), open=100.05, high=100.10, low=100.00, close=100.05),  # window close, for the 3R sensitivity check (never reaches 3R target)
    ]

    trades = detect_and_simulate_day(bars, "TEST", date(2023, 1, 10), pdl, pdh)

    assert len(trades) == 1
    trade = trades[0]
    assert trade.direction == "bull"
    assert trade.break_time == time(10, 5)
    assert trade.entry_time == time(10, 15)
    assert trade.entry_price == pytest.approx(99.95)
    assert trade.sweep_extreme == pytest.approx(99.90)
    assert trade.stop_price == pytest.approx(99.88002)
    assert trade.exit_reason == "TARGET"
    assert trade.exit_price == pytest.approx(100.08996, rel=1e-4)
