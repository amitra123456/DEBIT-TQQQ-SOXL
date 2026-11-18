# SOXL & TQQQ 3:30 PM Debit Spread Strategy — Feature-to-Schema & Data Dictionary Mapping

**Classification**: Quantitative Data Dictionary, Feature Engineering Formulas, & Schema Specification  
**Target Reviewer**: Sean (Data Integrity, Causality, & Schema Audit)  
**Package Location**: `soxl_tqqq_debit_330/`  

---

## 1. Multi-Granularity Data Ingestion & Causality Hierarchy

Every feature in the `soxl_tqqq_debit_330` package is bound to a strict publication timestamp so that **zero post-entry (`> 15:15–15:30 ET`) or post-close (`> 16:00 ET`) information can leak into trade decisions on Day $t$**:

```text
+----------------------------------------------------------------------------------------------------------+
|                         SOXL & TQQQ 3:30 PM DATA INGESTION & CAUSAL LAG HIERARCHY                        |
+----------------------------------------------------------------------------------------------------------+
|  1. PRIOR-DAY EOD (t-1, Published >16:30 ET on Day t-1)                                                  |
|     • SqueezeMetrics DIX & GEX (`data/historical/squeezemetrics_dix_gex_2011_2026.parquet`, `.shift(1)`) |
|     • FINRA / Alpaca TRF Dark Pool & ISO Whale Flow (`theta_flip_330/data/alpaca_trf/*.parquet`, `t-1`)  |
|                                                                                                          |
|  2. MORNING 10:30 AM ET SNAPSHOT (Day t @ 10:30:00 ET — 4.75 Hours Before Entry)                         |
|     • QQQ OPRA 0DTE Call/Put Walls & Net GEX (`data/historical/zero_dte_opra_walls_gex_2024_2026.parquet`)|
|                                                                                                          |
|  3. INTRADAY 3:12–3:30 PM ET CHECKPOINT BAR (Day t @ 15:12–15:30 ET)                                     |
|     • Underlying OHLCV (`SOXL`, `TQQQ`), Sector ETFs (`SMH`, `SOXX`, `QQQ`, `XLK`), & Peers              |
|     • Macro Volatility Term Structure (`^VIX`, `^VIX3M`, `^VXN`)                                         |
|                                                                                                          |
|  4. 1-MINUTE ALPACA STOCK & OPRA OPTION BARS (`2024-01-02` to `2026-11-11`)                              |
|     • `/v2/stocks/bars` (`timeframe=1Min`, RTH `09:30–16:00 ET`)                                         |
|     • `/v1beta1/options/bars` (`timeframe=1Min`, OPRA trade bars for listed option contracts)            |
|     • `/v1beta1/options/snapshots` (Live NBBO `bp`, `ap`, `mid` at `15:15 / 15:20 / 15:25 / 15:30 ET`)   |
+----------------------------------------------------------------------------------------------------------+
```

---

## 2. Exhaustive Feature Engineering & Input Schema Mapping Table

| Feature Name | Granularity & Causal Lag | Source File / API Endpoint | Source Columns | Type | Exact Mathematical Formula / Definition | Role in Strategy & Sleeves |
| :--- | :---: | :--- | :--- | :---: | :--- | :--- |
| `s_px`, `s_high`, `s_low` | **Day $t$ (`15:15–15:30 ET`)** | `data/historical/SOXL_1d.parquet`, `TQQQ_1d.parquet` + live `yfinance` / Alpaca `5m`/`1m` | `Open`, `High`, `Low`, `Close` $\times$ `sf_arr` | `float ($)` | Unsplit / as-traded price reconstructed via historical split factor `sf_arr` (`1.0` post-2021 `SOXL` / post-2022 `TQQQ`) | Reconstructs exact as-traded dollar strike levels (`$5.00`, `$2.50`, `$1.25` grids) and OPRA wall distances across all historical eras. |
| `atr14`, `s_atr` | **Day $t$ (14-Day Wilder/Rolling)** | [`multi_stock_engine.py`](file:///c:/Users/amitr/OneDrive/Documents/ANT_SOX/strategy/reversal_sniper_330pm/core/multi_stock_engine.py) | `High`, `Low`, `Close` | `float ($)` | $\text{ATR}_{14} = \text{Mean}_{14}\big(\max(H_t - L_t, |H_t - C_{t-1}|, |L_t - C_{t-1}|)\big)$ | Normalizes all target distances (`+0.45 ATR` `SOXL`, `+0.42 ATR` `TQQQ`), stop distances, and VWAP stretch. |
| `rsi2`, `rsi3` | **Day $t$ (`15:15–15:30 ET`)** | [`multi_stock_engine.py`](file:///c:/Users/amitr/OneDrive/Documents/ANT_SOX/strategy/reversal_sniper_330pm/core/multi_stock_engine.py) | `Close` | `float (0–100)` | 2-period and 3-period Wilder RSI of `Close` | Primary short-horizon exhaustion/mean-reversion oscillators (`rsi2 < 15` / `< 20` for Bull sleeves; `rsi3 > 90` for Exhaustion Bear; `rsi3 > 40` for 200-SMA Breakdown Bear). |
| `ibs` | **Day $t$ (`15:15–15:30 ET`)** | [`multi_stock_engine.py`](file:///c:/Users/amitr/OneDrive/Documents/ANT_SOX/strategy/reversal_sniper_330pm/core/multi_stock_engine.py) | `High`, `Low`, `Close` | `float (0.0–1.0)` | $\text{IBS}_t = \frac{C_t - L_t}{H_t - L_t + 10^{-9}}$ | Internal Bar Strength. Measures where price sits within the day's range (`ibs < 0.25` for washout dips; `ibs > 0.80` for parabolic top exhaustion). |
| `sma50`, `sma100`, `sma200`, `ema20` | **Day $t$ (`15:15–15:30 ET`)** | [`calibrate_soxl.py`](file:///c:/Users/amitr/OneDrive/Documents/ANT_SOX/soxl_tqqq_debit_330/calibration/calibrate_soxl.py), [`calibrate_tqqq.py`](file:///c:/Users/amitr/OneDrive/Documents/ANT_SOX/soxl_tqqq_debit_330/calibration/calibrate_tqqq.py) | `Close` | `float ($)` | Simple Moving Averages (`50`, `100`, `200` bars) and 20-bar Exponential Moving Average | Macro & intermediate trend anchors (`c > sma200` bull regime; `c < sma200` bear breakdown regime; `ema20` coil/reclaim anchor). |
| `vwap5`, `vwap20` | **Day $t$ (5D & 20D Rolling)** | [`calibrate_soxl.py`](file:///c:/Users/amitr/OneDrive/Documents/ANT_SOX/soxl_tqqq_debit_330/calibration/calibrate_soxl.py#L120-L126) | `High`, `Low`, `Close`, `Volume` | `float ($)` | $\text{VWAP}_N = \frac{\sum_{i=0}^{N-1} \frac{H_{t-i}+L_{t-i}+C_{t-i}}{3} \cdot V_{t-i}}{\sum_{i=0}^{N-1} V_{t-i}}$ | 5-day and 20-day institutional volume-weighted average price benchmarks. |
| `dist_vwap5`, `dist_vwap20` | **Day $t$ (`15:15–15:30 ET`)** | [`calibrate_soxl.py`](file:///c:/Users/amitr/OneDrive/Documents/ANT_SOX/soxl_tqqq_debit_330/calibration/calibrate_soxl.py#L125-L126) | `Close`, `vwap5`, `atr14` | `float (ATRs)` | $\frac{C_t - \text{VWAP}_5}{\text{ATR}_{14}}$ | ATR-normalized stretch below/above 5-day institutional VWAP (`dist_vwap5 < -0.35` triggers Phase 1 VWAP Bull sleeves). |
| `rth_ret`, `ovn_ret` | **Day $t$ (`09:30` vs `15:15–15:30`)** | [`calibrate_soxl.py`](file:///c:/Users/amitr/OneDrive/Documents/ANT_SOX/soxl_tqqq_debit_330/calibration/calibrate_soxl.py#L179-L185) | `Open`, `Close` | `float (dec)` | $\text{rth\_ret}_t = \frac{C_t - O_t}{O_t}, \quad \text{ovn\_ret}_t = \frac{O_t - C_{t-1}}{C_{t-1}}$ | Separates daytime institutional cash-session flow (`RTH`) from retail overnight gap flow (`OVN`). |
| `rth_sum5`, `rth_sum3`, `rth_vs_ovn_5d` | **Day $t$ (3D & 5D Rolling)** | [`calibrate_soxl.py`](file:///c:/Users/amitr/OneDrive/Documents/ANT_SOX/soxl_tqqq_debit_330/calibration/calibrate_soxl.py#L183-L185) | `rth_ret`, `ovn_ret` | `float (dec)` | $\sum_{i=0}^{4} \text{rth\_ret}_{t-i}$ and $\sum_{i=0}^{4}(\text{rth\_ret}_{t-i} - \text{ovn\_ret}_{t-i})$ | Raju RTH Institutional Flow Differential. Positive values confirm institutions are net buyers during cash hours despite overnight pullbacks. |
| `semi_rel` (`SOXL`) / `qqq_rel` (`TQQQ`) | **Day $t$ (`15:15–15:30 ET`)** | [`multi_stock_engine.py`](file:///c:/Users/amitr/OneDrive/Documents/ANT_SOX/strategy/reversal_sniper_330pm/core/multi_stock_engine.py) | `SOXL`, `NVDA`, `TSM`, `AVGO`, `AMD`, `SMH`, `SOXX`, `QQQ` | `float (dec)` | Peer & sector relative velocity differential (`stock_ret - sector_etf_ret` & peer breadth) | Measures peer-group leadership (`semi_vel_up`, `qqq_vel_up`) and sector impulse (`Phase4_SOXX_DipImpulse_Bull`, `Phase4_QQQ_DipImpulse_Bull`). |
| `vix_term`, `vxn_term` | **Day $t$ (`15:15–15:30 ET`)** | `macro_sentiment_universe_1d.parquet` | `VIX_close`, `VXN_close`, `VIX3M_close` | `float (ratio)` | $\frac{\text{VIX}_t}{\text{VIX3M}_t}, \quad \frac{\text{VXN}_t}{\text{VIX3M}_t}$ | Volatility Term Structure Ratio. `vix_term < 1.12` (contango / mild backwardation) passes `shock_ok`; `> 1.12` blocks entries during crash backwardation. |
| `dix`, `dix_z20`, `gex_bn`, `gex_z20` | **Prior Day $t-1$ (`.shift(1)`)** | `data/historical/squeezemetrics_dix_gex_2011_2026.parquet` | `dix`, `gex_bn`, `dix_z20`, `gex_z20` | `float` | `dix_gex_df[col].shift(1)` (strictly $t-1$ EOD publication) | SqueezeMetrics Dark Index (`DIX`) & Dealer Gamma Exposure (`GEX`). Blocks Bull entries if both `gex_z20 < -1.50` and `dix_z20 < -0.50` (gamma vacuum without dark pool buying). |
| `qqq_call_wall_1030`, `qqq_put_wall_1030`, `qqq_gex_imb_1030` | **Day $t$ @ `10:30 AM ET`** | `data/historical/zero_dte_opra_walls_gex_2024_2026.parquet` | `call_wall_1030`, `put_wall_1030`, `gex_imb_1030` | `float` | Snapped from OPRA 0DTE chain at `10:30 AM ET` on Day $t$ | Morning dealer gamma wall and imbalance telemetry (`4.75 hours` prior to `3:15 PM` entry). |
| `semi_flow_bull_ok` / `whale_bull_ok` | **Prior Day $t-1$ TRF Cache** | `theta_flip_330/data/alpaca_trf/*.parquet` | `dark_pool_ratio_pct`, `whale_volume_share_pct`, `iso_net_buy_pct` | `bool` | `False` if `DPR < 35%` and `Whale >= 4.0%` and `ISO < -10.0%` | Institutional Dark Pool / ISO Sweep Gate on peer components (`TSM`, `AMD`, `GOOGL`, `CRM`, `PANW`). Vetoes bull entries during institutional block distribution. |
| `put_wall_strike`, `call_wall_strike`, `put_wall_reclaim` | **Day $t$ (`15:15–15:30 ET`)** | [`calibrate_soxl.py`](file:///c:/Users/amitr/OneDrive/Documents/ANT_SOX/soxl_tqqq_debit_330/calibration/calibrate_soxl.py#L139-L143) | `s_px`, `s_low`, `grid_w` | `float ($)` / `bool` | $\text{put\_wall} = \lfloor s\_px / w \rfloor \cdot w$; $\text{reclaim} = (s\_low < \text{put\_wall}) \land (s\_px > \text{put\_wall})$ | Identifies intraday dealer gamma put-wall spring (`s_low` pierces strike grid wall and reclaims it by `3:15–3:30 PM ET`). |
| `call_wall_pinned_veto` | **Day $t$ (`15:15–15:30 ET`)** | [`calibrate_soxl.py`](file:///c:/Users/amitr/OneDrive/Documents/ANT_SOX/soxl_tqqq_debit_330/calibration/calibrate_soxl.py#L145-L147) | `s_px`, `gex_z20`, `dix_z20` | `bool` | `(0 < (ceil(s_px/5)*5 - s_px)/s_px <= 2.0%) & (gex_z20 > 0) & (dix_z20 < 0)` | Overhead Major `$5` Call Wall Pin Veto. Blocks buying call spreads directly underneath a heavy positive-GEX `$5` call wall when dark pools are not buying. |
| `ibs_1520`, `vwap_1520`, `no_freefall_1520` | **Day $t$ (`09:30–15:20 ET` 1Min)** | [`walk_forward_audit.py`](file:///c:/Users/amitr/OneDrive/Documents/ANT_SOX/soxl_tqqq_debit_330/backtest/walk_forward_audit.py#L51-L97) | Alpaca `1Min` stock bars `o, h, l, c, v` | `float` / `bool` | Computed exclusively from `09:30–15:20 ET` 1-minute bars on Day 0 | 1-minute microstructure diagnostics verifying intraday VWAP distance and absence of late-day free-fall waterfalls at `15:20 ET`. |

---

## 3. Output Schema Mapping: Trade Ledgers & Audit Files

### 3.1 Daily & 1-Minute Backtest Trade Ledgers (`soxl_first_principles_trades.csv`, `tqqq_first_principles_trades.csv`, `alpaca_1min_backtest_1yr_trades.csv`)

| Column Name | Type | Description & Calculation |
| :--- | :---: | :--- |
| `date` / `entry_date` | `str (YYYY-MM-DD)` | Signal entry date (Day 0, entered in the `15:15–15:30 ET` window). |
| `exit_date` / `exit_time_et` | `str` | Exact date (and `HH:MM ET` minute timestamp in 1-minute backtest) when the spread closed. |
| `symbol` | `str` | Underlying ETF ticker (`"SOXL"` or `"TQQQ"`). |
| `sleeve` | `str` | Canonical name of the triggering strategy sleeve (e.g., `"Phase1_VWAP5_RTH_Bull"`, `"Phase6_SMA200_Breakdown_Bear"`). |
| `dir` | `int (+1 / -1)` | Trade direction: `+1` for Bull Call Debit Spread, `-1` for Bear Put Debit Spread. |
| `structure` | `str` | `"Bull Call Spread"` or `"Bear Put Spread"`. |
| `expiry_rule` / `expiration_date` | `str` | Expiration selection rule (`"This Friday (2-4 DTE)"` on Mon–Wed; `"Next Friday (5-6 DTE)"` on Thu–Fri) and exact OCC expiration date `YYYY-MM-DD`. |
| `long_symbol`, `short_symbol` | `str` | Exact OCC option symbols from Alpaca `/v2/options/contracts` (e.g., `SOXL260828C00111000` / `SOXL260828C00113000`). |
| `k_long`, `k_short`, `width` | `float ($)` | Long leg strike, short leg strike, and vertical spread width $|k_{\text{short}} - k_{\text{long}}|$. |
| `as_traded_entry` / `entry_spot_1515` | `float ($)` | As-traded underlying spot price at entry (`15:15–15:30 ET` on Day 0). |
| `as_traded_exit` / `exit_spot` | `float ($)` | As-traded underlying spot price at exit. |
| `tp_target` / `tp_px` | `float ($)` | Underlying structural take-profit price (`spot_px + tp_move * dir`). |
| `sl_stop` / `sl_px` | `float ($)` | Underlying structural stop-loss price (`spot_px - sl_move * dir`). |
| `be_trigger_px`, `be_opt_stop_mid` | `float ($)` | (`SOXL` Only) Underlying `+2.0%` favorable excursion price that arms the Method A Breakeven Stop, and the corresponding `-3.5%` option midpoint stop (`0.965 * entry_mid`). |
| `calibrated_opra_iv` | `float (dec)` | Implied volatility calibrated strictly from Day-0 (`<= 15:15 ET`) Alpaca 1-minute OPRA option bars. |
| `opra_1m_bars_long`, `opra_1m_bars_short` | `int` | Count of real 1-minute OPRA option bars loaded from `/v1beta1/options/bars` for the long and short legs. |
| `candles_1m_scanned` | `int` | Total number of RTH 1-minute candles (`09:30–16:00 ET`) stepped through from entry to exit. |
| `entry_mid`, `exit_mid` | `float ($)` | Option spread debit midpoint at entry and credit midpoint at exit. |
| `days` / `days_held` | `int` | Number of trading days held (`1` to `max_hold_days`). |
| `exit_reason` | `str` | Exact exit rule triggered (`INTRABAR_1MIN_GTC_85TP_FILL`, `DAY1_1330_1MIN_ZERO_BOUNCE_EARLY_CUT`, `EOD_1525_TP_EXIT`, `EOD_1525_SOXL_BE_STOP`, `EOD_1530_1MIN_STRUCTURAL_STOP`, etc.). |
| `stock_ret_pct` | `float (%)` | Directional underlying stock return over the holding window (`((exit_px - entry_px) / entry_px * 100) * dir`). |
| `opt_roi_pct`, `opt_roi_dec` | `float` | Net realized option spread return after deducting `$0.01/spread` (`$0.50/leg`) round-trip slippage/commission drag. |
| `win` | `bool` | `True` if `opt_roi_pct > 0`, else `False`. |

---

### 3.2 Live Alpaca Execution Ledger (`soxl_tqqq_alpaca_debit_ledger.json`)

Each entry in [`soxl_tqqq_alpaca_debit_ledger.json`](file:///c:/Users/amitr/OneDrive/Documents/ANT_SOX/soxl_tqqq_debit_330/data/soxl_tqqq_alpaca_debit_ledger.json) persists the live order and position state for automated EOD and `1:30 PM` monitoring:

| JSON Field | Type | Description |
| :--- | :---: | :--- |
| `timestamp_et` | `str` | Order submission timestamp in `YYYY-MM-DD HH:MM:SS ET`. |
| `checkpoint_et` | `str` | Checkpoint label (`"15:15"`, `"15:20"`, `"15:25"`, `"15:30"`). |
| `order_id` | `str (UUID)` | Alpaca broker order ID returned by `POST /v2/orders`. |
| `client_order_id` | `str` | Canonical strategy-tagged ID: `STRAT_{SYM}_DEBIT_330__{SLEEVE}__CP{HHMM}__{YYYYMMDD}_{HHMMSS}`. |
| `strategy_name`, `strategy_tag` | `str` | Canonical strategy identifier (`SOXL_330_DEBIT_SPREAD` or `TQQQ_330_DEBIT_SPREAD`) and sleeve tag. |
| `status` | `str` | Live order/position lifecycle state (`accepted`, `filled`, `CLOSED (EOD_330PM_TAKE_PROFIT)`, etc.). |
| `underlying`, `direction`, `strategy_type` | `str / int` | Ticker (`SOXL` / `TQQQ`), direction (`+1` / `-1`), and spread description. |
| `long_symbol`, `short_symbol`, `long_strike`, `short_strike`, `expiration_date`, `width` | `str / float` | Exact OCC leg symbols, strike prices, expiration date, and dollar width. |
| `qty` | `int` | Number of spreads submitted/filled (sized at flat `2.5%` account risk). |
| `debit_mid`, `limit_price_submitted`, `gtc_tp_limit`, `sl_opt_mid` | `float ($)` | Initial midpoint, submitted limit price, resting `85%` width TP limit price, and expected stop midpoint. |
| `entry_px`, `spot_px`, `tp_px`, `sl_px`, `be_trigger_px`, `be_opt_stop_mid`, `max_hold_days` | `float / int` | Underlying entry price, structural target/stop levels, `SOXL` breakeven trigger levels, and max hold days (`3` `SOXL`, `8` `TQQQ`). |
| `risk_dollars` | `float ($)` | Dollar risk allocated (`0.025 * equity`). |
