import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
import pandas as pd


def list_metadata_files(metadata_dir: str = "metadata") -> List[str]:
    """
    Returns a sorted list of Excel filenames in the specified directory.
    
    Args:
        metadata_dir: Path to the metadata directory (default: "metadata")
    
    Returns:
        Sorted list of .xlsx/.xls filenames, excluding temporary Excel files
        (those starting with "~$")
    """
    metadata_path = Path(metadata_dir)
    
    # Get all Excel files (.xlsx and .xls)
    excel_files = []
    for file_path in metadata_path.iterdir():
        if file_path.is_file():
            # Check if it's an Excel file
            if file_path.suffix.lower() in ['.xlsx', '.xls']:
                # Skip temporary Excel files (starting with ~$)
                if not file_path.name.startswith('~$'):
                    excel_files.append(file_path.name)
    
    # Return sorted list
    return sorted(excel_files)


def is_segmentation_file_exist(file_name: str, outputs_dir: str = "outputs") -> bool:
    """
    Check if segmentation Excel file exists for a metadata file.
    
    Args:
        file_name: Name of the metadata file (e.g., "Data 2015 For Syl Segmentation_1.xlsx")
        outputs_dir: Path to the outputs directory (default: "outputs")
    
    Returns:
        True if the segmentation Excel file exists, False otherwise
    """
    outputs_path = Path(outputs_dir)
    output_filename = get_output_filename(file_name)
    xlsx_file = outputs_path / output_filename
    return xlsx_file.exists()


def is_already_processed(file_name: str, outputs_dir: str = "outputs") -> bool:
    """
    Check if a metadata file has already been fully processed.

    A file is considered processed if the main Excel output exists and the
    companion CSV exists (``.npy`` is optional — desktop pipeline may skip it).
    """
    outputs_path = Path(outputs_dir)
    output_filename = get_output_filename(file_name)
    output_stem = Path(output_filename).stem

    xlsx_file = outputs_path / output_filename
    csv_file = outputs_path / f"{output_stem}.csv"

    return xlsx_file.exists() and csv_file.exists()


# Required column names from metadata Excel files
# These columns contain essential mouse information needed for processing:
# - Mother: mother mouse identifier
# - Mother Genotype: genetic type of the mother
# - Name: pup mouse identifier
# - Sex: gender of the pup
# - Offspring Genotype: genetic type of the pup
# - Day: age of the mouse in days
# - Session: recording session number
# - Recording Number: unique identifier for each audio recording
METADATA_REQUIRED_COLUMNS = [
    "Mother",
    "Mother Genotype",
    "Name",
    "Sex",
    "Offspring Genotype",
    "Day",
    "Session",
    "Recording Number",
]

def _header_match_key(name: str) -> str:
    """Normalize header for alias lookup (case-insensitive, separator-insensitive)."""
    s = str(name).strip()
    if not s:
        return ""
    s = s.lower()
    for ch in (" ", "\t", "\n", "_", "-", "/", "\\", "(", ")", "[", "]", "{", "}", ".", ",", ":", ";", "|", '"', "'"):
        s = s.replace(ch, "")
    return s


# Alternate Excel headers → canonical METADATA_REQUIRED_COLUMNS (Hebrew lab sheets, typos, etc.)
_METADATA_CANONICAL_ALIASES: Dict[str, Tuple[str, ...]] = {
    "Mother": (
        "Mother",
        "mother",
        "MOTHER",
        "אם",
        "אמא",
        "עכברת אם",
        "אם עכברוש",
    ),
    "Mother Genotype": (
        "Mother Genotype",
        "mother genotype",
        "Maternal genotype",
        "maternal genotype",
        "MATERNAL GENOTYPE",
        "גנוטיפ אם",
        "גנטיקת אם",
        "גנוטיפ האם",
    ),
    "Name": (
        "Name",
        "name",
        "MOUSE NAME",
        "mouse name",
        "שם גור",
        "שם הגור",
        "שם פרטי גור",
        "גור",
        "Pup",
        "pup name",
        "Pup name",
    ),
    "Sex": (
        "Sex",
        "sex",
        "gender",
        "Gender",
        "GENDER",
        "gender/sex",
        "sex/gender",
        "gender sex",
        "sex gender",
        "מין",
        "מגדר",
    ),
    "Offspring Genotype": (
        "Offspring Genotype",
        "offspring genotype",
        "OFFSPRING GENOTYPE",
        "pup genotype",
        "Pup genotype",
        "Genotype",
        "genotype",
        "Genotytpe",
        "גנוטיפ גור",
        "גנטיקת גור",
        "גנוטיפ הצאצא",
    ),
    "Day": (
        "Day",
        "day",
        "יום",
        "גיל",
        "גיל (ימים)",
        "גיל בימים",
    ),
    "Session": (
        "Session",
        "session",
        "סשן",
        "מפגש",
    ),
    "Recording Number": (
        "Recording Number",
        "recording number",
        "Recording number",
        "מספר הקלטה",
        "מספר קובץ",
    ),
}


