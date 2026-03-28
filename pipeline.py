from __future__ import annotations

import gc
import os
import re
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import librosa

from metadata_export import MetadataRow, merge_syllable_counts_from_excel, save_metadata_inventory


ProgressFn = Callable[..., None]


@dataclass
class RunSummary:
    """Aggregated run statistics for UI summary."""

    metadata_rows_scanned: int = 0
    wav_files_found: int = 0
    wav_segmentation_succeeded: int = 0
    wav_segmentation_failed: int = 0
    recordings_with_zero_syllables: int = 0
    total_syllable_rows: int = 0
    years_processed: List[str] = field(default_factory=list)
    output_files: List[str] = field(default_factory=list)
    error_messages: List[str] = field(default_factory=list)
    classification_model_path: Optional[str] = None

    def merge(self, other: "RunSummary") -> None:
        self.metadata_rows_scanned += other.metadata_rows_scanned
        self.wav_files_found += other.wav_files_found
        self.wav_segmentation_succeeded += other.wav_segmentation_succeeded
        self.wav_segmentation_failed += other.wav_segmentation_failed
        self.recordings_with_zero_syllables += other.recordings_with_zero_syllables
        self.total_syllable_rows += other.total_syllable_rows
        self.years_processed.extend(other.years_processed)
        self.output_files.extend(other.output_files)
        self.error_messages.extend(other.error_messages)
        if other.classification_model_path is not None:
            self.classification_model_path = other.classification_model_path

    def format_report(self) -> str:
        lines = [
            "Run summary",
            f"  Years processed: {', '.join(self.years_processed) or '(none)'}",
            f"  Metadata rows scanned: {self.metadata_rows_scanned}",
            f"  WAV files resolved: {self.wav_files_found}",
            f"  Segmentation OK: {self.wav_segmentation_succeeded}",
            f"  Segmentation failed: {self.wav_segmentation_failed}",
            f"  Recordings with 0 syllables: {self.recordings_with_zero_syllables}",
            f"  Total syllable rows: {self.total_syllable_rows}",
        ]
        if self.classification_model_path:
            lines.append(f"  CNN model file: {self.classification_model_path}")
        if self.output_files:
            lines.append("  Outputs:")
            for p in self.output_files:
                lines.append(f"    - {p}")
        if self.error_messages:
            lines.append("  Notes:")
            for e in self.error_messages[:10]:
                lines.append(f"    - {e}")
            if len(self.error_messages) > 10:
                lines.append(f"    ... and {len(self.error_messages) - 10} more")
        return "\n".join(lines)


@dataclass
class PipelineOptions:
    root_folder: str
    output_dir: Optional[str] = None
    years: Optional[List[str]] = None
    want_syllables_xlsx: bool = True
    want_metadata_xlsx: bool = True
    metadata_only: bool = False


def _emit_progress(
    fn: ProgressFn,
    p: float,
    msg: str,
    eta_seconds: Optional[float] = None,
) -> None:
    try:
        fn(p, msg, eta_seconds)
    except TypeError:
        fn(p, msg)


def _runtime_base_dir() -> Path:
    frozen_base = getattr(sys, "_MEIPASS", None)
    if frozen_base:
        return Path(frozen_base)
    return Path(__file__).resolve().parent


def _add_preprocessing_to_path(preprocessing_dir: Path) -> None:
    path_str = str(preprocessing_dir)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)


def _scan_audio_files(root: Path) -> List[Path]:
    wav_ext = {".wav", ".wave"}
    return sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in wav_ext)


def _year_folder_name(selected: Path) -> str:
    if selected.name.isdigit() and len(selected.name) == 4:
        return selected.name
    m = re.search(r"(19|20)\d{2}", str(selected))
    return m.group(0) if m else selected.name


def discover_year_roots(user_root: Path) -> List[Tuple[str, Path]]:
    """
    Return list of (year_string, year_folder_path).

    If the selected folder is itself a 4-digit year, return a single pair.
    Otherwise scan immediate subdirectories named as four digits.
    If none match, treat the whole folder as one synthetic year from its name.
    """
    user_root = user_root.resolve()
    if user_root.name.isdigit() and len(user_root.name) == 4:
        return [(user_root.name, user_root)]
    found: List[Tuple[str, Path]] = []
    try:
        for p in sorted(user_root.iterdir()):
            if p.is_dir() and re.fullmatch(r"\d{4}", p.name):
                found.append((p.name, p.resolve()))
    except OSError:
        pass
    if found:
        return found
    return [(_year_folder_name(user_root), user_root)]


def _is_year_only_folder(path: Path) -> bool:
    return path.name.isdigit() and len(path.name) == 4


def _find_metadata_workbooks_client_layout(selected: Path) -> List[Path]:
    sel = selected.resolve()
    root_files: List[Path] = []
    for p in sorted(sel.iterdir()):
        if not p.is_file():
            continue
        if p.suffix.lower() not in (".xlsx", ".xls") or p.name.startswith("~$"):
            continue
        if _is_valid_metadata_workbook(p):
            root_files.append(p)
    if root_files:
        return root_files

    nested: List[Path] = []
    for child in sorted(sel.iterdir()):
        if not child.is_dir():
            continue
        for p in child.iterdir():
            if not p.is_file():
                continue
            if p.suffix.lower() not in (".xlsx", ".xls") or p.name.startswith("~$"):
                continue
            if _is_valid_metadata_workbook(p):
                nested.append(p)
    return sorted(set(nested))


