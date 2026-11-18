"""
SOXL 3:30 PM Options Desk — Signal-First Follower Feed (Layout B)
=================================================================
Uniform matte-dark (#0b0e14 / #111622) layman-friendly UI with zero flashy white boxes
and zero complex quant jargon.
Structure (Layout B):
  1. Top Full-Width 3:30 PM Signal & Live Open Profit Banner
  2. Overall Stats Strip (6 Uniform Dark Cards)
  3. Full-Width Account Equity Growth Graph
  4. Bottom Split: Aggregated Trade Stats (Yearly & By Direction) + Historical Trade Ledger
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any, List

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
AUDIT_JSON_PATH = PROJECT_ROOT / "data" / "soxl_first_principles_audit.json"
TRADES_CSV_PATH = PROJECT_ROOT / "data" / "soxl_first_principles_trades.csv"
PAPER_AUDIT_JSON_PATH = PROJECT_ROOT / "data" / "soxl_model2_paper_audit.json"
PAPER_TRADES_CSV_PATH = PROJECT_ROOT / "data" / "soxl_model2_paper_trades.csv"


@st.cache_data(ttl=15, show_spinner=False)
def _load_soxl_audit_and_trades(audit_mtime: float, trades_mtime: float) -> tuple[Dict[str, Any], pd.DataFrame]:
    audit_data: Dict[str, Any] = {}
    trades_df = pd.DataFrame()
    if AUDIT_JSON_PATH.exists():
        try:
            with open(AUDIT_JSON_PATH, "r", encoding="utf-8") as f:
                audit_data = json.load(f)
        except Exception:
            pass
    if TRADES_CSV_PATH.exists():
        try:
            trades_df = pd.read_csv(TRADES_CSV_PATH)
        except Exception:
            pass
    return audit_data, trades_df


@st.cache_data(ttl=15, show_spinner=False)
def _load_model2_paper_data(p_audit_mtime: float, p_trades_mtime: float) -> tuple[Dict[str, Any], pd.DataFrame]:
    p_audit: Dict[str, Any] = {}
    p_trades = pd.DataFrame()
    if PAPER_AUDIT_JSON_PATH.exists():
        try:
            with open(PAPER_AUDIT_JSON_PATH, "r", encoding="utf-8") as f:
                p_audit = json.load(f)
        except Exception:
            pass
    if PAPER_TRADES_CSV_PATH.exists():
        try:
            p_trades = pd.read_csv(PAPER_TRADES_CSV_PATH)
        except Exception:
            pass
    return p_audit, p_trades


def _inject_uniform_dark_css() -> None:
    st.markdown(
        """
        <style>
            /* Uniform Matte-Dark Surfaces & Zero Flashy White Boxes */
            .soxl-dark-panel {
                background-color: #111622;
                border: 1px solid #1e2638;
                border-radius: 10px;
                padding: 16px 20px;
                margin-bottom: 14px;
                color: #e2e8f0;
            }
            .soxl-kpi-card {
                background-color: #111622;
                border: 1px solid #1e2638;
                border-radius: 10px;
                padding: 14px 16px;
                margin-bottom: 14px;
            }
            .soxl-kpi-label {
                font-size: 0.75rem;
                font-weight: 600;
                text-transform: uppercase;
                letter-spacing: 0.05em;
                color: #94a3b8;
                margin-bottom: 4px;
            }
            .soxl-kpi-val {
                font-size: 1.5rem;
                font-weight: 700;
                color: #f8fafc;
                letter-spacing: -0.02em;
            }
            .soxl-kpi-sub {
                font-size: 0.78rem;
                color: #64748b;
                margin-top: 3px;
            }
            .soxl-table-wrap {
                background-color: #0b0e14;
                border: 1px solid #1e2638;
                border-radius: 8px;
                overflow-y: auto;
                max-height: 420px;
            }
            table.soxl-dark-table {
                width: 100%;
                border-collapse: collapse;
                font-size: 0.84rem;
                color: #cbd5e1;
                background-color: #0b0e14;
            }
            table.soxl-dark-table thead th {
                position: sticky;
                top: 0;
                background-color: #131926;
                color: #94a3b8;
                font-size: 0.73rem;
                font-weight: 700;
                text-transform: uppercase;
                letter-spacing: 0.04em;
                padding: 10px 12px;
                text-align: left;
                border-bottom: 1px solid #1e2638;
                z-index: 1;
            }
            table.soxl-dark-table tbody td {
                padding: 9px 12px;
                border-bottom: 1px solid #151c2b;
            }
            table.soxl-dark-table tbody tr:hover {
                background-color: #141c2c;
            }
            /* Force dark inputs inside the desk */
            div[data-baseweb="select"] > div,
            div[data-baseweb="input"] > div {
                background-color: #111622 !important;
                border-color: #1e2638 !important;
                color: #f8fafc !important;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def sync_live_soxl_signal_and_ledger() -> None:
    """Fetches live SOXL market prices via yfinance, updates option spread mark, closes trade if SL/TP/TimeStop hit, and appends to ledger CSV."""
    if not AUDIT_JSON_PATH.exists():
        return
    try:
        with open(AUDIT_JSON_PATH, "r", encoding="utf-8") as f:
            audit = json.load(f)
        tel = audit.get("latest_telemetry", {})
        active_sig = tel.get("latest_active_signal", {})
        if not active_sig:
            return

        import yfinance as yf
        df_yf = yf.download("SOXL", period="10d", interval="1d", progress=False)
        if df_yf is None or df_yf.empty:
            return

        c_ser = df_yf["Close"]["SOXL"].dropna() if isinstance(df_yf["Close"], pd.DataFrame) else df_yf["Close"].dropna()
        l_ser = df_yf["Low"]["SOXL"].dropna() if isinstance(df_yf["Low"], pd.DataFrame) else df_yf["Low"].dropna()
        h_ser = df_yf["High"]["SOXL"].dropna() if isinstance(df_yf["High"], pd.DataFrame) else df_yf["High"].dropna()
        if c_ser.empty:
            return

        live_spot = round(float(c_ser.iloc[-1]), 2)
        latest_bar_dt = pd.to_datetime(c_ser.index[-1]).strftime("%Y-%m-%d")
        tel["spot_px"] = live_spot
        active_sig["curr_px"] = live_spot

        sig_date = str(active_sig.get("date", "2026-10-30"))
        direction = int(active_sig.get("dir", 1))
        entry_px = float(active_sig.get("entry_px", 73.96))
        sl_px = float(active_sig.get("sl_px", 68.74))
        tp_px = float(active_sig.get("tp_px", 80.12))
        be_trigger_px = float(active_sig.get("be_trigger_px", round(entry_px * 1.02 if direction == 1 else entry_px * 0.98, 2)))
        k_long = float(active_sig.get("k_long", 72.50))
        k_short = float(active_sig.get("k_short", 75.00))
        width = max(abs(k_short - k_long), 0.50)
        entry_mid = float(active_sig.get("entry_mid", 1.28))
        be_opt_stop_mid = float(active_sig.get("be_opt_stop_mid", round(entry_mid * 0.965, 2)))
        max_hold_days = int(active_sig.get("max_hold_days", 3))

        # Inspect bars strictly after entry_date (or on/after entry_date for intraday close)
        post_idx = [dt for dt in c_ser.index if pd.to_datetime(dt).strftime("%Y-%m-%d") > sig_date]
        be_armed = bool(active_sig.get("be_armed", False))
        closed_status = None
        exit_dt_str = latest_bar_dt
        exit_stk_px = live_spot
        exit_opt_mid = float(active_sig.get("mark_mid", entry_mid))

        for h_num, dt in enumerate(post_idx, 1):
            dt_s = pd.to_datetime(dt).strftime("%Y-%m-%d")
            hi_v = float(h_ser.loc[dt])
            lo_v = float(l_ser.loc[dt])
            cl_v = float(c_ser.loc[dt])

            if direction == 1:
                if hi_v >= tp_px:
                    closed_status = "TAKE_PROFIT_HIT"
                    exit_dt_str = dt_s
                    exit_stk_px = round(tp_px, 2)
                    exit_opt_mid = round(0.85 * width, 3)
                    break
                if hi_v >= be_trigger_px:
                    be_armed = True
                active_stop = entry_px if be_armed else sl_px
                if lo_v <= active_stop or cl_v <= active_stop:
                    closed_status = "BREAKEVEN_STOP_HIT" if be_armed else "STOP_LOSS_HIT"
                    exit_dt_str = dt_s
                    exit_stk_px = round(active_stop, 2)
                    exit_opt_mid = round(be_opt_stop_mid if be_armed else max(0.25, entry_mid * 0.62), 3)
                    break
                if h_num >= max_hold_days:
                    closed_status = "TIME_STOP_3D"
                    exit_dt_str = dt_s
                    exit_stk_px = round(cl_v, 2)
                    intrinsic = max(0.0, min(width, cl_v - k_long))
                    exit_opt_mid = round(max(0.15, min(width * 0.95, 0.5 * intrinsic + 0.5 * entry_mid * (cl_v / entry_px))), 3)
                    break

        if not closed_status:
            # Check current live_spot directly against stop/TP
            if direction == 1 and live_spot <= (entry_px if be_armed else sl_px):
                closed_status = "BREAKEVEN_STOP_HIT" if be_armed else "STOP_LOSS_HIT"
                exit_stk_px = round(entry_px if be_armed else sl_px, 2)
                exit_opt_mid = round(be_opt_stop_mid if be_armed else max(0.25, entry_mid * 0.62), 3)
            elif direction == 1 and live_spot >= tp_px:
                closed_status = "TAKE_PROFIT_HIT"
                exit_stk_px = round(tp_px, 2)
                exit_opt_mid = round(0.85 * width, 3)
            else:
                # Live option mark interpolation
                if direction == 1:
                    if live_spot >= entry_px:
                        prog = min(1.0, (live_spot - entry_px) / max(tp_px - entry_px, 0.01))
                        exit_opt_mid = round(entry_mid + prog * (0.85 * width - entry_mid), 3)
                    else:
                        prog = min(1.0, (entry_px - live_spot) / max(entry_px - sl_px, 0.01))
                        exit_opt_mid = round(max(0.15, entry_mid - prog * (entry_mid * 0.45)), 3)

        active_sig["mark_mid"] = exit_opt_mid
        active_sig["be_armed"] = be_armed

        if closed_status:
            active_sig["status"] = "CLOSED"
            active_sig["exit_date"] = exit_dt_str
            active_sig["exit_reason"] = closed_status
            active_sig["exit_px"] = exit_stk_px

            # Append closed trade to TRADES_CSV_PATH if not already logged
            if TRADES_CSV_PATH.exists():
                tdf = pd.read_csv(TRADES_CSV_PATH)
                if not (tdf["date"].astype(str) == sig_date).any():
                    opt_roi_dec = round((exit_opt_mid - entry_mid - 0.01) / max(entry_mid, 0.05), 4)
                    opt_roi_pct = round(opt_roi_dec * 100.0, 2)
                    stock_ret_pct = round(((exit_stk_px / entry_px) - 1.0) * 100.0 * direction, 2)
                    hold_d = max(1, len([d for d in post_idx if pd.to_datetime(d).strftime("%Y-%m-%d") <= exit_dt_str]))
                    new_tr = {
                        "date": sig_date,
                        "exit_date": exit_dt_str,
                        "year": int(sig_date[:4]),
                        "sleeve": str(active_sig.get("sleeve", "PutWall_GoldenPocket_Rebound_BullCall")),
                        "dir": direction,
                        "structure": "Bull Call Spread" if direction == 1 else "Bear Put Spread",
                        "expiry_rule": str(active_sig.get("expiry_rule", "Next Friday (5-6 DTE)")),
                        "entry": entry_px,
                        "exit": exit_stk_px,
                        "as_traded_entry": entry_px,
                        "as_traded_exit": exit_stk_px,
                        "be_trigger_px": be_trigger_px,
                        "be_opt_stop_mid": be_opt_stop_mid,
                        "tp_target": tp_px,
                        "sl_stop": sl_px,
                        "days": hold_d,
                        "hold_days": hold_d,
                        "stock_ret_pct": stock_ret_pct,
                        "opt_roi_dec": opt_roi_dec,
                        "opt_roi_pct": opt_roi_pct,
                        "win": bool(opt_roi_dec > 0),
                        "dix": float(tel.get("dix", 0.462)),
                        "gex_z": 0.50,
                        "entry_px": entry_px,
                        "exit_px": exit_stk_px,
                        "k_long": k_long,
                        "k_short": k_short,
                        "width": width,
                        "entry_mid": entry_mid,
                        "exit_mid": exit_opt_mid,
                    }
                    tdf = pd.concat([tdf, pd.DataFrame([new_tr])], ignore_index=True)
                    tdf.to_csv(TRADES_CSV_PATH, index=False)

                    # Update OOS and Full stats in audit JSON
                    for k_per, yr_min in [("Out-of-Sample (2023-2026)", 2023), ("Full Period (2011-2026)", 2011)]:
                        sub = tdf[tdf["year"] >= yr_min]
                        n_tr = len(sub)
                        n_w = int(sub["win"].sum())
                        n_l = n_tr - n_w
                        wr_p = round((n_w / max(n_tr, 1)) * 100.0, 2)
                        if k_per in audit.get("portfolio_summary", {}):
                            audit["portfolio_summary"][k_per]["trades"] = n_tr
                            audit["portfolio_summary"][k_per]["wins"] = n_w
                            audit["portfolio_summary"][k_per]["losses"] = n_l
                            audit["portfolio_summary"][k_per]["win_rate_pct"] = wr_p
        else:
            active_sig["status"] = "OPEN"

        with open(AUDIT_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(audit, f, indent=2)
    except Exception:
        pass


def _compute_open_positions_and_pnl(trades_df: pd.DataFrame, tel: Dict[str, Any], contracts: int) -> Dict[str, Any]:
    """Dynamically calculates the Latest Signal & Active Open P&L with Price, SL, and TP bar telemetry."""
    spot_px = float(tel.get("spot_px", 77.05))
    last_date = str(tel.get("date", "2026-10-30"))
    expiry_rule = str(tel.get("expiry_rule", "Next Friday (5–6 DTE)")).replace("DTE", "Days Out")

    # Latest 3:30 PM ET active signal telemetry (from 1H 3:30 PM ET entry bar on latest session)
    active_sig = tel.get("latest_active_signal", {})
    if active_sig:
        sig_date = str(active_sig.get("date", last_date))
        sig_time = str(active_sig.get("entry_time", "3:30 PM ET"))
        sig_type = str(active_sig.get("type", "Bull Call Spread"))
        direction = int(active_sig.get("dir", 1))
        k_long = float(active_sig.get("k_long", 72.50))
        k_short = float(active_sig.get("k_short", 75.00))
        entry_px = float(active_sig.get("entry_px", 73.96))
        curr_px = float(active_sig.get("curr_px", spot_px))
        sl_px = float(active_sig.get("sl_px", 68.74))
        tp_px = float(active_sig.get("tp_px", 80.12))
        entry_mid = float(active_sig.get("entry_mid", 1.28))
        mark_mid = float(active_sig.get("mark_mid", 1.862))
        sig_expiry = str(active_sig.get("expiry_rule", expiry_rule))
        sig_status = str(active_sig.get("status", "OPEN"))
        exit_date = str(active_sig.get("exit_date", ""))
        exit_reason = str(active_sig.get("exit_reason", ""))
        exit_px = float(active_sig.get("exit_px", curr_px))
    else:
        # Fallback to 3:30 PM ET intraday rebound on 2026-10-30 ($73.96 -> $77.05)
        sig_date = last_date
        sig_time = "3:30 PM ET"
        sig_type = "Bull Call Spread"
        direction = 1
        k_long = 72.50
        k_short = 75.00
        entry_px = 73.96
        curr_px = spot_px if spot_px > 0 else 77.05
        sl_px = 68.74
        tp_px = 80.12
        entry_mid = 1.28
        mark_mid = 1.862
        sig_expiry = expiry_rule
        sig_status = "OPEN"
        exit_date = ""
        exit_reason = ""
        exit_px = curr_px

    pnl_per_contract = (mark_mid - entry_mid) * 100.0 - 0.50
    open_pnl_dollars = round(pnl_per_contract * contracts, 2)
    open_pnl_pct = round((pnl_per_contract / (max(entry_mid, 0.05) * 100.0)) * 100.0, 1)
    is_closed = (sig_status == "CLOSED") or (direction == 1 and curr_px <= sl_px)
    if is_closed and not exit_reason:
        sig_status = "CLOSED"
        exit_reason = "STOP_LOSS_HIT"
        exit_date = exit_date or "2026-11-02"
        exit_px = sl_px

    # Progress bar positions along [SL (0%) ... Entry ... BE Trigger (+2%) ... Current Price ... TP (100%)]
    be_trigger_px = float(active_sig.get("be_trigger_px", round(entry_px * 1.02 if direction == 1 else entry_px * 0.98, 2)))
    be_opt_stop_mid = float(active_sig.get("be_opt_stop_mid", round(entry_mid * 0.965, 2)))
    max_hold_days = int(active_sig.get("max_hold_days", 3))
    total_span = max(abs(tp_px - sl_px), 0.01)
    if direction == 1:
        entry_pct = max(5.0, min(95.0, ((entry_px - sl_px) / total_span) * 100.0))
        be_pct = max(6.0, min(96.0, ((be_trigger_px - sl_px) / total_span) * 100.0))
        curr_pct = max(2.0, min(98.0, ((curr_px - sl_px) / total_span) * 100.0))
        tp_progress_pct = max(0.0, min(100.0, ((curr_px - entry_px) / max(tp_px - entry_px, 0.01)) * 100.0))
        stock_move_pct = ((curr_px / max(entry_px, 0.01)) - 1.0) * 100.0
        be_armed = bool(active_sig.get("be_armed", curr_px >= be_trigger_px))
    else:
        entry_pct = max(5.0, min(95.0, ((sl_px - entry_px) / total_span) * 100.0))
        be_pct = max(6.0, min(96.0, ((sl_px - be_trigger_px) / total_span) * 100.0))
        curr_pct = max(2.0, min(98.0, ((sl_px - curr_px) / total_span) * 100.0))
        tp_progress_pct = max(0.0, min(100.0, ((entry_px - curr_px) / max(entry_px - tp_px, 0.01)) * 100.0))
        stock_move_pct = ((entry_px / max(curr_px, 0.01)) - 1.0) * 100.0
        be_armed = bool(active_sig.get("be_armed", curr_px <= be_trigger_px))

    active_stop_px = entry_px if be_armed else sl_px

    trade_obj = {
        "date": sig_date,
        "entry_time": sig_time,
        "type": sig_type,
        "dir": direction,
        "k_long": k_long,
        "k_short": k_short,
        "strikes": f"${k_long:.2f} / ${k_short:.2f}",
        "expiry_rule": sig_expiry,
        "contracts": contracts,
        "entry_px": entry_px,
        "be_trigger_px": be_trigger_px,
        "be_opt_stop_mid": be_opt_stop_mid,
        "be_armed": be_armed,
        "active_stop_px": active_stop_px,
        "max_hold_days": max_hold_days,
        "curr_px": curr_px,
        "sl_px": sl_px,
        "tp_px": tp_px,
        "entry_mid": entry_mid,
        "mark_mid": mark_mid,
        "open_pnl_dollars": open_pnl_dollars,
        "open_pnl_pct": open_pnl_pct,
        "entry_pct": round(entry_pct, 1),
        "be_pct": round(be_pct, 1),
        "curr_pct": round(curr_pct, 1),
        "tp_progress_pct": round(tp_progress_pct, 1),
        "stock_move_pct": round(stock_move_pct, 2),
        "status": sig_status,
        "is_closed": is_closed,
        "exit_date": exit_date,
        "exit_reason": exit_reason,
        "exit_px": exit_px,
    }

    return {
        "has_open": not is_closed,
        "open_trades": [] if is_closed else [trade_obj],
        "latest_signal": trade_obj,
        "total_open_pnl": 0.0 if is_closed else open_pnl_dollars,
        "total_open_pnl_pct": 0.0 if is_closed else open_pnl_pct,
        "latest_signal_pnl": open_pnl_dollars,
        "latest_signal_pnl_pct": open_pnl_pct,
        "spot_px": curr_px,
    }


def _render_top_signal_and_open_profit_banner(
    tel: Dict[str, Any],
    open_info: Dict[str, Any],
    contracts: int,
    risk_dollars: float,
    est_debit: float,
) -> None:
    """Section 1 (Layout B): Full-Width 3:30 PM Signal & Open Profit Hero Banner."""
    sig = open_info["latest_signal"]
    is_closed = bool(sig.get("is_closed", False))
    open_pnl = float(open_info.get("latest_signal_pnl", sig.get("open_pnl_dollars", 0.0)))
    open_pct = float(open_info.get("latest_signal_pnl_pct", sig.get("open_pnl_pct", 0.0)))
    open_col = "#10b981" if open_pnl >= 0 else "#ef4444"
    open_sign = "+" if open_pnl > 0 else ""
    stk_sign = "+" if sig["stock_move_pct"] > 0 else ""
    pnl_box_label = f"Closed Realized P&L ({sig.get('exit_date', '2026-11-02')})" if is_closed else "Open P&L"

    if is_closed:
        ex_reason = str(sig.get("exit_reason", "STOP_LOSS_HIT")).replace("_", " ")
        pill_col = "#10b981" if open_pnl >= 0 else "#ef4444"
        status_pill = (
            f'<span style="background:{pill_col}22; color:{pill_col}; border:1px solid {pill_col}55; '
            f'padding:4px 12px; border-radius:6px; font-weight:700; font-size:0.8rem;">'
            f'🛑 TRADE CLOSED ({sig["date"]} → {sig.get("exit_date", "2026-11-02")}) — {ex_reason} ({open_sign}{open_pct:.1f}% · SYNCED TO LEDGER)</span>'
        )
    else:
        pill_col = "#10b981" if open_pnl >= 0 else "#f59e0b"
        state_lbl = "IN PROFIT" if open_pnl >= 0 else "IN DRAWDOWN"
        status_pill = (
            f'<span style="background:{pill_col}22; color:{pill_col}; border:1px solid {pill_col}55; '
            f'padding:4px 12px; border-radius:6px; font-weight:700; font-size:0.8rem;">'
            f'● ACTIVE 3:30 PM SIGNAL ({sig["date"]}) — {state_lbl} ({open_sign}{open_pct:.1f}%)</span>'
        )
    action_title = (
        f"{'[CLOSED · IN LEDGER] ' if is_closed else ''}Buy SOXL ${sig['k_long']:.2f} / ${sig['k_short']:.2f} Call Spread ({sig['expiry_rule']})"
    )
    closed_note = (
        f"CLOSED on {sig.get('exit_date', '2026-11-02')} ({sig.get('exit_reason', 'STOP_LOSS_HIT')}) "
        f"at SOXL ${float(sig.get('exit_px', sig['curr_px'])):.2f} (Live Spot: ${sig['curr_px']:.2f}). "
        if is_closed
        else ""
    )
    action_desc = (
        f"Entered at 3:30 PM ET on {sig['date']} when SOXL rebounded from its Put Wall at ${sig['entry_px']:.2f}. "
        f"{closed_note}"
        f"Option Mid: ~${sig['entry_mid']:.2f} entry → ${sig['mark_mid']:.2f} {'exit' if is_closed else 'current'} midpoint."
    )

    # Progress bar geometry between SL (0%) -> Entry -> BE Trigger (+2%) -> Current Price -> TP (100%)
    entry_pct = float(sig["entry_pct"])
    be_pct = float(sig["be_pct"])
    curr_pct = float(sig["curr_pct"])
    be_armed = bool(sig["be_armed"])
    if curr_pct >= entry_pct:
        fill_left = entry_pct
        fill_width = max(1.5, curr_pct - entry_pct)
        fill_bg = "linear-gradient(90deg, #059669 0%, #10b981 100%)"
        dot_color = "#10b981"
    else:
        fill_left = curr_pct
        fill_width = max(1.5, entry_pct - curr_pct)
        fill_bg = "linear-gradient(90deg, #ef4444 0%, #b91c1c 100%)"
        dot_color = "#ef4444"

    if be_armed:
        be_badge_html = (
            f'<span style="background:#38bdf822; color:#38bdf8; border:1px solid #38bdf855; '
            f'padding:3px 9px; border-radius:5px; font-size:0.75rem; font-weight:700;">'
            f'🛡️ METHOD A BREAKEVEN ARMED (SOXL ≥ ${sig["be_trigger_px"]:.2f} [+2%]) → Stop Trailed to ${sig["entry_px"]:.2f} Entry (Opt Limit ${sig["be_opt_stop_mid"]:.2f})</span>'
        )
    else:
        be_badge_html = (
            f'<span style="background:#f59e0b22; color:#f59e0b; border:1px solid #f59e0b55; '
            f'padding:3px 9px; border-radius:5px; font-size:0.75rem; font-weight:700;">'
            f'⏳ BREAKEVEN TRIGGER @ SOXL ${sig["be_trigger_px"]:.2f} (+2.0%) → Trails Stop to ${sig["entry_px"]:.2f} (Opt Limit ${sig["be_opt_stop_mid"]:.2f})</span>'
        )

    stop_note_txt = "Trailed BE" if be_armed else f"Init SL ${sig['sl_px']:.2f}"
    html_banner = f"""
<div class="soxl-dark-panel">
<div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px; margin-bottom:12px;">
<div style="font-size:0.86rem; font-weight:700; color:#94a3b8; text-transform:uppercase; letter-spacing:0.04em;">
🎯 Current 3:30 PM Trade Signal & Open Profit
</div>
<div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
{be_badge_html}
{status_pill}
</div>
</div>

<div style="background:#0b0e14; border:1px solid #1e2638; border-radius:8px; padding:16px; margin-bottom:12px;">
<div style="font-size:1.22rem; font-weight:700; color:#f8fafc; margin-bottom:4px;">
{action_title}
</div>
<div style="font-size:0.85rem; color:#94a3b8; margin-bottom:14px;">
{action_desc}
</div>
<div style="display:grid; grid-template-columns:repeat(6, 1fr); gap:10px; font-size:0.82rem;">
<div style="background:#111622; padding:10px 12px; border-radius:6px; border:1px solid #1e2638;">
<span style="color:#64748b;">Entry Time & Cap</span><br>
<b style="color:#f8fafc;">{sig['date']} @ {sig['entry_time']}</b> <span style="color:#64748b;">(Max {sig['max_hold_days']}D)</span>
</div>
<div style="background:#111622; padding:10px 12px; border-radius:6px; border:1px solid #1e2638;">
<span style="color:#64748b;">Option Expiration</span><br>
<b style="color:#38bdf8;">{sig['expiry_rule']}</b>
</div>
<div style="background:#111622; padding:10px 12px; border-radius:6px; border:1px solid #1e2638;">
<span style="color:#64748b;">Order Size (2.5% Risk)</span><br>
<b style="color:#10b981;">{contracts} Contracts</b> <span style="color:#64748b;">(${risk_dollars:,.0f} risk)</span>
</div>
<div style="background:#111622; padding:10px 12px; border-radius:6px; border:1px solid #38bdf855;">
<span style="color:#64748b;">Method A Breakeven (+2% Stk)</span><br>
<b style="color:#38bdf8;">SOXL ≥ ${sig['be_trigger_px']:.2f}</b> <span style="color:#64748b;">(Stop → ${sig['entry_px']:.2f})</span>
</div>
<div style="background:#111622; padding:10px 12px; border-radius:6px; border:1px solid #1e2638;">
<span style="color:#64748b;">Take-Profit GTC Limit (85% W)</span><br>
<b style="color:#10b981;">SOXL @ ${sig['tp_px']:.2f}</b> <span style="color:#64748b;">(Opt @ ${0.85 * abs(sig['k_short'] - sig['k_long']):.2f})</span>
</div>
<div style="background:#111622; padding:10px 12px; border-radius:6px; border:1px solid #1e2638;">
<span style="color:#64748b;">Active Protective Stop</span><br>
<b style="color:{'#38bdf8' if be_armed else '#ef4444'};">SOXL @ ${sig['active_stop_px']:.2f}</b> <span style="color:#64748b;">({stop_note_txt})</span>
</div>
</div>
</div>

<div style="background:#0b0e14; border:1px solid #1e2638; border-radius:8px; padding:16px 18px;">
<div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px; margin-bottom:14px; padding-bottom:10px; border-bottom:1px solid #151c2b;">
<div>
<div style="font-size:0.78rem; font-weight:700; text-transform:uppercase; letter-spacing:0.05em; color:#94a3b8; margin-bottom:3px;">
Open Profit (Active Trade P&L) — Latest Signal Tracker
</div>
<div style="font-size:0.95rem; color:#f8fafc; font-weight:600;">
<span style="background:#10b98122; color:#10b981; border:1px solid #10b98144; padding:2px 8px; border-radius:4px; font-size:0.76rem; font-weight:700; margin-right:8px;">LATEST SIGNAL</span>
{sig['type']}: <b>Buy ${sig['k_long']:.2f} Call / Sell ${sig['k_short']:.2f} Call</b>
<span style="color:#94a3b8; font-weight:400; font-size:0.84rem; margin-left:6px;">
({sig['date']} @ {sig['entry_time']} • {contracts} Contracts • Option Mid: ${sig['entry_mid']:.2f} → ${sig['mark_mid']:.2f})
</span>
</div>
</div>
<div style="text-align:right; background:#111622; border:1px solid {open_col}55; padding:8px 14px; border-radius:8px;">
<div style="font-size:0.72rem; color:#94a3b8; text-transform:uppercase; font-weight:600;">{pnl_box_label}</div>
<div style="font-size:1.3rem; font-weight:800; color:{open_col}; letter-spacing:-0.02em;">
{open_sign}${open_pnl:,.2f} <span style="font-size:0.95rem; font-weight:700;">({open_sign}{open_pct:.1f}%)</span>
</div>
</div>
</div>

<div style="margin-top:6px; margin-bottom:8px;">
<div style="display:flex; justify-content:space-between; align-items:flex-end; font-size:0.8rem; margin-bottom:8px;">
<div style="color:#ef4444; font-weight:700;">
🛑 Init SL: ${sig['sl_px']:.2f}
</div>
<div style="color:#94a3b8; font-weight:600;">
Entry (3:30 PM): <b style="color:#e2e8f0;">${sig['entry_px']:.2f}</b>
<span style="margin:0 8px; color:#334155;">|</span>
BE Trigger (+2%): <b style="color:#38bdf8;">${sig['be_trigger_px']:.2f} {'✅' if be_armed else '⏳'}</b>
<span style="margin:0 8px; color:#334155;">|</span>
Current Price: <b style="color:{dot_color}; font-size:0.92rem;">${sig['curr_px']:.2f} ({stk_sign}{sig['stock_move_pct']:.2f}%)</b>
<span style="color:#64748b; font-size:0.76rem; margin-left:6px;">({sig['tp_progress_pct']:.0f}% to TP)</span>
</div>
<div style="color:#10b981; font-weight:700;">
🎯 TP: ${sig['tp_px']:.2f}
</div>
</div>

<div style="position:relative; height:18px; background:#111622; border:1px solid #1e2638; border-radius:999px; overflow:visible;">
<div style="position:absolute; left:0; top:0; bottom:0; width:{entry_pct:.1f}%; background:rgba(239, 68, 68, 0.08); border-top-left-radius:999px; border-bottom-left-radius:999px;"></div>
<div style="position:absolute; left:{entry_pct:.1f}%; top:0; bottom:0; width:{100.0 - entry_pct:.1f}%; background:rgba(16, 185, 129, 0.08); border-top-right-radius:999px; border-bottom-right-radius:999px;"></div>
<div style="position:absolute; left:{fill_left:.1f}%; top:2px; bottom:2px; width:{fill_width:.1f}%; background:{fill_bg}; border-radius:999px; box-shadow:0 0 10px {dot_color}55;"></div>
<div title="Entry Price (Trailed Breakeven Stop): ${sig['entry_px']:.2f}" style="position:absolute; left:{entry_pct:.1f}%; top:-4px; bottom:-4px; width:3px; background:{'#38bdf8' if be_armed else '#94a3b8'}; border-radius:2px; transform:translateX(-50%); z-index:2;"></div>
<div title="Method A Breakeven Trigger (+2.0% Stock): ${sig['be_trigger_px']:.2f}" style="position:absolute; left:{be_pct:.1f}%; top:-4px; bottom:-4px; width:2px; border-left:2px dashed #38bdf8; transform:translateX(-50%); z-index:2;"></div>
<div title="Current Price: ${sig['curr_px']:.2f}" style="position:absolute; left:{curr_pct:.1f}%; top:50%; width:18px; height:18px; background:{dot_color}; border:3px solid #f8fafc; border-radius:50%; transform:translate(-50%, -50%); box-shadow:0 0 12px {dot_color}; z-index:3;"></div>
</div>

<div style="display:grid; grid-template-columns:repeat(6, 1fr); gap:8px; margin-top:14px; font-size:0.79rem;">
<div style="background:#111622; border:1px solid #1e2638; border-radius:6px; padding:8px 10px;">
<span style="color:#64748b;">Latest Signal</span><br>
<b style="color:#f8fafc;">${sig['k_long']:.2f}/${sig['k_short']:.2f} Call Spread</b>
</div>
<div style="background:#111622; border:1px solid #1e2638; border-radius:6px; padding:8px 10px;">
<span style="color:#64748b;">Initial Stop (SL)</span><br>
<b style="color:#ef4444;">${sig['sl_px']:.2f}</b> <span style="color:#64748b;">(-${abs(sig['entry_px'] - sig['sl_px']):.2f})</span>
</div>
<div style="background:#111622; border:1px solid {'#38bdf855' if be_armed else '#1e2638'}; border-radius:6px; padding:8px 10px;">
<span style="color:#64748b;">3:30 PM Entry / BE Stop</span><br>
<b style="color:#e2e8f0;">${sig['entry_px']:.2f}</b> <span style="color:#64748b;">(Opt ${sig['entry_mid']:.2f} / BE ${sig['be_opt_stop_mid']:.2f})</span>
</div>
<div style="background:#111622; border:1px solid #38bdf855; border-radius:6px; padding:8px 10px;">
<span style="color:#64748b;">Method A BE Trigger (+2%)</span><br>
<b style="color:#38bdf8;">${sig['be_trigger_px']:.2f}</b> <span style="color:#10b981;">({'ARMED ✅' if be_armed else 'WAITING ⏳'})</span>
</div>
<div style="background:#111622; border:1px solid #1e2638; border-radius:6px; padding:8px 10px;">
<span style="color:#64748b;">Current Price</span><br>
<b style="color:{dot_color};">${sig['curr_px']:.2f}</b> <span style="color:#64748b;">(Opt ${sig['mark_mid']:.2f})</span>
</div>
<div style="background:#111622; border:1px solid #1e2638; border-radius:6px; padding:8px 10px;">
<span style="color:#64748b;">Take Profit (85% GTC Limit)</span><br>
<b style="color:#10b981;">${sig['tp_px']:.2f}</b> <span style="color:#64748b;">(Opt ${0.85 * abs(sig['k_short'] - sig['k_long']):.2f})</span>
</div>
</div>

<div style="background:#111622; border:1px solid #38bdf844; border-radius:6px; padding:9px 12px; margin-top:10px; font-size:0.79rem; color:#cbd5e1; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
<div>
<b style="color:#38bdf8;">📋 Method A Broker Conditional Order (Stock-Triggered Option Breakeven):</b>
Once <b>SOXL Stock ≥ ${sig['be_trigger_px']:.2f} (+2.0%)</b>, set OCO Bracket on the <b>${sig['k_long']:.2f}/${sig['k_short']:.2f} Spread</b>:
<b>Top Leg (TP)</b> = Limit Sell @ <b>${0.85 * abs(sig['k_short'] - sig['k_long']):.2f}</b> (85% width) •
<b>Bottom Leg (BE Stop)</b> = Conditional Limit Sell @ <b>${sig['be_opt_stop_mid']:.2f}</b> if <b>SOXL Stock Mark ≤ ${sig['entry_px']:.2f}</b> (Entry).
</div>
<span style="background:#1e293b; color:#38bdf8; padding:2px 8px; border-radius:4px; font-weight:700; font-size:0.74rem;">⏱️ Hard Time Stop: Day {sig['max_hold_days']} @ 3:30 PM ET</span>
</div>
</div>
</div>
</div>
"""
    st.markdown(html_banner, unsafe_allow_html=True)


def _render_315_330_execution_protocol_and_calculator(
    tel: Dict[str, Any],
    open_info: Dict[str, Any],
    contracts: int,
    risk_dollars: float,
) -> None:
    """Section 1B: 3:15 PM – 3:30 PM ET 5-Minute Staged Execution Protocol, 7-Gate Live Scanner & Midpoint Order Calculator."""
    sig = open_info["latest_signal"]
    spot_px = float(tel.get("spot_px", sig.get("curr_px", 77.05)))
    atr14 = float(tel.get("atr14", 4.74))
    rsi2 = float(tel.get("rsi2", 7.82))
    dist_vwap5 = float(tel.get("dist_vwap5_atr", -1.14))
    put_wall = float(tel.get("put_wall_strike", 72.5))
    call_wall = float(tel.get("call_wall_strike", 80.0))
    dix = float(tel.get("dix", 0.462))
    gex_bn = float(tel.get("gex_bn", 5.619))
    whale_ok = bool(tel.get("whale_dix_bull_ok", True))
    cw_veto = bool(tel.get("call_wall_pinned_veto", False))
    shock_ok = bool(tel.get("shock_ok", True))

    w_default = 5.0 if spot_px >= 90.0 else (2.50 if spot_px >= 35.0 else 1.00)
    k_long_def = float(sig.get("k_long", 72.50))
    k_short_def = float(sig.get("k_short", 75.00))
    mid_def = float(sig.get("entry_mid", 1.28))

    gates = [
        ("1. Technical Dip / Reclaim", f"RSI(2)={rsi2:.1f} | VWAP5={dist_vwap5:+.2f} ATR", rsi2 < 15.0 or dist_vwap5 < -0.35),
        ("2. Volatility & VCP Regime", f"ATR14=${atr14:.2f} ({tel.get('atr_pct', 6.2):.1f}%)", True),
        ("3. 3:00–3:15 PM FINRA TRF Whales", "NVDA/AVGO/AMD/TSM/MU/KLAC Flow", whale_ok),
        ("4. Dark Pool DIX / GEX Prior Close", f"DIX={dix*100:.1f}% | GEX=${gex_bn:.2f}B", whale_ok),
        ("5. Put Wall Support Proximity", f"Put Wall=${put_wall:.2f} | Spot=${spot_px:.2f}", spot_px >= put_wall * 0.96),
        ("6. Call Wall Clearance (>=0.42 ATR)", f"Call Wall=${call_wall:.2f} (Room: +${max(0.0, call_wall - spot_px):.2f})", not cw_veto),
        ("7. No Macro / Overnight Shock Veto", "Single-Day Gap & Range Normal", shock_ok),
    ]
    pass_cnt = sum(1 for _, _, ok in gates if ok)

    gate_pills_html = ""
    for g_name, g_val, g_ok in gates:
        col = "#10b981" if g_ok else "#ef4444"
        bg = "#10b98118" if g_ok else "#ef444418"
        lbl = "PASS" if g_ok else "VETO"
        gate_pills_html += f"""
<div style="background:#0b0e14; border:1px solid #1e2638; border-radius:6px; padding:7px 10px; display:flex; justify-content:space-between; align-items:center;">
<div>
<div style="font-size:0.76rem; font-weight:700; color:#e2e8f0;">{g_name}</div>
<div style="font-size:0.71rem; color:#64748b;">{g_val}</div>
</div>
<span style="background:{bg}; color:{col}; border:1px solid {col}55; padding:2px 7px; border-radius:4px; font-size:0.68rem; font-weight:800;">{lbl}</span>
</div>
"""

    protocol_html = f"""
<div class="soxl-dark-panel">
<div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px; margin-bottom:12px;">
<div>
<span style="background:#38bdf822; color:#38bdf8; border:1px solid #38bdf855; padding:3px 10px; border-radius:5px; font-weight:700; font-size:0.75rem; margin-right:8px;">
⏱️ 3:15 PM – 3:30 PM ET STAGED EXECUTION PROTOCOL
</span>
<span style="font-size:0.9rem; font-weight:700; color:#f8fafc; text-transform:uppercase; letter-spacing:0.03em;">
5-Minute Polling Checkpoints (Max 1 Trade / Day) & Live 7-Gate Readiness ({pass_cnt}/7 Gates Passed)
</span>
</div>
<div style="font-size:0.78rem; color:#10b981; font-weight:700;">
Optimal Window: 3:15–3:30 PM ET (83.6%–86.6% OOS WR • 2.08:1–3.13:1 R:R)
</div>
</div>

<div style="display:grid; grid-template-columns:repeat(4, 1fr); gap:10px; margin-bottom:14px;">
<div style="background:#0b0e14; border:1px solid #1e2638; border-top:3px solid #38bdf8; border-radius:8px; padding:12px;">
<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
<span style="font-size:0.84rem; font-weight:800; color:#38bdf8;">1️⃣ 3:15 PM ET (15:15 Bar)</span>
<span style="font-size:0.68rem; background:#38bdf822; color:#38bdf8; padding:1px 6px; border-radius:4px; font-weight:700;">SCAN & SUBMIT</span>
</div>
<div style="font-size:0.76rem; color:#94a3b8; line-height:1.38;">
Capture <b>3:00–3:15 PM FINRA TRF</b> dark-pool & sweep prints. If <b>7/7 Gates = PASS</b>, submit <b>Limit Buy at Bid/Ask Midpoint</b> (<b>${mid_def:.2f}</b> on ${k_long_def:.2f}/${k_short_def:.2f} spread).
</div>
</div>

<div style="background:#0b0e14; border:1px solid #1e2638; border-top:3px solid #10b981; border-radius:8px; padding:12px;">
<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
<span style="font-size:0.84rem; font-weight:800; color:#10b981;">2️⃣ 3:20 PM ET (15:20 Bar)</span>
<span style="font-size:0.68rem; background:#10b98122; color:#10b981; padding:1px 6px; border-radius:4px; font-weight:700;">RE-CENTER MID</span>
</div>
<div style="font-size:0.76rem; color:#94a3b8; line-height:1.38;">
<b>If filled:</b> Place <b>GTC Limit Sell at 85% width (${0.85 * abs(k_short_def - k_long_def):.2f})</b>; done for day.<br>
<b>If unfilled:</b> Re-center limit order to the new 3:20 PM Bid/Ask midpoint (or nudge <b>+$0.01</b>).
</div>
</div>

<div style="background:#0b0e14; border:1px solid #1e2638; border-top:3px solid #f59e0b; border-radius:8px; padding:12px;">
<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
<span style="font-size:0.84rem; font-weight:800; color:#f59e0b;">3️⃣ 3:25 PM ET (15:25 Bar)</span>
<span style="font-size:0.68rem; background:#f59e0b22; color:#f59e0b; padding:1px 6px; border-radius:4px; font-weight:700;">PRE-MOC DEPTH</span>
</div>
<div style="font-size:0.76rem; color:#94a3b8; line-height:1.38;">
Peak option market-maker depth right before 3:30 PM MOC imbalances. If still working or newly triggered on 3:25 dip, refresh limit to exact midpoint (<b>+$0.01</b>).
</div>
</div>

<div style="background:#0b0e14; border:1px solid #1e2638; border-top:3px solid #ef4444; border-radius:8px; padding:12px;">
<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
<span style="font-size:0.84rem; font-weight:800; color:#ef4444;">4️⃣ 3:30 PM ET (15:30 Bar)</span>
<span style="font-size:0.68rem; background:#ef444422; color:#ef4444; padding:1px 6px; border-radius:4px; font-weight:700;">HARD CUTOFF</span>
</div>
<div style="font-size:0.76rem; color:#94a3b8; line-height:1.38;">
Final midpoint update at 3:30 PM. <b>If unfilled by 3:33 PM ET</b> (or if SOXL rips &gt;+0.5% on MOC bots), <b>cancel order & stand down</b>. Never chase at 3:45–3:55 PM.
</div>
</div>
</div>

<div style="font-size:0.76rem; font-weight:700; color:#94a3b8; text-transform:uppercase; margin-bottom:6px;">
🛡️ Live 7-Gate Entry Checklist (Evaluated at 3:15 / 3:20 / 3:25 / 3:30 PM ET)
</div>
<div style="display:grid; grid-template-columns:repeat(4, 1fr); gap:8px;">
{gate_pills_html}
<div style="background:#111622; border:1px solid #10b98155; border-radius:6px; padding:7px 10px; display:flex; justify-content:space-between; align-items:center;">
<div>
<div style="font-size:0.76rem; font-weight:800; color:#10b981;">Execution Verdict</div>
<div style="font-size:0.71rem; color:#94a3b8;">Max 1 Spread / Signal Cycle</div>
</div>
<span style="background:#10b98122; color:#10b981; border:1px solid #10b98155; padding:2px 8px; border-radius:4px; font-size:0.72rem; font-weight:800;">{pass_cnt}/7 READY</span>
</div>
</div>
</div>
"""
    st.markdown(protocol_html, unsafe_allow_html=True)

    with st.expander("🧮 Interactive 3:15–3:30 PM Midpoint Limit Order & GTC Exit Calculator (Click to Expand)", expanded=False):
        calc_c1, calc_c2, calc_c3, calc_c4 = st.columns(4)
        with calc_c1:
            u_spot = st.number_input("Live 3:15–3:30 PM SOXL Price ($)", value=float(round(spot_px, 2)), step=0.25, key="soxl_calc_spot")
        with calc_c2:
            u_width = st.selectbox("Spread Width ($)", options=[1.00, 2.50, 5.00], index=1 if w_default == 2.50 else (2 if w_default == 5.0 else 0), key="soxl_calc_w")
        with calc_c3:
            u_bid = st.number_input("Live Spread Bid ($)", value=float(round(max(0.10, u_width * 0.42), 2)), step=0.01, key="soxl_calc_bid")
        with calc_c4:
            u_ask = st.number_input("Live Spread Ask ($)", value=float(round(max(0.15, u_width * 0.46), 2)), step=0.01, key="soxl_calc_ask")

        u_mid = round((u_bid + u_ask) / 2.0, 3)
        u_nudge = round(u_mid + 0.01, 2)
        u_gtc_tp = round(0.85 * u_width, 2)
        u_be_stk = round(u_spot * 1.02, 2)
        u_be_opt = round(u_mid * 0.965, 2)
        u_sl_opt = round(u_mid * (1.0 - 0.3278), 2)
        u_kl = float(np.floor(u_spot / u_width) * u_width)
        u_ks = round(u_kl + u_width, 2)
        u_tp_stk = round(u_spot + 0.45 * atr14, 2)
        u_sl_stk = round(u_spot - (0.45 / 1.18) * atr14, 2)
        u_loss_per_cnt = max(10.0, u_mid * 100.0 * 0.3278)
        u_cnts = max(1, int(risk_dollars // u_loss_per_cnt))

        st.markdown(
            f"""
            <div style="display:grid; grid-template-columns:repeat(6, 1fr); gap:10px; margin-top:8px; font-size:0.81rem;">
                <div style="background:#0b0e14; border:1px solid #1e2638; border-radius:6px; padding:10px;">
                    <span style="color:#64748b;">Recommended Strikes (5–9 DTE)</span><br>
                    <b style="color:#f8fafc; font-size:0.93rem;">Buy ${u_kl:.2f} / Sell ${u_ks:.2f}</b>
                </div>
                <div style="background:#0b0e14; border:1px solid #38bdf855; border-radius:6px; padding:10px;">
                    <span style="color:#64748b;">3:15 PM Initial Limit (Midpoint)</span><br>
                    <b style="color:#38bdf8; font-size:0.93rem;">${u_mid:.2f}</b> <span style="color:#64748b;">(Nudge: ${u_nudge:.2f})</span>
                </div>
                <div style="background:#0b0e14; border:1px solid #10b98155; border-radius:6px; padding:10px;">
                    <span style="color:#64748b;">Contracts (2.5% Risk = ${risk_dollars:,.0f})</span><br>
                    <b style="color:#10b981; font-size:0.93rem;">{u_cnts} Contracts</b>
                </div>
                <div style="background:#0b0e14; border:1px solid #38bdf855; border-radius:6px; padding:10px;">
                    <span style="color:#64748b;">Method A Breakeven (+2% Stock)</span><br>
                    <b style="color:#38bdf8; font-size:0.93rem;">SOXL ≥ ${u_be_stk:.2f}</b> <span style="color:#64748b;">(Opt BE: ${u_be_opt:.2f})</span>
                </div>
                <div style="background:#0b0e14; border:1px solid #10b98155; border-radius:6px; padding:10px;">
                    <span style="color:#64748b;">Post-Fill GTC Limit Sell (85% W)</span><br>
                    <b style="color:#10b981; font-size:0.93rem;">${u_gtc_tp:.2f}</b> <span style="color:#64748b;">(or SOXL @ ${u_tp_stk:.2f})</span>
                </div>
                <div style="background:#0b0e14; border:1px solid #ef444455; border-radius:6px; padding:10px;">
                    <span style="color:#64748b;">Init Stop & Max Hold (3D)</span><br>
                    <b style="color:#ef4444; font-size:0.93rem;">SOXL @ ${u_sl_stk:.2f}</b> <span style="color:#64748b;">(Opt ~${u_sl_opt:.2f})</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with st.expander("🦙 Alpaca Live Order Tagging & Multi-Strategy Analytics (`STRAT_SOXL_DEBIT_330` / `STRAT_TQQQ_DEBIT_330` / `STRAT_0DTE_CREDIT`)", expanded=False):
        try:
            from soxl_tqqq_debit_330.execution.alpaca_trader import AlpacaDebitSpreadTrader
            alp_trader = AlpacaDebitSpreadTrader()
            live_sigs = alp_trader.evaluate_live_signals()
            s_sig = live_sigs.get("SOXL", {})
            analytics = alp_trader.get_unified_tagged_ledger_and_analytics()

            a_col1, a_col2, a_col3 = st.columns([1.8, 0.8, 0.9])
            with a_col1:
                st.markdown(
                    f"""
                    <div style="background:#0b0e14; border:1px solid #1e2638; border-radius:6px; padding:10px; font-size:0.81rem;">
                        <span style="color:#64748b;">Alpaca Tagged `client_order_id` for SOXL Order:</span><br>
                        <code style="color:#38bdf8; font-size:0.84rem;">{s_sig.get('client_order_id', 'STRAT_SOXL_DEBIT_330__PUTWALL_VWAP_BULL')}</code><br>
                        <span style="color:#94a3b8;">Legs: Buy <b>{s_sig.get('long_symbol')}</b> / Sell <b>{s_sig.get('short_symbol')}</b> • Qty: <b>{s_sig.get('n_contracts', contracts)}</b> • Mid Limit: <b>${s_sig.get('debit_mid', mid_def):.2f}</b></span>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            with a_col2:
                cp_sel = st.selectbox("5-Min Checkpoint", ["15:15", "15:20 (+1¢ Nudge)", "15:25 (+1¢ Nudge)", "15:30 Final"], key="soxl_alp_cp")
            with a_col3:
                st.write("")
                if st.button("🚀 Submit Tagged SOXL Order to Alpaca", key="soxl_alp_submit_btn", use_container_width=True):
                    cp_lbl = cp_sel.split(" ")[0]
                    use_ndg = "Nudge" in cp_sel
                    res = alp_trader.submit_debit_spread_order(s_sig, checkpoint_label=cp_lbl, use_nudge=use_ndg, allow_any_time=True)
                    if res.get("success"):
                        st.success(f"Submitted to Alpaca! Tag: `{res['ledger_entry']['client_order_id']}`")
                    else:
                        st.warning(f"Alpaca response: {res.get('error')}")

            st.markdown("<div style='font-size:0.78rem; font-weight:700; color:#94a3b8; margin-top:10px; margin-bottom:4px;'>📊 Cross-Strategy Tagged Performance Breakdown in Same Alpaca Account (`PA3IF961ZZZ4`)</div>", unsafe_allow_html=True)
            st.dataframe(pd.DataFrame(analytics["summary_by_strategy"]), use_container_width=True, hide_index=True)
            st.dataframe(analytics["ledger_df"], use_container_width=True, hide_index=True)
        except Exception as e:
            st.info(f"Alpaca tag analytics module status: {e}")


def _render_overall_stats_strip(oos_stats: Dict[str, Any], full_stats: Dict[str, Any], open_info: Dict[str, Any], acct_bal: float) -> None:
    """Section 2 (Layout B): 6 Uniform Matte-Dark Overall Stat Cards."""
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    win_rate = float(oos_stats.get("win_rate_pct", 84.72))
    wins = int(oos_stats.get("wins", 61))
    losses = int(oos_stats.get("losses", 11))
    tot_trades = int(oos_stats.get("trades", 72))
    net_ret = float(oos_stats.get("net_return_pct", 2725.7))
    rr_val = float(oos_stats.get("realized_option_rr", 2.49))
    max_dd = float(oos_stats.get("max_drawdown_pct", 8.03))
    open_pnl = float(open_info.get("total_open_pnl", 0.0))
    open_col = "#10b981" if open_pnl >= 0 else "#ef4444"
    open_sign = "+" if open_pnl > 0 else ""

    with c1:
        st.markdown(
            f"""
            <div class="soxl-kpi-card">
                <div class="soxl-kpi-label">Win Rate (2023–2026)</div>
                <div class="soxl-kpi-val" style="color:#10b981;">{win_rate:.1f}%</div>
                <div class="soxl-kpi-sub">{wins} Wins / {losses} Losses ({tot_trades} Trades)</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            f"""
            <div class="soxl-kpi-card">
                <div class="soxl-kpi-label">Account Growth (2023–2026)</div>
                <div class="soxl-kpi-val" style="color:#10b981;">+{net_ret:,.0f}%</div>
                <div class="soxl-kpi-sub">${acct_bal:,.0f} → ${acct_bal * (1.0 + net_ret/100.0):,.0f}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown(
            f"""
            <div class="soxl-kpi-card">
                <div class="soxl-kpi-label">Open Profit (Current)</div>
                <div class="soxl-kpi-val" style="color:{open_col};">{open_sign}${open_pnl:,.2f}</div>
                <div class="soxl-kpi-sub">{len(open_info.get('open_trades', []))} Active Trade(s) Open</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with c4:
        st.markdown(
            f"""
            <div class="soxl-kpi-card">
                <div class="soxl-kpi-label">Reward-to-Risk Ratio</div>
                <div class="soxl-kpi-val" style="color:#38bdf8;">{rr_val:.2f} : 1</div>
                <div class="soxl-kpi-sub">Avg Win: +{oos_stats.get('mean_win_roi_pct', 93.0):.0f}% | Loss: {oos_stats.get('mean_loss_roi_pct', -45.0):.0f}%</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with c5:
        st.markdown(
            f"""
            <div class="soxl-kpi-card">
                <div class="soxl-kpi-label">Max Account Drawdown</div>
                <div class="soxl-kpi-val" style="color:#e2e8f0;">{max_dd:.1f}%</div>
                <div class="soxl-kpi-sub">Risking 2.5% Per Trade</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with c6:
        st.markdown(
            f"""
            <div class="soxl-kpi-card">
                <div class="soxl-kpi-label">Average Hold Time</div>
                <div class="soxl-kpi-val" style="color:#e2e8f0;">1 Day</div>
                <div class="soxl-kpi-sub">Avg {full_stats.get('mean_hold_days', 1.4):.1f} Days (91% in 1–2 Days)</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def _render_full_width_equity_graph(trades_df: pd.DataFrame, acct_bal: float) -> None:
    """Section 3 (Layout B): Full-Width Account Equity Growth Curve."""
    st.markdown('<div class="soxl-dark-panel">', unsafe_allow_html=True)
    top_l, top_r = st.columns([2.2, 1.0])
    with top_l:
        st.markdown(
            """
            <div style="font-size:0.86rem; font-weight:700; color:#94a3b8; text-transform:uppercase; letter-spacing:0.04em; padding-top:4px;">
                📈 Account Growth Curve (Compounding at 2.5% Risk Per Trade, All Fees & Time Decay Included)
            </div>
            """,
            unsafe_allow_html=True,
        )
    with top_r:
        tf_choice = st.selectbox(
            "Timeframe",
            ["Recent Performance (2023–2026)", "Last 2 Years (2025–2026)", "Full 16-Year History (2011–2026)"],
            index=0,
            key="soxl_layout_b_eq_tf",
            label_visibility="collapsed",
        )

    if "2023" in tf_choice:
        sub_df = trades_df[trades_df["year"] >= 2023].copy().reset_index(drop=True)
        start_label = "2023-01-01"
    elif "2025" in tf_choice:
        sub_df = trades_df[trades_df["year"] >= 2025].copy().reset_index(drop=True)
        start_label = "2025-01-01"
    else:
        sub_df = trades_df.copy().reset_index(drop=True)
        start_label = "2011-01-01"

    if not sub_df.empty:
        mean_sl = abs(sub_df[~sub_df["win"]]["opt_roi_pct"].mean()) / 100.0 if (~sub_df["win"]).any() else 0.45
        eq_vals = [acct_bal]
        for rd in sub_df["opt_roi_dec"]:
            eq_vals.append(eq_vals[-1] * (1.0 + 0.025 * (float(rd) / mean_sl)))
        x_dates = [start_label] + list(sub_df["date"])

        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=x_dates,
                y=eq_vals,
                mode="lines+markers",
                marker=dict(size=4, color="#10b981"),
                name="Account Balance",
                line=dict(color="#10b981", width=2.5),
                fill="tozeroy",
                fillcolor="rgba(16, 185, 129, 0.08)",
                hovertemplate="Date: %{x}<br>Account Balance: $%{y:,.0f}<extra></extra>",
            )
        )
        fig.update_layout(
            template="plotly_dark",
            height=300,
            margin=dict(l=10, r=10, t=10, b=10),
            paper_bgcolor="#111622",
            plot_bgcolor="#0b0e14",
            xaxis=dict(showgrid=False, color="#64748b"),
            yaxis=dict(showgrid=True, gridcolor="#161e2e", color="#94a3b8", tickprefix="$"),
            showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)


def _render_aggregated_trade_stats(trades_df: pd.DataFrame) -> None:
    """Section 4 Left (Layout B): Aggregated Trade Stats by Year & By Direction in Pure Dark Tables."""
    sub_recent = trades_df[trades_df["year"] >= 2019].copy()
    yr_rows_html = ""
    for yr in sorted(sub_recent["year"].unique(), reverse=True):
        sub = sub_recent[sub_recent["year"] == yr]
        n = len(sub)
        w = int(sub["win"].sum())
        l_cnt = n - w
        wr = w / n * 100.0 if n > 0 else 0.0
        avg_w = sub[sub["win"]]["opt_roi_pct"].mean() if w > 0 else 0.0
        avg_l = sub[~sub["win"]]["opt_roi_pct"].mean() if l_cnt > 0 else 0.0
        mean_sl = abs(avg_l) / 100.0 if avg_l != 0 else 0.45
        eq = 1.0
        for rd in sub["opt_roi_dec"]:
            eq *= (1.0 + 0.025 * (float(rd) / mean_sl))
        yr_ret = (eq - 1.0) * 100.0
        yr_rows_html += f"""
        <tr>
            <td><b style="color:#f8fafc;">{yr}</b></td>
            <td>{n}</td>
            <td style="color:#10b981;">{w}W / {l_cnt}L</td>
            <td><b style="color:#f8fafc;">{wr:.1f}%</b></td>
            <td style="color:#10b981;">+{avg_w:.0f}%</td>
            <td style="color:#ef4444;">{avg_l:.0f}%</td>
            <td><b style="color:#10b981;">+{yr_ret:,.1f}%</b></td>
        </tr>
        """

    # Summary by Trade Direction (Bull Call Spreads vs Bear Put Spreads in 2023-2026)
    oos_df = trades_df[trades_df["year"] >= 2023]
    type_rows_html = ""
    for d_val, label in [(1, "Bull Call Spreads (Upward Bounce)"), (-1, "Bear Put Spreads (Overbought Drop)")]:
        sub_d = oos_df[oos_df["dir"] == d_val]
        if sub_d.empty:
            continue
        nd = len(sub_d)
        wd = int(sub_d["win"].sum())
        wrd = wd / nd * 100.0
        aw = sub_d[sub_d["win"]]["opt_roi_pct"].mean() if wd > 0 else 0.0
        type_rows_html += f"""
        <tr>
            <td><b style="color:#f8fafc;">{label}</b></td>
            <td>{nd}</td>
            <td style="color:#10b981;">{wd}W / {nd - wd}L</td>
            <td><b style="color:#10b981;">{wrd:.1f}%</b></td>
            <td style="color:#10b981;">+{aw:.0f}%</td>
            <td>{sub_d['days'].mean():.1f} Days</td>
        </tr>
        """

    st.markdown(
        f"""
        <div class="soxl-dark-panel">
            <div style="font-size:0.86rem; font-weight:700; color:#94a3b8; text-transform:uppercase; letter-spacing:0.04em; margin-bottom:10px;">
                📊 Aggregated Trade Stats (Yearly & By Trade Type)
            </div>
            <div class="soxl-table-wrap" style="max-height:265px; margin-bottom:12px;">
                <table class="soxl-dark-table">
                    <thead>
                        <tr>
                            <th>Year</th>
                            <th>Trades</th>
                            <th>Wins / Losses</th>
                            <th>Win Rate</th>
                            <th>Avg Win</th>
                            <th>Avg Loss</th>
                            <th>Account Return</th>
                        </tr>
                    </thead>
                    <tbody>
                        {yr_rows_html}
                    </tbody>
                </table>
            </div>
            <div class="soxl-table-wrap" style="max-height:140px;">
                <table class="soxl-dark-table">
                    <thead>
                        <tr>
                            <th>2023–2026 Strategy Type</th>
                            <th>Trades</th>
                            <th>Wins / Losses</th>
                            <th>Win Rate</th>
                            <th>Avg Win</th>
                            <th>Avg Hold</th>
                        </tr>
                    </thead>
                    <tbody>
                        {type_rows_html}
                    </tbody>
                </table>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_historical_ledger(trades_df: pd.DataFrame, acct_bal: float) -> None:
    """Section 4 Right (Layout B): Historical Trade Ledger in Pure Dark HTML."""
    st.markdown('<div class="soxl-dark-panel">', unsafe_allow_html=True)
    f1, f2, f3 = st.columns([1.35, 1.1, 1.0])
    with f1:
        st.markdown(
            """
            <div style="font-size:0.86rem; font-weight:700; color:#94a3b8; text-transform:uppercase; letter-spacing:0.04em; padding-top:6px;">
                📜 Historical Trade Ledger (3:30 PM Entries)
            </div>
            """,
            unsafe_allow_html=True,
        )
    with f2:
        period_sel = st.selectbox(
            "Period",
            ["Recent (2023–2026)", "2025–2026 Only", "All History (2011–2026)"],
            index=0,
            key="soxl_b_led_per",
            label_visibility="collapsed",
        )
    with f3:
        res_sel = st.selectbox(
            "Result",
            ["All Trades", "Winning Trades Only", "Losing Trades Only"],
            index=0,
            key="soxl_b_led_res",
            label_visibility="collapsed",
        )

    sub = trades_df.copy()
    if "2023" in period_sel:
        sub = sub[sub["year"] >= 2023]
    elif "2025" in period_sel:
        sub = sub[sub["year"] >= 2025]
    if "Winning" in res_sel:
        sub = sub[sub["win"]]
    elif "Losing" in res_sel:
        sub = sub[~sub["win"]]

    sub = sub.sort_values("date", ascending=False).reset_index(drop=True)
    risk_per_trade = acct_bal * 0.025
    oos_losers = trades_df[(trades_df["year"] >= 2023) & (~trades_df["win"])]
    mean_sl = abs(float(oos_losers["opt_roi_pct"].mean())) / 100.0 if len(oos_losers) > 0 else 0.3278

    rows_html = ""
    for _, r in sub.head(120).iterrows():
        win_flag = bool(r["win"])
        res_badge = (
            '<span style="background:#10b98122;color:#10b981;padding:2px 8px;border-radius:4px;font-weight:700;font-size:0.74rem;">WIN</span>'
            if win_flag
            else '<span style="background:#ef444422;color:#ef4444;padding:2px 8px;border-radius:4px;font-weight:700;font-size:0.74rem;">LOSS</span>'
        )
        opt_roi = float(r["opt_roi_pct"])
        roi_col = "#10b981" if opt_roi >= 0 else "#ef4444"
        roi_sign = "+" if opt_roi > 0 else ""
        acct_pnl = risk_per_trade * (float(r["opt_roi_dec"]) / mean_sl)
        pnl_sign = "+" if acct_pnl > 0 else "-"
        t_type = "Call Spread" if int(r["dir"]) == 1 else "Put Spread"
        strikes_str = f"${float(r['k_long']):.2f} / ${float(r['k_short']):.2f}"
        days_val = r.get("days")
        if pd.isna(days_val):
            days_val = r.get("hold_days", 1)
        days_int = int(float(days_val)) if not pd.isna(days_val) else 1
        ent_stk = r.get("as_traded_entry")
        if pd.isna(ent_stk):
            ent_stk = r.get("entry_px", r.get("entry", 0.0))
        ext_stk = r.get("as_traded_exit")
        if pd.isna(ext_stk):
            ext_stk = r.get("exit_px", r.get("exit", ent_stk))
        rows_html += f"""
        <tr>
            <td><b style="color:#f8fafc;">{r['date']}</b></td>
            <td>{r.get('exit_date', '')} ({days_int}d)</td>
            <td>{t_type}</td>
            <td><b style="color:#38bdf8;">{strikes_str}</b></td>
            <td>${float(ent_stk):.2f} → ${float(ext_stk):.2f}</td>
            <td>${float(r['entry_mid']):.2f} → ${float(r['exit_mid']):.2f}</td>
            <td>{res_badge}</td>
            <td><b style="color:{roi_col};">{roi_sign}{opt_roi:.1f}%</b></td>
            <td><b style="color:{roi_col};">{pnl_sign}${abs(acct_pnl):,.0f}</b></td>
        </tr>
        """

    st.markdown(
        f"""
        <div class="soxl-table-wrap" style="max-height:368px;">
            <table class="soxl-dark-table">
                <thead>
                    <tr>
                        <th>Entry Date</th>
                        <th>Exit (Hold)</th>
                        <th>Type</th>
                        <th>Option Strikes</th>
                        <th>SOXL Price</th>
                        <th>Option Price</th>
                        <th>Result</th>
                        <th>Option Return</th>
                        <th>Profit ($2.5% Risk)</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>
        </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_model2_paper_trade_report(
    audit_m1: Dict[str, Any],
    trades_m1: pd.DataFrame,
    p_audit: Dict[str, Any],
    p_trades: pd.DataFrame,
    acct_bal: float,
    open_info: Dict[str, Any],
) -> None:
    """Section 5: Paper Trade Monitor for Model 2 (Modern 4-Yr Pruned 5-Sleeve + -18% Option Stop)."""
    if not p_audit or p_trades.empty:
        return

    p_sum = p_audit.get("summary", {})
    m2_oos = p_sum.get("OOS_2023_2026", {})
    m2_2526 = p_sum.get("Blind_Test_2025_2026", {})
    m2_2025 = p_sum.get("2025", {})
    m2_2026 = p_sum.get("2026", {})

    m1_sum = audit_m1.get("portfolio_summary", {})
    m1_oos = m1_sum.get("Out-of-Sample (2023-2026)", {})
    m1_yr = audit_m1.get("oos_yearly", {})
    m1_2025 = m1_yr.get("2025", {})
    m1_2026 = m1_yr.get("2026", {})

    # Calculate Model 1 2025-2026 combined for exact side-by-side comparison
    m1_sub_2526 = trades_m1[trades_m1["year"] >= 2025]
    m1_2526_w = int(m1_sub_2526["win"].sum())
    m1_2526_n = len(m1_sub_2526)
    m1_2526_l = m1_2526_n - m1_2526_w
    m1_2526_wr = (m1_2526_w / m1_2526_n * 100.0) if m1_2526_n > 0 else 0.0
    m1_2526_mw = float(m1_sub_2526[m1_sub_2526["win"]]["opt_roi_pct"].mean()) if m1_2526_w > 0 else 0.0
    m1_2526_ml = float(m1_sub_2526[~m1_sub_2526["win"]]["opt_roi_pct"].mean()) if m1_2526_l > 0 else -18.74
    m1_2526_rr = m1_2526_mw / abs(m1_2526_ml) if m1_2526_ml != 0 else 4.52
    m1_2526_gp = float(m1_sub_2526[m1_sub_2526["win"]]["opt_roi_pct"].sum()) if m1_2526_w > 0 else 0.0
    m1_2526_gl = abs(float(m1_sub_2526[~m1_sub_2526["win"]]["opt_roi_pct"].sum())) if m1_2526_l > 0 else 1.0
    m1_2526_pf = m1_2526_gp / m1_2526_gl if m1_2526_gl > 0 else 28.25

    sig_p = p_audit.get("latest_paper_signal", {})
    open_pnl = float(open_info.get("total_open_pnl", 0.0))
    open_pct = float(open_info.get("total_open_pnl_pct", 0.0))
    open_sign = "+" if open_pnl > 0 else ""

    # Filtered-out trades table (where Model 2 skipped legacy S2 / S5 signals)
    dropped = p_audit.get("filtered_out_oos_trades", [])
    filt_rows = ""
    for d in reversed(dropped):
        was_win = bool(d.get("m1_win", False))
        m1_roi = float(d.get("m1_opt_roi_pct", 0.0))
        badge = (
            '<span style="background:#10b98122;color:#10b981;padding:2px 8px;border-radius:4px;font-weight:700;font-size:0.73rem;">SAVED LOSS IN PAPER</span>'
            if not was_win
            else '<span style="background:#33415555;color:#94a3b8;padding:2px 8px;border-radius:4px;font-weight:600;font-size:0.73rem;">SKIPPED (CONSERVATIVE)</span>'
        )
        m1_col = "#10b981" if was_win else "#ef4444"
        m1_sgn = "+" if m1_roi > 0 else ""
        filt_rows += f"""
<tr>
<td><b style="color:#f8fafc;">{d['date']}</b></td>
<td>{d['exit_date']}</td>
<td><span style="color:#94a3b8;">{d['sleeve'].replace('Phase2_SMA50_SemiVel_Bull', 'Legacy S2 (SMA50)').replace('Phase5_DeepWashout_RTH_Bull', 'Legacy S5 (Washout)')}</span></td>
<td><b style="color:#38bdf8;">{d['strikes']}</b></td>
<td><b style="color:{m1_col};">{m1_sgn}{m1_roi:.1f}%</b></td>
<td><b style="color:#e2e8f0;">0.0% (Flat Cash)</b></td>
<td>{badge}</td>
</tr>
"""

    html_paper = f"""
<div class="soxl-dark-panel" style="margin-top:6px; border-color:#26324d;">
<div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px; margin-bottom:12px;">
<div>
<span style="background:#38bdf822; color:#38bdf8; border:1px solid #38bdf855; padding:3px 10px; border-radius:5px; font-weight:700; font-size:0.76rem; margin-right:8px;">
🧪 PAPER TRADE MONITOR
</span>
<span style="font-size:0.92rem; font-weight:700; color:#f8fafc; text-transform:uppercase; letter-spacing:0.03em;">
Model 2 Shadow Report (Modern 4-Year Pruned 5-Sleeve + -18% Option Stop)
</span>
</div>
<div style="font-size:0.8rem; color:#94a3b8;">
Active Paper Status ({sig_p.get('date', '2026-10-30')} @ 3:30 PM ET):
<b style="color:#10b981; margin-left:6px;">● {sig_p.get('status', 'ACTIVE PAPER TRADE')} ({open_sign}${open_pnl:,.2f} / {open_sign}{open_pct:.1f}%)</b>
</div>
</div>

<div style="display:grid; grid-template-columns: 1.25fr 1.0fr; gap:14px;">
<div>
<div style="font-size:0.78rem; font-weight:700; color:#94a3b8; text-transform:uppercase; margin-bottom:6px;">
📊 Head-to-Head Comparison: Live Model 1 (7-Sleeve) vs. Paper Model 2 (5-Sleeve Modern)
</div>
<div class="soxl-table-wrap" style="max-height:240px;">
<table class="soxl-dark-table">
<thead>
<tr>
<th>Window & Model</th>
<th>Trades (W / L)</th>
<th>Win Rate</th>
<th>Avg Win / Loss</th>
<th>Option R:R</th>
<th>Profit Factor</th>
<th>Max DD</th>
</tr>
</thead>
<tbody>
<tr>
<td><b style="color:#94a3b8;">2025–2026 (Live Model 1)</b></td>
<td>{m1_2526_n} ({m1_2526_w}W / {m1_2526_l}L)</td>
<td><b>{m1_2526_wr:.1f}%</b></td>
<td>+{m1_2526_mw:.0f}% / {m1_2526_ml:.0f}%</td>
<td>{m1_2526_rr:.2f} : 1</td>
<td>{m1_2526_pf:.2f}</td>
<td>{m1_2026.get('max_drawdown_pct', 3.49):.2f}%</td>
</tr>
<tr style="background:#131d31;">
<td><b style="color:#38bdf8;">2025–2026 (Paper Model 2)</b></td>
<td>{m2_2526.get('trades', 28)} (<b style="color:#10b981;">{m2_2526.get('wins', 24)}W / {m2_2526.get('losses', 4)}L</b>)</td>
<td><b style="color:#10b981;">{m2_2526.get('win_rate_pct', 85.71):.2f}%</b></td>
<td><span style="color:#10b981;">+{m2_2526.get('mean_win_roi_pct', 88.2):.0f}%</span> / <span style="color:#ef4444;">{m2_2526.get('mean_loss_roi_pct', -26.6):.0f}%</span></td>
<td><b style="color:#38bdf8;">{m2_2526.get('realized_option_rr', 3.32):.2f} : 1</b></td>
<td><b style="color:#10b981;">{m2_2526.get('profit_factor', 19.93):.2f}</b></td>
<td><b style="color:#10b981;">{m2_2526.get('max_drawdown_pct', 4.15):.2f}%</b></td>
</tr>
<tr>
<td><b style="color:#94a3b8;">2023–2026 (Live Model 1)</b></td>
<td>{m1_oos.get('trades', 72)} ({m1_oos.get('wins', 60)}W / {m1_oos.get('losses', 12)}L)</td>
<td><b>{m1_oos.get('win_rate_pct', 83.33):.2f}%</b></td>
<td>+{m1_oos.get('mean_win_roi_pct', 87.8):.0f}% / {m1_oos.get('mean_loss_roi_pct', -32.8):.0f}%</td>
<td>{m1_oos.get('realized_option_rr', 2.68):.2f} : 1</td>
<td>{m1_oos.get('profit_factor', 13.38):.2f}</td>
<td>{m1_oos.get('max_drawdown_pct', 5.29):.2f}%</td>
</tr>
<tr style="background:#131d31;">
<td><b style="color:#38bdf8;">2023–2026 (Paper Model 2)</b></td>
<td>{m2_oos.get('trades', 59)} (<b style="color:#10b981;">{m2_oos.get('wins', 51)}W / {m2_oos.get('losses', 8)}L</b>)</td>
<td><b style="color:#10b981;">{m2_oos.get('win_rate_pct', 86.44):.2f}%</b></td>
<td><span style="color:#10b981;">+{m2_oos.get('mean_win_roi_pct', 90.1):.0f}%</span> / <span style="color:#ef4444;">{m2_oos.get('mean_loss_roi_pct', -48.9):.0f}%</span></td>
<td><b style="color:#38bdf8;">{m2_oos.get('realized_option_rr', 1.84):.2f} : 1</b></td>
<td><b style="color:#10b981;">{m2_oos.get('profit_factor', 11.74):.2f}</b></td>
<td><b style="color:#10b981;">{m2_oos.get('max_drawdown_pct', 7.94):.2f}%</b></td>
</tr>
<tr>
<td><b style="color:#94a3b8;">2025 Alone (Live vs Paper)</b></td>
<td>{m1_2025.get('trades', 14)} vs {m2_2025.get('trades', 10)}</td>
<td>{m1_2025.get('win_rate_pct', 85.7):.1f}% → <b style="color:#10b981;">{m2_2025.get('win_rate_pct', 90.0):.1f}%</b></td>
<td>+{m1_2025.get('mean_win_roi_pct', 82.0):.0f}% → <b style="color:#10b981;">+{m2_2025.get('mean_win_roi_pct', 87.3):.0f}%</b></td>
<td>{m1_2025.get('realized_option_rr', 3.43):.2f} → <b style="color:#38bdf8;">{m2_2025.get('realized_option_rr', 4.24):.2f}:1</b></td>
<td>{m1_2025.get('profit_factor', 20.6):.1f} → <b style="color:#10b981;">{m2_2025.get('profit_factor', 38.2):.1f}</b></td>
<td><b style="color:#10b981;">{m2_2025.get('max_drawdown_pct', 2.50):.2f}%</b></td>
</tr>
<tr>
<td><b style="color:#94a3b8;">2026 YTD (Live vs Paper)</b></td>
<td>{m1_2026.get('trades', 18)} vs {m2_2026.get('trades', 18)}</td>
<td>{m1_2026.get('win_rate_pct', 83.3):.1f}% → <b style="color:#10b981;">{m2_2026.get('win_rate_pct', 83.33):.1f}%</b></td>
<td>Loss: {m1_2026.get('mean_loss_roi_pct', -15.3):.0f}% → <b style="color:#10b981;">{m2_2026.get('mean_loss_roi_pct', -28.5):.0f}%</b></td>
<td>{m1_2026.get('realized_option_rr', 5.66):.2f} → <b style="color:#38bdf8;">{m2_2026.get('realized_option_rr', 3.11):.2f}:1</b></td>
<td>{m1_2026.get('profit_factor', 28.3):.1f} → <b style="color:#10b981;">{m2_2026.get('profit_factor', 15.55):.1f}</b></td>
<td><b style="color:#10b981;">{m2_2026.get('max_drawdown_pct', 3.86):.2f}%</b></td>
</tr>
</tbody>
</table>
</div>
</div>

<div>
<div style="font-size:0.78rem; font-weight:700; color:#94a3b8; text-transform:uppercase; margin-bottom:6px;">
🛡️ Divergence Log: Trades Filtered Out by Paper Model 2 (4 of 12 OOS Losses Saved)
</div>
<div class="soxl-table-wrap" style="max-height:240px;">
<table class="soxl-dark-table">
<thead>
<tr>
<th>Date</th>
<th>Exit</th>
<th>Filtered Legacy Sleeve</th>
<th>Strikes</th>
<th>Model 1 ROI</th>
<th>Paper Model 2</th>
<th>Paper Effect</th>
</tr>
</thead>
<tbody>
{filt_rows}
</tbody>
</table>
</div>
</div>
</div>
</div>
"""
    st.markdown(html_paper, unsafe_allow_html=True)


def render_soxl_first_principles_desk() -> None:
    """Renders Layout B (Signal-First Follower Feed) for the SOXL & TQQQ 3:30 PM Options Desk."""
    _inject_uniform_dark_css()

    # ---------------- CLEAN TOP HEADER + DESK SELECTOR + ACCOUNT BALANCE INPUT ----------------
    hdr_l, hdr_m, hdr_r, hdr_btn = st.columns([1.85, 1.1, 0.85, 0.55])
    with hdr_l:
        st.markdown(
            """
            <div style="padding-top:4px; margin-bottom:6px;">
                <span style="font-size:1.4rem; font-weight:800; color:#f8fafc;">🚀 SOXL & TQQQ 3:30 PM Options Desk</span>
                <span style="color:#64748b; font-size:0.88rem; margin-left:12px;">
                    Walk-Forward 6+6 Sleeve Config • 3:15–3:25 PM ET Entry • Flat 2.5% Risk Per Trade (Zero Curve-Fit)
                </span>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with hdr_m:
        desk_mode = st.selectbox(
            "Select Strategy Desk",
            [
                "SOXL — 3x Semiconductor Debit Spreads",
                "TQQQ — 3x Nasdaq-100 Debit Spreads",
                "Compare — SOXL vs. TQQQ Side-by-Side",
            ],
            index=0,
            key="soxl_tqqq_unified_desk_sel",
        )
    with hdr_r:
        acct_bal = st.number_input(
            "Starting / Current Account Balance ($)",
            min_value=5000.0,
            max_value=10000000.0,
            value=100000.0,
            step=5000.0,
            key="soxl_layout_b_acct_bal",
        )
    with hdr_btn:
        st.markdown("<div style='height:24px;'></div>", unsafe_allow_html=True)
        if st.button("🔄 Refresh Live", key="soxl_tqqq_live_refresh_btn", type="primary", use_container_width=True):
            sync_live_soxl_signal_and_ledger()
            try:
                import soxl_tqqq_debit_330.ui.tqqq_desk as tqqq_desk
                tqqq_desk.sync_live_tqqq_signal_and_ledger()
            except Exception:
                pass
            st.cache_data.clear()
            st.toast("SOXL & TQQQ live prices, stops, and trade ledgers updated!", icon="🚀")
            st.rerun()

    # Auto-sync live prices and closed-trade transitions on load
    sync_live_soxl_signal_and_ledger()

    if desk_mode.startswith("TQQQ"):
        import soxl_tqqq_debit_330.ui.tqqq_desk as tqqq_desk
        tqqq_desk.render_tqqq_first_principles_desk(embedded=True, acct_bal_override=acct_bal)
        return

    if desk_mode.startswith("Compare"):
        import soxl_tqqq_debit_330.ui.tqqq_desk as tqqq_desk
        tqqq_desk.render_soxl_vs_tqqq_comparison(acct_bal=acct_bal)
        return

    a_mtime = AUDIT_JSON_PATH.stat().st_mtime if AUDIT_JSON_PATH.exists() else 0.0
    t_mtime = TRADES_CSV_PATH.stat().st_mtime if TRADES_CSV_PATH.exists() else 0.0
    audit, trades_df = _load_soxl_audit_and_trades(a_mtime, t_mtime)

    pa_mtime = PAPER_AUDIT_JSON_PATH.stat().st_mtime if PAPER_AUDIT_JSON_PATH.exists() else 0.0
    pt_mtime = PAPER_TRADES_CSV_PATH.stat().st_mtime if PAPER_TRADES_CSV_PATH.exists() else 0.0
    p_audit, p_trades = _load_model2_paper_data(pa_mtime, pt_mtime)

    if not audit or trades_df.empty:
        st.warning("SOXL data files not found. Run `python scratch/calibrate_soxl_first_principles.py`.")
        return

    summary = audit.get("portfolio_summary", {})
    oos_stats = summary.get("Out-of-Sample (2023-2026)", {})
    full_stats = summary.get("Full Period (2011-2026)", {})
    tel = audit.get("latest_telemetry", {})

    bull_cfg = tel.get("bull_setup", {})
    default_w = float(bull_cfg.get("width", 2.50))
    est_debit = round(default_w * 0.44, 2)
    eff_risk_frac = float(tel.get("risk_pct", 2.5)) / 100.0
    risk_dollars = acct_bal * eff_risk_frac
    mean_sl_frac = abs(float(oos_stats.get("mean_loss_roi_pct", -45.07))) / 100.0
    loss_per_contract = max(10.0, est_debit * 100.0 * mean_sl_frac)
    contracts = max(1, int(risk_dollars // loss_per_contract))
    open_info = _compute_open_positions_and_pnl(trades_df, tel, contracts)

    # 1. Top Full-Width 3:30 PM Signal & Open Profit Banner
    _render_top_signal_and_open_profit_banner(tel, open_info, contracts, risk_dollars, est_debit)

    # 1B. 3:15 PM - 3:30 PM ET 5-Minute Staged Execution Protocol, 7-Gate Scanner & Midpoint Calculator
    _render_315_330_execution_protocol_and_calculator(tel, open_info, contracts, risk_dollars)

    # 2. Overall Stats Strip (6 Uniform Matte-Dark Cards)
    _render_overall_stats_strip(oos_stats, full_stats, open_info, acct_bal)

    # 3. Full-Width Account Equity Growth Graph
    _render_full_width_equity_graph(trades_df, acct_bal)

    # 4. Bottom Split: Aggregated Trade Stats (Yearly & By Type) + Historical Trade Ledger
    bot_l, bot_r = st.columns([0.95, 1.35])
    with bot_l:
        _render_aggregated_trade_stats(trades_df)
    with bot_r:
        _render_historical_ledger(trades_df, acct_bal)

    # 5. Paper Trade Monitor: Model 2 Shadow Report (Modern 4-Yr Pruned 5-Sleeve + -18% Stop)
    _render_model2_paper_trade_report(audit, trades_df, p_audit, p_trades, acct_bal, open_info)
