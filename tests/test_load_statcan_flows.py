"""
Unit tests for the load rules in models/load/load_rds__statcan_flows.py.

split_rows() decides, for each row of a StatCan mart, whether it updates an existing
fact row, is inserted, or is left as is; read_mart() drops the rows RDS does not store.
All tests are offline: small hand-built tables, no database connection.
"""

import numpy as np
import pandas as pd
import pytest

from models.load.load_rds__statcan_flows import read_mart, split_rows

# Surrogate IDs used in the fixtures (values are arbitrary, only their roles matter)
EXPORTS, IMPORTS = 1, 2           # dim_naic_trade_type
USA, MEXICO = 220, 130            # dim_naic_trading_partner
AEROSPACE, FOOD = 1, 5            # dim_naics

KEY = ["year", "trade_type", "trading_partner", "naics_id"]
COLS = KEY + ["cad_value"]


def rows(*values):
    return pd.DataFrame(values, columns=COLS)


def run(new, cur):
    """Returns (updates, inserts, unchanged)."""
    plan = split_rows(new, cur, KEY, "cad_value")
    return tuple(plan[plan.action == a] for a in ("update", "insert", "unchanged"))


# --- update / insert / unchanged ------------------------------------------------

def test_unchanged_value_is_neither_updated_nor_inserted():
    cur = rows((2024, EXPORTS, USA, AEROSPACE, 1_500_000.0))
    updates, inserts, unchanged = run(rows((2024, EXPORTS, USA, AEROSPACE, 1_500_000.0)), cur)
    assert updates.empty and inserts.empty and len(unchanged) == 1


def test_floating_point_noise_is_not_a_revision():
    cur = rows((2024, EXPORTS, USA, AEROSPACE, 1_234_500_000.0))
    updates, inserts, _ = run(rows((2024, EXPORTS, USA, AEROSPACE, 1_234.5 * 10 ** 6 + 1e-6)), cur)
    assert updates.empty and inserts.empty


def test_revised_value_updates_the_existing_row():
    cur = rows((2023, EXPORTS, USA, AEROSPACE, 1_500_000.0))
    updates, inserts, _ = run(rows((2023, EXPORTS, USA, AEROSPACE, 1_520_000.0)), cur)
    assert inserts.empty
    assert updates[["cad_value", "cad_value_rds"]].values.tolist() == [[1_520_000.0, 1_500_000.0]]


def test_empty_existing_row_is_filled():
    cur = rows((2022, IMPORTS, MEXICO, FOOD, np.nan))
    updates, inserts, _ = run(rows((2022, IMPORTS, MEXICO, FOOD, 42_000.0)), cur)
    assert inserts.empty and len(updates) == 1 and updates["cad_value_rds"].isna().all()


def test_partial_year_in_rds_is_completed_by_the_next_load():
    # RDS holds January-August 2025; the refresh brings the full year
    cur = rows((2025, EXPORTS, USA, AEROSPACE, 8_000_000.0))
    updates, inserts, _ = run(rows((2025, EXPORTS, USA, AEROSPACE, 12_000_000.0)), cur)
    assert inserts.empty and updates["cad_value"].tolist() == [12_000_000.0]


def test_new_year_and_new_partner_are_inserted():
    cur = rows((2025, EXPORTS, USA, AEROSPACE, 12_000_000.0))
    new = rows((2026, EXPORTS, USA, AEROSPACE, 9_000_000.0),      # new (partial) year
               (2025, EXPORTS, MEXICO, AEROSPACE, 300_000.0))     # new key in an existing year
    updates, inserts, _ = run(new, cur)
    assert updates.empty
    assert sorted(inserts[["year", "trading_partner"]].values.tolist()) == [[2025, MEXICO], [2026, USA]]


def test_key_includes_every_dimension():
    # same year, partner and industry but a different trade type is a different row
    cur = rows((2024, EXPORTS, USA, FOOD, 100.0))
    updates, inserts, _ = run(rows((2024, IMPORTS, USA, FOOD, 100.0)), cur)
    assert updates.empty and inserts["trade_type"].tolist() == [IMPORTS]


def test_existing_rows_absent_from_the_mart_are_never_touched():
    cur = rows((2024, EXPORTS, USA, AEROSPACE, 1_500_000.0),
               (2010, IMPORTS, MEXICO, FOOD, 7_000.0))
    plan = split_rows(rows((2024, EXPORTS, USA, AEROSPACE, 1_600_000.0)), cur, KEY, "cad_value")
    assert plan[KEY].values.tolist() == [[2024, EXPORTS, USA, AEROSPACE]]


def test_duplicate_existing_rows_for_a_loaded_key_stop_the_load():
    cur = rows((2024, EXPORTS, USA, AEROSPACE, 10.0),
               (2024, EXPORTS, USA, AEROSPACE, 20.0))
    with pytest.raises(AssertionError, match="more than one existing"):
        run(rows((2024, EXPORTS, USA, AEROSPACE, 30.0)), cur)


def test_works_for_the_macroeconomic_flows_key():
    cur = pd.DataFrame([(2024, 1, 4, 683.8e9)], columns=["year", "region", "flow_type", "dollar_value"])
    new = pd.DataFrame([(2024, 1, 4, 683.6e9), (2025, 1, 4, 737.3e9)],
                       columns=["year", "region", "flow_type", "dollar_value"])
    plan = split_rows(new, cur, ["year", "region", "flow_type"], "dollar_value")
    assert plan["action"].tolist() == ["update", "insert"]


# --- rows RDS does not store --------------------------------------------------------

def test_trade_mart_drops_totals_unknown_partner_and_null_values(tmp_path):
    pd.DataFrame({
        "year": [2025, 2025, 2025, 2025, 2025],
        "trade_type": ["Exports"] * 5,
        "trading_partner": ["United States", "United States", "Unknown or unspecified", "Mexico", " Mexico "],
        "naics_code": [3364.0, np.nan, 3364.0, 3364.0, 3111.0],
        "naics_name": ["Aerospace product and parts manufacturing", "Total",
                       "Aerospace product and parts manufacturing",
                       "Aerospace product and parts manufacturing", "Animal food manufacturing"],
        "cad_value": [5.0, 9.0, 1.0, np.nan, 2.0],
    }).to_parquet(tmp_path / "fct_trade_by_naics_yearly.parquet")
    df = read_mart("fact_trade_by_naics", tmp_path)
    assert df[["trading_partner", "naics_code", "cad_value"]].values.tolist() == [
        ["United States", 3364, 5.0], ["Mexico", 3111, 2.0]]


def test_duplicate_keys_in_a_mart_stop_the_load(tmp_path):
    pd.DataFrame({"year": [2024, 2024], "region": ["Canada", "Canada"],
                  "flow_type": ["Exports to region"] * 2, "dollar_value": [1.0, 2.0]}
                 ).to_csv(tmp_path / "fct_macroecon_flows_yearly.csv", index=False)
    with pytest.raises(AssertionError, match="duplicate keys"):
        read_mart("fact_macroecon_flows", tmp_path)
