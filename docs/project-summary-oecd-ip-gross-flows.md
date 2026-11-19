# OECD IP Charges — Gross Flows Extension

**Branch:** `feature/oecd-ip-gross-flows`
**Date:** July 2026
**Builds on:** PR #1 (`feature/oecd-ip-charges`) — the original balance-only pipeline

---

## Overview

The original pipeline delivered Canada's bilateral IP charges **net balance** by trading partner. This extension adds the **gross flows** behind that balance — the two components that net into it:

- **Revenue** — royalties Canada **earns** from a partner (a "credit" in balance-of-payments terms)
- **Expenditure** — royalties Canada **pays** to a partner (a "debit")
- **Balance** — the net, `revenue − expenditure` (as before)

The fact table now carries all three per year × partner. Column names follow the **OECD Data Explorer's own labels** (Revenue / Expenditure / Balance) so the schema reads the same way as the published source for a general audience.

**Why it matters.** The net balance hides the gross story. In 2024 Canada *earned* about **$10.9B** in IP royalties from the world and *paid* about **$27.7B** — the net −$16.8B on its own makes it look as though Canada earns nothing from IP, which is false. Exposing revenue and expenditure lets the dashboards show what Canada actually earns, not just the deficit.

---

## What changed at the source

Revenue and expenditure are **not a new dataset** — they are two other values of the same series' `ACCOUNTING_ENTRY` dimension. A single change to the dimension key pulls all three entries in one request:

| | Before (balance only) | After (gross flows) |
|---|---|---|
| Dimension key | `CAN..SH.B..A.XDC.` | `CAN..SH.C+D+B..A.XDC.` |

`C` = Revenue (credit), `D` = Expenditure (debit), `B` = Balance. Everything else — dataset, measure (`SH`), frequency, currency — is unchanged.

---

## Data model decision: wide, not long

The three entries could be stored **long** (three rows per year × partner, tagged by entry) or **wide** (three value columns, one row per year × partner). This extension uses **wide**.

**Rationale:**
- **Grain is preserved.** One row per (year, counterpart) — identical to the balance-only table — so the existing Power BI model and its measures keep working unchanged.
- **Additivity is safe.** Because `balance = revenue − expenditure`, stacking all three in one long column would make `SUM` double-count (it would add the total back onto its parts). Separate columns are each independently additive down their own rows.
- **Complexity stays in tested Python.** The reshape lives in a unit-tested helper, not in the live report.

The balance column is renamed for clarity, and two columns are added:

| Before | After |
|---|---|
| `value_cad_millions` | `balance_cad_millions` |
| — | `revenue_cad_millions` |
| — | `expenditure_cad_millions` |

---

## Pipeline changes (same four layers)

| Layer | Change |
|---|---|
| Raw | Dimension key → `C+D+B`; validation prints the accounting entries returned |
| Staging | `clean_ip_charges()` now **retains** `accounting_entry` (previously dropped); the `ACCOUNTING_ENTRY = B` constant-dimension check is removed (it is no longer constant, like `MEASURE`) |
| Mart | Calls the new `pivot_ip_charges_wide()` to turn the long staged data into the wide `balance/revenue/expenditure` shape; `flow_type` column removed |
| Load | Writes the three value columns; `value_cad_millions` → `balance_cad_millions`. Because the balance-only table already exists and the schema changes, the load is a **full replace** (drop then reload) |

New helper in `utils/oecd_utils.py`:
- `pivot_ip_charges_wide(df)` — pivots the long cleaned data (one row per accounting entry) into one row per (year, counterpart) with `balance_cad_millions` / `revenue_cad_millions` / `expenditure_cad_millions`.

---

## Output schema

**Mart (`fct_ip_charges_yearly.csv`) — wide:**

| Column | Type | Description |
|---|---|---|
| `year` | int | Reference year |
| `counterpart_country` | str | Trading partner (e.g. `"United States"`) |
| `balance_cad_millions` | float | Net = revenue − expenditure, millions CAD |
| `revenue_cad_millions` | float | Revenue: royalties Canada earns, millions CAD |
| `expenditure_cad_millions` | float | Expenditure: royalties Canada pays, millions CAD |

**RDS table `country_profiles.fact_ip_charges_yearly`:** at load, `counterpart_country` is resolved to `macroecon_region_id` and dropped, giving `[year, macroecon_region_id, balance_cad_millions, revenue_cad_millions, expenditure_cad_millions]` (`numeric(20,2)` for the value columns).

**Row count:** 1,323 (was 1,315) · **Year range:** 1969–2024.

---

## Coverage (correction vs. an early assumption)

The **World aggregate carries all three entries back to 1969** (e.g. World 1990: revenue 274, expenditure 1,941, balance −1,667). Only the **partner-level** breakdown begins ~2010. A small number of partner-years report only some of the three entries — in the current pull, 8 rows have a null balance, 6 null revenue, 2 null expenditure. These are left blank (faithful to source); the wide layout handles them without inventing values.

---

## Verification

All logic is verified offline before any load, no database required:

- **`tests/test_oecd_ip_charges.py` — 25 tests** covering parse, clean (entry retained), and `pivot_ip_charges_wide` (three entries pivoted, pre-gross rows keep balance with null revenue/expenditure).
- **`tests/test_mart_fct_ip_charges.py` — 17 tests** on the generated wide CSV: schema, row count, keys never null (value columns may have gaps), revenue/expenditure non-negative, and the **`balance = revenue − expenditure` identity** across every fully-populated row.

Real spot checks (2024, CAD millions):

| Partner | Revenue (earns) | Expenditure (pays) | Balance |
|---|---|---|---|
| World | 10,915 | 27,745 | −16,830 |
| United States | 6,328 | 18,042 | −11,714 |
| Mexico | 355 | 43 | 312 |

---

## Files changed

| File | Change |
|---|---|
| `utils/oecd_utils.py` | `clean_ip_charges` retains the accounting entry; added `pivot_ip_charges_wide` |
| `tests/test_oecd_ip_charges.py` | Fixture extended to C/D/B; clean + pivot tests (25 total) |
| `tests/test_mart_fct_ip_charges.py` | Wide schema; nulls allowed in value columns; identity check (17 total) |
| `models/raw/oecd/raw_oecd__ip_charges.ipynb` | Dimension key → `C+D+B`; accounting-entry validation |
| `models/staging/oecd/stg_oecd__ip_charges.ipynb` | Removed the `ACCOUNTING_ENTRY = B` constant check |
| `models/marts/marts_ip_charges_yearly.ipynb` | Pivots to wide via `pivot_ip_charges_wide` |
| `models/load/load_rds__ip_charges.ipynb` | Three value columns; full-replace (drop + reload) |
| `docs/oecd-ip-charges.md` | Updated for the gross-flows pipeline |
| `utils/README_utils.md` | Documented `pivot_ip_charges_wide` |

---

## Notes for review

- The load is a **full replace** of `fact_ip_charges_yearly` (schema change), run manually after the mart validation passes: run the notebook's Rollback cell (drop), then Steps 1–8. The new data is a superset of the old (all prior balances plus the new revenue/expenditure), so nothing is lost.
- Downstream (separate work): add `IP Revenue` / `IP Expenditure` measures in Power BI and re-point the base measure to `balance_cad_millions`.
