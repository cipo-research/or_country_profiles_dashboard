# OECD IP Charges — Pipeline Summary

**Branch:** `feature/oecd-ip-charges`  
**Date:** June 2026  
**Author:** Karim Guida

---

## Overview

This work adds a new data pipeline for Canada's bilateral **Intellectual Property (IP) charges balance**, sourced from the OECD Balance of Payments Trade in Services dataset. The pipeline follows the project's existing three-layer ETL architecture and delivers a validated fact table loaded into the team's Amazon RDS environment.

**IP charges (service code SH)** measures the net flow of payments between Canada and each trading partner for patents, trademarks, franchises, and software licences:
- **Positive balance** — Canada received more than it paid (net IP exporter to that country)
- **Negative balance** — Canada paid more than it received (net IP importer from that country)

---

## Data Source

| | |
|---|---|
| **Provider** | OECD |
| **Dataset** | Balance of Payments Trade in Services (`DSD_BOP@DF_TIS`, version 1.0) |
| **Indicator** | Charges for use of intellectual property, n.i.e. (code: `SH`) — Balance |
| **Dimension key** | `CAN..SH.B..A.XDC.` |
| **API format** | SDMX-JSON 2.0 (`Accept: application/vnd.sdmx.data+json`) |
| **Authentication** | None — public API |
| **Coverage** | 1969–2024 (full available history, no start date filter applied) |
| **Counterparts** | 83 individual countries + World aggregate |
| **Currency** | Canadian dollars (CAD), millions |

---

## Pipeline Architecture

The pipeline follows the project's established layered structure:

```
OECD SDMX-JSON API
        ↓
  [Raw Layer]       Fetch and persist the raw API response unchanged
        ↓
  [Staging Layer]   Parse, filter, clean, and type-cast
        ↓
  [Mart Layer]      Produce the final dashboard-ready fact table
        ↓
  [Load Layer]      Validate and write to Amazon RDS
```

### Files added

| Layer | File | Output |
|---|---|---|
| Raw | `models/raw/oecd/raw_oecd__ip_charges.ipynb` | `data/raw/oecd/raw_oecd__ip_charges.json` |
| Staging | `models/staging/oecd/stg_oecd__ip_charges.ipynb` | `data/staging/oecd/stg_oecd__ip_charges.csv` |
| Mart | `models/marts/marts_ip_charges_yearly.ipynb` | `data/marts/fct_ip_charges_yearly.csv` |
| Load | `models/load/load_rds__ip_charges.ipynb` | `country_profiles.fact_ip_charges_yearly` |

### Supporting files added

| File | Purpose |
|---|---|
| `utils/oecd_utils.py` | Shared SDMX-JSON parsing and cleaning logic, unit-tested independently |
| `tests/test_oecd_ip_charges.py` | Unit tests for `parse_sdmx_json()` and `clean_ip_charges()` |
| `tests/test_mart_fct_ip_charges.py` | Validation tests for the mart CSV output (15 tests) |
| `docs/oecd-ip-charges.md` | Technical documentation for the pipeline |

---

## Key Processing Decisions

### Raw layer
The raw notebook fetches the full SDMX-JSON response from the OECD API and saves it unchanged. No transformation occurs at this layer — the raw file is preserved as an audit trail.

### Staging layer
The OECD API returns parent aggregate rows alongside the IP charges measure. Specifically:
- `SH` — Charges for use of intellectual property (the indicator we want)
- `S` — Services total (parent aggregate, excluded)
- `CA` — Current account total (grandparent aggregate, excluded)

Staging keeps only `MEASURE = SH` rows. Additionally, only observations with `OBS_STATUS = A` (actual) are retained — estimated (`E`) and missing values are dropped. Gaps in coverage are expected and are not filled.

### Mart layer
The mart applies a country name standardisation step to align OECD naming with the `dim_macroecon_region` dimension table in the existing data model. Mapping uses ISO area codes (from the `counterpart_area` column) to avoid special character encoding issues:

| OECD name | Standardised name | ISO code |
|---|---|---|
| China (People's Republic of) | China | `CHN` |
| Hong Kong (China) | Hong Kong | `HKG` |
| Slovak Republic | Slovakia | `SVK` |
| Korea | South Korea | `KOR` |
| Chinese Taipei | Taiwan | `TWN` |

The `World` aggregate (ISO code `W`) is retained in the mart output. It maps to the `All countries` entry (id = 1) in `dim_macroecon_region`.

The `flow_type` column (always `"Charges for use of IP - Balance"`) is present in the mart CSV for transparency but is intentionally excluded from the RDS fact table — it is implied by the table name and is constant across all rows.

### Load layer
The load notebook runs the full validation test suite before writing a single row. If any test fails the upload is aborted. Country names are joined against `dim_macroecon_region` to resolve integer surrogate keys (`macroecon_region_id`) before insert. Row count is verified post-upload.

---

## Output Dataset

**Table:** `country_profiles.fact_ip_charges_yearly`

| Column | PostgreSQL type | Description |
|---|---|---|
| `year` | `integer` | Reference year |
| `macroecon_region_id` | `integer` | FK → `dim_macroecon_region.macroecon_region_id` |
| `value_cad_millions` | `numeric(20,2)` | Net IP charges balance in millions CAD |

**Row count:** 1,315  
**Year range:** 1969–2024  
**Distinct counterparts:** 84 (83 countries + World aggregate)

---

## Data Quality

A suite of 15 automated tests (`tests/test_mart_fct_ip_charges.py`) runs before every RDS upload. The pipeline aborts if any test fails. Tests cover:

- Correct schema (column names, order, count)
- Expected row count (1,315)
- No null values in any column
- No empty strings in text columns
- Year within valid range (1969–2024)
- `flow_type` is always the expected single value
- `value_cad_millions` is numeric with both positive and negative values present
- No raw OECD names remaining (standardisation applied correctly)
- All required standardised country names present
- No duplicate `(year, counterpart_country)` combinations
- Spot-check: USA 2022 row exists with a negative balance

---

## New Project-Level Files

| File | Purpose |
|---|---|
| `requirements.txt` | Python dependency list for the project (`pandas`, `requests`, `pyarrow`, `pytest`, `jupyterlab`, `sqlalchemy`, `psycopg2-binary`, `python-dotenv`) |
| `pytest.ini` | Pytest configuration — points test runner at the `tests/` directory |
| `.gitignore` | Excludes data files, credentials, cache directories, and compiled Python from version control |

---

## Changes to Existing Files

| File | Change |
|---|---|
| `utils/paths.py` | Added `OECD` source constant, `RAW_OECD_DIR`, `STG_OECD_DIR`; fixed `REPO_DIR` repo name |
| `utils/etl_utils.py` | Fixed `REPO_NAME` constant; replaced `Optional[bool]` with `bool`; fixed typo |
| `models/README_models.md` | Added Anaconda environment note to the How to run section |
