import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from dotenv import load_dotenv

from alpaca.data.enums import Adjustment, DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.historical.crypto import CryptoHistoricalDataClient
from alpaca.data.requests import CryptoBarsRequest, StockBarsRequest
from alpaca.data.timeframe import TimeFrame

EXCHANGE_TZ = ZoneInfo("America/New_York")


def _latest_completed_session_end() -> datetime:
    today_eastern_midnight = datetime.now(EXCHANGE_TZ).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return today_eastern_midnight.astimezone(timezone.utc) - timedelta(seconds=1)


def _latest_completed_crypto_day_end() -> datetime:
    today_utc_midnight = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return today_utc_midnight - timedelta(seconds=1)


def download_daily_bars(symbol: str) -> pd.DataFrame:
    load_dotenv()
    is_crypto = "/" in symbol

    if is_crypto:
        client = CryptoHistoricalDataClient(
            os.environ["ALPACA_API_KEY"], os.environ["ALPACA_SECRET_KEY"]
        )
        request = CryptoBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Day,
            start=datetime(2016, 1, 1),
            end=_latest_completed_crypto_day_end(),
        )
        bars = client.get_crypto_bars(request)
    else:
        client = StockHistoricalDataClient(
            os.environ["ALPACA_API_KEY"], os.environ["ALPACA_SECRET_KEY"]
        )
        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Day,
            start=datetime(2016, 1, 1),
            end=_latest_completed_session_end(),
            adjustment=Adjustment.ALL,
            feed=DataFeed.SIP,
        )
        bars = client.get_stock_bars(request)

    return bars.df.loc[symbol].reset_index()


def save_bars(df: pd.DataFrame, symbol: str) -> Path:
    data_dir = Path("data")
    data_dir.mkdir(exist_ok=True)
    path = data_dir / f"{symbol.replace('/', '-')}.csv"
    df.to_csv(path, index=False)
    return path


if __name__ == "__main__":
    symbol = sys.argv[1]
    df = download_daily_bars(symbol)
    save_bars(df, symbol)
    print(f"Rows: {len(df)}")
    print(f"First date: {df['timestamp'].iloc[0]}")
    print(f"Last date: {df['timestamp'].iloc[-1]}")
