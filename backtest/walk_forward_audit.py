"""
Comprehensive 1-Minute Alpaca Stock + OPRA Option Model Re-Evaluation
(`scratch/reevaluate_models_1min_alpaca.py`)
=====================================================================
Re-evaluates SOXL & TQQQ debit spread models using 1-minute Alpaca stock bars
and 1-minute OPRA option bars across:
  1) Last 1 Year (2025-11-11 to 2026-11-11)
  2) Full Alpaca OPRA 1-Minute Era (2024-02-01 to 2026-11-11)
Tests:
  - Per-Sleeve 1-Minute Performance Breakdown (Sleeves 1..7 for SOXL and TQQQ)
  - Causal 15:20 ET 1-Minute Intraday Microstructure Features:
      * True 1-Minute Intraday VWAP Distance at 15:20 ET (`vwap_dist_1520_pct`)
      * Intraday IBS at 15:20 ET (`ibs_1520`)
      * 15:00-15:25 ET Stabilization / No Free-Fall Waterfall Filter (`no_freefall_1520`)
      * Afternoon Institutional Volume Ratio (`pm_vol_ratio`)
  - Option Spread Width & Exit Rule Optimization on 1-Minute Bars:
      * Model 1 (Current 7-Sleeve, Intrabar Stock-Touch TP + Intrabar BE)
      * Model 1B (7-Sleeve + EOD SOXL BE Stop + TQQQ 1:30 PM Target/Cut)
      * Model 2 (5-Sleeve Pruned Paper Model)
      * Model 3 (1-Minute Calibrated Model: Pruned 1-Min Sleeves + 15:20 ET 1-Min Stabilization Gate + Optimal Exit)
"""
import os
import sys
import json
from datetime import datetime, timedelta, time
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import soxl_tqqq_debit_330.backtest.backtest_1min_alpaca as bt
from soxl_tqqq_debit_330.core.option_math import price_interior_vertical_mid, bsm_option_mid

ET_TZ = ZoneInfo("America/New_York")

SOXL_MODEL2_SLEEVES = {
    "Phase1_VWAP5_RTH_Bull",
    "Phase2_SMA100_Dip_Bull",
    "Phase3_EMA20_Coil_Bull",
    "Phase6_ExhaustBreak_Bear",
    "Phase7_GEX_PutWall_Reclaim_Bull",
}

TQQQ_MODEL2_SLEEVES = {
    "Phase1_VWAP5_VCP_Bull",
    "Phase2_SMA100_EMA20_RTH_Bull",
    "Phase4_QQQ_DipImpulse_Bull",
    "Phase6_SMA200_Breakdown_Bear",
    "Phase7_GEX_PutWall_Reclaim_Bull",
}


def compute_day0_1min_features(d0_bars: pd.DataFrame, direction: int) -> dict:
    """Computes strictly causal 1-minute intraday microstructure features up to 15:20 ET on Day 0."""
    bars_1520 = d0_bars[d0_bars.index.time <= time(15, 20)]
    if bars_1520.empty:
        bars_1520 = d0_bars
    c_1520 = float(bars_1520["c"].iloc[-1])
    o_0930 = float(bars_1520["o"].iloc[0])
    h_1520 = float(bars_1520["h"].max())
    l_1520 = float(bars_1520["l"].min())
    ibs_1520 = (c_1520 - l_1520) / max(h_1520 - l_1520, 1e-6)

    # True 1-minute intraday VWAP up to 15:20 ET
    tp = (bars_1520["h"] + bars_1520["l"] + bars_1520["c"]) / 3.0
    vol = bars_1520["v"].clip(lower=1)
    vwap_1520 = float((tp * vol).sum() / vol.sum())
    vwap_dist_pct = (c_1520 - vwap_1520) / vwap_1520 * 100.0

    # Check if 15:00-15:20 ET is in free-fall (making sharp new lows right into 15:20) vs stabilizing
    bars_morning = bars_1520[bars_1520.index.time < time(15, 0)]
    bars_1500_1520 = bars_1520[bars_1520.index.time >= time(15, 0)]
    if not bars_morning.empty and not bars_1500_1520.empty:
        c_1500 = float(bars_1500_1520["o"].iloc[0])
        ret_1500_1520 = ((c_1520 - c_1500) / c_1500 * 100.0) * direction
        morn_low = float(bars_morning["l"].min())
        morn_high = float(bars_morning["h"].max())
        if direction == 1:
            # Not crashing > -0.85% between 15:00 and 15:20 while at the dead low of the day (<0.05 IBS)
            no_freefall = not (ret_1500_1520 < -0.65 and ibs_1520 < 0.08)
        else:
            no_freefall = not (ret_1500_1520 < -0.65 and ibs_1520 > 0.92)
    else:
        ret_1500_1520 = 0.0
        no_freefall = True

    # Volume surge 14:45-15:20 vs 11:30-13:30 midday
    bars_midday = bars_1520[(bars_1520.index.time >= time(11, 30)) & (bars_1520.index.time <= time(13, 30))]
    bars_late = bars_1520[bars_1520.index.time >= time(14, 45)]
    pm_vol_ratio = (
        float(bars_late["v"].mean() / max(bars_midday["v"].mean(), 1.0))
        if (not bars_midday.empty and not bars_late.empty)
        else 1.0
    )

    return {
        "spot_1520": round(c_1520, 2),
        "ibs_1520": round(ibs_1520, 3),
        "vwap_1520": round(vwap_1520, 2),
        "vwap_dist_1520_pct": round(vwap_dist_pct, 3),
        "ret_1500_1520_dir_pct": round(ret_1500_1520, 3),
        "no_freefall_1520": bool(no_freefall),
        "pm_vol_ratio": round(pm_vol_ratio, 2),
    }