def _is_valid_metadata_workbook(path: Path) -> bool:
    try:
        import pandas as pd
        from utils.io_utils import metadata_columns_satisfied  # type: ignore

        try:
            df = pd.read_excel(path, sheet_name=0, nrows=0, engine="openpyxl")
        except Exception:
            df = pd.read_excel(path, sheet_name=0, nrows=0, engine="xlrd")
        cols = {str(c).strip() for c in df.columns}
        return metadata_columns_satisfied(cols)
    except Exception:
        return False


def _is_pup_summary_workbook(path: Path) -> bool:
    """True for pup tables with Mother + Name + Gender (USV pups / טבלת עכברים style)."""
    try:
        import pandas as pd
        from utils.io_utils import pup_summary_columns_satisfied  # type: ignore

        try:
            df = pd.read_excel(path, sheet_name=0, nrows=0, engine="openpyxl")
        except Exception:
            df = pd.read_excel(path, sheet_name=0, nrows=0, engine="xlrd")
        cols = {str(c).strip() for c in df.columns}
        return pup_summary_columns_satisfied(cols)
    except Exception:
        return False


def _find_pup_summary_workbooks(selected: Path) -> List[Path]:
    """Pup-summary xlsx in the year folder or one nested subfolder (same discovery as metadata)."""
    sel = selected.resolve()
    found: List[Path] = []
    for p in sorted(sel.iterdir()):
        if not p.is_file():
            continue
        if p.suffix.lower() not in (".xlsx", ".xls") or p.name.startswith("~$"):
            continue
        if _is_pup_summary_workbook(p):
            found.append(p)
    for child in sorted(sel.iterdir()):
        if not child.is_dir():
            continue
        for p in sorted(child.iterdir()):
            if not p.is_file():
                continue
            if p.suffix.lower() not in (".xlsx", ".xls") or p.name.startswith("~$"):
                continue
            if _is_pup_summary_workbook(p):
                found.append(p)
    return sorted(set(found))


def _merge_sex_lookups_from_year_folder(selected: Path) -> Dict[Tuple[str, str], str]:
    from utils.io_utils import build_sex_lookup_from_pup_summary_xlsx  # type: ignore

    merged: Dict[Tuple[str, str], str] = {}
    for p in _find_pup_summary_workbooks(selected):
        try:
            merged.update(build_sex_lookup_from_pup_summary_xlsx(str(p)))
        except Exception:
            continue
    return merged


def _resolve_sex_from_pup_tables(
    mother: str,
    name_from_path: str,
    lookup: Dict[Tuple[str, str], str],
) -> str:
    from utils.audio_paths import pup_identity_key  # type: ignore

    if not lookup:
        return _guess_sex(name_from_path)
    m = str(mother).strip()
    mu = m.upper()
    raw = str(name_from_path).strip()
    nk = pup_identity_key(raw)
    for k in ((mu, nk), (m, raw), (mu, raw)):
        if k in lookup:
            return lookup[k]
    return _guess_sex(name_from_path)


def _excel_sex_with_pup_fallback(
    excel_sx: str,
    mother: str,
    name_key: str,
    lookup: Dict[Tuple[str, str], str],
) -> str:
    from utils.io_utils import normalize_sex_cell  # type: ignore

    sx = normalize_sex_cell(excel_sx)
    if sx != "U":
        return sx
    return _resolve_sex_from_pup_tables(mother, name_key, lookup)


def _resolve_dataset_and_metadata(selected: Path) -> Tuple[Optional[Path], Optional[Path]]:
    sel = selected.resolve()
    if sel.parent.name.lower() == "usv_recordings":
        root = sel.parent.parent
        meta = root / "metadata"
        if meta.is_dir():
            return root, meta
    if (sel / "metadata").is_dir() and (sel / "USV_Recordings").is_dir():
        return sel, sel / "metadata"
    if (sel.parent / "metadata").is_dir() and (sel.parent / "USV_Recordings").is_dir():
        return sel.parent, sel.parent / "metadata"
    return None, None


def _load_merged_metadata(metadata_dir: Path, year_hint: str) -> Dict[str, List]:
    from utils import (  # type: ignore
        METADATA_REQUIRED_COLUMNS,
        extract_year_from_filename,
        read_metadata_as_lists,
    )

    files = sorted(
        p
        for p in metadata_dir.iterdir()
        if p.is_file() and p.suffix.lower() in (".xlsx", ".xls") and not p.name.startswith("~$")
    )
    if not files:
        return {}

    matching: List[Path] = []
    for p in files:
        try:
            if extract_year_from_filename(p.name) == year_hint:
                matching.append(p)
        except ValueError:
            continue
    use_files = matching if matching else files

    merged: Dict[str, List] = {c: [] for c in METADATA_REQUIRED_COLUMNS}
    for p in use_files:
        data = read_metadata_as_lists(str(p))
        for c in METADATA_REQUIRED_COLUMNS:
            merged[c].extend(data[c])
    return merged


def _meta_row(meta: Dict[str, List], i: int) -> Tuple[str, str, str, str, str, int, int, str]:
    def g(col: str) -> Any:
        return meta[col][i]

    mother = str(g("Mother")).strip()
    matgen = str(g("Mother Genotype")).strip()
    name = str(g("Name")).strip()
    sex = str(g("Sex")).strip()
    pupgen = str(g("Offspring Genotype")).strip()
    day = _to_int(g("Day"))
    session = _to_int(g("Session"))
    rec = g("Recording Number")
    rec_str = str(rec).strip()
    if rec_str.endswith(".0") and rec_str.replace(".0", "").isdigit():
        rec_str = rec_str[:-2]
    return mother, matgen, name, sex, pupgen, day, session, rec_str


