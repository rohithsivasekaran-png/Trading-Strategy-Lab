import argparse
import sys
from dataclasses import asdict, dataclass, fields
from datetime import date, time
from pathlib import Path

import numpy as np
import pandas as pd

from trading_agent.intraday import EXCHANGE_TZ, FinalPeriodError, guard_final_period

STOP_BUFFER_PCT = 0.0002
BREAK_PCT = 0.0005
COST_PCT = 0.0002
RECLAIM_MAX_BARS = 6  # counting the breaking bar
LAST_ENTRY_TIME = time(15, 50)
WINDOWS = [
    ("AM", time(9, 30), time(10, 55)),
    ("LUNCH", time(11, 0), time(13, 25)),
    ("PM", time(13, 30), time(15, 55)),
]
SENSITIVITY_TARGETS_R = [1, 3]  # 2R is primary, computed separately
RANDOM_SETS = 100
RANDOM_SEED = 42
MIN_TRADES = 100


@dataclass(frozen=True)
class Bar:
    time: time
    open: float
    high: float
    low: float
    close: float


@dataclass
class Trade:
    symbol: str
    direction: str
    day: date
    window: str
    pdl: float
    pdh: float
    break_time: time
    break_price: float
    reclaim_time: time
    reclaim_price: float
    sweep_extreme: float
    entry_time: time
    entry_price: float
    stop_price: float
    risk: float
    target_price: float
    exit_time: time
    exit_price: float
    exit_reason: str
    cost_r: float
    r_2r: float
    r_1r: float
    r_3r: float


def load_bars(symbol: str) -> pd.DataFrame:
    path = Path("data") / "intraday" / f"{symbol}_5min_2021-01-01_2024-12-31.csv"
    if not path.exists():
        raise FileNotFoundError(f"No intraday data file at {path}")
    df = pd.read_csv(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True).dt.tz_convert(EXCHANGE_TZ)
    guard_development_period(df)
    return df


def guard_development_period(df: pd.DataFrame) -> None:
    max_date = df["timestamp"].max().date()
    guard_final_period(max_date, allow_final_period=False)


def group_by_day(bars: pd.DataFrame) -> list[tuple[date, pd.DataFrame]]:
    bars = bars.sort_values("timestamp").reset_index(drop=True)
    bars = bars.assign(ny_date=bars["timestamp"].dt.date)
    return list(bars.groupby("ny_date", sort=True))


def to_bar_list(day_df: pd.DataFrame) -> list[Bar]:
    return [
        Bar(ts.time(), o, h, l, c)
        for ts, o, h, l, c in zip(
            day_df["timestamp"], day_df["open"], day_df["high"], day_df["low"], day_df["close"]
        )
    ]


def window_for_time(t: time) -> str | None:
    for name, start, end in WINDOWS:
        if start <= t <= end:
            return name
    return None


def window_last_bar_time(window: str) -> time:
    for name, _, end in WINDOWS:
        if name == window:
            return end
    raise ValueError(f"Unknown window: {window}")


def is_break(bar: Bar, direction: str, pdl: float, pdh: float) -> bool:
    if direction == "bull":
        return bar.low < pdl * (1 - BREAK_PCT)
    return bar.high > pdh * (1 + BREAK_PCT)


def is_inside_threshold(price: float, direction: str, pdl: float, pdh: float) -> bool:
    if direction == "bull":
        return price >= pdl * (1 - BREAK_PCT)
    return price <= pdh * (1 + BREAK_PCT)


def is_reclaim(bar: Bar, direction: str, pdl: float, pdh: float) -> bool:
    if direction == "bull":
        return bar.close > pdl
    return bar.close < pdh


def sweep_extreme(day_bars: list[Bar], break_idx: int, reclaim_idx: int, direction: str) -> float:
    segment = day_bars[break_idx : reclaim_idx + 1]
    if direction == "bull":
        return min(b.low for b in segment)
    return max(b.high for b in segment)


def simulate_exit(
    day_bars: list[Bar],
    start_idx: int,
    direction: str,
    entry: float,
    stop: float,
    target: float,
    window_close_time: time,
) -> tuple[int, float, str]:
    for j in range(start_idx, len(day_bars)):
        bar = day_bars[j]
        if direction == "bull":
            hit_stop = bar.low <= stop
            hit_target = bar.high >= target
        else:
            hit_stop = bar.high >= stop
            hit_target = bar.low <= target

        if hit_stop:
            if direction == "bull":
                exit_price = bar.open if bar.open <= stop else stop
            else:
                exit_price = bar.open if bar.open >= stop else stop
            return j, exit_price, "STOP"
        if hit_target:
            return j, target, "TARGET"
        if bar.time == window_close_time:
            return j, bar.close, "TIME"
    raise AssertionError("simulate_exit ran past the window close bar without exiting")


