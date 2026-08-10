# OECD IP charges

"Charges for the use of intellectual property, n.i.e." (service code **SH**) from the OECD Balance of Payments Trade in Services dataset. Covers the payments between Canada and each trading partner for patents, trademarks, franchises, and software licences.

Three accounting entries are pulled together (`ACCOUNTING_ENTRY = C+D+B`):

| Entry | OECD label | Meaning for Canada |
|---|---|---|
| `C` | Revenue | Royalties Canada **earns** (receipts) — a BOP "credit" |
| `D` | Expenditure | Royalties Canada **pays** (payments) — a BOP "debit" |
| `B` | Balance | **Net** = revenue − expenditure |

Positive balance = Canada received more than it paid. Negative = Canada paid more than it received. Values are in **millions CAD**.

---

## Data availability

Coverage varies by counterpart — no start date filter is applied, so the pipeline always fetches the full available history:

| Counterpart | Approximate start (all three entries) |
|---|---|
| World total | 1969 |
| United States | ~1988 |
| Most individual countries | ~2010 |

The **World aggregate carries revenue, expenditure and balance back to 1969** (e.g. World 1990: revenue 274, expenditure 1,941, balance −1,667). The partner-level breakdown begins ~2010. A few partner-years report only some of the three entries, so `revenue` / `expenditure` / `balance` can individually be null in the wide mart — faithful to the source, not a defect.

---

## API

| | |
|---|---|
| Base URL | `https://sdmx.oecd.org/public/rest/data` |
| Dataset | `OECD.SDD.TPS,DSD_BOP@DF_TIS,1.0` |
| Dimension key | `CAN..SH.C+D+B..A.XDC.` |
| Format | SDMX-JSON (`Accept: application/vnd.sdmx.data+json`) |
| Auth | None |

Full URL:
```
https://sdmx.oecd.org/public/rest/data/OECD.SDD.TPS,DSD_BOP@DF_TIS,1.0/CAN..SH.C+D+B..A.XDC.?dimensionAtObservation=AllDimensions
```

The key `CAN..SH.C+D+B..A.XDC.` breaks down as: Canada · all counterparts · IP charges · **revenue + expenditure + balance** · all · annual · CAD · all.

Browse it in the OECD Data Explorer:
```
https://data-explorer.oecd.org/vis?df[ds]=dsDisseminateFinalDMZ&df[id]=DSD_BOP@DF_TIS&df[ag]=OECD.SDD.TPS&df[vs]=1.0&lc=en&dq=CAN..SH.C+D+B..A.XDC.
```

---

## Pipeline

| Layer | Notebook | Output |
|---|---|---|
| Raw | `models/raw/oecd/raw_oecd__ip_charges.ipynb` | `data/raw/oecd/raw_oecd__ip_charges.json` |
| Staging | `models/staging/oecd/stg_oecd__ip_charges.ipynb` | `data/staging/oecd/stg_oecd__ip_charges.csv` |
| Mart | `models/marts/marts_ip_charges_yearly.ipynb` | `data/marts/fct_ip_charges_yearly.csv` |
| Load | `models/load/load_rds__ip_charges.ipynb` | `country_profiles.fact_ip_charges_yearly` (Amazon RDS) |

No intermediate layer — single source, no joins needed.

**Staging schema (`stg_oecd__ip_charges.csv`) — long, one row per accounting entry:**

| Column | Type | Example |
|---|---|---|
| `year` | integer | `2024` |
| `counterpart_area` | string | `"USA"` |
| `counterpart_country` | string | `"United States"` |
| `accounting_entry` | string | `"C"` / `"D"` / `"B"` |
| `value_cad_millions` | float | `6328.0` |

**Mart schema (`fct_ip_charges_yearly.csv`) — wide, one row per year × counterpart:**

| Column | Type | Example |
|---|---|---|
| `year` | integer | `2024` |
| `counterpart_country` | string | `"United States"` |
| `balance_cad_millions` | float | `-11714.0` |
| `revenue_cad_millions` | float | `6328.0` |
| `expenditure_cad_millions` | float | `18042.0` |

At load, `counterpart_country` is resolved to `macroecon_region_id` and dropped, so the RDS table is `[year, macroecon_region_id, balance_cad_millions, revenue_cad_millions, expenditure_cad_millions]`.

---

## How to run

```bash
jupyter nbconvert --to notebook --execute models/raw/oecd/raw_oecd__ip_charges.ipynb
jupyter nbconvert --to notebook --execute models/staging/oecd/stg_oecd__ip_charges.ipynb
jupyter nbconvert --to notebook --execute models/marts/marts_ip_charges_yearly.ipynb
```

Or open them in JupyterLab and run all cells manually, **in order** (raw → staging → mart): the mart reads what staging writes.

**Load layer:** Run `models/load/load_rds__ip_charges.ipynb` interactively in JupyterLab after the mart. Requires a `.env` file in the project root with RDS credentials (`RDS_HOST`, `RDS_PORT`, `RDS_DB`, `RDS_USER`, `RDS_PASSWORD`). The notebook validates the mart CSV against the mart tests before writing a single row. Because the balance-only table already exists and the schema changes (new revenue/expenditure columns; `value_cad_millions` → `balance_cad_millions`), run the **Rollback** cell first to drop it, then reload (full replace).

---

## Country name standardisation

OECD country names differ slightly from the naming convention used in the dashboard's `Dim MacroRegion`. The mart notebook maps them (keyed on ISO area code to avoid special characters) before writing the output CSV:

| OECD name | Standardised name |
|---|---|
| `China (People's Republic of)` | `China` |
| `Hong Kong (China)` | `Hong Kong` |
| `Slovak Republic` | `Slovakia` |
| `Korea` | `South Korea` |
| `Chinese Taipei` | `Taiwan` |

`World` (the OECD aggregate across all counterparts, ISO code `W`) is **kept in the CSV** and mapped to `All countries` at load.

---

## Gotchas

- **Parent aggregates in raw data.** The API returns `S` (Services) and `CA` (Current account) rows even when filtering to `SH`. Staging filters them out.
- **Three accounting entries.** The `C+D+B` key returns revenue, expenditure and balance, so `ACCOUNTING_ENTRY` is not constant in the raw response (same as `MEASURE`) — it is excluded from the staging `EXPECTED` validation. Staging keeps the entry; the mart pivots it into `balance` / `revenue` / `expenditure` columns.
- **`balance = revenue − expenditure`.** The identity holds wherever all three are reported (unit-tested in `tests/test_mart_fct_ip_charges.py`).
- **Sparse coverage is expected.** Gaps are real — don't fill them. Revenue/expenditure run to 1969 for the World aggregate but only from ~2010 at the partner level, and some partner-years report only some entries.
- **Zero values are real.** `0` means the value rounded to zero at million-dollar precision. Truly missing data is excluded by the `OBS_STATUS = A` filter in staging.