def _to_int(v: Any) -> int:
    if v is None or (isinstance(v, float) and str(v) == "nan"):
        return 0
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int):
        return v
    try:
        return int(float(str(v).strip()))
    except (TypeError, ValueError):
        return 0


def _excel_path_from_resolved_wav(dataset_root: Path, wav: Path, year: str) -> str:
    anchor = (dataset_root / "USV_Recordings" / year).resolve()
    try:
        rel = wav.resolve().relative_to(anchor)
        return f"USV_Recordings/{year}/{rel.as_posix()}"
    except ValueError:
        return f"USV_Recordings/{year}/{wav.name}"


def _excel_path_column(selected: Path, wav_path: Path, year: str) -> str:
    rel = wav_path.relative_to(selected).as_posix()
    return f"USV_Recordings/{year}/{rel}"


def _resolve_model_path() -> Tuple[Optional[Path], List[str]]:
    """
    Find ``model_weights.h6`` regardless of ``os.getcwd()`` (e.g. user output under Downloads).

    Override with env ``USV_MODEL_PATH`` pointing to the file or its parent directory.

    Returns:
        (resolved file path or None, unique list of candidate paths checked, for diagnostics).
    """
    base_dir = _runtime_base_dir()
    app_root = Path(__file__).resolve().parent

    candidates: List[Path] = []

    env = os.environ.get("USV_MODEL_PATH", "").strip()
    if env:
        p = Path(env).expanduser()
        candidates.append(p)
        if p.is_dir():
            candidates.append(p / "model_weights.h6")

    candidates.extend(
        [
            app_root / "models" / "model_weights.h6",
            Path.cwd() / "models" / "model_weights.h6",
            base_dir / "models" / "model_weights.h6",
            base_dir / "preprocessing" / "src" / "models" / "model_weights.h6",
        ]
    )

    tried: List[str] = []
    seen: set[str] = set()
    for path in candidates:
        try:
            label = str(path.expanduser().resolve())
        except OSError:
            label = str(path.expanduser())
        if label not in seen:
            seen.add(label)
            tried.append(label)

    def _is_usable_keras_model_path(p: Path) -> bool:
        q = p.expanduser()
        if not q.exists():
            return False
        if q.is_file():
            return True
        # SavedModel bundle (e.g. folder ``model_weights.h6/`` with saved_model.pb + variables/)
        if q.is_dir() and (q / "saved_model.pb").is_file():
            return True
        return False

    for path in candidates:
        if _is_usable_keras_model_path(path):
            return path.expanduser().resolve(), tried
    return None, tried


def _write_constant_syllable_column(file_path: str, value: int) -> None:
    import openpyxl

    wb = openpyxl.load_workbook(file_path)
    ws = wb.worksheets[0]
    col = ws.max_column + 1
    ws.cell(row=1, column=col).value = "Syllable number"
    for row in range(2, ws.max_row + 1):
        ws.cell(row=row, column=col).value = value
    wb.save(file_path)


def _extract_row_metadata_from_path_layout(
    root: Path, wav_path: Path
) -> Tuple[str, str, str, str, str, int, int, str]:
    rel = wav_path.relative_to(root)
    parts = list(rel.parts)
    folders = parts[:-1] if len(parts) > 1 else []
    stem = wav_path.stem

    mother, matgen = "UnknownMother", "UNK"
    name, pupgen = "UnknownName", "UNK"
    day, session = 0, 0

    if len(folders) >= 4:
        mother, matgen = _split_pair(folders[0], "UnknownMother", "UNK")
        name, pupgen = _split_pair(folders[1], "UnknownName", "UNK")
        day = _extract_number(folders[2])
        session = _extract_number(folders[3])
    elif len(folders) == 3:
        mother, matgen = _split_pair(folders[0], "UnknownMother", "UNK")
        if folders[1].lower().startswith("day"):
            day = _extract_number(folders[1])
            session = _extract_number(folders[2])
        else:
            name, pupgen = _split_pair(folders[1], "UnknownName", "UNK")
            day = _extract_number(folders[2])
    elif len(folders) == 2:
        mother, matgen = _split_pair(folders[0], "UnknownMother", "UNK")
        if folders[1].lower().startswith("day"):
            day = _extract_number(folders[1])
        elif folders[1].lower().startswith("session"):
            session = _extract_number(folders[1])
        else:
            name, pupgen = _split_pair(folders[1], "UnknownName", "UNK")
    elif len(folders) == 1:
        mother, matgen = _split_pair(folders[0], "UnknownMother", "UNK")

    rec_num = stem
    sex = _guess_sex(name)
    return mother, matgen, name, sex, pupgen, day, session, rec_num


def _split_pair(value: str, default_left: str, default_right: str) -> Tuple[str, str]:
    if "_" not in value:
        return default_left, default_right
    left, right = value.split("_", 1)
    return left or default_left, right or default_right


def _extract_number(value: str) -> int:
    m = re.search(r"\d+", str(value))
    return int(m.group(0)) if m else 0


def _guess_sex(name: str) -> str:
    n = name.upper()
    if n.endswith("M") or "_M" in n or "MALE" in n:
        return "M"
    if n.endswith("F") or "_F" in n or "FEMALE" in n:
        return "F"
    return "U"


