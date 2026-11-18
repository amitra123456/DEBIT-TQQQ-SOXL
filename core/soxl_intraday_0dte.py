"""
SOXL Intraday 0 DTE Friday Debit Spread Engine (Hardened V2)
============================================================
Institutional-grade intraday options trading engine designed specifically for SOXL
exploiting terminal 0 DTE gamma collapse and intraday VWAP institutional order flow.

Audit Fixes Implemented:
  1. Listed Strike Grid Snapping: Strikes snapped to real listed $0.50 / $1.00 increments (never $0.10).
  2. Scale-Invariant Width: Spread width dynamically scaled to ~3.5% of spot (snapped to strike grid),
     preventing 20%–25% ITM distortion during low-price regimes (2020 / 2022).
  3. Unclamped Mark Stop Loss: Exits at true cur_mid (unclamped), capturing adverse gap slippage.
  4. Realistic OPRA Bid-Ask Friction: $0.08/spread round-trip slippage ($0.04/spread entry + $0.04 exit).
  5. Strict VWAP Deadband (+/- 0.15%): Filters chop around the VWAP mean.
"""

from __future__ import annotations

import math
from datetime import datetime, time
from typing import Dict, Any, Optional
import numpy as np

def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / 1.4142135623730951))

def bsm_call(S: float, K: float, T: float, r: float, sigma: float) -> float:
    if T <= 1e-6:
        return max(0.0, S - K)
    sig_sqrt_t = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / sig_sqrt_t
    d2 = d1 - sig_sqrt_t
    return S * norm_cdf(d1) - K * math.exp(-r * T) * norm_cdf(d2)

def bsm_put(S: float, K: float, T: float, r: float, sigma: float) -> float:
    if T <= 1e-6:
        return max(0.0, K - S)
    sig_sqrt_t = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / sig_sqrt_t
    d2 = d1 - sig_sqrt_t
    return K * math.exp(-r * T) * norm_cdf(-d2) - S * norm_cdf(-d1)

def calc_spread_mid(
    spot: float,
    k_long: float,
    k_short: float,
    t_years: float,
    r: float = 0.045,
    sigma: float = 1.25,
    is_call: bool = True
) -> float:
    w = abs(k_short - k_long)
    if is_call:
        c_long = bsm_call(spot, k_long, t_years, r, sigma)
        c_short = bsm_call(spot, k_short, t_years, r, sigma)
    else:
        c_long = bsm_put(spot, k_long, t_years, r, sigma)
        c_short = bsm_put(spot, k_short, t_years, r, sigma)
    val = c_long - c_short
    return max(0.01, min(w * 0.995, val))