def _metadata_alias_lookup() -> Dict[str, str]:
    """Map normalized header key → canonical column (first alias wins per key)."""
    out: Dict[str, str] = {}
    for canon, aliases in _METADATA_CANONICAL_ALIASES.items():
        for a in aliases:
            k = _header_match_key(a)
            if k and k not in out:
                out[k] = canon
    return out


def get_metadata_alias_lookup() -> Dict[str, str]:
    return _metadata_alias_lookup()


def _read_excel_with_header_detection(
    metadata_path: str,
    required_columns: Tuple[str, ...],
    max_scan_rows: int = 20,
):
    """
    Read first sheet while detecting header row in the first *max_scan_rows* rows.

    Some lab workbooks place a title row above headers, or use mixed labels
    like ``GENDER/SEX``. We scan early rows and pick the first one that can map
    to all required canonical columns after alias normalization.
    """
    engines = ("openpyxl", "xlrd")
    for engine in engines:
        try:
            probe = pd.read_excel(
                metadata_path,
                sheet_name=0,
                header=None,
                nrows=max_scan_rows,
                engine=engine,
            )
        except Exception:
            continue
        if probe.empty:
            continue
        for ridx in range(min(max_scan_rows, len(probe))):
            raw_headers = [str(v).strip() for v in probe.iloc[ridx].tolist()]
            dummy = pd.DataFrame(columns=raw_headers)
            mapped = normalize_metadata_columns(dummy)
            have = {str(c).strip() for c in mapped.columns}
            if all(req in have for req in required_columns):
                return pd.read_excel(
                    metadata_path,
                    sheet_name=0,
                    header=ridx,
                    engine=engine,
                )
    # Fallback to default header row if no candidate matched.
    for engine in engines:
        try:
            return pd.read_excel(metadata_path, sheet_name=0, engine=engine)
        except Exception:
            continue
    raise ValueError(f"Could not read workbook: {metadata_path}")


