import base64

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import Address
from app.photo import MAX_PHOTO_BYTES

BASE = "/api/v1/contacts"

TINY_PNG_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "sqlite"


def test_create_contact(client, payload):
    response = client.post(BASE, json=payload)
    assert response.status_code == 201
    body = response.json()
    assert body["id"] > 0
    assert body["email"] == "ada@example.com"
    assert body["full_name"] == "Ada Lovelace"
    assert body["created_at"] and body["updated_at"]


def test_create_requires_valid_email(client, payload):
    response = client.post(BASE, json={**payload, "email": "not-an-email"})
    assert response.status_code == 422


def test_create_requires_names(client, payload):
    response = client.post(BASE, json={**payload, "first_name": ""})
    assert response.status_code == 422


def test_duplicate_email_conflicts(client, payload):
    assert client.post(BASE, json=payload).status_code == 201
    response = client.post(BASE, json={**payload, "email": "ADA@example.com"})
    assert response.status_code == 409


def test_get_contact(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]
    response = client.get(f"{BASE}/{contact_id}")
    assert response.status_code == 200
    assert response.json()["id"] == contact_id


def test_get_missing_contact_returns_404(client):
    assert client.get(f"{BASE}/9999").status_code == 404


def test_list_pagination_and_total(client, payload):
    for index in range(5):
        client.post(BASE, json={**payload, "email": f"user{index}@example.com"})

    response = client.get(BASE, params={"limit": 2, "offset": 2})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 5
    assert len(body["items"]) == 2
    assert body["limit"] == 2 and body["offset"] == 2


def test_list_search(client, payload):
    client.post(BASE, json=payload)
    client.post(
        BASE,
        json={**payload, "first_name": "Grace", "last_name": "Hopper", "email": "grace@example.com", "company": "US Navy"},
    )

    hits = client.get(BASE, params={"search": "hopper"}).json()
    assert hits["total"] == 1
    assert hits["items"][0]["last_name"] == "Hopper"

    by_company = client.get(BASE, params={"search": "navy"}).json()
    assert by_company["total"] == 1

    misses = client.get(BASE, params={"search": "nobody"}).json()
    assert misses["total"] == 0


def test_list_sorting(client, payload):
    client.post(BASE, json={**payload, "last_name": "Zhang", "email": "z@example.com"})
    client.post(BASE, json={**payload, "last_name": "Adams", "email": "a@example.com"})

    names = [
        item["last_name"]
        for item in client.get(BASE, params={"sort_by": "last_name", "order": "asc"}).json()["items"]
    ]
    assert names == ["Adams", "Zhang"]


def test_list_rejects_bad_sort_field(client):
    assert client.get(BASE, params={"sort_by": "; DROP TABLE contacts"}).status_code == 422


def test_patch_updates_only_sent_fields(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]
    response = client.patch(f"{BASE}/{contact_id}", json={"phone": "+1-000-000-0000"})
    assert response.status_code == 200
    body = response.json()
    assert body["phone"] == "+1-000-000-0000"
    assert body["first_name"] == "Ada"
    assert body["company"] == "Analytical Engines"


def test_patch_duplicate_email_conflicts(client, payload):
    first = client.post(BASE, json=payload).json()["id"]
    client.post(BASE, json={**payload, "email": "grace@example.com"})
    response = client.patch(f"{BASE}/{first}", json={"email": "grace@example.com"})
    assert response.status_code == 409


def test_patch_same_email_is_allowed(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]
    response = client.patch(f"{BASE}/{contact_id}", json={"email": payload["email"]})
    assert response.status_code == 200


