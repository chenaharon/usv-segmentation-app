"""One-time Welch checks so PSD/frequency code fails fast instead of after a long run."""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


def welch_sanity_check_signal(signal: Any, rate: int) -> None:
    """
    Run :func:`legacy.features._welch_psd` on typical slices (start, end, short).

    Call once on the first successfully loaded recording. Raises if Welch/SciPy
    rejects parameters that would later break ``StartEndFreq_from_paths``.
    """
    from legacy.features import _welch_psd

    sig = np.asarray(signal, dtype=float).ravel()
    if sig.size == 0:
        raise ValueError("Empty audio signal — cannot validate Welch.")

    r = int(rate)
    slices = (
        sig[:2000],
        sig[max(0, sig.size - 2000) :],
        sig[:400],
        sig[:1],
    )
    for seg in slices:
        if seg.size == 0:
            continue
        out = _welch_psd(seg, r)
        if out is None:
            raise RuntimeError(
                "Welch sanity check: unexpected None PSD for a non-empty segment."
            )