def _classification_year_root(
    selected: Path,
    year: str,
    dataset_root: Optional[Path],
) -> Path:
    """Directory that contains ``Mother_* / Name_* / day_* / session* / file.wav``."""
    if dataset_root is not None:
        p = (dataset_root / "USV_Recordings" / year).resolve()
        if p.is_dir():
            return p
    return selected.resolve()


def _resolve_wav_under_mother_folder(
    mother_dir: Path,
    m: str,
    mg: str,
    n_: str,
    pg: str,
    d: int,
    ses: int,
    rec: str,
    resolve_wav_path_fn,
) -> Optional[Path]:
    from utils.audio_paths import iter_recording_base_candidates  # type: ignore

    for base in iter_recording_base_candidates(
        [mother_dir],
        m,
        mg,
        n_,
        pg,
        d,
        ses,
        rec,
        nested_mother_folder=True,
    ):
        w = resolve_wav_path_fn(base)
        if w is not None:
            return w.resolve()
    return None


def collect_metadata_inventory_only(
    *,
    selected: Path,
    year: str,
    resolve_wav_path_fn,
    progress: ProgressFn,
    progress_base: float,
    progress_span: float,
) -> Tuple[List[MetadataRow], RunSummary]:
    from utils import read_metadata_as_lists  # type: ignore
    from utils.audio_paths import resolve_wav_under_year_folder  # type: ignore

    summary = RunSummary()
    rows: List[MetadataRow] = []
    sel_resolved = selected.resolve()
    client_metadata_files = _find_metadata_workbooks_client_layout(selected)
    dataset_root, metadata_dir = _resolve_dataset_and_metadata(selected)
    sex_lookup = _merge_sex_lookups_from_year_folder(selected)

    def add_row(
        mf_name: str,
        m: str,
        mg: str,
        n_: str,
        sx: str,
        pg: str,
        d: int,
        ses: int,
        rec: str,
        wav: Optional[Path],
        status: str,
    ) -> None:
        summary.metadata_rows_scanned += 1
        abs_p = str(wav.resolve()) if wav is not None else ""
        path_style = _excel_path_column(selected, wav, year) if wav is not None else ""
        if wav is not None:
            summary.wav_files_found += 1
        rows.append(
            MetadataRow(
                year=year,
                metadata_file=mf_name,
                mother=m,
                mother_genotype=mg,
                name=n_,
                sex=sx,
                offspring_genotype=pg,
                day=d,
                session=ses,
                recording_number=rec,
                wav_absolute_path=abs_p,
                path_column_style=path_style,
                status=status,
            )
        )

    total_rows = 0
    if client_metadata_files:
        for mf in client_metadata_files:
            try:
                data = read_metadata_as_lists(str(mf))
                total_rows += len(data["Mother"])
            except Exception:
                continue
    elif dataset_root is not None and metadata_dir is not None:
        meta = _load_merged_metadata(metadata_dir, year)
        total_rows = len(meta.get("Mother", []))

    done = 0
    if client_metadata_files:
        for mf in client_metadata_files:
            try:
                data = read_metadata_as_lists(str(mf))
            except Exception:
                continue
            n = len(data["Mother"])
            for i in range(n):
                m, mg, n_, sx, pg, d, ses, rec = _meta_row(data, i)
                sx = _excel_sex_with_pup_fallback(sx, m, n_, sex_lookup)
                if mf.parent.resolve() == sel_resolved:
                    wav = resolve_wav_under_year_folder(
                        sel_resolved, m, mg, n_, pg, d, ses, rec
                    )
                else:
                    wav = _resolve_wav_under_mother_folder(
                        mf.parent, m, mg, n_, pg, d, ses, rec, resolve_wav_path_fn
                    )
                if wav is None:
                    add_row(mf.name, m, mg, n_, sx, pg, d, ses, rec, None, "WAV not found")
                else:
                    if _is_year_only_folder(selected):
                        try:
                            wav.relative_to(sel_resolved)
                        except ValueError:
                            done += 1
                            continue
                    add_row(mf.name, m, mg, n_, sx, pg, d, ses, rec, wav, "Found")
                done += 1
                if total_rows > 0:
                    p = progress_base + progress_span * (done / total_rows)
                    _emit_progress(progress, p, f"[{year}] metadata scan {done}/{total_rows}")
    elif dataset_root is not None and metadata_dir is not None:
        from utils.audio_paths import resolve_wav_usv_recordings_layout  # type: ignore

        old_cwd = os.getcwd()
        os.chdir(str(dataset_root))
        try:
            meta = _load_merged_metadata(metadata_dir, year)
            n = len(meta.get("Mother", []))
            for i in range(n):
                m, mg, n_, sx, pg, d, ses, rec = _meta_row(meta, i)
                sx = _excel_sex_with_pup_fallback(sx, m, n_, sex_lookup)
                wav = resolve_wav_usv_recordings_layout(
                    "USV_Recordings", year, m, mg, n_, pg, int(d), int(ses), rec
                )
                if wav is None:
                    add_row("(metadata dir)", m, mg, n_, sx, pg, d, ses, rec, None, "WAV not found")
                else:
                    wav = wav.resolve()
                    if _is_year_only_folder(selected):
                        try:
                            wav.relative_to(sel_resolved)
                        except ValueError:
                            done += 1
                            continue
                    add_row("(metadata dir)", m, mg, n_, sx, pg, d, ses, rec, wav, "Found")
                done += 1
                if n > 0:
                    p = progress_base + progress_span * (done / n)
                    _emit_progress(progress, p, f"[{year}] metadata scan {done}/{n}")
        finally:
            os.chdir(old_cwd)

    return rows, summary


