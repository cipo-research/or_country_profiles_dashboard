"""
Unit tests for OECD IP charges ETL logic.

Tests cover parse_sdmx_json(), clean_ip_charges() and pivot_ip_charges_wide()
from utils/oecd_utils.py. All tests are offline -- no real API calls are made.
"""

import unittest
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
import requests

from utils.oecd_utils import (
    clean_ip_charges,
    parse_sdmx_json,
    pivot_ip_charges_wide,
)


# ---------------------------------------------------------------------------
# Minimal SDMX-JSON 2.0 fixture
# ---------------------------------------------------------------------------
# Mirrors the real OECD response but with a handful of observations. Now covers
# all three accounting entries (B, C, D) plus a balance-only counterpart to
# exercise the pre-2009 case where credit/debit do not exist.
#
# Dimension order (keyPosition):
#   0  REF_AREA           CAN
#   1  COUNTERPART_AREA   USA | W
#   2  MEASURE            SH | S | CA
#   3  ACCOUNTING_ENTRY   B | C | D
#   4  FS_ENTRY           T
#   5  FREQ               A
#   6  UNIT_MEASURE       XDC
#   7  ADJUSTMENT         N
#   8  TIME_PERIOD        2022 | 2023
#
# Observation array: [value, obs_status_index]
#   OBS_STATUS: 0 = "A" (actual), 1 = "E" (estimated)

FIXTURE: dict = {
    "data": {
        "structures": [
            {
                "dimensions": {
                    "observation": [
                        {
                            "id": "REF_AREA",
                            "keyPosition": 0,
                            "values": [{"id": "CAN", "name": "Canada"}],
                        },
                        {
                            "id": "COUNTERPART_AREA",
                            "keyPosition": 1,
                            "values": [
                                {"id": "USA", "name": "United States"},
                                {"id": "W",   "name": "World"},
                            ],
                        },
                        {
                            "id": "MEASURE",
                            "keyPosition": 2,
                            "values": [
                                {"id": "SH", "name": "Charges for the use of intellectual property n.i.e."},
                                {"id": "S",  "name": "Services"},
                                {"id": "CA", "name": "Current account"},
                            ],
                        },
                        {
                            "id": "ACCOUNTING_ENTRY",
                            "keyPosition": 3,
                            "values": [
                                {"id": "B", "name": "Balance"},
                                {"id": "C", "name": "Revenue"},
                                {"id": "D", "name": "Expenditure"},
                            ],
                        },
                        {
                            "id": "FS_ENTRY",
                            "keyPosition": 4,
                            "values": [{"id": "T", "name": "Total"}],
                        },
                        {
                            "id": "FREQ",
                            "keyPosition": 5,
                            "values": [{"id": "A", "name": "Annual"}],
                        },
                        {
                            "id": "UNIT_MEASURE",
                            "keyPosition": 6,
                            "values": [{"id": "XDC", "name": "Domestic currency"}],
                        },
                        {
                            "id": "ADJUSTMENT",
                            "keyPosition": 7,
                            "values": [{"id": "N", "name": "Not adjusted"}],
                        },
                        {
                            "id": "TIME_PERIOD",
                            "keyPosition": 8,
                            "values": [
                                {"id": "2022", "name": "2022"},
                                {"id": "2023", "name": "2023"},
                            ],
                        },
                    ]
                },
                "attributes": {
                    "observation": [
                        {
                            "id": "OBS_STATUS",
                            "values": [
                                {"id": "A", "name": "Normal value"},
                                {"id": "E", "name": "Estimated value"},
                            ],
                        }
                    ]
                },
            }
        ],
        "dataSets": [
            {
                "observations": {
                    # key = REF:CPART:MEAS:ACCT:FS:FREQ:UNIT:ADJ:TIME
                    # --- USA, SH, all three entries in 2023 (balance = credit - debit) ---
                    "0:0:0:0:0:0:0:0:1": [-4325.4, 0],   # USA SH Balance     2023
                    "0:0:0:1:0:0:0:0:1": [1500.0,  0],   # USA SH Credit      2023
                    "0:0:0:2:0:0:0:0:1": [5825.4,  0],   # USA SH Debit       2023  (1500 - 5825.4 = -4325.4)
                    # --- USA, SH, balance only in 2022 (pre-gross case: no credit/debit) ---
                    "0:0:0:0:0:0:0:0:0": [-4200.0, 0],   # USA SH Balance     2022
                    # --- World, SH, balance only in 2022 ---
                    "0:1:0:0:0:0:0:0:0": [-3900.0, 0],   # W   SH Balance     2022
                    # --- Parent aggregates (MEASURE != SH) -> must be dropped ---
                    "0:0:1:0:0:0:0:0:1": [-20000.0, 0],  # USA S  Balance     2023
                    "0:0:2:0:0:0:0:0:1": [-50000.0, 0],  # USA CA Balance     2023
                    # --- Estimated observation (OBS_STATUS = E) -> must be dropped ---
                    "0:1:0:0:0:0:0:0:1": [-4000.0, 1],   # W   SH Balance     2023 (estimated)
                }
            }
        ],
    }
}


