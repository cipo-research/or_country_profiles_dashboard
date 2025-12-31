from __future__ import annotations

# Indicator map 
IP_INDICATOR_MAP: dict[str, tuple[str, list[str]]] = {
    "patent":     ("PA", ["1a", "1b", "2a", "2b", "3", "5", "9", "10"]),
    "trademark":  ("TM", ["1a", "1b", "2a", "2b", "4a", "4b", "5a", "5b", "6a", "6b", "7", "8", "9"]),
    "industrial": ("ID", ["1a", "1b", "2a", "2b", "4a", "4b", "5a", "5b", "6a", "6b", "7", "8", "9"]),
}

# Staged column names
DESTINATION_OFFICE      = "destination_office"
DESTINATION_OFFICE_CODE = "destination_office_st3_code"
ORIGIN                  = "origin"
ORIGIN_CODE             = "origin_st3_code"
FIELD_OF_TECHNOLOGY     = "tech_field"
LOCARNO_CLASSIFICATION  = "locarno_class"
NICE_CLASSIFICATION     = "nice_class"
YEAR  = "year"
COUNT = "count"

COL_RENAME_MAP = {
    "Office":                 DESTINATION_OFFICE,
    "Office (Code)":          DESTINATION_OFFICE_CODE,
    "Origin":                 ORIGIN,
    "Origin (Code)":          ORIGIN_CODE,
    "Field of technology":    FIELD_OF_TECHNOLOGY,
    "Locarno classification": LOCARNO_CLASSIFICATION,
    "Nice classification":    NICE_CLASSIFICATION,
}

NUMERIC_COLS = [YEAR, COUNT]
STRING_COLS = [
    DESTINATION_OFFICE,
    DESTINATION_OFFICE_CODE,
    ORIGIN,
    ORIGIN_CODE,
    FIELD_OF_TECHNOLOGY,
    LOCARNO_CLASSIFICATION,
    NICE_CLASSIFICATION,
]

# Compute helper maps
IND_NAME_TO_ABBR: dict[str, str] = {
    f"{ip_type}_{code}": f"{abbr}{code}"
    for ip_type, (abbr, codes) in IP_INDICATOR_MAP.items()
    for code in codes
}

TARGET_INDICATORS = [
    "PA1a", "PA1b", "PA2a", "PA2b", "PA3",
    "TM1a", "TM1b", "TM2a", "TM2b", "TM5a", "TM5b", "TM6a", "TM6b",
    "ID1a", "ID1b", "ID2a", "ID2b", "ID5a", "ID5b", "ID6a", "ID6b",
]

# === Class flows ===
CLASS_INDICATORS = ["PA5", "TM4a", "TM4b", "ID4a", "ID4b"]
CLASS_COL_LABELS = {
    FIELD_OF_TECHNOLOGY:    "Tech field",  # Patents
    LOCARNO_CLASSIFICATION: "Locarno",     # Industrial designs
    NICE_CLASSIFICATION:    "Nice",        # Trademarks
}
