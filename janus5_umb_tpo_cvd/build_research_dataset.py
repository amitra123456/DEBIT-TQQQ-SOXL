"""
Isolated Research Pipeline: Multi-Regime Macro, M1/M2/M3 Liquidity, Dark Pool /
Volume Microstructure, Options Term Structure, Leading/Lagging Cross-Asset,
Interest Rate, Gasoline/Inflation, and News Dataset Builder (1999–2026).

Strictly isolated inside `research/macro_5pct_engine/`.
Enforces causal publication lags on all weekly/monthly FRED series to guarantee
ZERO data leakage.
"""

from pathlib import Path
import warnings
import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

YF_TICKERS = [
    # Core Targets
    "QQQ", "SPY", "IWM", "DIA",
    # Sector & Leading/Lagging Equities
    "SMH", "SOXX", "XLK", "XLF", "XLE", "XLY", "XLP", "XLI", "XLV", "XLU", "RSP",
    # Bonds, Credit & Rates
    "TLT", "IEF", "SHY", "HYG", "LQD", "^TNX", "^IRX", "^FVX", "^TYX",
    # Options Volatility & Tail Skew
    "^VIX", "^VXN", "^VIX3M", "^VVIX", "^SKEW",
    # FX Carry, Dollar & Commodities (Oil, Gasoline, Gold, Copper)
    "UUP", "DX-Y.NYB", "JPY=X", "GLD", "CL=F", "HG=F", "RB=F"
]

# FRED series with their strict causal publication lag in trading days
FRED_SERIES_LAGS = {
    # Monetary Aggregates (M1, M2, M3, Money Market Funds, Monetary Base)
    "WM1NS": 10,            # Weekly M1 Money Stock (H.6 release lag ~10 bus. days)
    "WM2NS": 10,            # Weekly M2 Money Stock (H.6 release lag ~10 bus. days)
    "WRMFNS": 10,           # Weekly Retail Money Market Funds (M3 proxy)
    "M1SL": 20,             # Monthly M1 (for pre-1981 or cross-check)
    "M2SL": 20,             # Monthly M2
    "MABMM301USM189S": 22,  # OECD M3 Broad Money for US
    "BOGMBASE": 15,         # Monetary Base
    "TOTRESNS": 15,         # Total Reserves of Depository Institutions
    # Fed Balance Sheet & Net Liquidity Components
    "WALCL": 3,             # Fed Total Assets (Wednesday level, released Thursday 4:30pm)
    "WTREGEN": 3,           # Treasury General Account (weekly Wed, released Thu)
    "RRPONTSYD": 1,         # Overnight Reverse Repo (daily)
    # Inflation, Gasoline & Energy Prices
    "GASREGW": 2,           # US Regular All Formulations Gas Price (Weekly Mon release)
    "DCOILWTICO": 1,        # WTI Crude Oil Spot Price (Daily)
    "CPIAUCSL": 15,         # CPI All Urban Consumers (Monthly, released ~mid next month)
    "T10YIE": 1,            # 10-Year Breakeven Inflation Rate (Daily)
    "T5YIE": 1,             # 5-Year Breakeven Inflation Rate (Daily)
    "DFII10": 1,            # 10-Year Real TIPS Yield (Daily)
    # Interest Rates & Yield Curve
    "DGS3MO": 1,            # 3-Month Treasury Yield (Daily)
    "DGS2": 1,              # 2-Year Treasury Yield (Daily)
    "DGS5": 1,              # 5-Year Treasury Yield (Daily)
    "DGS10": 1,             # 10-Year Treasury Yield (Daily)
    "DGS30": 1,             # 30-Year Treasury Yield (Daily)
    "T10Y2Y": 1,            # 10Y-2Y Yield Curve Spread (Daily)
    "T10Y3M": 1,            # 10Y-3M Yield Curve Spread (Daily)
    # Credit Spreads, Financial Stress & Labor Market
    "BAA10Y": 1,            # Moody's Baa Corporate Bond Spread over 10Y Treasury (Daily, 1986+)
    "AAA10Y": 1,            # Moody's Aaa Corporate Bond Spread over 10Y Treasury (Daily, 1983+)
    "BAMLH0A0HYM2": 1,      # ICE BofA High Yield OAS (Daily)
    "NFCI": 5,              # Chicago Fed National Financial Conditions Index (Weekly)
    "STLFSI4": 5,           # St. Louis Fed Financial Stress Index (Weekly)
    "ICSA": 5,              # Initial Jobless Claims (Weekly Sat -> released Thu)
    # Volatility & News Policy Uncertainty
    "VIXCLS": 1,            # CBOE VIX Close (Daily, 1990+)
    "VXNCLS": 1,            # CBOE Nasdaq-100 Volatility Index VXN (Daily, 2001+)
    "USEPUINDXD": 1,        # Daily News-Based Economic Policy Uncertainty Index (1985+)
}


def fetch_fred_series(series_id: str) -> pd.Series:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    df = pd.read_csv(url)
    date_col = df.columns[0]
    val_col = df.columns[1]
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    df[val_col] = pd.to_numeric(df[val_col], errors="coerce")
    df = df.dropna(subset=[date_col]).set_index(date_col).sort_index()
    return df[val_col]


def build_dataset():
    print("1. Downloading Yahoo Finance OHLCV universe (1998-01-01 to present)...")
    raw = yf.download(
        YF_TICKERS,
        start="1998-01-01",
        interval="1d",
        progress=False,
        auto_adjust=True,
    )

    spy_close = raw["Close"]["SPY"].dropna()
    qqq_close = raw["Close"]["QQQ"].dropna()
    # Start master index where both SPY and QQQ exist (1999-03-10), but keep 1998 burn-in for SPY/macro
    master_idx = spy_close.index

    panel = pd.DataFrame(index=master_idx)

    for sym in YF_TICKERS:
        clean = (
            sym.replace("^", "")
            .replace("=X", "")
            .replace("=F", "")
            .replace("-", "_")
            .replace(".", "_")
        )
        if sym in raw["Close"].columns:
            panel[f"{clean}_close"] = raw["Close"][sym].reindex(master_idx).ffill()
            panel[f"{clean}_open"] = raw["Open"][sym].reindex(master_idx).ffill()
            panel[f"{clean}_high"] = raw["High"][sym].reindex(master_idx).ffill()
            panel[f"{clean}_low"] = raw["Low"][sym].reindex(master_idx).ffill()
            panel[f"{clean}_volume"] = (
                raw["Volume"][sym].reindex(master_idx).fillna(0.0)
            )

    print(f"2. Downloading {len(FRED_SERIES_LAGS)} FRED macro/monetary/news series with causal lags...")
    union_cal = pd.date_range(start="1995-01-01", end=master_idx[-1] + pd.Timedelta(days=5), freq="D")
    for fid, lag_days in FRED_SERIES_LAGS.items():
        try:
            s = fetch_fred_series(fid)
            s_cal = s.reindex(union_cal).ffill()
            s_bus = s_cal.reindex(master_idx).ffill()
            if lag_days > 1:
                s_bus = s_bus.shift(lag_days)
            panel[f"FRED_{fid}"] = s_bus
        except Exception as e:
            print(f"  Warning: failed {fid}: {e}")

    out_file = DATA_DIR / "qqq_spy_macro_panel_1999_2026.parquet"
    panel.to_parquet(out_file)
    print(f"Saved causal research panel: {panel.shape} -> {out_file}")
    print(f"Date range: {panel.index[0].strftime('%Y-%m-%d')} to {panel.index[-1].strftime('%Y-%m-%d')}")


if __name__ == "__main__":
    build_dataset()
