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

Each ETL is a **notebook**. From project root:

1. Open the relevant notebook in `models/<layer>/`
2. Run all cells
3. Outputs are written to the next layer’s location (as configured in `./utils/paths.py`)

> Note: Run ETL for region tables (M49, SCCAI, dim_regions, etc.) first, since other tables need to be joined with an M49 code to standardize region names.

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
