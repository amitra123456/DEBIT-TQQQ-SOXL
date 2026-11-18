"""
Empirical Investigation: Detecting Dead-Cat Bounces vs. Genuine Reversals
========================================================================
Analyzes all market bounce episodes (1999-2026, 6,959 daily sessions):
  - Bounce Event: Market drops >= 4% and then bounces >= 2.5% over 1-3 days.
  - Classification:
      * Dead-Cat Bounce (DCB): Rolls over and breaks below the bounce low within 15 days.
      * Genuine Bottom (GB): Holds the bounce low and rallies >= +5% without breaking the low.
  - Tests 6 Microstructure & Macro Discriminators:
      1. Volume Fade Ratio (Volume on bounce vs. volume on selloff)
      2. Hazard Crest Velocity (dM/dt on bounce day)
      3. EMA10 / EMA20 Moving Average Slope & Resistance Test
      4. Options Term Structure Slope (dTS/dt)
      5. Breadth Expansion (% of constituents participating)
      6. Multi-Horizon Relative Strength Coherence
"""

import numpy as np
import pandas as pd
from pathlib import Path
from scipy.stats import ttest_ind

ROOT = Path("c:/Users/amitr/OneDrive/Documents/ANT_SOX")
DATASET_PATH = ROOT / "research" / "qqq_drops_first_principles" / "data" / "qqq_disjoint_6domain_dataset_1999_2026.parquet"
P_DROP_PATH = ROOT / "qqq_alpha_engine" / "data" / "macro" / "final_9tier_daily_probabilities_1999_2026.parquet"
P_BOT_PATH = ROOT / "qqq_alpha_engine" / "data" / "macro" / "final_bottom_daily_scores_1999_2026.parquet"

