import argparse
from pathlib import Path

import pandas as pd

from trading_agent.backtest import _window_suffix, compute_metrics, run_backtest

COMMON_START = pd.Timestamp("2021-10-08", tz="UTC")
COMMON_END = pd.Timestamp("2026-10-07", tz="UTC")

RUNS = [
    {"label": "EWJ (50/200)", "symbol": "EWJ", "short_window": 50, "long_window": 200, "cost": 0.0005, "periods_per_year": 252},
    {"label": "VGK (50/200)", "symbol": "VGK", "short_window": 50, "long_window": 200, "cost": 0.0005, "periods_per_year": 252},
    {"label": "BTC-USD (70/280)", "symbol": "BTC-USD", "short_window": 70, "long_window": 280, "cost": 0.0025, "periods_per_year": 365},
    {"label": "BTC-USD (50/200)", "symbol": "BTC-USD", "short_window": 50, "long_window": 200, "cost": 0.0025, "periods_per_year": 365},
]


def run_one(cfg: dict, start_date: pd.Timestamp, end_date: pd.Timestamp) -> dict:
    bars = pd.read_csv(f"data/{cfg['symbol']}.csv", parse_dates=["timestamp"])
    suffix = _window_suffix(cfg["short_window"], cfg["long_window"])
    signals = pd.read_csv(f"data/{cfg['symbol']}{suffix}_signals.csv", parse_dates=["timestamp"])

    result = run_backtest(
        bars, signals, initial_capital=10_000.0, cost_rate=cfg["cost"],
        start_date=start_date, end_date=end_date,
    )

    trades = int(result["entry"].sum() + result["exit"].sum())
    strat = compute_metrics(
        result["strategy_equity"], result["timestamp"], trade_count=trades,
        pct_invested=result["position"].mean() * 100, periods_per_year=cfg["periods_per_year"],
    )
    bh = compute_metrics(
        result["buyhold_equity"], result["timestamp"], trade_count=1,
        pct_invested=result["buyhold_invested"].mean() * 100, periods_per_year=cfg["periods_per_year"],
    )

    return {
        "label": cfg["label"],
        "strategy_cagr": strat["cagr"],
        "buyhold_cagr": bh["cagr"],
        "cagr_diff": strat["cagr"] - bh["cagr"],
        "strategy_sharpe": strat["sharpe"],
        "buyhold_sharpe": bh["sharpe"],
        "sharpe_diff": strat["sharpe"] - bh["sharpe"],
        "strategy_max_drawdown": strat["max_drawdown"],
        "buyhold_max_drawdown": bh["max_drawdown"],
        "num_trades": strat["num_trades"],
        "pct_days_invested": strat["pct_days_invested"],
    }


def build_comparison_table(start_date: pd.Timestamp, end_date: pd.Timestamp) -> pd.DataFrame:
    return pd.DataFrame([run_one(cfg, start_date, end_date) for cfg in RUNS])


COLUMNS = [
    ("Run", "label", "{}"),
    ("Strategy CAGR", "strategy_cagr", "{:.2%}"),
    ("Buy & Hold CAGR", "buyhold_cagr", "{:.2%}"),
    ("CAGR Diff", "cagr_diff", "{:+.2%}"),
    ("Strategy Sharpe", "strategy_sharpe", "{:.2f}"),
    ("Buy & Hold Sharpe", "buyhold_sharpe", "{:.2f}"),
    ("Sharpe Diff", "sharpe_diff", "{:+.2f}"),
    ("Strategy Max DD", "strategy_max_drawdown", "{:.2%}"),
    ("Buy & Hold Max DD", "buyhold_max_drawdown", "{:.2%}"),
    ("Trades", "num_trades", "{}"),
    ("% Days Invested", "pct_days_invested", "{:.2f}%"),
]


def format_markdown(df: pd.DataFrame) -> str:
    headers = [label for label, _, _ in COLUMNS]
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for _, row in df.iterrows():
        cells = [fmt.format(row[key]) for _, key, fmt in COLUMNS]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def print_table(df: pd.DataFrame) -> None:
    widths = []
    for label, key, fmt in COLUMNS:
        values = [fmt.format(row[key]) for _, row in df.iterrows()]
        widths.append(max(len(label), *(len(v) for v in values)))

    header = "  ".join(f"{label:<{w}}" for (label, _, _), w in zip(COLUMNS, widths))
    print(header)
    print("-" * len(header))
    for _, row in df.iterrows():
        cells = [fmt.format(row[key]) for _, key, fmt in COLUMNS]
        print("  ".join(f"{cell:<{w}}" for cell, w in zip(cells, widths)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date", type=str, default=None)
    parser.add_argument("--end-date", type=str, default=None)
    args = parser.parse_args()

    start_date = pd.Timestamp(args.start_date, tz="UTC") if args.start_date else COMMON_START
    end_date = pd.Timestamp(args.end_date, tz="UTC") if args.end_date else COMMON_END

    print(f"Common period: {start_date.date()} to {end_date.date()}")
    print()

    table = build_comparison_table(start_date, end_date)

    results_dir = Path("results")
    results_dir.mkdir(exist_ok=True)
    table.to_csv(results_dir / "comparison.csv", index=False)
    (results_dir / "comparison.md").write_text(format_markdown(table))

    print_table(table)
