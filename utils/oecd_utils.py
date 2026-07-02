"""
Shared parsing and cleaning logic for OECD SDMX-JSON 2.0 data.

Functions here are used by the staging notebook and unit-tested independently.
"""

import pandas as pd


def parse_sdmx_json(data: dict) -> pd.DataFrame:
    """Parse an OECD SDMX-JSON 2.0 response into a flat DataFrame, one row per observation."""
    # SDMX-JSON 2.0 wraps everything under data.structures / data.dataSets
    d         = data['data']
    structure = d['structures'][0]

    # Build lookup: keyPosition -> {id, values_by_index}
    # keyPosition tells us which slot in the colon-separated key belongs to each dimension.
    dim_lookup: dict[int, dict] = {}
    for dim in structure['dimensions']['observation']:
        pos = dim['keyPosition']
        dim_lookup[pos] = {
            'id':     dim['id'],
            'values': {str(i): v for i, v in enumerate(dim['values'])},
        }
    # Find OBS_STATUS position in the attributes array.
    # Observation array layout: [obs_value, attr_0_index, attr_1_index, ...]
    obs_attrs       = structure.get('attributes', {}).get('observation', [])
    obs_status_pos  = None
    obs_status_map: dict[str, str] = {}
    for i, attr in enumerate(obs_attrs):
        if attr['id'] == 'OBS_STATUS':
            obs_status_pos = i
            obs_status_map = {str(j): v['id'] for j, v in enumerate(attr['values'])}
            break

    dataset = d['dataSets'][0]
    records = []

    for obs_key, obs_values in dataset['observations'].items():
        indices = obs_key.split(':')

        row: dict = {}
        for pos in sorted(dim_lookup.keys()):
            dim = dim_lookup[pos]
            val = dim['values'][indices[pos]]
            row[dim['id']] = val['id']
            # Capture full country name alongside the ISO code for COUNTERPART_AREA
            if dim['id'] == 'COUNTERPART_AREA':
                row['counterpart_country'] = val.get('name', val['id'])

        row['value_cad_millions'] = obs_values[0]

        if obs_status_pos is not None and len(obs_values) > obs_status_pos + 1:
            status_idx        = str(obs_values[obs_status_pos + 1])
            row['obs_status'] = obs_status_map.get(status_idx)

        records.append(row)

    return pd.DataFrame(records)


def clean_ip_charges(df: pd.DataFrame) -> pd.DataFrame:
    """Filter, rename, cast, and sort the parsed IP charges DataFrame for staging."""
    # 1. Keep only the specific IP charges measure, drop parent aggregates
    df = df[df['MEASURE'] == 'SH'].copy()

    # 2. Keep only actual (A) observations; drop estimated (E) or missing (M)
    if 'obs_status' in df.columns:
        df = df[df['obs_status'] == 'A'].copy()

    # 3. Drop rows where the observation value itself is null
    df = df.dropna(subset=['value_cad_millions'])

    # 4 & 5. Rename and select final columns
    df = (
        df
        .rename(columns={'TIME_PERIOD': 'year', 'COUNTERPART_AREA': 'counterpart_area'})
        [['year', 'counterpart_area', 'counterpart_country', 'value_cad_millions']]
        .copy()
    )

    # 6. Cast types
    df['year']               = pd.to_numeric(df['year'], errors='coerce').astype('Int32')
    df['value_cad_millions'] = df['value_cad_millions'].astype('Float64')

    # 7. Sort
    df = df.sort_values(['year', 'counterpart_country']).reset_index(drop=True)

    return df
