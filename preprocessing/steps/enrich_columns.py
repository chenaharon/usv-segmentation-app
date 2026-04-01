from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

SYLLABLE_TYPE_MAP = {
    0: "Complex",
    1: "Frequency steps",
    2: "Composite",
    3: "Two syllables",
    4: "Upward",
    5: "Flat",
    6: "Harmonic",
    7: "Downward",
    8: "Chevron",
    9: "Short",
    10: "Undefined",
}

_SINGLE_VOWEL = {0, 4, 5, 7, 8, 9}
_MULTIPLE_VOWELS = {1, 3}
_ADVANCED_HARMONIC = {2, 6, 10}


def _complexity_numeric(syl_num) -> Optional[int]:
    """Map a syllable number to its complexity level (1/2/3)."""
    if pd.isna(syl_num):
        return None
    syl_num = int(syl_num)
    if syl_num in _SINGLE_VOWEL:
        return 1
    if syl_num in _MULTIPLE_VOWELS:
        return 2
    if syl_num in _ADVANCED_HARMONIC:
        return 3
    return None


_COMPLEXITY_TEXT = {1: "Single Vowel", 2: "Multiple Vowels", 3: "Advanced Harmonic"}

FINAL_COLUMN_ORDER = [
    "Index",
    "Path",
    "Year",
    "Mother",
    "Mother Genotype",
    "Mother Genotype (binary)",
    "Supplement (Mother)",
    "Name",
    "Sex",
    "Offspring Genotype",
    "Offspring Genotype (binary)",
    "Supplement (Offspring)",
    "Day",
    "Session",
    "Recording Number",
    "Syllable order (in recording)",
    "Syllables per recording",
    "Start point(s)",
    "End point(s)",
    "Duration (time)",
    "ISI_time",
    "Start Point (Hz)",
    "End Point (Hz)",
    "Noise",
    "Syllable number",
    "Syllable type",
    "Complexity level",
    "Complexity level (numeric)",
]


def enrich_segmentation_columns(
    file_path: str,
    year: str,
    logger: Optional[logging.Logger] = None,
) -> str:
    """Add enrichment columns to the segmentation Excel file.

    Reads the Excel produced by the earlier pipeline steps (segmentation,
    basic features, classification), computes the columns specified in
    Issue #5, reorders to ``FINAL_COLUMN_ORDER``, and writes back.

    Args:
        file_path: Path to the segmentation Excel file (will be updated).
        year: Recording year (fallback when Path is unavailable).
        logger: Optional logger instance.

    Returns:
        Path to the updated Excel file.
    """
    if logger:
        logger.info("Enriching segmentation columns")

    df = pd.read_excel(file_path, engine="openpyxl")

    # 1. Row index (1-based serial ID)
    df["Index"] = range(1, len(df) + 1)

    # 2. Year — derive from Path when possible
    if "Path" in df.columns:
        df["Year"] = df["Path"].apply(
            lambda p: str(p).split("/")[1] if "/" in str(p) else year
        )
    else:
        df["Year"] = year

    # 3. Mother Genotype (binary): WT → 1, anything else → 0
    df["Mother Genotype (binary)"] = (
        df["Mother Genotype"]
        .apply(lambda x: 1 if str(x).strip().upper() == "WT" else 0)
    )

    # 4. Offspring Genotype (binary): WT → 1, anything else → 0
    df["Offspring Genotype (binary)"] = (
        df["Offspring Genotype"]
        .apply(lambda x: 1 if str(x).strip().upper() == "WT" else 0)
    )

    # 5a. Syllable order within recording (by ascending Start point)
    #     Group by Path (unique per recording) to handle repeated Recording Numbers
    #     across different mice.
    #     Missing Start point(s) → NaN rank; nullable Int64 avoids
    #     "Cannot convert non-finite values (NA or inf) to integer".
    _rank = df.groupby("Path")["Start point(s)"].rank(method="first")
    df["Syllable order (in recording)"] = _rank.astype("Int64")

    # 5b. Number of syllables in each recording
    df["Syllables per recording"] = (
        df.groupby("Path")["Path"].transform("count")
    )

    # 6. Noise indicator: 1 when Start Point (Hz) == End Point (Hz)
    if "Start Point (Hz)" in df.columns and "End Point (Hz)" in df.columns:
        _noise = df["Start Point (Hz)"] == df["End Point (Hz)"]
        df["Noise"] = _noise.fillna(False).astype("int64")
    else:
        df["Noise"] = 0

    # 7a. Supplement (Mother): 1 if Mother name contains "sup"
    df["Supplement (Mother)"] = (
        df["Mother"].astype(str)
        .str.contains("sup", case=False, na=False)
        .astype(int)
    )

    # 7b. Supplement (Offspring): 1 if offspring Name contains "sup"
    df["Supplement (Offspring)"] = (
        df["Name"].astype(str)
        .str.contains("sup", case=False, na=False)
        .astype(int)
    )

    # 8. Syllable type — English label derived from Syllable number
    if "Syllable number" in df.columns:
        df["Syllable type"] = df["Syllable number"].map(SYLLABLE_TYPE_MAP)
    else:
        df["Syllable type"] = None

    # 9a. Complexity level (text)
    if "Syllable number" in df.columns:
        df["Complexity level (numeric)"] = df["Syllable number"].apply(
            _complexity_numeric
        )
        df["Complexity level"] = df["Complexity level (numeric)"].map(
            _COMPLEXITY_TEXT
        )
    else:
        df["Complexity level"] = None
        df["Complexity level (numeric)"] = None

    # Reorder: known columns first (in spec order), then any extras
    ordered = [c for c in FINAL_COLUMN_ORDER if c in df.columns]
    extras = [c for c in df.columns if c not in FINAL_COLUMN_ORDER]
    df = df[ordered + extras]

    df.to_excel(file_path, index=False, engine="openpyxl")

    if logger:
        logger.info(
            f"Enrichment complete: {len(df)} rows, {len(df.columns)} columns "
            f"in {file_path}"
        )

    return file_path
