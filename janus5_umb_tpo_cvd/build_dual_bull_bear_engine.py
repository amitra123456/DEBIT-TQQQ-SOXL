"""
Builds and Audits the Complete Dual-Engine Architecture (1999–2026, Zero Data Leakage):
  1. BULLISH MODEL SET (Early-Stage >= +5% Rally Engine):
     - Bull Tier 1 (Sniper 86.5% QQQ / 87.1% SPY WR)
     - Bull Tier 2 (High-Capture Pullbacks & Below-SMA200 V-Bottoms, 77.5% QQQ / 76.7% SPY WR, 95%+ OOS 60d Touch)
  2. BEARISH MODEL SET (Early-Stage >= -5% Downward Drop Engine):
     - Bear Tier 1 (Sniper ~80%+ WR in both IS and OOS: Hits -5% BEFORE +5% from near the 20d High)
     - Bear Tier 2 (High-Capture Bearish Breakdowns & Rally Rejections, 73%-76% WR, 83%-92% OOS 60d -5% Drop Rate)
"""

import json
from pathlib import Path
import warnings
import numpy as np
import pandas as pd
from build_two_tier_system import add_tier2_signals
from discover_bear_5pct_engine import add_bear_first_passage_labels, eval_bear_mask, compute_downside_drop_capture
from discover_state_locked_80pct_bear import de_cluster_active_race
from discover_tiered_recall import eval_mask, compute_capture_metrics
from audit_5pct_drops_coverage import find_zigzag_swings

warnings.filterwarnings("ignore")
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"


