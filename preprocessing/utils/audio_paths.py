import re
from pathlib import Path
from typing import List, Optional

# Suffix after last "_" treated as genotype (Excel often has "17450L", folder "17450L_WT").
_GENOTYPE_SUFFIX_RE = re.compile(
    r"^(WT|HT|HOM|HET|KO|KI|\+\/\+|\+\/-|-\/-|\+/-|-/\+)$",
    re.I,
)


def pup_identity_key(label: str) -> str:
    """
    Normalize pup label from Excel ``Name`` or from a disk folder name so they can match.

    Examples:
      - ``17450L`` and folder ``17450L_WT`` → ``17450L``
      - ``24277J-2A (J)`` and ``24277J-2A (BLUE) WT-WT-WT`` → ``24277J-2A``
    """
    s = str(label).strip()
    if not s:
        return ""
    if " (" in s:
        s = s.split(" (", 1)[0].strip()
    if "_" in s:
        left, right = s.rsplit("_", 1)
        if _GENOTYPE_SUFFIX_RE.match(right.strip()):
            return left.strip()
    return s


def _append_unique(ordered: List[Path], seen: set, p: Path) -> None:
    if p not in seen:
        seen.add(p)
        ordered.append(p)


def iter_recording_base_candidates(
    search_roots: List[Path],
    mother: str,
    matgen: str,
    name: str,
    pupgen: str,
    day: int,
    session: int,
    rec_num: str,
    *,
    nested_mother_folder: bool,
) -> List[Path]:
    """
    Ordered WAV base paths (no extension) to try.

    If ``nested_mother_folder`` is True, ``search_roots`` are year directories:
    try ``root/<Mother>_<matgen>/<Name>_<pupgen>/...`` and ``root/<Name>_<pupgen>/...``,
    then fuzzy pup folders under ``root/<Mother>_<matgen>`` and ``root``.

    If False, ``search_roots`` already point at ``.../<year>/<Mother>_<matgen>``:
    only ``root/<Name>_<pupgen>/...`` and fuzzy children of ``root``.
    """
    day_part = f"day_{int(day)}"
    sess_part = f"session{int(session)}"
    rec_stem = str(rec_num).strip()
    fold_m = f"{mother}_{matgen}"
    pup_exact = f"{name}_{pupgen}"
    key = pup_identity_key(name)

    ordered: List[Path] = []
    seen: set = set()

    for root in search_roots:
        if nested_mother_folder:
            _append_unique(ordered, seen, root / fold_m / pup_exact / day_part / sess_part / rec_stem)
            _append_unique(ordered, seen, root / pup_exact / day_part / sess_part / rec_stem)
            scan_parents = [root / fold_m, root]
        else:
            _append_unique(ordered, seen, root / pup_exact / day_part / sess_part / rec_stem)
            scan_parents = [root]

        for mid in scan_parents:
            if not mid.is_dir():
                continue
            try:
                children = sorted(mid.iterdir(), key=lambda p: p.name)
            except OSError:
                continue
            for ch in children:
                if not ch.is_dir():
                    continue
                if pup_identity_key(ch.name) != key:
                    continue
                _append_unique(ordered, seen, ch / day_part / sess_part / rec_stem)

    return ordered


def build_recording_base_path(
    recordings_root: str,
    year: str,
    mother: str,
    matgen: str,
    name: str,
    pupgen: str,
    day: int,
    session: int,
    rec_num: str,
) -> Path:
    """
    Build the expected recording path WITHOUT the file extension.

    This project stores recordings in a structured folder layout:
      <recordings_root>/<year>/<mother>_<matgen>/<name>_<pupgen>/day_<day>/session<session>/<rec_num>.(wav|WAV)

    Example (base path, no extension):
      USV_Recordings/2015/08001P_HT/08132N_WT/day_10/session2/T0000001

    Returning a Path (instead of a string) makes it easier and safer to add extensions,
    check file existence, and avoid string formatting duplication.
    """
    return (
        Path(recordings_root)
        / str(year)
        / f"{mother}_{matgen}"
        / f"{name}_{pupgen}"
        / f"day_{int(day)}"
        / f"session{int(session)}"
        / str(rec_num)
    )


