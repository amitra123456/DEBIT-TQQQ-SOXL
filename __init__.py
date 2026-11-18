"""
SOXL & TQQQ 3:30 PM Debit Spread Strategy Package (`soxl_tqqq_debit_330`)
=========================================================================
Self-contained strategy package for the 3:15–3:30 PM ET SOXL and TQQQ Vertical Debit Spread
system, including canonical configuration, daily/intraday calibration, 1-minute Alpaca OPRA
backtesting, walk-forward audit, Streamlit UI desks, and automated Alpaca execution.
"""
from soxl_tqqq_debit_330.config import (
    PACKAGE_ROOT,
    PROJECT_ROOT,
    DATA_DIR,
    SOXL_ACTIVE_SLEEVES,
    SOXL_DISABLED_SLEEVES,
    TQQQ_ACTIVE_SLEEVES,
    TQQQ_DISABLED_SLEEVES,
    DEBIT_STRATEGY_CONFIGS,
)

__all__ = [
    "PACKAGE_ROOT",
    "PROJECT_ROOT",
    "DATA_DIR",
    "SOXL_ACTIVE_SLEEVES",
    "SOXL_DISABLED_SLEEVES",
    "TQQQ_ACTIVE_SLEEVES",
    "TQQQ_DISABLED_SLEEVES",
    "DEBIT_STRATEGY_CONFIGS",
]
