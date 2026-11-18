import numpy as np
import pandas as pd
from pathlib import Path
from discover_5pct_models import de_cluster
from finalize_engine_and_ledger import build_final_signals
from audit_5pct_drops_coverage import find_zigzag_swings

DATA_DIR = Path(__file__).resolve().parent / "data"


def eval_mask(df: pd.DataFrame, raw_mask: pd.Series, min_gap: int = 10):
    valid = raw_mask & df["RACE_UP"].notna()
    sig_idx = de_cluster(valid, min_gap=min_gap)
    sig_mask = pd.Series(df.index.isin(sig_idx), index=df.index)
    sub = df.loc[sig_idx].copy()
    is_sub = sub[sub.index.year <= 2019]
    oos_sub = sub[sub.index.year >= 2020]
    return sig_mask, {
        "n_all": len(sub),
        "n_is": len(is_sub),
        "n_oos": len(oos_sub),
        "race_wr_all": float(sub["RACE_UP"].mean() * 100.0) if len(sub) else 0.0,
        "race_wr_is": float(is_sub["RACE_UP"].mean() * 100.0) if len(is_sub) else 0.0,
        "race_wr_oos": float(oos_sub["RACE_UP"].mean() * 100.0) if len(oos_sub) else 0.0,
        "touch60_all": float(sub["TOUCH60_UP"].mean() * 100.0) if len(sub) else 0.0,
        "touch60_is": float(is_sub["TOUCH60_UP"].mean() * 100.0) if len(is_sub) else 0.0,
        "touch60_oos": float(oos_sub["TOUCH60_UP"].mean() * 100.0) if len(oos_sub) else 0.0,
    }


def compute_capture_metrics(df: pd.DataFrame, sig_mask: pd.Series):
    drops, _ = find_zigzag_swings(df["close"], df["high"], df["low"], pct=5.0)
    idx_map = {d: i for i, d in enumerate(df.index)}
    sig_indices = [idx_map[d] for d in df.index[sig_mask] if d in idx_map]

    sma200 = df["close"].rolling(200).mean()
    drops["trough_above_sma200"] = [
        bool(df["close"].iloc[int(r["end_idx"])] > sma200.iloc[int(r["end_idx"])] * 0.94)
        for _, r in drops.iterrows()
    ]
    caught = []
    for _, row in drops.iterrows():
        p_i = int(row["start_idx"])
        t_i = int(row["end_idx"])
        hit = any((s_i >= p_i) and (s_i <= t_i + 15) for s_i in sig_indices)
        caught.append(hit)
    drops["caught"] = caught

    dd63 = (df["close"] / df["high"].rolling(63).max() - 1.0) * 100.0
    in_dd5 = dd63 <= -5.0
    ep_starts = in_dd5 & (~in_dd5.shift(1, fill_value=False))
    ep_indices = []
    last_ep = -999
    for idx_i, flag in enumerate(ep_starts):
        if flag and (idx_i - last_ep >= 20):
            ep_indices.append(idx_i)
            last_ep = idx_i

    ep_is = [i for i in ep_indices if df.index[i].year <= 2019]
    ep_oos = [i for i in ep_indices if df.index[i].year >= 2020]
    ep_caught = [i for i in ep_indices if any(abs(s_i - i) <= 20 for s_i in sig_indices)]
    ep_caught_is = [i for i in ep_is if any(abs(s_i - i) <= 20 for s_i in sig_indices)]
    ep_caught_oos = [i for i in ep_oos if any(abs(s_i - i) <= 20 for s_i in sig_indices)]

    bull_drops = drops[drops["trough_above_sma200"]]
    bear_drops = drops[~drops["trough_above_sma200"]]
    bull_oos = bull_drops[bull_drops["sample"] == "OOS (2020-2026)"]
    bear_oos = bear_drops[bear_drops["sample"] == "OOS (2020-2026)"]

    return {
        "ep_total": len(ep_indices),
        "ep_caught": len(ep_caught),
        "ep_pct": len(ep_caught) / max(len(ep_indices), 1) * 100.0,
        "ep_is_caught": len(ep_caught_is),
        "ep_is_total": len(ep_is),
        "ep_is_pct": len(ep_caught_is) / max(len(ep_is), 1) * 100.0,
        "ep_oos_caught": len(ep_caught_oos),
        "ep_oos_total": len(ep_oos),
        "ep_oos_pct": len(ep_caught_oos) / max(len(ep_oos), 1) * 100.0,
        "zz_total": len(drops),
        "zz_caught": int(drops["caught"].sum()),
        "zz_pct": float(drops["caught"].mean() * 100.0),
        "zz_bull_caught": int(bull_drops["caught"].sum()),
        "zz_bull_total": len(bull_drops),
        "zz_bull_pct": float(bull_drops["caught"].mean() * 100.0),
        "zz_bull_oos_caught": int(bull_oos["caught"].sum()),
        "zz_bull_oos_total": len(bull_oos),
        "zz_bull_oos_pct": float(bull_oos["caught"].mean() * 100.0),
        "zz_bear_caught": int(bear_drops["caught"].sum()),
        "zz_bear_total": len(bear_drops),
        "zz_bear_pct": float(bear_drops["caught"].mean() * 100.0),
        "zz_bear_oos_caught": int(bear_oos["caught"].sum()),
        "zz_bear_oos_total": len(bear_oos),
    }


