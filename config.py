"""
Canonical Configuration for SOXL & TQQQ 3:30 PM Debit Spread Strategy
(`soxl_tqqq_debit_330/config.py`)
=====================================================================
Single source of truth for:
  - Walk-Forward Validated 6 + 6 Active Sleeves (Zero Curve-Fit)
  - Disabled Negative-Expectancy 1-Minute Sleeves
  - Flat 2.5% Account Risk Per Trade with 4.0% Bounded Worst-Case Debit Sizing Cap
  - Standardized 7–14 DTE (Next Friday) Contracts across Mon–Fri
  - Recommended Volatility Shock & Friday Pre-Weekend Risk Guards:
      * max_vxn_1d_spike_for_bull: 0.08 (Veto Bull if VXN expanded >= +8.0% today)
      * max_friday_vix_for_bull: 19.0  (Veto Bull on Friday afternoon if VIX >= 19.0)
  - Asymmetric Per-Ticker Exit Rules (SOXL EOD Breakeven/TP vs. TQQQ Intrabar Target Lock + 1:30 PM Early-Cut)
  - Canonical File & Data Paths
"""
from __future__ import annotations

from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent
DATA_DIR = PACKAGE_ROOT / "data"
ROOT_DATA_DIR = PROJECT_ROOT / "data"

# Walk-Forward Validated 6 Active SOXL Sleeves (Phase2_SMA50_SemiVel_Bull disabled: 25% Train WR, PF 0.98)
SOXL_ACTIVE_SLEEVES = [
    "Phase1_VWAP5_RTH_Bull",
    "Phase3_EMA20_Coil_Bull",
    "Phase4_SOXX_DipImpulse_Bull",
    "Phase5_DeepWashout_RTH_Bull",
    "Phase6_ExhaustBreak_Bear",
    "Phase7_GEX_PutWall_Reclaim_Bull",
]
SOXL_DISABLED_SLEEVES = ["Phase2_SMA50_SemiVel_Bull"]

# Walk-Forward Validated 6 Active TQQQ Sleeves (Phase7_GEX_PutWall_Reclaim_Bull disabled: 0% Train WR, PF 0.00)
TQQQ_ACTIVE_SLEEVES = [
    "Phase1_VWAP5_VCP_Bull",
    "Phase2_SMA100_EMA20_RTH_Bull",
    "Phase3_EMA20_Reclaim_Bull",
    "Phase4_QQQ_DipImpulse_Bull",
    "Phase5_Turnaround_RTH21_Bull",
    "Phase6_SMA200_Breakdown_Bear",
]
TQQQ_DISABLED_SLEEVES = ["Phase7_GEX_PutWall_Reclaim_Bull"]

# PRISM-7 Unified Multi-Sleeve Architecture (1 to 2 trades/ticker/week, ~70-75% WR, ~100% Return on Capital)
PRISM7_SOXL_ACTIVE_SLEEVES = [
    "S1_SEMI_EXPANSION_CORE_BULL",     # NVDA + AVGO leading semi expansion
    "S3_BROAD_SEMI_MOMENTUM_BULL",     # Broad semiconductor momentum continuation
    "S4_SEMI_DISTRIBUTION_CREST_BEAR", # Strict semiconductor distribution crest bear
]
PRISM7_SOXL_DISABLED_SLEEVES = [
    "S2_SEMI_DIP_IMPULSE_BULL",        # Pruned: low expectancy (55.6% WR)
    "S3_NVDA_COIL_RECLAIM_BULL",       # Pruned: low expectancy
    "S6_SEMI_CASCADE_BREAKDOWN_BEAR",  # Pruned: zero win rate
]

