"""
Option Mathematics & BSM Pricing Engine
=======================================
Black-Scholes-Merton midpoint vertical spread pricing, moneyness-calibrated
implied volatility skew, multi-day holding-period theta decay accounting,
scale-invariant strike grid alignment, and synthetic underlying stop execution.
"""

from __future__ import annotations

import math
from typing import Dict, Any
import numpy as np


def bsm_option_mid(
    spot: float,
    strike: float,
    dte_days: float,
    iv: float,
    rate: float = 0.045,
    is_call: bool = True,
) -> float:
    """
    Computes standard Black-Scholes-Merton theoretical price.
    """
    if dte_days <= 1e-4:
        return max(0.0, (spot - strike) if is_call else (strike - spot))
    t = max(dte_days / 365.0, 1e-6)
    sigma = max(iv, 1e-4)
    s = max(spot, 1e-4)
    k = max(strike, 1e-4)

    d1 = (math.log(s / k) + (rate + 0.5 * sigma**2) * t) / (sigma * math.sqrt(t))
    d2 = d1 - sigma * math.sqrt(t)

    def norm_cdf(x: float) -> float:
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

    if is_call:
        price = s * norm_cdf(d1) - k * math.exp(-rate * t) * norm_cdf(d2)
    else:
        price = k * math.exp(-rate * t) * norm_cdf(-d2) - s * norm_cdf(-d1)
    return max(0.01, float(price))


def price_interior_vertical_mid(
    spot: float,
    k_long: float,
    k_short: float,
    dte_days: float,
    iv: float,
    is_call: bool = True,
) -> float:
    """
    Computes the exact Black-Scholes-Merton Bid/Ask Midpoint of a vertical
    option debit spread with moneyness-calibrated implied volatility skew.
    """
    if is_call:
        m_long = math.log(max(k_long, 1e-4) / max(spot, 1e-4))
        m_short = math.log(max(k_short, 1e-4) / max(spot, 1e-4))
        iv_long = max(0.14, iv * (1.0 - 0.15 * m_long))
        iv_short = max(0.14, iv * (1.0 - 0.15 * m_short))
    else:
        m_long = math.log(max(spot, 1e-4) / max(k_long, 1e-4))
        m_short = math.log(max(spot, 1e-4) / max(k_short, 1e-4))
        iv_long = min(1.20, iv * (1.0 + 0.20 * m_long))
        iv_short = min(1.20, iv * (1.0 + 0.20 * m_short))

    c_long = bsm_option_mid(spot, k_long, dte_days, iv_long, is_call=is_call)
    c_short = bsm_option_mid(spot, k_short, dte_days, iv_short, is_call=is_call)
    width = abs(k_short - k_long)
    return float(np.clip(c_long - c_short, 0.02, width * 0.98))


def price_theta_flip_spread(
    entry_px: float,
    exit_px: float,
    tp_px: float,
    sl_px: float,
    atr_val: float,
    days_held: int,
    hit_tp: bool,
    hit_sl: bool,
    direction: int = 1,
    dte_entry: float = 2.0,
    k_long_offset_frac: float = -0.25,
    spread_width_dollars: float = 5.0,
    strike_grid_dollars: float = 5.0,
    slippage_pct: float = 0.0,
    round_trip_commission: float = 0.50,
    directional_stop_frac: float = -0.28,
) -> Dict[str, Any]:
    """
    Calculates execution metrics for a Theta-Flip vertical debit spread:
      - Aligns strikes to specified strike grid ($5.00 for modern CRM/large caps)
      - Computes initial entry midpoint at 3:30 PM ET
      - Explicitly accounts for time decay over the holding period:
          * On TP: 1.4 calendar days per trading day elapsed (positive ITM theta)
          * On SL: 0.70 calendar days per trading day elapsed up to synthetic sl_px touch
      - Deducts round-trip commission ($0.50 per contract = $0.005/share)
      - Returns complete pricing dictionary with explicit theta decay breakdown.
    """
    is_call = direction == 1
    atr_pct = atr_val / max(entry_px, 1.0)
    iv_entry = float(np.clip(atr_pct * 7.65, 0.16, 0.55))
    target_move = abs(tp_px - entry_px)

    # Era-aware strike scaling for split-adjusted data if price is low
    if entry_px >= 150.0:
        width = spread_width_dollars
        grid = strike_grid_dollars
    elif entry_px >= 60.0:
        width = min(spread_width_dollars, 2.50)
        grid = min(strike_grid_dollars, 2.50)
    else:
        width = min(spread_width_dollars, 1.25)
        grid = min(strike_grid_dollars, 1.25)

    if is_call:
        k_long = round((entry_px + k_long_offset_frac * target_move) / grid) * grid
        k_short = round(k_long + width, 2)
    else:
        k_long = round((entry_px - k_long_offset_frac * target_move) / grid) * grid
        k_short = round(k_long - width, 2)

    width = abs(k_short - k_long)
    raw_entry_mid = price_interior_vertical_mid(entry_px, k_long, k_short, dte_entry, iv_entry, is_call=is_call)
    entry_mid = raw_entry_mid * (1.0 + slippage_pct)

    # Elapsed calendar days of time decay (target/time exit vs synthetic sl_px touch)
    cal_elapsed = min(dte_entry - 0.35, float(days_held) * 1.4)
    dte_exit = max(0.35, dte_entry - cal_elapsed)
    dte_stop_theta = max(0.35, dte_entry - 0.70 * min(float(days_held), 2.0))

    decayed_at_s0 = price_interior_vertical_mid(entry_px, k_long, k_short, dte_stop_theta, iv_entry, is_call=is_call)
    theta_decay_frac = min(0.0, (decayed_at_s0 - raw_entry_mid) / max(raw_entry_mid, 0.02))

    eff_exit_px = tp_px if hit_tp else (sl_px if hit_sl else exit_px)
    eff_dte_exit = dte_exit if hit_tp else dte_stop_theta
    iv_exit = iv_entry * (0.98 if hit_tp else (1.02 if hit_sl else 1.00))
    raw_exit_mid = price_interior_vertical_mid(eff_exit_px, k_long, k_short, eff_dte_exit, iv_exit, is_call=is_call)
    exit_mid = raw_exit_mid * (1.0 - slippage_pct)

    comm_per_share = round_trip_commission / 100.0
    comm_frac = comm_per_share / max(entry_mid, 0.02)
    raw_roi_dec = ((exit_mid - entry_mid) - comm_per_share) / max(entry_mid, 0.02)

    if (not hit_tp) and raw_roi_dec < 0.0:
        theta_adjusted_stop_dec = directional_stop_frac + theta_decay_frac - comm_frac - (2.0 * slippage_pct)
        roi_dec = max(float(raw_roi_dec), float(theta_adjusted_stop_dec))
        exit_mid = max(0.02, entry_mid * (1.0 + roi_dec) + comm_per_share)
    else:
        roi_dec = float(raw_roi_dec)

    return {
        "k_long": k_long,
        "k_short": k_short,
        "width": round(width, 2),
        "entry_mid": round(entry_mid, 3),
        "exit_mid": round(exit_mid, 3),
        "dte_exit": round(eff_dte_exit, 2),
        "theta_decay_pct": round(theta_decay_frac * 100.0, 2),
        "comm_drag_pct": round(comm_frac * 100.0, 2),
        "roi_dec": float(roi_dec),
        "roi_pct": float(roi_dec * 100.0),
    }