def signed_raw_r(entry: float, stop: float, exit_price: float, direction: str) -> float:
    risk = abs(entry - stop)
    if direction == "bull":
        return (exit_price - entry) / risk
    return (entry - exit_price) / risk


def cost_in_r(entry: float, exit_price: float, risk: float) -> float:
    return (COST_PCT * entry + COST_PCT * exit_price) / risk


def net_r(entry: float, stop: float, exit_price: float, direction: str) -> float:
    risk = abs(entry - stop)
    return signed_raw_r(entry, stop, exit_price, direction) - cost_in_r(entry, exit_price, risk)


def build_trade(
    day_bars: list[Bar],
    symbol: str,
    day: date,
    direction: str,
    pdl: float,
    pdh: float,
    break_idx: int,
    break_price: float,
    reclaim_idx: int,
    reclaim_price: float,
    extreme: float,
    entry_idx: int,
    entry_price: float,
    stop_price: float,
) -> tuple[Trade, int]:
    risk = abs(entry_price - stop_price)
    sign = 1 if direction == "bull" else -1
    window = window_for_time(day_bars[entry_idx].time)
    window_close = window_last_bar_time(window)
    target_2r = entry_price + sign * 2 * risk

    exit_idx, exit_price, exit_reason = simulate_exit(
        day_bars, entry_idx, direction, entry_price, stop_price, target_2r, window_close
    )
    r2 = net_r(entry_price, stop_price, exit_price, direction)

    sensitivity = {}
    for k in SENSITIVITY_TARGETS_R:
        target_k = entry_price + sign * k * risk
        _, exit_k, _ = simulate_exit(
            day_bars, entry_idx, direction, entry_price, stop_price, target_k, window_close
        )
        sensitivity[k] = net_r(entry_price, stop_price, exit_k, direction)

    trade = Trade(
        symbol=symbol,
        direction=direction,
        day=day,
        window=window,
        pdl=pdl,
        pdh=pdh,
        break_time=day_bars[break_idx].time,
        break_price=break_price,
        reclaim_time=day_bars[reclaim_idx].time,
        reclaim_price=reclaim_price,
        sweep_extreme=extreme,
        entry_time=day_bars[entry_idx].time,
        entry_price=entry_price,
        stop_price=stop_price,
        risk=risk,
        target_price=target_2r,
        exit_time=day_bars[exit_idx].time,
        exit_price=exit_price,
        exit_reason=exit_reason,
        cost_r=cost_in_r(entry_price, exit_price, risk),
        r_2r=r2,
        r_1r=sensitivity[1],
        r_3r=sensitivity[3],
    )
    return trade, exit_idx


def detect_and_simulate_day(
    day_bars: list[Bar], symbol: str, day: date, pdl: float, pdh: float
) -> list[Trade]:
    trades: list[Trade] = []
    pending: dict[str, dict | None] = {"bull": None, "bear": None}
    used_today = {"bull": False, "bear": False}
    blocked = {"bull": False, "bear": False}
    n = len(day_bars)
    i = 0
    while i < n:
        bar = day_bars[i]

        if i == 0:
            prior_ref = {"bull": bar.open, "bear": bar.open}
        else:
            prev_bar = day_bars[i - 1]
            prior_ref = {"bull": prev_bar.low, "bear": prev_bar.high}

        for d in ("bull", "bear"):
            if (
                pending[d] is None
                and not used_today[d]
                and not blocked[d]
                and is_inside_threshold(prior_ref[d], d, pdl, pdh)
                and is_break(bar, d, pdl, pdh)
            ):
                pending[d] = {
                    "break_idx": i,
                    "break_price": bar.low if d == "bull" else bar.high,
                }

        for d in ("bull", "bear"):
            p = pending[d]
            if p is None:
                continue
            if is_reclaim(bar, d, pdl, pdh):
                extreme = sweep_extreme(day_bars, p["break_idx"], i, d)
                reclaim_idx = i
                reclaim_price = bar.close
                pending[d] = None

                entry_idx = i + 1
                if entry_idx >= n:
                    continue  # day ends — no trade, allowance not used
                entry_bar = day_bars[entry_idx]
                if entry_bar.time > LAST_ENTRY_TIME:
                    continue  # past cutoff — no trade, allowance not used

                entry_price = entry_bar.open
                if d == "bull":
                    stop_price = extreme - STOP_BUFFER_PCT * extreme
                    gapped = entry_price <= stop_price
                else:
                    stop_price = extreme + STOP_BUFFER_PCT * extreme
                    gapped = entry_price >= stop_price
                if gapped:
                    continue  # gapped past the stop before entry — no trade, allowance not used

                trade, exit_idx = build_trade(
                    day_bars,
                    symbol,
                    day,
                    d,
                    pdl,
                    pdh,
                    p["break_idx"],
                    p["break_price"],
                    reclaim_idx,
                    reclaim_price,
                    extreme,
                    entry_idx,
                    entry_price,
                    stop_price,
                )
                trades.append(trade)
                used_today[d] = True
                pending["bull"] = pending["bear"] = None
                i = exit_idx
                break
            elif (i - p["break_idx"]) >= RECLAIM_MAX_BARS - 1:
                pending[d] = None  # 6 bars elapsed, failed — allowance not used
                blocked[d] = True  # no new break until a close back inside the level

        for d in ("bull", "bear"):
            if blocked[d] and is_reclaim(bar, d, pdl, pdh):
                blocked[d] = False

        i += 1
    return trades


