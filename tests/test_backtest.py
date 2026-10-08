import numpy as np
import pandas as pd

from trading_agent.backtest import run_backtest


def test_always_invested_matches_buy_and_hold():
    bars = pd.read_csv("data/EWJ.csv", parse_dates=["timestamp"])
    signals = pd.DataFrame({"timestamp": bars["timestamp"], "signal": 1})

    result = run_backtest(bars, signals)

    assert np.allclose(
        result["strategy_equity"], result["buyhold_equity"], rtol=1e-9
    )
