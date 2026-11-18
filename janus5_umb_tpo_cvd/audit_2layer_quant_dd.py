"""
Full Quant Due-Diligence Evaluation of the 2-Layer Combined System (Jul 2020 - Nov 2026)
========================================================================================
Tests the 2-Layer System against:
  - Buy & Hold 24h
  - Exposure-Matched Benchmark
  - Always Overnight (15:50 -> 09:30, 1x Cost)
  - Layer-1 Only 24h Hold (No Layer-2 TPO/CVD, 1x Cost)
  - Layer-1 Only Overnight Hold (No Layer-2 TPO/CVD, 1x Cost)
  - 1x, 2x, 3x Transaction Costs
  - Nearby Parameter Thresholds (0.53/0.47 vs 0.55/0.45 vs 0.57/0.43)
  - 200-Permutation Placebo Test, Top-10 Day Concentration, Worst Day/Week/Month/Year
"""

import sys
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline

ROOT = Path("c:/Users/amitr/OneDrive/Documents/ANT_SOX")
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "research" / "macro_5pct_engine"))

from run_janus_tpo_cvd_sniper import (
    fetch_full_1m_2020_2026,
    build_1550_table,
    add_layer1_macro_frvwap_features,
    get_historical_rf_daily,
    compute_metrics,
)


