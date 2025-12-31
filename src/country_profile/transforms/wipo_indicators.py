
# src/country_profile/transforms/wipo_indicators.py
from __future__ import annotations
from pathlib import Path
import pandas as pd

from country_profile.config import (
    YEAR, COUNT, COL_RENAME_MAP, NUMERIC_COLS, STRING_COLS,
)

# ----------------------------- IO -----------------------------


def load_indicator_df(filepath: Path, verbose: bool = False) -> pd.DataFrame:
    """
    Load a WIPO IP indicator CSV.

    - Skips the 6-row preamble WIPO adds ahead of the header.
    - Normalizes header names if they appear as '$$MISSING$$' placeholders:
        A -> 'Office'
        B -> 'Office (Code)'
        C -> 'Origin'
      (only applied to the leading non-year columns)
    """
    if verbose:
        print(f"Loading IP indicator '{filepath.name}'")

    # WIPO CSVs have 6-row header preamble
    df = pd.read_csv(filepath, skiprows=6, index_col=False)

    # Normalize $$MISSING$$ placeholders that sometimes show up in A/B/C
    fixed_cols = _fix_missing_headers(list(df.columns))
    df.columns = fixed_cols
    return df


# -------------------------- transforms -------------------------


def unpivot_indicator_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    Convert wide year columns into long (YEAR, COUNT).

    Robust year detection: any 4-digit integer in [1800, 2100] is treated as a year.
    """
    df = df.copy()
    df.columns = [str(col).strip() for col in df.columns]

    # robust year detection (any 4-digit year 1800–2100)
    year_cols = [c for c in df.columns if _looks_year(c)]
    if year_cols:
        id_vars = [c for c in df.columns if c not in year_cols]
    else:
        # fallback: first digit-only col onward
        cols = list(df.columns)
        first_year_col_idx = next(i for i, col in enumerate(cols) if str(col).isdigit())
        id_vars = cols[:first_year_col_idx]
        year_cols = cols[first_year_col_idx:]

    return df.melt(id_vars=id_vars, value_vars=year_cols, var_name=YEAR, value_name=COUNT)


def rename_indicator_cols(df: pd.DataFrame) -> pd.DataFrame:
    """
    Rename WIPO headers to the project’s canonical column names using COL_RENAME_MAP.
    """
    cols_to_rename = {c: new for c, new in COL_RENAME_MAP.items() if c in df.columns}
    return df.rename(columns=cols_to_rename)


def enforce_indicator_schema(
    df: pd.DataFrame,
    strict: bool = False,
    verbose: bool = False,
) -> pd.DataFrame:
    """
    Final cleaning/casting step:
      - Trim and null-empty string columns (STRING_COLS)
      - Coerce numeric columns (NUMERIC_COLS)
      - Optionally raise if any required column is missing (strict=True)
    """

    def clean_string_col(s: pd.Series) -> pd.Series:
        s = s.astype("string").str.strip().replace("", pd.NA)
        return s

    missing = [col for col in (STRING_COLS + list(NUMERIC_COLS)) if col not in df.columns]
    if strict and missing:
        raise ValueError(f"Missing required columns: {missing}")

    df = df.copy()
    for col in STRING_COLS:
        if col in df.columns:
            df[col] = clean_string_col(df[col])
            if verbose:
                print(f"Cleaned string col: '{df[col].name}'")

    for col in NUMERIC_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
            if verbose:
                print(f"  Cast numeric col: '{df[col].name}' -> {df[col].dtype}")

    return df


# -------------------------- helpers ----------------------------


_MISS = "$$MISSING$$"


def _looks_year(x: str) -> bool:
    try:
        xi = int(str(x))
        return 1800 <= xi <= 2100
    except Exception:
        return False


def _fix_missing_headers(cols: list[str]) -> list[str]:
    """
    Replace '$$MISSING$$' placeholders with expected WIPO column names.

    We only touch the *leading non-year* columns so year columns remain intact.
    Typical incoming pattern (row after preamble):
        ['$$MISSING$$', '$$MISSING$$ ($$MISSING$$)', '$$MISSING$$', '1980', '1981', ...]
    becomes:
        ['Office', 'Office (Code)', 'Origin', '1980', '1981', ...]
    """
    c = [str(x).strip() for x in cols]

    # Identify the leftmost non-year columns
    non_year_idx = []
    for i, name in enumerate(c):
        if _looks_year(name):
            break
        non_year_idx.append(i)

    def is_missing(name: str) -> bool:
        return isinstance(name, str) and _MISS in name

    # 0 -> Office
    if len(non_year_idx) >= 1 and is_missing(c[non_year_idx[0]]):
        c[non_year_idx[0]] = "Office"

    # 1 -> Office (Code)
    if len(non_year_idx) >= 2 and is_missing(c[non_year_idx[1]]):
        c[non_year_idx[1]] = "Office (Code)"

    # 2 -> Origin  (Applicant's origin)
    if len(non_year_idx) >= 3 and is_missing(c[non_year_idx[2]]):
        c[non_year_idx[2]] = "Origin"

    return c
