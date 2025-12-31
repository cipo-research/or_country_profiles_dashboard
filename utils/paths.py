"""
Directory map for ETL pipelines

Rather than use hard-coded strings throughout ETL scripts that would
have to be updated one-by-one should directories be changed, this module
defines all key directories in one place.

By importing the desired paths from `./utils/paths.py` with
`from utils.paths import ...`, ETL jobs can reference common locations
consistently.

This provides a single source of truth for paths across the project
which can be updated all in one location.
"""

from pathlib import Path

from utils.etl_utils import get_repo_root


#############
# Directories
#############

# Repo directory
REPO_DIR: Path = get_repo_root(repo_name="or_country_profiles-main")


# Documentation directory
DOCS = 'docs'
DOCS_DIR = REPO_DIR / DOCS

# ---------------
# DIRECTORY NAMES
# ---------------

# Base data directory
DATA = 'data'

# Data layers
RAW          = 'raw'
STAGING      = 'staging'
INTERMEDIATE = 'intermediate'
MARTS        = 'marts'

# Common sources
UN         = 'un'
GAC        = 'gac'
WIPO       = 'wipo'
STATCAN    = 'statcan'
WORLD_BANK = 'world_bank'
CHINA      = 'china'

# Common sub-directories
REGIONS         = 'regions'

MACROECON_STATS = 'macroecon_stats'
MACROECON_FLOWS = 'macroecon_flows'

IP_OFFICES      = 'ip_offices'

IP_CLASSES      = 'ip_classes'
IPC_CLASSES     = 'ipc'
NICE_CLASSES    = 'nice'
LOCARNO_CLASSES = 'locarno'

IP_INDICATORS   = 'ip_indicators'  # WIPO IP indicators
IP_FLOWS        = 'ip_flows'       # Transformed IP indicators

UOM = 'units_of_measure'

# ------------------------------------------------------------------
# DATA DIRECTORIES BY DATA LAYER (Raw, Staging, Intermediate, Marts)
# ------------------------------------------------------------------

# Base data directory
DATA_DIR = REPO_DIR / DATA

# Demo data directory
DEMO_DIR = DATA_DIR / 'demo_japan'

# ---------
# RAW LAYER
# ---------

# RAW - Base directory
RAW_DIR = DATA_DIR / RAW

# RAW - Sources
RAW_WIPO_DIR       = RAW_DIR / WIPO
RAW_STATCAN_DIR    = RAW_DIR / STATCAN
RAW_WORLD_BANK_DIR = RAW_DIR / WORLD_BANK
RAW_CHINA_DIR      = RAW_DIR / CHINA

# RAW - IP data
RAW_IP_INDICATORS_DIR = RAW_WIPO_DIR / IP_INDICATORS

# RAW - IP classifications
RAW_IP_CLASSES_DIR      = RAW_WIPO_DIR / IP_CLASSES
RAW_IPC_CLASSES_DIR     = RAW_IP_CLASSES_DIR / IPC_CLASSES
RAW_NICE_CLASSES_DIR    = RAW_IP_CLASSES_DIR / NICE_CLASSES
RAW_LOCARNO_CLASSES_DIR = RAW_IP_CLASSES_DIR / LOCARNO_CLASSES


# -------------
# STAGING LAYER
# -------------

# STAGING - Base directory
STG_DIR = DATA_DIR / STAGING

# STAGING - WIPO - IP data & offices
STG_WIPO_DIR          = STG_DIR / WIPO
STG_IP_INDICATORS_DIR = STG_WIPO_DIR / IP_INDICATORS
STG_IP_OFFICES_DIR    = STG_WIPO_DIR / IP_OFFICES

# STAGING - WIPO - IP Classifications systems
STG_IP_CLASSES_DIR      = STG_WIPO_DIR / IP_CLASSES
STG_IPC_CLASSES_DIR     = STG_IP_CLASSES_DIR / IPC_CLASSES
STG_NICE_CLASSES_DIR    = STG_IP_CLASSES_DIR / NICE_CLASSES
STG_LOCARNO_CLASSES_DIR = STG_IP_CLASSES_DIR / LOCARNO_CLASSES

# STAGING - Non-WIPO sources
STG_WORLD_BANK_DIR = STG_DIR / WORLD_BANK  # World Bank
STG_STATCAN_DIR    = STG_DIR / STATCAN     # Statistics Canada (StatCan)
STG_GAC_DIR        = STG_DIR / GAC         # Global Affairs Canada (GAC)
STG_UN_DIR         = STG_DIR / UN          # United Nations
STG_CHINA_DIR      = STG_DIR / CHINA       # China


# ------------------
# INTERMEDIATE LAYER
# ------------------

# INTERMEDIATE - Base directory
INT_DIR = DATA_DIR / INTERMEDIATE

# INTERMEDIATE - Regions
INT_REGIONS_DIR = INT_DIR  # / REGIONS

# INTERMEDIATE - IP-related data
INT_IP_OFFICES_DIR = INT_DIR  # / IP_OFFICES
INT_IP_FLOWS_DIR   = INT_DIR  # / IP_FLOWS

# INTERMEDIATE - IP classification systems
INT_IP_CLASSES_DIR      = INT_DIR             # / IP_CLASSES
INT_IPC_CLASSES_DIR     = INT_IP_CLASSES_DIR  # / IPC_CLASSES
INT_NICE_CLASSES_DIR    = INT_IP_CLASSES_DIR  # / NICE_CLASSES
INT_LOCARNO_CLASSES_DIR = INT_IP_CLASSES_DIR  # / LOCARNO_CLASSES

# INTERMEDIATE - Economic data
INT_MACROECON_STATS_DIR = INT_DIR  # / MACROECON_STATS
INT_MACROECON_FLOWS_DIR = INT_DIR  # / ECON_FLOWS

# INTERMEDIATE - Units of measure
INT_UOM_DIR = INT_DIR  # / UOM


# ------------------
# (DATA) MARTS LAYER
# ------------------

# MARTS - Base directory
MARTS_DIR = DATA_DIR / MARTS

# MARTS - Economic data
MARTS_MACROECON_STATS_DIR = MARTS_DIR  # / MACROECON_STATS
MARTS_MACROECON_FLOWS_DIR = MARTS_DIR  # / MACROECON_FLOWS

# MARTS - IP-related data
MARTS_IP_FLOWS_DIR   = MARTS_DIR  # / IP_FLOWS
MARTS_IP_OFFICES_DIR = MARTS_DIR  # / IP_OFFICES


###########################################
# Helper function(s) for directory creation
###########################################

# Function to create directories if they don't exist
def create_dirs() -> None:
    """
    Creates all the defined directories if they don't already exist.
    """
    paths_to_create = [
        path for path in globals().values() if isinstance(path, Path)
    ]

    print("Ensuring project's data directories exist...\n")
    for path in paths_to_create:
        if not path.exists():
            print(f"'./{path.parent}/{path.name}' not found; creating directory...")
        path.mkdir(parents=True, exist_ok=True)

    print("Done:\n"
          "    - Project directories defined in `./utils/paths.py` checked.\n"
          "    - All directories that didn't exist have been created.\n"
          "    - Pre-existing files are safe; "
          "this check DID NOT overwrite any directories or files.")
