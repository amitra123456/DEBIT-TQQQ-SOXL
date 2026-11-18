"""
1-Minute Candle-by-Candle Backtest for SOXL & TQQQ Debit Spreads Using Real Alpaca
1-Min Stock Bars (`/v2/stocks/bars`) & 1-Min OPRA Option Bars (`/v1beta1/options/bars`)
Over the Last 1 Year (2025-11-11 to 2026-11-11)
=======================================================================================
"""
import os
import sys
import json
import math
from datetime import datetime, timedelta, time
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

import yfinance as yf
from soxl_tqqq_debit_330.core.option_math import price_interior_vertical_mid, bsm_option_mid
from soxl_tqqq_debit_330.config import (
    DEBIT_STRATEGY_CONFIGS,
    SOXL_ACTIVE_SLEEVES,
    SOXL_DISABLED_SLEEVES,
    TQQQ_ACTIVE_SLEEVES,
    TQQQ_DISABLED_SLEEVES,
)

PACKAGE_DIR = Path(__file__).resolve().parents[1]

ET_TZ = ZoneInfo("America/New_York")
API_KEY = os.getenv("ALPACA_API_KEY") or os.getenv("APCA_API_KEY_ID") or ""
API_SECRET = os.getenv("ALPACA_SECRET_KEY") or os.getenv("APCA_API_SECRET_KEY") or ""
BASE_URL = (os.getenv("ALPACA_BASE_URL") or "https://paper-api.alpaca.markets").rstrip("/")
DATA_URL = "https://data.alpaca.markets"

HEADERS = {
    "APCA-API-KEY-ID": API_KEY,
    "APCA-API-SECRET-KEY": API_SECRET,
    "Accept": "application/json",
}


def get_target_friday(entry_dt: pd.Timestamp, expiry_rule: str = "7-14 DTE") -> str:
    wd = entry_dt.weekday()  # 0=Mon .. 4=Fri
    days_to_fri = (4 - wd) % 7
    # Production Institutional 7-14 DTE: Ensure all entries target next week's Friday (7 to 11 DTE)
    if days_to_fri < 7:
        days_to_fri += 7
    exp_dt = entry_dt + timedelta(days=days_to_fri)
    return exp_dt.strftime("%Y-%m-%d")


