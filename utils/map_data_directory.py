"""
Generalized data directory mapper

##############
# The basics #
##############

What this script does in plain English
--------------------------------------
- Walks through a folder, logging the directory tree
- Tries to read data files (CSV, Parquet, etc.); logs column names and
  data types of each column
- Writes:
    1. A pretty-printed file directory "tree" to
       './project_docs/data_directory_structure.log'
    2. A data dictionary CSV to './project_docs/data_dictionary.csv'

How to run
----------
- If your terminal's working directory is the repo folder, enter:
  `python utils/map_data_directory.py`

Current file extension support
------------------------------
- .csv; .csv.gz; .csv.bz2
- .txt (i.e. tab-separated value (TSV) data)
- .parquet
- .xml (flat and hierarchical)


############
# Settings #
############

Basic settings in main() function
---------------------------------
- Set which folder to scan using by setting `start_dir`
- Set repo and docs folders with `repo_dir` and `project_docs_dir`
- Set which subfolders in `start_dir` to ignore with `ignored_dirs = (...)`
- Turn debugging log on and off

Advanced settings (outside main() function)
-------------------------------------------
- Define additional CSV parsing methods
    - Default: `default_csv_options()`
- Define additional data layer extraction methods
    - Default: `default_data_layer_extractor()`


###################################
# TODO & how to add functionality #
###################################

Immediate next steps
--------------------
This script has gotten large and complex enough to warrant giving it its
own directory structure and separating it into modules.
For example (incomplete):

or_country_profiles/
└── utils/
    └── map_data_directory/
        └── schema_readers/
            ├── base_schema_reader.py
            ├── xml_schema_readers.py
            └── flat_schema_readers.py
        ├── loggers/
            ├── logger_formatters.py
            └── directory_logger.py
        ├── data_dictionary_writers/
            └── csv_dictionary_writer.py    
        ├── config.py
        ├── main.py
        └── mapper_utils.py


How to add support for a new file extension
-------------------------------------------
1. Create a new class that inherits from BaseSchemaReader (abstract base class)
   and implement the read() function
    - The read() function follows this pattern:
        1. Open/inspect file
        2. Build a pd.DataFrame with exactly 2 columns:
            - 'Column' (str)
            - 'Data Type' (str)
        3. Return the pd.DataFrame or None if the schema cannot be determined

2. Instantiate your reader class in main() next to the others

3. Register the instantiated reader in `dispatch_map` with the file extension
   it reads as the key.
    - E.g. `dispatch_map = {..., 'json' = json_reader, ...}`

4. Run with test file(s) in the scanned directory using `debug=True`

5. Check output `data_directory_structure.log` and `data_dictionary.csv` files
   to confirm columns/types were written correctly


################
# How it works #
################

Mental model of the code
------------------------
  main(...) --> write_directory_log(...) --> walk_and_log_directory(...)
                    |                                  |
                    └--> process_file(...) --> get_reader(...)
                                                 |
                              BaseSchemaReader.read_safe(...) (handles errors)
                                                 |
                                  Specific readers (CSV/Parquet/TSV/XML)
                                                 |
                                    create_records_from_schema(...)
                                                 |
                                     write_data_dictionary(...)
"""

from __future__ import annotations

import logging
import os
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

import pandas as pd
import pyarrow.csv as pacsv
import pyarrow.parquet as pq


# -------------
# Configuration
# -------------

# CsvOptionsResolver is any function that you can give a Path to and it
# will return a pacsv.ReadOptions object.
# - pacsv.ReadOptions is a set of instructions for the CSV reader.
# - `default_csv_options` (defined below) is the default.
CsvOptionsConfig = Callable[[Path], pacsv.ReadOptions]

# LayerExtractor is any function that you give two paths to and it
# will return a string.
# - LayerExtractor is for returning the data layer (raw, staging, ...)
#   that a given data file belongs to.
DataLayerExtractor = Callable[[Path, Path], str]

@dataclass(frozen=True)
class DirectoryScanConfig:
    """Configuration for the directory scan."""
    start_dir: Path  # folder to be mapped
    repo_dir:  Path
    project_docs_dir: Path
    # Output files
    log_filename:  str = 'data_directory_structure.log'
    dict_filename: str = 'data_dictionary.csv'
    # Subfolders in `./data/` to ignore
    ignored_dirs: frozenset[str] = frozenset(("_legacy", "demo_japan"))
    debug: bool = True  # default: log when reading a file's schema fails


