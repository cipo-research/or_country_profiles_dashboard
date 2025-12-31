from __future__ import annotations
from pathlib import Path
from typing import Dict, List
import pandas as pd

from country_profile.logging_utils import get_logger
from country_profile.paths import DataPaths
from country_profile.config import IND_NAME_TO_ABBR
from country_profile.transforms.wipo_indicators import (
    load_indicator_df, unpivot_indicator_df, rename_indicator_cols, enforce_indicator_schema,
)

logger = get_logger(__name__)


def find_matches(paths: DataPaths) -> Dict[str, List[Path]]:
    return {
        prefix: sorted(paths.raw_ip_indicators.glob(f"{prefix}*.csv"))
        for prefix in IND_NAME_TO_ABBR.keys()
    }


def validate_inputs(matches_map: Dict[str, List[Path]], allow_missing: bool = False) -> None:
    missing_raw = sorted([p for p, files in matches_map.items() if not files])
    duplicates = {p: files for p, files in matches_map.items() if len(files) > 1}

    if duplicates:
        dup_str = '; '.join(f"{k}: [{', '.join(f.name for f in v)}]" for k, v in duplicates.items())
        raise ValueError(f"Duplicate matches per prefix: {dup_str}")

    if missing_raw and not allow_missing:
        raise ValueError("Missing required raw files for prefixes: " + ", ".join(missing_raw))

    if missing_raw and allow_missing:
        logger.warning("[yellow]Proceeding with missing prefixes:[/yellow] %s", ", ".join(missing_raw))


def stage(paths: DataPaths, allow_missing: bool = False) -> None:
    paths.stg_ip_indicators.mkdir(parents=True, exist_ok=True)
    matches_map = find_matches(paths)
    validate_inputs(matches_map, allow_missing=allow_missing)

    prefix_pad = max((len(k) for k in matches_map.keys()), default=0)
    raw_to_stg = {
        prefix: (paths.stg_ip_indicators / f"stg_wipo__{IND_NAME_TO_ABBR[prefix]}.parquet")
        for prefix in IND_NAME_TO_ABBR.keys()
    }

    for prefix, files in matches_map.items():
        if not files:
            continue
        raw_file = files[0]
        out_path = raw_to_stg[prefix]

        raw_df = load_indicator_df(raw_file)
        stg_df = unpivot_indicator_df(raw_df)
        stg_df = rename_indicator_cols(stg_df)
        stg_df = enforce_indicator_schema(stg_df)

        logger.info("Writing DataFrame: %s to %s...", f"{prefix:<{prefix_pad}}", out_path.name)
        stg_df.to_parquet(out_path, compression='snappy', index=False)

    logger.info("[green]Staging complete.[/green]")
