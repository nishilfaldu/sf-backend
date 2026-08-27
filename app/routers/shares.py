from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.lan import lan_ipv4_addresses
from app.qr import MAX_QR_CHARS, qr_svg
from app.routers.contacts import CONTACT_ID, NOT_FOUND, _get_or_404
from app.schemas import ContactRead, ErrorResponse, LanStatus, ShareCreated
from app.shares import create_share, get_share
from app.vcard import contact_to_vcard

router = APIRouter(prefix="/api/v1", tags=["shares"])

TOKEN = Path(
    description="Token returned by `POST /api/v1/contacts/{id}/share`.",
    min_length=4,
    max_length=64,
    examples=["aB3xY9_k"],
)

SHARE_NOT_FOUND = {
    "model": ErrorResponse,
    "description": "No live share exists for that token (unknown, or it expired).",
    "content": {"application/json": {"example": {"detail": "Share aB3xY9_k not found"}}},
}

_VCARD_MEDIA = "text/vcard; charset=utf-8"


def _snapshot(contact) -> dict:
    return ContactRead.model_validate(contact).model_dump(mode="json")


def _vcard_response(contact: dict, filename: str) -> Response:
    body = contact_to_vcard(contact)
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in filename) or "contact"
    return Response(
        content=body,
        media_type=_VCARD_MEDIA,
        headers={"Content-Disposition": f'attachment; filename="{safe}.vcf"'},
    )


@router.get(
    "/lan",
    response_model=LanStatus,
    operation_id="getLanStatus",
    summary="List LAN addresses",
    response_description="IPv4 addresses peers on the same Wi-Fi can use, plus how this process is bound.",
    tags=["meta"],
)
def get_lan_status() -> LanStatus:
    """
    Return the IPv4 addresses this machine is reachable on from the local network.

    The contacts UI uses this to print a join URL and QR code. Phones should open
    the Next.js app (port 3000), not this API port — the web server talks to us
    on localhost. An empty `addresses` list means we could not find a non-loopback
    interface (the host is offline, or Wi-Fi is down).
    """
    settings = get_settings()
    return LanStatus(
        addresses=lan_ipv4_addresses(),
        bind_host=settings.host,
        bind_port=settings.port,
    )


@router.get(
    "/qr",
    operation_id="getQrSvg",
    summary="Encode a QR code",
    response_description="An inline SVG QR code for the given payload.",
    responses={
        status.HTTP_200_OK: {
            "content": {"image/svg+xml": {"schema": {"type": "string"}}},
            "description": "SVG QR code.",
        },
        status.HTTP_422_UNPROCESSABLE_ENTITY: {
            "model": ErrorResponse,
            "description": "The payload was blank or longer than the limit.",
        },
    },
    tags=["meta"],
)
def get_qr(
    data: str = Query(
        description="Text to encode, typically a `http://<lan-ip>:3000/...` join URL.",
        max_length=MAX_QR_CHARS,
        min_length=1,
        examples=["http://192.168.1.42:3000/contacts/"],
    ),
) -> Response:
    """
    Encode `data` as an SVG QR code a phone camera can scan.

    Used by the web app to show a join link and a per-contact share link. The
    payload is limited to 512 characters so this cannot be used as a dump for
    arbitrary documents.
    """
    try:
        svg = qr_svg(data)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return Response(content=svg, media_type="image/svg+xml")


@router.post(
    "/contacts/{contact_id}/share",
    response_model=ShareCreated,
    status_code=status.HTTP_201_CREATED,
    operation_id="createContactShare",
    summary="Share a contact",
    response_description="A token that yields a snapshot of the contact for 30 minutes.",
    responses={status.HTTP_404_NOT_FOUND: NOT_FOUND},
    tags=["contacts"],
)
def share_contact(
    contact_id: int = CONTACT_ID,
    db: Session = Depends(get_db),
) -> ShareCreated:
    """
    Snapshot a contact into a short-lived share token.

    The token is random, unguessable, and expires after 30 minutes. It is stored
    only in this process — restarting the API forgets every share, same as the
    in-memory database. Recipients fetch `GET /api/v1/shares/{token}`.
    """
    contact = _get_or_404(db, contact_id)
    share = create_share(_snapshot(contact))
    return ShareCreated(token=share.token, expires_at=share.expires_at, contact_id=contact.id)


@router.get(
    "/contacts/{contact_id}/vcard",
    operation_id="getContactVCard",
    summary="Download a contact as a vCard",
    response_description="A vCard 3.0 file the phone can add to its address book.",
    responses={
        status.HTTP_200_OK: {
            "content": {"text/vcard": {"schema": {"type": "string"}}},
            "description": "vCard 3.0 attachment.",
        },
        status.HTTP_404_NOT_FOUND: NOT_FOUND,
    },
    tags=["contacts"],
)
def contact_vcard(
    contact_id: int = CONTACT_ID,
    db: Session = Depends(get_db),
) -> Response:
    """
    Return the live contact as a `.vcf` download.

    Phones treat `text/vcard` as "Add to Contacts". Photos travel as vCard
    `PHOTO` entries when the stored value is a JPEG/PNG/GIF/WebP data URL.
    """
    contact = _get_or_404(db, contact_id)
    snapshot = _snapshot(contact)
    return _vcard_response(snapshot, snapshot.get("full_name") or f"contact-{contact_id}")


@router.get(
    "/shares/{token}",
    response_model=ContactRead,
    operation_id="getShare",
    summary="Fetch a shared contact",
    response_description="The contact snapshot captured when the share was created.",
    responses={status.HTTP_404_NOT_FOUND: SHARE_NOT_FOUND},
)
def read_share(token: str = TOKEN) -> dict:
    """
    Return the contact snapshot for a still-valid share token.

    This is a copy taken at share time, not a live read — later edits do not
    change what the recipient sees. Unknown or expired tokens return `404`.
    """
    share = get_share(token)
    if share is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Share {token} not found")
    return share.contact


@router.get(
    "/shares/{token}/vcard",
    operation_id="getShareVCard",
    summary="Download a shared contact as a vCard",
    response_description="A vCard 3.0 file built from the share snapshot.",
    responses={
        status.HTTP_200_OK: {
            "content": {"text/vcard": {"schema": {"type": "string"}}},
            "description": "vCard 3.0 attachment.",
        },
        status.HTTP_404_NOT_FOUND: SHARE_NOT_FOUND,
    },
)
def share_vcard(token: str = TOKEN) -> Response:
    """
    Return the share snapshot as a `.vcf` download.

    Same body as `GET /api/v1/shares/{token}`, encoded so a phone can save it
    without creating a second record in this app's database.
    """
    share = get_share(token)
    if share is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Share {token} not found")
    name = str(share.contact.get("full_name") or token)
    return _vcard_response(share.contact, name)
