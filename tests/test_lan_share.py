from datetime import timedelta

from app.lan import _is_usable, _rank, lan_ipv4_addresses
from app.qr import qr_svg
from app.shares import create_share, get_share
from app.vcard import contact_to_vcard

BASE = "/api/v1/contacts"
TINY_PNG_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def test_loopback_and_link_local_are_not_lan_addresses():
    assert not _is_usable("127.0.0.1")
    assert not _is_usable("169.254.12.34")
    assert _is_usable("192.168.1.42")
    assert _is_usable("10.0.0.8")


def test_wifi_ranges_rank_ahead_of_other_ipv4():
    assert _rank("192.168.0.15") < _rank("10.1.2.3") < _rank("8.8.8.8")


def test_lan_status_shape(client):
    response = client.get("/api/v1/lan")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["addresses"], list)
    assert all(isinstance(ip, str) for ip in body["addresses"])
    assert body["bind_port"] == 8000
    assert "bind_host" in body
    for ip in body["addresses"]:
        assert _is_usable(ip)
    assert body["addresses"] == lan_ipv4_addresses()


def test_qr_returns_svg(client):
    response = client.get("/api/v1/qr", params={"data": "http://192.168.1.42:3000/contacts/"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")
    assert "<svg" in response.text
    assert qr_svg("http://192.168.1.42:3000/contacts/").startswith("<svg")


def test_qr_rejects_blank(client):
    assert client.get("/api/v1/qr", params={"data": "   "}).status_code == 422


def test_share_unknown_contact_is_404(client):
    assert client.post(f"{BASE}/9999/share").status_code == 404


def test_share_round_trip(client, payload):
    created = client.post(BASE, json=payload).json()
    response = client.post(f"{BASE}/{created['id']}/share")
    assert response.status_code == 201
    body = response.json()
    assert body["contact_id"] == created["id"]
    assert body["token"]
    assert body["expires_at"]

    shared = client.get(f"/api/v1/shares/{body['token']}")
    assert shared.status_code == 200
    snapshot = shared.json()
    assert snapshot["email"] == "ada@example.com"
    assert snapshot["full_name"] == "Ada Lovelace"
    assert snapshot["addresses"][0]["city"] == "San Francisco"


def test_share_is_a_snapshot_not_a_live_read(client, payload):
    created = client.post(BASE, json=payload).json()
    token = client.post(f"{BASE}/{created['id']}/share").json()["token"]

    client.patch(f"{BASE}/{created['id']}", json={"first_name": "Augusta"})

    shared = client.get(f"/api/v1/shares/{token}").json()
    assert shared["first_name"] == "Ada"
    live = client.get(f"{BASE}/{created['id']}").json()
    assert live["first_name"] == "Augusta"


def test_missing_and_expired_shares_are_404(client, payload):
    assert client.get("/api/v1/shares/does-not-exist").status_code == 404

    created = client.post(BASE, json=payload).json()
    snapshot = {
        "id": created["id"],
        "first_name": "Ada",
        "last_name": "Lovelace",
        "email": "ada@example.com",
        "full_name": "Ada Lovelace",
    }
    expired = create_share(snapshot, ttl=timedelta(seconds=-1))
    assert get_share(expired.token) is None
    assert client.get(f"/api/v1/shares/{expired.token}").status_code == 404


def test_contact_vcard_download(client, payload):
    created = client.post(BASE, json={**payload, "photo": TINY_PNG_DATA_URL}).json()
    response = client.get(f"{BASE}/{created['id']}/vcard")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/vcard")
    assert "Ada_Lovelace.vcf" in response.headers.get("content-disposition", "")
    text = response.text
    assert "BEGIN:VCARD" in text
    assert "FN:Ada Lovelace" in text
    assert "EMAIL;TYPE=INTERNET:ada@example.com" in text
    assert "TEL;TYPE=CELL:+1-415-555-0101" in text
    assert "ORG:Analytical Engines" in text
    assert "ADR;TYPE=HOME:" in text
    assert "San Francisco" in text
    assert "PHOTO;ENCODING=b;TYPE=PNG:" in text


def test_share_vcard_uses_the_snapshot(client, payload):
    created = client.post(BASE, json=payload).json()
    token = client.post(f"{BASE}/{created['id']}/share").json()["token"]
    response = client.get(f"/api/v1/shares/{token}/vcard")
    assert response.status_code == 200
    assert "FN:Ada Lovelace" in response.text


def test_vcard_escapes_specials_and_skips_empty_address():
    card = contact_to_vcard(
        {
            "first_name": "Ann;a",
            "last_name": "O'Neil",
            "full_name": "Ann;a O'Neil",
            "email": "ann@example.com",
            "notes": "line1\nline2",
            "addresses": [{"type": "home"}],
        }
    )
    assert "N:O'Neil;Ann\\;a;;;" in card
    assert "NOTE:line1\\nline2" in card
    assert "ADR;" not in card
