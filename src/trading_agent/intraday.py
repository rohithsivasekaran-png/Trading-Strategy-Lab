import argparse
import os
import sys
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from dotenv import load_dotenv

from alpaca.data.enums import Adjustment, DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetCalendarRequest

EXCHANGE_TZ = ZoneInfo("America/New_York")
REGULAR_CLOSE = time(16, 0)
FINAL_PERIOD_START = date(2025, 1, 1)
BARS_PER_FULL_DAY = 78


class FinalPeriodError(ValueError):
    pass


def guard_final_period(end: date, allow_final_period: bool) -> None:
    if end >= FINAL_PERIOD_START and not allow_final_period:
        raise FinalPeriodError(
            f"Refusing to download data ending {end}: this falls in the final test "
            f"period (>= {FINAL_PERIOD_START}), which docs/chapter2_preregistration.md "
            "reserves as unseen until all code is frozen. Downloading it now risks "
            "tainting that pre-registration. Pass --allow-final-period to override "
            "once you are ready to run the final test."
        )


def fetch_trading_calendar(start: date, end: date) -> pd.DataFrame:
    load_dotenv()
    client = TradingClient(
        os.environ["ALPACA_API_KEY"], os.environ["ALPACA_SECRET_KEY"], paper=True
    )
    calendar = client.get_calendar(GetCalendarRequest(start=start, end=end))
    return pd.DataFrame(
        {
            "date": [day.date for day in calendar],
            "open_time": [day.open.time() for day in calendar],
            "close_time": [day.close.time() for day in calendar],
        }
    )


def filter_to_regular_session(df: pd.DataFrame, calendar: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["_date"] = df["timestamp"].dt.date
    df = df.merge(calendar, left_on="_date", right_on="date", how="left")

    bar_time = df["timestamp"].dt.time
    in_session = (bar_time >= df["open_time"]) & (bar_time < df["close_time"])
    df = df[in_session].copy()
    df["early_close"] = df["close_time"] < REGULAR_CLOSE

    return df.drop(columns=["_date", "date", "open_time", "close_time"]).reset_index(
        drop=True
    )


def fetch_intraday_bars(symbol: str, start: date, end: date) -> pd.DataFrame:
    load_dotenv()
    client = StockHistoricalDataClient(
        os.environ["ALPACA_API_KEY"], os.environ["ALPACA_SECRET_KEY"]
    )
    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame(5, TimeFrameUnit.Minute),
        start=datetime(start.year, start.month, start.day),
        end=datetime(end.year, end.month, end.day, 23, 59, 59),
        adjustment=Adjustment.ALL,
        feed=DataFeed.SIP,
    )
    bars = client.get_stock_bars(request)
    df = bars.df.loc[symbol].reset_index()
    df["timestamp"] = df["timestamp"].dt.tz_convert(EXCHANGE_TZ)

    calendar = fetch_trading_calendar(start, end)
    return filter_to_regular_session(df, calendar)


def save_intraday_bars(df: pd.DataFrame, symbol: str, start: date, end: date) -> Path:
    data_dir = Path("data") / "intraday"
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / f"{symbol}_5min_{start}_{end}.csv"
    df.to_csv(path, index=False)
    return path


def quality_report(df: pd.DataFrame) -> dict:
    trading_day = df["timestamp"].dt.date
    bars_per_day = trading_day.value_counts().sort_index()

    early_close_days = sorted(df.loc[df["early_close"], "timestamp"].dt.date.unique())
    early_close_counts = {str(d): int(bars_per_day[d]) for d in early_close_days}

    regular_bars_per_day = bars_per_day.drop(index=early_close_days)
    anomalous_short_days = regular_bars_per_day[regular_bars_per_day < BARS_PER_FULL_DAY]

    return {
        "rows": len(df),
        "trading_days": trading_day.nunique(),
        "first_timestamp": df["timestamp"].iloc[0] if len(df) else None,
        "last_timestamp": df["timestamp"].iloc[-1] if len(df) else None,
        "full_days": int((regular_bars_per_day == BARS_PER_FULL_DAY).sum()),
        "early_close_days": early_close_counts,
        "anomalous_short_days": {
            str(d): int(c) for d, c in anomalous_short_days.items()
        },
        "duplicate_timestamps": int(df["timestamp"].duplicated().sum()),
        "zero_volume_bars": int((df["volume"] == 0).sum()),
        "high_below_low_bars": int((df["high"] < df["low"]).sum()),
    }


def print_quality_report(report: dict, symbol: str) -> None:
    print(f"\n=== Data quality report: {symbol} ===")
    print(f"Rows: {report['rows']}")
    print(f"Trading days: {report['trading_days']}")
    print(f"First timestamp: {report['first_timestamp']}")
    print(f"Last timestamp: {report['last_timestamp']}")
    print(f"Days with exactly {BARS_PER_FULL_DAY} bars: {report['full_days']}")
    print(f"Early-close days (official close before 16:00): {len(report['early_close_days'])}")
    for day, count in report["early_close_days"].items():
        print(f"  {day}: {count} bars")
    if report["anomalous_short_days"]:
        print("Other days with fewer than 78 bars (missing bars, not an early close):")
        for day, count in report["anomalous_short_days"].items():
            print(f"  {day}: {count} bars")
    else:
        print("Other days with fewer than 78 bars: none")
    print(f"Duplicate timestamps: {report['duplicate_timestamps']}")
    print(f"Zero-volume bars: {report['zero_volume_bars']}")
    print(f"Bars with high < low: {report['high_below_low_bars']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("symbol")
    parser.add_argument("--start", required=True, type=date.fromisoformat)
    parser.add_argument("--end", required=True, type=date.fromisoformat)
    parser.add_argument("--allow-final-period", action="store_true")
    args = parser.parse_args()

    try:
        guard_final_period(args.end, args.allow_final_period)
    except FinalPeriodError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    symbol = args.symbol
    df = fetch_intraday_bars(symbol, args.start, args.end)
    path = save_intraday_bars(df, symbol, args.start, args.end)
    print(f"Saved {len(df)} rows to {path}")

    report = quality_report(df)
    print_quality_report(report, symbol)
