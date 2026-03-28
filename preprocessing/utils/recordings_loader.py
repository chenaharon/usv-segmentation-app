from __future__ import annotations

from typing import List, Optional, Tuple

import logging

import librosa

from .audio_paths import resolve_wav_usv_recordings_layout


def load_recordings_from_metadata(
    *,
    year: str,
    mother: List,
    matgen: List,
    name: List,
    pupgen: List,
    age: List,
    session: List,
    rec_num: List,
    sr: int = 250000,
    recordings_root: str = "USV_Recordings",
    logger: Optional[logging.Logger] = None,
) -> Tuple[List, List[str], Optional[int], int]:
    """
    Load audio recordings referenced by the metadata rows.

    For each row i in the metadata lists, this function:
      1) Builds the expected file path (without extension) using the project layout:
         <recordings_root>/<year>/<mother>_<matgen>/<name>_<pupgen>/day_<day>/session<session>/<rec_num>
      2) Resolves the real WAV file by checking both '.wav' and '.WAV'
      3) If found: loads the audio with librosa.load(path, sr=sr), appends:
         - audio waveform -> signals
         - file path       -> paths
         and updates `rate` with the returned sample rate (used later as Fs)
      4) If not found: increments missing_count and logs a warning (then skips the row)

    Returns:
      signals        : list of loaded audio waveforms (one per found recording)
      paths          : list of loaded file paths (aligned with signals by index)
      rate           : sample-rate returned by librosa for the LAST loaded file (None if nothing loaded)
      missing_count  : number of metadata rows that had no matching audio file
    """
    signals: List = []
    paths: List[str] = []
    missing_count = 0
    rate: Optional[int] = None

    n = len(mother)

    if logger:
        logger.info(f"Loading recordings (rows={n})")

    for i in range(n):
        path_obj = resolve_wav_usv_recordings_layout(
            recordings_root,
            year,
            mother[i],
            matgen[i],
            name[i],
            pupgen[i],
            int(age[i]),
            int(session[i]),
            rec_num[i],
        )

        if path_obj is None:
            missing_count += 1
            if logger:
                logger.warning(
                    f"Recording not found (row={i}): {mother[i]}_{name[i]}, "
                    f"day={int(age[i])}, session={int(session[i])}, rec={rec_num[i]}"
                )
            continue

        path = str(path_obj)
        if logger:
            logger.info(f"Loaded recording {len(signals)+1}/{n}: {path}")

        rec, rate = librosa.load(path, sr=sr)
        signals.append(rec)
        paths.append(path)

    if logger:
        logger.info(f"Recordings loaded: {len(signals)}/{n} (missing={missing_count})")

    return signals, paths, rate, missing_count

