# SOXL & TQQQ 3:15–3:30 PM ET Debit Spread Strategy (`soxl_tqqq_debit_330`)

This package contains the self-contained production execution engine, calibration pipeline, 1-minute OPRA backtester, walk-forward causality auditor, and institutional specification documentation for the **SOXL & TQQQ 3:15–3:30 PM ET Vertical Debit Spread Strategy**.

---

## Institutional Specification Documents (For Sean's Independent Testing & Audit)

All strategy documentation has been organized into three comprehensive, fully auditable specification documents in [`soxl_tqqq_debit_330/docs/`](file:///c:/Users/amitr/OneDrive/Documents/ANT_SOX/soxl_tqqq_debit_330/docs):

1. **[Order Lifecycle & Execution Specification (`SEAN_EXECUTION_AND_ORDER_LIFECYCLE_SPECIFICATION.md`)](file:///c:/Users/amitr/OneDrive/Documents/ANT_SOX/soxl_tqqq_debit_330/docs/SEAN_EXECUTION_AND_ORDER_LIFECYCLE_SPECIFICATION.md)**
   - Step-by-step chronological lifecycle of every action taken to **open**, **modify**, and **close** orders (`10:30 AM` 0DTE snapshot $\rightarrow$ `3:12 PM` Stage 1 Alert $\rightarrow$ `3:15 PM` Stage 2 Confirm $\rightarrow$ `3:20 PM` Stage 3 Execute $\rightarrow$ Intraday `5-min` Active Monitor $\rightarrow$ `Day 1–3` `3:25–3:30 PM` EOD Structural Check).
   - Exact JSON payloads sent to Alpaca (`mleg` entry orders, cancel-and-replace limit price chasing, resting stop-limit order modifications, and multi-leg close orders with 2-leg fallback).
   - Strike selection, expiration targeting (`7–14 DTE`), and flat `2.5%` account equity position sizing math.

2. **[Column & Feature Schema Mapping (`FEATURE_AND_DATA_SCHEMA_MAPPING.md`)](file:///c:/Users/amitr/OneDrive/Documents/ANT_SOX/soxl_tqqq_debit_330/docs/FEATURE_AND_DATA_SCHEMA_MAPPING.md)**
   - Complete dictionary of every raw data source, engineered feature column, mathematical formula, rolling window, publication lag (`t-1` shifts), and schema mapping across `daily_features.parquet`, `trades.parquet`, `live_state.json`, `active_positions.json`, and 1-minute OPRA audit outputs.

3. **[Models Architecture, Sleeve Behavior, & Causality Audit (`MODELS_ARCHITECTURE_AND_CAUSALITY_AUDIT.md`)](file:///c:/Users/amitr/OneDrive/Documents/ANT_SOX/soxl_tqqq_debit_330/docs/MODELS_ARCHITECTURE_AND_CAUSALITY_AUDIT.md)**
   - Exact trigger formulas, economic intuition, and 1-minute OPRA performance for all **12 active walk-forward sleeves (`6 SOXL + 6 TQQQ`)** and the **2 pruned sleeves (`SOXL::Phase2_SMA50_SemiVel_Bull`, `TQQQ::Phase7_GEX_PutWall_Reclaim_Bull`)**.
   - The 7 Live Readiness Gates, real OPRA implied volatility dynamics (`131%` median `SOXL` IV vs. `63%` median `TQQQ` IV), asymmetric exit rules, and the complete **Zero-Leakage & Anti-Overfitting Audit Checklist**.

---

## Package Directory Layout

```text
soxl_tqqq_debit_330/
├── __init__.py
├── README.md                                 # Master index (this file)
├── config.py                                 # Central parameters, flat 2.5% risk, active/disabled sleeves
├── docs/
│   ├── SEAN_EXECUTION_AND_ORDER_LIFECYCLE_SPECIFICATION.md
│   ├── FEATURE_AND_DATA_SCHEMA_MAPPING.md
│   └── MODELS_ARCHITECTURE_AND_CAUSALITY_AUDIT.md
├── execution/
│   ├── __init__.py
│   └── alpaca_trader.py                      # Autonomous Alpaca multi-leg execution & lifecycle daemon
├── calibration/
│   ├── __init__.py
│   ├── calibrate_soxl.py                     # SOXL feature engineering & 6 active sleeve evaluator
│   └── calibrate_tqqq.py                     # TQQQ feature engineering & 6 active sleeve evaluator
├── backtest/
│   ├── __init__.py
│   ├── backtest_1min_alpaca.py               # 1-minute stock + 1-minute OPRA option bar backtester
│   └── walk_forward_audit.py                 # Train (2024-2025) -> OOS (2025-2026) & 15:15 ET causality audit
├── ui/
│   ├── __init__.py
│   ├── soxl_desk.py                          # Streamlit SOXL Desk tab
│   └── tqqq_desk.py                          # Streamlit TQQQ Desk tab
└── data/                                     # Strategy state, telemetry Parquets, and 1-min audit CSVs
```

---

## Quick Verification Commands

```powershell
# 1. Re-sync daily features & telemetry for SOXL and TQQQ
C:\Python314\python.exe -m soxl_tqqq_debit_330.calibration.calibrate_soxl
C:\Python314\python.exe -m soxl_tqqq_debit_330.calibration.calibrate_tqqq

# 2. Dry-run live execution readiness check (no orders placed without --execute)
C:\Python314\python.exe -m soxl_tqqq_debit_330.execution.alpaca_trader

# 3. Run the 1-minute Alpaca stock + OPRA option bar backtest
C:\Python314\python.exe -m soxl_tqqq_debit_330.backtest.backtest_1min_alpaca

# 4. Run the strict Walk-Forward & 15:15 ET Causality Audit
C:\Python314\python.exe -m soxl_tqqq_debit_330.backtest.walk_forward_audit
```


---

## JANUS-5 / UMB / FR-VWAP + 15:50 TPO & 1m Delta Flow (CVD) Sniper Suite (`janus5_umb_tpo_cvd/`)

* **[Strategy Manual: Entry, Exit, & Trade Management with Flowcharts (`docs/JANUS5_UMB_TPO_CVD_STRATEGY_AND_TRADE_MANAGEMENT.md`)](./docs/JANUS5_UMB_TPO_CVD_STRATEGY_AND_TRADE_MANAGEMENT.md)** — Complete specification of the 2-Layer Hierarchy, Bull/Bear entry archetypes, `15:50 ET` vs. `10:00 AM ET` `TPO + 1m CVD` execution gates, profit targets, structural stops, cooldown rules, and Mermaid flowcharts.

In addition to the 3:15–3:30 PM ET Debit Spread engine, this repository includes the **2-Layer JANUS-5 / UMB / Fixed-Range VWAP + 15:50 TPO Market Profile & 1m Delta Flow (CVD) Sniper Suite** and its complete `1999–2026` / `2020–2026` model datasets:

### Code & TradingView Pine (`janus5_umb_tpo_cvd/`)
* `macro_5pct_early_stage_v6.pine`: **JANUS-5 Dual-Regime Sniper** TradingView Pine Script v6 (`B1–B4` Top/Bottom Sniper + `5d Exhaustion Volume` + `Flush/Trough FR-VWAP` + `V-Bottom` & `Bull Surf Dip`).
* `run_janus_tpo_cvd_sniper.py`: Unified **2-Layer Production Engine** combining Layer 1 (`JANUS-5 / UMB Macro Regime + 5d Exhaustion Volume & Flush/Trough FR-VWAP`) with Layer 2 (`15:50 TPO Profile + 1m Delta Flow CVD`) across `TQQQ/SQQQ` and `SOXL/SOXS`.
* `test_2020_2023_untouched_tpo_cvd_sqqq_soxs.py`: Untouched `2020–2023` (including `2022` Bear Market) and `2020–2026` walk-forward backtest with real `SQQQ` and `SOXS` fills and `1x/2x/3x` transaction costs.
* `audit_or_tpo_delta_gex_due_diligence.py`: Institutional strategy due-diligence suite (`1m/5m/30m OR`, `TPO POC/VAH/VAL`, `1m CVD`, `Session VWAP`, `OPRA 0DTE GEX/Walls`, ablation, 200-permutation placebo tests, and tail-risk metrics).
* `optimize_dead_cat_bounce_universe.py` & `optimize_ticker_specific_rules.py`: Upgraded Dead-Cat Bounce (`DCB`) vs. Real Bounce (`GB`) detector (`5d Exhaustion Volume` + `Flush/Trough FR-VWAP`).
* `compute_todays_umb_scores.py`: Daily `UMB` (`Model U`, `Model M`, `Model B`) calculator with `5d Exhaustion Volume` and `FR-VWAP`.

### Model Data (`data/models_2020_2026/`)
* `*_1m_2020-01-02_2026-11-17_rth.parquet`: Real 1-minute Alpaca SIP RTH bars (`2020–2026`, `1,729` sessions each) for `QQQ`, `TQQQ`, `SQQQ`, `SOXX`, `SOXL`, and `SOXS`.
* `*_1550_tpo_cvd_2020_2026.parquet`: Precomputed `15:50` Market Profile `TPO` (`POC`, `VAH`, `VAL`, `Buying/Selling Tails`) and `1m Delta Flow (CVD)` model tables (`2020–2026`) for `QQQ`, `TQQQ`, `SQQQ`, `SOXX`, `SOXL`, and `SOXS`.
* `zero_dte_opra_walls_gex_2024_2026.parquet` & `squeezemetrics_dix_gex_2011_2026.parquet`: Real OPRA `0DTE` Call/Put Walls, Gamma Flip, Net `GEX`, and SqueezeMetrics `DIX/GEX`.
* `qqq_features_1999_2026.parquet`, `spy_features_1999_2026.parquet`, `qqq_disjoint_6domain_dataset_1999_2026.parquet`, `final_9tier_daily_probabilities_1999_2026.parquet`, `final_bottom_daily_scores_1999_2026.parquet`: Full `1999–2026` macro and `UMB` probability panels.
