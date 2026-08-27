from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import Address, Contact
from app.schemas import AddressWrite, ContactCreate, ContactReplace, ContactUpdate

SORTABLE_FIELDS = ("id", "first_name", "last_name", "email", "company", "created_at", "updated_at")


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _with_addresses():
    return selectinload(Contact.addresses)


def _set_addresses(contact: Contact, rows: list[AddressWrite]) -> None:
    contact.addresses.clear()
    contact.addresses.extend(Address(**row.model_dump()) for row in rows)
    # Child-table writes do not dirty Contact columns, so bump updated_at
    # ourselves for address-only PUT/PATCH.
    contact.updated_at = datetime.now(timezone.utc)


def get_contact(db: Session, contact_id: int) -> Contact | None:
    stmt = select(Contact).options(_with_addresses()).where(Contact.id == contact_id)
    return db.execute(stmt).scalar_one_or_none()


def get_contact_by_email(db: Session, email: str) -> Contact | None:
    stmt = select(Contact).where(func.lower(Contact.email) == _normalize_email(email))
    return db.execute(stmt).scalar_one_or_none()


def count_contacts(db: Session) -> int:
    return db.execute(select(func.count()).select_from(Contact)).scalar_one()


def list_contacts(
    db: Session,
    *,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
    sort_by: str = "id",
    order: str = "asc",
) -> tuple[list[Contact], int]:
    """Return (page of contacts, total matching count)."""
    stmt = select(Contact)

    if search:
        pattern = f"%{search.strip().lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Contact.first_name).like(pattern),
                func.lower(Contact.last_name).like(pattern),
                func.lower(Contact.email).like(pattern),
                func.lower(func.coalesce(Contact.company, "")).like(pattern),
                func.lower(func.coalesce(Contact.phone, "")).like(pattern),
            )
        )

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()

    if sort_by not in SORTABLE_FIELDS:
        sort_by = "id"
    column = getattr(Contact, sort_by)
    stmt = stmt.options(_with_addresses()).order_by(column.desc() if order == "desc" else column.asc())

    items = db.execute(stmt.limit(limit).offset(offset)).scalars().unique().all()
    return list(items), total


def create_contact(db: Session, payload: ContactCreate) -> Contact:
    data = payload.model_dump(exclude={"addresses"})
    data["email"] = _normalize_email(data["email"])
    contact = Contact(**data)
    _set_addresses(contact, payload.addresses)
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return contact


def replace_contact(db: Session, contact: Contact, payload: ContactReplace) -> Contact:
    data = payload.model_dump(exclude={"addresses"})
    for field, value in data.items():
        setattr(contact, field, _normalize_email(value) if field == "email" else value)
    _set_addresses(contact, payload.addresses)
    db.commit()
    db.refresh(contact)
    return contact


def update_contact(db: Session, contact: Contact, payload: ContactUpdate) -> Contact:
    data = payload.model_dump(exclude_unset=True, exclude={"addresses"})
    for field, value in data.items():
        setattr(contact, field, _normalize_email(value) if field == "email" else value)
    if "addresses" in payload.model_fields_set:
        _set_addresses(contact, payload.addresses or [])
    db.commit()
    db.refresh(contact)
    return contact


def delete_contact(db: Session, contact: Contact) -> None:
    db.delete(contact)
    db.commit()