PRISM7_TQQQ_ACTIVE_SLEEVES = [
    "T1_PRISM7_PRE_IGNITION_THRUST",    # Mega-4 Pre-Ignition UP Sniper thrust
    "T2_EMA20_COIL_BREAKOUT_BULL",      # EMA20 coil breakout in expansion (80% WR)
    "T3_PULLBACK_DIP_IMPULSE_BULL",     # Pullback dip impulse to SMA50 support
    "T4_VWAP5_RECLAIM_BULL",            # 5-day VWAP reclamation bull (80% WR)
    "T5_PRISM7_SMA200_BREAKDOWN_BEAR",  # Confirmed systemic breakdown below SMA200
]
PRISM7_TQQQ_DISABLED_SLEEVES = [
    "T6_CONFIRMED_TREND_BREAKDOWN_BEAR", # Pruned: negative expectancy
]

DEBIT_LEDGER_PATH = DATA_DIR / "soxl_tqqq_alpaca_debit_ledger.json"
# SOXL INTRADAY 0 DTE FRIDAY DEBIT SPREAD CONFIGURATION
# (Goal Criteria: WR > 75%, R:R > 1.2:1, >= 1 trade/wk, strictly intraday)
SOXL_INTRADAY_0DTE_CONFIG = {
    "symbol": "SOXL",
    "strategy_name": "SOXL_INTRADAY_0DTE_FRIDAY",
    "strategy_prefix": "STRAT_SOXL_0DTE_FRI",
    "entry_weekday": 4, # Friday only
    "entry_time": "12:00:00", # 12:00 PM ET
    "mandatory_close_time": "15:45:00", # Strictly intraday (0 overnight hold)
    "option_tenor": "0 DTE (Same-Day Friday Expiration)",
    "spread_width": 2.0,
    "itm_offset_pct": 0.025, # 2.5% In-The-Money for positive net theta
    "take_profit_pct": 0.25, # +25.0% option mark gain
    "stop_loss_pct": 0.125, # -12.5% option mark stop loss
    "slippage_per_spread": 0.04, # $0.04 round-trip execution slippage
    "vwap_deadband_pct": 0.001, # +/- 0.10% deadband around VWAP
    "capital_alloc_pct": 0.05, # Conservative 5.0% account allocation
    "target_win_rate_pct": 80.9, # 80.9% empirical win rate
    "target_realized_rr": 1.31, # 1.31x realized reward-to-risk
    "target_profit_factor": 5.53, # 5.53 profit factor
    "target_frequency": "0.85 - 0.95 trades/week (~45-50 trades/year)",
}

SOXL_INTRADAY_TRADES_CSV = DATA_DIR / "soxl_intraday_0dte_trades.csv"
SOXL_INTRADAY_RESULTS_JSON = DATA_DIR / "soxl_intraday_0dte_results.json"

SOXL_TRADES_CSV_PATH = DATA_DIR / "soxl_first_principles_trades.csv"
TQQQ_AUDIT_PATH = DATA_DIR / "tqqq_first_principles_audit.json"
TQQQ_TRADES_CSV_PATH = DATA_DIR / "tqqq_first_principles_trades.csv"
BACKTEST_1MIN_CSV_PATH = DATA_DIR / "alpaca_1min_model_reevaluation_2024_2026.csv"
BACKTEST_1MIN_REPORT_PATH = DATA_DIR / "alpaca_1min_model_reevaluation_report.json"

