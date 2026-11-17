# Chapter 2 pre-registration: Testing ICT concepts

**Written:** 17 November 2026, before downloading any intraday data or seeing any results.
**Status:** Frozen. Rules may only be changed to fix code that does not match this document (a bug), never to improve results. Every change is logged in the changelog at the end, with its reason.

## Research question

Do popular ICT concepts, turned into precise rules, show a real edge over random entries after trading costs?

## Hypotheses

- **H1:** Liquidity sweeps will work best on their own, because they are the clearest sign that big players have entered.
- **H2:** Setups inside killzones will do better than setups outside them, because moves then reflect big players rather than random noise.
- **H3:** The full ICT model will beat random entries after costs, because combining the rules makes it more precise.

## Design decisions

| Item | Decision |
| --- | --- |
| Markets | SPY and QQQ |
| Data | 5-minute bars, SIP feed, split- and dividend-adjusted, regular hours only (09:30 to 16:00 New York time) |
| Time zone | All rules use New York time |
| Development period | 2021-01-01 to 2024-12-31 |
| Final test period (unseen) | 2025-01-01 to 2026-09-30, run once, only after all code is frozen |
| Costs | 0.02% of price per side, on every entry and exit |
| Directions | Bullish and bearish setups, reported separately (bearish rules mirror the bullish ones) |
| Positions | One trade at a time per symbol; nothing held overnight |
| Same-bar ambiguity | If a bar touches both stop and target, assume the stop was hit first |
| Results | Measured in R (multiples of the risk per trade), after costs |
| Minimum sample | At least 100 trades before drawing a conclusion from any test |

## Definitions

- **Bar time:** each bar is labelled by its start time.
- **Windows:**
  - Killzone AM: bars starting 09:30 to 10:55
  - Outside killzones (lunch): bars starting 11:00 to 13:25
  - Killzone PM: bars starting 13:30 to 15:55
- **Time exit:** a trade still open at the end of the window in which it was entered is closed at that window's last bar close.
- **Previous day's high and low (PDH, PDL):** from the previous trading day's regular-hours bars.
- **Swing high:** a bar whose high is higher than the highs of the 3 bars before and the 3 bars after it. It is only **confirmed** at the close of the 3rd bar after it, and can only be used from the next bar onwards (no look-ahead). Swing lows are the mirror image.
- **Average body:** the average of |close − open| over the previous 20 bars (not including the current bar).
- **Displacement bar:** a bar whose body is at least 2 × the average body, in the direction of the setup.
- **R:** the distance between the entry price and the stop-loss.
- **Cost in R:** (0.0002 × entry price + 0.0002 × exit price) ÷ R, subtracted from every trade.
- **Limit order fill rule:** a buy limit only counts as filled if a later bar trades at least 0.01% below the limit price; it fills at the limit price (or at the bar's open, if the bar opens below it). Sell limits mirror this.
- **Stop buffer:** 0.02% of price beyond the level that invalidates the setup.
- **Primary target:** 2R. Targets of 1R and 3R are reported as sensitivity checks only.

## Setup A: Liquidity sweep (bullish)

1. **Level:** the previous day's low (PDL).
2. **Break:** a bar's low goes below PDL × (1 − 0.0005), i.e. at least 0.05% below the level.
3. **Reclaim:** within 6 bars, counting the breaking bar, a bar **closes** above PDL. If not, there is no trade.
4. **Sweep low:** the lowest low from the breaking bar to the reclaim bar.
5. **Entry:** the open of the bar after the reclaim bar.
6. **Stop-loss:** the sweep low minus the stop buffer.
7. **Target:** 2R.
8. **Limits:** one trade per level per day; no entries after 15:50.

## Setup B: Fair value gap (bullish)

1. **Gap:** for three bars (1, 2, 3), the low of bar 3 is above the high of bar 1, and the gap is at least 0.05% of bar 2's close.
2. **Displacement:** bar 2 is a bullish displacement bar.
3. **Order:** a buy limit at the top of the gap (the low of bar 3), active from the bar after bar 3 for up to 24 bars, or until the end of the window, whichever comes first.
4. **Cancel:** if a bar closes below the bottom of the gap before the order fills.
5. **Stop-loss:** the bottom of the gap (the high of bar 1) minus the stop buffer.
6. **Target:** 2R.
7. **Limits:** one trade per gap; first touch only.

## Setup C: Order block (bullish)

1. **Displacement:** a bullish displacement bar that **closes above the highest high of the previous 10 bars**.
2. **Order block:** the last bearish bar (close below open) within the 5 bars before the displacement bar. If there is none, no setup.
3. **Zone:** from the order block's low to its open.
4. **Order:** a buy limit at the top of the zone (the order block's open), active from the bar after the displacement bar for up to 24 bars, or until the end of the window.
5. **Cancel:** if a bar closes below the order block's low before the order fills.
6. **Stop-loss:** the order block's low minus the stop buffer.
7. **Target:** 2R.
8. **Limits:** one trade per order block; first touch only.

## Setup D: Full ICT model (bullish)

Only setups that form **inside a killzone** (AM or PM).

1. **Level:** the most recent confirmed swing low.
2. **Sweep:** price breaks below that level and closes back above it, using the break and reclaim rules of Setup A.
3. **Structure shift:** within 12 bars after the reclaim, a bar closes above the most recent confirmed swing high that formed before the sweep.
4. **Gap:** the move that produced the structure shift creates a bullish fair value gap (Setup B rules), with bar 2 of the gap being the structure-shift bar or one of the 2 bars after it.
5. **Entry, cancel, stop and target:** as in Setup B.
6. **Secondary variant (reported separately):** stop-loss below the sweep low instead of below the gap.

## Random benchmark

For every real trade, a random trade is created with:

- the same symbol, day, window and direction,
- a random entry bar within that window (at the bar's open), no later than the last allowed entry time,
- the same stop distance as a percentage of the entry price,
- the same 2R target, costs and time-exit rule.

This is repeated to create **100 random sets**. The average R of each random set gives a distribution of results that luck alone produces.

## How results are judged

For each setup, symbol, direction and window, report: number of trades, win rate, average R after costs, median R, total R, worst losing streak in R, and the share of trades closed by the time exit.

- **Edge in the development period:** at least 100 trades, average R after costs above 0, and above the 95th percentile of the random sets.
- **Edge confirmed:** in the unseen final test period, average R after costs is still above 0 and above the 90th percentile of the random sets.
- **H2** is judged by comparing Setups A, B and C in the killzone windows with the same setups in the lunch window.

Anything else is reported as **no evidence of an edge**.

## Changelog

| Date | Change | Reason |
| --- | --- | --- |
| 2026-11-17 | Document created and frozen | Pre-registration before any data was downloaded |
