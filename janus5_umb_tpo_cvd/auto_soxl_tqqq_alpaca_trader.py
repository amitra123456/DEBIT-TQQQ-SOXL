"""
Automated 3:15–3:30 PM ET Debit Spread Execution Engine for Alpaca (SOXL & TQQQ)
=================================================================================
Production Forwarder for Windows Scheduled Tasks:
Routes all live execution, 5-minute staged checkpoints (15:12, 15:15, 15:20, 15:25, 15:30, 15:33),
and Day-1 1:30 PM early-cut checks directly to the audited, hardened package:
`soxl_tqqq_debit_330.execution.alpaca_trader`.

Enforces:
  1. Triply-redundant Day-0 Hard Block (no self-stops on Day 0).
  2. Bounded Worst-Case Debit Sizing Cap (max 4.0% account equity).
  3. Standardized 7–14 DTE (Next Friday) contracts (eliminating 2–4 DTE gamma cliffs).
  4. Hard-blocked disabled sleeves before order routing.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure ANT_SOX repository root is at front of sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from soxl_tqqq_debit_330.execution.alpaca_trader import AlpacaDebitSpreadTrader, main

if __name__ == "__main__":
    main()
