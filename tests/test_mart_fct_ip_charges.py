"""
Validates the mart output CSV (fct_ip_charges_yearly.csv) before uploading to RDS.

Run with: pytest tests/test_mart_fct_ip_charges.py -v
All tests must pass before writing to the database.
"""

import pandas as pd
import pytest
from pathlib import Path

MART_PATH = Path(__file__).parent.parent / 'data' / 'marts' / 'fct_ip_charges_yearly.csv'

EXPECTED_COLUMNS   = ['year', 'counterpart_country', 'flow_type', 'value_cad_millions']
EXPECTED_FLOW_TYPE = 'Charges for use of IP - Balance'
EXPECTED_ROW_COUNT = 1315
YEAR_MIN           = 1969
YEAR_MAX           = 2024

# Country names that must NOT appear (raw OECD names that should have been standardised)
BANNED_NAMES = [
    "China (People's Republic of)",
    "Hong Kong (China)",
    "Slovak Republic",
    "Korea",
    "Chinese Taipei",
]

# Country names that must appear (our standardised versions)
REQUIRED_NAMES = [
    "China",
    "Hong Kong",
    "Slovakia",
    "South Korea",
    "Taiwan",
    "World",           # kept in CSV, filtered in Power BI
    "United States",
]


@pytest.fixture(scope='module')
def df():
    assert MART_PATH.exists(), f"Mart CSV not found: {MART_PATH}"
    return pd.read_csv(MART_PATH)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def test_columns_correct(df):
    assert list(df.columns) == EXPECTED_COLUMNS, (
        f"Expected columns {EXPECTED_COLUMNS}, got {list(df.columns)}"
    )

def test_row_count(df):
    assert len(df) == EXPECTED_ROW_COUNT, (
        f"Expected {EXPECTED_ROW_COUNT} rows, got {len(df)}"
    )

def test_no_nulls(df):
    null_counts = df.isnull().sum()
    assert null_counts.sum() == 0, f"Nulls found:\n{null_counts[null_counts > 0]}"

def test_no_empty_strings(df):
    for col in ['counterpart_country', 'flow_type']:
        blanks = (df[col].str.strip() == '').sum()
        assert blanks == 0, f"Empty strings in '{col}': {blanks}"


# ---------------------------------------------------------------------------
# Year
# ---------------------------------------------------------------------------

def test_year_dtype(df):
    assert pd.api.types.is_integer_dtype(df['year']), (
        f"year column should be integer, got {df['year'].dtype}"
    )

def test_year_range(df):
    assert df['year'].min() >= YEAR_MIN, f"year below {YEAR_MIN}: {df['year'].min()}"
    assert df['year'].max() <= YEAR_MAX, f"year above {YEAR_MAX}: {df['year'].max()}"


# ---------------------------------------------------------------------------
# flow_type
# ---------------------------------------------------------------------------

def test_flow_type_single_value(df):
    unique = df['flow_type'].unique()
    assert list(unique) == [EXPECTED_FLOW_TYPE], (
        f"Unexpected flow_type values: {unique}"
    )


# ---------------------------------------------------------------------------
# value_cad_millions
# ---------------------------------------------------------------------------

def test_value_dtype(df):
    assert pd.api.types.is_numeric_dtype(df['value_cad_millions']), (
        f"value_cad_millions should be numeric, got {df['value_cad_millions'].dtype}"
    )

def test_value_not_all_positive(df):
    # Canada runs a net IP deficit — there must be negative values
    assert (df['value_cad_millions'] < 0).any(), "No negative values — something is wrong"

def test_value_not_all_zero(df):
    assert (df['value_cad_millions'] != 0).any(), "All values are zero — something is wrong"


# ---------------------------------------------------------------------------
# Country names
# ---------------------------------------------------------------------------

def test_no_raw_oecd_names(df):
    countries = set(df['counterpart_country'].unique())
    found = [name for name in BANNED_NAMES if name in countries]
    assert not found, f"Raw OECD names not standardised: {found}"

def test_required_names_present(df):
    countries = set(df['counterpart_country'].unique())
    missing = [name for name in REQUIRED_NAMES if name not in countries]
    assert not missing, f"Expected country names missing: {missing}"


# ---------------------------------------------------------------------------
# Duplicates
# ---------------------------------------------------------------------------

def test_no_duplicate_year_country(df):
    dupes = df.duplicated(subset=['year', 'counterpart_country'])
    assert not dupes.any(), (
        f"{dupes.sum()} duplicate (year, counterpart_country) rows found:\n"
        f"{df[dupes][['year', 'counterpart_country']].head(10)}"
    )


# ---------------------------------------------------------------------------
# Spot checks
# ---------------------------------------------------------------------------

def test_usa_has_data_in_2022(df):
    row = df[(df['counterpart_country'] == 'United States') & (df['year'] == 2022)]
    assert len(row) == 1, "Missing USA 2022 row"
    assert row.iloc[0]['value_cad_millions'] < 0, "USA 2022 balance should be negative"

def test_world_present(df):
    world = df[df['counterpart_country'] == 'World']
    assert len(world) > 0, "World aggregate missing from CSV"