@dataclass(frozen=True)
class DataRecord:
    """A record representing a single row in a data table."""
    layer: str  # Data layer (i.e. raw, staging, intermediate, marts)
    table_path: str
    table_filetype: str
    table_name: str
    column_name: str
    column_dtype: str


# ----------------
# Helper functions
# ----------------

# XML helper functions

def find_xml_max_depth(path: Path) -> int:
    """
    Calculates the maximum depth of an XML tree using iterparse.
    """
    max_depth = 0
    depth = 0
    try:
        for event, _ in ET.iterparse(path, events=('start', 'end')):
            if event == 'start':
                depth += 1
                max_depth = max(max_depth, depth)
            elif event == 'end':
                depth -= 1
        return max_depth

    except ET.ParseError:
        return 0


def find_xml_repeating_tag(path: Path) -> str | None:
    """
    Heuristic to find the main 'record' tag by parsing the file once
    to track tag counts and their maximum depths.
    
    The best candidate for a 'record' is the deepest tag that repeats.
    This is often the most granular, unique item.
    """
    tag_counts = {}
    tag_depths = {}
    depth = 0
    # Traverse XML tree; catalog all XML tags and their depths
    try:
        for event, elem in ET.iterparse(path, events=('start', 'end')):
            if event == 'start':
                depth += 1
                tag = elem.tag
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
                tag_depths[tag] = max(tag_depths.get(tag,0), depth)
            elif event == 'end':
                depth -= 1

    except ET.ParseError:
        return None

    # Find repeating XML tags
    repeating_tags = {tag for tag, count in tag_counts.items() if count > 1}
    if not repeating_tags:
        return None

    # Rule of thumb from docstring
    deepest_tag = max(repeating_tags, key=lambda tag: tag_depths[tag])
    return deepest_tag


# ----------------------------------------------------------------
# Policies (Dependency-injected; used as args in other functions)
# ----------------------------------------------------------------

def default_csv_options(path: Path) -> pacsv.ReadOptions:
    """Provides deterministic column naming for CSV files."""
    return pacsv.ReadOptions(autogenerate_column_names=False)


def default_data_layer_extractor(
    file_path: Path, start_dir_parent: Path) -> str:
    """Extracts data layer using the convention: ./data/<layer>/..."""
    try:
        rel = file_path.relative_to(start_dir_parent)
    except ValueError:
        return "unknown"
    return rel.parts[1] if len(rel.parts) > 1 else "unknown"


# --------------------------------------------------------------------
# File schema readers (Abstract base class & concrete implementations)
# --------------------------------------------------------------------

class BaseSchemaReader(ABC):
    """
    Defines the contract for a file schema reader and provides robust error handling.
    All concrete readers must inherit from this class.
    """
    def __init__(self, logger: logging.Logger, debug: bool):
        self._logger = logger
        self._debug = debug

    @abstractmethod
    def read(self, path: Path) -> pd.DataFrame | None:
        """Core logic to read a given filetype's schema."""

    def read_safe(self, path: Path) -> pd.DataFrame | None:
        """Error-handling wrapper for BaseSchemaReader.read()."""
        try:
            return self.read(path)

        except Exception as e:
            if self._debug:
                self._logger.debug("Schema read failed for %s", path, exc_info=e)
            return None


