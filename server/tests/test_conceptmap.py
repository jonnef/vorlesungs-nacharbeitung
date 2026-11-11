import json

from app import conceptmap, main

from .conftest import FakeClient
from .test_api import AUTH, _post_lecture, client  # noqa: F401  (Fixture)


def _finish(fake_client):
    fake_client.finished = True
    main.service.poll_jobs()              # Notizen
    main.service.ensure_glossary_jobs()
    main.service.ensure_conceptmap_jobs()  # Glossar läuft noch → noch keine Map
    main.service.poll_jobs()              # Glossar fertig
    main.service.ensure_conceptmap_jobs()
    main.service.poll_jobs()              # Concept Map fertig


def _maps():
    with main.service.db.connect() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM jobs WHERE kind = 'conceptmap' ORDER BY id")]


def test_parse_keeps_only_glossary_terms():
    data, warnings = conceptmap.parse(FakeClient().conceptmap_json, {"eigenwert", "ähnlichkeit"})
    assert {n["norm"] for n in data["nodes"]} == {"eigenwert", "ähnlichkeit"}
    # Begriff nur in einer Kante → Gruppe „Sonstiges“; Duplikat, Schleife und unbekannter Begriff fallen weg
    assert [n["group"] for n in data["nodes"] if n["norm"] == "ähnlichkeit"] == ["Sonstiges"]
    assert data["edges"] == [{"from": "ähnlichkeit", "to": "eigenwert", "kind": "verwendet", "label": "erhält die"}]
    assert warnings == ["Nicht im Glossar und daher weggelassen: Erfunden"]


def test_conceptmap_flow(client, fake_client):
    lecture = _post_lecture(client, "VL01.mp4").json()["lecture_id"]
    _finish(fake_client)
    [job] = _maps()
    assert job["status"] == "done" and json.loads(job["source_ids"])[0][0] == lecture
    request = json.loads(job["request_json"])
    assert "- Eigenwert (Begriff; VL 01)" in request["messages"][0]["content"]

    # Unverändertes Glossar → keine neue Fassung
    main.service.ensure_conceptmap_jobs()
    assert len(_maps()) == 1

    data = main.service.module_conceptmap(1)
    assert [n["term"] for n in data["map"]["nodes"]] == ["Eigenwert", "Ähnlichkeit"]
    assert data["map"]["nodes"][0]["lectures"] == [lecture]
    page = client.get("/modules/1/concept-map")
    assert page.status_code == 200 and "cytoscape" in page.text and "erhält die → Eigenwert" in page.text
    assert "2 Begriffe, 1 Verbindungen" in client.get("/modules/1").text

    # Neue Vorlesung → neue Fassung, sobald ihr Glossar fertig ist
    _post_lecture(client, "VL02.mp4")
    _finish(fake_client)
    assert len(_maps()) == 2

    # Von Hand neu erstellen
    client.post("/modules/1/concept-map")
    assert len(_maps()) == 3


def test_retry_after_token_limit_once_limit_is_higher(client, fake_client):
    _post_lecture(client, "VL01.mp4")
    fake_client.finished = True
    main.service.poll_jobs()
    main.service.ensure_glossary_jobs()
    main.service.poll_jobs()
    old_limit = main.settings.conceptmap_max_tokens
    main.settings.conceptmap_max_tokens = 16000
    try:
        fake_client.stop_reason = "max_tokens"
        main.service.ensure_conceptmap_jobs()
        main.service.poll_jobs()
        [failed] = _maps()
        assert failed["status"] == "failed" and "Token-Deckel" in failed["error"]
        page = client.get("/modules/1/concept-map").text
        assert "Erneut versuchen" in page

        # Gleicher Deckel → kein automatischer neuer Versuch (keine laufenden Kosten)
        main.service.ensure_conceptmap_jobs()
        assert len(_maps()) == 1

        # Höherer Deckel → genau ein neuer Versuch, der klappt
        fake_client.stop_reason = "end_turn"
        main.settings.conceptmap_max_tokens = 32000
        main.service.ensure_conceptmap_jobs()
        main.service.poll_jobs()
        assert len(_maps()) == 2 and _maps()[-1]["status"] == "done"
        assert json.loads(_maps()[-1]["request_json"])["max_tokens"] == 32000
        main.service.ensure_conceptmap_jobs()
        assert len(_maps()) == 2
    finally:
        main.settings.conceptmap_max_tokens = old_limit
        fake_client.stop_reason = "end_turn"


def test_prompt_caps_terms():
    params = conceptmap.build_request(model="m", effort="medium", max_tokens=10, module="LA", groups=[], max_terms=42)
    assert "höchstens 42" in params["system"] and "{max_terms}" not in params["system"]