def main():
    syms = ["QQQ", "TQQQ", "SQQQ", "SOXX", "SOXL", "SOXS"]
    bars = {s: fetch_full_1m_2020_2026(s) for s in syms}
    tables = {s: build_1550_table(bars[s], s) for s in syms}
    feat_2factor = [
        "clv_1550",
        "poc_dist_1550",
        "above_vah_1550",
        "below_val_1550",
        "btail_1550",
        "stail_1550",
        "cvd_day_1550",
        "cvd_pm_1550",
        "und_cvd_pm_1550",
    ]

    for bull_etf, bear_etf, und_etf, cost_1x in [("TQQQ", "SQQQ", "QQQ", 6.0), ("SOXL", "SOXS", "SOXX", 10.0)]:
        df = add_layer1_macro_frvwap_features(tables[bull_etf], tables[und_etf])
        u_df = tables[und_etf].reindex(df.index)
        inv_df = tables[bear_etf].reindex(df.index)
        df["und_cvd_pm_1550"] = u_df["cvd_pm_1550"]
        df["inv_ret_24h_1550"] = inv_df["ret_24h_1550"]
        df["inv_ret_ovn_1550"] = inv_df["ret_ovn_1550"]
        df = df.dropna(
            subset=feat_2factor + ["ret_24h_1550", "inv_ret_24h_1550", "ret_ovn_1550", "inv_ret_ovn_1550"]
        ).copy()
        rf_s = get_historical_rf_daily(df.index)
        X_all = df[feat_2factor].values
        min_train, refit_step = 126, 21

        def run_var(ret_b, ret_s, cost_bps, p_hi=0.55, p_lo=0.45, use_l1=True):
            y_all = (df[ret_b].values > 0.0).astype(int)
            rb, rs = df[ret_b].values, df[ret_s].values
            al_l, al_s = df["layer1_allow_long"].values, df["layer1_allow_short"].values
            rf_v = rf_s.values
            c_dec = cost_bps / 10000.0
            pos = np.zeros(len(df))
            clf = None
            for t in range(min_train, len(df)):
                if clf is None or ((t - min_train) % refit_step == 0):
                    clf = make_pipeline(StandardScaler(), LogisticRegression(C=0.20))
                    clf.fit(X_all[: t - 1], y_all[: t - 1])
                p = clf.predict_proba(X_all[t : t + 1])[0, 1]
                if p >= p_hi and (not use_l1 or al_l[t]):
                    pos[t] = 1.0
                elif p <= p_lo and (not use_l1 or al_s[t]):
                    pos[t] = -1.0
            net = np.where(pos == 1.0, rb - c_dec, np.where(pos == -1.0, rs - c_dec, rf_v))
            return pd.DataFrame(
                {"pos": pos[min_train:], "ret": net[min_train:], "rb": rb[min_train:], "rs": rs[min_train:]},
                index=df.index[min_train:],
            )

        w_24_1x = run_var("ret_24h_1550", "inv_ret_24h_1550", cost_1x)
        w_24_2x = run_var("ret_24h_1550", "inv_ret_24h_1550", cost_1x * 2)
        w_24_3x = run_var("ret_24h_1550", "inv_ret_24h_1550", cost_1x * 3)
        w_ovn_1x = run_var("ret_ovn_1550", "inv_ret_ovn_1550", cost_1x)
        w_ovn_2x = run_var("ret_ovn_1550", "inv_ret_ovn_1550", cost_1x * 2)
        w_ovn_3x = run_var("ret_ovn_1550", "inv_ret_ovn_1550", cost_1x * 3)
        w_ovn_53 = run_var("ret_ovn_1550", "inv_ret_ovn_1550", cost_1x, 0.53, 0.47)
        w_ovn_57 = run_var("ret_ovn_1550", "inv_ret_ovn_1550", cost_1x, 0.57, 0.43)

        idx = w_ovn_1x.index
        bmk_24h = df.loc[idx, "ret_24h_1550"]
        c_dec = cost_1x / 10000.0
        bmk_ovn_always = df.loc[idx, "ret_ovn_1550"] - c_dec
        l1_only_ovn = pd.Series(
            np.where(df.loc[idx, "layer1_allow_long"], df.loc[idx, "ret_ovn_1550"] - c_dec, rf_s.loc[idx]), index=idx
        )
        l1_pos = df.loc[idx, "layer1_allow_long"].astype(float)
        l1_turn = l1_pos.diff().abs().fillna(0.0)
        l1_only_24h = l1_pos * df.loc[idx, "ret_24h_1550"] + (1.0 - l1_pos) * rf_s.loc[idx] - l1_turn * (c_dec / 2.0)

        exp_ovn = (w_ovn_1x["pos"] != 0).mean()
        bmk_exp = bmk_24h * exp_ovn + rf_s.loc[idx] * (1.0 - exp_ovn)

        print(f"\n=========================================================================================================")
        print(f"  {bull_etf}/{bear_etf} QUANT DUE-DILIGENCE EVALUATION (Jul 2020 - Nov 2026, {len(idx)} Sessions, Exp={exp_ovn*100:.1f}%)")
        print(f"=========================================================================================================")
        for name, s in [
            ("1. Benchmark: Buy & Hold 24h", bmk_24h),
            (f"2. Exposure-Matched Benchmark ({exp_ovn*100:.0f}% Exp)", bmk_exp),
            ("3. Baseline: Always Overnight 15:50->09:30 (1x Cost)", bmk_ovn_always),
            ("4. Baseline: Layer-1 Only 24h Hold (No TPO/CVD, 1x)", l1_only_24h),
            ("5. Baseline: Layer-1 Only Overnight (No TPO/CVD, 1x)", l1_only_ovn),
            ("6. 2-Layer Combined 24h Hold (1x Cost)", w_24_1x["ret"]),
            ("7. 2-Layer Combined 24h Hold (2x Cost)", w_24_2x["ret"]),
            ("8. 2-Layer Combined 24h Hold (3x Cost)", w_24_3x["ret"]),
            ("9. 2-Layer Combined Overnight 15:50->09:30 (1x Cost)", w_ovn_1x["ret"]),
            ("10. 2-Layer Combined Overnight 15:50->09:30 (2x Cost)", w_ovn_2x["ret"]),
            ("11. 2-Layer Combined Overnight 15:50->09:30 (3x Cost)", w_ovn_3x["ret"]),
            ("12. Robustness: 2-Layer Ovn Thresh 0.53/0.47 (1x)", w_ovn_53["ret"]),
            ("13. Robustness: 2-Layer Ovn Thresh 0.57/0.43 (1x)", w_ovn_57["ret"]),
        ]:
            m = compute_metrics(s, bmk_24h)
            top10 = s.nlargest(10).sum() * 100
            tot = s.sum() * 100
            yr_r = ((1 + s).resample("YE").prod() - 1) * 100
            w_yr = yr_r.min()
            b_yr = yr_r.max()
            print(
                f"  {name:54s} | CAGR:{m['cagr']:+6.1f}% | DD:{m['max_dd']:+6.1f}% | Shp:{m['sharpe']:5.2f} | "
                f"Beta:{m['beta']:4.2f} | Alp:{m['alpha']:+6.1f}% (t={m['t']:+5.2f}) | WDay:{m['worst_day']:+6.1f}% | "
                f"WMo:{m['worst_mo']:+6.1f}% | WYr:{w_yr:+6.1f}% | BYr:{b_yr:+6.1f}% | Top10/Tot:{top10:+.0f}%/{tot:+.0f}%"
            )

        # Trade counts & Placebo on 2-Layer Overnight (Row 9)
        l_tr = w_ovn_1x[w_ovn_1x["pos"] == 1.0]
        s_tr = w_ovn_1x[w_ovn_1x["pos"] == -1.0]
        l_wr = (l_tr["rb"] > 0).mean() * 100 if len(l_tr) else 0
        s_wr = (s_tr["rs"] > 0).mean() * 100 if len(s_tr) else 0
        base_ovn_up = (w_ovn_1x["rb"] > 0).mean() * 100

        rng = np.random.default_rng(42)
        real_shp = compute_metrics(w_ovn_1x["ret"], bmk_24h)["sharpe"]
        pos_arr = w_ovn_1x["pos"].values
        rb_arr = w_ovn_1x["rb"].values
        rs_arr = w_ovn_1x["rs"].values
        rf_arr = rf_s.loc[idx].values
        pl_shps = []
        for _ in range(200):
            p_s = rng.permutation(pos_arr)
            r_p = np.where(p_s == 1.0, rb_arr - c_dec, np.where(p_s == -1.0, rs_arr - c_dec, rf_arr))
            ex = r_p - rf_arr
            pl_shps.append((ex.mean() / (r_p.std() + 1e-9)) * np.sqrt(252.0))
        pval = (np.array(pl_shps) >= real_shp).mean()
        print(
            f"  [2-Layer Ovn Trade & Placebo Audit]: Long {bull_etf}: N={len(l_tr):3d} (WR={l_wr:4.1f}% vs Base={base_ovn_up:4.1f}%), "
            f"Long {bear_etf}: N={len(s_tr):3d} (WR={s_wr:4.1f}%) | Placebo Shp={np.mean(pl_shps):+.2f}+/-{np.std(pl_shps):.2f} (p={pval:.3f})"
        )


if __name__ == "__main__":
    main()