class SOXLIntraday0DTEEngine:
    """
    Intraday 0 DTE debit spread engine for SOXL.
    """
    def __init__(
        self,
        itm_offset_pct: float = 0.025,
        target_width_pct: float = 0.035,
        spread_width: Optional[float] = None,
        take_profit_pct: float = 0.25,
        stop_loss_pct: float = 0.125,
        slippage_per_spread: float = 0.08, # Realistic $0.08 round-trip ($0.04/leg)
        entry_time: time = time(12, 0),
        mandatory_exit_time: time = time(15, 45),
        soxl_median_iv: float = 1.25,
        rate: float = 0.045,
    ):
        self.itm_offset_pct = itm_offset_pct
        self.target_width_pct = target_width_pct
        self.take_profit_pct = take_profit_pct
        self.stop_loss_pct = stop_loss_pct
        self.slippage = slippage_per_spread
        self.entry_time = entry_time
        self.mandatory_exit_time = mandatory_exit_time
        self.soxl_iv = soxl_median_iv
        self.rate = rate

    def get_strike_grid(self, spot: float) -> float:
        """Listed SOXL strike increment: $0.50 if spot < $25, else $1.00."""
        if spot < 25.0:
            return 0.50
        elif spot < 100.0:
            return 1.00
        else:
            return 2.50

    def compute_strikes(self, spot: float, is_call: bool) -> tuple[float, float, float]:
        """
        Computes scale-invariant, exchange-listed strikes for SOXL.
        Returns: (k_long, k_short, width)
        """
        grid = self.get_strike_grid(spot)
        # Scale-invariant spread width ~ 3.5% of spot, snapped to grid
        raw_width = max(grid, round(round(spot * self.target_width_pct / grid) * grid, 2))
        width = min(raw_width, 5.0) # Cap max width at $5.00
        
        if is_call:
            # Short strike is 2.5% ITM (below spot), long strike is width dollars further ITM
            target_short = spot * (1.0 - self.itm_offset_pct)
            k_short = round(round(target_short / grid) * grid, 2)
            k_long = round(k_short - width, 2)
        else:
            # Bear put: Short strike is 2.5% ITM (above spot), long strike is width dollars further ITM
            target_short = spot * (1.0 + self.itm_offset_pct)
            k_short = round(round(target_short / grid) * grid, 2)
            k_long = round(k_short + width, 2)
            
        return k_long, k_short, width

    def evaluate_friday_signal(
        self,
        current_time: time,
        spot: float,
        vwap: float,
        weekday: int, # 4 = Friday
    ) -> Optional[Dict[str, Any]]:
        """
        Evaluates intraday signal at 12:00 PM ET on Fridays.
        """
        if weekday != 4:
            return None
            
        # Entry window: 11:45 to 12:15 ET
        if not (time(11, 45) <= current_time <= time(12, 15)):
            return None
            
        # VWAP deadband filter: 0.15% to prevent chop entries right at VWAP
        if spot >= vwap * 1.0015:
            is_call = True
            direction = "BULL_CALL"
        elif spot <= vwap * 0.9985:
            is_call = False
            direction = "BEAR_PUT"
        else:
            return None
            
        k_long, k_short, width = self.compute_strikes(spot, is_call)
            
        # 0 DTE time-to-expiry in years (hours remaining / 6.5 trading hours / 252)
        cur_hour_float = current_time.hour + current_time.minute / 60.0
        frac_day_left = max(0.01, (16.0 - cur_hour_float) / 6.5)
        t_years = frac_day_left / 252.0
        
        entry_mid = calc_spread_mid(
            spot=spot,
            k_long=k_long,
            k_short=k_short,
            t_years=t_years,
            r=self.rate,
            sigma=self.soxl_iv,
            is_call=is_call
        )
        entry_cost = entry_mid + self.slippage / 2.0
        
        return {
            "symbol": "SOXL",
            "direction": direction,
            "is_call": is_call,
            "entry_time": str(current_time),
            "spot": spot,
            "vwap": vwap,
            "k_long": k_long,
            "k_short": k_short,
            "long_strike": k_long,
            "short_strike": k_short,
            "width": width,
            "t_years": t_years,
            "entry_mid": round(entry_mid, 3),
            "entry_cost": round(entry_cost, 3),
            "debit_mid": round(entry_mid, 3),
            "target_tp_price": round(entry_cost * (1.0 + self.take_profit_pct), 3),
            "target_sl_price": round(entry_cost * (1.0 - self.stop_loss_pct), 3),
            "gtc_tp_limit": round(entry_cost * (1.0 + self.take_profit_pct), 3),
            "sl_opt_mid": round(entry_cost * (1.0 - self.stop_loss_pct), 3),
            "mandatory_close_time": str(self.mandatory_exit_time),
        }

    def check_position_exit(
        self,
        position: Dict[str, Any],
        current_time: time,
        current_spot: float,
    ) -> Optional[Dict[str, Any]]:
        """
        Checks whether active intraday position should be closed via TP, SL, or EOD.
        Unclamped: Exits at actual cur_mid if market plunged through stop level.
        """
        is_call = position["is_call"]
        k_long = position["k_long"]
        k_short = position["k_short"]
        entry_cost = position["entry_cost"]
        target_tp = position["target_tp_price"]
        target_sl = position["target_sl_price"]
        
        cur_hour_float = current_time.hour + current_time.minute / 60.0
        frac_day_left = max(0.005, (16.0 - cur_hour_float) / 6.5)
        t_years = frac_day_left / 252.0
        
        cur_mid = calc_spread_mid(
            spot=current_spot,
            k_long=k_long,
            k_short=k_short,
            t_years=t_years,
            r=self.rate,
            sigma=self.soxl_iv,
            is_call=is_call
        )
        
        # 1. Unclamped Stop Loss Check
        if cur_mid <= target_sl:
            # Unclamped exit: exits at cur_mid - slip (captures true gap through stop)
            exit_price = max(0.01, cur_mid - self.slippage / 2.0)
            pnl = exit_price - entry_cost
            return {
                "exit_triggered": True,
                "exit_reason": "INTRADAY_SL_-12.5%",
                "exit_price": round(exit_price, 3),
                "net_pnl": round(pnl, 3),
                "roi_pct": round((pnl / entry_cost) * 100.0, 2),
                "win": pnl > 0
            }
            
        # 2. Take Profit Check
        if cur_mid >= target_tp:
            exit_price = target_tp - self.slippage / 2.0
            pnl = exit_price - entry_cost
            return {
                "exit_triggered": True,
                "exit_reason": "INTRADAY_TP_+25%",
                "exit_price": round(exit_price, 3),
                "net_pnl": round(pnl, 3),
                "roi_pct": round((pnl / entry_cost) * 100.0, 2),
                "win": pnl > 0
            }
            
        # 3. Mandatory 15:45 ET Close (NO OVERNIGHT HOLD)
        if current_time >= self.mandatory_exit_time:
            exit_price = max(0.01, cur_mid - self.slippage / 2.0)
            pnl = exit_price - entry_cost
            return {
                "exit_triggered": True,
                "exit_reason": "MANDATORY_1545_CLOSE",
                "exit_price": round(exit_price, 3),
                "net_pnl": round(pnl, 3),
                "roi_pct": round((pnl / entry_cost) * 100.0, 2),
                "win": pnl > 0
            }
            
        return None
