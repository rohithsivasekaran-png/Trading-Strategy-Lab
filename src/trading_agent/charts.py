import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd


def _cash_runs(dates: pd.Series, in_cash: pd.Series) -> list[tuple]:
    runs = []
    start = None
    for i, flag in enumerate(in_cash):
        if flag and start is None:
            start = dates.iloc[i]
        if not flag and start is not None:
            runs.append((start, dates.iloc[i - 1]))
            start = None
    if start is not None:
        runs.append((start, dates.iloc[len(in_cash) - 1]))
    return runs


def build_chart(
    bars: pd.DataFrame,
    signals: pd.DataFrame,
    backtest: pd.DataFrame,
    symbol: str,
) -> plt.Figure:
    df = pd.merge(
        bars[["timestamp", "open", "close"]],
        signals[["timestamp", "sma_short", "sma_long", "signal"]],
        on="timestamp",
    )
    df = pd.merge(df, backtest[["timestamp", "strategy_equity", "buyhold_equity"]], on="timestamp")
    df = df.sort_values("timestamp").reset_index(drop=True)

    position = df["signal"].shift(1).fillna(0).astype(int)
    prev_position = position.shift(1).fillna(0).astype(int)
    df["position"] = position
    df["entry"] = (position == 1) & (prev_position == 0)
    df["exit"] = (position == 0) & (prev_position == 1)

    entry_indices = df.index[df["entry"]]
    if len(entry_indices) == 0:
        raise ValueError("Signal never turns on; nothing to chart from an entry day")
    first_entry_idx = entry_indices[0]

    window = df.loc[first_entry_idx:].reset_index(drop=True)
    dates = window["timestamp"]

    strategy_equity = window["strategy_equity"] / window["strategy_equity"].iloc[0] * 10_000
    buyhold_equity = window["buyhold_equity"] / window["buyhold_equity"].iloc[0] * 10_000

    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, sharex=True, figsize=(12, 10))
    fig.suptitle(f"{symbol} Moving-Average Crossover Backtest", fontsize=14, fontweight="bold")

    # Panel 1: equity curves
    ax1.plot(dates, strategy_equity, color="tab:blue", linestyle="-", label="Strategy")
    ax1.plot(dates, buyhold_equity, color="tab:orange", linestyle="--", label="Buy & Hold")
    for start, end in _cash_runs(dates, window["position"] == 0):
        ax1.axvspan(start, end, color="lightgrey", alpha=0.4, zorder=0)
    ax1.set_ylabel("Portfolio value ($)")
    ax1.set_title("Equity Curve (grey = strategy in cash)")
    ax1.legend(loc="upper left")

    # Panel 2: drawdown
    strategy_dd = strategy_equity / strategy_equity.cummax() - 1
    buyhold_dd = buyhold_equity / buyhold_equity.cummax() - 1
    ax2.plot(dates, strategy_dd * 100, color="tab:blue", linestyle="-", label="Strategy")
    ax2.plot(dates, buyhold_dd * 100, color="tab:orange", linestyle="--", label="Buy & Hold")

    # Drawdown is never positive, so anchoring labels in the y > 0 band
    # guarantees they can't overlap either line, regardless of where the
    # troughs fall in time.
    for dd, color in ((strategy_dd, "tab:blue"), (buyhold_dd, "tab:orange")):
        trough_pos = dd.values.argmin()
        trough_date = dates.iloc[trough_pos]
        trough_value = dd.iloc[trough_pos] * 100
        ax2.scatter([trough_date], [trough_value], color=color, marker="v", s=80, zorder=5)
        ax2.annotate(
            f"{trough_value:.1f}%",
            xy=(trough_date, trough_value),
            xytext=(trough_date, 3.5),
            textcoords="data",
            ha="center",
            va="bottom",
            fontsize=8,
            fontweight="bold",
            color=color,
            arrowprops=dict(arrowstyle="-", color=color, lw=0.8, shrinkA=0, shrinkB=4),
            bbox=dict(boxstyle="round,pad=0.25", fc="white", ec=color, lw=0.6, alpha=0.9),
            zorder=6,
        )

    min_dd = min(strategy_dd.min(), buyhold_dd.min()) * 100
    ax2.set_ylim(min_dd * 1.3, 9)
    ax2.set_ylabel("Drawdown (%)")
    ax2.set_title("Drawdown from Previous Peak")
    ax2.legend(loc="lower left")

    # Panel 3: price with signals and trades
    ax3.plot(dates, window["close"], color="black", linestyle="-", linewidth=1, label="Close")
    ax3.plot(dates, window["sma_short"], color="tab:green", linestyle="-.", linewidth=1, label="50-day SMA")
    ax3.plot(dates, window["sma_long"], color="tab:red", linestyle=":", linewidth=1.3, label="200-day SMA")

    buys = window[window["entry"]]
    sells = window[window["exit"]]
    ax3.scatter(buys["timestamp"], buys["open"], color="green", marker="^", s=70, zorder=5, label="Buy")
    ax3.scatter(sells["timestamp"], sells["open"], color="red", marker="v", s=70, zorder=5, label="Sell")

    ax3.set_ylabel("Price ($)")
    ax3.set_xlabel("Date")
    ax3.set_title("Price, Moving Averages, and Trades")
    ax3.legend(loc="upper left", ncol=3, fontsize=8)

    fig.autofmt_xdate()
    fig.tight_layout(rect=(0, 0, 1, 0.96))

    return fig


def save_chart(fig: plt.Figure, symbol: str) -> Path:
    results_dir = Path("results")
    results_dir.mkdir(exist_ok=True)
    path = results_dir / f"{symbol}_backtest.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    return path


if __name__ == "__main__":
    symbol = sys.argv[1]
    bars = pd.read_csv(f"data/{symbol}.csv", parse_dates=["timestamp"])
    signals = pd.read_csv(f"data/{symbol}_signals.csv", parse_dates=["timestamp"])
    backtest = pd.read_csv(f"data/{symbol}_backtest.csv", parse_dates=["timestamp"])

    chart = build_chart(bars, signals, backtest, symbol)
    output_path = save_chart(chart, symbol)
    print(f"Saved chart to {output_path}")
