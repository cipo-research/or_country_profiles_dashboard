"""
Unit tests for the fact_yearly load rules in models/load/load_rds__wipo_ip_flows.py.

split_yearly() decides, for each row of the WIPO extract, whether it updates an
existing fact_yearly row, is inserted, is skipped to avoid double counting, or
(trademarks into China) is summed into a 'total' row.
All tests are offline: small hand-built tables, no database connection.
"""

import numpy as np
import pandas as pd
import pytest

from models.load.load_rds__wipo_ip_flows import split_yearly

# Surrogate IDs used in the fixtures (values are arbitrary, only their roles matter)
WORLD, CANADA, USA_ORIGIN = 1, 2, 3            # dim_origin
CHINA, USA_OFFICE = 10, 11                      # dim_destination
PA1A, PA3, TM1A, TM1B, TOTAL = 6, 10, 11, 12, 16  # dim_indicator

# RDS holds Chinese 'total' data for 2023-2024 in these fixtures
RULES = dict(world_id=WORLD, pa3_id=PA3, china_id=CHINA, china_tm_ids={TM1A, TM1B},
             total_id=TOTAL, china_total_years={2023, 2024})

CUR_COLS = ["id", "year", "origin", "indicator", "destination_office", "count"]
NEW_COLS = ["year", "origin", "indicator", "destination_office", "office", "count"]


def existing(*rows):
    return pd.DataFrame(rows, columns=CUR_COLS)


def extract(*rows):
    return pd.DataFrame(rows, columns=NEW_COLS)


def run(new, cur, **overrides):
    """Returns (skipped, derived_total, updates, inserts)."""
    skipped, derived, plan = split_yearly(new, cur, **{**RULES, **overrides})
    return skipped, derived, plan[plan.action == "update"], plan[plan.action == "insert"]


# --- update / insert / unchanged ------------------------------------------------

def test_unchanged_value_is_neither_updated_nor_inserted():
    cur = existing((100, 2024, CANADA, PA1A, USA_OFFICE, 10662.0))
    new = extract((2024, CANADA, PA1A, USA_OFFICE, "United States of America", 10662.0))
    skipped, _, updates, inserts = run(new, cur)
    assert skipped.empty and updates.empty and inserts.empty


def test_revised_value_updates_the_existing_row():
    cur = existing((100, 2023, CANADA, PA1A, USA_OFFICE, 9771.0))
    new = extract((2023, CANADA, PA1A, USA_OFFICE, "United States of America", 9990.0))
    _, _, updates, inserts = run(new, cur)
    assert inserts.empty
    assert updates[["id", "count", "count_rds"]].values.tolist() == [[100, 9990.0, 9771.0]]


def test_empty_existing_row_is_filled():
    cur = existing((100, 2022, CANADA, PA1A, USA_OFFICE, np.nan))
    new = extract((2022, CANADA, PA1A, USA_OFFICE, "United States of America", 42.0))
    _, _, updates, inserts = run(new, cur)
    assert inserts.empty
    assert updates["id"].tolist() == [100] and updates["count_rds"].isna().all()


def test_new_year_is_inserted():
    cur = existing((100, 2024, CANADA, PA1A, USA_OFFICE, 10662.0))
    new = extract((2025, CANADA, PA1A, USA_OFFICE, "United States of America", 10447.0))
    _, _, updates, inserts = run(new, cur)
    assert updates.empty
    assert inserts[["year", "count"]].values.tolist() == [[2025, 10447.0]]


def test_existing_rows_absent_from_extract_are_never_touched():
    # e.g. Chinese 'total' rows or legacy indicators: not in the extract, so no update and no delete
    cur = existing((100, 2024, CANADA, PA1A, USA_OFFICE, 10662.0),
                   (101, 2019, USA_ORIGIN, PA1A, USA_OFFICE, 285000.0),
                   (102, 2024, CANADA, TOTAL, CHINA, 2867.0))
    new = extract((2024, CANADA, PA1A, USA_OFFICE, "United States of America", 10700.0))
    _, _, updates, _ = run(new, cur)
    assert updates["id"].tolist() == [100]


# --- trademarks into China --------------------------------------------------------

def test_china_trademarks_skipped_in_years_with_chinese_total():
    cur = existing((102, 2024, CANADA, TOTAL, CHINA, 2867.0))
    new = extract((2024, CANADA, TM1A, CHINA, "China", 0.0),
                  (2024, CANADA, TM1B, CHINA, "China", 201.0))
    skipped, derived, updates, inserts = run(new, cur)
    assert len(skipped) == 2 and derived.empty and updates.empty and inserts.empty


