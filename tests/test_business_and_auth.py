"""Business acceptance and access-control tests; never touch the local customer DB."""

import importlib
import csv
import io
from datetime import date, timedelta
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def backend(tmp_path, monkeypatch):
    monkeypatch.setenv("RADAR_DATA_DIR", str(tmp_path))
    module = importlib.import_module("backend.app")
    monkeypatch.setattr(module, "DB_PATH", tmp_path / "test.sqlite3")
    monkeypatch.setattr(module, "config_value", lambda name: __import__("os").environ.get(name))
    monkeypatch.delenv("RADAR_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT_ID", raising=False)
    monkeypatch.delenv("RADAR_REQUIRE_AUTH", raising=False)
    module._LOGIN_ATTEMPTS.clear()
    module.init_db()
    return module


@pytest.fixture
def client(backend):
    with TestClient(backend.app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as current:
        yield current


def campaign(client):
    response = client.post("/api/campaigns", json={
        "name": "Test comercial", "start_date": "2026-11-16", "end_date": "2026-11-30",
    })
    assert response.status_code == 201
    return response.json()["id"]


def test_demo_is_coherent_and_never_invokes_scraping(client, backend, monkeypatch):
    def prohibit_scraping(*args, **kwargs):
        raise AssertionError("demo attempted network capture")

    monkeypatch.setattr(backend, "run_campaign_job", prohibit_scraping)
    result = client.post("/api/demo")
    assert result.status_code == 201
    demo = result.json()
    assert demo["is_demo"] == 1
    assert len(demo["products"]) == 50
    assert demo["summary"]["compliant"] > 0
    assert demo["summary"]["non_compliant"] > 0
    assert demo["summary"]["evidence_official"] == 0
    assert all(product["evidence_source"] == "demo" for product in demo["products"])
    assert all(product["screenshot_url"] is None for product in demo["products"])
    assert client.post("/api/demo").json()["id"] == demo["id"]
    for product in demo["products"]:
        history = client.get(f"/api/campaigns/{demo['id']}/price-history", params={"sku": product["sku"], "retailer": product["retailer"]}).json()
        assert len(history["observations"]) == 7
        assert history["observations"][0]["price"] == product["detected_price"]
        for observation in history["observations"]:
            expected = "compliant" if observation["price"] <= product["promo_price"] else "non_compliant"
            assert observation["status"] == expected
    before = demo["summary"]
    assert client.post(f"/api/campaigns/{demo['id']}/run", json={}).json()["summary"] == before
    intelligence = client.get(f"/api/campaigns/{demo['id']}/intelligence").json()
    assert intelligence["stock_risk"]["critical"] > 0
    assert intelligence["actions"][0]["priority"] == "critical"
    brief = client.get(f"/api/campaigns/{demo['id']}/brief").json()
    assert brief["is_demo"] is True
    assert brief["metrics"]["comparable_groups"] == 10
    assert brief["findings"]


def test_inventory_uses_safety_buffer_but_actual_stockout_date(backend):
    row = backend.inventory_row({"sku": "A", "stock": "30", "ventas_30d": "60", "lead_time": "14", "stock_seguridad": "10"})
    assert row["daily_sales"] == 2
    assert row["coverage_days"] == 10
    assert row["risk"] == "critical"
    assert row["stockout_date"] == (date.today() + timedelta(days=15)).isoformat()


@pytest.mark.parametrize("bad_value", ["-5", "desconocido", "10unidades", "NaN", "1e999"])
def test_invalid_inventory_never_creates_a_false_healthy_result(backend, bad_value):
    row = backend.inventory_row({"sku": "A", "stock": bad_value, "ventas_30d": "20", "lead_time": "3"})
    assert row["risk"] == "insufficient"
    assert row["stockout_date"] is None


def test_inventory_missing_and_zero_sales_are_distinct(backend):
    missing = backend.inventory_row({"sku": "A", "stock": "50", "lead_time": "5"})
    idle = backend.inventory_row({"sku": "A", "stock": "50", "lead_time": "5", "ventas_30d": "0"})
    empty = backend.inventory_row({"sku": "A", "stock": "0", "lead_time": "5", "ventas_30d": "0"})
    assert missing["risk"] == "insufficient"
    assert idle["risk"] == "low" and idle["stockout_date"] is None
    assert empty["risk"] == "critical" and empty["stockout_date"] == date.today().isoformat()


def test_inventory_import_persists_and_flags_missing_fields(client):
    campaign_id = campaign(client)
    content = b"sku,retailer,stock,ventas_30d,lead_time\nA,Paris,20,90,14\nB,Ripley,30,,\n"
    response = client.post(f"/api/campaigns/{campaign_id}/inventory/import", files={"file": ("stock.csv", content, "text/csv")})
    assert response.status_code == 200
    assert response.json()["imported"] == 2
    data = client.get(f"/api/campaigns/{campaign_id}/inventory").json()
    assert data["summary"]["critical"] == 1
    assert data["summary"]["insufficient"] == 1


def test_comparables_require_explicit_group_and_compare_latest_by_retailer(client):
    campaign_id = campaign(client)
    content = (
        "grupo_comparable,sku,retailer,precio,fecha\n"
        "G,A,Paris,100,2026-11-01\nG,A,Paris,120,2026-11-16\n"
        "G,B,Ripley,150,2026-11-16\n,H,Falabella,10,2026-11-16\n"
        "G,X,,200,2026-11-16\nG,Q,ABC,200,not-a-date\n"
    ).encode()
    response = client.post(f"/api/campaigns/{campaign_id}/comparables/import", files={"file": ("comp.csv", content, "text/csv")})
    assert response.status_code == 200
    data = response.json()
    assert data["imported"] == 3 and data["skipped"] == 3
    assert data["count"] == 2 and data["history_count"] == 3
    group = data["groups"][0]
    assert group["gap"] == 30
    assert group["gap_percent"] == 25
    assert len(group["history"]) == 3


def test_single_retailer_has_no_competitive_gap_and_missing_inputs_are_visible(client):
    campaign_id = campaign(client)
    content = b"grupo_comparable,sku,retailer,precio\nG,A,Paris,120\nG,B,Paris,150\n"
    response = client.post(f"/api/campaigns/{campaign_id}/comparables/import", files={"file": ("comp.csv", content, "text/csv")})
    group = response.json()["groups"][0]
    assert group["gap"] is None and group["gap_percent"] is None
    assert group["comparable"] is False
    intelligence = client.get(f"/api/campaigns/{campaign_id}/intelligence").json()
    assert intelligence["compliance_percent"] is None
    assert any("Completar datos" in action["title"] for action in intelligence["actions"])
    brief = client.get(f"/api/campaigns/{campaign_id}/brief").json()
    assert "sin datos evaluables" in brief["executive_summary"]


def test_auth_is_fail_closed_remotely_and_health_is_public(backend):
    with TestClient(backend.app, base_url="https://retail.example") as remote:
        assert remote.get("/api/campaigns").status_code == 503
        assert remote.get("/screenshots/example.png").status_code == 503
        assert remote.get("/openapi.json").status_code == 503
        assert remote.get("/api/auth/session").json()["authenticated"] is False
        assert remote.get("/api/health").json() == {"status": "ok", "browser_available": True}


def test_auth_cookie_login_tampering_logout_and_rotation(backend, monkeypatch):
    monkeypatch.setenv("RADAR_ACCESS_TOKEN", "test-only-access-key")
    with TestClient(backend.app, base_url="https://retail.example") as remote:
        assert remote.get("/api/campaigns").status_code == 401
        assert remote.post("/api/auth/login", json={"token": "bad"}).status_code == 401
        login = remote.post("/api/auth/login", json={"token": "test-only-access-key"})
        assert login.status_code == 200
        assert "HttpOnly" in login.headers["set-cookie"]
        assert "Secure" in login.headers["set-cookie"]
        assert "SameSite=lax" in login.headers["set-cookie"]
        assert remote.get("/api/campaigns").status_code == 200
        cookie = remote.cookies.get(backend.SESSION_COOKIE)
        assert backend.valid_session(cookie, "test-only-access-key")
        assert not backend.valid_session(cookie + "x", "test-only-access-key")
        monkeypatch.setenv("RADAR_ACCESS_TOKEN", "rotated-key")
        assert remote.get("/api/campaigns").status_code == 401
        monkeypatch.setenv("RADAR_ACCESS_TOKEN", "test-only-access-key")
        assert remote.post("/api/auth/logout").status_code == 200
        assert remote.get("/api/campaigns").status_code == 401


def test_login_throttles_failures(backend, monkeypatch):
    monkeypatch.setenv("RADAR_ACCESS_TOKEN", "test-key")
    with TestClient(backend.app, base_url="https://retail.example") as remote:
        for _ in range(5):
            assert remote.post("/api/auth/login", json={"token": "wrong"}).status_code == 401
        assert remote.post("/api/auth/login", json={"token": "test-key"}).status_code == 429


def test_cross_site_mutations_are_rejected_even_with_a_valid_cookie(backend, monkeypatch):
    monkeypatch.setenv("RADAR_ACCESS_TOKEN", "test-key")
    with TestClient(backend.app, base_url="https://retail.example") as remote:
        assert remote.post("/api/auth/login", json={"token": "test-key"}).status_code == 200
        assert remote.post("/api/demo", headers={"origin": "https://unrelated.example"}).status_code == 403


def test_evidence_exports_preserve_source_and_never_label_structured_or_demo_official(client, backend, tmp_path, monkeypatch):
    campaign_id = campaign(client)
    source_file = b"sku,retailer,url\nA,Paris,\nB,Ripley,\nC,Falabella,\nD,ABC,\n"
    assert client.post(f"/api/campaigns/{campaign_id}/import", files={"file": ("products.csv", source_file, "text/csv")}).status_code == 200
    monkeypatch.setattr(backend, "SCREENSHOTS_DIR", tmp_path)
    sources = {"A": "retailer", "B": "retailer_structured", "C": "google_reference", "D": "demo"}
    with backend.db() as connection:
        for sku, source in sources.items():
            filename = f"{sku}.png"
            backend.Image.new("RGB", (30, 30), "white").save(tmp_path / filename)
            connection.execute("UPDATE products SET screenshot_url = ?, evidence_source = ? WHERE campaign_id = ? AND sku = ?", (f"/screenshots/{filename}", source, campaign_id, sku))
    report = client.get(f"/api/campaigns/{campaign_id}/report.csv")
    rows = {row["SKU"]: row for row in csv.DictReader(io.StringIO(report.content.decode("utf-8-sig")), delimiter=";")}
    assert rows["A"]["Evidencia oficial"] == "/screenshots/A.png"
    assert rows["B"]["Evidencia oficial"] == ""
    assert rows["B"]["Evidencia indirecta"] == "/screenshots/B.png"
    assert rows["C"]["Evidencia oficial"] == ""
    assert rows["C"]["Evidencia Google"] == "/screenshots/C.png"
    assert rows["D"]["Evidencia oficial"] == ""
    result = client.get(f"/api/campaigns/{campaign_id}/evidence.zip")
    with ZipFile(io.BytesIO(result.content)) as archive:
        names = archive.namelist()
        assert len([name for name in names if name.endswith(".png")]) == 3
        assert any(name.startswith("evidencias/") and name.endswith("-a-oficial.png") for name in names)
        assert any(name.startswith("evidencias-indirectas/") and name.endswith("-b-datos-estructurados.png") for name in names)
        assert any(name.startswith("evidencias-indirectas/") and name.endswith("-c-referencia-google.png") for name in names)
        assert not any("-b-oficial" in name or "-d-oficial" in name for name in names)


@pytest.mark.parametrize("confidence,expected", [("low", "baja"), ("medium", "media")])
def test_derived_evidence_always_renders_visible_source_disclaimer(backend, tmp_path, monkeypatch, confidence, expected):
    from datetime import datetime

    # An old environment override must never hide the source disclosure.
    monkeypatch.setenv("RADAR_EVIDENCE_DISCLAIMER", "internal")
    texts = []
    original = backend.ImageDraw.ImageDraw.text

    def capture_text(self, xy, text, *args, **kwargs):
        texts.append(text)
        return original(self, xy, text, *args, **kwargs)

    monkeypatch.setattr(backend.ImageDraw.ImageDraw, "text", capture_text)
    path = tmp_path / f"card-{confidence}.png"
    backend.render_indirect_evidence_card(
        path, retailer="ripley_cl", sku="123", product_url="https://simple.ripley.cl/product",
        google_price=109990, search_url="https://simple.ripley.cl/product",
        captured_at=datetime.now().astimezone(), note="Origen verificable en datos públicos.",
        source_label="datos estructurados públicos de Ripley" if confidence == "medium" else "referencia pública de Google",
        confidence=confidence,
    )
    assert path.exists()
    assert any(f"confianza {expected}" in text and "no es pantallazo oficial" in text for text in texts)
    assert any("Fuente de precio:" in text for text in texts)
