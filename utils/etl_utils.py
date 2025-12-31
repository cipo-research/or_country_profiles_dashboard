"""
Shared helper/utility functions for ETL pipeline

If having all utility functions in one place becomes unmanageable, then
separate it into separate scripts by category. For example, move StatCan
API functions to a new file `statcan_utils.py`.
"""

from http import HTTPStatus
from pathlib import Path
from typing import Optional
from zipfile import ZipFile, BadZipFile

import pandas as pd
import pyarrow as pa
import pyarrow.csv as pv
import pyarrow.parquet as pq
import requests


REPO_NAME = 'or_country_profiles'

# ------------------------
# Directory & file helpers
# ------------------------

def get_repo_root(start: Path = Path.cwd(), repo_name: str = REPO_NAME) -> Path:
    """
    Find the Path to the repo folder by walking up the file directory 
    from a given path.
    """
    p = start.resolve()
    if p.is_file():
        p = p.parent

    while True:
        if p.name == repo_name:
            return p
        if p.parent == p:  # reached filesystem root
            raise FileNotFoundError(
                f"Ancestor named '{repo_name}' not found from {start!s}"
            )
        p = p.parent


def extract_zip_file(zip_path: Path | str, out_file_prefix: str | None) -> None:
    """
    Extracts all contents of the given ZIP file to its parent directory.
    """
    if isinstance(zip_path, str):
        zip_path = Path(zip_path)

    target_path: Path = zip_path.parent

    print(f'Extracting {zip_path.name}... ', end='')
    try:
        with ZipFile(zip_path) as zf:
            # Test for corrupt files in .zip file
            bad_member = zf.testzip()
            if bad_member is not None:
                raise BadZipFile(
                    # Note: `!s` is a conversion flag.
                    #       `{zip_path!s}` == `{str(zip_path)}`
                    f'Corrupt archive {zip_path!s}: first bad member: "{bad_member}"'
                )

            # All good, proceed to extraction
            # Keep original name if no assigned out_file_prefix
            if not out_file_prefix:
                zf.extractall(path=target_path)

            # Alter extracted filenames so they have the assigned out_file_prefix
            else:
                for member in zf.infolist():
                    # Skip directories
                    if member.is_dir():
                        continue

                    # Read data for each file in zipfile
                    file_data = zf.read(member.filename)

                    # Construct new Path with prefix
                    # Also handles files in subdirectories in the zip file
                    original_member_path = Path(member.filename)
                    new_filename = f'{out_file_prefix}{original_member_path.name}'
                    new_path = target_path / original_member_path.parent / new_filename

                    # Check destination dir exists; don't overwrite anything
                    new_path.parent.mkdir(parents=True, exist_ok=True)

                    # Extract zip member's data into a file with the assigned out_file_prefix
                    with open(new_path, 'wb') as f:
                        f.write(file_data)

            print('Done!')

    # Error handling
    except BadZipFile as e:
        raise RuntimeError(f'Extraction failed for {zip_path!s}: {e}') from e
    except FileNotFoundError as e:
        raise FileNotFoundError(f'ZIP file does not exist: {zip_path!s}: {e}') from e


def extract_zip_csv_to_parquet(
    zip_path:     str | Path,
    out_parquet:  str | Path,
    *,
    csv_member:   str | None = None,  # if None, use first *.csv in the zip
    column_types: dict[str, pa.DataType] | None = None,  # optional schema
    delimiter:    str = ",",
    compression:  str = "snappy",  # "zstd" compresses smaller, a bit slower
    block_size:   int = 256 << 20,  # 256 MB read blocks
    ) -> None:
    """
    Write the data from CSV that's compressed in a ZIP file to Parquet.
    
    This function streams the CSV inside a ZIP and writes it to Parquet
    incrementally. Useful when the uncompressed CSV's filesize is too
    large to load into RAM.
    
    TODO
    ----
    This function is slow and single-threaded. Make it multi-threaded to
    improve performance.

    Dependencies
    ------------
    - pathlib
    - zipfile

    - pyarrow as pa
    - pyarrow.csv as pv
    - pyarrow.parquet as pq

    Usage Example
    -------------
    extract_zip_csv_to_parquet(
        zip_path='data/big_dump.zip',
        out_parquet='data/big_dump.parquet',
        csv_member='path/in/zip/yourfile.csv',  # only if the zip has multiple CSVs
        column_types={'id': pa.int64(),
                      'ts': pa.timestamp('ns'),
                      'value': pa.float64()},
        compression='zstd',  # 'snappy' for fastest writes
    )
    """
    zip_path = Path(zip_path)
    out_parquet = Path(out_parquet)

    print('Reading zip file...')
    with ZipFile(zip_path) as zf:
        # Find CSVs
        all_csvs = [n for n in zf.namelist() if n.lower().endswith('.csv')]
        if not all_csvs:
            raise FileNotFoundError("No .csv file found inside the zip.")

        if csv_member is not None:
            if csv_member not in all_csvs:
                raise FileNotFoundError(
                    f"CSV member {csv_member!r} not found. "
                    f"Available: {all_csvs[:5]}{'...' if len(all_csvs)>5 else ''}"
                )
            csv_to_process = csv_member
        else:
            # Default to the first CSV found
            csv_to_process = all_csvs[0]

        writer = None
        try:
            with zf.open(csv_to_process, 'r') as zipped_bytes:  # ZipExtFile (stream)
                print(f'Writing {csv_to_process} to parquet... ', end='')
                stream = pa.input_stream(zipped_bytes)  # wrap as Arrow input stream

                # Arrow CSV reader that yields record batches lazily
                read_opts   = pv.ReadOptions(block_size=block_size)
                parse_opts  = pv.ParseOptions(delimiter=delimiter,
                                              newlines_in_values=True)
                convert_opts = (
                    pv.ConvertOptions(column_types=column_types) if column_types
                    else pv.ConvertOptions()
                )
                reader = pv.open_csv(stream,
                                     read_options=read_opts,
                                     parse_options=parse_opts,
                                     convert_options=convert_opts)

                # Create ParquetWriter on first chunk to lock the schema
                writer = pq.ParquetWriter(where=str(out_parquet),
                                            schema=reader.schema,
                                            compression=compression,
                                            use_dictionary=True,
                                            write_statistics=True)

                # Write each `batch` (pyarrow.RecordBatch obj) to Parquet file
                for batch in reader:
                    writer.write_batch(batch)
                print('Done!')

        finally:
            if writer is not None:
                writer.close()

    print("CSV(s) in zip file successfully extracted as Parquet files.")