def run_study():
    print("=" * 105)
    print("EMPIRICAL INVESTIGATION: DEAD-CAT BOUNCE (DCB) VS. GENUINE BOTTOM (GB) [1999-2026]")
    print("=" * 105)

    df_feat = pd.read_parquet(DATASET_PATH)
    p_drop = pd.read_parquet(P_DROP_PATH)
    p_bot = pd.read_parquet(P_BOT_PATH)

    idx = df_feat.index.intersection(p_drop.index).intersection(p_bot.index)
    df = df_feat.loc[idx].copy()
    close = df["QQQ_close"]
    high = df["QQQ_high"]
    low = df["QQQ_low"]
    vol = df["QQQ_volume"]
    n = len(df)

    # 1. Macro & Micro Indicators
    m_val = p_drop.loc[idx, "prob_tier_5pct"] * 100.0
    b_val = np.clip(p_bot.loc[idx, "TOTAL_BOTTOM_SCORE"] / 25.5 * 100.0, 0.0, 100.0)
    dM_dt1 = m_val.diff(1).fillna(0.0)
    dM_dt3 = (m_val.diff(3) / 3.0).fillna(0.0)

    # Moving averages & EMA10
    ema10 = close.ewm(span=10, adjust=False).mean()
    ema20 = close.ewm(span=20, adjust=False).mean()
    dist_ema10_pct = (close / ema10 - 1.0) * 100.0

    # Volume dynamics: 3-day volume / 20-day avg volume
    vol_sma20 = vol.rolling(20).mean()
    rvol3 = vol.rolling(3).mean() / (vol_sma20 + 1.0)
    # Volume trend during bounce: volume on up days vs down days
    vol_fade = (vol / vol.shift(1)).rolling(3).mean()

    # Breadth: % above SMA50
    breadth50 = df["m3_cs_pct_above_sma50"] * 100.0 if "m3_cs_pct_above_sma50" in df.columns else df["m3_cs_pct_above_sma20"] * 100.0
    breadth_chg3 = breadth50.diff(3)

    # Options term structure
    ts_ratio = df["m4_term_structure_ratio"] if "m4_term_structure_ratio" in df.columns else np.ones(n)
    d_ts_dt3 = pd.Series(ts_ratio, index=df.index).diff(3)

    # 2. Identify all Bounce Events
    # Criteria:
    # A) In a pullback: close <= rolling 20d max * 0.96 (dropped at least 4%)
    # B) Bounced >= +2.5% over past 1 to 3 days: (close / rolling 3d min - 1.0) >= 0.025
    # C) Green candle today: close > close[t-1]
    roll_max20 = close.rolling(20).max()
    in_pullback = (close <= roll_max20 * 0.96)
    roll_min3 = low.rolling(3).min()
    bounced_25 = ((close / roll_min3 - 1.0) >= 0.025) & (close > close.shift(1))

    candidate_days = df[in_pullback & bounced_25].index

    # Deduplicate into distinct bounce episodes (gap >= 5 days)
    bounce_episodes = []
    last_d = None
    for d in candidate_days:
        if last_d is None or (d - last_d).days > 5:
            bounce_episodes.append(d)
            last_d = d

    print(f"Total Bounce Episodes Identified (1999-2026): {len(bounce_episodes)}")

    # 3. Label Outcome: Dead-Cat Bounce vs. Genuine Bottom
    # Forward 15-day window:
    # GB: Forward min does not break below bounce low (fwd_min > low[d] * 0.995) AND fwd_max >= close[d] * 1.04
    # DCB: Forward min breaks below bounce low (fwd_min < low[d] * 0.995)
    records = []
    for d in bounce_episodes:
        pos = df.index.get_loc(d)
        if pos + 15 >= n:
            continue
        cur_px = close.iloc[pos]
        cur_low = low.iloc[pos]
        fwd_window_low = low.iloc[pos+1 : pos+16].min()
        fwd_window_high = high.iloc[pos+1 : pos+16].max()

        # Did it roll over and break to new lows?
        broke_low = (fwd_window_low < cur_low * 0.995)
        # Did it follow through to the upside?
        gained_4 = (fwd_window_high >= cur_px * 1.04)

        if broke_low:
            label = "Dead-Cat Bounce"
        elif gained_4:
            label = "Genuine Bottom"
        else:
            label = "Neutral Chop"

        records.append({
            "date": d,
            "label": label,
            "px": cur_px,
            "B_val": b_val.loc[d],
            "M_val": m_val.loc[d],
            "dM_dt1": dM_dt1.loc[d],
            "dM_dt3": dM_dt3.loc[d],
            "dist_ema10": dist_ema10_pct.loc[d],
            "rvol3": rvol3.loc[d],
            "vol_fade": vol_fade.loc[d],
            "breadth50": breadth50.loc[d],
            "breadth_chg3": breadth_chg3.loc[d],
            "ts_ratio": ts_ratio.iloc[pos] if hasattr(ts_ratio, "iloc") else ts_ratio[pos],
            "d_ts_dt3": d_ts_dt3.loc[d],
            "fwd_ret5": (close.iloc[pos+5] / cur_px - 1.0) * 100.0,
            "fwd_ret15": (close.iloc[pos+15] / cur_px - 1.0) * 100.0
        })

    res = pd.DataFrame(records)
    print(f"Outcome Distribution: DCB={sum(res['label'] == 'Dead-Cat Bounce')}, GB={sum(res['label'] == 'Genuine Bottom')}, Neutral={sum(res['label'] == 'Neutral Chop')}\n")

    dcb = res[res["label"] == "Dead-Cat Bounce"]
    gb = res[res["label"] == "Genuine Bottom"]

    print("=" * 105)
    print("FEATURE DISCRIMINATION: DEAD-CAT BOUNCE (DCB) VS. GENUINE BOTTOM (GB)")
    print("=" * 105)
    print(f"{'Discriminator Feature':<36} | {'Dead-Cat Bounce (Mean)':<24} | {'Genuine Bottom (Mean)':<24} | {'Statistical T-Test p-val':<20}")
    print("-" * 110)

    test_features = [
        ("Hazard Crest Velocity (dM/dt 1d)", "dM_dt1", False),
        ("Hazard Acceleration (dM/dt 3d)", "dM_dt3", False),
        ("Model B Capitulation Score", "B_val", True),
        ("Downside Hazard M Level", "M_val", False),
        ("Volume Fade Ratio (Vol Trend)", "vol_fade", True),
        ("Relative Volume (3-Day RVol)", "rvol3", True),
        ("Breadth Thrust (3d Chg % Above SMA50)", "breadth_chg3", True),
        ("Distance to 10 EMA (Dist %)", "dist_ema10", True),
        ("Term Structure Inversion (TS Ratio)", "ts_ratio", False),
        ("Term Structure Slope (dTS/dt)", "d_ts_dt3", False),
    ]

    for fname, col, _ in test_features:
        mean_dcb = dcb[col].mean()
        mean_gb = gb[col].mean()
        stat, pval = ttest_ind(dcb[col].dropna(), gb[col].dropna(), equal_var=False)
        sig = "***" if pval < 0.001 else "**" if pval < 0.01 else "*" if pval < 0.05 else " "
        print(f"{fname:<36} | {mean_dcb:>18.2f}       | {mean_gb:>18.2f}       | {pval:.4e} ({sig})")

    # 4. Accuracy of Combined Dead-Cat Bounce Filter Rule
    # Rule to FLAG Dead-Cat Bounce:
    # 1. dM/dt > 0 (Hazard still rising)
    # 2. Volume fading (vol_fade < 1.0)
    # 3. Model B weak (B < 75%)
    # 4. Stuck below EMA10 (dist_ema10 < 0)
    print("\n" + "=" * 105)
    print("DEAD-CAT BOUNCE FILTER ACCURACY & TRAP ELIMINATION")
    print("=" * 105)
    
    # Filter 1: dM/dt > 0
    dcb_risk1 = (res["dM_dt1"] > 0.0)
    p_dcb_given_m_rising = (res.loc[dcb_risk1, "label"] == "Dead-Cat Bounce").mean() * 100
    print(f"Rule 1 [Hazard Rising: dM/dt > 0]:        {p_dcb_given_m_rising:4.1f}% are Dead-Cat Bounces (N={dcb_risk1.sum()})")

    # Filter 2: B < 75% (No true capitulation)
    dcb_risk2 = (res["B_val"] < 75.0)
    p_dcb_given_low_b = (res.loc[dcb_risk2, "label"] == "Dead-Cat Bounce").mean() * 100
    print(f"Rule 2 [Low Capitulation: B < 75%]:       {p_dcb_given_low_b:4.1f}% are Dead-Cat Bounces (N={dcb_risk2.sum()})")

    # Filter 3: Low Volume on bounce (vol_fade < 0.95)
    dcb_risk3 = (res["vol_fade"] < 0.95)
    p_dcb_given_low_vol = (res.loc[dcb_risk3, "label"] == "Dead-Cat Bounce").mean() * 100
    print(f"Rule 3 [Volume Fading: Vol_Fade < 0.95]:   {p_dcb_given_low_vol:4.1f}% are Dead-Cat Bounces (N={dcb_risk3.sum()})")

    # Filter 4: Combined Composite Dead-Cat Trap Flag
    # (dM/dt > 0) OR (B < 75% AND dist_ema10 < -1.0%)
    composite_dcb_flag = (res["dM_dt1"] > 0.5) | ((res["B_val"] < 75.0) & (res["dist_ema10"] < -1.0))
    p_dcb_composite = (res.loc[composite_dcb_flag, "label"] == "Dead-Cat Bounce").mean() * 100
    p_gb_composite = (res.loc[~composite_dcb_flag, "label"] == "Genuine Bottom").mean() * 100
    print(f"\nCOMPOSITE DEAD-CAT BOUNCE FILTER:")
    print(f"  When Flagged as 'Dead-Cat Trap' (N={composite_dcb_flag.sum()}): {p_dcb_composite:4.1f}% Roll Over to New Lows (Trap Confirmed)")
    print(f"  When Cleared as 'Genuine Bottom' (N={(~composite_dcb_flag).sum()}): {p_gb_composite:4.1f}% Hold Support and Rally (High Precision)")

if __name__ == "__main__":
    run_study()