def test_put_replaces_contact(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]
    response = client.put(
        f"{BASE}/{contact_id}",
        json={"first_name": "Grace", "last_name": "Hopper", "email": "grace@example.com"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["full_name"] == "Grace Hopper"
    assert body["company"] is None  # omitted fields are cleared by PUT
    assert body["addresses"] == []


def test_put_missing_contact_returns_404(client):
    response = client.put(
        f"{BASE}/9999",
        json={"first_name": "A", "last_name": "B", "email": "ab@example.com"},
    )
    assert response.status_code == 404


def test_delete_contact(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]
    assert client.delete(f"{BASE}/{contact_id}").status_code == 204
    assert client.get(f"{BASE}/{contact_id}").status_code == 404
    assert client.delete(f"{BASE}/{contact_id}").status_code == 404


def test_root_lists_entrypoints(client):
    body = client.get("/").json()
    assert body["contacts"] == BASE


def test_create_contact_without_photo_returns_null(client, payload):
    body = client.post(BASE, json=payload).json()
    assert body["photo"] is None


def test_create_contact_with_photo(client, payload):
    response = client.post(BASE, json={**payload, "photo": TINY_PNG_DATA_URL})
    assert response.status_code == 201
    assert response.json()["photo"] == TINY_PNG_DATA_URL


def test_jpg_alias_is_stored_as_jpeg(client, payload):
    raw = base64.b64encode(b"\xff\xd8\xff" + b"\x00" * 16).decode()
    response = client.post(BASE, json={**payload, "photo": f"data:image/jpg;base64,{raw}"})
    assert response.status_code == 201
    assert response.json()["photo"] == f"data:image/jpeg;base64,{raw}"


def test_create_rejects_non_image_photo(client, payload):
    response = client.post(BASE, json={**payload, "photo": "https://example.com/ada.png"})
    assert response.status_code == 422


def test_create_rejects_svg_photo(client, payload):
    response = client.post(
        BASE,
        json={**payload, "photo": "data:image/svg+xml;base64,PHN2Zy8+"},
    )
    assert response.status_code == 422


def test_create_rejects_oversized_photo(client, payload):
    png_prefix = b"\x89PNG\r\n\x1a\n"
    blob = base64.b64encode(png_prefix + b"\x00" * (MAX_PHOTO_BYTES + 1 - len(png_prefix))).decode()
    response = client.post(BASE, json={**payload, "photo": f"data:image/png;base64,{blob}"})
    assert response.status_code == 422


def test_create_rejects_non_image_bytes_labeled_as_png(client, payload):
    blob = base64.b64encode(b"Hello").decode()
    response = client.post(BASE, json={**payload, "photo": f"data:image/png;base64,{blob}"})
    assert response.status_code == 422


def test_create_rejects_jpeg_bytes_labeled_as_png(client, payload):
    blob = base64.b64encode(b"\xff\xd8\xff" + b"\x00" * 16).decode()
    response = client.post(BASE, json={**payload, "photo": f"data:image/png;base64,{blob}"})
    assert response.status_code == 422


def test_put_without_photo_clears_it(client, payload):
    contact_id = client.post(BASE, json={**payload, "photo": TINY_PNG_DATA_URL}).json()["id"]
    response = client.put(
        f"{BASE}/{contact_id}",
        json={"first_name": "Ada", "last_name": "Lovelace", "email": "ada@example.com"},
    )
    assert response.status_code == 200
    assert response.json()["photo"] is None


def test_put_with_photo_keeps_it(client, payload):
    contact_id = client.post(BASE, json={**payload, "photo": TINY_PNG_DATA_URL}).json()["id"]
    response = client.put(
        f"{BASE}/{contact_id}",
        json={
            "first_name": "Ada",
            "last_name": "Lovelace",
            "email": "ada@example.com",
            "photo": TINY_PNG_DATA_URL,
        },
    )
    assert response.status_code == 200
    assert response.json()["photo"] == TINY_PNG_DATA_URL


def test_patch_sets_and_clears_photo(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]
    set_response = client.patch(f"{BASE}/{contact_id}", json={"photo": TINY_PNG_DATA_URL})
    assert set_response.status_code == 200
    assert set_response.json()["photo"] == TINY_PNG_DATA_URL

    clear_response = client.patch(f"{BASE}/{contact_id}", json={"photo": None})
    assert clear_response.status_code == 200
    assert clear_response.json()["photo"] is None


def test_init_db_adds_photo_column_to_existing_table(client):
    from sqlalchemy import inspect, text

    from app.database import engine, init_db

    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS addresses"))
        connection.execute(text("DROP TABLE contacts"))
        connection.execute(
            text(
                "CREATE TABLE contacts ("
                "id INTEGER PRIMARY KEY, "
                "first_name VARCHAR(100) NOT NULL, "
                "last_name VARCHAR(100) NOT NULL, "
                "email VARCHAR(320) NOT NULL"
                ")"
            )
        )

    assert "photo" not in {
        column["name"] for column in inspect(engine).get_columns("contacts")
    }

    init_db()
    init_db()  # idempotent when the column is already present

    inspector = inspect(engine)
    inspector.clear_cache()
    columns = {column["name"] for column in inspector.get_columns("contacts")}
    assert "photo" in columns
    assert client.get("/health").status_code == 200


def test_create_contact_stores_multiple_addresses(client, payload):
    work = {
        "type": "work",
        "address": "1 Market St, Suite 400",
        "city": "San Francisco",
        "state": "CA",
        "postal_code": "94105",
        "country": "USA",
    }
    response = client.post(BASE, json={**payload, "addresses": [payload["addresses"][0], work]})
    assert response.status_code == 201
    addresses = response.json()["addresses"]
    assert [row["type"] for row in addresses] == ["home", "work"]
    assert addresses[0]["city"] == "San Francisco"
    assert addresses[1]["address"] == work["address"]
    assert all(row["id"] > 0 for row in addresses)


def test_create_rejects_unknown_address_type(client, payload):
    response = client.post(
        BASE,
        json={**payload, "addresses": [{"type": "vacation", "city": "Tahoe"}]},
    )
    assert response.status_code == 422


def test_create_rejects_too_many_addresses(client, payload):
    too_many = [{"type": "other", "city": f"City {index}"} for index in range(21)]
    response = client.post(BASE, json={**payload, "addresses": too_many})
    assert response.status_code == 422


def test_patch_omitting_addresses_keeps_them(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]
    response = client.patch(f"{BASE}/{contact_id}", json={"phone": "+1-000-000-0000"})
    assert response.status_code == 200
    addresses = response.json()["addresses"]
    assert len(addresses) == 1
    assert addresses[0]["type"] == "home"
    assert addresses[0]["city"] == "San Francisco"


def test_patch_empty_addresses_clears_them(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]
    response = client.patch(f"{BASE}/{contact_id}", json={"addresses": []})
    assert response.status_code == 200
    assert response.json()["addresses"] == []


def test_put_replaces_addresses(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]
    response = client.put(
        f"{BASE}/{contact_id}",
        json={
            "first_name": "Ada",
            "last_name": "Lovelace",
            "email": "ada@example.com",
            "addresses": [
                {"type": "work", "city": "London", "country": "UK"},
                {"type": "other", "address": "Hut 8", "city": "Bletchley"},
            ],
        },
    )
    assert response.status_code == 200
    addresses = response.json()["addresses"]
    assert [row["type"] for row in addresses] == ["work", "other"]
    assert addresses[0]["city"] == "London"


def test_delete_contact_cascades_addresses(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]
    with SessionLocal() as db:
        assert db.execute(select(func.count()).select_from(Address)).scalar_one() == 1

    assert client.delete(f"{BASE}/{contact_id}").status_code == 204

    with SessionLocal() as db:
        assert db.execute(select(func.count()).select_from(Address)).scalar_one() == 0