def process_single_year(
    *,
    selected: Path,
    year: str,
    outputs_dir: Path,
    progress: ProgressFn,
    progress_lo: float,
    progress_hi: float,
) -> Tuple[Optional[str], RunSummary, List[MetadataRow]]:
    """
    Run segmentation + features + classification + enrich for one year folder.
    Returns (syllable_xlsx_path or None, summary, inventory rows with syllable counts filled when applicable).
    """
    from utils.audio_paths import resolve_wav_under_year_folder  # type: ignore
    from steps.segmentation import (  # type: ignore
        create_segmentation_workbook,
        segment_single_recording,
        FRAME_LENGTH,
        OVERLAP,
        THRESH,
        HARMONY_TH,
    )
    from steps.read_segmentation import read_segmentation_results  # type: ignore
    from steps.compute_basic_features import compute_basic_features  # type: ignore
    from steps.classification import run_classification  # type: ignore
    from steps.enrich_columns import enrich_segmentation_columns  # type: ignore
    from utils import read_metadata_as_lists  # type: ignore

    summary = RunSummary()
    inventory: List[MetadataRow] = []

    def span_t(p: float) -> float:
        return progress_lo + (progress_hi - progress_lo) * max(0.0, min(1.0, p))

    dataset_root, metadata_dir = _resolve_dataset_and_metadata(selected)
    client_metadata_files = _find_metadata_workbooks_client_layout(selected)
    sex_lookup = _merge_sex_lookups_from_year_folder(selected)

    book, sheet = create_segmentation_workbook()
    audio_paths: List[Path] = []
    mother_r: List = []
    matgen_r: List = []
    name_r: List = []
    sex_r: List = []
    pupgen_r: List = []
    age_r: List = []
    session_r: List = []
    rec_num_r: List = []
    audio_files: List[Path] = []
    total_calls = 0
    last_rate: int = 250000

    times_deque: deque = deque(maxlen=8)
    total_work_units = 1
    work_done = 0

    old_cwd = os.getcwd()
    resolve_wav_path_fn = __import__(
        "utils.audio_paths", fromlist=["resolve_wav_path"]
    ).resolve_wav_path

    try:

        def estimate_eta(extra_units: int = 0) -> Optional[float]:
            if not times_deque or total_work_units <= 0:
                return None
            rem = max(0, total_work_units - work_done - extra_units)
            return float(rem * (sum(times_deque) / len(times_deque)))

        if client_metadata_files:
            total_rows = 0
            for mf in client_metadata_files:
                try:
                    data = read_metadata_as_lists(str(mf))
                    total_rows += len(data["Mother"])
                except Exception:
                    continue
            total_work_units = max(1, total_rows)
            sel_resolved = selected.resolve()
            for mf in client_metadata_files:
                try:
                    data = read_metadata_as_lists(str(mf))
                except Exception:
                    summary.error_messages.append(f"Unreadable metadata: {mf.name}")
                    continue
                n = len(data["Mother"])
                for i in range(n):
                    m, mg, n_, sx, pg, d, ses, rec = _meta_row(data, i)
                    sx = _excel_sex_with_pup_fallback(sx, m, n_, sex_lookup)
                    summary.metadata_rows_scanned += 1
                    if mf.parent.resolve() == sel_resolved:
                        wav = resolve_wav_under_year_folder(
                            sel_resolved, m, mg, n_, pg, d, ses, rec
                        )
                    else:
                        wav = _resolve_wav_under_mother_folder(
                            mf.parent, m, mg, n_, pg, d, ses, rec, resolve_wav_path_fn
                        )
                    if wav is None:
                        inventory.append(
                            MetadataRow(
                                year,
                                mf.name,
                                m,
                                mg,
                                n_,
                                sx,
                                pg,
                                d,
                                ses,
                                rec,
                                "",
                                "",
                                "WAV not found",
                            )
                        )
                        work_done += 1
                        continue
                    wav = wav.resolve()
                    if _is_year_only_folder(selected):
                        try:
                            wav.relative_to(sel_resolved)
                        except ValueError:
                            work_done += 1
                            continue

                    summary.wav_files_found += 1
                    t0 = time.perf_counter()
                    try:
                        signal, rate = librosa.load(str(wav), sr=250000)
                        last_rate = int(rate)
                        calls = segment_single_recording(
                            signal=signal,
                            Fs=rate,
                            frame_length=FRAME_LENGTH,
                            overlap=OVERLAP,
                            thresh=THRESH,
                            harmony_th=HARMONY_TH,
                            signal_file_name=str(wav),
                        )
                    except Exception as exc:
                        summary.wav_segmentation_failed += 1
                        summary.error_messages.append(f"{wav.name}: {exc}")
                        inventory.append(
                            MetadataRow(
                                year,
                                mf.name,
                                m,
                                mg,
                                n_,
                                sx,
                                pg,
                                d,
                                ses,
                                rec,
                                str(wav),
                                _excel_path_column(selected, wav, year),
                                f"Error: {exc}",
                                0,
                            )
                        )
                        work_done += 1
                        continue

                    del signal
                    gc.collect()

                    times_deque.append(time.perf_counter() - t0)
                    work_done += 1
                    summary.wav_segmentation_succeeded += 1
                    if not calls:
                        summary.recordings_with_zero_syllables += 1

                    audio_paths.append(wav)
                    mother_r.append(m)
                    matgen_r.append(mg)
                    name_r.append(n_)
                    sex_r.append(sx)
                    pupgen_r.append(pg)
                    age_r.append(int(d))
                    session_r.append(int(ses))
                    rec_num_r.append(rec)
                    audio_files.append(wav)

                    path_excel = _excel_path_column(selected, wav, year)
                    inventory.append(
                        MetadataRow(
                            year,
                            mf.name,
                            m,
                            mg,
                            n_,
                            sx,
                            pg,
                            d,
                            ses,
                            rec,
                            str(wav),
                            path_excel,
                            "OK",
                            len(calls),
                        )
                    )

                    for call in calls:
                        st, en = float(call[0]), float(call[1])
                        sheet.append(
                            [
                                path_excel,
                                m,
                                mg,
                                n_,
                                sx,
                                pg,
                                int(d),
                                int(ses),
                                rec,
                                st,
                                en,
                                en - st,
                            ]
                        )
                        total_calls += 1

                    eta = estimate_eta()
                    _emit_progress(
                        progress,
                        span_t(0.55 * (work_done / total_work_units)),
                        f"[{year}] Segment {work_done}/{total_work_units}: {wav.name}",
                        eta,
                    )

        elif dataset_root is not None and metadata_dir is not None:
            os.chdir(str(dataset_root))
            meta = _load_merged_metadata(metadata_dir, year)
            n_meta = len(meta.get("Mother", [])) if meta else 0
            total_work_units = max(1, n_meta)
            if n_meta > 0:
                from utils.audio_paths import resolve_wav_usv_recordings_layout  # type: ignore

                for i in range(n_meta):
                    m, mg, n_, sx, pg, d, ses, rec = _meta_row(meta, i)
                    sx = _excel_sex_with_pup_fallback(sx, m, n_, sex_lookup)
                    summary.metadata_rows_scanned += 1
                    wav = resolve_wav_usv_recordings_layout(
                        "USV_Recordings",
                        year,
                        m,
                        mg,
                        n_,
                        pg,
                        int(d),
                        int(ses),
                        rec,
                    )
                    if wav is None:
                        inventory.append(
                            MetadataRow(
                                year,
                                "(metadata)",
                                m,
                                mg,
                                n_,
                                sx,
                                pg,
                                d,
                                ses,
                                rec,
                                "",
                                "",
                                "WAV not found",
                            )
                        )
                        work_done += 1
                        continue
                    wav = wav.resolve()
                    if _is_year_only_folder(selected):
                        try:
                            wav.relative_to(selected.resolve())
                        except ValueError:
                            work_done += 1
                            continue

                    summary.wav_files_found += 1
                    t0 = time.perf_counter()
                    try:
                        signal, rate = librosa.load(str(wav), sr=250000)
                        last_rate = int(rate)
                        calls = segment_single_recording(
                            signal=signal,
                            Fs=rate,
                            frame_length=FRAME_LENGTH,
                            overlap=OVERLAP,
                            thresh=THRESH,
                            harmony_th=HARMONY_TH,
                            signal_file_name=str(wav),
                        )
                    except Exception as exc:
                        summary.wav_segmentation_failed += 1
                        summary.error_messages.append(f"{wav.name}: {exc}")
                        inventory.append(
                            MetadataRow(
                                year,
                                "(metadata)",
                                m,
                                mg,
                                n_,
                                sx,
                                pg,
                                d,
                                ses,
                                rec,
                                str(wav),
                                _excel_path_from_resolved_wav(dataset_root, wav, year),
                                f"Error: {exc}",
                                0,
                            )
                        )
                        work_done += 1
                        continue

                    del signal
                    gc.collect()
                    times_deque.append(time.perf_counter() - t0)
                    work_done += 1
                    summary.wav_segmentation_succeeded += 1
                    if not calls:
                        summary.recordings_with_zero_syllables += 1

                    audio_paths.append(wav)
                    mother_r.append(m)
                    matgen_r.append(mg)
                    name_r.append(n_)
                    sex_r.append(sx)
                    pupgen_r.append(pg)
                    age_r.append(int(d))
                    session_r.append(int(ses))
                    rec_num_r.append(rec)
                    audio_files.append(wav)

                    path_excel = _excel_path_from_resolved_wav(dataset_root, wav, year)
                    inventory.append(
                        MetadataRow(
                            year,
                            "(metadata)",
                            m,
                            mg,
                            n_,
                            sx,
                            pg,
                            d,
                            ses,
                            rec,
                            str(wav),
                            path_excel,
                            "OK",
                            len(calls),
                        )
                    )

                    for call in calls:
                        st, en = float(call[0]), float(call[1])
                        sheet.append(
                            [
                                path_excel,
                                m,
                                mg,
                                n_,
                                sx,
                                pg,
                                int(d),
                                int(ses),
                                rec,
                                st,
                                en,
                                en - st,
                            ]
                        )
                        total_calls += 1

                    eta = estimate_eta()
                    _emit_progress(
                        progress,
                        span_t(0.55 * (work_done / total_work_units)),
                        f"[{year}] Segment {work_done}/{total_work_units}: {wav.name}",
                        eta,
                    )

        if not audio_files:
            os.chdir(old_cwd)
            _emit_progress(progress, span_t(0.05), f"[{year}] WAV scan fallback...")
            wav_list = _scan_audio_files(selected)
            if not wav_list:
                if not inventory and total_calls == 0:
                    raise ValueError(f"[{year}] No WAV files and no usable metadata rows.")
            else:
                total_work_units = max(1, len(wav_list))
                for idx, wav_path in enumerate(wav_list, start=1):
                    summary.metadata_rows_scanned += 1
                    summary.wav_files_found += 1
                    t0 = time.perf_counter()
                    try:
                        signal, rate = librosa.load(str(wav_path), sr=250000)
                        last_rate = int(rate)
                        calls = segment_single_recording(
                            signal=signal,
                            Fs=rate,
                            frame_length=FRAME_LENGTH,
                            overlap=OVERLAP,
                            thresh=THRESH,
                            harmony_th=HARMONY_TH,
                            signal_file_name=str(wav_path),
                        )
                    except Exception as exc:
                        summary.wav_segmentation_failed += 1
                        summary.error_messages.append(f"{wav_path.name}: {exc}")
                        work_done += 1
                        continue

                    del signal
                    gc.collect()
                    times_deque.append(time.perf_counter() - t0)
                    work_done += 1
                    summary.wav_segmentation_succeeded += 1
                    if not calls:
                        summary.recordings_with_zero_syllables += 1

                    m, mg, n_, _, pg, d, ses, rec = _extract_row_metadata_from_path_layout(
                        selected, wav_path
                    )
                    sx = _resolve_sex_from_pup_tables(m, n_, sex_lookup)
                    audio_paths.append(wav_path)
                    mother_r.append(m)
                    matgen_r.append(mg)
                    name_r.append(n_)
                    sex_r.append(sx)
                    pupgen_r.append(pg)
                    age_r.append(d)
                    session_r.append(ses)
                    rec_num_r.append(rec)
                    audio_files.append(wav_path)
                    path_excel = _excel_path_column(selected, wav_path, year)
                    inventory.append(
                        MetadataRow(
                            year,
                            "(scan)",
                            m,
                            mg,
                            n_,
                            sx,
                            pg,
                            d,
                            ses,
                            rec,
                            str(wav_path.resolve()),
                            path_excel,
                            "OK",
                            len(calls),
                        )
                    )
                    for call in calls:
                        st, en = float(call[0]), float(call[1])
                        sheet.append(
                            [
                                path_excel,
                                m,
                                mg,
                                n_,
                                sx,
                                pg,
                                d,
                                ses,
                                rec,
                                st,
                                en,
                                en - st,
                            ]
                        )
                        total_calls += 1
                    eta = estimate_eta()
                    _emit_progress(
                        progress,
                        span_t(0.55 * (idx / total_work_units)),
                        f"[{year}] Segment {idx}/{total_work_units}: {wav_path.name}",
                        eta,
                    )

        try:
            os.chdir(old_cwd)
        except OSError:
            pass

        summary.total_syllable_rows = total_calls

        if total_calls == 0 and not audio_files:
            raise ValueError(f"[{year}] No recordings processed.")

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = outputs_dir / f"segmentation_{year}_{ts}.xlsx"
        outputs_dir.mkdir(parents=True, exist_ok=True)
        _emit_progress(progress, span_t(0.58), f"[{year}] Saving segmentation workbook...")
        book.save(str(output_path))
        out_str = str(output_path.resolve())
        siz = len(audio_paths)

        _emit_progress(progress, span_t(0.62), f"[{year}] Reading segmentation table...")
        (
            mother_syl,
            matgen_syl,
            name_syl,
            sex_syl,
            pupgen_syl,
            age_syl,
            session_syl,
            rec_num_syl,
            start_syl,
            end_syl,
        ) = read_segmentation_results(out_str, logger=None)

        _emit_progress(progress, span_t(0.70), f"[{year}] Computing ISI and frequencies...")
        compute_basic_features(
            file_path=out_str,
            signal_vec=None,
            siz=siz,
            mother=mother_r,
            name=name_r,
            age=age_r,
            session=session_r,
            rec_num=rec_num_r,
            mother_syl=mother_syl,
            name_syl=name_syl,
            age_syl=age_syl,
            session_syl=session_syl,
            rec_num_syl=rec_num_syl,
            start_syl=start_syl,
            end_syl=end_syl,
            rate=last_rate,
            logger=None,
            audio_paths=audio_paths,
        )

        cls_root = _classification_year_root(selected, year, dataset_root)
        model_path, model_tried_paths = _resolve_model_path()
        year_audio = cls_root if cls_root.is_dir() else None

        if model_path is not None:
            summary.classification_model_path = str(model_path.resolve())
            _emit_progress(progress, span_t(0.82), f"[{year}] Running syllable classification (CNN)...")
            try:
                run_classification(
                    file_path=out_str,
                    year=year,
                    model_path=str(model_path),
                    age_syl=age_syl,
                    matgen_syl=matgen_syl,
                    pupgen_syl=pupgen_syl,
                    mother_syl=mother_syl,
                    name_syl=name_syl,
                    sex_syl=sex_syl,
                    session_syl=session_syl,
                    rec_num_syl=rec_num_syl,
                    start_syl=start_syl,
                    end_syl=end_syl,
                    logger=None,
                    year_audio_root=year_audio,
                )
            except Exception as exc:
                summary.error_messages.append(f"Classification: {exc}")
                _write_constant_syllable_column(out_str, 10)
        else:
            tried_txt = "; ".join(model_tried_paths) if model_tried_paths else "(no candidates)"
            summary.error_messages.append(
                "Classification skipped (model_weights.h6 not found). "
                f"Set USV_MODEL_PATH or place the file under segmentation-app/models/. Checked: {tried_txt}"
            )
            _write_constant_syllable_column(out_str, 10)

        _emit_progress(progress, span_t(0.94), f"[{year}] Enriching columns...")
        enrich_segmentation_columns(file_path=out_str, year=year, logger=None)

        merge_syllable_counts_from_excel(inventory, out_str)

        summary.output_files.append(out_str)
        _emit_progress(
            progress,
            span_t(1.0),
            f"[{year}] Done. Syllables: {total_calls}. Output: {out_str}",
            0.0,
        )
        return out_str, summary, inventory

    finally:
        try:
            os.chdir(old_cwd)
        except OSError:
            pass