# ---------------------------------------------------------------------------
# Tests for parse_sdmx_json
# ---------------------------------------------------------------------------

class TestParseSDMXJson(unittest.TestCase):

    def setUp(self):
        self.df = parse_sdmx_json(FIXTURE)

    def test_returns_dataframe(self):
        assert isinstance(self.df, pd.DataFrame)

    def test_row_count_matches_observations(self):
        assert len(self.df) == 8

    def test_expected_columns_present(self):
        for col in ['REF_AREA', 'COUNTERPART_AREA', 'counterpart_country',
                    'MEASURE', 'ACCOUNTING_ENTRY', 'TIME_PERIOD',
                    'value_cad_millions', 'obs_status']:
            assert col in self.df.columns, f"Missing column: {col}"

    def test_ref_area_is_always_can(self):
        assert (self.df['REF_AREA'] == 'CAN').all()

    def test_counterpart_country_name_resolved(self):
        usa_rows = self.df[self.df['COUNTERPART_AREA'] == 'USA']
        assert (usa_rows['counterpart_country'] == 'United States').all()

        world_rows = self.df[self.df['COUNTERPART_AREA'] == 'W']
        assert (world_rows['counterpart_country'] == 'World').all()

    def test_measure_values_include_parent_aggregates(self):
        measures = set(self.df['MEASURE'].unique())
        assert measures == {'SH', 'S', 'CA'}

    def test_accounting_entry_values_include_all_three(self):
        entries = set(self.df['ACCOUNTING_ENTRY'].unique())
        assert entries == {'B', 'C', 'D'}

    def test_obs_status_decoded(self):
        assert set(self.df['obs_status'].unique()) == {'A', 'E'}

    def test_observation_values_correct(self):
        usa_sh_credit_2023 = self.df[
            (self.df['COUNTERPART_AREA'] == 'USA') &
            (self.df['MEASURE'] == 'SH') &
            (self.df['ACCOUNTING_ENTRY'] == 'C') &
            (self.df['TIME_PERIOD'] == '2023')
        ]
        assert len(usa_sh_credit_2023) == 1
        assert usa_sh_credit_2023.iloc[0]['value_cad_millions'] == 1500.0


# ---------------------------------------------------------------------------
# Tests for clean_ip_charges
# ---------------------------------------------------------------------------

class TestCleanIPCharges(unittest.TestCase):

    def setUp(self):
        self.raw = parse_sdmx_json(FIXTURE)
        self.clean = clean_ip_charges(self.raw)

    def test_returns_dataframe(self):
        assert isinstance(self.clean, pd.DataFrame)

    def test_measure_filter_removes_parent_aggregates(self):
        assert 'MEASURE' not in self.clean.columns  # dropped after filter

    def test_obs_status_filter_removes_estimated(self):
        # World has SH Balance in 2022 (A) and 2023 (E); only 2022 should survive
        world_rows = self.clean[self.clean['counterpart_area'] == 'W']
        assert len(world_rows) == 1
        assert world_rows.iloc[0]['year'] == 2022

    def test_final_row_count(self):
        # SH actual rows: USA B/C/D 2023, USA B 2022, W B 2022 = 5
        # Dropped: USA S 2023, USA CA 2023 (MEASURE), W SH 2023 (status E)
        assert len(self.clean) == 5

    def test_output_columns(self):
        assert list(self.clean.columns) == [
            'year', 'counterpart_area', 'counterpart_country',
            'accounting_entry', 'value_cad_millions',
        ]

    def test_accounting_entry_retained(self):
        # The three entries survive for USA 2023
        usa_2023 = self.clean[
            (self.clean['counterpart_area'] == 'USA') & (self.clean['year'] == 2023)
        ]
        assert set(usa_2023['accounting_entry']) == {'B', 'C', 'D'}

    def test_year_cast_to_int32(self):
        assert self.clean['year'].dtype == pd.Int32Dtype()

    def test_value_cast_to_float64(self):
        assert self.clean['value_cad_millions'].dtype == pd.Float64Dtype()

    def test_sorted_by_year_then_country(self):
        years = self.clean['year'].tolist()
        assert years == sorted(years)

    def test_balance_value_preserved_correctly(self):
        usa_2023_balance = self.clean[
            (self.clean['counterpart_area'] == 'USA') &
            (self.clean['year'] == 2023) &
            (self.clean['accounting_entry'] == 'B')
        ]
        assert len(usa_2023_balance) == 1
        assert float(usa_2023_balance.iloc[0]['value_cad_millions']) == pytest.approx(-4325.4)


