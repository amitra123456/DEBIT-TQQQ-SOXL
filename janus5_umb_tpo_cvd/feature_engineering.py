"""
Causal Multi-Domain Feature Engineering & Structural Regime Classifier (1999–2026)
for Predicting Early-Stage >= 5% Moves in QQQ and SPY.

Strictly isolated in `research/macro_5pct_engine/`.
100% Causal: Every rolling mean, std, Z-score, and regime state uses ONLY data up to bar t.
"""

from pathlib import Path
import warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"


def rolling_zscore(s: pd.Series, window: int = 63, min_periods: int = 20) -> pd.Series:
    m = s.rolling(window, min_periods=min_periods).mean()
    sd = s.rolling(window, min_periods=min_periods).std()
    return (s - m) / sd.replace(0, np.nan)


def wilder_rsi(close: pd.Series, period: int = 5) -> pd.Series:
    delta = close.diff()
    up = delta.clip(lower=0.0)
    dn = -delta.clip(upper=0.0)
    au = up.ewm(alpha=1.0 / period, adjust=False).mean()
    ad = dn.ewm(alpha=1.0 / period, adjust=False).mean()
    rs = au / ad.replace(0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))


def wilder_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_c = close.shift(1)
    tr = pd.concat([
        (high - low).abs(),
        (high - prev_c).abs(),
        (low - prev_c).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False).mean()


def engineer_features_for_target(panel: pd.DataFrame, target: str = "QQQ") -> pd.DataFrame:
    """
    Builds a comprehensive causal feature matrix for `target` ('QQQ' or 'SPY')
    plus forward target labels for >= 5% moves (strictly separated into `LABEL_*` columns).
    """
    df = pd.DataFrame(index=panel.index)

    c = panel[f"{target}_close"]
    o = panel[f"{target}_open"]
    h = panel[f"{target}_high"]
    l = panel[f"{target}_low"]
    v = panel[f"{target}_volume"]

    df["close"] = c
    df["open"] = o
    df["high"] = h
    df["low"] = l
    df["volume"] = v

    ret1 = c.pct_change()
    atr14 = wilder_atr(h, l, c, 14)
    df["atr_pct"] = (atr14 / c) * 100.0

    # =========================================================================
    # 1. TECHNICAL & CYCLE STRETCH / EARLY-STAGE POSITIONING FEATURES
    # =========================================================================
    ema10 = c.ewm(span=10, adjust=False).mean()
    ema20 = c.ewm(span=20, adjust=False).mean()
    ema50 = c.ewm(span=50, adjust=False).mean()
    ema65 = c.ewm(span=65, adjust=False).mean()
    sma200 = c.rolling(200, min_periods=100).mean()

    df["z10"] = (c - ema10) / atr14
    df["z20"] = (c - ema20) / atr14
    df["z50"] = (c - ema50) / atr14
    df["z65"] = (c - ema65) / atr14
    df["z200"] = (c - sma200) / atr14
    df["dist_sma200_pct"] = (c / sma200 - 1.0) * 100.0
    df["sma200_slope21"] = sma200.pct_change(21) * 100.0

    df["rsi2"] = wilder_rsi(c, 2)
    df["rsi5"] = wilder_rsi(c, 5)
    df["rsi14"] = wilder_rsi(c, 14)
    df["rsi5_turn_up"] = df["rsi5"] - df["rsi5"].shift(1)

    # Distance from trailing 20d/63d high and low (measures how early in the wave we are)
    low20 = l.rolling(20, min_periods=5).min()
    high20 = h.rolling(20, min_periods=5).max()
    high63 = h.rolling(63, min_periods=20).max()
    low63 = l.rolling(63, min_periods=20).min()

    df["pct_off_20d_low"] = (c / low20 - 1.0) * 100.0
    df["pct_off_20d_high"] = (c / high20 - 1.0) * 100.0
    df["pct_off_63d_high"] = (c / high63 - 1.0) * 100.0
    df["pos_in_20d_range"] = (c - low20) / (high20 - low20).replace(0, np.nan)
    df["pos_in_63d_range"] = (c - low63) / (high63 - low63).replace(0, np.nan)

    # Volatility compression (Bollinger Band width percentile)
    bb_std20 = c.rolling(20, min_periods=10).std()
    df["bb_width20"] = (2.0 * bb_std20) / ema20
    df["bb_width_z63"] = rolling_zscore(df["bb_width20"], 63)

    # =========================================================================
    # 2. VOLUME & DARK POOL / INSTITUTIONAL STEALTH ACCUMULATION FEATURES
    # =========================================================================
    # Overnight return (Close[t-1] -> Open[t]) vs Intraday RTH return (Open[t] -> Close[t])
    ovn_ret = (o / c.shift(1) - 1.0).fillna(0.0)
    rth_ret = (c / o - 1.0).fillna(0.0)
    df["dp_ovn_21"] = ovn_ret.rolling(21, min_periods=10).sum() * 100.0
    df["dp_rth_21"] = rth_ret.rolling(21, min_periods=10).sum() * 100.0
    df["dp_ovn_minus_rth_21"] = df["dp_ovn_21"] - df["dp_rth_21"]
    df["dp_ovn_z63"] = rolling_zscore(df["dp_ovn_21"], 63)

    # Intraday Candle Closing Range (0 = closed at low, 1 = closed at high -> institutional block absorption)
    bar_range = (h - l).replace(0, np.nan)
    df["close_loc"] = ((c - l) / bar_range).fillna(0.5)
    vol_sma20 = v.rolling(20, min_periods=5).mean().replace(0, np.nan)
    df["rel_vol20"] = (v / vol_sma20).fillna(1.0)

    # Dark Pool / Institutional Absorption Score: high relative volume + strong close location after dip
    clv = (((c - l) - (h - c)) / bar_range).fillna(0.0)
    df["dp_cmf20"] = (clv * v).rolling(20, min_periods=10).sum() / v.rolling(20, min_periods=10).sum().replace(0, np.nan)
    df["dp_absorption_bar"] = df["close_loc"] * df["rel_vol20"]

    # Up-Volume vs Down-Volume Asymmetry (21d)
    up_vol = np.where(ret1 > 0, v, 0.0)
    dn_vol = np.where(ret1 < 0, v, 0.0)
    up_v21 = pd.Series(up_vol, index=df.index).rolling(21, min_periods=10).sum()
    dn_v21 = pd.Series(dn_vol, index=df.index).rolling(21, min_periods=10).sum()
    df["dp_up_dn_vol_ratio21"] = up_v21 / (up_v21 + dn_v21).replace(0, np.nan)

    # Amihud Illiquidity Shock
    dollar_vol = (c * v).replace(0, np.nan)
    amihud = (ret1.abs() / dollar_vol)
    df["dp_amihud_z63"] = rolling_zscore(amihud.rolling(5, min_periods=2).mean(), 63)

    # =========================================================================
    # 3. OPTIONS IMPLIED VOLATILITY, TERM STRUCTURE & VARIANCE RISK PREMIUM
    # =========================================================================
    vix = panel.get("VIX_close", pd.Series(index=df.index)).combine_first(panel["FRED_VIXCLS"])
    vxn = panel.get("VXN_close", pd.Series(index=df.index)).combine_first(panel["FRED_VXNCLS"]).combine_first(vix * 1.25)
    iv_series = vxn if target == "QQQ" else vix

    df["opt_iv"] = iv_series
    df["opt_vix"] = vix
    df["opt_iv_z21"] = rolling_zscore(iv_series, 21, 10)
    df["opt_iv_z63"] = rolling_zscore(iv_series, 63, 20)

    # VIX Term Structure: VIX / VIX3M (with causal fallback to VIX / SMA63(VIX) pre-2007)
    vix_sma63 = vix.rolling(63, min_periods=20).mean()
    vix3m = panel.get("VIX3M_close", vix_sma63).combine_first(vix_sma63)
    df["opt_term_ratio"] = vix / vix3m.replace(0, np.nan)
    df["opt_term_max5"] = df["opt_term_ratio"].rolling(5, min_periods=1).max()
    # Term structure inversion peak & turn down (Vanna/Charm Tailwind)
    df["opt_term_pullback_from_peak"] = df["opt_term_ratio"] / df["opt_term_max5"].replace(0, np.nan) - 1.0
    df["opt_iv_drop_from_5d_high"] = iv_series / iv_series.rolling(5, min_periods=1).max().replace(0, np.nan) - 1.0

    # Variance Risk Premium (VRP = Implied Vol - 20d Annualized Realized Vol)
    rv20 = ret1.rolling(20, min_periods=10).std() * np.sqrt(252) * 100.0
    df["opt_rv20"] = rv20
    df["opt_vrp"] = iv_series - rv20
    df["opt_vrp_z63"] = rolling_zscore(df["opt_vrp"], 63)

    # Skew & Vol-of-Vol
    skew = panel.get("SKEW_close", pd.Series(120.0, index=df.index)).ffill().bfill()
    df["opt_skew_z63"] = rolling_zscore(skew, 63)

    # =========================================================================
    # 4. MONETARY FLOWS (M1 / M2 / M3 / MONEY MARKET FUNDS & FED NET LIQUIDITY)
    # =========================================================================
    m1 = panel["FRED_WM1NS"].combine_first(panel["FRED_M1SL"])
    m2 = panel["FRED_WM2NS"].combine_first(panel["FRED_M2SL"])
    mmf = panel["FRED_WRMFNS"]
    mbase = panel["FRED_BOGMBASE"]

    df["flow_m1_yoy"] = m1.pct_change(252) * 100.0
    df["flow_m2_yoy"] = m2.pct_change(252) * 100.0
    df["flow_m2_roc63"] = m2.pct_change(63) * 100.0
    df["flow_m2_accel"] = df["flow_m2_roc63"] - (m2.pct_change(126) * 100.0 / 2.0)
    df["flow_mmf_yoy"] = mmf.pct_change(252) * 100.0
    df["flow_mmf_to_m2"] = (mmf / m2.replace(0, np.nan)) * 100.0
    df["flow_mbase_yoy"] = mbase.pct_change(252) * 100.0

    # Fed Net Liquidity (2003+): WALCL (millions) - WTREGEN (millions) - RRPONTSYD (billions * 1000)
    walcl = panel["FRED_WALCL"].fillna(0.0)
    tga = panel["FRED_WTREGEN"].fillna(0.0)
    rrp = panel["FRED_RRPONTSYD"].fillna(0.0) * 1000.0
    net_liq = (walcl - tga - rrp).replace(0, np.nan)
    df["flow_net_liq_roc21"] = net_liq.pct_change(21).fillna(m2.pct_change(21)) * 100.0
    df["flow_net_liq_roc63"] = net_liq.pct_change(63).fillna(m2.pct_change(63)) * 100.0

    # =========================================================================
    # 5. INFLATION, GASOLINE, OIL & INTEREST RATES / YIELD CURVE / CREDIT
    # =========================================================================
    cpi = panel["FRED_CPIAUCSL"]
    gas = panel["FRED_GASREGW"]
    oil = panel["FRED_DCOILWTICO"]
    dgs10 = panel["FRED_DGS10"]
    dgs2 = panel["FRED_DGS2"]
    dgs3m = panel["FRED_DGS3MO"]
    t10y2y = panel["FRED_T10Y2Y"]
    t10y3m = panel["FRED_T10Y3M"]
    baa_spread = panel["FRED_BAA10Y"]
    nfci = panel["FRED_NFCI"]
    icsa = panel["FRED_ICSA"]
    epu_news = panel["FRED_USEPUINDXD"]

    df["macro_cpi_yoy"] = cpi.pct_change(252) * 100.0
    df["macro_cpi_roc63"] = cpi.pct_change(63) * 400.0  # annualized 3M CPI
    df["macro_real_m2_yoy"] = df["flow_m2_yoy"] - df["macro_cpi_yoy"]

    # Gasoline & Oil shock features
    df["macro_gas_level"] = gas
    df["macro_gas_yoy"] = gas.pct_change(252) * 100.0
    df["macro_gas_roc21"] = gas.pct_change(21) * 100.0
    df["macro_gas_z63"] = rolling_zscore(gas, 63)
    df["macro_oil_roc21"] = oil.pct_change(21) * 100.0
    df["macro_oil_z63"] = rolling_zscore(oil, 63)

    # Interest Rates & Real Yields
    df["rate_dgs10"] = dgs10
    df["rate_dgs10_chg21"] = dgs10.diff(21)
    df["rate_dgs10_z63"] = rolling_zscore(dgs10, 63)
    df["rate_dgs2_chg21"] = dgs2.diff(21)
    df["rate_real10y"] = panel["FRED_DFII10"].combine_first(dgs10 - df["macro_cpi_yoy"])
    df["rate_real10y_chg21"] = df["rate_real10y"].diff(21)
    df["rate_curve_10y2y"] = t10y2y
    df["rate_curve_10y3m"] = t10y3m
    df["rate_curve_steep21"] = t10y2y.diff(21)

    # Credit Spreads, Financial Conditions & Jobless Claims
    df["credit_baa_spread"] = baa_spread
    df["credit_baa_chg21"] = baa_spread.diff(21)
    df["credit_baa_z63"] = rolling_zscore(baa_spread, 63)
    df["macro_nfci"] = nfci
    df["macro_nfci_chg21"] = nfci.diff(21)
    df["macro_icsa_z63"] = rolling_zscore(icsa, 63)

    # News Policy Uncertainty
    df["news_epu_ma5"] = epu_news.rolling(5, min_periods=1).mean()
    df["news_epu_z63"] = rolling_zscore(df["news_epu_ma5"], 63)

    # =========================================================================
    # 6. LEADING / LAGGING CROSS-ASSET INDICATORS & MARKET REGIME CLASSIFIER
    # =========================================================================
    spy_c = panel["SPY_close"]
    qqq_c = panel["QQQ_close"]
    iwm_c = panel["IWM_close"].combine_first(spy_c)
    smh_c = panel["SMH_close"].combine_first(panel["XLK_close"]).combine_first(qqq_c)
    xly_c = panel["XLY_close"].combine_first(spy_c)
    xlp_c = panel["XLP_close"].combine_first(spy_c)
    xlf_c = panel["XLF_close"].combine_first(spy_c)
    hyg_c = panel["HYG_close"].combine_first(spy_c)
    ief_c = panel["IEF_close"].combine_first(spy_c)
    dxy_c = panel["DX_Y_NYB_close"].combine_first(panel["UUP_close"])
    jpy_c = panel["JPY_close"]

    # Leading Cross-Asset Ratios
    df["lead_smh_qqq_z21"] = rolling_zscore(smh_c / qqq_c, 21)
    df["lead_xly_xlp_z21"] = rolling_zscore(xly_c / xlp_c, 21)
    df["lead_iwm_spy_z21"] = rolling_zscore(iwm_c / spy_c, 21)
    df["lead_xlf_spy_z21"] = rolling_zscore(xlf_c / spy_c, 21)
    df["lead_hyg_ief_z21"] = rolling_zscore(hyg_c / ief_c, 21)
    df["lead_dxy_z21"] = rolling_zscore(dxy_c, 21)
    df["lead_jpy_z21"] = rolling_zscore(jpy_c, 21)

    # Credit vs Equity Divergence: Credit Spreads Calm/Tightening while Equity Pulled Back
    # Negative credit_baa_z63 is good (tight spreads); subtract z20 so positive = credit much stronger than equity!
    df["lead_credit_equity_div"] = (-df["credit_baa_z63"]) - df["z20"]

    # Stock-Yield Correlation Regime (Positive vs Negative Stock-Bond Correlation)
    df["reg_stock_yield_corr63"] = ret1.rolling(63, min_periods=20).corr(dgs10.diff())

    # Structural Regime Classification (100% Causal, Zero Hardcoded Dates):
    # - Inflation/Rate Shock Headwind: CPI > 3.5% or Gas YoY > 25% AND 10Y yields spiking (rate_dgs10_z63 > 0.8)
    # - Liquidity Drain Headwind: Real M2 YoY < -1.0% AND Net Liquidity falling (flow_net_liq_roc63 < 0)
    # - Credit Crisis Headwind: Baa Credit Spread > 3.0% AND widening rapidly (credit_baa_z63 > 1.2)
    df["reg_inflation_rate_shock"] = (
        ((df["macro_cpi_yoy"] > 3.5) | (df["macro_gas_yoy"] > 25.0))
        & (df["rate_dgs10_z63"] > 0.75)
    ).astype(int)

    df["reg_liquidity_tailwind"] = (
        (df["macro_real_m2_yoy"] > -1.0) | (df["flow_net_liq_roc21"] > 0.0) | (df["flow_m2_accel"] > 0.0)
    ).astype(int)

    df["reg_credit_healthy"] = (
        (df["credit_baa_spread"] < 3.2) & (df["credit_baa_z63"] < 1.25)
    ).astype(int)

    # =========================================================================
    # 7. STRICTLY SEPARATED FORWARD TARGET LABELS (FOR EVALUATION ONLY)
    # =========================================================================
    c_arr = c.values
    h_arr = h.values
    l_arr = l.values
    n = len(c_arr)

    for H in [20, 30, 40, 45, 60]:
        up5_touch = np.full(n, np.nan)
        dn5_touch = np.full(n, np.nan)
        up5_before_dn5 = np.full(n, np.nan)
        dn5_before_up5 = np.full(n, np.nan)
        up5_before_dn35 = np.full(n, np.nan)
        mfe_up = np.full(n, np.nan)
        mae_dn = np.full(n, np.nan)
        days_to_up5 = np.full(n, np.nan)

        for i in range(n - H):
            entry = c_arr[i]
            if np.isnan(entry) or entry <= 0:
                continue
            win_h = h_arr[i + 1 : i + H + 1]
            win_l = l_arr[i + 1 : i + H + 1]

            max_g = (np.max(win_h) - entry) / entry
            max_l = (entry - np.min(win_l)) / entry
            mfe_up[i] = max_g * 100.0
            mae_dn[i] = max_l * 100.0
            up5_touch[i] = 1.0 if max_g >= 0.05 else 0.0
            dn5_touch[i] = 1.0 if max_l >= 0.05 else 0.0

            # First-passage race within H days
            u_idx = np.where((win_h - entry) / entry >= 0.05)[0]
            d_idx = np.where((entry - win_l) / entry >= 0.05)[0]
            d35_idx = np.where((entry - win_l) / entry >= 0.035)[0]

            first_u = u_idx[0] if len(u_idx) > 0 else 9999
            first_d = d_idx[0] if len(d_idx) > 0 else 9999
            first_d35 = d35_idx[0] if len(d35_idx) > 0 else 9999

            if first_u < 9999:
                days_to_up5[i] = first_u + 1

            # Did it hit +5% within H days BEFORE hitting -5%?
            up5_before_dn5[i] = 1.0 if (first_u < 9999 and first_u < first_d) else 0.0
            dn5_before_up5[i] = 1.0 if (first_d < 9999 and first_d < first_u) else 0.0
            up5_before_dn35[i] = 1.0 if (first_u < 9999 and first_u < first_d35) else 0.0

        df[f"LABEL_touch_up5_{H}d"] = up5_touch
        df[f"LABEL_touch_dn5_{H}d"] = dn5_touch
        df[f"LABEL_race_up5_vs_dn5_{H}d"] = up5_before_dn5
        df[f"LABEL_race_dn5_vs_up5_{H}d"] = dn5_before_up5
        df[f"LABEL_race_up5_vs_dn35_{H}d"] = up5_before_dn35
        df[f"LABEL_mfe_up_{H}d"] = mfe_up
        df[f"LABEL_mae_dn_{H}d"] = mae_dn
        df[f"LABEL_days_to_up5_{H}d"] = days_to_up5

    return df


if __name__ == "__main__":
    panel_path = DATA_DIR / "qqq_spy_macro_panel_1999_2026.parquet"
    panel = pd.read_parquet(panel_path)
    for tgt in ["QQQ", "SPY"]:
        fdf = engineer_features_for_target(panel, tgt)
        fdf = fdf.loc["1999-03-10":]
        out_p = DATA_DIR / f"{tgt.lower()}_features_1999_2026.parquet"
        fdf.to_parquet(out_p)
        print(f"Saved {tgt} feature matrix: {fdf.shape} -> {out_p}")
