"""
Alpaca TRF / SIP Microstructure Extractor
=========================================
Loads historical and live 3:00-3:30 PM ET FINRA TRF Dark Pool prints,
Lit Intermarket Sweep Orders (ISO), and Whale Blocks for order-flow gating.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Any, Tuple
import numpy as np
import pandas as pd


def load_ticker_trf_cache(ticker: str, cache_dir: Path | str) -> pd.DataFrame:
    """
    Loads all cached 3:00-3:30 PM ET Alpaca SIP tick summary CSV files for a given ticker.
    """
    c_dir = Path(cache_dir)
    pattern = f"{ticker.upper()}_trf_*.csv"
    rows = []
    for f in sorted(c_dir.glob(pattern)):
        try:
            df_sub = pd.read_csv(f)
            rows.append(df_sub.to_dict("records")[0])
        except Exception:
            pass
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).drop_duplicates(subset=["signal_date"]).set_index("signal_date")


def evaluate_dark_pool_gate(
    ticker: str,
    date_str: str,
    trf_df: pd.DataFrame,
    default_dpr: float = 38.0,
) -> Tuple[bool, bool, Dict[str, float]]:
    """
    Evaluates the Dark-Pool-Conditioned Order-Flow Series Gate:
      - Bullish entries: VETO if Dark Pool Ratio < 35.0% AND Whale Blocks >= 4.0% AND Lit Sweeps < -10.0%
      - Bearish entries: VETO if Dark Pool Ratio < 35.0% AND Whale Blocks >= 4.0% AND Lit Sweeps > +10.0%
      - When off-exchange dark pool participation is healthy (dpr >= 35.0%), dark pools absorb lit dumps.
    """
    if date_str in trf_df.index:
        row = trf_df.loc[date_str]
        dpr = float(row.get("dark_pool_ratio_pct", default_dpr))
        whale_sh = float(row.get("whale_volume_share_pct", 0.0))
        iso_net = float(row.get("iso_net_buy_pct", 0.0))
    else:
        dpr = default_dpr
        whale_sh = 0.0
        iso_net = 0.0

    # Ticker specific thresholds
    if ticker.upper() == "CRWD":
        # CRWD mid-cap tech: strict lit sweep threshold
        bull_ok = not (iso_net < -20.0 and whale_sh >= 5.0)
        bear_ok = not (iso_net > 20.0 and whale_sh >= 5.0)
    else:
        # Mega-caps (CRM, CAT, GE, TSM): dark-pool conditioned
        bull_ok = not ((dpr < 35.0) and (whale_sh >= 4.0) and (iso_net < -10.0))
        bear_ok = not ((dpr < 35.0) and (whale_sh >= 4.0) and (iso_net > 10.0))

    stats = {
        "dark_pool_ratio_pct": dpr,
        "whale_volume_share_pct": whale_sh,
        "iso_net_buy_pct": iso_net,
    }
    return bull_ok, bear_ok, stats
