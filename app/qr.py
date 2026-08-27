"""QR codes as inline SVG, so a phone can scan a join or share URL."""

from __future__ import annotations

import segno

MAX_QR_CHARS = 512


def qr_svg(data: str, *, scale: int = 6) -> str:
    """Return an inline SVG QR for `data`. Raises ValueError if it is unusable."""
    payload = data.strip()
    if not payload:
        raise ValueError("QR data must not be blank")
    if len(payload) > MAX_QR_CHARS:
        raise ValueError(f"QR data must be {MAX_QR_CHARS} characters or fewer")
    return segno.make(payload, error="m").svg_inline(scale=scale, border=2)
