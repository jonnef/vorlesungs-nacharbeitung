import pytest
from fastapi.testclient import TestClient

from app import main

from .conftest import SEGMENTS

AUTH = {"Authorization": "Bearer test-token"}


@pytest.fixture
def client(fake_client):
    main.service._client = fake_client
    main.settings.monthly_budget_usd = 5.0
    with main.service.db.connect() as conn:
        for table in ("usage_log", "jobs", "lectures", "pages", "scripts", "modules"):
            conn.execute(f"DELETE FROM {table}")
    with TestClient(main.app) as c:
        yield c


def _post_lecture(client, name="VL01.mp4"):
    return client.post("/api/modules/Lineare Algebra/lectures", headers=AUTH, json={
        "title": "VL 01", "source_filename": name, "duration_sec": 3600, "segments": SEGMENTS})


def test_api_requires_token(client):
    assert client.get("/api/lectures/1").status_code == 401


def test_full_flow(client, fake_client, sample_pdf):
    with sample_pdf.open("rb") as f:
        r = client.post("/api/modules/Lineare Algebra/scripts", headers=AUTH,
                        files={"file": ("Skript.pdf", f, "application/pdf")})
    assert r.json()["created"] is True
    with sample_pdf.open("rb") as f:  # gleiches PDF nochmal → kein Duplikat
        r = client.post("/api/modules/Lineare Algebra/scripts", headers=AUTH,
                        files={"file": ("Skript.pdf", f, "application/pdf")})
    assert r.json()["created"] is False

    r = _post_lecture(client)
    assert r.status_code == 200, r.text
    lecture_id = r.json()["lecture_id"]
    # Token-Zählung mit denselben Parametern wie der Job, inkl. Skriptseiten
    assert "Eigenwerte" in fake_client.counted[0]["messages"][0]["content"]
    assert client.get(f"/api/lectures/{lecture_id}", headers=AUTH).json()["status"] == "submitted"

    fake_client.finished = True
    main.service.poll_jobs()
    info = client.get(f"/api/lectures/{lecture_id}", headers=AUTH).json()
    assert info["status"] == "done"
    assert info["notes_md"].startswith("# Notizen")
    assert len(info["warnings"]) == 2  # Zeitstempel hinter Videoende + unbekannte Seite
    assert main.service.month_spent_usd() == pytest.approx((10_000 * 5 + 4_000 * 25) / 1e6 * 0.5)

    for url in ["/", "/modules/1", f"/lectures/{lecture_id}", "/kosten"]:
        page = client.get(url)
        assert page.status_code == 200, url
    assert 'class="ts"' in client.get(f"/lectures/{lecture_id}").text


def test_budget_blocks_job(client):
    main.settings.monthly_budget_usd = 0.01
    lecture_id = _post_lecture(client).json()["lecture_id"]
    job = main.service.latest_job(lecture_id)
    assert job["status"] == "blocked"
    assert "Monatsbudget" in job["error"]
    assert "Budget reicht nicht" in client.get(f"/lectures/{lecture_id}").text
