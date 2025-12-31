from __future__ import annotations
from pathlib import Path
import duckdb

from country_profile.logging_utils import get_logger
from country_profile.paths import DataPaths

logger = get_logger(__name__)


def _csv_copy(in_path: Path, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    try:
        con.execute(f"""
COPY (SELECT * FROM read_parquet('{in_path.as_posix()}'))
TO '{out_path.as_posix()}'
(FORMAT CSV,
 HEADER,
 DELIMITER ',',
 QUOTE '"',
 ESCAPE '"',
 NULL '',
 FORCE_QUOTE *,
 COMPRESSION GZIP);
""")
        logger.info("[green]Exported[/green] %s", out_path)
        return out_path
    finally:
        con.close()


def export_yearly(paths: DataPaths, in_name: str = 'int_ip_flows.parquet', out_name: str = 'fct_ip_flows_yearly.csv.gz') -> Path:
    in_path  = (paths.int_ip_flows / in_name).resolve()
    out_path = (paths.marts_ip_flows / out_name).resolve()
    if not in_path.exists():
        raise FileNotFoundError(f"Intermediate parquet not found: {in_path}")
    return _csv_copy(in_path, out_path)


def export_yearly_by_class(paths: DataPaths, in_name: str = 'int_ip_flows_by_class.parquet', out_name: str = 'fct_ip_flows_by_class_yearly.csv.gz') -> Path:
    in_path  = (paths.int_ip_flows / in_name).resolve()
    out_path = (paths.marts_ip_flows / out_name).resolve()
    if not in_path.exists():
        raise FileNotFoundError(f"Intermediate parquet not found: {in_path}")
    return _csv_copy(in_path, out_path)
