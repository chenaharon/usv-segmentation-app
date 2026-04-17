import re
import unicodedata
from pathlib import Path
from typing import List, Optional, Set, Tuple

# Suffix after last "_" treated as genotype (Excel often has "17450L", folder "17450L_WT").
_GENOTYPE_SUFFIX_RE = re.compile(
    r"^(WT|HT|HOM|HET|KO|KI|\+\/\+|\+\/-|-\/-|\+/-|-/\+)$",
    re.I,
)

# One token that is only color words, including compounds like GREEN-RED (must be handled
# before naive \\bRED\\b stripping, which would leave "GREEN-").
_COLOR_COMPOUND_SEGMENT_RE = re.compile(
    r"^(?:RED|BLUE|GREEN|YELLOW|BLACK|WHITE|PURPLE|PINK|ORANGE|VIOLET|CYAN|MAGENTA)"
    r"(?:[-_]?(?:RED|BLUE|GREEN|YELLOW|BLACK|WHITE|PURPLE|PINK|ORANGE|VIOLET|CYAN|MAGENTA))*$",
    re.I,
)

# Folder shorthand not covered by full color names (e.g. ``BLU`` vs ``BLUE``).
_COLOR_NAME_SHORTHAND: Set[str] = frozenset(
    {
        "blu",
        "grn",
        "org",
        "orn",
        "pnk",
        "ylw",
        "blk",
        "wht",
        "gry",
        "brn",
        "pur",
        "vio",
        "cya",
        "mag",
        "tan",
        "lav",
    }
)


def _strip_pup_parenthetical_notes(s: str) -> str:
    return re.sub(r"\s*\([^)]*\)", "", str(s))


def _normalize_pup_label_separators(s: str) -> str:
    """ASCII / Unicode hyphens → '-' so tokenization and keys stay consistent."""
    t = unicodedata.normalize("NFKC", str(s))
    for ch in ("\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2212"):
        t = t.replace(ch, "-")
    return t


def _pup_label_tokens(label: str) -> List[str]:
    """Underscore segments after removing parenthetical notes and SUPP markers."""
    s = _normalize_pup_label_separators(_strip_pup_parenthetical_notes(str(label).strip()))
    s = re.sub(r"\bSUPP?\b", "", s, flags=re.I)
    s = re.sub(r"\s+", "_", s)
    # Unify hyphen only before a digit (14164P-1C, 24277J-2A); keep G-R, GREEN-RED as one token.
    s = re.sub(r"-(?=\d)", "_", s)
    s = s.strip("_-")
    return [p for p in s.split("_") if p]


def _is_trailing_color_or_compound_token(tok: str) -> bool:
    return bool(_COLOR_COMPOUND_SEGMENT_RE.match(tok.strip()))


def _is_trailing_color_shorthand_token(tok: str) -> bool:
    t = str(tok).strip().lower()
    return bool(t) and t in _COLOR_NAME_SHORTHAND


def _is_trailing_genotype_token(tok: str) -> bool:
    return bool(_GENOTYPE_SUFFIX_RE.match(tok.strip()))


def _is_trailing_color_abbrev_token(tok: str) -> bool:
    """
    Lab shorthand for compound colors, e.g. G-R ≈ GREEN-RED, B-G, R-B.
    Only single letters separated by - or / (avoids stripping real ids with digits).
    """
    t = tok.strip()
    if len(t) < 3 or len(t) > 16:
        return False
    parts = re.split(r"[-/]", t)
    if len(parts) < 2:
        return False
    return all(len(p) == 1 and p.isalpha() for p in parts)


def strip_trailing_pup_decorator_tokens(parts: List[str]) -> List[str]:
    """Drop trailing color / compound-color / genotype-only segments (right to left)."""
    out = list(parts)
    while out:
        last = out[-1].strip()
        if (
            _is_trailing_color_or_compound_token(last)
            or _is_trailing_color_abbrev_token(last)
            or _is_trailing_color_shorthand_token(last)
        ):
            out.pop()
            continue
        if _is_trailing_genotype_token(last):
            out.pop()
            continue
        low = last.lower()
        if low in {"sup", "supp", "i"}:
            out.pop()
            continue
        break
    return out


# Pup/cage slot after the mouse line id, e.g. ``1A`` in ``13131J Het SUP 1A red`` → ``13131J-1A``.
_PUP_SLOT_TOKEN_RE = re.compile(r"^\d+[A-Za-z]+$")