class CsvSchemaReader(BaseSchemaReader):
    """
    Reads column headers & datatypes in CSV files using pyarrow.csv.
    pyarrow.csv automatically handles compressed CSV files like *.csv.gz.
    
    CSVs don't have a single standard format, so this class is
    configurable using the 'options_config' argument. 'options_config'
    tells `pacsv.read_csv()` how to read the CSV file. 
    """
    def __init__(self,
                 options_config: CsvOptionsConfig,
                 logger: logging.Logger,
                 debug: bool):
        super().__init__(logger, debug)
        self._options_config = options_config  # CSV configuration

    def check_wipo_indicator(self, path: Path) -> bool:
        """
        Checks if a data file is a raw WIPO IP indicator.
        """
        dir_parts: set[str] = {p.lower() for p in path.parts}
        return all(p in dir_parts for p in ('raw', 'wipo', 'ip_indicators'))

    def read(self, path: Path) -> pd.DataFrame | None:
        """Reads the CSV schema using the configured options."""
        if self.check_wipo_indicator(path):
            try:
                df = pd.read_csv(path, skiprows=6, nrows=100)
                if df.empty:
                    return None

                # Infer dtypes for CSV; else strings recorded as 'Object'
                df = df.convert_dtypes()
                return pd.DataFrame({"Column": df.columns,
                                     "Data Type": df.dtypes.astype(str)})

            except Exception:  # Triggers except block in BaseSchemaReader.read_safe()
                raise

        table = pacsv.read_csv(path, read_options=self._options_config(path))
        if not table.schema or not table.schema.names:
            return None

        return pd.DataFrame({"Column": table.schema.names,
                             "Data Type": [str(f.type) for f in table.schema]})


class ParquetSchemaReader(BaseSchemaReader):
    """
    Reads column headers & datatypes in Parquet files.
    
    Parquet files contain metadata about their schema, so no extra
    configuration is required.
    """
    def read(self, path: Path) -> pd.DataFrame | None:
        schema: pq.ParquetSchema = pq.read_schema(path)
        if not schema:
            return None

        return pd.DataFrame({"Column": schema.names,
                             "Data Type": [str(t) for t in schema.types]})


class TsvSchemaReader(BaseSchemaReader):
    """
    Reads a schema from a .txt file, but only if it's tab-separated (TSV).
    Detects if the file is a valid TSV with a header.
    """
    def _is_tsv_check(self, path: Path, sample_line_count: int = 10) -> bool:
        """
        Detects valid TSV files by checking for consistent tab counts.
        Prevents us from reading unstructured text files as tables.
        """
        try:
            with open(path, 'r', encoding='utf-8') as f:
                # Read text file line-by-line, then remove blank lines
                lines = [f.readline() for i in range(sample_line_count)]
                lines = [line for line in lines if line]

                # Check if file is empty
                if len(lines) == 0:
                    return False

                # Check header
                header_tab_count = lines[0].count('\t')
                if header_tab_count == 0:
                    return False

                # Check if lines have same number of tabs (cols) as header line
                for line in lines[1:]:
                    if line.strip() and line.count('\t') != header_tab_count:
                        return False  # Inconsistent structure in TSV file

                return True

        except (IOError, UnicodeDecodeError) as e:
            self._logger.debug(f"Could not read {path.name}, {e}.")
            return False

    def read(self, path: Path) -> pd.DataFrame | None:
        """Infers a schema by reading the first line of the text file."""
        if not self._is_tsv_check(path):
            self._logger.debug(f"Skipping {path.name}: not a tab-separated file.")
            return None

        df = pd.read_csv(path, sep='\t', nrows=500)
        if df.empty:
            return None

        # Success: The file is a valid TSV with a header.
        return pd.DataFrame({"Column": df.columns,
                             "Data Type": [str(dtype) for dtype in df.dtypes]})


class FlatXmlSchemaReader(BaseSchemaReader):
    """
    Reads a potential schema from an XML file by inspecting its structure.

    Important: Assumes the XML is structured like a list of records:
    <root>
      <record>  <-- It inspects this first record
        <col1>data</col1>
        <col2>data</col2>
      </record>
      <record>
        ...
      </record>
    </root>

    It uses the tags from the first child of the root (`<record>`) as the
    source for the column names (`<col1>`, `<col2>`).
    """
    def read(self, path: Path) -> pd.DataFrame | None:
        root = ET.parse(path).getroot()
        if len(root) == 0:
            return None

        first_child = root[0]
        cols = [child.tag for child in first_child]

        return pd.DataFrame({"Column": cols,
                             "Data Type": ["string"] * len(cols)})


