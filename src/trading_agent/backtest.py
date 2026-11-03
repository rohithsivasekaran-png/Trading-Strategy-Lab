import argparse
from pathlib import Path

import numpy as np
import pandas as pd


def run_backtest(
    bars: pd.DataFrame,
    signals: pd.DataFrame,
    initial_capital: float = 10_000.0,
    cost_rate: float = 0.0005,
    start_date: pd.Timestamp | None = None,
    end_date: pd.Timestamp | None = None,
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

    if start_date is None and end_date is None:
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

    if start_date is not None:
        start_date = pd.Timestamp(start_date)
    if end_date is not None:
        end_date = pd.Timestamp(end_date)
    if start_date is not None and end_date is not None and start_date.date() > end_date.date():
        raise ValueError(f"start_date {start_date.date()} is after end_date {end_date.date()}")

    mask = pd.Series(True, index=df.index)
    if start_date is not None:
        mask &= df["timestamp"].dt.date >= start_date.date()
    if end_date is not None:
        mask &= df["timestamp"].dt.date <= end_date.date()
    if not mask.any():
        raise ValueError(
            f"No trading days found between start_date={start_date} and end_date={end_date}"
        )

    window = df.loc[mask].reset_index(drop=True)
    w_position = position.loc[mask].reset_index(drop=True)
    w_entry = entry.loc[mask].reset_index(drop=True).copy()
    w_exit = exit_.loc[mask].reset_index(drop=True).copy()
    w_held = held.loc[mask].reset_index(drop=True).copy()

    w_entry.iloc[0] = bool(w_position.iloc[0] == 1)
    w_exit.iloc[0] = False
    w_held.iloc[0] = False

    prev_close = window["close"].shift(1)

    strategy_return = pd.Series(0.0, index=window.index)
    strategy_return[w_held] = window["close"][w_held] / prev_close[w_held] - 1
    strategy_return[w_entry] = window["close"][w_entry] / window["open"][w_entry] - 1
    strategy_return[w_exit] = window["open"][w_exit] / prev_close[w_exit] - 1

    strategy_equity = np.empty(len(window))
    equity = initial_capital
    for i in range(len(window)):
        raw_equity = equity * (1 + strategy_return.iloc[i])
        if w_entry.iloc[i]:
            cost = cost_rate * equity
        elif w_exit.iloc[i]:
            cost = cost_rate * raw_equity
        else:
            cost = 0.0
        equity = raw_equity - cost
        strategy_equity[i] = equity

    buyhold_equity = np.empty(len(window))
    equity = initial_capital
    raw_equity = equity * window["close"].iloc[0] / window["open"].iloc[0]
    equity = raw_equity - cost_rate * equity
    buyhold_equity[0] = equity
    for i in range(1, len(window)):
        equity = equity * window["close"].iloc[i] / window["close"].iloc[i - 1]
        buyhold_equity[i] = equity

    window["position"] = w_position
    window["entry"] = w_entry
    window["exit"] = w_exit
    window["strategy_return"] = strategy_return
    window["strategy_equity"] = strategy_equity
    window["buyhold_equity"] = buyhold_equity
    window["buyhold_invested"] = True

    return window


def compute_metrics(
    equity: pd.Series,
    timestamps: pd.Series,
    trade_count: int,
    pct_invested: float,
    periods_per_year: int = 252,
) -> dict:
    daily_returns = equity.pct_change().dropna()
    n_days = len(equity) - 1

    initial_value = equity.iloc[0]
    final_value = equity.iloc[-1]
    total_return = final_value / initial_value - 1
    years = n_days / periods_per_year
    cagr = (final_value / initial_value) ** (1 / years) - 1 if years > 0 else float("nan")

    vol = daily_returns.std() * np.sqrt(periods_per_year)
    sharpe = (
        daily_returns.mean() / daily_returns.std() * np.sqrt(periods_per_year)
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


def _window_suffix(short_window: int, long_window: int) -> str:
    if (short_window, long_window) == (50, 200):
        return ""
    return f"_{short_window}_{long_window}"


def _date_suffix(start_date: pd.Timestamp | None, end_date: pd.Timestamp | None) -> str:
    if start_date is None and end_date is None:
        return ""
    start_str = pd.Timestamp(start_date).date().isoformat() if start_date is not None else "start"
    end_str = pd.Timestamp(end_date).date().isoformat() if end_date is not None else "end"
    return f"_{start_str}_{end_str}"


def save_backtest(
    df: pd.DataFrame,
    symbol: str,
    short_window: int = 50,
    long_window: int = 200,
    start_date: pd.Timestamp | None = None,
    end_date: pd.Timestamp | None = None,
) -> Path:
    data_dir = Path("data")
    data_dir.mkdir(exist_ok=True)
    suffix = _window_suffix(short_window, long_window)
    date_suffix = _date_suffix(start_date, end_date)
    path = data_dir / f"{symbol}{suffix}{date_suffix}_backtest.csv"
    df[["timestamp", "strategy_equity", "buyhold_equity"]].to_csv(path, index=False)
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("symbol")
    parser.add_argument("--short-window", type=int, default=50)
    parser.add_argument("--long-window", type=int, default=200)
    parser.add_argument("--cost", type=float, default=0.0005)
    parser.add_argument("--periods-per-year", type=int, default=252)
    parser.add_argument("--start-date", type=str, default=None, help="YYYY-MM-DD, inclusive, UTC calendar date")
    parser.add_argument("--end-date", type=str, default=None, help="YYYY-MM-DD, inclusive, UTC calendar date")
    args = parser.parse_args()

    symbol = args.symbol
    suffix = _window_suffix(args.short_window, args.long_window)
    bars = pd.read_csv(f"data/{symbol}.csv", parse_dates=["timestamp"])
    signals = pd.read_csv(f"data/{symbol}{suffix}_signals.csv", parse_dates=["timestamp"])

    start_date = pd.Timestamp(args.start_date, tz="UTC") if args.start_date else None
    end_date = pd.Timestamp(args.end_date, tz="UTC") if args.end_date else None

    initial_capital = 10_000.0
    result = run_backtest(
        bars, signals, initial_capital=initial_capital, cost_rate=args.cost,
        start_date=start_date, end_date=end_date,
    )
    save_backtest(result, symbol, args.short_window, args.long_window, start_date, end_date)

    if start_date is None and end_date is None:
        first_entry_idx = result.index[result["entry"]][0]
        active = result.loc[first_entry_idx:].reset_index(drop=True)
    else:
        active = result
        print(f"Window: {active['timestamp'].iloc[0].date()} to {active['timestamp'].iloc[-1].date()}")

    strategy_trades = int(active["entry"].sum() + active["exit"].sum())
    strategy_metrics = compute_metrics(
        active["strategy_equity"],
        active["timestamp"],
        trade_count=strategy_trades,
        pct_invested=active["position"].mean() * 100,
        periods_per_year=args.periods_per_year,
    )
    buyhold_metrics = compute_metrics(
        active["buyhold_equity"],
        active["timestamp"],
        trade_count=1,
        pct_invested=active["buyhold_invested"].mean() * 100,
        periods_per_year=args.periods_per_year,
    )

    print_metrics_table(strategy_metrics, buyhold_metrics)
