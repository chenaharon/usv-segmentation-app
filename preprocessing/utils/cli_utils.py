import argparse
import logging
from typing import List, Optional


def parse_args() -> argparse.Namespace:
    """Parse command line arguments for the ASD tool pipeline."""
    parser = argparse.ArgumentParser(description="Run ASD tool pipeline")
    parser.add_argument(
        "--metadata-file",
        type=str,
        help="Process a single metadata file (must exist in metadata directory)",
    )
    return parser.parse_args()


def get_files_to_process(
    input_files: List[str],
    metadata_file: Optional[str],
    logger: logging.Logger,
) -> List[str]:
    """
    Determine which files to process based on CLI arguments.
    
    Args:
        input_files: List of all available metadata files
        metadata_file: Optional single file name from CLI
        logger: Logger instance for output
        
    Returns:
        List of file names to process
        
    Raises:
        FileNotFoundError: If metadata_file is specified but not found in input_files
    """
    if metadata_file:
        if metadata_file not in input_files:
            raise FileNotFoundError(
                f"Metadata file '{metadata_file}' not found in metadata directory. "
                f"Available files: {input_files}"
            )
        files_to_process = [metadata_file]
    else:
        files_to_process = input_files
    
    logger.info("Will process %d metadata file(s): %s", len(files_to_process), files_to_process)
    return files_to_process

