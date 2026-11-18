"""
SOXL Intraday 0 DTE Friday Debit Spread Backtest Engine (Hardened V2)
=====================================================================
Executes the institutional backtest of the SOXL Intraday 0 DTE Friday Debit Spread Engine
across multi-year intraday market data (2020 - 2026).

Audit Hardening:
  1. Real Listed Strikes: Snapped to $0.50 / $1.00 exchange increments.
  2. Scale-Invariant Spread Width: ~3.5% of spot, eliminating low-price distortions.
  3. Unclamped Stop Loss: Realized loss tracks true market plunge without -12.5% clamp.
  4. Adverse-First Intra-Bar Priority: SL checked on r_low before TP on r_high to prevent high-bias.
  5. Real OPRA Friction: $0.08/spread round-trip slippage.
"""

from __future__ import annotations

import os
import sys
import json
from pathlib import Path
from datetime import datetime, time
from typing import Dict, Any
import numpy as np
import pandas as pd

# Add repository root to path
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from soxl_tqqq_debit_330.core.soxl_intraday_0dte import SOXLIntraday0DTEEngine

def run_intraday_0dte_backtest(
    parquet_path: str = "system_15m/data/cache/SOXL_15Min.parquet",
    output_dir: str = "soxl_tqqq_debit_330/data",
) -> Dict[str, Any]:
    print("=" * 80)
    print("RUNNING SOXL INTRADAY 0 DTE FRIDAY DEBIT SPREAD BACKTEST (HARDENED V2)")
    print("=" * 80)
    
    if not os.path.exists(parquet_path):
        raise FileNotFoundError(f"Intraday data not found at {parquet_path}")
        
    df_raw = pd.read_parquet(parquet_path)
    if df_raw.index.tz is None:
        df_raw.index = df_raw.index.tz_localize("America/New_York")
    else:
        df_raw.index = df_raw.index.tz_convert("America/New_York")
        
    df_raw["date"] = df_raw.index.date
    df_raw["time"] = df_raw.index.time
    
    engine = SOXLIntraday0DTEEngine(
        itm_offset_pct=0.025,
        target_width_pct=0.035,
        take_profit_pct=0.25,
        stop_loss_pct=0.125,
        slippage_per_spread=0.08, # Realistic $0.08 round-trip ($0.04/leg)
        entry_time=time(12, 0),
        mandatory_exit_time=time(15, 45)
    )
    
    grouped = {d: g.sort_index() for d, g in df_raw.groupby("date")}
    friday_dates = sorted([d for d in grouped.keys() if pd.Timestamp(d).weekday() == 4])
    print(f"Loaded {len(df_raw):,} 15-minute bars across {len(friday_dates)} Friday sessions.")
    
    trades = []
    
    for d in friday_dates:
        bars = grouped[d]
        if len(bars) < 14:
            continue
            
        # Intraday cumulative VWAP from 09:30 ET
        tp = (bars["high"] + bars["low"] + bars["close"]) / 3.0
        pv = tp * bars["volume"]
        vwap_series = pv.cumsum() / (bars["volume"].cumsum() + 1e-9)
        
        bars_noon = bars[bars["time"] == time(12, 0)]
        if bars_noon.empty:
            continue
            
        bar_entry = bars_noon.iloc[0]
        idx_entry = bars.index.get_loc(bar_entry.name)
        spot_noon = float(bar_entry["close"])
        vwap_noon = float(vwap_series.iloc[idx_entry])
        
        signal = engine.evaluate_friday_signal(
            current_time=time(12, 0),
            spot=spot_noon,
            vwap=vwap_noon,
            weekday=4
        )
        if signal is None:
            continue
            
        rem_bars = bars.iloc[idx_entry + 1:]
        exit_res = None
        
        for r_ts, r_bar in rem_bars.iterrows():
            r_time = r_bar["time"]
            r_high = float(r_bar["high"])
            r_low = float(r_bar["low"])
            r_close = float(r_bar["close"])
            
            fav_spot_check = r_high if signal["is_call"] else r_low
            adv_spot_check = r_low if signal["is_call"] else r_high
            
            # AUDIT FIX: CHECK ADVERSE (SL) FIRST to eliminate high-before-low bias!
            sl_check = engine.check_position_exit(signal, r_time, adv_spot_check)
            if sl_check and sl_check["exit_reason"].startswith("INTRADAY_SL"):
                exit_res = sl_check
                exit_res["exit_time"] = str(r_time)
                break
                
            # Then check TP on favorable touch
            tp_check = engine.check_position_exit(signal, r_time, fav_spot_check)
            if tp_check and tp_check["exit_reason"].startswith("INTRADAY_TP"):
                exit_res = tp_check
                exit_res["exit_time"] = str(r_time)
                break
                
            # Check Mandatory EOD Exit
            if r_time >= time(15, 45):
                eod_check = engine.check_position_exit(signal, r_time, r_close)
                exit_res = eod_check
                exit_res["exit_time"] = str(r_time)
                break
                
        if exit_res is None and not rem_bars.empty:
            final_c = float(rem_bars.iloc[-1]["close"])
            eod_check = engine.check_position_exit(signal, time(16, 0), final_c)
            exit_res = eod_check or {
                "exit_triggered": True,
                "exit_reason": "EOD_1600_EXPIRY",
                "exit_price": round(signal["entry_cost"], 3),
                "net_pnl": 0.0,
                "roi_pct": 0.0,
                "win": False,
                "exit_time": "16:00:00"
            }
            
        if exit_res is not None:
            trades.append({
                "date": str(d),
                "year": pd.Timestamp(d).year,
                "direction": signal["direction"],
                "spot_entry": round(signal["spot"], 2),
                "vwap_entry": round(signal["vwap"], 2),
                "k_long": signal["k_long"],
                "k_short": signal["k_short"],
                "width": signal["width"],
                "entry_mid": signal["entry_mid"],
                "entry_cost": signal["entry_cost"],
                "exit_price": exit_res["exit_price"],
                "exit_time": exit_res.get("exit_time", "15:45:00"),
                "exit_reason": exit_res["exit_reason"],
                "net_pnl": exit_res["net_pnl"],
                "roi_pct": exit_res["roi_pct"],
                "win": exit_res["win"]
            })
            
    df_trades = pd.DataFrame(trades)
    
    def compute_stats(df_sub: pd.DataFrame) -> Dict[str, Any]:
        n = len(df_sub)
        if n == 0:
            return {}
        wins = df_sub[df_sub["win"]]["roi_pct"]
        losses = df_sub[~df_sub["win"]]["roi_pct"]
        n_wins = len(wins)
        n_losses = len(losses)
        wr = round(n_wins / n * 100.0, 2)
        mean_w = round(float(wins.mean()), 2) if n_wins > 0 else 0.0
        mean_l = round(abs(float(losses.mean())), 2) if n_losses > 0 else 0.0
        rr = round(mean_w / mean_l, 2) if mean_l > 0 else 99.0
        gross_w = float(wins.sum())
        gross_l = abs(float(losses.sum()))
        pf = round(gross_w / max(gross_l, 1e-9), 2)
        
        t0_dt = pd.Timestamp(df_sub["date"].iloc[0])
        t1_dt = pd.Timestamp(df_sub["date"].iloc[-1])
        n_weeks = max(1.0, (t1_dt - t0_dt).days / 7.0)
        trades_per_week = round(n / n_weeks, 2)
        ann_trades = round(trades_per_week * 52, 1)
        
        equity = [100.0]
        for roi in df_sub["roi_pct"]:
            equity.append(equity[-1] * (1.0 + (roi / 100.0) * 0.05))
        peak = np.maximum.accumulate(equity)
        dd = (np.array(equity) - peak) / peak * 100.0
        max_dd = round(float(abs(dd.min())), 2)
        cum_ret = round(equity[-1] - 100.0, 2)
        
        return {
            "trades": n,
            "wins": n_wins,
            "losses": n_losses,
            "win_rate_pct": wr,
            "mean_win_roi_pct": mean_w,
            "mean_loss_roi_pct": mean_l,
            "realized_rr": rr,
            "profit_factor": pf,
            "trades_per_week": trades_per_week,
            "annual_trades": ann_trades,
            "max_drawdown_pct": max_dd,
            "cum_return_5pct_pos": cum_ret
        }
        
    full_stats = compute_stats(df_trades)
    is_stats = compute_stats(df_trades[df_trades["year"] <= 2023])
    oos_stats = compute_stats(df_trades[df_trades["year"] >= 2024])
    
    annual_breakdown = {}
    for yr, g in df_trades.groupby("year"):
        annual_breakdown[int(yr)] = compute_stats(g)
        
    sleeve_breakdown = {}
    for d_name, g in df_trades.groupby("direction"):
        sleeve_breakdown[d_name] = compute_stats(g)
        
    print("\n" + "=" * 90)
    print(f"FULL SAMPLE (2020 - 2026): N={full_stats['trades']} | WR={full_stats['win_rate_pct']}% | R:R={full_stats['realized_rr']}x | PF={full_stats['profit_factor']} | Freq={full_stats['trades_per_week']}/wk | MaxDD={full_stats['max_drawdown_pct']}% | Return=+{full_stats['cum_return_5pct_pos']}%")
    print(f"IN-SAMPLE   (2020 - 2023): N={is_stats['trades']} | WR={is_stats['win_rate_pct']}% | R:R={is_stats['realized_rr']}x | PF={is_stats['profit_factor']} | Freq={is_stats['trades_per_week']}/wk | MaxDD={is_stats['max_drawdown_pct']}% | Return=+{is_stats['cum_return_5pct_pos']}%")
    print(f"OUT-OF-SAMP (2024 - 2026): N={oos_stats['trades']} | WR={oos_stats['win_rate_pct']}% | R:R={oos_stats['realized_rr']}x | PF={oos_stats['profit_factor']} | Freq={oos_stats['trades_per_week']}/wk | MaxDD={oos_stats['max_drawdown_pct']}% | Return=+{oos_stats['cum_return_5pct_pos']}%")
    print("=" * 90)
    
    print("\nANNUAL REGIME BREAKDOWN:")
    for yr, st in annual_breakdown.items():
        print(f"  {yr}: N={st['trades']:2d} | WR={st['win_rate_pct']:5.1f}% | R:R={st['realized_rr']:4.2f}x | PF={st['profit_factor']:4.2f} | Freq={st['trades_per_week']:.2f}/wk | MaxDD={st['max_drawdown_pct']:4.1f}% | Return={st['cum_return_5pct_pos']:+6.1f}%")
        
    print("\nSLEEVE PERFORMANCE:")
    for sl, st in sleeve_breakdown.items():
        print(f"  {sl:10s}: N={st['trades']:3d} | WR={st['win_rate_pct']:5.1f}% | R:R={st['realized_rr']:4.2f}x | PF={st['profit_factor']:4.2f} | Freq={st['trades_per_week']:.2f}/wk | Return={st['cum_return_5pct_pos']:+6.1f}%")
        
    print("\nEXIT DISTRIBUTION:")
    print(df_trades["exit_reason"].value_counts())
    
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs("data", exist_ok=True)
    
    # Save to both soxl_tqqq_debit_330/data and data/
    for out_d in [output_dir, "data"]:
        trades_path = os.path.join(out_d, "soxl_intraday_0dte_trades.csv")
        results_path = os.path.join(out_d, "soxl_intraday_0dte_results.json")
        df_trades.to_csv(trades_path, index=False)
        results_payload = {
            "strategy": "SOXL_INTRADAY_0DTE_FRIDAY_DEBIT_SPREAD",
            "audit_version": "V2_HARDENED",
            "timestamp": datetime.now().isoformat(),
            "parameters": {
                "itm_offset_pct": 0.025,
                "target_width_pct": 0.035,
                "take_profit_pct": 0.25,
                "stop_loss_pct": 0.125,
                "entry_time": "12:00:00",
                "mandatory_close_time": "15:45:00",
                "slippage": 0.08
            },
            "full_sample": full_stats,
            "in_sample": is_stats,
            "out_of_sample": oos_stats,
            "annual_breakdown": annual_breakdown,
            "sleeve_breakdown": sleeve_breakdown,
            "exit_counts": df_trades["exit_reason"].value_counts().to_dict()
        }
        with open(results_path, "w") as f:
            json.dump(results_payload, f, indent=2)
            
    print(f"\nArtifacts saved cleanly to both {output_dir} and data/")
    return results_payload

if __name__ == "__main__":
    run_intraday_0dte_backtest()
