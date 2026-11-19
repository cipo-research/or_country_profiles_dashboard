`or_country_profiles/models/`

This folder mirrors a **dbt (Data Build Tool)-style** layout (`raw`, `staging`, `intermediate`, `marts`) to keep transformations legible and layered—even though we’re **not using dbt** right now.

## Current state of things

- **Today:** each ETL is a **notebook** that writes outputs into the next layer.
- **Future:** notebooks should be converted to python scripts
    - Add an **orchestrator** that runs them in order (similar in spirit to dbt model dependency graphs and YAML configs).

### Data build tool (dbt) ETL structure

For reference on dbt project struture and best practices, see:

- [How we structure our dbt projects](https://docs.getdbt.com/best-practices/how-we-structure/1-guide-overview)
- [dbt Best Practices](https://docs.getdbt.com/best-practices)

### Data marts and star schemas

For notes on fact (`fct`) and dimension (`dim`) tables, see the [Wikipedia page on star schemas](https://en.wikipedia.org/wiki/Star_schema)

- [Kimbal - dimensional modeling techniques](https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/)
    - I.e. how to build effective, maintainable data marts.

---

## TODO

1. **Incomplete pipelines:** `ip_offices`, `regional_ip_office_members` (ETL work remains).
2. Convert priority notebooks to scripts (start with high-churn jobs).
3. Add a minimal orchestrator (`models/run_pipeline.py`) and a dependency order.
4. Add tests (row counts, not-null checks, key uniqueness) per layer.
5. Document inputs/outputs in each script/module docstring.
6. Add a cleaning step after DuckDB runs to remove `.tmp/` folder(s)

If you're not sure what to do next (or disagree with the next steps laid out above), check the dbt guides linked at the top to see where to go next. They’re excellent references even without dbt.

---

## Directory layout

```
models/
├─ raw/           # Land external data with minimal transformation
├─ staging/       # Clean, normalize, and lightly type data; no joins
├─ intermediate/  # Joins, transformations, surrogate keys, slowly-changing dimensions
└─ marts/         # Final, analytics-ready tables for data products
```

**Layer intent (quick rules of thumb):**

-  **raw:** load as-is; only fix what's required to read the data.
-  **staging:** 1:1 with sources; standardize column names, datatypes, and null handling.
-  **intermediate:** integrate across sources; add surrogate keys; apply conformed dimensions.
-  **marts:** presentation-ready; star/snowflake schemas, narrow purpose, stable interfaces.

---

## How to run

**Environment:** use the base Anaconda environment (`C:\ProgramData\anaconda3`). This is the environment where all dependencies (`pandas`, `requests`, `pyarrow`, etc.) are installed. See `requirements.txt` for the full list.

Each ETL is a **notebook**. From project root:

1. Open the relevant notebook in `models/<layer>/`
2. Run all cells
3. Outputs are written to the next layer’s location (as configured in `./utils/paths.py`)

> Note: Run ETL for region tables (M49, SCCAI, dim_regions, etc.) first, since other tables need to be joined with an M49 code to standardize region names.

### WIPO IP flows: annual refresh to RDS

Run when WIPO announces an update to the IP Statistics Data Center (usually November). Use the Anaconda environment for every step.

1. **Set the year range.** Replace `1980_<old year>` with `1980_<new year>` in the WIPO notebooks (`raw/wipo/raw_wipo_ip_extract.ipynb` sets `to_year`; the three `staging/wipo/stg_wipo_ip_flows*.ipynb` notebooks list the file names). A staging notebook stops with `FileNotFoundError` if a raw file for the new range is missing.
2. **Download.** Run `raw/wipo/raw_wipo_ip_extract.ipynb`. Large files occasionally fail with `IncompleteRead`; re-run the notebook, as it skips files already downloaded.
3. **Stage and integrate.** Run `staging/wipo/stg_wipo_ip_flows.ipynb`, `stg_wipo_ip_flows_by_class.ipynb` and `stg_wipo_ip_flows_by_residency.ipynb`, then `intermediate/int_ip_flows.ipynb`, `int_ip_flows_by_class.ipynb` and `int_ip_flows_by_residency.ipynb`. Class labels are read from `data/staging/wipo/ip_classes/` (tracked in git).
4. **Dry run the load.** `python models/load/load_rds__wipo_ip_flows.py` checks the database permissions, validates the tables, maps names to the existing RDS dimension IDs, prints the `fact_yearly` plan (rows unchanged / revised / filled / inserted) and the percentage change per indicator and year for `fact_class` and `fact_ip_total`. Review it before loading.
5. **Optional: test load.** `python models/load/load_rds__wipo_ip_flows.py --test` runs the same load into `fact_yearly_test`, `fact_class_test` and `fact_ip_total_test`, leaving the real tables untouched (it does not need the sequence permissions). Check the test tables with a SQL client, then drop them (SQL in the loader's header).
6. **Load.** `python models/load/load_rds__wipo_ip_flows.py --write` backs up the three fact tables to `<table>_bak_<YYYYMMDD>`, then, in a single transaction: updates revised values and inserts new rows in `fact_yearly` (no rows are deleted), and fully replaces `fact_class` and `fact_ip_total`. To undo, run `--rollback <YYYYMMDD>`. Drop the backup tables once the dashboard has been checked.

Not touched in `fact_yearly`: the existing Chinese trademark rows (indicator `total`, 2014–2024, sourced outside WIPO), the legacy indicators (ID5–ID9, PA9–PA10, TM5–TM9), and PA3 in the years RDS stores by applicant's origin.

Trademark applications into China are stored as one `total` row per origin and year from 2014 (it already includes Madrid filings). The loader therefore skips WIPO's TM1a/TM1b rows into China for years that have `total`, and for later years (from 2025, WIPO reports China by origin) stores them the same way: `total` = WIPO TM1a + TM1b. Years before 2014 keep WIPO's TM1a/TM1b rows, as before.

The load needs `USAGE` on `country_profiles.fact_yearly_id_seq` and `country_profiles.fact_class_id_seq`; the dry run reports any missing permission.

---

## Naming Conventions

### Models

Model filenames should be descriptive and reflect their primary output or function.

- **One-to-One**: When a model creates a single primary table, its filename should match the table name.
    - `int_ip_flows.ipynb` creates the `int_ip_flows` table.
    - The one exception is `marts_`, where `marts_regions.ipynb` would create `dim_regions` table.
        - `marts_*.ipynb` files can create either fact or dimensional tables.
            - Feel free to change this naming scheme if it doesn't work for you; it varies in the DBT literature.
                - I.e. rename `./marts/marts_regions.ipynb` to `./marts/dim_regions.ipynb` so that it conforms to the name of the table it produces
- **Functional Grouping**: For future models that perform a broader action or build multiple related tables, use a name that describes the process.
    - Not yet implemented in current file structure
    - E.g. a script `raw_world_bank__ingest_all.py` loads all World Bank-related sources into the raw layer.

### Tables/Views

- stg_<source>__<entity> (staging)
- int_<domain>__<purpose> (intermediate; to be implemented)
- dim_*, fct_* (marts)

### Columns

- Use snake_case.
- Ensure explicit data types (e.g., cast strings to dates, numbers to appropriate numerics).
- Surrogate keys (e.g., region_sk) should be added in the intermediate or marts layers to provide stable, unique identifiers.
  
> A note on column stability: Marts (composed of fact and dim tables) should be stable interfaces for analytics. Avoid making breaking changes to them (like renaming or removing columns) to avoid breaking downstream data products

---

## Long-term: the Data Bus Marix

In the long run, to manage our ETL pipelines, data marts, and the data that powers our dashboards and reports, we’ll need an easy-to-maintain, high-level planning tool: the Data Bus Matrix.

The Bus Matrix helps us build the data warehouse incrementally, focusing on the business processes our data products serve rather than the data sources or ETL jobs themselves. It highlights which tables and dimensions can be reused across pipelines, making it easier to spot overlaps and avoid duplicating work as the warehouse grows.

To read more about it, see [Kimbal - Enterprise Data Warehouse Bus Architecture](https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/kimball-data-warehouse-bus-architecture/)
