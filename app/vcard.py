"""Build a vCard 3.0 from a contact snapshot so phones can Save to Contacts."""

from __future__ import annotations

from typing import Any

_PHOTO_TYPE = {
    "jpeg": "JPEG",
    "jpg": "JPEG",
    "png": "PNG",
    "gif": "GIF",
    "webp": "WEBP",
}

_ADR_TYPE = {
    "home": "HOME",
    "work": "WORK",
    "other": "POSTAL",
}


def _escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def _fold(line: str) -> str:
    if len(line) <= 75:
        return line
    chunks = [line[:75]]
    rest = line[75:]
    while rest:
        chunks.append(" " + rest[:74])
        rest = rest[74:]
    return "\r\n".join(chunks)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _adr_line(row: dict[str, Any]) -> str | None:
    street = _escape(_text(row.get("address")) or "")
    city = _escape(_text(row.get("city")) or "")
    region = _escape(_text(row.get("state")) or "")
    postal = _escape(_text(row.get("postal_code")) or "")
    country = _escape(_text(row.get("country")) or "")
    if not any((street, city, region, postal, country)):
        return None
    kind = _ADR_TYPE.get(str(row.get("type") or "").lower(), "POSTAL")
    return f"ADR;TYPE={kind}:;;{street};{city};{region};{postal};{country}"


def _photo_line(data_url: str) -> str | None:
    if not data_url.lower().startswith("data:image/") or ";base64," not in data_url:
        return None
    header, payload = data_url.split(";base64,", 1)
    subtype = header.rsplit("/", 1)[-1].lower().split("+", 1)[0]
    type_name = _PHOTO_TYPE.get(subtype)
    if type_name is None:
        return None
    blob = "".join(payload.split())
    if not blob:
        return None
    return f"PHOTO;ENCODING=b;TYPE={type_name}:{blob}"


def contact_to_vcard(contact: dict[str, Any]) -> str:
    """Return a CRLF-joined vCard 3.0 document for `contact`."""
    first = _text(contact.get("first_name")) or ""
    last = _text(contact.get("last_name")) or ""
    full = _text(contact.get("full_name")) or f"{first} {last}".strip()

    lines = [
        "BEGIN:VCARD",
        "VERSION:3.0",
        f"N:{_escape(last)};{_escape(first)};;;",
        f"FN:{_escape(full)}",
    ]

    if email := _text(contact.get("email")):
        lines.append(f"EMAIL;TYPE=INTERNET:{_escape(email)}")
    if phone := _text(contact.get("phone")):
        lines.append(f"TEL;TYPE=CELL:{_escape(phone)}")
    if company := _text(contact.get("company")):
        lines.append(f"ORG:{_escape(company)}")
    if title := _text(contact.get("job_title")):
        lines.append(f"TITLE:{_escape(title)}")
    if notes := _text(contact.get("notes")):
        lines.append(f"NOTE:{_escape(notes)}")

    addresses = contact.get("addresses")
    if isinstance(addresses, list) and addresses:
        for row in addresses:
            if isinstance(row, dict) and (line := _adr_line(row)):
                lines.append(line)
    elif line := _adr_line(contact):
        lines.append(line)

    if photo := _text(contact.get("photo")):
        if photo_line := _photo_line(photo):
            lines.append(photo_line)

    lines.append("END:VCARD")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"