class HierarchicalXmlSchemaReader(BaseSchemaReader):
    """
    Reads a schema from a hierarchical XML by deducing its structure and
    flattening it into a table.
    """
    def read(self, path: Path) -> pd.DataFrame | None:
        # 1. Find repeating element that defines a 'row'
        record_tag = find_xml_repeating_tag(path)
        if not record_tag:
            self._logger.debug("No repeating elements found in %s to flatten.",
                               path)
            return None

        try:
            tree = ET.parse(path)
        except ET.ParseError:
            return None

        root = tree.getroot()
        parent_map = {child: parent
                      for parent in root.iter()
                      for child in parent}

        all_records = []
        for record_elem in root.findall(f'.//{record_tag}'):
            flat_record = {}

            # 2. Get ancestor by walking up from leaves of XML tree
            parent = parent_map.get(record_elem)
            while parent is not None:
                # Prefix to avoid naming collision
                prefix = parent.tag.split('}')[-1] + '_'
                for key, value in parent.attrib.items():
                    if prefix + key not in flat_record:
                        flat_record[prefix + key] = value
                parent = parent_map.get(parent)

            # 3. Get record's attributes and text/attributes of immediate children
            flat_record.update(record_elem.attrib)
            for child in record_elem:
                child_tag = child.tag.split('}')[-1]
                flat_record[child_tag] = child.text
                flat_record.update(
                    {f"{child.tag.split('}')[-1]}_{k}": v for k, v in child.attrib.items()}
                )

            all_records.append(flat_record)

        if not all_records:
            return None

        # 4. Create a DataFrame, which handles missing keys gracefully.
        df = pd.DataFrame(all_records)
        return pd.DataFrame({"Column": df.columns,
                             "Data Type": [str(dtype) for dtype in df.dtypes]})


class XmlDispatcherReader(BaseSchemaReader):
    """
    A "manager" reader that delegates to the correct specialized XML reader
    based on the file's structural complexity (depth).
    """
    def __init__(self,
                 hierarchical_reader: HierarchicalXmlSchemaReader,
                 flat_reader: FlatXmlSchemaReader,
                 logger: logging.Logger,
                 debug: bool):
        super().__init__(logger, debug)
        self._hierarchical_reader = hierarchical_reader
        self._simple_reader = flat_reader

    def read(self, path: Path) -> pd.DataFrame | None:
        """Checks XML depth and delegates to the appropriate reader."""
        # The heuristic: if the tree is deeper than 2 levels (root -> record),
        # it's considered hierarchical. Otherwise, it's simple.
        max_depth = find_xml_max_depth(path)

        if max_depth > 2:
            return self._hierarchical_reader.read_safe(path)

        elif max_depth > 0:
            return self._simple_reader.read_safe(path)

        else:
            return None


# -------------------------------------
# Directory logger format configuration
# -------------------------------------

class LogTreeFormatter(logging.Formatter):
    """Formatter to create a tree-like log structure."""
    def format(self, record: logging.LogRecord) -> str:
        depth = getattr(record, "depth", 0)
        item_type = getattr(record, "item_type", "detail")
        prefix = ""
        indent = " " * 4

        if item_type == "dir":
            prefix = f"{indent * max(0, depth - 1)}└── "
            record.msg = f"{record.msg}/"

        elif item_type == "file":
            prefix = f"{indent * depth}├── "

        elif item_type == "detail":
            prefix = f"{indent * depth}"

        record.msg = f"{prefix}{record.msg}"

        # Return a logging.LogRecord formatted as a string
        return super().format(record)


# ----------------------------
# Core logic and orchestration
# ----------------------------

def walk_and_log_directory(
    cfg: DirectoryScanConfig,
    logger: logging.Logger
) -> Iterable[tuple[Path, int]]:
    """
    Walks the directory tree, logs the structure, and yields files to be
    processed.
    """
    start_depth = len(cfg.start_dir.parts)
    for root, dirnames, filenames in os.walk(cfg.start_dir):
        root_path = Path(root)
        depth = len(root_path.parts) - start_depth + 1
        logger.info(root_path.name, extra={"depth": depth, "item_type": "dir"})

        # Slice ignored directories out of list of dirs to be scanned
        dirnames[:] = [d for d in dirnames if d not in cfg.ignored_dirs]

        for filename in sorted(filenames):
            yield root_path / filename, depth


