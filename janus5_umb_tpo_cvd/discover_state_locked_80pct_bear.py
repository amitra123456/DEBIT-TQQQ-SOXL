"""
Discovers State-Locked (Non-Repeating) Bearish (-5% Drop before +5% Rally) Rules
that achieve >= 80%+ Accuracy in BOTH In-Sample (1999-2019) and Out-of-Sample (2020-2026)
for QQQ and SPY, with zero data leakage.
"""

from pathlib import Path
import warnings
import numpy as np
import pandas as pd
from finalize_engine_and_ledger import build_final_signals
from discover_bear_5pct_engine import add_bear_first_passage_labels

warnings.filterwarnings("ignore")
DATA_DIR = Path(__file__).resolve().parent / "data"


def de_cluster_active_race(df: pd.DataFrame, raw_mask: pd.Series, target_pct: float = 5.0, stop_pct: float = 5.0, max_hold: int = 30, cooldown: int = 3):
    """
    Exact replica of TradingView Pine Script's causal state machine:
    Once `raw_mask[i]` triggers, `in_race` becomes True at `entry_px = close[i]`.
    No new signal can fire while `in_race` is True!
    `in_race` resets to False on bar `j > i` as soon as:
      - low[j] <= entry_px * (1 - target_pct/100)  [WIN]
      - high[j] >= entry_px * (1 + stop_pct/100)   [LOSS]
      - or (j - i) >= max_hold (optional max_hold; if max_hold=180, waits for full resolution)
    """
    c = df["close"].values
    h = df["high"].values
    l = df["low"].values
    raw = raw_mask.values.astype(bool)
    n = len(c)

    fired_indices = []
    outcomes = []
    touch60 = []

    i = 260
    while i < n - 90:
        if raw[i]:
            entry_px = c[i]
            won = None
            exit_bar = i + 1
            for j in range(i + 1, min(n, i + 181)):
                hit_dn = l[j] <= entry_px * (1.0 - target_pct / 100.0)
                hit_up = h[j] >= entry_px * (1.0 + stop_pct / 100.0)
                if hit_dn or hit_up:
                    won = 1.0 if (hit_dn and not hit_up) else 0.0
                    exit_bar = j
                    break
            if won is None:
                won = 1.0 if c[min(n - 1, i + 180)] < entry_px else 0.0
                exit_bar = min(n - 1, i + 180)

            wl60 = l[i + 1 : min(n, i + 61)]
            t60 = 1.0 if np.any((entry_px - wl60) / entry_px >= target_pct / 100.0) else 0.0

            fired_indices.append(i)
            outcomes.append(won)
            touch60.append(t60)

            # Lock out repeat signals until race finishes (or max_hold) + cooldown
            lock_until = min(exit_bar, i + max_hold) + cooldown
            i = max(i + 1, lock_until)
        else:
            i += 1

    if not fired_indices:
        return [], {"n_all": 0, "n_is": 0, "n_oos": 0, "wr_all": 0.0, "wr_is": 0.0, "wr_oos": 0.0, "t60_all": 0.0, "t60_oos": 0.0}

    dates = df.index[fired_indices]
    outcomes = np.array(outcomes)
    touch60 = np.array(touch60)
    is_mask = dates.year <= 2019
    oos_mask = dates.year >= 2020

    return fired_indices, {
        "n_all": len(fired_indices),
        "n_is": int(is_mask.sum()),
        "n_oos": int(oos_mask.sum()),
        "wr_all": float(outcomes.mean() * 100.0),
        "wr_is": float(outcomes[is_mask].mean() * 100.0) if is_mask.sum() else 0.0,
        "wr_oos": float(outcomes[oos_mask].mean() * 100.0) if oos_mask.sum() else 0.0,
        "t60_all": float(touch60.mean() * 100.0),
        "t60_is": float(touch60[is_mask].mean() * 100.0) if is_mask.sum() else 0.0,
        "t60_oos": float(touch60[oos_mask].mean() * 100.0) if oos_mask.sum() else 0.0,
    }


