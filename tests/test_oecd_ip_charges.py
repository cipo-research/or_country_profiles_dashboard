"""
Unit tests for OECD IP charges ETL logic.

Tests cover parse_sdmx_json() and clean_ip_charges() from utils/oecd_utils.py.
All tests are offline — no real API calls are made.
"""

import json
import unittest
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
import requests

from utils.oecd_utils import clean_ip_charges, parse_sdmx_json


# ---------------------------------------------------------------------------
# Minimal SDMX-JSON 2.0 fixture
# ---------------------------------------------------------------------------
# This mirrors the real OECD API response structure but with only a handful
# of observations to keep the tests fast and readable.
#
# Dimension order (keyPosition):
#   0  REF_AREA           CAN
#   1  COUNTERPART_AREA   USA | W
#   2  MEASURE            SH | S | CA
#   3  ACCOUNTING_ENTRY   B
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
                            "values": [{"id": "B", "name": "Balance"}],
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
                    # REF_AREA=CAN, COUNTERPART=USA, MEASURE=SH, ..., 2022 → -4200.0, status=A
                    "0:0:0:0:0:0:0:0:0": [-4200.0, 0],
                    # REF_AREA=CAN, COUNTERPART=USA, MEASURE=SH, ..., 2023 → -4325.4, status=A
                    "0:0:0:0:0:0:0:0:1": [-4325.4, 0],
                    # REF_AREA=CAN, COUNTERPART=W, MEASURE=SH, ..., 2022 → -3900.0, status=A
                    "0:1:0:0:0:0:0:0:0": [-3900.0, 0],
                    # REF_AREA=CAN, COUNTERPART=USA, MEASURE=S (parent aggregate), 2023
                    "0:0:1:0:0:0:0:0:1": [-20000.0, 0],
                    # REF_AREA=CAN, COUNTERPART=USA, MEASURE=CA (grandparent aggregate), 2023
                    "0:0:2:0:0:0:0:0:1": [-50000.0, 0],
                    # REF_AREA=CAN, COUNTERPART=W, MEASURE=SH, 2023 → estimated, should be dropped
                    "0:1:0:0:0:0:0:0:1": [-4000.0, 1],
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
        assert len(self.df) == 6

    def test_expected_columns_present(self):
        for col in ['REF_AREA', 'COUNTERPART_AREA', 'counterpart_country',
                    'MEASURE', 'TIME_PERIOD', 'value_cad_millions', 'obs_status']:
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

    def test_obs_status_decoded(self):
        # Index 0 → 'A', index 1 → 'E'
        assert set(self.df['obs_status'].unique()) == {'A', 'E'}

    def test_observation_values_correct(self):
        usa_sh_2023 = self.df[
            (self.df['COUNTERPART_AREA'] == 'USA') &
            (self.df['MEASURE'] == 'SH') &
            (self.df['TIME_PERIOD'] == '2023')
        ]
        assert len(usa_sh_2023) == 1
        assert usa_sh_2023.iloc[0]['value_cad_millions'] == -4325.4


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
        # Fixture has 6 obs: 3 SH, 1 S, 1 CA → only SH rows kept; also 1 SH is estimated
        assert 'MEASURE' not in self.clean.columns  # dropped after filter
        # S and CA rows should all be gone

    def test_obs_status_filter_removes_estimated(self):
        # World/2023 SH obs has status=E → should be dropped
        world_rows = self.clean[self.clean['counterpart_area'] == 'W']
        # Only 2022 row (status=A) should survive; 2023 (status=E) is dropped
        assert len(world_rows) == 1
        assert world_rows.iloc[0]['year'] == 2022

    def test_final_row_count(self):
        # 3 SH actual rows survive: USA/2022, USA/2023, W/2022
        # Dropped: USA S/2023 and USA CA/2023 (MEASURE filter), W SH/2023 (status=E)
        assert len(self.clean) == 3

    def test_output_columns(self):
        assert list(self.clean.columns) == [
            'year', 'counterpart_area', 'counterpart_country', 'value_cad_millions'
        ]

    def test_year_cast_to_int32(self):
        assert self.clean['year'].dtype == pd.Int32Dtype()

    def test_value_cast_to_float64(self):
        assert self.clean['value_cad_millions'].dtype == pd.Float64Dtype()

    def test_sorted_by_year_then_country(self):
        years = self.clean['year'].tolist()
        assert years == sorted(years)

    def test_value_preserved_correctly(self):
        usa_2023 = self.clean[
            (self.clean['counterpart_area'] == 'USA') &
            (self.clean['year'] == 2023)
        ]
        assert len(usa_2023) == 1
        assert float(usa_2023.iloc[0]['value_cad_millions']) == pytest.approx(-4325.4)


# ---------------------------------------------------------------------------
# Integration-style test: mocked requests.get
# ---------------------------------------------------------------------------

class TestMockedAPIFetch(unittest.TestCase):
    """
    Verify that the fetch → parse → clean pipeline works end-to-end
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

        # Simulate what the raw notebook does
        url     = 'https://sdmx.oecd.org/public/rest/data/OECD.SDD.TPS,DSD_BOP@DF_TIS,1.0/CAN..SH.B..A.XDC.'
        params  = {'dimensionAtObservation': 'AllDimensions'}
        headers = {'Accept': 'application/vnd.sdmx.data+json'}

        response = requests.get(url, params=params, headers=headers, timeout=60)
        response.raise_for_status()
        data = response.json()

        # Simulate staging notebook
        df    = parse_sdmx_json(data)
        clean = clean_ip_charges(df)

        assert len(clean) == 3
        assert set(clean.columns) == {
            'year', 'counterpart_area', 'counterpart_country', 'value_cad_millions'
        }
        mock_get.assert_called_once()