def get_reader(
    path: Path,
    dispatch_map: dict[str, BaseSchemaReader]
) -> BaseSchemaReader | None:
    """
    Finds a reader for the file; handles compound extensions like '.csv.gz'.
    """
    full_ext = ''.join(path.suffixes).lower()
    return dispatch_map.get(full_ext) or dispatch_map.get(path.suffix.lower())


def create_records_from_schema(
    file_path: Path,
    schema_df: pd.DataFrame,
    cfg: DirectoryScanConfig,
    layer_extractor: DataLayerExtractor
) -> list[DataRecord]:
    """
    Factory function to create DataRecord objects from a schema DataFrame.
    """
    try:
        rel_path = file_path.relative_to(cfg.start_dir.parent)
    except ValueError:
        rel_path = file_path

    layer = layer_extractor(file_path, cfg.start_dir.parent)
    file_ext = "".join(file_path.suffixes)
    table_name = file_path.stem

    data_records: list[DataRecord] = [
        DataRecord(layer=layer,
                   table_path=rel_path.as_posix(),
                   table_filetype=file_ext,
                   table_name=table_name,
                   column_name=str(col),
                   column_dtype=str(dtype))
        for col, dtype in schema_df.itertuples(index=False, name=None)
    ]

    return data_records


def process_file(
    file_path: Path,
    depth: int,
    cfg: DirectoryScanConfig,
    logger: logging.Logger,
    dispatch_map: dict[str, BaseSchemaReader],
    layer_extractor: DataLayerExtractor,
) -> list[DataRecord]:
    """Contains the complete, linear logic for processing a single file."""
    logger.info(file_path.name,
                extra={"depth": depth, "item_type": "file"})

    # 1. Find the correct reader for the file type
    reader = get_reader(file_path, dispatch_map)
    if not reader:
        logger.info("    (Unsupported file type)",
                    extra={"depth": depth, "item_type": "detail"})
        return []

    # 2. Read the schema using the safe entry point
    schema_df = reader.read_safe(file_path)
    if schema_df is None or schema_df.empty:
        logger.info("    (Could not extract column info or file is empty)",
                    extra={"depth": depth, "item_type": "detail"})
        return []

    # 3. Create the final DataRecord objects
    records = create_records_from_schema(
        file_path=file_path, schema_df=schema_df, cfg=cfg, layer_extractor=layer_extractor
    )

    # 4. Log the extracted columns
    for col, dtype in schema_df.itertuples(index=False, name=None):
        logger.info(f"    - {col} ({dtype})",
                    extra={"depth": depth, "item_type": "detail"})

    return records