def main():
    for ticker in ["QQQ", "SPY"]:
        raw_df = pd.read_parquet(DATA_DIR / f"{ticker.lower()}_features_1999_2026.parquet")
        df = build_final_signals(raw_df)

        c = df["close"]
        h = df["high"]
        sma200 = df["sma200"]
        dd63 = (c / h.rolling(63).max() - 1.0) * 100.0
        low5_dd63 = dd63.rolling(5).min()
        no_gas_surge = (df["macro_gas_yoy"] < 14.0) | (df["macro_gas_roc21"] <= 0.5)

        t1_raw = df["SIG_EXPANDED"]

        # Tier 2A: High-Capture Bull/Transitional Pullback (Score >= 13.0, Close > 0.92*SMA200, Pullback >= 3.5% or z20 < -0.6)
        t2a = (
            (c > sma200 * 0.92)
            & (df["sma200_slope21"] > -0.35)
            & (df["pos_in_20d_range"] < 0.45)
            & ((low5_dd63 <= -3.5) | (df["z20"] < -0.75))
            & (df["z20"] < -0.35)
            & (df["rsi5"] < 40.0)
            & (df["TOTAL_BULL_MACRO_SCORE"] >= 13.0)
            & no_gas_surge
            & (df["z252_iv"] > -0.45)
            & ((df["opt_iv_drop_from_5d_high"] < -0.02) | (df["close_loc"] > 0.50) | (df["dp_ovn_21"] > 0.0))
        )

        # Tier 2B: Medium Correction / Transitional Washout (Close > 0.86*SMA200, Credit & NFCI non-crisis, IV flush + turn)
        t2b = (
            (c > sma200 * 0.86)
            & (low5_dd63 <= -5.0)
            & (df["z20"] < -1.00)
            & (df["rsi5"] < 32.0)
            & (df["z252_nfci"] < 0.40)
            & (df["z63_baa_spread"] < 0.45)
            & no_gas_surge
            & (df["z252_iv"] > 0.05)
            & ((df["opt_iv_drop_from_5d_high"] < -0.03) | (df["close_loc"] > 0.55))
        )

        # Tier 2C: Below-SMA200 V-Bottom Capitulation Rebound
        # Extreme oversold washout below SMA200 + Options IV panic spike rolling over + strong intraday buyer absorption + rates/gas not actively spiking
        t2c = (
            (c <= sma200 * 0.96)
            & (low5_dd63 <= -7.5)
            & (df["pos_in_20d_range"] < 0.55)
            & (df["z20"] < -0.75)
            & (df["z252_iv"] > 0.75)
            & (df["opt_iv_drop_from_5d_high"] < -0.05)
            & (df["close_loc"] > 0.55)
            & (c > c.shift(1) * 1.005)
            & (df["rate_dgs10_chg21"] <= 0.15)
            & ((df["macro_gas_roc21"] <= 1.0) | (df["z252_nfci"] < 0.75))
        )

        print(f"================ {ticker} TIERED CONVICTION AUDIT ================")
        for name, mask, gap in [
            ("Tier 1 Only (Sniper 85%+)", t1_raw, 10),
            ("Tier 2A (Bull/Transitional High-Capture)", t2a, 10),
            ("Tier 2B (Medium Correction Washout)", t2b, 10),
            ("Tier 2C (Below-SMA200 V-Bottom Capitulation)", t2c, 10),
            ("Combined Tier 1 + Tier 2 (gap=10)", t1_raw | t2a | t2b | t2c, 10),
            ("Combined Tier 1 + Tier 2 (gap=7)", t1_raw | t2a | t2b | t2c, 7),
        ]:
            declust_mask, stats = eval_mask(df, mask, min_gap=gap)
            cap = compute_capture_metrics(df, declust_mask)
            print(
                f"{name:45s} | N={stats['n_all']:3d} (IS={stats['n_is']:2d}, OOS={stats['n_oos']:2d}) "
                f"| RaceWR: All={stats['race_wr_all']:5.1f}% (IS={stats['race_wr_is']:5.1f}%, OOS={stats['race_wr_oos']:5.1f}%) "
                f"| Touch60: All={stats['touch60_all']:5.1f}% (IS={stats['touch60_is']:5.1f}%, OOS={stats['touch60_oos']:5.1f}%) "
                f"| 63dEpCap: {cap['ep_caught']}/{cap['ep_total']} ({cap['ep_pct']:.1f}%, OOS {cap['ep_oos_caught']}/{cap['ep_oos_total']}={cap['ep_oos_pct']:.1f}%) "
                f"| BullZZ_OOS: {cap['zz_bull_oos_caught']}/{cap['zz_bull_oos_total']} ({cap['zz_bull_oos_pct']:.1f}%) "
                f"| BearZZ: {cap['zz_bear_caught']}/{cap['zz_bear_total']} (OOS {cap['zz_bear_oos_caught']}/{cap['zz_bear_oos_total']})"
            )
        print()


if __name__ == "__main__":
    main()
