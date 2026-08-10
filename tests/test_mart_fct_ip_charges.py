"""
Validates the mart output CSV (fct_ip_charges_yearly.csv) before uploading to RDS.

Run with: pytest tests/test_mart_fct_ip_charges.py -v
All tests must pass before writing to the database.

Wide schema (one row per year x counterpart, gross flows split into columns):
  year, counterpart_country, balance_cad_millions, revenue_cad_millions, expenditure_cad_millions
  balance = credit - debit.  Credit/debit are null for some partner-years
  (partner breakdown starts ~2010; a few cells report only some entries).
"""

import pandas as pd
import pytest
from pathlib import Path

MART_PATH = Path(__file__).parent.parent / 'data' / 'marts' / 'fct_ip_charges_yearly.csv'

EXPECTED_COLUMNS = [
    'year', 'counterpart_country',
    'balance_cad_millions', 'revenue_cad_millions', 'expenditure_cad_millions',
]
VALUE_COLUMNS      = ['balance_cad_millions', 'revenue_cad_millions', 'expenditure_cad_millions']
EXPECTED_ROW_COUNT = 1323   # distinct (year, counterpart); bump on OECD data refresh
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
    "World",           # kept in CSV, mapped to "All countries" at load
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

def test_keys_never_null(df):
    # Structural keys must always be present...
    for col in ['year', 'counterpart_country']:
        assert df[col].isnull().sum() == 0, f"Nulls found in key column '{col}'"

def test_value_columns_not_entirely_null(df):
    # ...but value columns may have gaps (unreported entries); each must still carry data
    for col in VALUE_COLUMNS:
        assert df[col].notna().any(), f"Value column '{col}' is entirely null"

def test_counterpart_country_no_empty_strings(df):
    blanks = (df['counterpart_country'].str.strip() == '').sum()
    assert blanks == 0, f"Empty strings in 'counterpart_country': {blanks}"


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
# Values
# ---------------------------------------------------------------------------

def test_value_dtypes_numeric(df):
    for col in VALUE_COLUMNS:
        assert pd.api.types.is_numeric_dtype(df[col]), (
            f"{col} should be numeric, got {df[col].dtype}"
        )

def test_balance_not_all_positive(df):
    # Canada runs a net IP deficit — there must be negative balances
    assert (df['balance_cad_millions'] < 0).any(), "No negative balances — something is wrong"

def test_balance_not_all_zero(df):
    assert (df['balance_cad_millions'].fillna(0) != 0).any(), "All balances zero — something is wrong"

def test_credit_and_debit_are_non_negative_where_present(df):
    # Gross flows are magnitudes: revenue and expenditure are >= 0
    assert (df['revenue_cad_millions'].dropna() >= 0).all(), "Negative credit (revenue) found"
    assert (df['expenditure_cad_millions'].dropna() >= 0).all(), "Negative debit (expenditure) found"

def test_balance_identity_holds_where_all_present(df):
    # balance = credit - debit for every row where all three are reported
    full = df.dropna(subset=VALUE_COLUMNS)
    diff = (full['balance_cad_millions'] - (full['revenue_cad_millions'] - full['expenditure_cad_millions'])).abs()
    assert (diff <= 1.0).all(), (
        f"balance != credit - debit in {(diff > 1.0).sum()} rows (max diff {diff.max()})"
    )


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

def test_usa_gross_flows_present_2024(df):
    row = df[(df['counterpart_country'] == 'United States') & (df['year'] == 2024)]
    assert len(row) == 1, "Missing USA 2024 row"
    r = row.iloc[0]
    assert r['balance_cad_millions'] < 0, "USA 2024 balance should be negative"
    assert r['revenue_cad_millions'] > 0, "USA 2024 credit (earnings) should be populated and positive"
    assert r['expenditure_cad_millions'] > 0, "USA 2024 debit (payments) should be populated and positive"

def test_world_present(df):
    world = df[df['counterpart_country'] == 'World']
    assert len(world) > 0, "World aggregate missing from CSV"
