`./or_country_profiles/utils` docs
==================================

This folder contains helper scripts that support the ETL pipeline.
Think of it as the toolbox for common tasks like shared functions, mapping data directories, and managing paths.

> Each script has a detailed description in its module-level docstring.
> Open the script to see more details about what it does and how to extend it.

## Contents

### `etl_utils.py`

General helper functions used across the ETL pipeline.

If it gets too big, split functions into topic-specific files (e.g., statcan_utils.py).

---

### `map_data_directory.py`

Walks through a data folder and logs the directory structure.

Reads data files (CSV, Parquet, TSV, XML, etc.) and records column names + data types.

Outputs:

A directory log at ./project_docs/data_directory_structure.log

A data dictionary at ./project_docs/data_dictionary.csv

How to run:

```bash
# From the repo root
python utils/map_data_directory.py
```

For extension (adding new file formats, changing settings, etc.), see the script’s docstring.

---

### `paths.py`

Central place to define important project directories.

Lets you update directory paths in one file instead of changing many scripts.

How to use in code:

```python
from utils.paths import RAW_DIR, STAGING_DIR

print(RAW_DIR)  # points to ./data/raw
```

---

## Guidelines

Keep it simple. Add helpers here when they’re used in more than one place.

Check the docstring. Each script explains itself in more detail.

Refactor when needed. If a script grows too large, split it into smaller modules.