# ---------------------------------------------------------------------------
# Tests for pivot_ip_charges_wide
# ---------------------------------------------------------------------------

class TestPivotIPChargesWide(unittest.TestCase):

    def setUp(self):
        self.clean = clean_ip_charges(parse_sdmx_json(FIXTURE))
        self.wide = pivot_ip_charges_wide(self.clean)

    def test_output_columns(self):
        assert list(self.wide.columns) == [
            'year', 'counterpart_area', 'counterpart_country',
            'balance_cad_millions', 'revenue_cad_millions', 'expenditure_cad_millions',
        ]

    def test_one_row_per_year_counterpart(self):
        # USA 2023, USA 2022, World 2022 = 3 rows
        assert len(self.wide) == 3
        assert not self.wide.duplicated(subset=['year', 'counterpart_country']).any()

    def test_all_three_entries_pivoted(self):
        usa_2023 = self.wide[
            (self.wide['counterpart_area'] == 'USA') & (self.wide['year'] == 2023)
        ].iloc[0]
        assert float(usa_2023['balance_cad_millions']) == pytest.approx(-4325.4)
        assert float(usa_2023['revenue_cad_millions']) == pytest.approx(1500.0)
        assert float(usa_2023['expenditure_cad_millions']) == pytest.approx(5825.4)

    def test_balance_equals_credit_minus_debit(self):
        usa_2023 = self.wide[
            (self.wide['counterpart_area'] == 'USA') & (self.wide['year'] == 2023)
        ].iloc[0]
        derived = float(usa_2023['revenue_cad_millions']) - float(usa_2023['expenditure_cad_millions'])
        assert derived == pytest.approx(float(usa_2023['balance_cad_millions']))

    def test_pre_gross_rows_keep_balance_but_null_credit_debit(self):
        # USA 2022 and World 2022 have only a balance -> credit/debit must be NA
        usa_2022 = self.wide[
            (self.wide['counterpart_area'] == 'USA') & (self.wide['year'] == 2022)
        ].iloc[0]
        assert float(usa_2022['balance_cad_millions']) == pytest.approx(-4200.0)
        assert pd.isna(usa_2022['revenue_cad_millions'])
        assert pd.isna(usa_2022['expenditure_cad_millions'])


# ---------------------------------------------------------------------------
# Integration-style test: mocked requests.get
# ---------------------------------------------------------------------------

class TestMockedAPIFetch(unittest.TestCase):
    """
    Verify that the fetch -> parse -> clean -> pivot pipeline works end-to-end
    when requests.get is replaced with a mock returning the fixture.
    """

    def _make_mock_response(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = FIXTURE
        mock_resp.raise_for_status.return_value = None
        return mock_resp

    @patch('requests.get')
    def test_full_pipeline_with_mocked_request(self, mock_get):
        mock_get.return_value = self._make_mock_response()

        # Simulate the raw notebook (now fetches C+D+B)
        url     = 'https://sdmx.oecd.org/public/rest/data/OECD.SDD.TPS,DSD_BOP@DF_TIS,1.0/CAN..SH.C+D+B..A.XDC.'
        params  = {'dimensionAtObservation': 'AllDimensions'}
        headers = {'Accept': 'application/vnd.sdmx.data+json'}

        response = requests.get(url, params=params, headers=headers, timeout=60)
        response.raise_for_status()
        data = response.json()

        # Simulate staging + mart
        clean = clean_ip_charges(parse_sdmx_json(data))
        wide  = pivot_ip_charges_wide(clean)

        assert len(clean) == 5
        assert set(clean.columns) == {
            'year', 'counterpart_area', 'counterpart_country',
            'accounting_entry', 'value_cad_millions',
        }
        assert set(wide.columns) == {
            'year', 'counterpart_area', 'counterpart_country',
            'balance_cad_millions', 'revenue_cad_millions', 'expenditure_cad_millions',
        }
        mock_get.assert_called_once()
