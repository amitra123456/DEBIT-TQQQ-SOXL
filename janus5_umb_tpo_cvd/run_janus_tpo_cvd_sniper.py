"""
Unified Production 2-Layer Sniper Engine (v2 — Post-Audit Hardened Configuration):
  Layer 1: JANUS-5 / UMB Macro Regime + 5d Exhaustion Volume & Flush/Trough FR-VWAP Filter
  Layer 2: Reduced 2-Factor Intraday Execution & Overnight Timing (15:50 TPO Profile + 1m Delta Flow CVD)
=========================================================================================================
Implements the 3 Post-Audit Production Upgrades:
  1. Stricter Layer-2 Conviction Thresholds: PROB_LONG = 0.57, PROB_SHORT = 0.43 (cuts boundary churn).
  2. Turnover-Reduced Multi-Day Swing Continuity + Marketable Limit Order Windows (15:50-15:55 & 09:32-09:35):
     - In Multi-Day Swing Hold mode, holds existing Long/Short while Layer 1 remains valid and Layer 2 stays
       aligned (prob >= 0.50 for held Long, prob <= 0.50 for held Short), charging transaction costs ONLY
       when position changes (actual turnover), preventing daily round-trip spread drag.
  3. Half-Sized SOXL/SOXS Allocation Relative to TQQQ/SQQQ (1.0x TQQQ/SQQQ : 0.5x SOXL/SOXS = 66.7% / 33.3%)
     to equalize realized volatility and cut portfolio tail drawdown.
"""

import sys
from pathlib import Path
import warnings
import numpy as np
import pandas as pd
import statsmodels.api as sm
import yfinance as yf
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline

ROOT = Path("c:/Users/amitr/OneDrive/Documents/ANT_SOX")
sys.path.insert(0, str(ROOT / "research" / "macro_5pct_engine"))

from test_2020_2023_untouched_tpo_cvd_sqqq_soxs import (
    fetch_full_1m_2020_2026,
    build_1550_table,
    compute_tpo_from_slice,
    get_historical_rf_daily,
    compute_metrics,
)

warnings.filterwarnings("ignore")

# Production Hyperparameters (Locked Post-Audit)
PROB_LONG_ENTRY = 0.57
PROB_SHORT_ENTRY = 0.43
PROB_LONG_HOLD = 0.50
PROB_SHORT_HOLD = 0.50
WEIGHT_TQQQ = 2.0 / 3.0  # 1.0x base unit (66.7% of risk budget)
WEIGHT_SOXL = 1.0 / 3.0  # 0.5x half-size unit (33.3% of risk budget)


def add_layer1_macro_frvwap_features(df_bull: pd.DataFrame, df_und: pd.DataFrame) -> pd.DataFrame:
    """
    Computes Layer 1 (Macro & Swing Regime Filter + 5d Exhaustion Volume + Flush/Trough FR-VWAP)
    using strictly causal data known by 15:50 on day t.
    """
    df = df_bull.copy()
    u_c = df_und["px_1550"].reindex(df.index)

    sma50 = u_c.rolling(50, min_periods=20).mean()
    sma200 = u_c.rolling(200, min_periods=50).mean()
    sma200_slope21 = sma200.pct_change(21).fillna(0.0) * 100.0

    low5 = u_c.rolling(5, min_periods=1).min()
    high20 = u_c.rolling(20, min_periods=5).max()
    low20 = u_c.rolling(20, min_periods=5).min()
    pos20 = (u_c - low20) / (high20 - low20 + 1e-6)
    flush_vwap5 = u_c.rolling(5, min_periods=1).mean()
    trough_reclaim = (u_c >= low5 * 1.01) & (df["clv_1550"] >= 0.50)

    bull_trend_ok = (u_c >= sma200 * 0.985) | ((sma200_slope21 > 0.0) & (u_c >= sma50))
    real_bounce_ok = ((u_c >= flush_vwap5 * 0.995) | trough_reclaim) & (df_und["cvd_pm_1550"].reindex(df.index) > 0.0)
    df["layer1_allow_long"] = (bull_trend_ok | real_bounce_ok).astype(bool)

    bear_regime_ok = (u_c < sma50) | (u_c < sma200) | (pos20 < 0.55)
    overext_top_ok = (df["poc_dist_1550"] > 1.5) & (df["cvd_day_1550"] < 0.0)
    df["layer1_allow_short"] = (bear_regime_ok | overext_top_ok).astype(bool)
    return df