def scan_symbol(bars: pd.DataFrame, symbol: str) -> pd.DataFrame:
    trades: list[Trade] = []
    prev_df = None
    for day, day_df in group_by_day(bars):
        if prev_df is None:
            prev_df = day_df
            continue
        if day_df["early_close"].any():
            prev_df = day_df
            continue
        pdl = prev_df["low"].min()
        pdh = prev_df["high"].max()
        day_bars = to_bar_list(day_df)
        trades.extend(detect_and_simulate_day(day_bars, symbol, day, pdl, pdh))
        prev_df = day_df

    if not trades:
        return pd.DataFrame(columns=[f.name for f in fields(Trade)])
    return pd.DataFrame([asdict(t) for t in trades])


def run_random_benchmark(
    trades_df: pd.DataFrame, bars_by_symbol: dict[str, pd.DataFrame]
) -> pd.DataFrame:
    rng = np.random.default_rng(RANDOM_SEED)

    day_bars_lookup: dict[tuple[str, date], list[Bar]] = {}
    for symbol, bars in bars_by_symbol.items():
        for day, day_df in group_by_day(bars):
            day_bars_lookup[(symbol, day)] = to_bar_list(day_df)

    records = []
    for set_id in range(RANDOM_SETS):
        for row_idx, row in enumerate(trades_df.itertuples()):
            day_bars = day_bars_lookup[(row.symbol, row.day)]
            eligible = [
                idx
                for idx, b in enumerate(day_bars)
                if window_for_time(b.time) == row.window and b.time <= LAST_ENTRY_TIME
            ]
            pick = eligible[rng.integers(len(eligible))]
            entry_bar = day_bars[pick]
            entry_price = entry_bar.open
            stop_pct = row.risk / row.entry_price
            sign = 1 if row.direction == "bull" else -1
            stop_price = entry_price - sign * stop_pct * entry_price
            target_price = entry_price + sign * 2 * stop_pct * entry_price
            window_close = window_last_bar_time(row.window)

            _, exit_price, _ = simulate_exit(
                day_bars, pick, row.direction, entry_price, stop_price, target_price, window_close
            )
            r = net_r(entry_price, stop_price, exit_price, row.direction)
            records.append((set_id, row_idx, row.symbol, row.direction, row.window, r))

    return pd.DataFrame(
        records, columns=["set_id", "trade_row_id", "symbol", "direction", "window", "random_r"]
    )


def worst_losing_streak(ordered_r: list[float]) -> float:
    worst = 0.0
    current = 0.0
    for r in ordered_r:
        if r < 0:
            current += r
            worst = min(worst, current)
        else:
            current = 0.0
    return worst