# --------------------
# API helper functions
# --------------------

# Generic, source-agnostic HTTP Request helpers

def print_response_status(response: requests.Response) -> None:
    """
    Inspect response.status_code, then print a human-readable message.
    """
    code = response.status_code
    try:
        # Use the official reason phrase, e.g. 'OK', 'Not Found', etc.
        msg = HTTPStatus(code).phrase
    except ValueError:
        # Fallback by status‐code class
        msg = {
            2: 'Success',
            3: 'Redirection',
            4: 'Client error',
            5: 'Server error'
        }.get(code // 100, 'Unknown status code')

    print(f'HTTP {code}: {msg}')


def download_zip(
    url: str,
    destination: Path,
    chunk: int = 8192,
    verbose: Optional[bool] = False
    ) -> None:
    """
    Stream a remote file and save it locally at `destination`. Creates
    parent directories if needed. Performs Content-Type check for ZIP
    files.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=120) as response:
        # Check respones status
        response.raise_for_status()
        if verbose is True:
            print("Download status: ", end='')
            print_response_status(response)

        if 'zip' not in response.headers.get('Content-Type', '').lower():
            raise RuntimeError(
                f'Expected a ZIP, got {response.headers.get("Content-Type")!r} from {url}'
            )

        with open(destination, 'wb') as f:
            for part in response.iter_content(chunk_size=chunk):
                if part:
                    f.write(part)


# StatCan API Helpers

STATCAN_WEB_DATA_SERVICE = 'https://www150.statcan.gc.ca/t1/wds/rest'

def get_full_table_zip_url(
    table_id: int | str,
    lang: str = 'en',
    verbose: Optional[bool] = False
    ) -> str:
    """
    Call StatCan WDS to obtain the direct ZIP URL for a full-table CSV download.
    Returns a URL like 'https://www150.statcan.gc.ca/n1/tbl/csv/36100473-eng.zip'.
    """
    url = f'{STATCAN_WEB_DATA_SERVICE}/getFullTableDownloadCSV/{table_id}/{lang}'
    response = requests.get(url, timeout=30)
    # Note: 409 can occur ~00:00–08:30 ET while tables are locked.
    #   :contentReference[oaicite:1]{index=1}

    # Check respones status
    response.raise_for_status()
    if verbose is True:
        print("GET URL status: ", end='')
        print_response_status(response)

    payload = response.json()

    if payload.get('status') != 'SUCCESS' or 'object' not in payload:
        raise RuntimeError(f'Unexpected WDS response: {payload}')

    return payload['object']


# ------------------------
# Pandas DataFrame helpers
# ------------------------

def merge_columns_safe(df: pd.DataFrame, col1: str, col2: str) -> pd.Series:
    """
    Safely merge two pd.DataFrame columns into one.
    
    Application logic
    -----------------
    - For a given row, if column_A has a value and column_B is null,
      then column_A's value is used.

    - If both columns have the same value, then that value is used.

    - If both columns have different values (a conflict),
      merge_columns_safe() raises an error and leaves both input columns
      untouched.
      
    Args
    ----
        - df (pd.DataFrame): The df containing columns to be combined
        - col1 (str): Name/header of the 1st column
        - col2 (str): Name/header of the 2nd column

    Returns
    -------
        - pd.Series: A single merged column

    Raises
    ------
        - ValueError: If 2 columns both have different non-null values
                      in the same row.
    """
    # find any “conflicts” where both are non-NA
    both_non_na = df[col1].notna() & df[col2].notna()
    disagree = df[col1] != df[col2]
    conflicts = df[both_non_na & disagree]

    if not conflicts.empty:
        raise ValueError("Conflicting values found in rows:\n"
                         + conflicts[[col1, col2]].to_string())

    return df[col1].combine_first(df[col2])
