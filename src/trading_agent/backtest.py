import sys
from pathlib import Path

import numpy as np
import pandas as pd

TRADING_DAYS_PER_YEAR = 252


def run_backtest(
    bars: pd.DataFrame,
    signals: pd.DataFrame,
    initial_capital: float = 10_000.0,
    cost_rate: float = 0.0005,
) -> pd.DataFrame:
    df = pd.merge(
        bars[["timestamp", "open", "close"]],
        signals[["timestamp", "signal"]],
        on="timestamp",
    ).sort_values("timestamp").reset_index(drop=True)

    position = df["signal"].shift(1).fillna(0).astype(int)
    prev_position = position.shift(1).fillna(0).astype(int)
    entry = (position == 1) & (prev_position == 0)
    exit_ = (position == 0) & (prev_position == 1)
    held = (position == 1) & (prev_position == 1)

    prev_close = df["close"].shift(1)

    strategy_return = pd.Series(0.0, index=df.index)
    strategy_return[held] = df["close"][held] / prev_close[held] - 1
    strategy_return[entry] = df["close"][entry] / df["open"][entry] - 1
    strategy_return[exit_] = df["open"][exit_] / prev_close[exit_] - 1

    strategy_equity = np.empty(len(df))
    equity = initial_capital
    for i in range(len(df)):
        raw_equity = equity * (1 + strategy_return.iloc[i])
        if entry.iloc[i]:
            cost = cost_rate * equity
        elif exit_.iloc[i]:
            cost = cost_rate * raw_equity
        else:
            cost = 0.0
        equity = raw_equity - cost
        strategy_equity[i] = equity

    entry_indices = df.index[entry]
    if len(entry_indices) == 0:
        raise ValueError("Signal never turns on; no entry day to anchor buy-and-hold")
    first_entry_idx = entry_indices[0]

    buyhold_equity = np.empty(len(df))
    equity = initial_capital
    for i in range(len(df)):
        if i < first_entry_idx:
            equity = initial_capital
        elif i == first_entry_idx:
            raw_equity = equity * df["close"].iloc[i] / df["open"].iloc[i]
            equity = raw_equity - cost_rate * equity
        else:
            equity = equity * df["close"].iloc[i] / df["close"].iloc[i - 1]
        buyhold_equity[i] = equity

    df["position"] = position
    df["entry"] = entry
    df["exit"] = exit_
    df["strategy_return"] = strategy_return
    df["strategy_equity"] = strategy_equity
    df["buyhold_equity"] = buyhold_equity
    df["buyhold_invested"] = df.index >= first_entry_idx

    return df


def compute_metrics(
    equity: pd.Series,
    timestamps: pd.Series,
    trade_count: int,
    pct_invested: float,
) -> dict:
    daily_returns = equity.pct_change().dropna()
    n_days = len(equity) - 1

    initial_value = equity.iloc[0]
    final_value = equity.iloc[-1]
    total_return = final_value / initial_value - 1
    years = n_days / TRADING_DAYS_PER_YEAR
    cagr = (final_value / initial_value) ** (1 / years) - 1 if years > 0 else float("nan")

    vol = daily_returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR)
    sharpe = (
        daily_returns.mean() / daily_returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR)
        if daily_returns.std() > 0
        else float("nan")
    )

    running_max = equity.cummax()
    drawdown = equity / running_max - 1
    trough_pos = drawdown.values.argmin()
    max_drawdown = drawdown.iloc[trough_pos]
    peak_pos = equity.iloc[: trough_pos + 1].values.argmax()
    peak_date = timestamps.iloc[peak_pos]
    trough_date = timestamps.iloc[trough_pos]

    return {
        "final_value": final_value,
        "total_return": total_return,
        "cagr": cagr,
        "annualized_vol": vol,
        "sharpe": sharpe,
        "max_drawdown": max_drawdown,
        "max_drawdown_peak_date": peak_date,
        "max_drawdown_trough_date": trough_date,
        "num_trades": trade_count,
        "pct_days_invested": pct_invested,
    }


def print_metrics_table(strategy_metrics: dict, buyhold_metrics: dict) -> None:
    rows = [
        ("Final value", "final_value", "${:,.2f}"),
        ("Total return", "total_return", "{:.2%}"),
        ("CAGR", "cagr", "{:.2%}"),
        ("Annualized volatility", "annualized_vol", "{:.2%}"),
        ("Sharpe ratio", "sharpe", "{:.2f}"),
        ("Max drawdown", "max_drawdown", "{:.2%}"),
        ("Max drawdown peak", "max_drawdown_peak_date", "{}"),
        ("Max drawdown trough", "max_drawdown_trough_date", "{}"),
        ("Number of trades", "num_trades", "{}"),
        ("% days invested", "pct_days_invested", "{:.2f}%"),
    ]
    label_width = max(len(label) for label, _, _ in rows)
    header = f"{'Metric':<{label_width}}  {'Strategy':>18}  {'Buy & Hold':>18}"
    print(header)
    print("-" * len(header))
    for label, key, fmt in rows:
        strategy_val = fmt.format(strategy_metrics[key])
        buyhold_val = fmt.format(buyhold_metrics[key])
        print(f"{label:<{label_width}}  {strategy_val:>18}  {buyhold_val:>18}")


def save_backtest(df: pd.DataFrame, symbol: str) -> Path:
    data_dir = Path("data")
    data_dir.mkdir(exist_ok=True)
    path = data_dir / f"{symbol}_backtest.csv"
    df[["timestamp", "strategy_equity", "buyhold_equity"]].to_csv(path, index=False)
    return path


if __name__ == "__main__":
    symbol = sys.argv[1]
    bars = pd.read_csv(f"data/{symbol}.csv", parse_dates=["timestamp"])
    signals = pd.read_csv(f"data/{symbol}_signals.csv", parse_dates=["timestamp"])

    initial_capital = 10_000.0
    result = run_backtest(bars, signals, initial_capital=initial_capital)
    save_backtest(result, symbol)

    first_entry_idx = result.index[result["entry"]][0]
    active = result.loc[first_entry_idx:].reset_index(drop=True)

    strategy_trades = int(active["entry"].sum() + active["exit"].sum())
    strategy_metrics = compute_metrics(
        active["strategy_equity"],
        active["timestamp"],
        trade_count=strategy_trades,
        pct_invested=active["position"].mean() * 100,
    )
    buyhold_metrics = compute_metrics(
        active["buyhold_equity"],
        active["timestamp"],
        trade_count=1,
        pct_invested=active["buyhold_invested"].mean() * 100,
    )

    print_metrics_table(strategy_metrics, buyhold_metrics)
