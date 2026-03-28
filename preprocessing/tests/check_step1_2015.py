"""
Smoke test for Step 1 (prepare_recording_metadata) using 2015 metadata files.

This script validates that Step 1 of the pipeline works correctly by:
- Finding a metadata file from year 2015 that hasn't been processed yet
- Loading the metadata and all available audio recordings
- Printing a summary with statistics (rows, loaded, missing, rate)

How to run:
    source .venv/bin/activate
    python preprocessing/tests/check_step1_2015.py

What success looks like:
    - The script finds a 2015 metadata file
    - Metadata is loaded successfully (rows count is printed)
    - Some recordings are loaded (loaded count > 0)
    - Sample rate is printed (rate=250000, not None)
    - First and last recording paths are printed
    - SignalVec contains audio data in memory (length matches loaded count)
    - No errors or exceptions during execution

Note: It's normal to see warnings about missing recordings - not all recordings
      in the metadata file may exist in the file system.
"""

import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils import (
    setup_logger,
    list_metadata_files,
    is_already_processed,
    extract_year_from_filename,
)
from steps import prepare_recording_metadata

# Only test metadata files that match this year
TARGET_METADATA_YEAR = "2015"


def main() -> None:
    logger = setup_logger()

    metadata_dir = "metadata"
    outputs_dir = "outputs"
    recordings_root = "USV_Recordings"
    sr = 250000

    files = list_metadata_files(metadata_dir)
    logger.info("STEP1 CHECK | found %d metadata file(s)", len(files))
    logger.info("STEP1 CHECK | target_year=%s", TARGET_METADATA_YEAR)

    # Find the first metadata file from the target year that is NOT already processed
    for file_name in files:
        year = extract_year_from_filename(file_name)
        if year != TARGET_METADATA_YEAR:
            continue

        if is_already_processed(file_name, outputs_dir):
            logger.info("STEP1 CHECK | skip already processed: %s", file_name)
            continue

        (
            year,
            mother, matgen, name, sex, pupgen, age, session, rec_num,
            SignalVec, signal_name, rate, missing_count,
        ) = prepare_recording_metadata(
            file_name=file_name,
            metadata_dir=metadata_dir,
            recordings_root=recordings_root,
            sr=sr,
            logger=logger,
        )

        logger.info(
            "STEP1 CHECK | file=%s | year=%s | rows=%d | loaded=%d | missing=%d | rate=%s",
            file_name,
            year,
            len(mother),
            len(SignalVec),
            missing_count,
            rate,
        )

        if signal_name:
            logger.info("STEP1 CHECK | first_path=%s", signal_name[0])
            logger.info("STEP1 CHECK | last_path=%s", signal_name[-1])
            logger.info("STEP1 CHECK | SignalVec length=%d (audio data loaded in memory)", len(SignalVec))
            logger.info("STEP1 CHECK | First signal shape=%s", SignalVec[0].shape if SignalVec else "N/A")
        else:
            logger.warning("STEP1 CHECK | no recordings loaded (signal_name is empty)")

        # Only test one file
        return

    logger.warning(
        "STEP1 CHECK | no unprocessed metadata file found for year=%s",
        TARGET_METADATA_YEAR,
    )


if __name__ == "__main__":
    main()
