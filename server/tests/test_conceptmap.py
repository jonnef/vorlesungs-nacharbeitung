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