def normalize_metadata_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Strip headers and rename known aliases (English / Hebrew) to ``METADATA_REQUIRED_COLUMNS``.

    If the workbook uses Hebrew headers (e.g. ``טבלת עכברים``), this avoids falling back to
    WAV-only scan (which sets ``Sex`` via ``_guess_sex`` → ``U``).
    """
    out = df.copy()
    out.columns = [str(c).strip() for c in out.columns]
    lookup = get_metadata_alias_lookup()
    rename: Dict[str, str] = {}
    assigned = {c for c in out.columns if c in METADATA_REQUIRED_COLUMNS}

    for col in list(out.columns):
        if col in METADATA_REQUIRED_COLUMNS:
            continue
        k = _header_match_key(col)
        if not k or k not in lookup:
            continue
        canon = lookup[k]
        if canon in assigned:
            continue
        rename[col] = canon
        assigned.add(canon)

    return out.rename(columns=rename)


def metadata_columns_satisfied(column_names: Set[str]) -> bool:
    """Return True if *column_names* contains every METADATA_REQUIRED_COLUMNS (after alias rules)."""
    dummy = pd.DataFrame(columns=sorted(column_names))
    normalized = normalize_metadata_columns(dummy)
    have = {str(c).strip() for c in normalized.columns}
    return all(req in have for req in METADATA_REQUIRED_COLUMNS)


# Pup summary workbooks (e.g. ``USV pups 2024 summary…xlsx``, ``טבלת עכברים``): one row per pup,
# Gender column — no per-recording Day/Session/Recording Number. Used to build a Sex lookup
# while WAV layout supplies recording paths (same idea as ``generate_metadata.py`` in mouse-usv-asd-pipeline).
PUP_SUMMARY_REQUIRED_COLUMNS = ("Mother", "Name", "Sex")


def pup_summary_columns_satisfied(column_names: Set[str]) -> bool:
    """True if the sheet has Mother, Name, and Sex (or Gender / GENDER / …) after header normalization."""
    dummy = pd.DataFrame(columns=sorted(column_names))
    normalized = normalize_metadata_columns(dummy)
    have = {str(c).strip() for c in normalized.columns}
    return all(req in have for req in PUP_SUMMARY_REQUIRED_COLUMNS)


def build_sex_lookup_from_pup_summary_xlsx(metadata_path: str) -> Dict[Tuple[str, str], str]:
    """
    Load a pup-summary Excel and return mapping ``(mother, name_key) -> M|F|U``.

    Keys include ``(mother.upper(), pup_identity_key(name))`` and ``(mother, name)`` for exact match.
    """
    from .audio_paths import pup_identity_key

    df = _read_excel_with_header_detection(
        metadata_path,
        PUP_SUMMARY_REQUIRED_COLUMNS,
    )
    df = normalize_metadata_columns(df)
    if not all(c in df.columns for c in PUP_SUMMARY_REQUIRED_COLUMNS):
        return {}
    out: Dict[Tuple[str, str], str] = {}
    for _, row in df.iterrows():
        m = str(row["Mother"]).strip()
        n = str(row["Name"]).strip()
        if not m or not n or m.lower() in ("nan", "none"):
            continue
        if n.lower() in ("nan", "none"):
            continue
        sx = normalize_sex_cell(row["Sex"])
        mu = m.upper()
        nk = pup_identity_key(n)
        out[(mu, nk)] = sx
        out[(m, n)] = sx
    return out


# Column names for segmentation results Excel file
# These are the metadata columns plus segmentation-specific columns
SEGMENTATION_RESULT_COLUMNS = METADATA_REQUIRED_COLUMNS + [
    "Start point(s)",
    "End point(s)",
]

# Column names used by the feature extraction step
FEATURE_COLUMNS = [
    "Name", "Day", "Session",
    "Start Point (Hz)", "End Point (Hz)", "Duration (time)",
    "Syllable number", "Recording Number",
    "Mother Genotype", "Sex", "ISI_time", "Offspring Genotype",
    "Strain",
]

# Year-to-strain mapping: 2022 recordings are strain 1, all others strain 2
STRAIN_YEAR = 2022


def strain_from_year(year) -> int:
    """Return the strain identifier (1 or 2) for a given recording year."""
    return 1 if int(year) == STRAIN_YEAR else 2


def replace_extension(file_path: str, new_ext: str) -> str:
    """Return *file_path* with its extension replaced by *new_ext*.

    >>> replace_extension("outputs/segmentation_2015_1.xlsx", ".csv")
    'outputs/segmentation_2015_1.csv'
    """
    base, _ = os.path.splitext(file_path)
    if not new_ext.startswith('.'):
        new_ext = f'.{new_ext}'
    return base + new_ext


# Regular expression pattern to extract 4-digit year (1900-2099) from filenames
# Used to identify the year from metadata file names (e.g., "metadata_2022.xlsx" -> "2022")
_YEAR_REGEX_PATTERN = re.compile(r"(19|20)\d{2}")


def extract_year_from_filename(file_name: str) -> str:
    """Extract a 4-digit year (e.g., 2015) from the filename."""
    m = _YEAR_REGEX_PATTERN.search(file_name)
    if not m:
        raise ValueError(f"Could not extract year from filename: {file_name}")
    return m.group(0)


def get_output_filename(metadata_file_name: str) -> str:
    """
    Generate output filename from metadata file name.
    
    Converts metadata filename like "Data 2015 For Syl Segmentation_1.xlsx"
    to output filename like "segmentation_2015_1.xlsx"
    
    Args:
        metadata_file_name: Name of the metadata file
    
    Returns:
        Output filename for segmentation/features/classification results
    """
    year = extract_year_from_filename(metadata_file_name)
    
    # Extract the number from the filename (e.g., "_1" from "Segmentation_1.xlsx")
    import re
    number_match = re.search(r'_(\d+)\.xlsx$', metadata_file_name)
    if number_match:
        number = number_match.group(1)
    else:
        # Fallback: use the whole filename stem if no number found
        from pathlib import Path
        stem = Path(metadata_file_name).stem
        number = stem.replace(' ', '_').lower()
    
    return f"segmentation_{year}_{number}.xlsx"


def normalize_sex_cell(value: Any) -> str:
    """
    Map spreadsheet sex values to ``M`` / ``F`` / ``U``.

    Handles empty cells, common English words, and short Hebrew labels.
    """
    if value is None:
        return "U"
    if isinstance(value, float) and pd.isna(value):
        return "U"
    s = str(value).strip()
    if not s or s.lower() in ("nan", "none", "-", "—", "n/a", "na"):
        return "U"
    low = s.lower()
    if low in ("m", "male", "זכר", "גבר"):
        return "M"
    if low in ("f", "female", "נקבה", "אשה"):
        return "F"
    if low in ("u", "unk", "unknown"):
        return "U"
    u = s.upper()
    if u in ("M", "F", "U"):
        return u
    if len(u) == 1 and u in "MFU":
        return u
    return "U"


def read_metadata_as_lists(metadata_path: str) -> Dict[str, List]:
    """
    Read the first sheet of the metadata Excel file and return a dict:
    {column_name: list_of_values}, for METADATA_REQUIRED_COLUMNS only.
    Assumes the first row is a header (matches the metadata files in this project).
    """
    df = _read_excel_with_header_detection(
        metadata_path,
        tuple(METADATA_REQUIRED_COLUMNS),
    )
    df = normalize_metadata_columns(df)

    missing = [c for c in METADATA_REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns in {metadata_path}: {missing}")

    df = df[METADATA_REQUIRED_COLUMNS].dropna(how="all")
    if df.empty:
        raise ValueError(f"No metadata rows found in {metadata_path}")

    out = {c: df[c].tolist() for c in METADATA_REQUIRED_COLUMNS}
    out["Sex"] = [normalize_sex_cell(v) for v in out["Sex"]]
    return out

