from __future__ import annotations

from pathlib import Path
import gc
import re
from typing import List
from pandas._libs.missing import NAType  # type: ignore


import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from country_profile.logging_utils import get_logger
from country_profile.paths import DataPaths
from country_profile.config import (
    DESTINATION_OFFICE, DESTINATION_OFFICE_CODE, ORIGIN,
    YEAR, COUNT,
    CLASS_INDICATORS, CLASS_COL_LABELS,  # e.g. {"tech_field":"Tech field","locarno_class":"Locarno","nice_class":"Nice"}
)

logger = get_logger(__name__)

# ---------------- Target schema & column order (match your notebook order) ----------------
TARGET_FIELDS = [
    (YEAR, pa.int32()),
    (ORIGIN, pa.utf8()),
    (DESTINATION_OFFICE, pa.utf8()),
    (DESTINATION_OFFICE_CODE, pa.utf8()),
    ("ip_indicator", pa.utf8()),
    ("class_type", pa.utf8()),
    ("class_code", pa.utf8()),
    (COUNT, pa.float64()),
]
TARGET_SCHEMA = pa.schema([pa.field(n, t) for n, t in TARGET_FIELDS])
TARGET_COLS = [n for n, _ in TARGET_FIELDS]


# ---------------- Helpers: ST.3, batch iteration, Arrow->pandas ----------------
def _st3_map(paths: DataPaths) -> dict[str, str]:
    st3_fp = paths.stg_offices / "stg_wipo__st3_codes.csv"
    if not st3_fp.exists():
        raise FileNotFoundError(f"Required ST.3 mapping not found: {st3_fp}")
    st3_df = pd.read_csv(st3_fp)
    return dict(zip(st3_df["entity_name"], st3_df["st3_code"]))


def _iter_batches(fp: Path, cols: list[str], batch_size: int = 200_000):
    # Defensive projection + deterministic close
    with pq.ParquetFile(str(fp)) as pf:
        existing = set(pf.schema_arrow.names)
        proj = [c for c in cols if c in existing]
        if not proj:
            raise ValueError(f"No requested columns found in {fp.name}: {cols}")
        for batch in pf.iter_batches(columns=proj, batch_size=batch_size):
            yield pa.Table.from_batches([batch])


def _table_to_pandas_arrow(tbl: pa.Table) -> pd.DataFrame:
    # Keep Arrow-backed dtypes in pandas
    return tbl.to_pandas(types_mapper=pd.ArrowDtype)


# ---------------- Helpers: Nice/Locarno label handling ----------------
def _norm_class_code(s: str | NAType | None) -> str | NAType | None:
    """
    Normalize class codes to a 2-digit form for joining labels:
      'Class 07'/'7'/'07' -> '07'
      keep 'Other' and 'Unknown' literally.
    """
    if pd.isna(s):
        return pd.NA
    s = str(s).strip()
    sl = s.lower()
    if sl.startswith("other"):
        return "Other"
    if sl.startswith("unknown"):
        return "Unknown"
    m = re.search(r"(\d+)", s)
    return f"{int(m.group(1))}" if m else s


def _load_label_xlsx(path: Path, class_type: str) -> pd.DataFrame:
    """
    Excel must contain: 'Class' | 'Industry'
    Returns columns: class_type, class_code_short, class_code_labeled  (e.g. '07', '07 - Hand Tools')
    """
    if not path.exists():
        raise FileNotFoundError(f"Label file not found: {path}")
    df = pd.read_excel(path).convert_dtypes()
    df.columns = [c.strip().lower() for c in df.columns]
    if "class" not in df.columns or "industry" not in df.columns:
        raise ValueError(f"{path.name} must have columns 'Class' and 'Industry'")
    out = pd.DataFrame({
        "class_type": class_type,
        "class_code_short": df["class"].map(_norm_class_code),
        "class_name": df["industry"].astype("string").str.strip(),
    }).dropna(subset=["class_code_short"])
    out["class_code_labeled"] = out["class_code_short"] + " - " + out["class_name"]
    return out[["class_type", "class_code_short", "class_code_labeled"]].reset_index(drop=True)


def _build_label_lookup(paths: DataPaths) -> dict[tuple[str, str], str]:
    """
    Build a mapping: (class_type, 'NN') -> 'NN - Short name' for Nice/Locarno.
    Locates files at: <.../staging/wipo>/ip_classes/{nice,locarno}/*.xlsx
    """
    ip_classes_dir = (paths.stg_ip_indicators.parent / "ip_classes").resolve()
    nice_xlsx = ip_classes_dir / "nice" / "Nice.xlsx"
    loc_xlsx  = ip_classes_dir / "locarno" / "locarno.xlsx"

    logger.info("Loading class labels: %s ; %s", nice_xlsx, loc_xlsx)
    nice = _load_label_xlsx(nice_xlsx, "Nice")
    loc  = _load_label_xlsx(loc_xlsx,  "Locarno")
    dim  = pd.concat([nice, loc], ignore_index=True).convert_dtypes()

    lookup: dict[tuple[str, str], str] = {}
    for ct, code_short, labeled in dim.itertuples(index=False, name=None):
        lookup[(ct, code_short)] = labeled
    return lookup


def _label_tm_id_series(class_type_label: str,
                        s: pd.Series,
                        label_lookup: dict[tuple[str, str], str]) -> pd.Series:
    """
    For TM/ID rows, convert class_code -> 'NN - Short name'.
    Leaves PA (Tech field) values unchanged.
    """
    if class_type_label not in ("Nice", "Locarno"):
        return s

    def _map_one(v):
        code_short = _norm_class_code(v)
        if pd.isna(code_short) or code_short in ("Other", "Unknown"):
            return code_short
        return label_lookup.get((class_type_label, code_short), v)

    out = s.map(_map_one).astype("string[pyarrow]")
    return out


