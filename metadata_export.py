"""
Build the per-recording metadata Excel (paths, status, optional syllable counts).
Used for metadata-only runs and combined with full pipeline outputs.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import pandas as pd


@dataclass
class MetadataRow:
    year: str
    metadata_file: str
    mother: str
    mother_genotype: str
    name: str
    sex: str
    offspring_genotype: str
    day: Any
    session: Any
    recording_number: Any
    wav_absolute_path: str
    path_column_style: str
    status: str
    syllable_count: Optional[int] = None


def _meta_row_dict(r: MetadataRow) -> Dict[str, Any]:
    d = {
        "Year": r.year,
        "Metadata file": r.metadata_file,
        "Mother": r.mother,
        "Mother Genotype": r.mother_genotype,
        "Name": r.name,
        "Sex": r.sex,
        "Offspring Genotype": r.offspring_genotype,
        "Day": r.day,
        "Session": r.session,
        "Recording Number": r.recording_number,
        "Recording file (absolute path)": r.wav_absolute_path,
        "Path (Excel style)": r.path_column_style,
        "Status": r.status,
    }
    if r.syllable_count is not None:
        d["Syllable count"] = r.syllable_count
    else:
        d["Syllable count"] = ""
    return d


def save_metadata_inventory(path: str, rows: List[MetadataRow]) -> str:
    df = pd.DataFrame([_meta_row_dict(r) for r in rows])
    df.to_excel(path, index=False, engine="openpyxl")
    return path


PROCESSING_SUMMARY_COLUMNS = [
    "Year",
    "Total mice (pups)",
    "Total recordings",
    "Total syllables",
    "Mice with syllables detected",
    "Recordings with syllables",
]


def save_processing_summary_workbook(path: str, rows: List[Dict[str, Any]]) -> str:
    """Write per-year processing stats (English headers). *rows* keys match PROCESSING_SUMMARY_COLUMNS."""
    df = pd.DataFrame(rows)
    for col in PROCESSING_SUMMARY_COLUMNS:
        if col not in df.columns:
            df[col] = "" if col == "Year" else 0
    df = df[PROCESSING_SUMMARY_COLUMNS]
    df.to_excel(path, index=False, engine="openpyxl")
    return path


def merge_syllable_counts_from_excel(
    rows: List[MetadataRow],
    syllable_xlsx_path: str,
    path_column_name: str = "Path",
) -> None:
    """Fill syllable counts by grouping rows in the enriched segmentation workbook."""
    df = pd.read_excel(syllable_xlsx_path, sheet_name=0, engine="openpyxl")
    if path_column_name not in df.columns:
        return
    counts = df.groupby(path_column_name).size().to_dict()
    path_to_row = {(r.path_column_style or ""): r for r in rows}
    for p, r in path_to_row.items():
        if p in counts:
            r.syllable_count = int(counts[p])