def resolve_wav_path(base_path: Path) -> Optional[Path]:
    """
    Resolve the actual WAV file path from a base path (no extension).

    Some datasets use '.wav' and others use '.WAV'. This helper:
      1) checks '<base>.wav'
      2) if not found, checks '<base>.WAV'
      3) returns None if neither exists

    This keeps the main loop clean and avoids duplicating the full path formatting twice.
    """
    wav_lower = base_path.with_suffix(".wav")
    if wav_lower.exists():
        return wav_lower

    wav_upper = base_path.with_suffix(".WAV")
    if wav_upper.exists():
        return wav_upper

    return None


def resolve_wav_under_year_folder(
    year_root: Path,
    mother: str,
    matgen: str,
    name: str,
    pupgen: str,
    day: int,
    session: int,
    rec_num: str,
) -> Optional[Path]:
    """
    Client layout: WAVs live under a single year folder (no ``USV_Recordings`` prefix)::

        year_root/<Mother>_<matgen>/<Name>_<pupgen>/day_<d>/session<s>/<rec>

    Also tries without the mother folder segment, and matches pup folders by
    :func:`pup_identity_key` when the Excel ``Name`` does not match the dirname
    (e.g. ``17450L`` vs ``17450L_WT``, or ``24277J-2A (J)`` vs ``24277J-2A (BLUE) ...``).
    """
    roots: List[Path] = [year_root]
    # Some exports add an extra nested year directory: <selected>/<year>/<Mother_...>/...
    try:
        nested_year_dirs = sorted(
            p for p in year_root.iterdir() if p.is_dir() and re.fullmatch(r"\d{4}", p.name)
        )
        roots.extend(nested_year_dirs)
    except OSError:
        pass

    for base in iter_recording_base_candidates(
        roots,
        mother,
        matgen,
        name,
        pupgen,
        day,
        session,
        rec_num,
        nested_mother_folder=True,
    ):
        w = resolve_wav_path(base)
        if w is not None:
            return w.resolve()
    return None


def resolve_wav_usv_recordings_layout(
    recordings_root: str,
    year: str,
    mother: str,
    matgen: str,
    name: str,
    pupgen: str,
    day: int,
    session: int,
    rec_num: str,
) -> Optional[Path]:
    """
    Resolve WAV under ``<recordings_root>/<year>/<Mother>_<matgen>/...`` with the same
    pup-folder fuzzy matching as :func:`resolve_wav_under_year_folder`.
    """
    root = Path(recordings_root) / str(year) / f"{mother}_{matgen}"
    for base in iter_recording_base_candidates(
        [root],
        mother,
        matgen,
        name,
        pupgen,
        day,
        session,
        rec_num,
        nested_mother_folder=False,
    ):
        w = resolve_wav_path(base)
        if w is not None:
            return w.resolve()
    return None


def resolve_recording_wav(
    year: str,
    mother: str,
    matgen: str,
    name: str,
    pupgen: str,
    day: int,
    session: int,
    rec_num: str,
    *,
    year_folder: Optional[Path] = None,
) -> Optional[Path]:
    """
    Resolve a recording WAV for syllable classification / metadata.

    If ``year_folder`` is set (GUI client layout), try that first; otherwise use
    ``USV_Recordings/<year>/...`` relative to the current working directory.
    """
    if year_folder is not None:
        w = resolve_wav_under_year_folder(
            year_folder, mother, matgen, name, pupgen, day, session, rec_num
        )
        if w is not None:
            return w
    root = Path("USV_Recordings") / str(year) / f"{mother}_{matgen}"
    for base in iter_recording_base_candidates(
        [root],
        mother,
        matgen,
        name,
        pupgen,
        day,
        session,
        rec_num,
        nested_mother_folder=False,
    ):
        w = resolve_wav_path(base)
        if w is not None:
            return w
    return None

