import sys
from pathlib import Path
import pandas as pd
import numpy as np

# Load datasets
p_df = pd.read_parquet("qqq_alpha_engine/data/macro/final_9tier_daily_probabilities_1999_2026.parquet")
b_df = pd.read_parquet("qqq_alpha_engine/data/macro/final_bottom_daily_scores_1999_2026.parquet")
d_df = pd.read_parquet("research/qqq_drops_first_principles/data/qqq_disjoint_6domain_dataset_1999_2026.parquet")

common_idx = p_df.index.intersection(b_df.index).intersection(d_df.index)
p_df = p_df.loc[common_idx]
b_df = b_df.loc[common_idx]
d_df = d_df.loc[common_idx]

qqq_close = p_df["QQQ_close"].values
q_ret = p_df["QQQ_close"].pct_change().fillna(0.0).values
n = len(common_idx)

# TQQQ returns
synth_tqqq = 3.0 * q_ret - (0.0095 / 252.0)
tqqq_file = Path("data/historical/TQQQ_1d.parquet")
if tqqq_file.exists():
    t_df = pd.read_parquet(tqqq_file)
    act_t = t_df["close"].reindex(common_idx).pct_change().values
    tqqq_ret = np.where(~np.isnan(act_t), act_t, synth_tqqq)
else:
    tqqq_ret = synth_tqqq

# Signals (Point-in-Time, t-1 close dictates t action)
sig_m_raw = ((p_df["sig_tier_5pct"] == 1) | (p_df["sig_tier_8pct"] == 1)).values
prob_m = p_df["prob_tier_5pct"].values
term_ratio = d_df["m4_term_structure_ratio"].values

sig_sniper = (b_df["SIG_BOTTOM_SNIPER_RAW"] == 1).values
sig_broad = (b_df["SIG_BOTTOM_BROAD_RAW"] == 1).values
sig_bottom = (sig_sniper | sig_broad)

# Model U Resilience Score
s_qqq = pd.Series(qqq_close, index=common_idx)
sma50 = s_qqq.rolling(50, min_periods=1).mean().values
sma200 = s_qqq.rolling(200, min_periods=1).mean().values
golden_spread = (sma50 / sma200 - 1.0) * 100.0
dist_200 = (qqq_close / sma200 - 1.0) * 100.0
slope_200 = s_qqq.rolling(200).mean().pct_change(21).fillna(0.0).values * 100.0
breadth_200 = d_df["m3_cs_pct_above_sma200"].values * 100.0
vol_buffer = (1.0 - term_ratio) * 100.0

s_altitude = np.clip((golden_spread + dist_200 + 10.0) / 25.0 * 100.0, 0.0, 100.0)
s_slope = np.clip((slope_200 + 2.0) / 4.0 * 100.0, 0.0, 100.0)
s_breadth = np.clip(breadth_200, 0.0, 100.0)
s_vol = np.clip((vol_buffer + 15.0) / 30.0 * 100.0, 0.0, 100.0)
u_raw = 0.35 * s_altitude + 0.20 * s_slope + 0.25 * s_breadth + 0.20 * s_vol
u_resilience = pd.Series(u_raw, index=common_idx).rolling(3, min_periods=1).mean().values

# Cash yield (SGOV ~3% annualized)
rf_daily = 0.03 / 252.0

def run_simulation(model_mode: str):
    """
    Simulates with EXACT production rules of FpDcteCashShield:
    - Cash Exit:
        In FP: sig_m_raw[i-1] == True
        In UMB: sig_m_raw[i-1] == True AND NOT (u_resilience[i-1] >= 52.0 and prob_m[i-1] < 0.85 and term_ratio[i-1] < 1.0)
    - Cash Re-entry (3 Deterministic Rules):
        1. Target -5.0% Drop Realized from cash entry
        2. FP-DCTE Bottom Arrival Signal (sig_bottom[i-1] == True)
        3. 20-Day Timeout (days_in_cash >= 20)
    - Tactical 15% TQQQ Booster:
        Active when re-entering on sig_bottom or when sig_bottom fires in equities.
        Takes profit at +5.0% QQQ gain.
    """
    daily_returns = np.zeros(n)
    in_cash = False
    cash_entry_px = 0.0
    cash_days = 0
    tqqq_active = False
    tqqq_entry_px = 0.0
    
    cash_events = 0
    whipsaws_vetoed = 0
    tqqq_trades = 0
    tqqq_wins = 0
    
    for i in range(1, n):
        if not in_cash:
            exit_flag = False
            if sig_m_raw[i-1]:
                if model_mode == "FP_CURRENT":
                    exit_flag = True
                elif model_mode == "TRI_ENGINE_UMB":
                    # Hierarchical rule:
                    is_emergency = (prob_m[i-1] >= 0.85) or (term_ratio[i-1] >= 1.0)
                    if is_emergency:
                        exit_flag = True
                    elif u_resilience[i-1] >= 52.0:
                        exit_flag = False
                        whipsaws_vetoed += 1
                    else:
                        exit_flag = True
                        
            if exit_flag:
                in_cash = True
                cash_entry_px = qqq_close[i]
                cash_days = 1
                cash_events += 1
                tqqq_active = False
                daily_returns[i] = rf_daily
                continue
            else:
                pass
        else:
            cash_days += 1
            current_drop_from_cash_entry = (qqq_close[i] / cash_entry_px - 1.0) * 100.0
            
            # 3 Deterministic Exit Rules:
            rule1_target_hit = current_drop_from_cash_entry <= -5.0
            rule2_bottom_fired = sig_bottom[i-1]
            rule3_timeout_hit = cash_days >= 20
            
            if rule1_target_hit or rule2_bottom_fired or rule3_timeout_hit:
                in_cash = False
                if rule2_bottom_fired:
                    tqqq_active = True
                    tqqq_entry_px = qqq_close[i]
                    tqqq_trades += 1
                    daily_returns[i] = 0.85 * q_ret[i] + 0.15 * tqqq_ret[i]
                else:
                    tqqq_active = False
                    daily_returns[i] = q_ret[i]
                continue
            else:
                daily_returns[i] = rf_daily
                continue
                
        # Outside Cash Shield (100% Invested in Equities)
        if tqqq_active:
            q_gain = (qqq_close[i] / tqqq_entry_px - 1.0) * 100.0
            if q_gain >= 5.0:
                tqqq_active = False
                tqqq_wins += 1
            elif q_gain <= -5.0:
                tqqq_active = False
            daily_returns[i] = 0.85 * q_ret[i] + 0.15 * tqqq_ret[i]
        else:
            if sig_bottom[i-1]:
                tqqq_active = True
                tqqq_entry_px = qqq_close[i]
                tqqq_trades += 1
                daily_returns[i] = 0.85 * q_ret[i] + 0.15 * tqqq_ret[i]
            else:
                daily_returns[i] = q_ret[i]
                
    return daily_returns, cash_events, whipsaws_vetoed, tqqq_trades, tqqq_wins