PRISM7_STRATEGY_CONFIGS = {
    "SOXL": {
        "symbol": "SOXL",
        "strategy_name": "SOXL_PRISM7_DEBIT_SPREAD",
        "strategy_prefix": "STRAT_SOXL_PRISM7_330",
        "capital_alloc_pct": 0.035,
        "max_debit_cap_pct": 0.035,
        "active_sleeves": PRISM7_SOXL_ACTIVE_SLEEVES,
        "disabled_sleeves": PRISM7_SOXL_DISABLED_SLEEVES,
        "tp_atr_mult": 0.48,
        "sl_atr_mult": 0.38,
        "opt_mark_tp_trigger": 1.45,
        "day1_zero_bounce_early_cut_pct": -0.028,
        "day1_zero_bounce_fav_atr_max": 0.10,
        "day1_zero_bounce_adv_atr_min": -0.35,
        "day1_early_cut_opt_loss_frac": -0.22,
        "be_stock_trigger_pct": 0.016,
        "be_opt_stop_frac": 0.965,
        "spread_width": 1.0,
        "max_hold_days": 3,
        "gtc_tp_width_frac": 0.85,
        "min_dte": 7,
        "max_dte": 14,
        "target_trades_per_week": "1.0 - 1.5 trades/week",
    },
    "TQQQ": {
        "symbol": "TQQQ",
        "strategy_name": "TQQQ_PRISM7_DEBIT_SPREAD",
        "strategy_prefix": "STRAT_TQQQ_PRISM7_330",
        "capital_alloc_pct": 0.035,
        "max_debit_cap_pct": 0.035,
        "active_sleeves": PRISM7_TQQQ_ACTIVE_SLEEVES,
        "disabled_sleeves": PRISM7_TQQQ_DISABLED_SLEEVES,
        "tp_atr_mult": 0.42,
        "sl_atr_mult": 0.35,
        "opt_mark_tp_trigger": 1.45,
        "day1_zero_bounce_early_cut_pct": -0.028,
        "day1_early_cut_opt_loss_frac": -0.185,
        "max_hold_days": 3,
        "gtc_tp_width_frac": 0.85,
        "min_dte": 7,
        "max_dte": 14,
        "target_trades_per_week": "1.0 - 1.5 trades/week",
    },
}

DEBIT_STRATEGY_CONFIGS = {
    "SOXL": {
        "symbol": "SOXL",
        "strategy_name": "SOXL_330_DEBIT_SPREAD",
        "strategy_prefix": "STRAT_SOXL_DEBIT_330",
        "risk_pct": 0.025,
        "elite_risk_pct": 0.025,
        "active_sleeves": SOXL_ACTIVE_SLEEVES,
        "disabled_1m_sleeves": SOXL_DISABLED_SLEEVES,
        "elite_35pct_sleeves": [],
        "mean_sl_frac": 0.3278,
        "max_debit_cap_pct": 0.040,
        "max_vxn_1d_spike_for_bull": 0.08,
        "max_friday_vix_for_bull": 19.0,
        "tp_atr_mult": 0.45,
        "sl_atr_mult": 0.381,
        "be_stock_trigger_pct": 0.02,
        "be_opt_stop_frac": 0.965,
        "max_hold_days": 3,
        "gtc_tp_width_frac": 0.85,
        "mon_wed_min_dte": 7,
        "mon_wed_max_dte": 14,
        "thu_fri_min_dte": 7,
        "thu_fri_max_dte": 14,
        "min_dte": 7,
        "max_dte": 14,
        "audit_path": ROOT_DATA_DIR / "soxl_first_principles_audit.json",
    },
    "TQQQ": {
        "symbol": "TQQQ",
        "strategy_name": "TQQQ_330_DEBIT_SPREAD",
        "strategy_prefix": "STRAT_TQQQ_DEBIT_330",
        "risk_pct": 0.025,
        "elite_risk_pct": 0.025,
        "active_sleeves": TQQQ_ACTIVE_SLEEVES,
        "disabled_1m_sleeves": TQQQ_DISABLED_SLEEVES,
        "elite_35pct_sleeves": [],
        "mean_sl_frac": 0.2311,
        "max_debit_cap_pct": 0.040,
        "max_vxn_1d_spike_for_bull": 0.08,
        "max_friday_vix_for_bull": 19.0,
        "tp_atr_mult": 0.42,
        "sl_atr_mult": 0.356,
        "day1_zero_bounce_fav_atr_max": 0.08,
        "day1_zero_bounce_adv_atr_min": -0.30,
        "day1_early_cut_opt_loss_frac": -0.185,
        "max_hold_days": 8,
        "gtc_tp_width_frac": 0.85,
        "mon_wed_min_dte": 7,
        "mon_wed_max_dte": 14,
        "thu_fri_min_dte": 7,
        "thu_fri_max_dte": 14,
        "min_dte": 7,
        "max_dte": 14,
        "audit_path": ROOT_DATA_DIR / "tqqq_first_principles_audit.json",
    },
}