def compute_group_stats(
    trades_df: pd.DataFrame, random_long: pd.DataFrame, group_cols: list[str]
) -> pd.DataFrame:
    rows = []
    for key, g in trades_df.groupby(group_cols, sort=True):
        key = key if isinstance(key, tuple) else (key,)
        n = len(g)
        win_rate = (g["exit_reason"] == "TARGET").mean()
        pct_positive = (g["r_2r"] > 0).mean()
        avg_r = g["r_2r"].mean()
        median_r = g["r_2r"].median()
        total_r = g["r_2r"].sum()
        ordered = g.sort_values(["day", "entry_time"])["r_2r"].tolist()
        streak = worst_losing_streak(ordered)
        pct_time = (g["exit_reason"] == "TIME").mean()

        mask = pd.Series(True, index=random_long.index)
        for col, val in zip(group_cols, key):
            mask &= random_long[col] == val
        sub = random_long[mask]
        set_means = sub.groupby("set_id")["random_r"].mean()
        p50 = set_means.quantile(0.50)
        p95 = set_means.quantile(0.95)
        real_percentile = 100.0 * (set_means < avg_r).mean()
        edge = bool(n >= MIN_TRADES and avg_r > 0 and avg_r > p95)

        row = dict(zip(group_cols, key))
        row.update(
            {
                "trades": n,
                "win_rate": win_rate,
                "pct_positive": pct_positive,
                "avg_r": avg_r,
                "median_r": median_r,
                "total_r": total_r,
                "worst_streak": streak,
                "pct_time_exit": pct_time,
                "random_p50": p50,
                "random_p95": p95,
                "real_percentile": real_percentile,
                "edge": edge,
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


SUMMARY_COLUMN_ORDER = [
    "symbol",
    "direction",
    "window",
    "trades",
    "win_rate",
    "pct_positive",
    "avg_r",
    "median_r",
    "total_r",
    "worst_streak",
    "pct_time_exit",
    "random_p50",
    "random_p95",
    "real_percentile",
    "edge",
]


def build_summary_table(trades_df: pd.DataFrame, random_long: pd.DataFrame) -> pd.DataFrame:
    detail = compute_group_stats(trades_df, random_long, ["symbol", "direction", "window"])
    by_symbol = compute_group_stats(trades_df, random_long, ["symbol"])
    by_symbol["direction"] = "ALL"
    by_symbol["window"] = "ALL"
    by_window = compute_group_stats(trades_df, random_long, ["window"])
    by_window["symbol"] = "ALL"
    by_window["direction"] = "ALL"
    combined = pd.concat([detail, by_symbol, by_window], ignore_index=True)
    return combined[SUMMARY_COLUMN_ORDER]


COLUMNS = [
    ("Symbol", "symbol", "{}"),
    ("Direction", "direction", "{}"),
    ("Window", "window", "{}"),
    ("Trades", "trades", "{}"),
    ("Win Rate (Target)", "win_rate", "{:.1%}"),
    ("% R>0", "pct_positive", "{:.1%}"),
    ("Avg R", "avg_r", "{:.3f}"),
    ("Median R", "median_r", "{:.3f}"),
    ("Total R", "total_r", "{:.1f}"),
    ("Worst Losing Streak (R)", "worst_streak", "{:.2f}"),
    ("% Time Exit", "pct_time_exit", "{:.1%}"),
    ("Random P50", "random_p50", "{:.3f}"),
    ("Random P95", "random_p95", "{:.3f}"),
    ("Real R Percentile", "real_percentile", "{:.0f}th"),
    ("Edge (Dev)", "edge", "{}"),
]


def format_markdown(df: pd.DataFrame) -> str:
    headers = [label for label, _, _ in COLUMNS]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for _, row in df.iterrows():
        cells = [fmt.format(row[key]) for _, key, fmt in COLUMNS]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def print_table(df: pd.DataFrame) -> None:
    widths = []
    for label, key, fmt in COLUMNS:
        values = [fmt.format(row[key]) for _, row in df.iterrows()]
        widths.append(max(len(label), *(len(v) for v in values)) if values else len(label))

    header = "  ".join(f"{label:<{w}}" for (label, _, _), w in zip(COLUMNS, widths))
    print(header)
    print("-" * len(header))
    for _, row in df.iterrows():
        cells = [fmt.format(row[key]) for _, key, fmt in COLUMNS]
        print("  ".join(f"{cell:<{w}}" for cell, w in zip(cells, widths)))


def save_outputs(trades_df: pd.DataFrame, summary_df: pd.DataFrame) -> tuple[Path, Path]:
    data_dir = Path("data") / "chapter2"
    data_dir.mkdir(parents=True, exist_ok=True)
    trades_path = data_dir / "setupA_dev_trades.csv"
    trades_df.to_csv(trades_path, index=False)

    results_dir = Path("results") / "chapter2"
    results_dir.mkdir(parents=True, exist_ok=True)
    summary_path = results_dir / "setupA_dev_summary.md"
    summary_path.write_text(format_markdown(summary_df))

    return trades_path, summary_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("symbols", nargs="+")
    args = parser.parse_args()

    bars_by_symbol = {}
    all_trades = []
    for symbol in args.symbols:
        try:
            bars = load_bars(symbol)
        except FinalPeriodError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(1)
        bars_by_symbol[symbol] = bars
        all_trades.append(scan_symbol(bars, symbol))

    trades_df = pd.concat(all_trades, ignore_index=True)
    if len(trades_df) == 0:
        print("No trades found.", file=sys.stderr)
        sys.exit(1)

    random_long = run_random_benchmark(trades_df, bars_by_symbol)
    summary_df = build_summary_table(trades_df, random_long)

    trades_path, summary_path = save_outputs(trades_df, summary_df)
    print(f"Saved {len(trades_df)} trades to {trades_path}")
    print(f"Saved summary to {summary_path}")
    print()
    print_table(summary_df)


if __name__ == "__main__":
    main()