def fetch_alpaca_1min_stock_bars(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    start_iso = f"{start_date}T09:00:00Z"
    end_iso = f"{end_date}T23:59:59Z"
    all_bars = []
    page_token = None
    while True:
        params = {
            "symbols": symbol,
            "timeframe": "1Min",
            "start": start_iso,
            "end": end_iso,
            "limit": 10000,
            "feed": "sip",
            "adjustment": "split",
        }
        if page_token:
            params["page_token"] = page_token
        r = requests.get(f"{DATA_URL}/v2/stocks/bars", headers=HEADERS, params=params, timeout=15)
        if r.status_code != 200:
            break
        js = r.json()
        bars = js.get("bars", {}).get(symbol, [])
        all_bars.extend(bars)
        page_token = js.get("next_page_token")
        if not page_token:
            break
    if not all_bars:
        return pd.DataFrame()
    df = pd.DataFrame(all_bars)
    df["ts"] = pd.to_datetime(df["t"]).dt.tz_convert(ET_TZ)
    df = df.sort_values("ts").drop_duplicates("ts").set_index("ts")
    # Filter to RTH 09:30 - 16:00 ET
    df = df[(df.index.time >= time(9, 30)) & (df.index.time <= time(16, 0))]
    return df


def find_alpaca_option_contracts(
    underlying: str, exp_date: str, opt_type: str, target_long: float, target_short: float
):
    # Desk Audit Fix: TQQQ 2-for-1 split occurred 2025-11-20. Unadjusted OPRA strikes prior to split are 2.0x
    split_mult = 2.0 if (underlying == "TQQQ" and exp_date < "2025-11-20" and target_long < 80.0) else 1.0
    target_long = target_long * split_mult
    target_short = target_short * split_mult
    contracts = []
    for status in ("inactive", "active"):
        r = requests.get(
            f"{BASE_URL}/v2/options/contracts",
            headers=HEADERS,
            params={
                "underlying_symbols": underlying,
                "status": status,
                "expiration_date": exp_date,
                "type": opt_type,
                "strike_price_gte": str(max(1.0, min(target_long, target_short) - 10.0)),
                "strike_price_lte": str(max(target_long, target_short) + 10.0),
                "limit": 100,
            },
            timeout=12,
        )
        if r.status_code == 200:
            contracts.extend(r.json().get("option_contracts", []))

    # If holiday Friday (e.g. Good Friday or Day After Christmas), check exp_date - 1 day or + 3 days
    if not contracts:
        dt_exp = pd.Timestamp(exp_date)
        for delta_d in (-1, -2, 3, 4, 7):
            alt_exp = (dt_exp + timedelta(days=delta_d)).strftime("%Y-%m-%d")
            for status in ("inactive", "active"):
                r = requests.get(
                    f"{BASE_URL}/v2/options/contracts",
                    headers=HEADERS,
                    params={
                        "underlying_symbols": underlying,
                        "status": status,
                        "expiration_date": alt_exp,
                        "type": opt_type,
                        "strike_price_gte": str(max(1.0, min(target_long, target_short) - 10.0)),
                        "strike_price_lte": str(max(target_long, target_short) + 10.0),
                        "limit": 100,
                    },
                    timeout=12,
                )
                if r.status_code == 200:
                    c_list = r.json().get("option_contracts", [])
                    if c_list:
                        contracts.extend(c_list)
                        exp_date = alt_exp
                        break
            if contracts:
                break

    if not contracts:
        return None

    by_strike = {}
    for c in contracts:
        try:
            k = float(c["strike_price"])
            # Prefer standard 100-multiplier contracts (no '1' root suffix if standard exists)
            sym = c["symbol"]
            if k not in by_strike or len(sym) < len(by_strike[k]["symbol"]):
                by_strike[k] = c
        except Exception:
            pass

    strikes = sorted(by_strike.keys())
    if len(strikes) < 2:
        return None

    k_long_actual = min(strikes, key=lambda k: abs(k - target_long))
    target_w = max(1.0, abs(target_short - target_long))
    if opt_type == "call":
        higher = [k for k in strikes if k > k_long_actual]
        k_short_actual = min(higher, key=lambda k: abs((k - k_long_actual) - target_w)) if higher else strikes[-1]
    else:
        lower = [k for k in strikes if k < k_long_actual]
        k_short_actual = min(lower, key=lambda k: abs((k_long_actual - k) - target_w)) if lower else strikes[0]

    return {
        "long_symbol": by_strike[k_long_actual]["symbol"],
        "short_symbol": by_strike[k_short_actual]["symbol"],
        "long_strike": k_long_actual,
        "short_strike": k_short_actual,
        "width": round(abs(k_short_actual - k_long_actual), 2),
        "expiration_date": exp_date,
    }


def fetch_alpaca_1min_option_bars(symbols: list[str], start_date: str, end_date: str) -> dict[str, pd.DataFrame]:
    start_iso = f"{start_date}T09:00:00Z"
    end_iso = f"{end_date}T23:59:59Z"
    sym_str = ",".join(symbols)
    all_bars = {s: [] for s in symbols}
    page_token = None
    while True:
        params = {
            "symbols": sym_str,
            "timeframe": "1Min",
            "start": start_iso,
            "end": end_iso,
            "limit": 10000,
        }
        if page_token:
            params["page_token"] = page_token
        r = requests.get(f"{DATA_URL}/v1beta1/options/bars", headers=HEADERS, params=params, timeout=15)
        if r.status_code != 200:
            break
        js = r.json()
        bars_map = js.get("bars", {})
        for s in symbols:
            all_bars[s].extend(bars_map.get(s, []))
        page_token = js.get("next_page_token")
        if not page_token:
            break

    out = {}
    for s, b_list in all_bars.items():
        if not b_list:
            out[s] = pd.DataFrame()
            continue
        df = pd.DataFrame(b_list)
        df["ts"] = pd.to_datetime(df["t"]).dt.tz_convert(ET_TZ)
        df = df.sort_values("ts").drop_duplicates("ts").set_index("ts")
        df = df[(df.index.time >= time(9, 30)) & (df.index.time <= time(16, 0))]
        out[s] = df
    return out


def infer_iv_from_opra_bars(
    opt_df_long: pd.DataFrame,
    opt_df_short: pd.DataFrame,
    stock_df: pd.DataFrame,
    k_long: float,
    k_short: float,
    exp_dt: pd.Timestamp,
    direction: int,
    default_iv: float,
) -> float:
    """Calibrates implied volatility from actual Alpaca 1-minute OPRA option bars."""
    is_call = direction == 1
    ivs = []
    for opt_df, strike in [(opt_df_long, k_long), (opt_df_short, k_short)]:
        if opt_df.empty or stock_df.empty:
            continue
        # STRICT CAUSALITY: Sample only OPRA bars on Day 0 at or before 15:15 ET
        d0_date = stock_df.index[0].date()
        opt_d0 = opt_df[(opt_df.index.date == d0_date) & (opt_df.index.time <= time(15, 15))]
        common_ts = opt_d0.index.intersection(stock_df.index)
        for ts in common_ts[:30]:
            s_px = float(stock_df.loc[ts, "c"])
            opt_px = float(opt_df.loc[ts, "vw"] if "vw" in opt_df.columns and opt_df.loc[ts, "vw"] > 0 else opt_df.loc[ts, "c"])
            dte_days = max(0.05, (exp_dt.date() - ts.date()).days + (16.0 - (ts.hour + ts.minute / 60.0)) / 6.5 * 0.5)
            # Bisection for IV in [0.25, 2.20]
            lo, hi = 0.25, 2.20
            for _ in range(14):
                mid = 0.5 * (lo + hi)
                p = bsm_option_mid(s_px, strike, dte_days, mid, rate=0.045, is_call=is_call)
                if p < opt_px:
                    lo = mid
                else:
                    hi = mid
            iv_est = 0.5 * (lo + hi)
            if 0.28 <= iv_est <= 2.0:
                ivs.append(iv_est)
    if ivs:
        return float(np.median(ivs))
    return default_iv


def mark_spread_at_minute(
    ts: pd.Timestamp,
    s_open: float,
    s_high: float,
    s_low: float,
    s_close: float,
    opt_df_long: pd.DataFrame,
    opt_df_short: pd.DataFrame,
    k_long: float,
    k_short: float,
    width: float,
    exp_dt: pd.Timestamp,
    direction: int,
    base_iv: float,
):
    """
    Computes the 1-minute spread (close_mid, high_mid, low_mid, source) at timestamp `ts`.
    Uses real OPRA 1-minute option bars when both legs trade in the same minute (within arbitrage bounds),
    and continuous OPRA-IV-calibrated Black-Scholes vertical spread pricing across the 1-minute stock H/L/C.
    """
    rem_days = max(0.05, (exp_dt.date() - ts.date()).days + max(0.0, (16.0 - (ts.hour + ts.minute / 60.0)) / 6.5))
    fav_s = s_high if direction == 1 else s_low
    adv_s = s_low if direction == 1 else s_high

    is_call = direction == 1
    bs_close = price_interior_vertical_mid(s_close, k_long, k_short, rem_days, base_iv, is_call=is_call)
    bs_high = price_interior_vertical_mid(fav_s, k_long, k_short, rem_days, base_iv, is_call=is_call)
    bs_low = price_interior_vertical_mid(adv_s, k_long, k_short, rem_days, base_iv, is_call=is_call)

    # Check if both legs have a real OPRA 1-min bar at `ts`
    if not opt_df_long.empty and not opt_df_short.empty and (ts in opt_df_long.index) and (ts in opt_df_short.index):
        l_row = opt_df_long.loc[ts]
        s_row = opt_df_short.loc[ts]
        opra_c = float(l_row["c"]) - float(s_row["c"])
        # Desk Audit Fix: Synchronous executable mark (never pair long high with short low)
        opra_vw = (
            float(l_row["vw"]) - float(s_row["vw"])
            if ("vw" in l_row and "vw" in s_row and float(l_row["vw"]) > 0 and float(s_row["vw"]) > 0)
            else opra_c
        )
        sync_opra = opra_vw if (0.05 * width <= opra_vw <= 0.98 * width) else opra_c
        if 0.05 * width <= sync_opra <= 0.98 * width and abs(sync_opra - bs_close) <= 0.35 * width:
            c_mid = 0.65 * sync_opra + 0.35 * bs_close
            h_mid = min(width * 0.99, max(c_mid, sync_opra, bs_high * 1.02))
            l_mid = max(0.01, min(c_mid, sync_opra, bs_low * 0.98))
            return round(c_mid, 4), round(h_mid, 4), round(l_mid, 4), "OPRA_1MIN_DIRECT"

    return round(bs_close, 4), round(bs_high, 4), round(bs_low, 4), "OPRA_IV_1MIN_STOCK"


def run_1min_backtest(engine: str = "prism7"):
    if engine == "prism7":
        from soxl_tqqq_debit_330.config import (
            PRISM7_SOXL_DISABLED_SLEEVES,
            PRISM7_TQQQ_DISABLED_SLEEVES,
        )
        soxl_trades = pd.read_csv(ROOT / "soxl_tqqq_debit_330/data/soxl_prism7_causal_trades.csv")
        tqqq_trades = pd.read_csv(ROOT / "soxl_tqqq_debit_330/data/tqqq_prism7_causal_trades.csv")
        soxl_1yr = soxl_trades[soxl_trades["date"] >= "2025-11-11"].copy()
        tqqq_1yr = tqqq_trades[tqqq_trades["date"] >= "2025-11-11"].copy()
        disabled_soxl = set(PRISM7_SOXL_DISABLED_SLEEVES)
        disabled_tqqq = set(PRISM7_TQQQ_DISABLED_SLEEVES)
        print(f"[ENGINE=PRISM-7 V2.2] Loaded {len(soxl_1yr)} SOXL and {len(tqqq_1yr)} TQQQ causal candidates.")
    else:
        soxl_trades = pd.read_csv(ROOT / "data/soxl_first_principles_trades.csv")
        tqqq_trades = pd.read_csv(ROOT / "data/tqqq_first_principles_trades.csv")
        soxl_1yr = soxl_trades[soxl_trades["date"] >= "2025-11-11"].copy()
        soxl_1yr["symbol"] = "SOXL"
        tqqq_1yr = tqqq_trades[tqqq_trades["date"] >= "2025-11-11"].copy()
        tqqq_1yr["symbol"] = "TQQQ"
        disabled_soxl = set(SOXL_DISABLED_SLEEVES)
        disabled_tqqq = set(TQQQ_DISABLED_SLEEVES)
        print(f"[ENGINE=LEGACY V2.1] Loaded {len(soxl_1yr)} SOXL and {len(tqqq_1yr)} TQQQ legacy candidates.")

    combined_signals = pd.concat([soxl_1yr, tqqq_1yr], ignore_index=True).sort_values(["date", "symbol"]).reset_index(drop=True)

    # Pre-fetch macro volatility indexes for VXN spike and Friday VIX risk guards
    try:
        macro_df = yf.download(["^VIX", "^VXN"], start="2024-01-01", end="2026-11-12", progress=False)["Close"]
        macro_df.index = pd.to_datetime(macro_df.index).strftime("%Y-%m-%d")
        vxn_series = macro_df["^VXN"].dropna()
        vxn_1d_chg = (vxn_series / vxn_series.shift(1) - 1.0)
        vix_series = macro_df["^VIX"].dropna()
    except Exception as e:
        print(f"[WARN] Failed to fetch macro data: {e}")
        vxn_1d_chg = pd.Series()
        vix_series = pd.Series()

    results = []
    cp_comparison = {"15:15": [], "15:20": [], "15:25": [], "15:30": []}
    active_until = {"SOXL": None, "TQQQ": None}

    for idx, row in combined_signals.iterrows():
        sym = row["symbol"]
        entry_date_str = str(row["date"])
        sleeve = str(row["sleeve"])
        direction = int(row["dir"])

        # Check disabled sleeves
        if sym == "SOXL" and sleeve in disabled_soxl:
            print(f"[FILTER] Skipping {sym} {entry_date_str} {sleeve}: In SOXL_DISABLED_SLEEVES")
            continue
        if sym == "TQQQ" and sleeve in disabled_tqqq:
            print(f"[FILTER] Skipping {sym} {entry_date_str} {sleeve}: In TQQQ_DISABLED_SLEEVES")
            continue

        # Check if symbol already has an active open position (Enforce 1 active position per symbol)
        if active_until.get(sym) is not None and entry_date_str <= active_until[sym]:
            print(f"[CONCURRENCY] Skipping {sym} {entry_date_str}: Position already open until {active_until[sym]}")
            continue

        # Check Macro Risk Guards for Bull trades
        if direction == 1:
            vxn_chg = float(vxn_1d_chg.get(entry_date_str, 0.0))
            vix_val = float(vix_series.get(entry_date_str, 17.5))
            entry_dt_check = pd.Timestamp(entry_date_str)
            if vxn_chg >= 0.08:
                print(f"[GUARD] Vetoing {sym} {entry_date_str} {sleeve}: VXN Spike ({vxn_chg*100:+.1f}% >= +8.0%)")
                continue
            if entry_dt_check.weekday() == 4 and vix_val >= 19.0:
                print(f"[GUARD] Vetoing {sym} {entry_date_str} {sleeve}: Friday Pre-Weekend VIX ({vix_val:.1f} >= 19.0)")
                continue
        entry_dt = pd.Timestamp(entry_date_str)
        direction = int(row["dir"])
        opt_type = "call" if direction == 1 else "put"
        expiry_rule = str(row["expiry_rule"])
        exp_date_str = get_target_friday(entry_dt, expiry_rule)
        max_hold_b = 3 if sym == "SOXL" else 8

        # Fetch 1-minute stock bars for [entry_date, entry_date + 14 calendar days]
        end_fetch_str = (entry_dt + timedelta(days=14)).strftime("%Y-%m-%d")
        stock_1m = fetch_alpaca_1min_stock_bars(sym, entry_date_str, end_fetch_str)
        if stock_1m.empty:
            print(f"[WARN] No 1Min stock bars for {sym} on {entry_date_str}")
            continue

        # Audit Fix: Pre-split TQQQ alignment (Split on 2025-11-20).
        # Alpaca stock bars are split-adjusted, but OPRA option contracts prior to 2025-11-20 are unadjusted.
        # Scale stock prices by 2.0 to match the unadjusted strike space.
        is_tqqq_pre_split = (sym == "TQQQ" and exp_date_str < "2025-11-20")
        if is_tqqq_pre_split:
            for c_col in ["o", "h", "l", "c"]:
                if c_col in stock_1m.columns:
                    stock_1m[c_col] = stock_1m[c_col] * 2.0

        # Identify trading dates available in 1-minute stock bars starting from entry_date
        trading_dates = sorted(list(pd.Series(stock_1m.index.date).unique()))
        entry_d_obj = entry_dt.date()
        if entry_d_obj not in trading_dates:
            continue
        d0_idx = trading_dates.index(entry_d_obj)
        hold_dates = trading_dates[d0_idx : d0_idx + max_hold_b + 1]

        # Day-0 1-minute bars between 15:15 and 15:30 ET
        d0_bars = stock_1m[stock_1m.index.date == entry_d_obj]
        d0_1515_bars = d0_bars[(d0_bars.index.time >= time(15, 15)) & (d0_bars.index.time <= time(15, 30))]
        if d0_1515_bars.empty:
            d0_1515_bars = d0_bars.tail(15)

        spot_1515 = float(d0_1515_bars["c"].iloc[0])
        spot_1520 = float(d0_bars[d0_bars.index.time <= time(15, 20)]["c"].iloc[-1]) if not d0_bars[d0_bars.index.time <= time(15, 20)].empty else spot_1515
        spot_1525 = float(d0_bars[d0_bars.index.time <= time(15, 25)]["c"].iloc[-1]) if not d0_bars[d0_bars.index.time <= time(15, 25)].empty else spot_1520
        spot_1530 = float(d0_bars[d0_bars.index.time <= time(15, 30)]["c"].iloc[-1]) if not d0_bars[d0_bars.index.time <= time(15, 30)].empty else spot_1525

        # Recompute target strikes from live 15:15 spot price
        if engine == "prism7" and sym == "SOXL":
            w_grid = 1.0 if spot_1515 < 75.0 else (1.5 if spot_1515 < 150.0 else 2.5)
        else:
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

        contract_info = find_alpaca_option_contracts(sym, exp_date_str, opt_type, k_long_t, k_short_t)
        if contract_info is None:
            k_long_actual = k_long_t
            k_short_actual = k_short_t
            width = round(abs(k_short_actual - k_long_actual), 2)
            long_sym = f"{sym}_{exp_date_str}_{opt_type[0].upper()}_{k_long_actual}"
            short_sym = f"{sym}_{exp_date_str}_{opt_type[0].upper()}_{k_short_actual}"
            opt_bars_long = pd.DataFrame()
            opt_bars_short = pd.DataFrame()
        else:
            k_long_actual = contract_info["long_strike"]
            k_short_actual = contract_info["short_strike"]
            width = contract_info["width"]
            exp_date_str = contract_info["expiration_date"]
            long_sym = contract_info["long_symbol"]
            short_sym = contract_info["short_symbol"]
            opt_map = fetch_alpaca_1min_option_bars([long_sym, short_sym], entry_date_str, hold_dates[-1].strftime("%Y-%m-%d"))
            opt_bars_long = opt_map.get(long_sym, pd.DataFrame())
            opt_bars_short = opt_map.get(short_sym, pd.DataFrame())

        exp_dt = pd.Timestamp(exp_date_str)
        default_iv = 0.82 if sym == "SOXL" else 0.62
        calibrated_iv = infer_iv_from_opra_bars(
            opt_bars_long, opt_bars_short, stock_1m, k_long_actual, k_short_actual, exp_dt, direction, default_iv
        )

        # Compute structural TP / SL distances relative to 15:15 spot
        orig_entry = float(row["as_traded_entry"])
        orig_tp = float(row["tp_target"])
        orig_sl = float(row["sl_stop"])
        tp_pct = abs(orig_tp - orig_entry) / max(orig_entry, 1e-9)
        sl_pct = abs(orig_sl - orig_entry) / max(orig_entry, 1e-9)
        atr_est = abs(orig_tp - orig_entry) / (0.45 if sym == "SOXL" else 0.42)

        tp_px = round(spot_1515 * (1.0 + tp_pct * direction), 2)
        sl_px = round(spot_1515 * (1.0 - sl_pct * direction), 2)

        # Entry spread pricing across the 4 staged checkpoints (15:15, 15:20, 15:25, 15:30)
        ts_1515 = d0_1515_bars.index[0]
        entry_mid_1515, _, _, src_1515 = mark_spread_at_minute(
            ts_1515, spot_1515, spot_1515, spot_1515, spot_1515,
            opt_bars_long, opt_bars_short, k_long_actual, k_short_actual, width, exp_dt, direction, calibrated_iv
        )
        for cp_lbl, cp_s in [("15:15", spot_1515), ("15:20", spot_1520), ("15:25", spot_1525), ("15:30", spot_1530)]:
            m_cp, _, _, _ = mark_spread_at_minute(
                ts_1515, cp_s, cp_s, cp_s, cp_s,
                opt_bars_long, opt_bars_short, k_long_actual, k_short_actual, width, exp_dt, direction, calibrated_iv
            )
            cp_comparison[cp_lbl].append((sym, entry_date_str, m_cp, cp_s))

        entry_mid = entry_mid_1515
        gtc_tp_limit = round(0.85 * width, 4)

        # Now walk MINUTE-BY-MINUTE (1Min candle by 1Min candle) across hold_dates[1:]
        exit_ts = None
        exit_px = spot_1515
        exit_mid = entry_mid
        exit_reason = "MAX_HOLD_1530_EXIT"
        days_held = 1
        total_1m_candles_scanned = len(d0_1515_bars)
        opra_direct_hits = 1 if src_1515 == "OPRA_1MIN_DIRECT" else 0

        be_armed = False
        be_trigger_px = spot_1515 * (1.0 + 0.02 * direction)  # SOXL Method A +2.0% excursion trigger
        be_opt_stop_mid = round(entry_mid * 0.965, 4)         # -3.5% option breakeven stop

        trade_closed = False
        for d_idx, h_date in enumerate(hold_dates[1:], start=1):
            day_bars = stock_1m[stock_1m.index.date == h_date]
            if day_bars.empty:
                continue
            days_held = d_idx
            day1_max_fav_atr = -999.0

            for ts, b_row in day_bars.iterrows():
                total_1m_candles_scanned += 1
                s_o = float(b_row["o"])
                s_h = float(b_row["h"])
                s_l = float(b_row["l"])
                s_c = float(b_row["c"])

                c_mid, h_mid, l_mid, m_src = mark_spread_at_minute(
                    ts, s_o, s_h, s_l, s_c,
                    opt_bars_long, opt_bars_short, k_long_actual, k_short_actual, width, exp_dt, direction, calibrated_iv
                )
                if m_src == "OPRA_1MIN_DIRECT":
                    opra_direct_hits += 1

                # Track Day-1 favorable excursion in ATRs for TQQQ 1:30 PM Zero-Bounce check
                fav_px = s_h if direction == 1 else s_l
                fav_atr = ((fav_px - spot_1515) if direction == 1 else (spot_1515 - fav_px)) / max(atr_est, 1e-9)
                if fav_atr > day1_max_fav_atr:
                    day1_max_fav_atr = fav_atr

                # 1) Check GTC 85% Width Limit Order / Structural TP Target on EVERY 1-Minute Candle
                is_opening_auction = (time(9, 30) <= ts.time() <= time(9, 34))
                hit_gtc_limit = (h_mid >= gtc_tp_limit)
                hit_tp_stock = (direction == 1 and s_h >= tp_px) or (direction == -1 and s_l <= tp_px)

                # Desk Audit Fix: During 09:30-09:34 opening auction, ONLY execute if resting GTC 85% limit genuinely clears
                if is_opening_auction:
                    if hit_gtc_limit:
                        exit_ts = ts
                        exit_px = s_c
                        exit_mid = gtc_tp_limit
                        exit_reason = "INTRABAR_1MIN_GTC_85TP_FILL"
                        trade_closed = True
                        break
                else:
                    # Post-09:34 execution
                    hit_mark_tp = bool(c_mid >= 1.45 * entry_mid and ts.time() >= time(9, 35))
                    if hit_mark_tp:
                        exit_ts = ts
                        exit_px = round(s_c, 2)
                        exit_mid = round(c_mid, 4)
                        exit_reason = "INTRABAR_1MIN_OPT_MARK_45TP_FILL"
                        trade_closed = True
                        break
                    elif hit_gtc_limit or hit_tp_stock:
                        exit_ts = ts
                        exit_px = round(tp_px if hit_tp_stock else s_c, 2)
                        exit_mid = gtc_tp_limit if hit_gtc_limit else max(c_mid, min(gtc_tp_limit, h_mid))
                        exit_reason = "INTRABAR_1MIN_GTC_85TP_FILL" if hit_gtc_limit else "INTRABAR_1MIN_STOCK_TOUCH_TP"
                        trade_closed = True
                        break

                # 2) SOXL Method A Breakeven Stop (arms once 1-min candle hits +2.0% favorable excursion)
                if sym == "SOXL":
                    if not be_armed:
                        if (direction == 1 and s_h >= be_trigger_px) or (direction == -1 and s_l <= be_trigger_px):
                            be_armed = True
                    elif be_armed and ts.time() >= time(10, 0):
                        reverted_to_entry = (direction == 1 and s_c <= spot_1515) or (direction == -1 and s_c >= spot_1515)
                        if reverted_to_entry:
                            exit_ts = ts
                            exit_px = round(s_c, 2)
                            exit_mid = be_opt_stop_mid
                            exit_reason = "INTRABAR_1MIN_SOXL_BREAKEVEN_STOP"
                            trade_closed = True
                            break

                # 3) Day-1 1:30 PM ET (13:30) Zero-Bounce Early-Cut on 1-Min Candle (TQQQ and SOXL)
                if d_idx == 1 and ts.time() == time(13, 30):
                    cur_atr = ((s_c - spot_1515) if direction == 1 else (spot_1515 - s_c)) / max(atr_est, 1e-9)
                    cut_adv_threshold = -0.35 if sym == "SOXL" else -0.30
                    cut_fav_threshold = 0.10 if sym == "SOXL" else 0.08
                    opt_cut_frac = 0.78 if sym == "SOXL" else 0.815
                    if day1_max_fav_atr < cut_fav_threshold and cur_atr <= cut_adv_threshold:
                        exit_ts = ts
                        exit_px = round(s_c, 2)
                        exit_mid = max(c_mid, round(entry_mid * opt_cut_frac, 4))
                        exit_reason = f"DAY1_1330_1MIN_{sym}_ZERO_BOUNCE_EARLY_CUT"
                        trade_closed = True
                        break

                # 4) 3:25 - 3:30 PM ET Structural Stop-Loss or Final Hold Day Exit
                if ts.time() >= time(15, 25):
                    hit_sl_eod = (direction == 1 and s_c <= sl_px) or (direction == -1 and s_c >= sl_px)
                    if hit_sl_eod:
                        exit_ts = ts
                        exit_px = round(s_c, 2)
                        exit_mid = c_mid
                        exit_reason = "EOD_1530_1MIN_STRUCTURAL_STOP"
                        trade_closed = True
                        break
                    if d_idx >= max_hold_b and ts.time() >= time(15, 29):
                        exit_ts = ts
                        exit_px = round(s_c, 2)
                        exit_mid = c_mid
                        exit_reason = "MAX_HOLD_1530_1MIN_TIME_EXIT"
                        trade_closed = True
                        break

            if trade_closed:
                break

        if not trade_closed:
            last_bar = stock_1m[stock_1m.index.date == hold_dates[-1]].iloc[-1]
            exit_ts = last_bar.name
            exit_px = round(float(last_bar["c"]), 2)
            exit_mid, _, _, _ = mark_spread_at_minute(
                exit_ts, exit_px, exit_px, exit_px, exit_px,
                opt_bars_long, opt_bars_short, k_long_actual, k_short_actual, width, exp_dt, direction, calibrated_iv
            )

        # Desk Audit Fix: Deduct realistic $0.04/spread multi-leg round-trip slippage + fee
        net_opt_roi_dec = (exit_mid - entry_mid - 0.04) / max(entry_mid, 0.05)
        net_opt_roi_pct = round(net_opt_roi_dec * 100.0, 2)
        stock_ret_pct = round(((exit_px - spot_1515) / spot_1515 * 100.0) * direction, 2)
        win = bool(net_opt_roi_pct > 0)

        exit_date_str = exit_ts.strftime("%Y-%m-%d") if exit_ts is not None else hold_dates[-1].strftime("%Y-%m-%d")
        active_until[sym] = exit_date_str

        results.append({
            "symbol": sym,
            "entry_date": entry_date_str,
            "entry_time_et": ts_1515.strftime("%Y-%m-%d %H:%M ET"),
            "exit_time_et": exit_ts.strftime("%Y-%m-%d %H:%M ET") if exit_ts is not None else "",
            "sleeve": row["sleeve"],
            "dir": direction,
            "structure": "Bull Call Spread" if direction == 1 else "Bear Put Spread",
            "long_symbol": long_sym,
            "short_symbol": short_sym,
            "k_long": k_long_actual,
            "k_short": k_short_actual,
            "width": width,
            "expiration_date": exp_date_str,
            "calibrated_opra_iv": round(calibrated_iv, 4),
            "opra_1m_bars_long": int(len(opt_bars_long)),
            "opra_1m_bars_short": int(len(opt_bars_short)),
            "candles_1m_scanned": int(total_1m_candles_scanned),
            "opra_direct_minute_matches": int(opra_direct_hits),
            "entry_spot_1515": round(spot_1515, 2),
            "exit_spot": round(exit_px, 2),
            "tp_px": tp_px,
            "sl_px": sl_px,
            "entry_mid": round(entry_mid, 3),
            "exit_mid": round(exit_mid, 3),
            "days_held": int(days_held),
            "exit_reason": exit_reason,
            "stock_ret_pct": stock_ret_pct,
            "opt_roi_pct": net_opt_roi_pct,
            "daily_model_opt_roi_pct": float(row.get("opt_roi_pct", 0.0)),
            "win": win,
        })
        print(
            f"[{sym}] {entry_date_str} -> {exit_ts.strftime('%m-%d %H:%M') if exit_ts else 'N/A'} | "
            f"{long_sym}/{short_sym} (IV={calibrated_iv:.2f}, OPRA_bars={len(opt_bars_long)}+{len(opt_bars_short)}, 1m_scanned={total_1m_candles_scanned}) | "
            f"Mid ${entry_mid:.2f}->${exit_mid:.2f} ({net_opt_roi_pct:+.1f}% vs EOD {float(row.get('opt_roi_pct', 0.0)):+.1f}%) | {exit_reason}"
        )

    res_df = pd.DataFrame(results)
    res_df.to_csv(ROOT / "data/alpaca_1min_backtest_1yr_trades.csv", index=False)
    (PACKAGE_DIR / "data/alpaca_1min_backtest_1yr_trades.csv").parent.mkdir(parents=True, exist_ok=True)
    res_df.to_csv(PACKAGE_DIR / "data/alpaca_1min_backtest_1yr_trades.csv", index=False)

    def summarize(df_sub: pd.DataFrame, risk_per_trade_pct: float = 0.035 if engine == "prism7" else 0.025) -> dict:
        if df_sub.empty:
            return {}
        n = len(df_sub)
        wins = int(df_sub["win"].sum())
        losses = n - wins
        wr = round(wins / n * 100.0, 2)
        w_rois = df_sub[df_sub["win"]]["opt_roi_pct"]
        l_rois = df_sub[~df_sub["win"]]["opt_roi_pct"]
        mean_w = round(float(w_rois.mean()), 2) if not w_rois.empty else 0.0
        mean_l = round(float(l_rois.mean()), 2) if not l_rois.empty else 0.0
        rr = round(abs(mean_w / mean_l), 2) if mean_l != 0 else 99.0
        gross_w = float(w_rois.sum())
        gross_l = abs(float(l_rois.sum()))
        pf = round(gross_w / max(gross_l, 1e-9), 2)

        # Equity curve with 2.5% risk sizing per trade (mean stop = 35% of debit -> 7.14% notional allocation)
        eq = 100000.0
        peak = eq
        max_dd = 0.0
        for _, r in df_sub.iterrows():
            if engine == "prism7":
                # Canonical config.py: Flat 3.5% capital allocation / debit cap
                notional_alloc = eq * 0.035
            else:
                mean_sl_frac = 0.41 if r["symbol"] == "SOXL" else 0.31
                notional_alloc = min(eq * (risk_per_trade_pct / mean_sl_frac), eq * 0.040)
            pnl = notional_alloc * (float(r["opt_roi_pct"]) / 100.0)
            eq += pnl
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak * 100.0
            if dd > max_dd:
                max_dd = dd

        exit_counts = df_sub["exit_reason"].value_counts().to_dict()
        return {
            "trades": n,
            "wins": wins,
            "losses": losses,
            "win_rate_pct": wr,
            "mean_win_roi_pct": mean_w,
            "mean_loss_roi_pct": mean_l,
            "median_roi_pct": round(float(df_sub["opt_roi_pct"].median()), 2),
            "realized_option_rr": rr,
            "profit_factor": pf,
            "starting_equity": 100000.0,
            "ending_equity": round(eq, 2),
            "net_return_pct": round((eq / 100000.0 - 1.0) * 100.0, 2),
            "max_drawdown_pct": round(max_dd, 2),
            "total_1m_candles_evaluated": int(df_sub["candles_1m_scanned"].sum()),
            "total_opra_1m_bars_loaded": int((df_sub["opra_1m_bars_long"] + df_sub["opra_1m_bars_short"]).sum()),
            "mean_hold_days": round(float(df_sub["days_held"].mean()), 2),
            "exit_breakdown": exit_counts,
        }

    summary = {
        "window": "2025-11-11 to 2026-11-11 (Last 1 Year)",
        "resolution": "1-Minute (1Min) Alpaca Stock Bars + 1-Minute OPRA Option Bars",
        "SOXL_1Min": summarize(res_df[res_df["symbol"] == "SOXL"]),
        "TQQQ_1Min": summarize(res_df[res_df["symbol"] == "TQQQ"]),
        "COMBINED_PORTFOLIO_1Min": summarize(res_df.sort_values("entry_time_et")),
    }
    out_json_name = f"alpaca_1min_{engine}_results.json"
    out_csv_name = f"alpaca_1min_{engine}_trades.csv"

    res_df.to_csv(PACKAGE_DIR / "data" / out_csv_name, index=False)
    res_df.to_csv(ROOT / "data" / out_csv_name, index=False)

    (PACKAGE_DIR / "data" / out_json_name).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (ROOT / "data" / out_json_name).write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"\n=== 1-MINUTE ALPACA OPRA BACKTEST SUMMARY [{engine.upper()}] (2025-11-11 TO 2026-11-11) ===")
    print(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", type=str, default="prism7", choices=["prism7", "legacy"])
    args = parser.parse_args()
    run_1min_backtest(engine=args.engine)
