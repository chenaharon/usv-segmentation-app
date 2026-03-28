from __future__ import annotations

from typing import List, Optional, Tuple

import logging

import os

from utils import (
    METADATA_REQUIRED_COLUMNS,
    extract_year_from_filename,
    read_metadata_as_lists,
    load_recordings_from_metadata,
)


def prepare_recording_metadata(
    *,
    file_name: str,
    metadata_dir: str = "metadata",
    recordings_root: str = "USV_Recordings",
    sr: int = 250000,
    logger: Optional[logging.Logger] = None,
) -> Tuple[
    str,                 # year
    List, List, List, List, List, List, List, List,   # mother..rec_num
    List, List[str], Optional[int], int               # SignalVec, signal_name, rate, missing_count
]:
    """
    Step 1: Prepare inputs for processing a single metadata file.

    - Build the metadata Excel path
    - Extract the year from the filename
    - Read metadata columns as lists
    - Unpack required columns
    - Load WAV recordings into memory (SignalVec) + collect their paths (signal_name)

    The caller is responsible for deciding whether to skip already-processed files.
    """
    metadata_path = os.path.join(metadata_dir, file_name)
    year = extract_year_from_filename(file_name)
    meta = read_metadata_as_lists(metadata_path)

    mother, matgen, name, sex, pupgen, age, session, rec_num = (
        meta[c] for c in METADATA_REQUIRED_COLUMNS
    )

    if logger:
        logger.info(f"Loaded metadata rows={len(mother)} from {metadata_path} (year={year})")

    SignalVec, signal_name, rate, missing_count = load_recordings_from_metadata(
        year=year,
        mother=mother,
        matgen=matgen,
        name=name,
        pupgen=pupgen,
        age=age,
        session=session,
        rec_num=rec_num,
        sr=sr,
        recordings_root=recordings_root,
        logger=logger,
    )

    return (
        year,
        mother, matgen, name, sex, pupgen, age, session, rec_num,
        SignalVec, signal_name, rate, missing_count,
    )

