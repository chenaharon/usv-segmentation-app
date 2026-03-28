from __future__ import annotations

import glob
import logging
import os
from typing import List, Optional

import numpy as np
import pandas as pd

from legacy.audio_feature_extraction_reduction_by_recording import feature_extraction
from utils import FEATURE_COLUMNS, strain_from_year, replace_extension


def read_segmentation_data(file_path: str) -> pd.DataFrame:
    """Read a segmentation Excel file into a DataFrame."""
    return pd.read_excel(file_path)


def add_strain_column(dataset: pd.DataFrame, year: str) -> pd.DataFrame:
    """Add a Strain column to the DataFrame based on the recording year.

    Uses `strain_from_year` to map the year to a strain identifier
    (1 for 2022 recordings, 2 for all others).
    """
    dataset["Strain"] = strain_from_year(year)
    return dataset


def add_strain_from_path(dataset: pd.DataFrame) -> pd.DataFrame:
    """Add a Strain column by extracting the year from the Path column.

    The Path column contains recording file paths like
    ``USV_Recordings/2022/...``. The second path component is the year.
    """
    dataset["Strain"] = [
        strain_from_year(x.split('/')[1]) for x in dataset["Path"]
    ]
    return dataset


def select_feature_columns(dataset: pd.DataFrame) -> pd.DataFrame:
    """Select only the columns required by the feature extraction pipeline."""
    return dataset[FEATURE_COLUMNS]


def compute_features(X: pd.DataFrame) -> np.ndarray:
    """Run the feature extraction algorithm on the selected columns.

    Groups data by mouse, day, session, and recording, then computes
    per-recording features: average start/end frequencies per syllable type,
    syllable distribution, average duration, mother genotype, pup sex,
    mean ISI time, age, session, strain, offspring genotype, and mouse index.
    """
    return feature_extraction(X)


def save_features_csv(
    mouse_final_data: np.ndarray,
    file_path: str,
) -> str:
    """Save the extracted feature matrix to a CSV file.

    The CSV is saved alongside the source Excel file, with the same
    base name but a .csv extension.

    Returns the path to the saved CSV file.
    """
    output_csv = replace_extension(file_path, ".csv")
    np.savetxt(output_csv, X=mouse_final_data, delimiter=",")
    return output_csv


def load_all_segmentation_files(outputs_dir: str) -> List[str]:
    """Return a list of all segmentation Excel files in the outputs directory."""
    return glob.glob(os.path.join(outputs_dir, "*.xlsx"))


def concat_segmentation_files(file_paths: List[str]) -> pd.DataFrame:
    """Read and concatenate multiple segmentation Excel files into one DataFrame."""
    return pd.concat(
        (pd.read_excel(f) for f in file_paths), ignore_index=True
    )


def save_aggregated_excel(dataset: pd.DataFrame, outputs_dir: str) -> str:
    """Save the combined dataset (all files) as ``all_data.xlsx``.

    Returns the path to the saved Excel file.
    """
    output_path = os.path.join(outputs_dir, "all_data.xlsx")
    dataset.to_excel(output_path, index=False)
    return output_path


def run_feature_extraction(
    file_path: str,
    year: str,
    logger: Optional[logging.Logger] = None,
) -> str:
    """Run feature extraction on a single segmentation Excel file.

    Orchestrates five steps:
    1. Read the segmentation Excel into a DataFrame
    2. Add a Strain column derived from the recording year
    3. Select the feature columns required by the extraction algorithm
    4. Compute per-recording features (frequencies, distribution, duration, etc.)
    5. Save the feature matrix as a CSV file

    Args:
        file_path: Path to the segmentation Excel file
        year: Recording year (used to derive Strain)
        logger: Optional logger instance

    Returns:
        Path to the output CSV file
    """
    if logger:
        logger.info("Feature extraction started")

    dataset = read_segmentation_data(file_path)
    dataset = add_strain_column(dataset, year)
    X = select_feature_columns(dataset)
    mouse_final_data = compute_features(X)
    output_csv = save_features_csv(mouse_final_data, file_path)

    if logger:
        logger.info(f"Feature extraction finished: {output_csv}")

    return output_csv


def run_aggregated_feature_extraction(
    outputs_dir: str,
    logger: Optional[logging.Logger] = None,
) -> str:
    """Aggregate all segmentation Excel files and run feature extraction.

    Orchestrates six steps:
    1. Find all segmentation Excel files in the outputs directory
    2. Concatenate them into a single DataFrame
    3. Add a Strain column derived from the year in each recording Path
    4. Save the combined dataset as ``all_data.xlsx``
    5. Select the feature columns and compute per-recording features
    6. Save the aggregated feature matrix as ``all_data.csv``

    Args:
        outputs_dir: Directory containing the per-file segmentation Excel files
        logger: Optional logger instance

    Returns:
        Path to the aggregated CSV file
    """
    if logger:
        logger.info("Aggregating features from all processed files")

    all_files = load_all_segmentation_files(outputs_dir)
    if logger:
        logger.info(f"Found {len(all_files)} processed file(s)")

    dataset = concat_segmentation_files(all_files)
    dataset = add_strain_from_path(dataset)
    save_aggregated_excel(dataset, outputs_dir)

    X = select_feature_columns(dataset)
    mouse_final_data = compute_features(X)

    output_csv = os.path.join(outputs_dir, "all_data.csv")
    np.savetxt(output_csv, X=mouse_final_data, delimiter=",")

    if logger:
        logger.info(f"Finished aggregating features: {output_csv}")

    return output_csv
