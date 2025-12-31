from __future__ import annotations
from pathlib import Path
import pandas as pd
from typing import Dict

from country_profile.logging_utils import get_logger
from country_profile.paths import DataPaths
from country_profile.config import (
    DESTINATION_OFFICE, DESTINATION_OFFICE_CODE, ORIGIN, ORIGIN_CODE,
    YEAR, COUNT, TARGET_INDICATORS,
)

logger = get_logger(__name__)


def _load_staged_indicators(paths: DataPaths) -> Dict[str, pd.DataFrame]:
    dfs: Dict[str, pd.DataFrame] = {}
    for fp in paths.stg_ip_indicators.glob("stg_wipo__*.parquet"):
        abbr = fp.stem.split("__")[1]
        if abbr in TARGET_INDICATORS:
            logger.info("Loading %-24s", fp.name)
            dfs[abbr] = pd.read_parquet(fp, engine="pyarrow", dtype_backend="pyarrow")
    return dfs


def _maybe_read_china_tm(paths: DataPaths) -> pd.DataFrame | None:
    cn_fp = paths.stg_china / 'stg_china__tm_filings.csv'
    if not cn_fp.exists():
        logger.warning("[yellow]Chinese TM enrichment skipped[/yellow] — %s not found", cn_fp)
        return None
    df = (pd.read_csv(cn_fp)
            .rename(columns={'region': ORIGIN})
            .drop_duplicates()
            .convert_dtypes())
    df[DESTINATION_OFFICE] = 'China'
    df[DESTINATION_OFFICE_CODE] = 'CN'
    return df


def _insert_chinese_tm(ip_indicator: str, dfs: Dict[str, pd.DataFrame], china_tm_df: pd.DataFrame) -> pd.DataFrame:
    if ip_indicator == 'TM1a':
        app_col = 'direct_apps'
    elif ip_indicator == 'TM1b':
        app_col = 'madrid_apps'
    else:
        raise ValueError("Indicator must be TM1a or TM1b")

    china_cols = [YEAR, ORIGIN, DESTINATION_OFFICE, DESTINATION_OFFICE_CODE, app_col]
    china_df = china_tm_df[china_cols].copy()

    tm_df = dfs[ip_indicator].copy()
    tm_df = tm_df.merge(
        china_df,
        on=[YEAR, ORIGIN, DESTINATION_OFFICE, DESTINATION_OFFICE_CODE],
        how='left'
    )
    tm_total = tm_df[[COUNT, app_col]].sum(axis=1, min_count=1)
    tm_df[COUNT] = (tm_total
        .where(tm_df[COUNT].notna() | (tm_total > 0))
        .astype('Int64'))
    tm_df = tm_df.drop(columns=app_col).drop_duplicates()
    return tm_df[[YEAR, ORIGIN, DESTINATION_OFFICE, DESTINATION_OFFICE_CODE, COUNT]]


def build(paths: DataPaths) -> Path:
    dfs = _load_staged_indicators(paths)

    china_tm_df = _maybe_read_china_tm(paths)
    if china_tm_df is not None:
        for ind in ('TM1a', 'TM1b'):
            if ind in dfs:
                dfs[ind] = _insert_chinese_tm(ind, dfs, china_tm_df)

    # Replace 'Total' -> 'World'
    for k, df in dfs.items():
        if ORIGIN in df.columns and DESTINATION_OFFICE in df.columns:
            df[[ORIGIN, DESTINATION_OFFICE]] = df[[ORIGIN, DESTINATION_OFFICE]].replace({'Total': 'World'})
            dfs[k] = df

    # ST.3 codes mapping
    st3_fp = paths.stg_offices / 'stg_wipo__st3_codes.csv'
    if not st3_fp.exists():
        raise FileNotFoundError(f"Required ST.3 mapping not found: {st3_fp}")
    st3_df = pd.read_csv(st3_fp)
    st3_map = dict(zip(st3_df['entity_name'], st3_df['st3_code']))

    # Ensure codes
    updated: Dict[str, pd.DataFrame] = {}
    for ind, df in dfs.items():
        if ORIGIN_CODE not in df.columns and ORIGIN in df.columns:
            df = df.assign(**{ORIGIN_CODE: pd.Series(df[ORIGIN].map(st3_map), dtype='string')})
        if DESTINATION_OFFICE_CODE not in df.columns and DESTINATION_OFFICE in df.columns:
            df = df.assign(**{DESTINATION_OFFICE_CODE: pd.Series(df[DESTINATION_OFFICE].map(st3_map), dtype='string')})
        updated[ind] = df

    # Concatenate long
    long_df = (pd.concat(updated, names=['indicator'])
                 .reset_index(level=0)
                 .rename(columns={'level_0': 'indicator'}))

    # Cast types (column-wise, not DataFrame.apply)
    text_cols = [ORIGIN, ORIGIN_CODE, DESTINATION_OFFICE, DESTINATION_OFFICE_CODE, 'indicator']
    for c in text_cols:
        if c in long_df.columns:
            long_df[c] = long_df[c].astype('string[pyarrow]').str.strip()
    long_df[YEAR]  = pd.to_numeric(long_df[YEAR], errors='coerce').astype('Int32')
    long_df[COUNT] = pd.to_numeric(long_df[COUNT], errors='coerce').astype('Float64')

    # Fill 'World' ST.3 codes
    origin_world_mask = long_df[ORIGIN].eq('World') & long_df[ORIGIN_CODE].isna()
    dest_world_mask   = long_df[DESTINATION_OFFICE].eq('World') & long_df[DESTINATION_OFFICE_CODE].isna()
    long_df.loc[origin_world_mask, ORIGIN_CODE] = 'WD'
    long_df.loc[dest_world_mask,   DESTINATION_OFFICE_CODE] = 'WD'

    col_order = [YEAR, ORIGIN, ORIGIN_CODE, DESTINATION_OFFICE, DESTINATION_OFFICE_CODE, 'indicator', COUNT]
    long_df = long_df[col_order].reset_index(drop=True)

    out_fp = paths.int_ip_flows / 'int_ip_flows.parquet'
    long_df.to_parquet(out_fp, index=False)
    logger.info("[green]Wrote[/green] %s (rows=%d)", out_fp, len(long_df))
    return out_fp
