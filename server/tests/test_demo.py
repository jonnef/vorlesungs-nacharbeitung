import pytest
from fastapi.testclient import TestClient

from app import main


@pytest.fixture
def demo_client(fake_client, monkeypatch):
    main.service._client = fake_client
    monkeypatch.setattr(main.settings, "demo_mode", True)
    monkeypatch.setitem(main.templates.env.globals, "demo", True)
    with main.service.db.connect() as conn:
        for table in ("usage_log", "glossary_entries", "jobs", "lectures", "pages", "scripts", "modules"):
            conn.execute(f"DELETE FROM {table}")
    with TestClient(main.app) as c:  # Start füllt die leere Datenbank mit Beispieldaten
        yield c


def test_preview_shows_sample_data(demo_client):
    home = demo_client.get("/").text
    assert "Vorschau mit Beispieldaten" in home and "Beispiel: Lineare Algebra" in home
    assert 'action="/modules"' not in home  # kein Formular zum Anlegen
    module = demo_client.get("/modules/1").text
    assert "VL01 Vektorräume und Basen" in module and "PDFs hochladen" not in module
    lecture = demo_client.get("/lectures/1").text
    assert 'class="card notes"' in lecture and "Neu erstellen" not in lecture and "Input-Tokens" not in lecture
    glossary = demo_client.get("/modules/1/glossar").text
    assert "Eigenwert" in glossary and "Charakteristisches Polynom" in glossary
    # „Basis“ kommt in beiden Vorlesungen vor und wird zusammengeführt
    assert len(main.service.module_glossary(1)) == 7


def test_preview_is_read_only(demo_client, fake_client):
    assert demo_client.post("/modules", data={"name": "X"}).status_code == 403
    assert demo_client.post("/lectures/1/jobs").status_code == 403
    assert demo_client.get("/api/lectures/1", headers={"Authorization": "Bearer test-token"}).status_code == 404
    assert demo_client.post("/api/modules/X/lectures", json={}).status_code == 404
    assert fake_client.counted == [] and fake_client.messages.batches.created == []
    with main.service.db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM modules").fetchone()[0] == 1
