"""Profile-photo data URLs stored on contacts.

The database is in-memory SQLite with no file store, so photos travel as
`data:image/...;base64,...` strings. SVG is rejected on purpose: an SVG data
URL can carry script, and we only ever render photos in an `<img>`.
"""

from __future__ import annotations

import base64
import binascii
import re

PHOTO_SUBTYPES = ("jpeg", "png", "gif", "webp")
PHOTO_SUBTYPE_ALIASES = {"jpg": "jpeg"}
MAX_PHOTO_BYTES = 512 * 1024
# ~4/3 expansion of 512 KiB plus the `data:image/...;base64,` prefix.
MAX_PHOTO_DATA_URL_CHARS = 800_000

_PATTERN_SUBTYPES = "|".join((*PHOTO_SUBTYPES, *PHOTO_SUBTYPE_ALIASES))
_DATA_URL = re.compile(
    rf"^data:image/({_PATTERN_SUBTYPES});base64,([A-Za-z0-9+/=\s]+)$",
    re.IGNORECASE,
)


def normalize_photo(value: str | None) -> str | None:
    """Return a canonical data URL, or None. Raises ValueError if the value is unusable."""
    if value is None:
        return None

    stripped = value.strip()
    if not stripped:
        return None

    match = _DATA_URL.fullmatch(stripped)
    if match is None:
        raise ValueError("Photo must be a JPEG, PNG, GIF, or WebP data URL")

    subtype = PHOTO_SUBTYPE_ALIASES.get(match.group(1).lower(), match.group(1).lower())
    payload = re.sub(r"\s+", "", match.group(2))
    try:
        raw = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Photo data is not valid base64") from exc

    if len(raw) > MAX_PHOTO_BYTES:
        raise ValueError("Photo must be 512 KB or smaller")

    if not _matches_declared_subtype(raw, subtype):
        raise ValueError("Photo bytes do not match the declared image type")

    return f"data:image/{subtype};base64,{payload}"


def _matches_declared_subtype(raw: bytes, subtype: str) -> bool:
    """True when the decoded payload's magic bytes match `subtype`."""
    if subtype == "jpeg":
        return raw.startswith(b"\xff\xd8\xff")
    if subtype == "png":
        return raw.startswith(b"\x89PNG\r\n\x1a\n")
    if subtype == "gif":
        return raw.startswith((b"GIF87a", b"GIF89a"))
    if subtype == "webp":
        return len(raw) >= 12 and raw.startswith(b"RIFF") and raw[8:12] == b"WEBP"
    return False
