# OECD IP charges

"Charges for the use of intellectual property, n.i.e." (service code **SH**) from the OECD Balance of Payments Trade in Services dataset. Measures the net value of payments between Canada and each trading partner for patents, trademarks, franchises, and software licences.

Positive balance = Canada received more than it paid. Negative = Canada paid more than it received. Values are in **millions CAD**.

---

## Data availability

Coverage varies by counterpart — no start date filter is applied, so the pipeline always fetches the full available history:

| Counterpart | Approximate start |
|---|---|
| World total | before 1988 |
| United States | ~1988 |
| Most individual countries | ~2020 |

---

## API

| | |
|---|---|
| Base URL | `https://sdmx.oecd.org/public/rest/data` |
| Dataset | `OECD.SDD.TPS,DSD_BOP@DF_TIS,1.0` |
| Dimension key | `CAN..SH.B..A.XDC.` |
| Format | SDMX-JSON (`Accept: application/vnd.sdmx.data+json`) |
| Auth | None |

Full URL:
```
https://sdmx.oecd.org/public/rest/data/OECD.SDD.TPS,DSD_BOP@DF_TIS,1.0/CAN..SH.B..A.XDC.?dimensionAtObservation=AllDimensions
```

The key `CAN..SH.B..A.XDC.` breaks down as: Canada · all counterparts · IP charges · balance · all · annual · CAD · all.

---

## Pipeline

| Layer | Notebook | Output |
|---|---|---|
| Raw | `models/raw/oecd/raw_oecd__ip_charges.ipynb` | `data/raw/oecd/raw_oecd__ip_charges.json` |
| Staging | `models/staging/oecd/stg_oecd__ip_charges.ipynb` | `data/staging/oecd/stg_oecd__ip_charges.csv` |
| Mart | `models/marts/marts_ip_charges_yearly.ipynb` | `data/marts/fct_ip_charges_yearly.csv` |
| Load | `models/load/load_rds__ip_charges.ipynb` | `country_profiles.fact_ip_charges_yearly` (Amazon RDS) |

No intermediate layer — single source, no joins needed.

**Mart schema (`fct_ip_charges_yearly.csv`):**

| Column | Type | Example |
|---|---|---|
| `year` | integer | `2022` |
| `counterpart_country` | string | `"United States"` |
| `flow_type` | string | `"Charges for use of IP - Balance"` |
| `value_cad_millions` | float | `-4325.4` |

---

## How to run

```bash
jupyter nbconvert --to notebook --execute models/raw/oecd/raw_oecd__ip_charges.ipynb
jupyter nbconvert --to notebook --execute models/staging/oecd/stg_oecd__ip_charges.ipynb
jupyter nbconvert --to notebook --execute models/marts/marts_ip_charges_yearly.ipynb
```

Or open them in JupyterLab and run all cells manually.

**Load layer:** Run `models/load/load_rds__ip_charges.ipynb` interactively in JupyterLab after the mart. Requires a `.env` file in the project root with RDS credentials (`RDS_HOST`, `RDS_PORT`, `RDS_DB`, `RDS_USER`, `RDS_PASSWORD`). The notebook validates the mart CSV against 15 tests before writing a single row.

---

## Country name standardisation

OECD country names differ slightly from the naming convention used in the dashboard's `Dim MacroRegion`. The mart notebook applies the following mapping before writing the output CSV:

| OECD name | Standardised name |
|---|---|
| `China (People's Republic of)` | `China` |
| `Hong Kong (China)` | `Hong Kong` |
| `Slovak Republic` | `Slovakia` |
| `Korea` | `South Korea` |
| `Chinese Taipei` | `Taiwan` |

`World` (the OECD aggregate across all counterparts, ISO code `W`) is **kept in the CSV** and can be filtered out downstream as needed.

---

## Gotchas

- **Parent aggregates in raw data.** The API returns `S` (Services) and `CA` (Current account) rows even when filtering to `SH`. Staging filters them out.
- **Sparse coverage is expected.** Gaps are real — don't fill them.
- **Zero values are real.** `0` means the balance rounded to zero at million-dollar precision. Truly missing data is excluded by the `OBS_STATUS = A` filter in staging.
- **Balance only for now.** To add credits/debits, update `DIMENSION_KEY` in the raw notebook to `CAN..SH.B+C+D..A.XDC.` and add a `flow_type` mapping in the mart.
