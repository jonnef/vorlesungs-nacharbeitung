from app import main

from .test_api import AUTH, _post_lecture, client  # noqa: F401  (Fixture)
from .test_exam import _exam_jobs, _finish_all


def _notes_jobs(lecture_id):
    with main.service.db.connect() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM jobs WHERE kind = 'notes' AND lecture_id = ? ORDER BY id", (lecture_id,))]


def test_regenerate_module_keeps_old_notes_until_new_ones_are_done(client, fake_client):
    first = _post_lecture(client, "VL01.mp4").json()["lecture_id"]
    second = _post_lecture(client, "VL02.mp4").json()["lecture_id"]
    _finish_all(fake_client)
    assert len(_exam_jobs()) == 1
    old = main.service.latest_notes(first)

    page = client.get("/modules/1/neu-erstellen")
    assert page.status_code == 200 and "2 Vorlesungen neu erstellen" in page.text and "Höchstens" in page.text

    fake_client.finished = False
    assert client.post("/modules/1/neu-erstellen", follow_redirects=False).status_code == 303
    assert len(_notes_jobs(first)) == 2 and len(_notes_jobs(second)) == 2

    # Während die neuen Fassungen laufen: bisherige Notizen sichtbar, nichts doppelt anlegen
    lecture = client.get(f"/lectures/{first}")
    assert "Eine neue Fassung dieser Notizen wird gerade erstellt" in lecture.text
    assert main.service.latest_notes(first)["id"] == old["id"]
    api = client.get(f"/api/lectures/{first}", headers=AUTH).json()
    assert api["status"] == "submitted" and api["notes_md"] == old["notes_md"] and api["notes_job_id"] == old["id"]
    assert main.service.regeneration_plan(1)["todo"] == []
    main.service.ensure_exam_jobs()
    assert len(_exam_jobs()) == 1  # Klausurvorbereitung wartet auf alle neuen Notizen

    # Fertig: neue Fassungen, Glossar/Hinweise neu, genau eine neue Klausurvorbereitung
    _finish_all(fake_client)
    new = main.service.latest_notes(first)
    assert new["id"] != old["id"]
    assert len(_exam_jobs()) == 2
    versions = client.get("/api/modules/Lineare Algebra/notes-versions", headers=AUTH).json()
    assert versions[str(first)] == new["id"]


def test_exam_waits_while_notes_wait_for_budget(client, fake_client):
    _post_lecture(client, "VL01.mp4")
    _finish_all(fake_client)
    assert len(_exam_jobs()) == 1
    second = _post_lecture(client, "VL02.mp4").json()["lecture_id"]
    main.service._set(_notes_jobs(second)[-1]["id"], status="blocked")
    main.service.ensure_exam_jobs()
    assert len(_exam_jobs()) == 1  # nicht ohne die blockierte Vorlesung neu erstellen


def test_slide_image_from_uploaded_pdf(client, sample_pdf):
    with sample_pdf.open("rb") as f:
        client.post("/api/modules/Lineare Algebra/scripts", headers=AUTH, files={"file": ("Skript.pdf", f)})
    r = client.get("/modules/1/folie/Skript/2.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.content[:4] == b"\x89PNG"
    assert client.get("/modules/1/folie/Skript/2.png").content == r.content  # aus dem Zwischenspeicher
    assert client.get("/modules/1/folie/Skript/99.png").status_code == 404
    assert client.get("/modules/1/folie/Gibtsnicht/1.png").status_code == 404
