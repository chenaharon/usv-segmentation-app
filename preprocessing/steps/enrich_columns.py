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
_ADVANCED_HARMONIC = {2, 6}
_UNDEFINED = {10}


def _complexity_numeric(syl_num) -> Optional[int]:
    """Map a syllable number to its complexity level (0/1/2/3).

    Class 10 (low-confidence/Undefined) is reported as its own complexity
    level 0 instead of being folded into Advanced Harmonic, so analyses can
    treat it as a distinct category.
    """
    if pd.isna(syl_num):
        return None
    syl_num = int(syl_num)
    if syl_num in _UNDEFINED:
        return 0
    if syl_num in _SINGLE_VOWEL:
        return 1
    if syl_num in _MULTIPLE_VOWELS:
        return 2
    if syl_num in _ADVANCED_HARMONIC:
        return 3
    return None


_COMPLEXITY_TEXT = {
    0: "Undefined",
    1: "Single Vowel",
    2: "Multiple Vowels",
    3: "Advanced Harmonic",
}

# Written by CNN / fallback classification; omitted in segmentation-only runs.
SYLLABLE_CLASSIFICATION_OUTPUT_COLUMNS = (
    "Syllable number",
    "Syllable type",
    "Complexity level",
    "Complexity level (numeric)",
)

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
    "Genotype Group",
    "Genotype Group (numeric)",
    "Supplement (Offspring)",
    "Day",
    "Session",
    "Strain",
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


def _strain_label_from_year(y) -> str:
    s = str(y).strip()
    try:
        yi = int(float(s))
    except ValueError:
        yi = 0
    return "BALB/C" if yi in (2015, 2018) else "BALB/C+BLACK/C57"


_GENOTYPE_NORMAL_VALUES = {"WT", "HT", "UNK", "NAN"}


def _normalize_genotype(value) -> str:
    """Normalize a raw genotype value to one of {WT, HT, UNK, NAN}.

    - Real missing values (``NaN``/empty/``-``) are reported as ``NAN`` so the
      reason a row was excluded from the WT/HT groups stays visible.
    - Anything that is not ``WT`` or ``HT`` (and not missing) is reported as
      ``UNK``, matching the labels used by the segmentation workbook.
    """
    if pd.isna(value):
        return "NAN"
    s = str(value).strip().upper()
    if not s or s in {"NAN", "NA", "NONE", "-", "—"}:
        return "NAN"
    if s == "WT":
        return "WT"
    if s == "HT":
        return "HT"
    return "UNK"


def _genotype_group_numeric(mother: str, offspring: str) -> int:
    """Numeric encoding of the (Mother, Offspring) genotype combination.

    Only the three explicitly requested combinations get a non-zero code,
    every other pair (including any UNK/NAN) collapses to 0.
    """
    if mother == "WT" and offspring == "WT":
        return 1
    if mother == "HT" and offspring == "WT":
        return 2
    if mother == "HT" and offspring == "HT":
        return 3
    return 0


def _genotype_binary(value) -> int:
    """Binary encoding for the Mother/Offspring Genotype columns.

    HT -> 1; everything else (WT, UNK, NAN, missing, or any unknown text) -> 0.
    """
    if pd.isna(value):
        return 0
    s = str(value).strip().upper()
    if not s or s in {"NAN", "NA", "NONE", "-", "—"}:
        return 0
    return 1 if s == "HT" else 0


def _supplement_flag(value) -> Optional[int]:
    if pd.isna(value):
        return None
    s = str(value).strip().lower()
    if not s or s in {"nan", "none", "-", "—"}:
        return None
    if s in {"0", "false", "no", "ללא תיסוף"}:
        return 0
    if s in {"1", "true", "yes", "עם תיסוף"}:
        return 1
    return None