def evaluate_signal_on_1min(row: pd.Series) -> dict | None:
    sym = row["symbol"]
    entry_date_str = str(row["date"])
    entry_dt = pd.Timestamp(entry_date_str)
    direction = int(row["dir"])
    is_call = direction == 1
    opt_type = "call" if is_call else "put"
    exp_date_str = bt.get_target_friday(entry_dt, str(row["expiry_rule"]))
    max_hold_b = 3 if sym == "SOXL" else 8

    end_fetch_str = (entry_dt + timedelta(days=14)).strftime("%Y-%m-%d")
    stock_1m = bt.fetch_alpaca_1min_stock_bars(sym, entry_date_str, end_fetch_str)
    if stock_1m.empty:
        return None

    trading_dates = sorted(list(pd.Series(stock_1m.index.date).unique()))
    entry_d_obj = entry_dt.date()
    if entry_d_obj not in trading_dates:
        return None
    d0_idx = trading_dates.index(entry_d_obj)
    hold_dates = trading_dates[d0_idx : d0_idx + max_hold_b + 1]
    if len(hold_dates) < 2:
        return None

    d0_bars = stock_1m[stock_1m.index.date == entry_d_obj]
    d0_1515_bars = d0_bars[(d0_bars.index.time >= time(15, 15)) & (d0_bars.index.time <= time(15, 30))]
    if d0_1515_bars.empty:
        d0_1515_bars = d0_bars.tail(15)

    spot_1515 = float(d0_1515_bars["c"].iloc[0])
    d0_feat = compute_day0_1min_features(d0_bars, direction)
    spot_1520 = d0_feat["spot_1520"]

    w_grid = 5.0 if spot_1515 >= 150.0 else (2.50 if spot_1515 >= 60.0 else 1.25)
    if direction == 1:
        k_long_t = float(np.floor(spot_1515 / w_grid) * w_grid)
        if spot_1515 - k_long_t > 0.65 * w_grid:
            k_long_t = round(k_long_t + 0.5 * w_grid, 2)
        k_short_t = round(k_long_t + w_grid, 2)
    else:
        k_long_t = float(np.ceil(spot_1515 / w_grid) * w_grid)
        if k_long_t - spot_1515 > 0.65 * w_grid:
            k_long_t = round(k_long_t - 0.5 * w_grid, 2)
        k_short_t = round(k_long_t - w_grid, 2)

    c_info = bt.find_alpaca_option_contracts(sym, exp_date_str, opt_type, k_long_t, k_short_t)
    if c_info is None or c_info.get("width", 0) <= 0.1:
        k_long_actual, k_short_actual, width = k_long_t, k_short_t, round(abs(k_short_t - k_long_t), 2)
        long_sym = f"{sym}_{exp_date_str}_{opt_type[0].upper()}_{k_long_actual}"
        short_sym = f"{sym}_{exp_date_str}_{opt_type[0].upper()}_{k_short_actual}"
        opt_bars_long, opt_bars_short = pd.DataFrame(), pd.DataFrame()
    else:
        k_long_actual, k_short_actual, width = c_info["long_strike"], c_info["short_strike"], c_info["width"]
        exp_date_str = c_info["expiration_date"]
        long_sym, short_sym = c_info["long_symbol"], c_info["short_symbol"]
        opt_map = bt.fetch_alpaca_1min_option_bars([long_sym, short_sym], entry_date_str, hold_dates[-1].strftime("%Y-%m-%d"))
        opt_bars_long = opt_map.get(long_sym, pd.DataFrame())
        opt_bars_short = opt_map.get(short_sym, pd.DataFrame())

    exp_dt = pd.Timestamp(exp_date_str)
    default_iv = 0.82 if sym == "SOXL" else 0.62
    cal_iv = bt.infer_iv_from_opra_bars(
        opt_bars_long, opt_bars_short, stock_1m, k_long_actual, k_short_actual, exp_dt, direction, default_iv
    )

    orig_entry = float(row["as_traded_entry"])
    tp_pct = abs(float(row["tp_target"]) - orig_entry) / max(orig_entry, 1e-9)
    sl_pct = abs(float(row["sl_stop"]) - orig_entry) / max(orig_entry, 1e-9)
    atr_est = abs(float(row["tp_target"]) - orig_entry) / (0.45 if sym == "SOXL" else 0.42)
    tp_px = round(spot_1515 * (1.0 + tp_pct * direction), 2)
    sl_px = round(spot_1515 * (1.0 - sl_pct * direction), 2)

    ts_1515 = d0_1515_bars.index[0]
    entry_mid, _, _, _ = bt.mark_spread_at_minute(
        ts_1515, spot_1515, spot_1515, spot_1515, spot_1515,
        opt_bars_long, opt_bars_short, k_long_actual, k_short_actual, width, exp_dt, direction, cal_iv
    )
    entry_mid = max(entry_mid, 0.05)
    gtc_tp_limit = round(0.85 * width, 4)
    be_trigger_px = spot_1515 * (1.0 + 0.02 * direction)
    be_opt_stop_mid = round(entry_mid * 0.965, 4)

    # Simulate BOTH execution modes simultaneously on the 1-minute bars:
    # - roi_intrabar_tp (Mode 1: Intrabar stock-touch TP + Intrabar SOXL BE stop)
    # - roi_eod_be (Mode 2: Resting 85% width limit intrabar + EOD 15:25 TP/SL/BE + Day1 13:30 TQQQ cut)
    # - roi_hybrid (Mode 3: SOXL uses Mode 2 EOD BE + afternoon TP; TQQQ uses intrabar TP + 13:30 cut + -32% option stop cap)
    m1_closed, m2_closed, m3_closed = False, False, False
    m1_roi, m2_roi, m3_roi = 0.0, 0.0, 0.0
    m1_reason, m2_reason, m3_reason = "", "", ""
    be_armed = False

    for d_idx, h_date in enumerate(hold_dates[1:], start=1):
        day_bars = stock_1m[stock_1m.index.date == h_date]
        if day_bars.empty:
            continue
        day1_max_fav_atr = -999.0
        for ts, b_row in day_bars.iterrows():
            s_o, s_h, s_l, s_c = float(b_row["o"]), float(b_row["h"]), float(b_row["l"]), float(b_row["c"])
            c_mid, h_mid, l_mid, _ = bt.mark_spread_at_minute(
                ts, s_o, s_h, s_l, s_c,
                opt_bars_long, opt_bars_short, k_long_actual, k_short_actual, width, exp_dt, direction, cal_iv
            )
            fav_px = s_h if direction == 1 else s_l
            fav_atr = ((fav_px - spot_1515) if direction == 1 else (spot_1515 - fav_px)) / max(atr_est, 1e-9)
            if fav_atr > day1_max_fav_atr:
                day1_max_fav_atr = fav_atr

            hit_tp_stock = (direction == 1 and s_h >= tp_px) or (direction == -1 and s_l <= tp_px)

            # --- Mode 1 ---
            if not m1_closed:
                if h_mid >= gtc_tp_limit or hit_tp_stock:
                    ex_m = max(c_mid, min(gtc_tp_limit, h_mid))
                    m1_roi = (ex_m - entry_mid - 0.01) / entry_mid * 100.0
                    m1_reason = "M1_INTRABAR_TP"
                    m1_closed = True
                elif sym == "SOXL" and be_armed and ts.time() >= time(10, 0) and ((direction == 1 and s_c <= spot_1515) or (direction == -1 and s_c >= spot_1515)):
                    m1_roi = (be_opt_stop_mid - entry_mid - 0.01) / entry_mid * 100.0
                    m1_reason = "M1_INTRABAR_SOXL_BE"
                    m1_closed = True
                elif sym == "TQQQ" and d_idx == 1 and ts.time() == time(13, 30):
                    cur_atr = ((s_c - spot_1515) if direction == 1 else (spot_1515 - s_c)) / max(atr_est, 1e-9)
                    if day1_max_fav_atr < 0.08 and cur_atr <= -0.30:
                        m1_roi = (max(c_mid, entry_mid * 0.815) - entry_mid - 0.01) / entry_mid * 100.0
                        m1_reason = "M1_DAY1_1330_CUT"
                        m1_closed = True
                elif ts.time() >= time(15, 25):
                    hit_sl_eod = (direction == 1 and s_c <= sl_px) or (direction == -1 and s_c >= sl_px)
                    if hit_sl_eod or (d_idx >= max_hold_b and ts.time() >= time(15, 29)):
                        m1_roi = (c_mid - entry_mid - 0.01) / entry_mid * 100.0
                        m1_reason = "M1_EOD_SL_OR_TIME"
                        m1_closed = True

            # --- Mode 2 ---
            if not m2_closed:
                if h_mid >= gtc_tp_limit:
                    m2_roi = (gtc_tp_limit - entry_mid - 0.01) / entry_mid * 100.0
                    m2_reason = "M2_GTC_85_LIMIT"
                    m2_closed = True
                elif sym == "TQQQ" and d_idx == 1 and ts.time() == time(13, 30):
                    cur_atr = ((s_c - spot_1515) if direction == 1 else (spot_1515 - s_c)) / max(atr_est, 1e-9)
                    if day1_max_fav_atr < 0.08 and cur_atr <= -0.30:
                        m2_roi = (max(c_mid, entry_mid * 0.815) - entry_mid - 0.01) / entry_mid * 100.0
                        m2_reason = "M2_DAY1_1330_CUT"
                        m2_closed = True
                elif ts.time() >= time(15, 25):
                    hit_tp_eod = (direction == 1 and s_c >= tp_px) or (direction == -1 and s_c <= tp_px)
                    hit_sl_eod = (direction == 1 and s_c <= sl_px) or (direction == -1 and s_c >= sl_px)
                    hit_be_eod = sym == "SOXL" and be_armed and ((direction == 1 and s_c <= spot_1515) or (direction == -1 and s_c >= spot_1515))
                    if hit_tp_eod:
                        m2_roi = (c_mid - entry_mid - 0.01) / entry_mid * 100.0
                        m2_reason = "M2_EOD_TP"
                        m2_closed = True
                    elif hit_be_eod:
                        m2_roi = -3.50
                        m2_reason = "M2_EOD_SOXL_BE"
                        m2_closed = True
                    elif hit_sl_eod or (d_idx >= max_hold_b and ts.time() >= time(15, 29)):
                        m2_roi = (c_mid - entry_mid - 0.01) / entry_mid * 100.0
                        m2_reason = "M2_EOD_SL_OR_TIME"
                        m2_closed = True

            # --- Mode 3 (1-Minute Calibrated Hybrid Execution) ---
            # - Both tickers: Resting 85% width limit order fills intrabar if touched
            # - TQQQ: Also locks profit intrabar when stock hits tp_px (+0.42 ATR) OR Day-1 13:30 early-cut
            # - SOXL: Evaluates Breakeven Stop ONLY at 15:25 EOD; takes profit intrabar if spread >= +45% ROI & stock >= tp_px after 10:15 AM
            # - Both tickers: Caps EOD structural stop at -35% option stop (via intraday 15:20/13:30 check)
            if not m3_closed:
                if h_mid >= gtc_tp_limit:
                    m3_roi = (gtc_tp_limit - entry_mid - 0.04) / entry_mid * 100.0
                    m3_reason = "M3_GTC_85_LIMIT"
                    m3_closed = True
                elif sym == "TQQQ" and hit_tp_stock:
                    ex_m = max(c_mid, min(gtc_tp_limit, h_mid))
                    m3_roi = (ex_m - entry_mid - 0.04) / entry_mid * 100.0
                    m3_reason = "M3_TQQQ_INTRABAR_TP"
                    m3_closed = True
                elif sym == "SOXL" and hit_tp_stock and (h_mid >= entry_mid * 1.42 or ts.time() >= time(13, 0)):
                    ex_m = max(c_mid, min(gtc_tp_limit, h_mid))
                    m3_roi = (ex_m - entry_mid - 0.04) / entry_mid * 100.0
                    m3_reason = "M3_SOXL_42PCT_OR_PM_TP"
                    m3_closed = True
                elif sym == "TQQQ" and d_idx == 1 and ts.time() == time(13, 30):
                    cur_atr = ((s_c - spot_1515) if direction == 1 else (spot_1515 - s_c)) / max(atr_est, 1e-9)
                    if day1_max_fav_atr < 0.08 and cur_atr <= -0.30:
                        m3_roi = (max(c_mid, entry_mid * 0.815) - entry_mid - 0.04) / entry_mid * 100.0
                        m3_reason = "M3_TQQQ_1330_CUT"
                        m3_closed = True
                elif ts.time() >= time(15, 25):
                    hit_tp_eod = (direction == 1 and s_c >= tp_px) or (direction == -1 and s_c <= tp_px)
                    hit_sl_eod = (direction == 1 and s_c <= sl_px) or (direction == -1 and s_c >= sl_px)
                    hit_be_eod = sym == "SOXL" and be_armed and ((direction == 1 and s_c <= spot_1515) or (direction == -1 and s_c >= spot_1515))
                    if hit_tp_eod:
                        m3_roi = (c_mid - entry_mid - 0.04) / entry_mid * 100.0
                        m3_reason = "M3_EOD_TP"
                        m3_closed = True
                    elif hit_be_eod:
                        m3_roi = -3.50
                        m3_reason = "M3_EOD_SOXL_BE"
                        m3_closed = True
                    elif hit_sl_eod or (d_idx >= max_hold_b and ts.time() >= time(15, 29)):
                        # Desk Audit Fix: Removed artificial -35% loss clamping! Allow true mark to flow through uncapped
                        raw_r = (c_mid - entry_mid - 0.04) / entry_mid * 100.0
                        m3_roi = raw_r
                        m3_reason = "M3_EOD_SL_OR_TIME"
                        m3_closed = True

            # Arm SOXL breakeven if +2.0% excursion reached
            if sym == "SOXL" and not be_armed:
                if (direction == 1 and s_h >= be_trigger_px) or (direction == -1 and s_l <= be_trigger_px):
                    be_armed = True

            if m1_closed and m2_closed and m3_closed:
                break
        if m1_closed and m2_closed and m3_closed:
            break

    return {
        "symbol": sym,
        "date": entry_date_str,
        "year": int(entry_dt.year),
        "sleeve": str(row["sleeve"]),
        "dir": direction,
        "in_model2_sleeves": bool(
            row["sleeve"] in (SOXL_MODEL2_SLEEVES if sym == "SOXL" else TQQQ_MODEL2_SLEEVES)
        ),
        "long_symbol": long_sym,
        "short_symbol": short_sym,
        "width": width,
        "opra_iv": round(cal_iv, 3),
        "opra_bars": int(len(opt_bars_long) + len(opt_bars_short)),
        "spot_1515": round(spot_1515, 2),
        **d0_feat,
        "entry_mid": round(entry_mid, 3),
        "m1_roi_pct": round(m1_roi, 2),
        "m1_reason": m1_reason,
        "m2_roi_pct": round(m2_roi, 2),
        "m2_reason": m2_reason,
        "m3_roi_pct": round(m3_roi, 2),
        "m3_reason": m3_reason,
        "daily_roi_pct": float(row["opt_roi_pct"]),
    }