def run_pipeline(options: PipelineOptions, progress: ProgressFn) -> Tuple[RunSummary, List[str]]:
    """
    Main entry: multi-year aware, optional metadata-only, dual Excel outputs.
    """
    root = Path(options.root_folder).resolve()
    if not root.is_dir():
        raise ValueError(f"Selected folder does not exist: {root}")

    out_dir = Path(options.output_dir).resolve() if options.output_dir else Path.cwd() / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)

    _emit_progress(progress, 0.02, "Initializing preprocessing modules...")
    preprocessing_dir = _runtime_base_dir() / "preprocessing"
    if not preprocessing_dir.exists():
        raise ValueError("Missing `preprocessing` directory next to app files.")
    _add_preprocessing_to_path(preprocessing_dir)

    pairs = discover_year_roots(root)
    if options.years:
        allow = set(options.years)
        pairs = [(y, p) for y, p in pairs if y in allow]
        if not pairs:
            raise ValueError("No matching years after filter.")

    total_summary = RunSummary()
    all_outputs: List[str] = []
    n_years = len(pairs)

    for yi, (year_str, year_path) in enumerate(pairs):
        lo = yi / n_years
        hi = (yi + 1) / n_years
        total_summary.years_processed.append(year_str)

        if options.metadata_only:
            from utils.audio_paths import resolve_wav_path  # type: ignore

            inv_rows, part = collect_metadata_inventory_only(
                selected=year_path,
                year=year_str,
                resolve_wav_path_fn=resolve_wav_path,
                progress=progress,
                progress_base=lo,
                progress_span=hi - lo,
            )
            meta_path = str(out_dir / f"recordings_metadata_{year_str}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx")
            save_metadata_inventory(meta_path, inv_rows)
            total_summary.merge(part)
            total_summary.output_files.append(meta_path)
            all_outputs.append(meta_path)
            _emit_progress(progress, hi, f"Year {year_str} metadata inventory saved.")
            continue

        syllable_path: Optional[str] = None
        inv_rows: List[MetadataRow] = []
        part = RunSummary()

        if options.want_syllables_xlsx:
            syllable_path, part, inv_rows = process_single_year(
                selected=year_path,
                year=year_str,
                outputs_dir=out_dir,
                progress=progress,
                progress_lo=lo,
                progress_hi=hi,
            )
            total_summary.merge(part)
            if syllable_path:
                all_outputs.append(syllable_path)
        else:
            from utils.audio_paths import resolve_wav_path  # type: ignore

            inv_rows, part = collect_metadata_inventory_only(
                selected=year_path,
                year=year_str,
                resolve_wav_path_fn=resolve_wav_path,
                progress=progress,
                progress_base=lo,
                progress_span=(hi - lo) * 0.9,
            )
            total_summary.merge(part)

        if options.want_metadata_xlsx:
            if not inv_rows and syllable_path is None:
                from utils.audio_paths import resolve_wav_path  # type: ignore

                inv_rows, part = collect_metadata_inventory_only(
                    selected=year_path,
                    year=year_str,
                    resolve_wav_path_fn=resolve_wav_path,
                    progress=progress,
                    progress_base=lo + (hi - lo) * 0.5,
                    progress_span=(hi - lo) * 0.5,
                )
                total_summary.merge(part)
            if syllable_path and inv_rows:
                merge_syllable_counts_from_excel(inv_rows, syllable_path)
            meta_path = str(
                out_dir / f"recordings_metadata_{year_str}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            )
            save_metadata_inventory(meta_path, inv_rows)
            total_summary.output_files.append(meta_path)
            all_outputs.append(meta_path)

    _emit_progress(progress, 1.0, "All selected years finished.", 0.0)
    return total_summary, all_outputs


def execute_pipeline(
    folder_path: str,
    progress_callback: ProgressFn,
    *,
    output_dir: Optional[str] = None,
    years: Optional[List[str]] = None,
    want_syllables_xlsx: bool = True,
    want_metadata_xlsx: bool = True,
    metadata_only: bool = False,
) -> Tuple[str, RunSummary]:
    """
    Backward-compatible wrapper. Returns (primary syllable xlsx path or first output, summary).

    ``progress_callback`` may be ``(progress, message)`` or ``(progress, message, eta_seconds)``.
    """
    opts = PipelineOptions(
        root_folder=folder_path,
        output_dir=output_dir,
        years=years,
        want_syllables_xlsx=want_syllables_xlsx,
        want_metadata_xlsx=want_metadata_xlsx,
        metadata_only=metadata_only,
    )

    def _wrap(p: float, msg: str, eta: Optional[float] = None) -> None:
        try:
            progress_callback(p, msg, eta)
        except TypeError:
            progress_callback(p, msg)

    summary, outputs = run_pipeline(opts, _wrap)
    primary = ""
    for p in outputs:
        if "segmentation_" in Path(p).name and p.endswith(".xlsx"):
            primary = p
            break
    if not primary and outputs:
        primary = outputs[0]
    return primary, summary
