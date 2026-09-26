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


def _bad_request(message: str):
    import anthropic
    import httpx2

    response = httpx2.Response(400, request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages/count_tokens"))
    body = {"type": "error", "error": {"type": "invalid_request_error", "message": message}}
    return anthropic.BadRequestError(message, response=response, body=body)


def test_count_tokens_retries_without_thinking(client, fake_client):
    original = fake_client.messages.count_tokens

    def strict_count(**params):
        if "thinking" in params:
            raise _bad_request("thinking: Extra inputs are not permitted")
        return original(**params)

    fake_client.messages.count_tokens = strict_count
    r = _post_lecture(client)
    assert r.status_code == 200, r.text
    assert main.service.latest_job(r.json()["lecture_id"])["status"] == "submitted"


def test_api_error_shows_reason(client, fake_client):
    def failing_count(**params):
        raise _bad_request("Your credit balance is too low to access the Anthropic API.")

    fake_client.messages.count_tokens = failing_count
    r = _post_lecture(client)
    assert r.status_code == 502
    assert "credit balance is too low" in r.json()["detail"]
    assert "HTTP 400 invalid_request_error" in r.json()["detail"]


def test_forwarded_prefix_for_caddy_subpath(client):
    headers = {"X-Forwarded-Prefix": "/vorlesungen"}
    page = client.get("/", headers=headers).text
    assert 'href="/vorlesungen/kosten"' in page and 'action="/vorlesungen/modules"' in page
    r = client.post("/modules", data={"name": "Analysis"}, headers=headers, follow_redirects=False)
    assert r.headers["location"].startswith("/vorlesungen/modules/")
    # Ohne Header (direkt über Port 8000) bleibt alles wie bisher
    assert 'href="/kosten"' in client.get("/").text
    # Manipulierte Header werden ignoriert
    evil = client.get("/", headers={"X-Forwarded-Prefix": '/x"><script>'}).text
    assert "<script>" not in evil and 'href="/kosten"' in evil
