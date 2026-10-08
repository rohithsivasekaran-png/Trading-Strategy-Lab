import sys
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


def save_signals(df: pd.DataFrame, symbol: str) -> Path:
    data_dir = Path("data")
    data_dir.mkdir(exist_ok=True)
    path = data_dir / f"{symbol}_signals.csv"
    df.to_csv(path, index=False)
    return path


if __name__ == "__main__":
    symbol = sys.argv[1]
    bars = pd.read_csv(f"data/{symbol}.csv", parse_dates=["timestamp"])
    result = compute_signals(bars)
    save_signals(result, symbol)

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