def run_2layer_backtest():
    print("=" * 130)
    print("PRODUCTION 2-LAYER SNIPER ENGINE (0.57/0.43 THRESHOLD + TURNOVER-REDUCED SWING HOLD + 2:1 TQQQ:SOXL SIZING)")
    print("=" * 130)

    syms = ["QQQ", "TQQQ", "SQQQ", "SOXX", "SOXL", "SOXS"]
    bars = {s: fetch_full_1m_2020_2026(s) for s in syms}
    tables = {s: build_1550_table(bars[s], s) for s in syms}

    feat_2factor = [
        "clv_1550",
        "poc_dist_1550",
        "above_vah_1550",
        "below_val_1550",
        "btail_1550",
        "stail_1550",
        "cvd_day_1550",
        "cvd_pm_1550",
        "und_cvd_pm_1550",
    ]

    results_by_pair = {}
    live_models = {}

    for bull_etf, bear_etf, und_etf, cost_1x in [
        ("TQQQ", "SQQQ", "QQQ", 6.0),
        ("SOXL", "SOXS", "SOXX", 10.0),
    ]:
        df = add_layer1_macro_frvwap_features(tables[bull_etf], tables[und_etf])
        u_df = tables[und_etf].reindex(df.index)
        inv_df = tables[bear_etf].reindex(df.index)

        df["und_cvd_pm_1550"] = u_df["cvd_pm_1550"]
        df["inv_ret_24h_1550"] = inv_df["ret_24h_1550"]
        df["inv_ret_ovn_1550"] = inv_df["ret_ovn_1550"]
        df_valid = df.dropna(
            subset=feat_2factor + ["ret_24h_1550", "inv_ret_24h_1550", "ret_ovn_1550", "inv_ret_ovn_1550"]
        ).copy()

        rf_s = get_historical_rf_daily(df_valid.index)
        X_all = df_valid[feat_2factor].values
        min_train = 126
        refit_step = 21

        def sim_engine(ret_bull_col, ret_bear_col, cost_rt_bps, p_hi=PROB_LONG_ENTRY, p_lo=PROB_SHORT_ENTRY, multi_day_hold=False):
            y_all = (df_valid[ret_bull_col].values > 0.0).astype(int)
            r_bull = df_valid[ret_bull_col].values
            r_bear = df_valid[ret_bear_col].values
            allow_l = df_valid["layer1_allow_long"].values
            allow_s = df_valid["layer1_allow_short"].values
            rf_v = rf_s.values
            half_turn_cost = (cost_rt_bps / 2.0) / 10000.0
            rt_cost = cost_rt_bps / 10000.0
            n = len(df_valid)
            pos = np.zeros(n)
            probs = np.full(n, np.nan)
            clf = None

            for t in range(min_train, n):
                if clf is None or ((t - min_train) % refit_step == 0):
                    clf = make_pipeline(StandardScaler(), LogisticRegression(C=0.20))
                    clf.fit(X_all[: t - 1], y_all[: t - 1])
                p = clf.predict_proba(X_all[t : t + 1])[0, 1]
                probs[t] = p

                if not multi_day_hold:
                    if p >= p_hi and allow_l[t]:
                        pos[t] = 1.0
                    elif p <= p_lo and allow_s[t]:
                        pos[t] = -1.0
                else:
                    prev_p = pos[t - 1]
                    if prev_p == 1.0 and allow_l[t] and p >= PROB_LONG_HOLD:
                        pos[t] = 1.0
                    elif prev_p == -1.0 and allow_s[t] and p <= PROB_SHORT_HOLD:
                        pos[t] = -1.0
                    elif p >= p_hi and allow_l[t]:
                        pos[t] = 1.0
                    elif p <= p_lo and allow_s[t]:
                        pos[t] = -1.0

            pos_s = pos[min_train:]
            r_b_s = r_bull[min_train:]
            r_s_s = r_bear[min_train:]
            rf_sub = rf_v[min_train:]

            if not multi_day_hold:
                # Overnight hold enters at 15:50 and exits at 09:30 every active day (pays full RT cost each trade)
                net_ret = np.where(pos_s == 1.0, r_b_s - rt_cost, np.where(pos_s == -1.0, r_s_s - rt_cost, rf_sub))
                ann_half_turns = (np.abs(pos_s) * 2.0).sum() * (252.0 / len(pos_s))
            else:
                # Multi-day 24h swing hold only pays half-turn cost when position changes!
                half_turns = np.abs(np.diff(pos_s, prepend=0.0))
                gross_ret = np.where(pos_s == 1.0, r_b_s, np.where(pos_s == -1.0, r_s_s, rf_sub))
                net_ret = gross_ret - half_turns * half_turn_cost
                ann_half_turns = half_turns.sum() * (252.0 / len(pos_s))

            out = pd.DataFrame(
                {"pos": pos_s, "prob": probs[min_train:], "strat_ret": net_ret},
                index=df_valid.index[min_train:],
            )
            out.attrs["ann_rt_trades"] = ann_half_turns / 2.0
            out.attrs["clf"] = clf
            return out

        ovn_1x = sim_engine("ret_ovn_1550", "inv_ret_ovn_1550", cost_1x, PROB_LONG_ENTRY, PROB_SHORT_ENTRY, False)
        ovn_2x = sim_engine("ret_ovn_1550", "inv_ret_ovn_1550", cost_1x * 2, PROB_LONG_ENTRY, PROB_SHORT_ENTRY, False)
        ovn_3x = sim_engine("ret_ovn_1550", "inv_ret_ovn_1550", cost_1x * 3, PROB_LONG_ENTRY, PROB_SHORT_ENTRY, False)

        swg_1x = sim_engine("ret_24h_1550", "inv_ret_24h_1550", cost_1x, PROB_LONG_ENTRY, PROB_SHORT_ENTRY, True)
        swg_2x = sim_engine("ret_24h_1550", "inv_ret_24h_1550", cost_1x * 2, PROB_LONG_ENTRY, PROB_SHORT_ENTRY, True)
        swg_3x = sim_engine("ret_24h_1550", "inv_ret_24h_1550", cost_1x * 3, PROB_LONG_ENTRY, PROB_SHORT_ENTRY, True)

        results_by_pair[bull_etf] = {
            "bmk": df_valid.loc[ovn_1x.index, "ret_24h_1550"],
            "ovn_1x": ovn_1x,
            "ovn_2x": ovn_2x,
            "ovn_3x": ovn_3x,
            "swg_1x": swg_1x,
            "swg_2x": swg_2x,
            "swg_3x": swg_3x,
        }
        live_models[bull_etf] = (ovn_1x.attrs["clf"], swg_1x.attrs["clf"], df.iloc[-1])

        idx = ovn_1x.index
        bmk = results_by_pair[bull_etf]["bmk"]
        print(f"\n=========================================================================================================")
        print(f"  {bull_etf} / {bear_etf} (Underlying: {und_etf}) — HARDENED 0.57/0.43 RESULTS (Jul 2020 - Nov 2026, {len(idx)} Days)")
        print(f"  [Turnover]: Overnight Mode = {ovn_1x.attrs['ann_rt_trades']:.0f} RT/yr | Multi-Day Swing Mode = {swg_1x.attrs['ann_rt_trades']:.0f} RT/yr")
        print(f"=========================================================================================================")
        print(f"  {'Strategy Variant':58s} | {'CAGR%':>7s} | {'MaxDD%':>7s} | {'Sharpe':>6s} | {'Beta':>5s} | {'Alpha%':>7s} | {'t-stat':>6s} | {'WorstMo':>8s} | {'MaxUW':>5s}")
        print("  " + "-" * 130)
        for lbl, s_r in [
            (f"1. Benchmark: Buy & Hold {bull_etf} (24h)", bmk),
            ("2. 2-Layer Overnight (0.57/0.43, Limit 1x Cost)", ovn_1x["strat_ret"]),
            ("3. 2-Layer Overnight (0.57/0.43, 2x Cost)", ovn_2x["strat_ret"]),
            ("4. 2-Layer Overnight (0.57/0.43, 3x Cost)", ovn_3x["strat_ret"]),
            ("5. 2-Layer Multi-Day Swing Hold (0.57/0.43, 1x Cost)", swg_1x["strat_ret"]),
            ("6. 2-Layer Multi-Day Swing Hold (0.57/0.43, 2x Cost)", swg_2x["strat_ret"]),
            ("7. 2-Layer Multi-Day Swing Hold (0.57/0.43, 3x Cost)", swg_3x["strat_ret"]),
        ]:
            m = compute_metrics(s_r, bmk)
            print(
                f"  {lbl:58s} | {m['cagr']:+6.1f}% | {m['max_dd']:+6.1f}% | {m['sharpe']:6.2f} | "
                f"{m['beta']:5.2f} | {m['alpha']:+6.1f}% | {m['t']:+6.2f} | {m['worst_mo']:+7.2f}% | {m['max_uw']:4d}d"
            )

    # =========================================================================
    # COMBINED PORTFOLIO: 66.7% TQQQ/SQQQ (1.0x) + 33.3% SOXL/SOXS (0.5x Half-Size)
    # =========================================================================
    t_res = results_by_pair["TQQQ"]
    s_res = results_by_pair["SOXL"]
    c_idx = t_res["ovn_1x"].index.intersection(s_res["ovn_1x"].index)

    bmk_port = WEIGHT_TQQQ * t_res["bmk"].loc[c_idx] + WEIGHT_SOXL * s_res["bmk"].loc[c_idx]
    port_ovn_1x = WEIGHT_TQQQ * t_res["ovn_1x"].loc[c_idx, "strat_ret"] + WEIGHT_SOXL * s_res["ovn_1x"].loc[c_idx, "strat_ret"]
    port_ovn_2x = WEIGHT_TQQQ * t_res["ovn_2x"].loc[c_idx, "strat_ret"] + WEIGHT_SOXL * s_res["ovn_2x"].loc[c_idx, "strat_ret"]
    port_ovn_3x = WEIGHT_TQQQ * t_res["ovn_3x"].loc[c_idx, "strat_ret"] + WEIGHT_SOXL * s_res["ovn_3x"].loc[c_idx, "strat_ret"]

    port_swg_1x = WEIGHT_TQQQ * t_res["swg_1x"].loc[c_idx, "strat_ret"] + WEIGHT_SOXL * s_res["swg_1x"].loc[c_idx, "strat_ret"]
    port_swg_2x = WEIGHT_TQQQ * t_res["swg_2x"].loc[c_idx, "strat_ret"] + WEIGHT_SOXL * s_res["swg_2x"].loc[c_idx, "strat_ret"]
    port_swg_3x = WEIGHT_TQQQ * t_res["swg_3x"].loc[c_idx, "strat_ret"] + WEIGHT_SOXL * s_res["swg_3x"].loc[c_idx, "strat_ret"]

    # 50/50 Blend of Overnight Harvest + Multi-Day Swing Continuity
    port_hybrid_1x = 0.50 * port_ovn_1x + 0.50 * port_swg_1x
    port_hybrid_2x = 0.50 * port_ovn_2x + 0.50 * port_swg_2x
    port_hybrid_3x = 0.50 * port_ovn_3x + 0.50 * port_swg_3x

    print(f"\n=========================================================================================================")
    print(f"  COMBINED PORTFOLIO: 66.7% TQQQ/SQQQ (1.0x) + 33.3% SOXL/SOXS (0.5x Half-Size) | Jul 2020 - Nov 2026")
    print(f"=========================================================================================================")
    print(f"  {'Portfolio Strategy':58s} | {'CAGR%':>7s} | {'MaxDD%':>7s} | {'Sharpe':>6s} | {'Beta':>5s} | {'Alpha%':>7s} | {'t-stat':>6s} | {'WorstMo':>8s} | {'MaxUW':>5s}")
    print("  " + "-" * 130)
    for lbl, s_r in [
        ("1. Benchmark: 67% TQQQ + 33% SOXL Buy & Hold", bmk_port),
        ("2. Combined 2-Layer Overnight (0.57/0.43, 1x Cost)", port_ovn_1x),
        ("3. Combined 2-Layer Overnight (0.57/0.43, 2x Cost)", port_ovn_2x),
        ("4. Combined 2-Layer Overnight (0.57/0.43, 3x Cost)", port_ovn_3x),
        ("5. Combined 2-Layer Multi-Day Swing (0.57/0.43, 1x Cost)", port_swg_1x),
        ("6. Combined 2-Layer Multi-Day Swing (0.57/0.43, 2x Cost)", port_swg_2x),
        ("7. Combined 2-Layer Multi-Day Swing (0.57/0.43, 3x Cost)", port_swg_3x),
        ("8. Combined Hybrid (50% Ovn + 50% Swing, 1x Cost)", port_hybrid_1x),
        ("9. Combined Hybrid (50% Ovn + 50% Swing, 2x Cost)", port_hybrid_2x),
        ("10. Combined Hybrid (50% Ovn + 50% Swing, 3x Cost)", port_hybrid_3x),
    ]:
        m = compute_metrics(s_r, bmk_port)
        print(
            f"  {lbl:58s} | {m['cagr']:+6.1f}% | {m['max_dd']:+6.1f}% | {m['sharpe']:6.2f} | "
            f"{m['beta']:5.2f} | {m['alpha']:+6.1f}% | {m['t']:+6.2f} | {m['worst_mo']:+7.2f}% | {m['max_uw']:4d}d"
        )


if __name__ == "__main__":
    run_2layer_backtest()