# ---------------- Core transform for a batch ----------------
def _transform_batch_pdf(
    pdf: pd.DataFrame,
    code: str,
    class_col: str,
    st3_map: dict[str, str],
    label_lookup: dict[tuple[str, str], str],
) -> pd.DataFrame:
    pdf = pdf.copy()

    # Normalize 'Total' -> 'World' (case-insensitive)
    if ORIGIN in pdf.columns:
        pdf[ORIGIN] = (
            pdf[ORIGIN]
            .astype("string[pyarrow]")
            .str.strip()
            .str.replace(r"(?i)^total$", "World", regex=True)
        )
    if DESTINATION_OFFICE in pdf.columns:
        pdf[DESTINATION_OFFICE] = (
            pdf[DESTINATION_OFFICE]
            .astype("string[pyarrow]")
            .str.strip()
            .str.replace(r"(?i)^total$", "World", regex=True)
        )

    # Ensure destination ST.3 code (if missing)
    if DESTINATION_OFFICE_CODE not in pdf.columns and DESTINATION_OFFICE in pdf.columns:
        pdf[DESTINATION_OFFICE_CODE] = (
            pdf[DESTINATION_OFFICE]
            .map(st3_map)
            .astype("string[pyarrow]")
        )

    # Add meta columns
    class_type_label = CLASS_COL_LABELS[class_col]  # 'Tech field' | 'Nice' | 'Locarno'
    pdf["ip_indicator"] = pd.Series(code, index=pdf.index, dtype="string[pyarrow]")
    pdf["class_type"] = pd.Series(class_type_label, index=pdf.index, dtype="string[pyarrow]")

    # Rename class column to class_code
    if class_col in pdf.columns and class_col != "class_code":
        pdf = pdf.rename(columns={class_col: "class_code"})

    # Enforce text dtypes
    for c in [ORIGIN, DESTINATION_OFFICE, DESTINATION_OFFICE_CODE, "ip_indicator", "class_type", "class_code"]:
        if c in pdf.columns:
            pdf[c] = pdf[c].astype("string[pyarrow]").str.strip()

    # --- Label TM/ID codes to "NN - Short name"; leave PA as-is
    if "class_code" in pdf.columns:
        pdf["class_code"] = _label_tm_id_series(class_type_label, pdf["class_code"], label_lookup)

    # Cast numerics
    if YEAR in pdf.columns:
        pdf[YEAR] = pd.to_numeric(pdf[YEAR], errors="coerce").astype("Int32")
    if COUNT in pdf.columns:
        pdf[COUNT] = pd.to_numeric(pdf[COUNT], errors="coerce").astype("Float64")

    # Ensure every target column exists
    for col in TARGET_COLS:
        if col not in pdf.columns:
            pdf[col] = pd.NA

    # Fill 'World' ST.3 code for destination (align w/ non-class behavior)
    mask_dest = pdf[DESTINATION_OFFICE].eq("World") & pdf[DESTINATION_OFFICE_CODE].isna()
    pdf.loc[mask_dest, DESTINATION_OFFICE_CODE] = "WD"

    # Exact order
    return pdf[TARGET_COLS]


# ---------------- Pipeline entrypoint ----------------
def build(paths: DataPaths) -> Path:
    st3_map = _st3_map(paths)
    label_lookup = _build_label_lookup(paths)  # (class_type,'NN')->'NN - Short name'

    out_fp = paths.int_ip_flows / "int_ip_flows_by_class.parquet"
    out_fp.parent.mkdir(parents=True, exist_ok=True)
    if out_fp.exists():
        out_fp.unlink()

    writer: pq.ParquetWriter | None = None
    total_rows = 0
    try:
        for code in CLASS_INDICATORS:
            fp = paths.stg_ip_indicators / f"stg_wipo__{code}.parquet"
            if not fp.exists():
                logger.warning("Missing staged parquet for %s: %s", code, fp)
                continue

            # Discover which classification column this indicator has
            with pq.ParquetFile(str(fp)) as pf:
                schema_names = set(pf.schema_arrow.names)
            class_col = next((c for c in CLASS_COL_LABELS.keys() if c in schema_names), None)
            if class_col is None:
                raise ValueError(f"No classification column found in {code} at {fp}")

            base_cols = [DESTINATION_OFFICE, DESTINATION_OFFICE_CODE, ORIGIN, YEAR, COUNT]
            cols = [c for c in base_cols + [class_col] if c in schema_names]

            logger.info("Loading %s", fp.name)

            # Tune batch_size if memory is tight
            for tbl in _iter_batches(fp, cols, batch_size=200_000):
                pdf = _table_to_pandas_arrow(tbl)
                pdf = _transform_batch_pdf(pdf, code, class_col, st3_map, label_lookup)

                # Convert back to Arrow with target schema
                atbl = pa.Table.from_pandas(pdf, schema=TARGET_SCHEMA, preserve_index=False)

                # Lazily create writer with schema on first batch
                if writer is None:
                    writer = pq.ParquetWriter(str(out_fp), schema=TARGET_SCHEMA, compression="snappy")

                # Keep stable row group sizes for nicer scans
                writer.write_table(atbl, row_group_size=200_000)
                total_rows += atbl.num_rows

                # free memory
                del pdf, atbl, tbl
                gc.collect()

        if writer is None:
            raise FileNotFoundError("No class indicators found in staging. Expected PA5, TM4a/b, ID4a/b.")
    finally:
        if writer is not None:
            writer.close()

    logger.info("[green]Wrote[/green] %s (rows=%d)", out_fp, total_rows)
    return out_fp