def enrich_segmentation_columns(
    file_path: str,
    year: str,
    logger: Optional[logging.Logger] = None,
    *,
    include_syllable_classification_columns: bool = True,
) -> str:
    """Add enrichment columns to the segmentation Excel file.

    Reads the Excel produced by the earlier pipeline steps (segmentation,
    basic features, classification), computes the columns specified in
    Issue #5, reorders to ``FINAL_COLUMN_ORDER``, and writes back.

    Args:
        file_path: Path to the segmentation Excel file (will be updated).
        year: Recording year (fallback when Path is unavailable).
        logger: Optional logger instance.
        include_syllable_classification_columns: If False, drop CNN-derived syllable
            columns and omit them from the final column order (segmentation-only run).

    Returns:
        Path to the updated Excel file.
    """
    if logger:
        logger.info("Enriching segmentation columns")

    df = pd.read_excel(file_path, engine="openpyxl")

    if not include_syllable_classification_columns:
        for c in SYLLABLE_CLASSIFICATION_OUTPUT_COLUMNS:
            if c in df.columns:
                df.drop(columns=[c], inplace=True)

    # 1. Row index (1-based serial ID)
    df["Index"] = range(1, len(df) + 1)

    # 2. Year — derive from Path when possible
    if "Path" in df.columns:
        df["Year"] = df["Path"].apply(
            lambda p: str(p).split("/")[1] if "/" in str(p) else year
        )
    else:
        df["Year"] = year

    # 3. Mother Genotype (binary): HT → 1, anything else (WT/UNK/NAN/...) → 0
    df["Mother Genotype (binary)"] = df["Mother Genotype"].apply(_genotype_binary)

    # 4. Offspring Genotype (binary): HT → 1, anything else (WT/UNK/NAN/...) → 0
    df["Offspring Genotype (binary)"] = df["Offspring Genotype"].apply(_genotype_binary)

    # 4b. Genotype Group (Issue #2): combined Mother+Offspring label and
    #     numeric encoding (WT-WT=1, HT-WT=2, HT-HT=3, anything else 0).
    _mother_norm = df["Mother Genotype"].apply(_normalize_genotype)
    _offspring_norm = df["Offspring Genotype"].apply(_normalize_genotype)
    df["Genotype Group"] = _mother_norm.str.cat(_offspring_norm, sep="-")
    df["Genotype Group (numeric)"] = [
        _genotype_group_numeric(m, o)
        for m, o in zip(_mother_norm, _offspring_norm)
    ]

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
    path_has_sup = (
        df["Path"].astype(str).str.contains("sup", case=False, na=False)
        if "Path" in df.columns
        else pd.Series(False, index=df.index)
    )
    df["Supplement (Mother)"] = (
        df["Mother"].astype(str)
        .str.contains("sup", case=False, na=False)
        .astype(int) | path_has_sup.astype(int)
    )

    # 7b. Supplement (Offspring): metadata value first, fallback to name contains "sup"
    if "Supplement (Offspring)" in df.columns:
        parsed = df["Supplement (Offspring)"].apply(_supplement_flag)
        fallback = (
            df["Name"].astype(str).str.contains("sup", case=False, na=False).astype(int)
            | path_has_sup.astype(int)
        )
        df["Supplement (Offspring)"] = parsed.fillna(fallback).astype(int)
    else:
        df["Supplement (Offspring)"] = (
            df["Name"].astype(str)
            .str.contains("sup", case=False, na=False)
            .astype(int) | path_has_sup.astype(int)
        )

    # 8–9. Syllable type / complexity (require CNN ``Syllable number`` column)
    if include_syllable_classification_columns:
        if "Syllable number" in df.columns:
            df["Syllable type"] = df["Syllable number"].map(SYLLABLE_TYPE_MAP)
        else:
            df["Syllable type"] = None

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

    # 10. Strain by year
    df["Strain"] = df["Year"].apply(_strain_label_from_year)

    # Reorder: known columns first (in spec order), then any extras
    col_order = (
        FINAL_COLUMN_ORDER
        if include_syllable_classification_columns
        else [c for c in FINAL_COLUMN_ORDER if c not in SYLLABLE_CLASSIFICATION_OUTPUT_COLUMNS]
    )
    ordered = [c for c in col_order if c in df.columns]
    extras = [c for c in df.columns if c not in FINAL_COLUMN_ORDER]
    df = df[ordered + extras]

    df.to_excel(file_path, index=False, engine="openpyxl")

    if logger:
        logger.info(
            f"Enrichment complete: {len(df)} rows, {len(df.columns)} columns "
            f"in {file_path}"
        )

    return file_path