def test_china_trademarks_after_chinese_total_are_stored_as_total():
    new = extract((2025, CANADA, TM1A, CHINA, "China", 2094.0),
                  (2025, CANADA, TM1B, CHINA, "China", 245.0),
                  (2025, USA_ORIGIN, TM1B, CHINA, "China", 900.0))  # Madrid only
    skipped, derived, updates, inserts = run(new, existing())
    assert skipped.empty and updates.empty
    got = inserts[["year", "origin", "indicator", "destination_office", "count"]].values.tolist()
    assert sorted(got) == [[2025, CANADA, TOTAL, CHINA, 2339.0], [2025, USA_ORIGIN, TOTAL, CHINA, 900.0]]
    assert len(derived) == 2


def test_china_trademarks_before_chinese_total_stay_as_tm1a_tm1b():
    new = extract((2013, CANADA, TM1A, CHINA, "China", 1500.0),
                  (2013, CANADA, TM1B, CHINA, "China", 300.0))
    skipped, derived, _, inserts = run(new, existing(), china_total_years={2014, 2024})
    assert skipped.empty and derived.empty
    assert sorted(inserts["indicator"].tolist()) == [TM1A, TM1B]


def test_existing_total_year_is_left_alone_on_a_rerun():
    # 2025 'total' already in RDS (from an earlier load or the Chinese data): 2025 now counts as a 'total' year
    cur = existing((103, 2025, CANADA, TOTAL, CHINA, 2339.0))
    new = extract((2025, CANADA, TM1A, CHINA, "China", 2100.0),
                  (2025, CANADA, TM1B, CHINA, "China", 245.0))
    skipped, derived, updates, inserts = run(new, cur, china_total_years={2023, 2024, 2025})
    assert len(skipped) == 2 and derived.empty and updates.empty and inserts.empty


def test_without_any_chinese_total_china_trademarks_stay_as_tm1a_tm1b():
    new = extract((2025, CANADA, TM1A, CHINA, "China", 2094.0))
    skipped, derived, _, inserts = run(new, existing(), china_total_years=set())
    assert skipped.empty and derived.empty and inserts["indicator"].tolist() == [TM1A]


def test_china_rule_only_applies_to_trademarks_into_china():
    new = extract((2024, CANADA, PA1A, CHINA, "China", 341.0),                          # patents into China
                  (2024, CANADA, TM1B, USA_OFFICE, "United States of America", 16.0))  # TM into another office
    skipped, derived, _, inserts = run(new, existing())
    assert skipped.empty and derived.empty and len(inserts) == 2


# --- PA3 (patents in force) ---------------------------------------------------------

def test_pa3_skipped_in_years_stored_by_origin_and_loaded_otherwise():
    cur = existing((200, 2023, CANADA, PA3, USA_OFFICE, 50000.0),   # 2023 stored by origin country
                   (201, 2024, WORLD, PA3, USA_OFFICE, 3300000.0))  # 2024 stored as office total
    new = extract((2023, WORLD, PA3, USA_OFFICE, "United States of America", 3200000.0),
                  (2024, WORLD, PA3, USA_OFFICE, "United States of America", 3310000.0),
                  (2025, WORLD, PA3, USA_OFFICE, "United States of America", 3400000.0))
    skipped, _, updates, inserts = run(new, cur)
    assert skipped["year"].tolist() == [2023]
    assert updates["id"].tolist() == [201]
    assert inserts["year"].tolist() == [2025]


# --- duplicate keys already in RDS --------------------------------------------------

def test_duplicate_existing_rows_for_a_loaded_key_stop_the_load():
    cur = existing((100, 2024, CANADA, PA1A, USA_OFFICE, 10.0),
                   (101, 2024, CANADA, PA1A, USA_OFFICE, 20.0))
    new = extract((2024, CANADA, PA1A, USA_OFFICE, "United States of America", 30.0))
    with pytest.raises(AssertionError, match="more than one existing"):
        run(new, cur)


def test_duplicate_existing_rows_in_a_skipped_slice_are_ignored():
    # RDS has duplicate China trademark rows for 2014/2016; they sit in a 'total' year, so are skipped
    cur = existing((100, 2024, CANADA, TM1A, CHINA, 156.0),
                   (101, 2024, CANADA, TM1A, CHINA, 105.0))
    new = extract((2024, CANADA, TM1A, CHINA, "China", 300.0))
    skipped, _, updates, inserts = run(new, cur)
    assert len(skipped) == 1 and updates.empty and inserts.empty
