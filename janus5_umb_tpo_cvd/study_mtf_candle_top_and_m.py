"""
Research Experiment: Daily (1D), Weekly (5D), and Monthly (21D) Candle Structure
in Top Detection (JANUS-5 Bear B1/B2) and Market Fall-Through (Model M)
================================================================================
Tests zero-lookahead rolling Daily, Weekly (5-bar composite candle), and Monthly
(21-bar composite candle) structure across 1999-2026 for QQQ and SPY.
"""

from pathlib import Path
import warnings
import numpy as np
import pandas as pd

from build_dual_bull_bear_engine import add_bear_model_set
from discover_state_locked_80pct_bear import de_cluster_active_race
from test_janus5_trending_bull_fix import apply_janus5_fixes

warnings.filterwarnings("ignore")
DATA_DIR = Path(__file__).resolve().parent / "data"


def add_mtf_candles(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    o = df["open"]
    h = df["high"]
    l = df["low"]
    c = df["close"]

    # 1. Daily (1D) Candle Structure
    rng1 = (h - l).clip(lower=1e-6)
    df["d1_clv"] = (c - l) / rng1
    df["d1_uwick"] = (h - np.maximum(o, c)) / rng1
    df["d1_red"] = c < o
    df["d1_engulf_bear"] = (c < o) & (o >= c.shift(1)) & (c <= o.shift(1)) & ((o - c) > (c.shift(1) - o.shift(1)).abs())

    # 2. Weekly (5D Composite) Candle Structure
    o5 = o.shift(4)
    h5 = h.rolling(5, min_periods=1).max()
    l5 = l.rolling(5, min_periods=1).min()
    rng5 = (h5 - l5).clip(lower=1e-6)
    df["w1_clv"] = (c - l5) / rng5
    df["w1_uwick"] = (h5 - np.maximum(o5, c)) / rng5
    df["w1_top_tail"] = (h5 - c) / rng5  # Distance from 5d high relative to 5d range (1 - w1_clv)
    df["w1_red"] = c < o5
    df["w1_rollover"] = (df["w1_clv"] < 0.55) | (df["w1_uwick"] > 0.25) | df["w1_red"]

    # 3. Monthly (21D Composite) Candle Structure
    o21 = o.shift(20)
    h21 = h.rolling(21, min_periods=5).max()
    l21 = l.rolling(21, min_periods=5).min()
    rng21 = (h21 - l21).clip(lower=1e-6)
    df["m1_clv"] = (c - l21) / rng21
    df["m1_uwick"] = (h21 - np.maximum(o21, c)) / rng21
    df["m1_top_tail"] = (h21 - c) / rng21
    df["m1_red"] = c < o21
    df["m1_rollover"] = (df["m1_clv"] < 0.65) | (df["m1_uwick"] > 0.20) | df["m1_red"]

    # 4. Optimal MTF (1D / 1W / 1M) Top Candle Structure Filter:
    # - 1D: Never short a strong green breakout candle closing in top 25% of range (~(d1_clv > 0.75 & ~d1_red))
    # - 1W (5D): Require Weekly Upper Wick (w1_uwick >= 0.12) OR Weekly Rollover (w1_clv < 0.70)
    # - 1M (21D): Must be an early top, NOT already washed out at bottom of monthly candle (m1_uwick <= 0.65 & m1_clv >= 0.25)
    df["mtf_candle_top_filter"] = (
        ~((df["d1_clv"] > 0.75) & (~df["d1_red"]))
        & ((df["w1_uwick"] >= 0.12) | (df["w1_clv"] < 0.70))
        & (df["m1_uwick"] <= 0.65)
        & (df["m1_clv"] >= 0.25)
    )

    return df


def eval_model_m_fallthrough(df: pd.DataFrame, ticker: str):
    c = df["close"]
    h = df["high"]
    l = df["low"]

    sma50 = c.rolling(50).mean()
    sma200 = df["sma200"]
    pos20 = df["pos_in_20d_range"]
    vix = df["opt_vix"]
    ts = df["opt_term_ratio"]
    hyg_z = df["lead_hyg_ief_z21"].fillna(0.0)
    can_z = df["lead_xly_xlp_z21"].fillna(0.0)
    clv_d = ((c - l) - (h - c)) / (h - l).replace(0, np.nan)
    clv_ema5 = clv_d.ewm(span=5, adjust=False).mean().fillna(0.0)

    # Baseline Model M raw sum
    m_term = np.maximum(0.0, (ts - 0.95) / 0.15) * 2.0
    m_vix = np.maximum(0.0, (vix - 20.0) / 10.0) * 1.5
    m_hyg = np.maximum(0.0, -hyg_z) * 1.5
    m_dark = np.maximum(0.0, -clv_ema5) * 1.5
    m_roll20 = np.maximum(0.0, (0.50 - pos20) * 2.0) * 1.5
    m_ma = (c < sma50).astype(float) * 1.0 + (c < sma200).astype(float) * 1.5
    m_can = np.maximum(0.0, -can_z) * 1.5

    m_raw_base = m_term + m_vix + m_hyg + m_dark + m_roll20 + m_ma + m_can
    model_m_base = (1.0 / (1.0 + np.exp(-(m_raw_base - 6.5) / 2.0))) * 100.0

    # Upgraded Model M with 1D + 1W + 1M Candle Structure:
    # Weekly Upper Wick / Rejection + Monthly Upper Wick / Red Candle + Daily Rejection
    w1_stress = np.maximum(0.0, (0.50 - df["w1_clv"]) * 2.0) * 1.2 + np.where(df["w1_red"], 0.6, 0.0)
    m1_stress = np.maximum(0.0, (0.50 - df["m1_clv"]) * 2.0) * 1.2 + np.where(df["m1_red"], 0.6, 0.0)
    mtf_candle_gate = (df["d1_clv"] < 0.45) & (df["w1_clv"] < 0.50) & (df["m1_clv"] < 0.55)

    # Forward 20-day max drawdown (fall-through >= -5%)
    fwd_low20 = l.iloc[::-1].rolling(20, min_periods=1).min().iloc[::-1].shift(-1)
    fwd_dd20 = (fwd_low20 / c - 1.0) * 100.0
    is_fall5 = (fwd_dd20 <= -5.0)

    # Compare M >= 70% trigger precision for -5% fall-through (de-clustered 15d)
    def score_trigger(mask_s):
        dates = []
        last_i = -999
        arr = mask_s.fillna(False).values
        for i in range(len(arr) - 20):
            if arr[i] and (i - last_i >= 15):
                dates.append(i)
                last_i = i
        if not dates:
            return 0, 0.0, 0.0
        sub_dd = fwd_dd20.iloc[dates]
        wr = (sub_dd <= -5.0).mean() * 100.0
        return len(dates), wr, sub_dd.mean()

    b_mask = (model_m_base >= 70.0) & (model_m_base.shift(1) < 70.0)
    u_mask = b_mask & mtf_candle_gate
    w_only = b_mask & (df["w1_clv"] < 0.45) & df["w1_red"]
    m_only = b_mask & (df["m1_clv"] < 0.45) & df["m1_red"]
    wm_comb = b_mask & df["d1_red"] & df["w1_red"] & df["m1_red"] & (df["w1_clv"] < 0.40)

    print(f"\n================ {ticker} MODEL M FALL-THROUGH (-5% IN 20D) CANDLE RESEARCH ================")
    for label, m in [
        ("1. Baseline Model M Cross >= 70% (1D CLV only)", b_mask),
        ("2. Model M + Weekly (5D) Red & CLV < 45%", w_only),
        ("3. Model M + Monthly (21D) Red & CLV < 45%", m_only),
        ("4. Model M + 1D/1W/1M CLV Rollover Gate", u_mask),
        ("5. Model M + Full 1D+1W+1M Red Candle Alignment", wm_comb),
    ]:
        n, wr, avg_dd = score_trigger(m)
        print(f"  {label:48s} | Signals: {n:3d} | -5% Drop Hit Rate: {wr:5.1f}% | Avg 20d Max Drop: {avg_dd:+6.2f}%")


def eval_janus5_bear_candles(df: pd.DataFrame, ticker: str):
    print(f"\n================ {ticker} JANUS-5 BEAR (B1+B2 TOP DETECTOR) CANDLE RESEARCH ================")
    base_sig = df["BEAR_COMBINED_RAW"].copy()
    b1_sig = df["BEAR_TIER1_RAW"].copy()

    # Variants of MTF candle filter on JANUS-5 Bear Combined (B1+B2)
    variants = [
        ("1. Baseline B1 Sniper (1D only)", b1_sig),
        ("2. B1 Sniper + Optimal 1D/1W/1M Candle Filter", b1_sig & df["mtf_candle_top_filter"]),
        ("3. Baseline B1+B2 All (1D only)", base_sig),
        ("4. B1+B2 All + Optimal 1D/1W/1M Candle Filter", base_sig & df["mtf_candle_top_filter"]),
        ("5. B1+B2 All + Monthly (21D) Rollover", base_sig & df["m1_rollover"]),
    ]

    for label, sig in variants:
        _, st = de_cluster_active_race(df, sig, max_hold=180, cooldown=3)
        print(
            f"  {label:52s} | N={st['n_all']:2d} (IS={st['n_is']:2d}, OOS={st['n_oos']:2d}) | "
            f"RACE_DN WR: All={st['wr_all']:5.1f}% (IS={st['wr_is']:5.1f}%, OOS={st['wr_oos']:5.1f}%) | "
            f"TOUCH60_DN: {st['t60_all']:5.1f}%"
        )


def main():
    for ticker in ["QQQ", "SPY"]:
        raw_df = pd.read_parquet(DATA_DIR / f"{ticker.lower()}_features_1999_2026.parquet")
        df = apply_janus5_fixes(raw_df, ticker)
        df = add_mtf_candles(df)
        eval_janus5_bear_candles(df, ticker)
        eval_model_m_fallthrough(df, ticker)


if __name__ == "__main__":
    main()