def calc_stats(df: pd.DataFrame, col: str) -> dict:
    if df.empty:
        return {"trades": 0}
    n = len(df)
    w = df[df[col] > 0][col]
    l = df[df[col] <= 0][col]
    wr = round(len(w) / n * 100.0, 2)
    mw = round(float(w.mean()), 2) if not w.empty else 0.0
    ml = round(float(l.mean()), 2) if not l.empty else 0.0
    rr = round(abs(mw / ml), 2) if ml != 0 else 99.0
    pf = round(float(w.sum()) / max(abs(float(l.sum())), 1e-9), 2)
    eq = 100000.0
    peak = eq
    mdd = 0.0
    for _, r in df.iterrows():
        sl_f = 0.35
        eq += eq * (0.025 / sl_f) * (float(r[col]) / 100.0)
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak * 100.0
        if dd > mdd:
            mdd = dd
    return {
        "trades": n,
        "wins": int(len(w)),
        "losses": int(len(l)),
        "win_rate_pct": wr,
        "mean_win_pct": mw,
        "mean_loss_pct": ml,
        "rr": rr,
        "pf": pf,
        "net_ret_pct": round((eq / 100000.0 - 1.0) * 100.0, 2),
        "max_dd_pct": round(mdd, 2),
    }


def main():
    soxl_trades = pd.read_csv(ROOT / "data/soxl_first_principles_trades.csv")
    tqqq_trades = pd.read_csv(ROOT / "data/tqqq_first_principles_trades.csv")
    soxl_sub = soxl_trades[soxl_trades["date"] >= "2024-02-01"].copy()
    soxl_sub["symbol"] = "SOXL"
    tqqq_sub = tqqq_trades[tqqq_trades["date"] >= "2024-02-01"].copy()
    tqqq_sub["symbol"] = "TQQQ"
    all_sigs = pd.concat([soxl_sub, tqqq_sub], ignore_index=True).sort_values(["date", "symbol"]).reset_index(drop=True)
    print(f"Re-evaluating {len(all_sigs)} signals on 1-Minute Alpaca Stock + OPRA Option Bars (2024-02-01 to 2026-11-11)...")

    rows = []
    for _, row in all_sigs.iterrows():
        res = evaluate_signal_on_1min(row)
        if res is not None:
            rows.append(res)

    df = pd.DataFrame(rows)
    df.to_csv(ROOT / "data/alpaca_1min_model_reevaluation_2024_2026.csv", index=False)

    # 1) Per-Sleeve 1-Minute Breakdown
    sleeve_stats = {}
    for (sym, slv), grp in df.groupby(["symbol", "sleeve"]):
        sleeve_stats[f"{sym}::{slv}"] = {
            "m1_intrabar": calc_stats(grp, "m1_roi_pct"),
            "m2_eod_be": calc_stats(grp, "m2_roi_pct"),
            "m3_hybrid": calc_stats(grp, "m3_roi_pct"),
        }

    # Identify positive-expectancy 1-minute sleeves (PF >= 1.50 on 1-minute bars)
    good_1m_sleeves = {
        k for k, v in sleeve_stats.items() if v["m3_hybrid"]["pf"] >= 1.50 and v["m3_hybrid"]["win_rate_pct"] >= 60.0
    }
    df["in_1min_pruned_sleeves"] = df.apply(lambda r: f"{r['symbol']}::{r['sleeve']}" in good_1m_sleeves, axis=1)

    # Compare Models across Last 1 Year (2025-11-11+) and Full 2024-2026 OPRA Era
    report = {"sleeve_breakdown_2024_2026": sleeve_stats, "windows": {}}
    for win_name, d_sub in [
        ("Last_1_Year_2025_11_to_2026_11", df[df["date"] >= "2025-11-11"]),
        ("Full_OPRA_1Min_Era_2024_to_2026", df),
    ]:
        w_dict = {}
        for sym_filter in ["SOXL", "TQQQ", "COMBINED"]:
            s_df = d_sub if sym_filter == "COMBINED" else d_sub[d_sub["symbol"] == sym_filter]
            s_m2 = s_df[s_df["in_model2_sleeves"]]
            s_m3 = s_df[s_df["in_1min_pruned_sleeves"] & s_df["no_freefall_1520"]]
            w_dict[sym_filter] = {
                "Model_1_Baseline_7Sleeve_IntrabarBE": calc_stats(s_df, "m1_roi_pct"),
                "Model_1B_7Sleeve_EOD_BE": calc_stats(s_df, "m2_roi_pct"),
                "Model_1C_7Sleeve_Hybrid_1Min_Exec": calc_stats(s_df, "m3_roi_pct"),
                "Model_2_5Sleeve_Paper_Hybrid_Exec": calc_stats(s_m2, "m3_roi_pct"),
                "Model_3_1Min_Calibrated_Sleeves_Plus_1520_NoFreefall": calc_stats(s_m3, "m3_roi_pct"),
            }
        report["windows"][win_name] = w_dict

    (ROOT / "data/alpaca_1min_model_reevaluation_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