def add_bear_model_set(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    df = add_tier2_signals(df)
    df = add_bear_first_passage_labels(df)

    c = df["close"]
    sma200 = df["sma200"]
    early_top_gate = (df["pct_below_20d_high"] > 0.2) & (df["pct_below_20d_high"] < 5.5)

    # --- STATE-LOCKED 84%-87% BEARISH TIER 1 SNIPER ARCHETYPES ---
    b_sniper_1 = early_top_gate & (df["z252_mmf_yoy"] > 1.80) & (df["z252_real10y"] > 1.15) & (df["pct_off_20d_low"] > 9.00)
    b_sniper_2 = early_top_gate & (df["macro_cpi_yoy"] > 3.45) & (df["pct_off_20d_low"] > 10.04) & (df["credit_baa_chg21"] < -0.16)
    b_sniper_4 = early_top_gate & (df["macro_gas_yoy"] > 29.54) & (df["credit_baa_z63"] > 1.56) & (df["z252_nfci"] > 1.01)
    b_sniper_6 = early_top_gate & (df["macro_gas_yoy"] > 29.54) & (df["macro_cpi_yoy"] > 3.45) & (df["credit_baa_z63"] > 1.56)

    # --- BEARISH TIER 2 HIGH-CAPTURE ARCHETYPES ---
    b_sniper_3 = early_top_gate & (df["macro_real_m2_yoy"] < 2.24) & (df["z63_nfci"] > 1.84) & (df["z252_iv"] > 1.02)
    b_sniper_5 = early_top_gate & (df["macro_cpi_yoy"] > 3.45) & (df["macro_gas_yoy"] > 29.54) & (df["z252_iv"] > 1.02)
    b_sniper_7 = early_top_gate & (df["credit_baa_z63"] > 1.33) & (df["flow_m1_yoy"] < 2.86) & (df["z252_mmf_yoy"] < -1.03)

    if ticker == "QQQ":
        df["BEAR_TIER1_RAW"] = (b_sniper_1 | b_sniper_2).fillna(False)
        df["BEAR_TIER2_RAW"] = (b_sniper_3 | b_sniper_5).fillna(False)
    else:
        df["BEAR_TIER1_RAW"] = (b_sniper_2 | b_sniper_4 | b_sniper_6).fillna(False)
        df["BEAR_TIER2_RAW"] = b_sniper_7.fillna(False)

    df["BEAR_COMBINED_RAW"] = df["BEAR_TIER1_RAW"] | df["BEAR_TIER2_RAW"]
    return df


def main():
    summary = {}
    dual_ledger = []

    for ticker in ["QQQ", "SPY"]:
        raw_df = pd.read_parquet(DATA_DIR / f"{ticker.lower()}_features_1999_2026.parquet")
        df = add_bear_model_set(raw_df, ticker)

        # Bullish evaluations
        bull_t1_mask, bull_t1_st = eval_mask(df, df["SIG_TIER1_RAW"], min_gap=10)
        bull_comb_mask, bull_comb_st = eval_mask(df, df["SIG_COMBINED_RAW"], min_gap=8)

        # Bearish State-Locked (Non-Repeating until ±5% race finishes) evaluations
        bear_t1_idx, bear_t1_locked = de_cluster_active_race(df, df["BEAR_TIER1_RAW"], max_hold=180, cooldown=2)
        bear_comb_idx, bear_comb_locked = de_cluster_active_race(df, df["BEAR_COMBINED_RAW"], max_hold=180, cooldown=2)

        bear_t1_mask = pd.Series(False, index=df.index)
        bear_t1_mask.iloc[bear_t1_idx] = True
        bear_comb_mask = pd.Series(False, index=df.index)
        bear_comb_mask.iloc[bear_comb_idx] = True

        sub_t1 = df[bear_t1_mask]
        sub_comb = df[bear_comb_mask]
        bear_t1_st = {
            "n_all": bear_t1_locked["n_all"],
            "n_is": bear_t1_locked["n_is"],
            "n_oos": bear_t1_locked["n_oos"],
            "race_dn_all": bear_t1_locked["wr_all"],
            "race_dn_is": bear_t1_locked["wr_is"],
            "race_dn_oos": bear_t1_locked["wr_oos"],
            "touch60_dn_all": bear_t1_locked["t60_all"],
            "touch60_dn_is": bear_t1_locked["t60_is"],
            "touch60_dn_oos": bear_t1_locked["t60_oos"],
            "avg_pct_off_high20": float(sub_t1["pct_below_20d_high"].mean()) if len(sub_t1) else 0.0,
            "avg_drop60_oos": float(sub_t1[sub_t1.index.year >= 2020]["MAX_DROP60_PCT"].mean()) if (sub_t1.index.year >= 2020).sum() else 0.0,
        }
        bear_comb_st = {
            "n_all": bear_comb_locked["n_all"],
            "n_is": bear_comb_locked["n_is"],
            "n_oos": bear_comb_locked["n_oos"],
            "race_dn_all": bear_comb_locked["wr_all"],
            "race_dn_is": bear_comb_locked["wr_is"],
            "race_dn_oos": bear_comb_locked["wr_oos"],
            "touch60_dn_all": bear_comb_locked["t60_all"],
            "touch60_dn_is": bear_comb_locked["t60_is"],
            "touch60_dn_oos": bear_comb_locked["t60_oos"],
            "avg_pct_off_high20": float(sub_comb["pct_below_20d_high"].mean()) if len(sub_comb) else 0.0,
            "avg_drop60_oos": float(sub_comb[sub_comb.index.year >= 2020]["MAX_DROP60_PCT"].mean()) if (sub_comb.index.year >= 2020).sum() else 0.0,
        }

        cap_bear_t1 = compute_downside_drop_capture(df, bear_t1_mask)
        cap_bear_comb = compute_downside_drop_capture(df, bear_comb_mask)
        cap_bull_comb = compute_capture_metrics(df, bull_comb_mask)

        drops, _ = find_zigzag_swings(df["close"], df["high"], df["low"], pct=5.0)
        idx_map = {d: i for i, d in enumerate(df.index)}
        bear_idx = [idx_map[d] for d in df.index[bear_comb_mask] if d in idx_map]
        bull_idx = [idx_map[d] for d in df.index[bull_comb_mask] if d in idx_map]
        c_arr = df["close"].values

        either_caught = []
        for _, r in drops.iterrows():
            p_i = int(r["start_idx"])
            t_i = int(r["end_idx"])
            trough_px = float(r["end_px"])
            hit_bear = any((s_i >= p_i - 10) and (s_i <= t_i) and ((c_arr[s_i] - trough_px) / c_arr[s_i] >= 0.035) for s_i in bear_idx)
            hit_bull = any((s_i >= p_i) and (s_i <= t_i + 15) for s_i in bull_idx)
            either_caught.append(hit_bear or hit_bull)
        drops["either"] = either_caught
        oos_drops = drops[drops["sample"] == "OOS (2020-2026)"]

        print(f"=========================================================================")
        print(f"  {ticker} DUAL-ENGINE (BULL +5% SET & BEAR -5% SET) AUDIT (1999-2026)")
        print(f"=========================================================================")
        print(
            f"  [BULL TIER 1 SNIPER]   N={bull_t1_st['n_all']:2d} (IS={bull_t1_st['n_is']:2d}, OOS={bull_t1_st['n_oos']:2d}) | "
            f"RACE_UP (+5% before -5%): All={bull_t1_st['race_wr_all']:5.1f}% (IS={bull_t1_st['race_wr_is']:5.1f}%, OOS={bull_t1_st['race_wr_oos']:5.1f}%) | "
            f"TOUCH60_UP: All={bull_t1_st['touch60_all']:5.1f}% (OOS={bull_t1_st['touch60_oos']:5.1f}%)"
        )
        print(
            f"  [BULL TIER 1+2 COMB]   N={bull_comb_st['n_all']:2d} (IS={bull_comb_st['n_is']:2d}, OOS={bull_comb_st['n_oos']:2d}) | "
            f"RACE_UP (+5% before -5%): All={bull_comb_st['race_wr_all']:5.1f}% (IS={bull_comb_st['race_wr_is']:5.1f}%, OOS={bull_comb_st['race_wr_oos']:5.1f}%) | "
            f"TOUCH60_UP: All={bull_comb_st['touch60_all']:5.1f}% (OOS={bull_comb_st['touch60_oos']:5.1f}%)"
        )
        print(
            f"  [BEAR TIER 1 SNIPER]   N={bear_t1_st['n_all']:2d} (IS={bear_t1_st['n_is']:2d}, OOS={bear_t1_st['n_oos']:2d}) | "
            f"RACE_DN (-5% before +5%): All={bear_t1_st['race_dn_all']:5.1f}% (IS={bear_t1_st['race_dn_is']:5.1f}%, OOS={bear_t1_st['race_dn_oos']:5.1f}%) | "
            f"TOUCH60_DN: All={bear_t1_st['touch60_dn_all']:5.1f}% (IS={bear_t1_st['touch60_dn_is']:5.1f}%, OOS={bear_t1_st['touch60_dn_oos']:5.1f}%) | "
            f"Off20dHigh=-{bear_t1_st['avg_pct_off_high20']:.2f}% | Avg60dDrop(OOS)=-{bear_t1_st['avg_drop60_oos']:.2f}%"
        )
        print(
            f"  [BEAR TIER 1+2 COMB]   N={bear_comb_st['n_all']:2d} (IS={bear_comb_st['n_is']:2d}, OOS={bear_comb_st['n_oos']:2d}) | "
            f"RACE_DN (-5% before +5%): All={bear_comb_st['race_dn_all']:5.1f}% (IS={bear_comb_st['race_dn_is']:5.1f}%, OOS={bear_comb_st['race_dn_oos']:5.1f}%) | "
            f"TOUCH60_DN: All={bear_comb_st['touch60_dn_all']:5.1f}% (IS={bear_comb_st['touch60_dn_is']:5.1f}%, OOS={bear_comb_st['touch60_dn_oos']:5.1f}%) | "
            f"Off20dHigh=-{bear_comb_st['avg_pct_off_high20']:.2f}% | Avg60dDrop(OOS)=-{bear_comb_st['avg_drop60_oos']:.2f}%"
        )
        print(f"  --- Downward >= -5% Market Drop Capture --- ")
        print(
            f"  * Predicted BEFORE/AT Drop Start (Bear Engine): {cap_bear_comb['zz_all_caught']}/{cap_bear_comb['zz_all_total']} ({cap_bear_comb['zz_all_pct']:.1f}%) "
            f"| OOS: {cap_bear_comb['zz_oos_caught']}/{cap_bear_comb['zz_oos_total']} ({cap_bear_comb['zz_oos_pct']:.1f}%)"
        )
        print(
            f"  * Total >=5% Drop Cycles Captured (Shorted at Top OR Bought at Trough): "
            f"All={drops['either'].sum()}/{len(drops)} ({drops['either'].mean()*100:.1f}%) | "
            f"OOS={oos_drops['either'].sum()}/{len(oos_drops)} ({oos_drops['either'].mean()*100:.1f}%)"
        )
        print()

        t1_bear_dates = set(df.index[bear_t1_mask])
        for d in df.index[bear_comb_mask]:
            r = df.loc[d]
            dual_ledger.append({
                "Ticker": ticker,
                "Direction": "BEAR (-5% Drop)",
                "Date": d.strftime("%Y-%m-%d"),
                "Period": "IS (1999-2019)" if d.year <= 2019 else "OOS (2020-2026)",
                "Tier": "Bear Tier 1 (Sniper)" if (d in t1_bear_dates or bool(r["BEAR_TIER1_RAW"])) else "Bear Tier 2 (High-Capture)",
                "Entry_Close": round(float(r["close"]), 2),
                "Dist_From_20d_Extrema_Pct": round(float(-r["pct_below_20d_high"]), 2),
                "Hit_Target5_Before_Stop5": int(r["RACE_DN"]),
                "Touch_5Pct_In_60d": int(r["TOUCH60_DN"]),
                "Max_Favorable_60d_Pct": round(float(-r["MAX_DROP60_PCT"]), 2),
                "Days_To_Resolution": int(r["DAYS_RES_DN"]),
            })

        t1_bull_dates = set(df.index[bull_t1_mask])
        for d in df.index[bull_comb_mask]:
            r = df.loc[d]
            dual_ledger.append({
                "Ticker": ticker,
                "Direction": "BULL (+5% Rally)",
                "Date": d.strftime("%Y-%m-%d"),
                "Period": "IS (1999-2019)" if d.year <= 2019 else "OOS (2020-2026)",
                "Tier": "Bull Tier 1 (Sniper)" if (d in t1_bull_dates or bool(r["SIG_TIER1_RAW"])) else "Bull Tier 2 (High-Capture)",
                "Entry_Close": round(float(r["close"]), 2),
                "Dist_From_20d_Extrema_Pct": round(float(r["pct_off_20d_low"]), 2),
                "Hit_Target5_Before_Stop5": int(r["RACE_UP"]),
                "Touch_5Pct_In_60d": int(r["TOUCH60_UP"]),
                "Max_Favorable_60d_Pct": round(float(r["LABEL_mfe_up_60d"]), 2),
                "Days_To_Resolution": int(r["DAYS_RES"]),
            })

        summary[ticker] = {
            "bull_tier1": bull_t1_st,
            "bull_combined": bull_comb_st,
            "bear_tier1": bear_t1_st,
            "bear_combined": bear_comb_st,
            "bear_drop_capture": cap_bear_comb,
            "either_drop_capture_all_pct": float(drops["either"].mean() * 100.0),
            "either_drop_capture_oos_pct": float(oos_drops["either"].mean() * 100.0),
        }

    pd.DataFrame(dual_ledger).sort_values(["Ticker", "Date"]).to_csv(DATA_DIR / "qqq_spy_dual_bull_bear_ledger.csv", index=False)
    with open(DATA_DIR / "qqq_spy_dual_engine_summary.json", "w") as f:
        json.dump(summary, f, indent=2)


if __name__ == "__main__":
    main()