def write_directory_log(
    cfg: DirectoryScanConfig,
    logger: logging.Logger,
    dispatch_map: dict[str, BaseSchemaReader],
    layer_extractor: DataLayerExtractor,
) -> list[DataRecord]:
    """Orchestrates the directory scan and data record generation."""
    all_records: list[DataRecord] = []
    start_dir_rel = f"./{cfg.start_dir.parent.name}/{cfg.start_dir.name}"

    logger.info(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    logger.info(f"### Starting analysis: '{start_dir_rel}' ###\n")
    logger.info(f"{cfg.start_dir.parent.name}/")

    # Walk the directory and process each file
    for file_path, depth in walk_and_log_directory(cfg, logger):
        file_records = process_file(file_path,
                                    depth,
                                    cfg=cfg,
                                    logger=logger,
                                    dispatch_map=dispatch_map,
                                    layer_extractor=layer_extractor)
        all_records.extend(file_records)

    logger.info(f"\n### Analysis complete: '{start_dir_rel}' ###")

    return all_records


# ------------
# Side-effects
# ------------

def create_directory_logger(log_path: Path, level: int) -> logging.Logger:
    """
    Initializes and configures the logger with the custom formatter.
    
    General rule of thumb: don't use the base `logging` object to write
    logs. Make a `logging.Logger` object for each log to be written.
    """
    logger = logging.getLogger('data_directory')
    # Python has 6 logging levels:
    # {NOTSET: 0, DEBUG: 10, INFO: 20, WARN: 30, ERROR: 40, CRITICAL: 50}
    logger.setLevel(level)
    logger.handlers.clear()
    handler = logging.FileHandler(log_path, mode="w", encoding="utf-8")
    handler.setFormatter(LogTreeFormatter("%(message)s"))
    logger.addHandler(handler)
    return logger


def write_data_dictionary(
    records: list[DataRecord],
    output_path: Path,
    repo_dir: Path
) -> None:
    """Writes the collected data records to a CSV file."""
    if not records:
        print("No data records were collected to write to CSV.")
        return
    df = pd.DataFrame([r.__dict__ for r in records])
    df.to_csv(output_path, index=False, encoding="utf-8")
    try:
        rel_path = output_path.relative_to(repo_dir)
    except ValueError:
        rel_path = output_path
    print(f"Successfully created data dictionary at '{rel_path}'")


# ---------------------------
# Main orchestration function
# ---------------------------

def main(
    start_dir: Path,
    repo_dir: Path,
    project_docs_dir: Path,
    csv_options_resolver: CsvOptionsConfig = default_csv_options,
    layer_extractor: DataLayerExtractor = default_data_layer_extractor,
    ignored_dirs: Iterable[str] = ("_legacy", "demo_japan"),
    debug: bool = False,
) -> None:
    """Configures dependencies and runs the data dictionary generation process."""
    if not (start_dir.exists() and start_dir.is_dir()):
        print(f"Error: The starting directory '{start_dir}' "
               "does not exist or is not a directory.")
        return

    dir_cfg = DirectoryScanConfig(start_dir=start_dir,
                                  repo_dir=repo_dir,
                                  project_docs_dir=project_docs_dir,
                                  ignored_dirs=frozenset(ignored_dirs),
                                  debug=debug,)

    logger = create_directory_logger(
        log_path=dir_cfg.project_docs_dir / dir_cfg.log_filename,
        level=logging.DEBUG if dir_cfg.debug else logging.INFO
    )

    # 1. Instantiate the specific reader strategies
    # Note: All schema readers inherit from BaseSchemaReader, which
    #       provides logger-based error handling via inheritance.

    # 1a. Tabular data files
    csv_reader     = CsvSchemaReader(csv_options_resolver, logger, dir_cfg.debug)
    parquet_reader = ParquetSchemaReader(logger, dir_cfg.debug)
    tsv_reader     = TsvSchemaReader(logger, dir_cfg.debug)

    # 1b. Tree-like data files
    flat_xml_reader         = FlatXmlSchemaReader(logger, dir_cfg.debug)
    hierarchical_xml_reader = HierarchicalXmlSchemaReader(logger, dir_cfg.debug)
    xml_dispatcher = XmlDispatcherReader(
        hierarchical_reader=hierarchical_xml_reader,
        flat_reader=flat_xml_reader,
        logger=logger,
        debug=dir_cfg.debug
    )

    # 2. Map file extensions to schema readers
    dispatch_map: dict[str, BaseSchemaReader] = {
        '.csv':     csv_reader,
        '.csv.gz':  csv_reader,
        '.csv.bz2': csv_reader,
        '.parquet': parquet_reader,
        '.txt':     tsv_reader,
        '.xml':     xml_dispatcher,
    }

    # Write the log (.log file)
    print('Starting analysis... ', end='')
    records = write_directory_log(
        cfg=dir_cfg,
        logger=logger,
        dispatch_map=dispatch_map,
        layer_extractor=layer_extractor,
    )
    print('Analysis complete.')

    # Write the data dictionary (.csv file)
    write_data_dictionary(records=records,
                          output_path=dir_cfg.project_docs_dir / dir_cfg.dict_filename,
                          repo_dir=dir_cfg.repo_dir)


if __name__ == '__main__':
    try:
        from utils.paths import REPO_DIR, DOCS_DIR, DATA_DIR

        main(start_dir=DATA_DIR,
             repo_dir=REPO_DIR,
             project_docs_dir=DOCS_DIR,)

    except ImportError as e:
        CWD = Path.cwd()
        print(f"Error: {e}.\n"
               "Could not import paths from 'utils.paths'. "
               "Using current working directory as fallback.")
        print()
        print(f"Current working directory: {CWD}")

        main(start_dir=CWD / 'data',
             repo_dir=CWD,
             project_docs_dir=CWD / 'project_docs')