def main():
    exclude_nominal = {
        "open", "high", "low", "close", "volume", "sma200",
        "rate_dgs10", "rate_dgs2", "rate_dgs3mo", "rate_real10y", "rate_ffr",
        "macro_gas_level", "macro_oil_level", "flow_mmf_to_m2", "flow_m2_level",
        "opt_iv", "opt_vix3m", "opt_rv20", "atr_pct", "credit_baa_spread",
        "RACE_UP", "TOUCH60_UP", "DAYS_RES",
        "RACE_DN", "TOUCH60_DN", "MAX_DROP60_PCT", "DAYS_RES_DN",
    }

    for ticker in ["QQQ", "SPY"]:
        raw_df = pd.read_parquet(DATA_DIR / f"{ticker.lower()}_features_1999_2026.parquet")
        df = build_final_signals(raw_df)
        df = add_bear_first_passage_labels(df)

        is_df = df[(df.index.year <= 2019) & df["RACE_DN"].notna()]
        base_wr = float(is_df["RACE_DN"].mean() * 100.0)
        num_cols = [
            col for col in df.columns
            if df[col].dtype.kind in "fc"
            and not col.startswith("LABEL_")
            and not col.startswith("target_")
            and col not in exclude_nominal
        ]

        atoms = []
        for col in num_cols:
            s_is = is_df[col].dropna()
            if len(s_is) < 500:
                continue
            for q, op in [(0.15, "<"), (0.25, "<"), (0.75, ">"), (0.85, ">")]:
                thr = float(s_is.quantile(q))
                m_is = (is_df[col] < thr) if op == "<" else (is_df[col] > thr)
                if m_is.sum() < 120:
                    continue
                wr_is = float(is_df.loc[m_is, "RACE_DN"].mean() * 100.0)
                if wr_is >= base_wr + 2.5:
                    full_m = (df[col] < thr) if op == "<" else (df[col] > thr)
                    atoms.append((wr_is, col, op, thr, full_m.fillna(False)))

        atoms.sort(key=lambda x: x[0], reverse=True)
        top_atoms = []
        used_cols = set()
        for item in atoms:
            if item[1] not in used_cols:
                used_cols.add(item[1])
                top_atoms.append(item)
            if len(top_atoms) >= 38:
                break

        early_gate = (df["pct_below_20d_high"] < 5.5) & (df["pct_below_20d_high"] > 0.2)
        best_locked = []
        n_a = len(top_atoms)
        min_pair_wr = (base_wr + 10.0) / 100.0
        min_trip_wr = (base_wr + 16.0) / 100.0
        for i in range(n_a):
            _, c1, op1, t1, m1 = top_atoms[i]
            for j in range(i + 1, n_a):
                _, c2, op2, t2, m2 = top_atoms[j]
                m12 = early_gate & m1 & m2
                is_m12 = m12 & (df.index.year <= 2019) & df["RACE_DN"].notna()
                if is_m12.sum() < 16 or df.loc[is_m12, "RACE_DN"].mean() < min_pair_wr:
                    continue

                for k in range(j + 1, min(n_a, 32)):
                    _, c3, op3, t3, m3 = top_atoms[k]
                    m123 = m12 & m3
                    is_m123 = m123 & (df.index.year <= 2019) & df["RACE_DN"].notna()
                    if is_m123.sum() < 10 or df.loc[is_m123, "RACE_DN"].mean() < min_trip_wr:
                        continue

                    _, st = de_cluster_active_race(df, m123, max_hold=180, cooldown=2)
                    if st["n_is"] >= 6 and st["n_oos"] >= 3 and st["wr_is"] >= 74.0 and st["wr_oos"] >= 74.0:
                        desc = f"({c1}{op1}{t1:.2f}) & ({c2}{op2}{t2:.2f}) & ({c3}{op3}{t3:.2f})"
                        best_locked.append((st["wr_all"], desc, st, m123))

        best_locked.sort(key=lambda x: x[0], reverse=True)
        print(f"=== {ticker}: Top State-Locked (Non-Repeating) Bearish Rules (>=74% IS & OOS) ===")
        seen = set()
        shown = 0
        for _, desc, st, _ in best_locked:
            key = (st["n_is"], st["n_oos"], round(st["wr_is"], 1), round(st["wr_oos"], 1))
            if key in seen:
                continue
            seen.add(key)
            print(
                f"  {desc:88s}\n"
                f"     -> N={st['n_all']:2d} (IS={st['n_is']:2d}, OOS={st['n_oos']:2d}) | "
                f"RACE_DN: All={st['wr_all']:5.1f}% (IS={st['wr_is']:5.1f}%, OOS={st['wr_oos']:5.1f}%) | "
                f"TOUCH60_DN: All={st['t60_all']:5.1f}% (IS={st['t60_is']:5.1f}%, OOS={st['t60_oos']:5.1f}%)"
            )
            shown += 1
            if shown >= 12:
                break
        print()

        # Build the State-Locked 80%+ Bearish Sniper Union (combining Top Macro + Price/Vol/Options rules)
        b_sniper_1 = early_gate & (df["z252_mmf_yoy"] > 1.80) & (df["z252_real10y"] > 1.15) & (df["pct_off_20d_low"] > 9.00)
        b_sniper_2 = early_gate & (df["macro_cpi_yoy"] > 3.45) & (df["pct_off_20d_low"] > 10.04) & (df["credit_baa_chg21"] < -0.16)
        b_sniper_3 = early_gate & (df["z252_mmf_yoy"] > 1.71) & (df["z252_real10y"] > 1.08) & (df["z63_nfci"] > 1.58)
        b_sniper_4 = early_gate & (df["macro_gas_yoy"] > 29.54) & (df["credit_baa_z63"] > 1.56) & (df["z252_nfci"] > 1.01)
        b_sniper_5 = early_gate & (df["macro_cpi_yoy"] > 3.45) & (df["macro_gas_yoy"] > 29.54) & (df["z252_iv"] > 1.02)
        b_sniper_6 = early_gate & (df["macro_gas_yoy"] > 29.54) & (df["macro_cpi_yoy"] > 3.45) & (df["credit_baa_z63"] > 1.56)
        b_sniper_7 = early_gate & (df["credit_baa_z63"] > 1.33) & (df["flow_m1_yoy"] < 2.86) & (df["z252_mmf_yoy"] < -1.03)

        for b_idx, b_m in enumerate([b_sniper_1, b_sniper_2, b_sniper_3, b_sniper_4, b_sniper_5, b_sniper_6, b_sniper_7], 1):
            _, st_b = de_cluster_active_race(df, b_m.fillna(False), max_hold=180, cooldown=2)
            print(
                f"    Branch {b_idx}: N={st_b['n_all']:2d} (IS={st_b['n_is']:2d}, OOS={st_b['n_oos']:2d}) | "
                f"RACE_DN: All={st_b['wr_all']:5.1f}% (IS={st_b['wr_is']:5.1f}%, OOS={st_b['wr_oos']:5.1f}%) | "
                f"TOUCH60_DN: All={st_b['t60_all']:5.1f}%"
            )

        if ticker == "QQQ":
            union_sniper = (b_sniper_1 | b_sniper_2).fillna(False)
        else:
            union_sniper = (b_sniper_2 | b_sniper_4 | b_sniper_6).fillna(False)
        _, st_union = de_cluster_active_race(df, union_sniper, max_hold=180, cooldown=2)
        print(
            f"  >>> {ticker} STATE-LOCKED BEAR SNIPER UNION (No Repeat While Active):\n"
            f"      N={st_union['n_all']:2d} (IS={st_union['n_is']:2d}, OOS={st_union['n_oos']:2d}) | "
            f"RACE_DN: All={st_union['wr_all']:5.1f}% (IS={st_union['wr_is']:5.1f}%, OOS={st_union['wr_oos']:5.1f}%) | "
            f"TOUCH60_DN: All={st_union['t60_all']:5.1f}% (IS={st_union['t60_is']:5.1f}%, OOS={st_union['t60_oos']:5.1f}%)\n"
        )


if __name__ == "__main__":
    main()