def _collapse_mouse_line_and_slot_tokens(parts: List[str]) -> List[str]:
    """
    If decorators were stripped but genotype/markers remain between id and slot
    (e.g. ``Het``, ``SUP``), keep only ``<first>`` and ``<last>`` when ``last`` looks
    like a numeric+letter cage id (``1A``, ``4A``, ``12B``).
    """
    if len(parts) < 3:
        return parts
    first = parts[0].strip()
    last = parts[-1].strip()
    if not first or not last:
        return parts
    if not _PUP_SLOT_TOKEN_RE.fullmatch(last):
        return parts
    if not (re.search(r"\d", first) and re.search(r"[A-Za-z]", first)):
        return parts
    if _GENOTYPE_SUFFIX_RE.match(first):
        return parts
    return [first, last]


def canonical_pup_display_name(label: str) -> str:
    """
    Short pup id for Excel ``Name`` / path output: strip colors (incl. GREEN-RED), genotypes, notes.

    Examples:
      - ``22731O_1A_BLUE`` → ``22731O_1A``
      - ``22731O_4A_GREEN-RED`` → ``22731O_4A``
      - ``22742K_4A_G-R`` (Excel) aligns with folder ``…_GREEN-RED`` → ``22742K_4A``
      - ``14164P-1C (RED)`` → ``14164P_1C`` (underscore; same identity key as hyphen form)
      - ``13131J Het SUP 1A red`` → ``13131J_1A`` (matches Excel ``13131J-1A`` via :func:`pup_identity_key`)
      - ``13131J Het SUP 2A BLU`` → ``13131J_2A`` (shorthand ``BLU`` stripped like ``BLUE``)
    """
    parts = strip_trailing_pup_decorator_tokens(_pup_label_tokens(label))
    parts = _collapse_mouse_line_and_slot_tokens(parts)
    if not parts:
        t = _strip_pup_parenthetical_notes(str(label).strip())
        t = re.sub(r"\s+", " ", t).strip(" -_")
        return t
    base = "_".join(parts)
    base = re.sub(r"[-_]+$", "", base)
    return base.strip(" -_") or str(label).strip()


def _pup_identity_key_core(base: str) -> str:
    """Normalize already-canonical base (no extra canonical_pup_display_name)."""
    s = _normalize_pup_label_separators(str(base).strip())
    if not s:
        return ""
    s = s.replace("-", "_")
    t = s.replace("_", " ")
    m = re.fullmatch(r"([A-Za-z0-9]+)\s+([0-9]+[A-Za-z]?)", t.strip())
    if m:
        return f"{m.group(1)}-{m.group(2)}".upper()
    if "_" in s:
        left, right = s.rsplit("_", 1)
        if _GENOTYPE_SUFFIX_RE.match(right.strip()):
            s = left.strip()
    # Identity keys are used for lookups across folder names and Excel labels.
    # Force uppercase so joins are case-insensitive (e.g. 13128k/13128K, 3a/3A).
    return s.replace(" ", "_").upper()


def pup_identity_key(label: str) -> str:
    """
    Normalize pup label from Excel ``Name`` or from a disk folder name so they can match.

    Examples:
      - ``17450L`` and folder ``17450L_WT`` → ``17450L``
      - ``24277J-2A (J)`` and ``24277J-2A (BLUE) WT-WT-WT`` → ``24277J-2A``
      - ``14164P-1C`` and ``14164P_1C`` → same key
      - ``22742K_4A_G-R`` and path ``…22742K_4A_GREEN-RED…`` → same key (via canonical)
    """
    return _pup_identity_key_core(canonical_pup_display_name(label))


def iter_pup_table_lookup_keys(mother: str, *name_hints: str) -> List[Tuple[str, str]]:
    """
    Ordered (mother, name) keys to try against pup-summary / sex lookups.

    Includes raw hints plus ``pup_identity_key`` variants so Excel rows with color
    suffixes still match folder-based keys.
    """
    m = str(mother).strip()
    mu = m.upper()
    seen: Set[Tuple[str, str]] = set()
    out: List[Tuple[str, str]] = []

    def add_pair(a: str, b: str) -> None:
        b2 = str(b).strip()
        if not b2:
            return
        key = (a, b2)
        if key not in seen:
            seen.add(key)
            out.append(key)

    variants: List[str] = []
    for h in name_hints:
        hs = str(h).strip() if h else ""
        if not hs:
            continue
        if hs not in variants:
            variants.append(hs)
        cd = canonical_pup_display_name(hs)
        if cd and cd not in variants:
            variants.append(cd)

    for nm in variants:
        pk = pup_identity_key(nm)
        for a in (mu, m):
            add_pair(a, nm)
            if pk != nm:
                add_pair(a, pk)
    return out


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

