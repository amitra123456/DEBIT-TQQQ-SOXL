"""
PRISM-7 Semiconductor Multi-Domain Regime & Kinematics Engine (`prism7_semi.py`)
================================================================================
First-Principles 7-Domain Semiconductor Evaluation for SOXL Trading:
  - Leaders: NVDA (35%), AVGO (20%), TSM (15%), AMD (10%), SMH/SOXX (20%)
  - Physical Regimes: EXPANSION, PULLBACK, CHOP, BEAR_MARKET_DRAWDOWN
  - Pre-Event Kinematics: Distribution Crests (DOWN) vs Coils / Spring Exhaustion (UP)
  - Causal 100% Backward Calculus (Zero Lookahead)
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = Path(__file__).resolve().parents[1]
PANEL_PATH = PROJECT_ROOT / "prism7" / "data" / "daily_market_macro_panel_2010_2026.parquet"

SEMI_WEIGHTS = {
    "NVDA": 0.35,
    "AVGO": 0.20,
    "TSM": 0.15,
    "AMD": 0.10,
    "SMH": 0.20,
}


class PRISM7SemiEngine:
    """Evaluates semiconductor multi-stock kinematics and composite regime states."""

    def __init__(self, panel_parquet_path: Optional[Path] = None):
        self.panel_path = panel_parquet_path or PANEL_PATH
        self._panel: Optional[pd.DataFrame] = None
        self._semi_regimes: Dict[str, pd.DataFrame] = {}
        self._composite: Optional[pd.DataFrame] = None
        self._load_and_compute()

    def _load_and_compute(self) -> None:
        if self.panel_path.exists():
            self._panel = pd.read_parquet(self.panel_path)
        else:
            raise FileNotFoundError(f"Market panel not found at {self.panel_path}")

        # Compute individual regime for each semi driver
        for sym in ["NVDA", "AVGO", "TSM", "AMD", "SMH", "SOXX"]:
            if f"{sym}_close" in self._panel.columns:
                self._semi_regimes[sym] = self._compute_single_regime(sym, self._panel)

        # Build composite regime
        self._composite = self._build_composite_regime()

    def _compute_single_regime(self, sym: str, df: pd.DataFrame) -> pd.DataFrame:
        c = df[f"{sym}_close"].astype(float)
        h = df[f"{sym}_high"].astype(float)
        l = df[f"{sym}_low"].astype(float)
        idx = df.index

        ln_p = np.log(c.clip(lower=1e-4))
        ret_1d = c.pct_change(1)

        ln_ma50 = ln_p.rolling(50, min_periods=25).mean()
        ln_ma200 = ln_p.rolling(200, min_periods=80).mean()
        ma200_slope_21d = ln_ma200 - ln_ma200.shift(21)

        dd_63 = c / h.rolling(63, min_periods=15).max() - 1.0
        dd_252 = c / h.rolling(252, min_periods=60).max() - 1.0

        vol_63 = ret_1d.rolling(63, min_periods=20).std()
        vel_21 = ((ln_p.diff(21)) / (vol_63 * np.sqrt(21) + 1e-9)).clip(-4.5, 4.5)

        # Choppiness / Efficiency
        net_chg_21 = (c - c.shift(21)).abs()
        tot_path_21 = c.diff(1).abs().rolling(21, min_periods=10).sum()
        er_21 = (net_chg_21 / (tot_path_21 + 1e-9)).clip(0.0, 1.0)

        # 4-State Regime Logic
        is_bear = (
            (dd_252 <= -0.22)
            | ((dd_252 <= -0.16) & (ln_p < ln_ma200) & (ma200_slope_21d < 0.0))
        )
        is_pullback = (
            (~is_bear)
            & (
                (dd_63 <= -0.060)
                | ((dd_63 <= -0.045) & (vel_21 < -0.55) & (ln_p < ln_ma50))
            )
        )
        is_chop = (
            (~is_bear)
            & (~is_pullback)
            & (
                (er_21 < 0.28)
                | (vel_21.abs() < 0.85)
            )
        )

        regime = np.where(
            is_bear,
            "BEAR_MARKET_DRAWDOWN",
            np.where(is_pullback, "PULLBACK", np.where(is_chop, "CHOP", "EXPANSION")),
        )

        dd_20d = c / h.rolling(20, min_periods=1).max() - 1.0
        up_10d = c / l.rolling(10, min_periods=1).min() - 1.0

        is_pre_dn = (
            ((dd_20d >= -0.045) | (up_10d >= +0.05))
            & (c < h.shift(1))
            & (ret_1d > -0.020)
        )
        is_pre_up = (
            (up_10d <= +0.045)
            & (ret_1d < +0.025)
            & (c > l.shift(1))
            & (dd_63 >= -0.18)
        )

        out = pd.DataFrame({
            "date_str": idx.strftime("%Y-%m-%d"),
            "close": c,
            "regime": regime,
            "is_bear": is_bear,
            "is_pullback": is_pullback,
            "is_chop": is_chop,
            "is_expansion": (regime == "EXPANSION"),
            "is_pre_dn": is_pre_dn,
            "is_pre_up": is_pre_up,
            "vel_21": vel_21,
            "dd_20d": dd_20d,
            "up_10d": up_10d,
        }, index=idx)
        return out

    def _build_composite_regime(self) -> pd.DataFrame:
        dates = sorted(list(self._semi_regimes["NVDA"]["date_str"].unique()))
        records = []
        for d_str in dates:
            exp_w = 0.0
            bear_w = 0.0
            n_exp = 0
            n_bear = 0
            for sym, w in SEMI_WEIGHTS.items():
                if sym in self._semi_regimes:
                    df_sym = self._semi_regimes[sym]
                    match = df_sym[df_sym["date_str"] == d_str]
                    if not match.empty:
                        reg = match.iloc[0]["regime"]
                        if reg == "EXPANSION":
                            exp_w += w
                            n_exp += 1
                        elif reg == "BEAR_MARKET_DRAWDOWN":
                            bear_w += w
                            n_bear += 1

            comp = "CHOP_PULLBACK"
            if exp_w >= 0.50 or n_exp >= 3:
                comp = "BULL_EXPANSION"
            elif bear_w >= 0.40 or n_bear >= 3:
                comp = "BEAR_DRAWDOWN"
            elif exp_w >= 0.30 or n_exp >= 2:
                comp = "MILD_BULL"

            nvda_r = self.get_stock_regime("NVDA", d_str)
            avgo_r = self.get_stock_regime("AVGO", d_str)

            records.append({
                "date_str": d_str,
                "composite_regime": comp,
                "exp_weight": round(exp_w, 3),
                "bear_weight": round(bear_w, 3),
                "n_exp": n_exp,
                "n_bear": n_bear,
                "nvda_regime": nvda_r,
                "avgo_regime": avgo_r,
            })
        return pd.DataFrame(records)

    def get_stock_regime(self, symbol: str, date_str: str) -> str:
        if symbol in self._semi_regimes:
            df_s = self._semi_regimes[symbol]
            row = df_s[df_s["date_str"] == date_str]
            if not row.empty:
                return str(row.iloc[0]["regime"])
        return "CHOP"

    def get_composite_state(self, date_str: str) -> Dict[str, Any]:
        if self._composite is not None:
            row = self._composite[self._composite["date_str"] == date_str]
            if not row.empty:
                return row.iloc[0].to_dict()
            # If date_str is past historical panel, return latest state
            return self._composite.iloc[-1].to_dict()
        return {
            "composite_regime": "CHOP_PULLBACK",
            "exp_weight": 0.0,
            "bear_weight": 0.0,
            "n_exp": 0,
            "n_bear": 0,
            "nvda_regime": "CHOP",
            "avgo_regime": "CHOP",
        }
