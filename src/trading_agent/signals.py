import argparse
from pathlib import Path

import pandas as pd


def compute_signals(
    df: pd.DataFrame, short_window: int = 50, long_window: int = 200
) -> pd.DataFrame:
    df = df.copy()
    df["sma_short"] = df["close"].rolling(window=short_window).mean()
    df["sma_long"] = df["close"].rolling(window=long_window).mean()
    df["signal"] = (df["sma_short"] > df["sma_long"]).astype(int)

    signal_diff = df["signal"].diff()
    df["golden_cross"] = signal_diff == 1
    df["death_cross"] = signal_diff == -1

    return df[
        [
            "timestamp",
            "close",
            "sma_short",
            "sma_long",
            "signal",
            "golden_cross",
            "death_cross",
        ]
    ]


def _window_suffix(short_window: int, long_window: int) -> str:
    if (short_window, long_window) == (50, 200):
        return ""
    return f"_{short_window}_{long_window}"


def save_signals(
    df: pd.DataFrame, symbol: str, short_window: int = 50, long_window: int = 200
) -> Path:
    data_dir = Path("data")
    data_dir.mkdir(exist_ok=True)
    suffix = _window_suffix(short_window, long_window)
    path = data_dir / f"{symbol}{suffix}_signals.csv"
    df.to_csv(path, index=False)
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("symbol")
    parser.add_argument("--short-window", type=int, default=50)
    parser.add_argument("--long-window", type=int, default=200)
    args = parser.parse_args()

    symbol = args.symbol
    bars = pd.read_csv(f"data/{symbol}.csv", parse_dates=["timestamp"])
    result = compute_signals(
        bars, short_window=args.short_window, long_window=args.long_window
    )
    save_signals(result, symbol, args.short_window, args.long_window)

    first_valid_date = result.loc[result["sma_long"].notna(), "timestamp"].iloc[0]

    crossovers = pd.concat(
        [
            result.loc[result["golden_cross"], "timestamp"]
            .to_frame(name="timestamp")
            .assign(type="golden"),
            result.loc[result["death_cross"], "timestamp"]
            .to_frame(name="timestamp")
            .assign(type="death"),
        ]
    ).sort_values("timestamp")

    pct_invested = result["signal"].mean() * 100

    print(f"First date with valid signal: {first_valid_date.date()}")
    print(f"Golden crosses: {result['golden_cross'].sum()}")
    print(f"Death crosses: {result['death_cross'].sum()}")
    print("Crossover dates:")
    for _, row in crossovers.iterrows():
        print(f"  {row['timestamp'].date()}: {row['type']}")
    print(f"Percent of days invested: {pct_invested:.2f}%")
