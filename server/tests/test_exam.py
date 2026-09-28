from app import exam, main

from .conftest import SEGMENTS
from .test_api import AUTH, _post_lecture, client  # noqa: F401  (Fixture)


def _finish_all(fake_client):
    fake_client.finished = True
    main.service.poll_jobs()          # Notizen
    main.service.ensure_glossary_jobs()
    main.service.ensure_exam_jobs()   # Klausurvorbereitung anlegen
    main.service.poll_jobs()          # Glossar + Klausurvorbereitung fertig


def _exam_jobs():
    with main.service.db.connect() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM jobs WHERE kind = 'exam' ORDER BY id")]


def test_hint_excerpts_and_request():
    excerpts = exam.hint_excerpts(SEGMENTS)
    assert excerpts == ["[00:00:40] Das kommt garantiert in der Klausur."]
    params = exam.build_request(model="claude-opus-5", effort="high", max_tokens=100, module="LA",
                                lectures=[{"title": "VL 01", "notes": "# N", "segments": SEGMENTS}])
    content = params["messages"][0]["content"]
    assert 'kuerzel="V1"' in content and "# N" in content and "garantiert in der Klausur" in content
    assert "Klausurvorbereitung" in params["system"]


def test_validate_and_links():
    lectures = [{"title": "VL 01", "duration_sec": 3600}]
    warnings = exam.validate("[V1 00:10:00] [V2 00:01:00] [V1 02:00:00]", lectures)
    assert len(warnings) == 2
    html = exam.link_citations("<p>[V1 00:10:00] [V7 00:00:01]</p>", [42], "/vorlesungen")
    assert '<a class="ts" href="/vorlesungen/lectures/42">[V1 00:10:00]</a>' in html
    assert '<span class="ts">[V7 00:00:01]</span>' in html
    assert exam.legend([{"title": "A"}, {"title": "B"}]) == "> **Vorlesungen:** V1 = A · V2 = B"


def test_exam_grows_with_lectures(client, fake_client):
    first = _post_lecture(client, "VL01.mp4").json()["lecture_id"]
    _finish_all(fake_client)
    [job] = _exam_jobs()
    assert job["status"] == "done"
    data = main.service.module_exam(1)
    assert data["markdown"].startswith("# Klausurvorbereitung") and [l["id"] for l in data["lectures"]] == [first]
    assert len(data["warnings"]) == 2  # unbekannte Vorlesung V9 + Zeitstempel hinter dem Ende

    # Nichts Neues → keine neue Fassung
    main.service.ensure_exam_jobs()
    assert len(_exam_jobs()) == 1

    # Neue Vorlesung: solange ihre Notizen laufen, wird gewartet …
    fake_client.finished = False
    second = _post_lecture(client, "VL02.mp4").json()["lecture_id"]
    main.service.ensure_exam_jobs()
    assert len(_exam_jobs()) == 1
    # … danach entsteht eine neue Fassung aus beiden Vorlesungen
    _finish_all(fake_client)
    jobs = _exam_jobs()
    assert len(jobs) == 2 and jobs[-1]["status"] == "done"
    assert [l["id"] for l in main.service.module_exam(1)["lectures"]] == [first, second]
    exam_request = fake_client.messages.batches.created[-1][0]["params"]["messages"][0]["content"]
    assert 'kuerzel="V1"' in exam_request and 'kuerzel="V2"' in exam_request

    # Weboberfläche, Download, API für den Watcher
    page = client.get("/modules/1/klausur").text
    assert f'href="/lectures/{first}">[V1 00:00:40]</a>' in page and "task-list-item-checkbox" in page
    assert "Klausurvorbereitung" in client.get("/modules/1").text
    md = client.get("/modules/1/klausur.md")
    assert md.headers["content-disposition"].startswith("attachment") and "V2 = VL 01" in md.text
    api = client.get("/api/modules/Lineare Algebra/exam", headers=AUTH).json()
    assert api["markdown"].startswith("> **Vorlesungen:** V1 = VL 01") and api["updated_at"]
    assert client.get("/api/modules/Unbekannt/exam", headers=AUTH).json()["markdown"] == ""

    # Manuell neu erstellen
    r = client.post("/modules/1/klausur", follow_redirects=False)
    assert r.status_code == 303 and len(_exam_jobs()) == 3
    assert "(Klausurvorbereitung)" in client.get("/kosten").text