def calc_stats(ret_series):
    cum = float(np.prod(1.0 + ret_series) - 1.0) * 100.0
    n_days = len(ret_series)
    cagr = float((np.prod(1.0 + ret_series) ** (252.0 / max(1, n_days)) - 1.0) * 100.0)
    vol = float(np.std(ret_series) * np.sqrt(252.0)) * 100.0
    eq = np.cumprod(1.0 + ret_series)
    pk = np.maximum.accumulate(eq)
    dd = float(np.min((eq - pk) / pk)) * 100.0
    rf = 0.02
    excess = ret_series - rf / 252.0
    sharpe = float(np.mean(excess) / np.std(ret_series) * np.sqrt(252.0)) if np.std(ret_series) > 0 else 0.0
    downside = np.minimum(excess, 0.0)
    downside_vol = float(np.sqrt(np.mean(downside ** 2)) * np.sqrt(252.0))
    sortino = float(np.mean(excess) * 252.0 / downside_vol) if downside_vol > 0 else 0.0
    calmar = float(cagr / abs(dd)) if abs(dd) > 0 else 0.0
    return {
        "cum_return_pct": round(cum, 2),
        "cagr_pct": round(cagr, 2),
        "ann_vol_pct": round(vol, 2),
        "max_drawdown_pct": round(dd, 2),
        "sharpe": round(sharpe, 2),
        "sortino": round(sortino, 2),
        "calmar": round(calmar, 3)
    }

# Run simulations
r_fp, c_fp, _, t_fp, w_fp = run_simulation("FP_CURRENT")
r_umb, c_umb, w_veto, t_umb, w_umb = run_simulation("TRI_ENGINE_UMB")

eras = {
    "Full History (1999-2026)": np.ones(n, dtype=bool),
    "Modern Traded Era (2010-2026)": (common_idx >= "2010-01-01"),
    "In-Sample (IS: 1999-2019)": (common_idx < "2020-01-01"),
    "Out-of-Sample (OOS: 2020-2026)": (common_idx >= "2020-01-01"),
    "2022 Tech Bear Market": (common_idx >= "2022-01-01") & (common_idx <= "2022-12-31"),
}

print("=" * 105)
print(" RIGOROUS COMPARISON: FP (CURRENT PRODUCTION) VS. TRI-ENGINE (UMB) WITH IDENTICAL RULES")
print("=" * 105)

for era_name, mask in eras.items():
    print(f"\n--- {era_name} ({mask.sum()} Trading Days) ---")
    st_q = calc_stats(q_ret[mask])
    st_fp = calc_stats(r_fp[mask])
    st_umb = calc_stats(r_umb[mask])
    
    rows = [
        {"Model Architecture": "1. Benchmark QQQ Buy & Hold", **st_q},
        {"Model Architecture": "2. Current Production FP (Raw M&B)", **st_fp},
        {"Model Architecture": "3. Tri-Engine UMB (M + B + U Resilience)", **st_umb},
    ]
    df_rows = pd.DataFrame(rows)
    print(df_rows[["Model Architecture", "cum_return_pct", "cagr_pct", "ann_vol_pct", "max_drawdown_pct", "sharpe", "sortino", "calmar"]].to_string(index=False))

print("\n" + "=" * 105)
print(" OPERATIONAL EFFICIENCY & EVENT METRICS")
print("=" * 105)
print(f"Current FP Cash Events Triggered:  {c_fp} Cash Periods  | Time in Market: {np.mean(r_fp != rf_daily)*100:.1f}%")
print(f"Tri-Engine UMB Cash Events:        {c_umb} Cash Periods  | Time in Market: {np.mean(r_umb != rf_daily)*100:.1f}% | Whipsaws Filtered: {w_veto}")
print(f"Tactical TQQQ Booster Trades (FP): {t_fp} trades | Win Rate (+5% Target Hit): {w_fp/max(1,t_fp)*100:.1f}%")
print(f"Tactical TQQQ Booster Trades (UMB):{t_umb} trades | Win Rate (+5% Target Hit): {w_umb/max(1,t_umb)*100:.1f}%")
