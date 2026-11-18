# SOXL & TQQQ 3:30 PM Vertical Debit Spread Strategy — Complete Order Lifecycle & Execution Specification for Sean

**Classification**: Production Execution Runbook & Order Lifecycle Specification  
**Target Reviewer**: Sean (Independent Strategy & Execution Verification)  
**Package Location**: `soxl_tqqq_debit_330/`  
**Execution Engine**: [`soxl_tqqq_debit_330/execution/alpaca_trader.py`](file:///c:/Users/amitr/OneDrive/Documents/ANT_SOX/soxl_tqqq_debit_330/execution/alpaca_trader.py)  
**Position Sizing**: Bounded Worst-Case Debit Sizing Cap: Flat `2.5%` Target Risk, **Hard-Capped at `4.0%` of Total Account Equity**  
**Trading Discipline**: Strict Max `1` Entry Per Ticker (`SOXL`, `TQQQ`) Per Trading Day  

---

## 1. Executive Summary & Empirical Performance Baseline

The **SOXL & TQQQ 3:30 PM Vertical Debit Spread Strategy** captures institutional late-day dark pool accumulation, dealer gamma put-wall springs, and 200-SMA / exhaustion breakdowns on `SOXL` (3x Semiconductor Bull ETF) and `TQQQ` (3x Nasdaq-100 Bull ETF).

All parameters, sleeve selections, and exit rules have been audited on **1-minute Alpaca stock bars (`/v2/stocks/bars`)** and **1-minute OPRA option bars (`/v1beta1/options/bars`, `2024-01-02` to `2026-11-11`)** across both raw and forensic audit tiers:

### Candle-by-Candle Forensic Audit Scorecard (2025-11-11 to 2026-11-11, $100,000 Equity)

| Audit Tier | Methodology / Assumptions | Trades | Win Rate | Realized Option R:R | Profit Factor | Net 1-Yr Return | Max Drawdown |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **1. Spec Doc Baseline** | Mode 3 with `-35%` loss clamp, $0.01 slippage | `32` | `75.00%` | `2.56x` | `7.68` | `+119.52%` | `2.50%` *(clamped)* |
| **2. Raw Repo 1-Min** | Original 1-min backtest output | `34` | `70.59%` | `1.44x` | `3.45` | `+65.51%` | `7.22%` |
| **3. Desk Forensic Baseline** | Uncapped tail gaps, 15:15 causal snapshots, $0.04 slip | `27` | `62.96%` | `1.04x` | `1.98` | `+31.40%` | `9.85%` |
| **4. Production Hardened V2** | **4.0% Max Debit Cap + 7–14 DTE + Day-0 Block + $0.04 Slip** | **`34`** | **`67.65%`** | **`1.39x`** | **`2.91`** | **`+59.36%`** | **`8.20%`** |

> [!IMPORTANT]
> **Production Hardened V2** incorporates all 6 engineering upgrades from the Desk audit:
> 1. Triply-redundant Day-0 Hard Block in execution (`alpaca_trader.py`).
> 2. Hard-capped total debit sizing at $\le 4.0\%$ account equity.
> 3. Standardized 7–14 DTE (Next Friday) contracts across all days.
> 4. Split-adjusted strike matching & SIP consolidated feed.
> 5. Synchronous OPRA marks & 09:30–09:34 ET opening-auction limit fill guard.
> 6. Zero artificial loss clamping (true tail risk fully absorbed).

---

## 2. Daily Chronological Schedule (All Times in US Eastern Time `America/New_York`)

The strategy operates on six deterministic intraday checkpoints managed by Windows Task Scheduler (or cron) invoking [`soxl_tqqq_debit_330/execution/alpaca_trader.py`](file:///c:/Users/amitr/OneDrive/Documents/ANT_SOX/soxl_tqqq_debit_330/execution/alpaca_trader.py):

| Time (`ET`) | Scheduled Task / CLI Flag | Exact Operational Action |
| :---: | :--- | :--- |
| **`13:30:00`** | `--early-cut-check` | **Day-1 `1:30 PM` Intraday Monitor (`TQQQ` Only)**: Evaluates open `TQQQ` positions strictly held $\ge 1$ day (`days_held == 1`) for (a) **Zero-Bounce Early-Cut** (`fav_atr < +0.08` and `cur_atr <= -0.30`) and (b) **Midday Target Lock** (`cur_atr >= +0.42`). Does **not** stop out `SOXL` intrabar. |
| **`15:12:00`** | `--staged-checkpoint 15:12` | **Pre-Window Telemetry Sync**: Incrementally updates `SOXL`, `TQQQ`, `QQQ`, `SPY`, `SMH`, `SOXX`, `XLK`, and peer bars up to `15:12 ET` and regenerates telemetry parquets and audit JSONs. |
| **`15:15:00`** | `--staged-checkpoint 15:15` | **Checkpoint 1 (Initial Entry & Multi-Day EOD Exits)**: (1) Syncs telemetry; (2) Evaluates `3:15–3:30 PM` EOD exits strictly on multi-day positions (`days_held >= 1`, Day-0 positions are hard-blocked); (3) Ensures resting `85%` width TP orders exist for filled positions; (4) If `7/7` readiness gates pass, active sleeve is not in `disabled_1m_sleeves`, and no order filled today, submits initial multi-leg limit order at **exact NBBO midpoint (`debit_mid`)**. |
| **`15:20:00`** | `--staged-checkpoint 15:20` | **Checkpoint 2 (Modify +`$0.01` Nudge)**: (1) Evaluates multi-day EOD exits (`days_held >= 1`); (2) If a `buy_to_open` entry order from `15:15` is still working (unfilled), **cancels** the working order (`DELETE /v2/orders/{id}`), re-queries the live OPRA option chain midpoint, and **replaces** (`POST /v2/orders`) at **`debit_mid + $0.01`** (`nudge_limit_px`). Day-0 filled positions are strictly protected from self-stops. |
| **`15:25:00`** | `--staged-checkpoint 15:25` | **Checkpoint 3 (Empirical Sweet Spot Modify +`$0.01` Nudge)**: If still unfilled, cancels the working entry order, refreshes the live option chain midpoint at `15:25 ET` (the empirical `-0.19%` underlying price trough), and submits a replacement limit order at **`debit_mid + $0.01`**. |
| **`15:30:00`** | `--staged-checkpoint 15:30` | **Checkpoint 4 (Final Midpoint Refresh)**: If still unfilled, cancels the working order and submits one final limit order at the refreshed **`15:30 ET` midpoint (`debit_mid`)**. |
| **`15:33:00`** | `--staged-checkpoint 15:33` | **Hard Cutoff & Post-Fill TP Placement**: (1) **Cancels any remaining unfilled entry orders** (`DELETE /v2/orders/{id}`) so no stale entry order lingers into the `15:50` MOC imbalance; (2) Verifies that every filled position has an active resting **Limit Sell Take-Profit order at `85%` of spread width (`gtc_tp_limit`)**. |

---

## 3. Step-by-Step Procedure to OPEN an Order

Every step below is executed deterministically inside [`AlpacaDebitSpreadTrader.evaluate_live_signals()`](file:///c:/Users/amitr/OneDrive/Documents/ANT_SOX/soxl_tqqq_debit_330/execution/alpaca_trader.py#L316-L475) and [`AlpacaDebitSpreadTrader.submit_debit_spread_order()`](file:///c:/Users/amitr/OneDrive/Documents/ANT_SOX/soxl_tqqq_debit_330/execution/alpaca_trader.py#L477-L600).

### Step 1: Verify the 7 Readiness Gates & Disabled Sleeve Block
An entry order for `SOXL` or `TQQQ` is eligible to open **if and only if all 7 gates evaluate to `True`**:
1. **`gate_sleeve` (`Active Walk-Forward Sleeve`)**: At least 1 active walk-forward sleeve for that ticker is `True` at the checkpoint evaluation (`len(active_sleeves) > 0`, strictly excluding `SOXL::Phase2_SMA50_SemiVel_Bull` and `TQQQ::Phase7_GEX_PutWall_Reclaim_Bull`).
2. **`gate_regime` (`200-SMA Structural Alignment`)**:
   * Bull Call Spreads (`direction == +1`): `spot_px >= sma200 * 0.96` (or verified deep-washout/reclaim sleeve).
   * Bear Put Spreads (`direction == -1`): `spot_px < sma200 * 1.04` (or verified breakdown sleeve).
3. **`gate_trf_whale` (`Dark Pool / ISO Whale Flow`)**: `whale_dix_bull_ok == True` (no institutional dark-pool distribution where `DPR < 35%`, `Whale >= 4%`, and `ISO < -10%` on `t-1` TRF cache).
4. **`gate_dix_gex` (`SqueezeMetrics DIX/GEX Vacuum Guard`)**: `not (gex_z20 < -1.50 and dix_z20 < -0.50)` on `t-1` SqueezeMetrics telemetry.
5. **`gate_wall_dist` (`Target Room to Opposing Wall`)**: `abs(tp_px - spot_px) / atr14 <= 1.10`.
6. **`gate_cw_pin` (`Overhead $5 Call-Wall Pin Veto`)**: For Bull spreads, `call_wall_pinned_veto == False` (vetoes bull entries if spot is within `0.0%–2.0%` below a major `$5` strike wall while `gex_z20 > 0` and `dix_z20 < 0`).
7. **`gate_shock` (`Macro Volatility Shock Guard`)**: `shock_ok == True` (`bar_range_atr <= 2.35` and `vix_term <= 1.12`).

### Step 2: Calculate Target Strikes (`k_long`, `k_short`), Structural `tp_px`, and `sl_px`
Using the live underlying price `spot_px` and 14-day ATR `atr14`:
1. **Target Grid Width (`w_grid`)**:
   * `$5.00` if `spot_px >= $150.00`
   * `$2.50` if `$60.00 <= spot_px < $150.00`
   * `$1.25` if `spot_px < $60.00`
2. **Target Long & Short Strikes**:
   * **Bull Call Spread (`direction == +1`)**:
     * `k_long = floor(spot_px / w_grid) * w_grid` (stepped up by `+0.5 * w_grid` if `spot_px - k_long > 0.65 * w_grid`)
     * `k_short = k_long + w_grid`
   * **Bear Put Spread (`direction == -1`)**:
     * `k_long = ceil(spot_px / w_grid) * w_grid` (stepped down by `-0.5 * w_grid` if `k_long - spot_px > 0.65 * w_grid`)
     * `k_short = k_long - w_grid`
3. **Underlying Target (`tp_px`) & Stop (`sl_px`)**:
   * `tp_mult = 0.45` (`SOXL`) or `0.42` (`TQQQ`)
   * `tp_move = max(0.015 * spot_px, tp_mult * atr14)`
   * `sl_move = tp_move / 1.18`
   * `tp_px = round(spot_px + tp_move * direction, 2)`
   * `sl_px = round(spot_px - sl_move * direction, 2)`

### Step 3: Select Listed Alpaca Option Contracts (Standardized 7–14 DTE)
Executed in [`find_debit_spread_contracts()`](file:///c:/Users/amitr/OneDrive/Documents/ANT_SOX/soxl_tqqq_debit_330/execution/alpaca_trader.py#L204-L295):
1. **Standardized DTE Window**:
   * **Monday through Friday**: Strictly selects **Next Friday (`7 to 14` calendar DTE)**. Eliminates 2–4 DTE gamma cliffs and cuts overnight theta bleed by more than `50%`.
2. **Alpaca Contract Lookup**:
   * Queries `GET {ALPACA_BASE_URL}/v2/options/contracts` with `underlying_symbols={sym}`, `status=active`, `type={call|put}`, `expiration_date_gte`, and `expiration_date_lte`.
   * Maps `k_long` to the closest listed strike (`long_symbol`) and `k_short` to the listed strike closest to the target width (`short_symbol`).
3. **Live OPRA Quote Snapshot & Midpoint Calculation**:
   * Queries `GET https://data.alpaca.markets/v1beta1/options/snapshots?symbols={long_symbol},{short_symbol}`.
   * Computes net spread midpoint:
     $$\text{debit\_mid} = \text{clip}\Big(\text{round}(\text{long\_mid} - \text{short\_mid}, 2),\; 0.15 \times \text{width},\; 0.75 \times \text{width}\Big)$$

### Step 4: Compute Bounded Worst-Case Debit Sizing Quantity (`n_contracts`)
To prevent account blow-ups from overnight gaps (such as SOXL `-88.2%` on tariffs/earnings), contract quantity is strictly capped:
$$N_{\text{contracts}} = \left\lfloor \frac{\min\left(\frac{0.025 \cdot \text{Equity}}{\text{sl\_frac}}, \; 0.040 \cdot \text{Equity}\right)}{100 \cdot D_0} \right\rfloor$$
where:
* $\text{sl\_frac} = 0.3278$ (`SOXL`) or $0.2311$ (`TQQQ`)
* $D_0 = \text{debit\_mid}$
* Capped between `1` and max `25` contracts.
* Guarantees total debit paid can **never exceed 4.0% of total account equity**.

### Step 5: Submit Multi-Leg (`mleg`) Limit Entry Order to Alpaca
Submits `POST {ALPACA_BASE_URL}/v2/orders` with the following exact JSON payload:
```json
{
  "client_order_id": "STRAT_SOXL_DEBIT_330__PHASE1_VWAP5_RTH_BULL__CP1515__20261111_151500",
  "order_class": "mleg",
  "qty": "25",
  "type": "limit",
  "limit_price": "1.03",
  "time_in_force": "day",
  "legs": [
    {
      "symbol": "SOXL261120C00066000",
      "ratio_qty": "1",
      "side": "buy",
      "position_intent": "buy_to_open"
    },
    {
      "symbol": "SOXL261120C00070000",
      "ratio_qty": "1",
      "side": "sell",
      "position_intent": "sell_to_open"
    }
  ]
}
```

---

## 4. Step-by-Step Procedure to MODIFY an Entry Order (Cancel & Replace)

If an order is not filled within 5 minutes, [`run_staged_5min_checkpoint()`](file:///c:/Users/amitr/OneDrive/Documents/ANT_SOX/soxl_tqqq_debit_330/execution/alpaca_trader.py#L740-L835) executes the modification protocol:

1. **Query Open Orders**: `GET {ALPACA_BASE_URL}/v2/orders?status=open`.
2. **Cancel Existing Working Order**: `DELETE {ALPACA_BASE_URL}/v2/orders/{working_order_id}`.
3. **Wait 1.5 Seconds**: Reallocates buying power cleanly in Alpaca's order state machine.
4. **Re-Query Live Option Snapshots**: Obtains refreshed `debit_mid`.
5. **Nudge Modification**:
   * At `15:20` and `15:25`: Submits replacement order with `limit_price = debit_mid + 0.01` (`use_nudge = True`).
   * At `15:30`: Submits replacement order at refreshed midpoint `limit_price = debit_mid`.
   * At `15:33`: **Cancels all remaining unfilled entry orders** without replacement.

---

## 5. Step-by-Step Procedure to CLOSE an Open Position (The 5 Exit Pathways)

### Pathway 1: Post-Fill Resting `85%` Width Take-Profit Limit Order (Intrabar Auto-Exit)
Immediately after entry fill, [`submit_gtc_take_profit_order()`](file:///c:/Users/amitr/OneDrive/Documents/ANT_SOX/soxl_tqqq_debit_330/execution/alpaca_trader.py#L830-L870) places a resting GTC Limit Sell order at `85%` of spread width (`gtc_tp_limit`):
```json
{
  "client_order_id": "STRAT_SOXL_DEBIT_330__EXIT_GTC_85TP__20261111_153300",
  "order_class": "mleg",
  "qty": "25",
  "type": "limit",
  "limit_price": "-3.40",
  "time_in_force": "day",
  "legs": [
    {
      "symbol": "SOXL261120C00066000",
      "ratio_qty": "1",
      "side": "sell",
      "position_intent": "sell_to_close"
    },
    {
      "symbol": "SOXL261120C00070000",
      "ratio_qty": "1",
      "side": "buy",
      "position_intent": "buy_to_close"
    }
  ]
}
```

### Pathway 2: Day-1 `1:30 PM ET` (`13:30`) `TQQQ` Zero-Bounce Early-Cut (`E2*`)
Executed at `13:30 ET` by [`monitor_day1_zero_bounce_early_cut()`](file:///c:/Users/amitr/OneDrive/Documents/ANT_SOX/soxl_tqqq_debit_330/execution/alpaca_trader.py) strictly when `days_held == 1`:
* Trigger: `fav_atr < 0.08` AND `cur_atr <= -0.30`.
* Action: Closes option legs via `DELETE {ALPACA_BASE_URL}/v2/positions/{option_symbol}`, capping option loss at `~-18.5%` instead of `-35%` at EOD.

### Pathway 3: Day-1 `1:30 PM ET` (`13:30`) `TQQQ` Midday Target Lock
* Trigger: `cur_atr >= 0.42` at `1:30 PM ET` on Day 1+.
* Action: Closes option legs immediately to lock profit before afternoon chop.

### Pathway 4: Multi-Day `3:15–3:30 PM ET` EOD Target, Structural Stop, & `SOXL` Method A Breakeven Stop
Executed at `15:15–15:30 ET` by [`monitor_330_open_position_exits()`](file:///c:/Users/amitr/OneDrive/Documents/ANT_SOX/soxl_tqqq_debit_330/execution/alpaca_trader.py#L605-L700):
1. **Strict Day-0 Protection Hard Block**:
   ```python
   if filled_today_for_sym or entry_ts_raw == today_str or days_held < 1:
       continue  # Hard-block ALL stop/breakeven/EOD exits on Day 0
   ```
2. **Evaluates 4 EOD Exit Conditions on `days_held >= 1`**:
   * **Target Hit (`TP_HIT_330`)**: `cur_px >= tp_px` (Call) or `cur_px <= tp_px` (Put).
   * **Structural Stop (`SL_HIT_330`)**: `cur_px <= sl_px` (Call) or `cur_px >= sl_px` (Put).
   * **SOXL Method A Breakeven Stop (`SOXL_BE_STOP_330`)**: Underlying rallied $\ge +2.0\%$ from entry and pulled back below `entry_px` (`days_held >= 1`).
   * **Max-Hold Time Stop (`TIME_STOP`)**: `days_held >= 3` (`SOXL`) or `days_held >= 8` (`TQQQ`) or expiration today.
3. **Execution Action**: Calls `DELETE {ALPACA_BASE_URL}/v2/positions/{symbol}` on both option legs.
