from __future__ import annotations

from typing import List, Optional, Tuple
import pandas as pd
import logging

from utils import SEGMENTATION_RESULT_COLUMNS


def read_segmentation_results(
    file_path: str,
    logger: Optional[logging.Logger] = None,
) -> Tuple[List, List, List, List, List, List, List, List, List, List, List]:
    """
    Read segmentation results from Excel file.
    
    Reads the segmentation Excel file and returns columns as separate lists.
    Uses column names instead of indices for safety.
    
    Args:
        file_path: Path to the segmentation Excel file
        logger: Optional logger instance for logging
    
    Returns:
        Tuple of 11 lists in this order:
        (path, mother, matgen, name, sex, pupgen, age, session, rec_num, start, end)
    
    Raises:
        FileNotFoundError: If the file doesn't exist
        ValueError: If required columns are missing
    """
    if logger:
        logger.debug(f"Reading segmentation results from {file_path}")
    
    df = pd.read_excel(file_path, sheet_name=0, engine="openpyxl")
    
    # Verify all expected columns exist (excluding 'Path' and 'Duration (time)' which we don't need)
    required_cols = [col for col in SEGMENTATION_RESULT_COLUMNS]
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise ValueError(
            f"Missing required columns in {file_path}: {missing_cols}. "
            f"Found columns: {list(df.columns)}"
        )
    
    # Extract columns in the order they will be returned
    path_col = df["Path"].tolist() if "Path" in df.columns else ["" for _ in range(len(df))]
    mother = df['Mother'].tolist()
    matgen = df['Mother Genotype'].tolist()
    name = df['Name'].tolist()
    sex = df['Sex'].tolist()
    pupgen = df['Offspring Genotype'].tolist()
    age = df['Day'].tolist()
    session = df['Session'].tolist()
    rec_num = df['Recording Number'].tolist()
    start = df['Start point(s)'].tolist()
    end = df['End point(s)'].tolist()
    
    num_rows = len(mother)  # All columns have the same length (one value per row)
    if logger:
        logger.debug(f"Read {num_rows} rows from segmentation file")
    
    return (path_col, mother, matgen, name, sex, pupgen, age, session, rec_num, start, end)

